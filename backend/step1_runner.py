# -*- coding: utf-8 -*-
"""step1 数据集生成四步编排：计划 → 生成 → 检查 → 评估。

与原项目 `_dataset_ext_execute_worker`（device.py:1289）流程同构：
  planner  LLM ×1       → domain_scenarios / parameter_space / constraint_templates / underspecification_plan
  generator LLM ×N 并行 → task_set（含欠指定变体）
  verifier  LLM ×N 并行 → verification_results（pass + 5 维评分）
  evaluator 程序化      → 5 项指标（信息熵/宽度/均衡度/深度/覆盖度）

提示词逐字取自 backend/prompts.py（原项目 dataset_ext_prompts.py）。
LLM 未配置或调用失败时降级为确定性 mock（backend/mockgen.py），并在日志中显式标注。
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import api_agent
import llm
import mockgen
import scene_matrix as sm
import store
from prompts import MD_G_AGENT_PROMPT, MD_P_AGENT_PROMPT, MD_V_AGENT_PROMPT

SCORE_DIMS = ["clarity", "completeness", "consistency", "feasibility", "constraint_coverage"]
_stop: set[int] = set()
_lock = threading.RLock()


def request_stop(run_id: int) -> None:
    with _lock:
        _stop.add(run_id)


def _stopped(run_id: int) -> bool:
    with _lock:
        return run_id in _stop


def _clear(run_id: int) -> None:
    with _lock:
        _stop.discard(run_id)


def _concurrency() -> int:
    try:
        return max(1, int(os.environ.get("DATASET_EXT_CONCURRENCY") or 4))
    except ValueError:
        return 4


# ── 提示词拼装（外层动态参数与原项目一致，另注入场景维度）───────────────────────
def _planner_prompt(brief: str, matrix_dimensions: dict | None) -> str:
    extra = ""
    cats = (matrix_dimensions or {}).get("categories") or []
    if cats:
        scene = (matrix_dimensions or {}).get("scene") or ""
        lines = [f"- {c.get('name')}: {'、'.join(c.get('dims') or [])}" for c in cats if c.get("name")]
        if lines:
            extra = (f"\n参考场景维度（{scene}）：\n" + "\n".join(lines)
                     + "\n请让 parameter_space 覆盖上述维度。\n")
    return (MD_P_AGENT_PROMPT
            + f"\n\n本次正式输入：\n任务简述: {brief}\n" + extra
            + "\n请直接按上述「输出格式」输出 JSON 对象，不要 markdown 围栏，不要解释，不要等待下一轮。")


def _gen_prompt(planner: dict, n: int, variant_count: int) -> str:
    return (MD_G_AGENT_PROMPT
            + f"\n\n本次正式输入：\n计划: {json.dumps(planner, ensure_ascii=False)}\n"
            + f"本次只生成第 {n + 1} 条任务（task_id 为 task-{n + 1}），含恰好 {variant_count} 个欠指定变体。\n\n"
            + '请直接按上述「输出格式」输出形如 {"task_set":[{"一个任务"}]} 的 JSON，不要 markdown 围栏，不要解释，不要等待下一轮。')


def _verify_prompt(task: dict) -> str:
    return (MD_V_AGENT_PROMPT
            + f"\n\n本次正式输入：\n要检查的任务: {json.dumps(task, ensure_ascii=False)}\n\n"
            + '请直接按上述「输出格式」输出形如 {"verification_results":[{"一个结果"}]} 的 JSON，不要 markdown 围栏，不要解释，不要等待下一轮。')


# ── 五维评估指标（逐字移植 pipeline_controller._compute_evaluator_metrics）────
def _score_scale(results: list) -> float:
    """verifier 评分的标度上限。

    原项目的提示词要求 5 个维度都按 0.0~1.0 打分
    （见 prompts.MD_V_AGENT_PROMPT「评分：1.0（完全清晰）→ 0.0」），
    而内置 mock 给的是 3~5 的整数分。按实际值域判断标度，统一折算到 0~1 再判阈值——
    否则真 LLM 的 0.95/1.0 会被 `>= 3.0` 判成「未覆盖」，覆盖度评分永远是 0.000。
    """
    top = 0.0
    for r in results:
        for v in (r.get("scores") or {}).values():
            try:
                top = max(top, float(v))
            except (TypeError, ValueError):
                continue
    return 1.0 if top <= 1.0 else 5.0


def compute_evaluator_metrics(verifier_results: list, task_count: int) -> dict | None:
    results = [r for r in (verifier_results or []) if isinstance(r, dict)]
    if not results:
        return None
    scale = _score_scale(results)
    n_dims, n_tasks = len(SCORE_DIMS), len(results)
    dim_avgs = {}
    for dim in SCORE_DIMS:
        vals = [(r.get("scores") or {}).get(dim, 0) for r in results]
        vals = [v for v in vals if v is not None]
        dim_avgs[dim] = sum(vals) / len(vals) if vals else 0.0

    task_totals = [sum((r.get("scores") or {}).get(d, 0) or 0 for d in SCORE_DIMS) for r in results]
    sum_total = sum(task_totals)
    if sum_total > 0:
        p_vals = [t / sum_total for t in task_totals]
        h = -sum(p * math.log2(p) for p in p_vals if p > 0)
        hmax = math.log2(n_tasks) if n_tasks > 0 else 1.0
        entropy_normalized = h / hmax if hmax > 0 else 0.0
    else:
        entropy_normalized = 0.0

    # 阈值按归一化后的 0~1 判断：等价于「5 分制下 >= 3.0」（mock 的档位）
    covered = sum(1 for d in SCORE_DIMS if dim_avgs[d] / scale >= 0.6)
    width = covered / n_dims
    d_vals = [dim_avgs[d] for d in SCORE_DIMS if dim_avgs[d] > 0]
    balance = (min(d_vals) / max(d_vals)) if d_vals and max(d_vals) > 0 else 0.0
    depth = ((dim_avgs.get("completeness", 0) + dim_avgs.get("feasibility", 0)) / scale) / 2.0
    return {
        "coverage_score": round(width * balance * depth, 4),
        "entropy_normalized": round(entropy_normalized, 4),
        "width": round(width, 4),
        "balance": round(balance, 4),
        "depth": round(depth, 4),
        "covered_capabilities": covered,
        "total_capabilities": n_dims,
        "score_scale": scale,
    }


def _pass_rate(results: list) -> int:
    results = [r for r in (results or []) if isinstance(r, dict)]
    if not results:
        return 0
    return round(100 * sum(1 for r in results if r.get("pass")) / len(results))


# ── 主流程 ─────────────────────────────────────────────────────────────────
def run(run_id: int) -> None:
    run = store.get(run_id)
    if not run:
        return
    brief = run.get("brief") or ""
    scene = run.get("scene") or ""
    task_count = max(1, int(run.get("task_count") or 2))
    variant_count = max(0, int(run.get("variant_count") or 1))
    matrix_dimensions = run.get("matrix_dimensions") or None
    # LLM 来源：环境变量 / backend/config.yaml 优先；都没有就用「本次运行用到的智能体配置」
    # 里声明的 api / key / model —— 即前端在 r1 上传的那份配置文件，前端传什么就用什么。
    cfg = llm.load_config(api_agent.llm_declared(run.get("agent_id")))
    llm_ok = llm.is_configured(cfg)
    fallback = bool((cfg.get("llm") or {}).get("fallback_to_mock", True))
    model = (cfg.get("llm") or {}).get("model", "")
    llm_src = (cfg.get("llm") or {}).get("config_source") or ""

    sc = sm.find_scene(scene or (matrix_dimensions or {}).get("scene") or "")
    dims = sm.flatten_dims(sc) if sc else []
    if sc and not scene:
        scene = sc["name"]

    engine = "llm" if llm_ok else "mock"
    store.update(run_id, engine=engine, scene=scene, matrix_dimensions=matrix_dimensions,
                 llm_source=llm_src, llm_model=(model if llm_ok else ""))
    store.log(run_id, f"[Step1] 数据集生成启动 · 场景 {scene} · 任务 {task_count} · 变体 {variant_count}", "muted")
    store.log(run_id, f"[Step1] 引擎: {'LLM ' + model if llm_ok else 'mock（未配置 LLM）'}"
                      + (f" · 来源 {llm_src}" if llm_ok and llm_src else "")
                      + (f" · 场景维度 {len(dims)} 个" if dims else ""), "muted")
    if not llm_ok:
        store.log(run_id, "[Step1] 没有可用 LLM：在 r1 上传含 api/key/model 的智能体配置即可被 step1 直接使用"
                          "（也可另建 backend/config.yaml）；否则全程走内置 mock", "muted")

    degraded = False

    def degrade(step: str, err: str) -> None:
        nonlocal degraded, engine
        degraded = True
        engine = "llm+mock" if llm_ok else "mock"
        store.log(run_id, f"[降级] {step} 调用 LLM 失败（{err}），该步改用确定性 mock 继续", "warning")

    try:
        # ── 步骤 1：计划 ──────────────────────────────────────────────────
        store.set_progress(run_id, substeps={"planner": "running"})
        store.log(run_id, "[Step1] 计划: 正在生成...", "muted")
        planner = None
        last_err = ""
        if llm_ok:
            prompt = _planner_prompt(brief, matrix_dimensions)
            for attempt in range(3):
                if _stopped(run_id):
                    return _cancelled(run_id)
                try:
                    planner = llm.robust_json_parse(llm.chat(prompt, cfg))
                    if isinstance(planner, dict) and "domain_scenarios" in planner:
                        break
                    last_err = f"返回结构异常（第 {attempt + 1} 次）"
                    planner = None
                except Exception as e:
                    last_err = str(e)
                time.sleep(2)
        if not isinstance(planner, dict):
            if llm_ok and not fallback:
                return _fail(run_id, "planner", last_err or "planner 失败")
            if llm_ok:
                degrade("planner", last_err or "planner 失败")
            planner = mockgen.mock_planner(brief, scene, dims)
        store.set_step(run_id, "planner", planner)
        store.set_progress(run_id, substeps={"planner": "completed"})
        params_n = len(planner.get("parameter_space") or {})
        store.log(run_id, f"[Step1] 计划: 完成（参数空间 {params_n} 项）", "success")

        # ── 步骤 2：生成（逐条并行）───────────────────────────────────────
        store.set_progress(run_id, substeps={"generator": "running"})
        store.log(run_id, f"[Step1] 生成: 正在并行生成 {task_count} 条任务...", "muted")
        task_set: list = [None] * task_count
        done = 0
        workers = min(_concurrency(), task_count)

        if llm_ok:
            def _gen_one(n: int):
                prompt = _gen_prompt(planner, n, variant_count)
                for _ in range(3):
                    if _stopped(run_id):
                        return None
                    try:
                        parsed = llm.robust_json_parse(llm.chat(prompt, cfg))
                        task = llm.extract_first(parsed, "task_set")
                        if isinstance(task, dict) and "full_instruction" in task:
                            task["task_id"] = f"task-{n + 1}"
                            task.setdefault("covered_dimensions", [])
                            return task
                    except Exception as e:
                        last_error.append(str(e))
                    time.sleep(2)
                return None

            last_error: list[str] = []
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(_gen_one, n): n for n in range(task_count)}
                for fut in as_completed(futs):
                    n = futs[fut]
                    try:
                        task_set[n] = fut.result()
                    except Exception:
                        task_set[n] = None
                    done += 1
                    store.set_step(run_id, "generator", {"task_set": [t for t in task_set if t]})
                    store.set_progress(run_id, generator_completed=done, generator_total=task_count)
                    store.log(run_id, f"[Step1] 生成: 完成 {done}/{task_count}", "muted")
                    if _stopped(run_id):
                        return _cancelled(run_id)
            if any(t is None for t in task_set):
                if not fallback:
                    return _fail(run_id, "generator", (last_error or ["生成失败"])[0])
                degrade("generator", (last_error or ["生成失败"])[0])
                mock_tasks = mockgen.mock_generator(planner, dims, task_count, variant_count)
                task_set = [t if t is not None else mock_tasks[i] for i, t in enumerate(task_set)]
        else:
            task_set = mockgen.mock_generator(planner, dims, task_count, variant_count)
            for i in range(task_count):
                if _stopped(run_id):
                    return _cancelled(run_id)
                done = i + 1
                store.set_step(run_id, "generator", {"task_set": task_set[:done]})
                store.set_progress(run_id, generator_completed=done, generator_total=task_count)
                store.log(run_id, f"[Step1] 生成: 完成 {done}/{task_count}", "muted")
                time.sleep(0.05)

        store.set_step(run_id, "generator", {"task_set": task_set})
        store.set_progress(run_id, substeps={"generator": "completed"})
        store.log(run_id, f"[Step1] 生成: 完成, 共 {len(task_set)} 条任务", "success")

        # ── 步骤 3：检查（逐条并行）───────────────────────────────────────
        store.set_progress(run_id, substeps={"verifier": "running"})
        store.log(run_id, "[Step1] 检查: 正在并行验证任务...", "muted")
        ver_results: list = [None] * len(task_set)
        vr_done = 0

        def _verify_one(n: int, task: dict):
            prompt = _verify_prompt(task)
            for _ in range(3):
                if _stopped(run_id):
                    return None
                try:
                    parsed = llm.robust_json_parse(llm.chat(prompt, cfg))
                    vr = llm.extract_first(parsed, "verification_results")
                    if isinstance(vr, dict):
                        vr.setdefault("task_id", task.get("task_id", f"task-{n + 1}"))
                        return vr
                except Exception as e:
                    ver_error.append(str(e))
                time.sleep(2)
            return None

        if llm_ok:
            ver_error: list[str] = []
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(_verify_one, n, t): n for n, t in enumerate(task_set)}
                for fut in as_completed(futs):
                    n = futs[fut]
                    try:
                        ver_results[n] = fut.result()
                    except Exception:
                        ver_results[n] = None
                    vr_done += 1
                    store.set_step(run_id, "verifier", {
                        "verification_results": [r for r in ver_results if r],
                        "overall_pass": all((r or {}).get("pass", False) for r in ver_results if r),
                    })
                    store.set_progress(run_id, verifier_completed=vr_done, verifier_total=len(task_set))
                    store.log(run_id, f"[Step1] 检查: 验证完成 {vr_done}/{len(task_set)}", "muted")
                    if _stopped(run_id):
                        return _cancelled(run_id)
            if any(r is None for r in ver_results):
                if not fallback:
                    return _fail(run_id, "verifier", (ver_error or ["验证失败"])[0])
                degrade("verifier", (ver_error or ["验证失败"])[0])
                ver_results = [r if r is not None else mockgen.mock_verifier(task_set[i])
                               for i, r in enumerate(ver_results)]
        else:
            for i, t in enumerate(task_set):
                if _stopped(run_id):
                    return _cancelled(run_id)
                ver_results[i] = mockgen.mock_verifier(t)
                vr_done = i + 1
                store.set_step(run_id, "verifier", {
                    "verification_results": ver_results[:vr_done],
                    "overall_pass": all(r.get("pass", False) for r in ver_results[:vr_done]),
                })
                store.set_progress(run_id, verifier_completed=vr_done, verifier_total=len(task_set))
                store.log(run_id, f"[Step1] 检查: 验证完成 {vr_done}/{len(task_set)}", "muted")
                time.sleep(0.05)

        store.set_step(run_id, "verifier", {
            "verification_results": ver_results,
            "overall_pass": all(r.get("pass", False) for r in ver_results),
            "overall_issues": [],
            "overall_recommendations": [],
        })
        store.set_progress(run_id, substeps={"verifier": "completed"})
        store.log(run_id, f"[Step1] 检查: 完成, 通过率 {_pass_rate(ver_results)}%", "success")

        # ── 步骤 4：评估（程序化，无 LLM）─────────────────────────────────
        store.set_progress(run_id, substeps={"evaluator": "running"})
        store.log(run_id, "[Step1] 评估: 正在计算覆盖度...", "muted")
        metrics = compute_evaluator_metrics(ver_results, len(task_set)) or {}
        total_variants = sum(len(t.get("underspecified_variants") or []) for t in task_set)
        evaluator = {
            "total_tasks": len(task_set),
            "total_variants": total_variants,
            "pass_rate": _pass_rate(ver_results),
            "coverage_note": "auto-generated from server-side execution",
            **metrics,
        }
        store.set_step(run_id, "evaluator", evaluator)
        store.set_progress(run_id, substeps={"evaluator": "completed"})
        store.update(run_id, status="completed", engine=engine,
                     error=None if not degraded else f"部分步骤降级为 mock")
        store.log(run_id, f"[Step1] 完成: {len(task_set)} 条任务 · {total_variants} 个变体 · "
                          f"覆盖度 {evaluator.get('coverage_score', 0):.3f}", "success")

    except Exception as e:  # noqa: BLE001
        return _fail(run_id, "unknown", f"{type(e).__name__}: {e}")
    finally:
        _clear(run_id)


def _fail(run_id: int, step: str, message: str) -> None:
    store.log(run_id, f"[Step1] {step} 失败: {message}", "error")
    run = store.get(run_id) or {}
    steps = dict(run.get("steps") or {})
    steps["__failed__"] = step
    store.update(run_id, status="failed", steps=steps, error=f"{step}: {message}")
    _clear(run_id)


def _cancelled(run_id: int) -> None:
    store.log(run_id, "[Step1] 已取消", "warning")
    store.update(run_id, status="cancelled")
    _clear(run_id)
