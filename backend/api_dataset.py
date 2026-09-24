# -*- coding: utf-8 -*-
"""step1 数据集接口：create / get / summary / stream / cancel。

`build_summary()` 是本项目唯一的聚合点：把原 pipeline step1 的原始产出
（planner / generator / verifier / evaluator）折算成 index 页面
r3 任务空间树、r4 能力矩阵、r5 六项指标、r6 参数覆盖明细所需的视图模型。
"""

from __future__ import annotations

import json
import threading

import api_agent
import mockgen
import scene_matrix as sm
import step1_runner
import store

DEFAULT_TASK_COUNT = 4
DEFAULT_VARIANT_COUNT = 2
MAX_PARAM_ROWS = 8


# ── 运行管理 ──────────────────────────────────────────────────────────────
def create(body: dict) -> dict:
    brief = (body.get("brief") or "").strip()[:2000]
    scene = (body.get("scene") or "").strip()
    matrix_dimensions = body.get("matrix_dimensions") or None
    if not scene and matrix_dimensions:
        scene = matrix_dimensions.get("scene") or ""
    sc = sm.find_scene(scene)
    if sc and not scene:
        scene = sc["name"]

    try:
        task_count = max(1, min(50, int(body.get("task_count") or DEFAULT_TASK_COUNT)))
    except (TypeError, ValueError):
        task_count = DEFAULT_TASK_COUNT
    try:
        variant_count = max(0, min(20, int(body.get("variant_count") or DEFAULT_VARIANT_COUNT)))
    except (TypeError, ValueError):
        variant_count = DEFAULT_VARIANT_COUNT

    run = store.create(
        brief=brief, scene=scene, task_count=task_count, variant_count=variant_count,
        matrix_dimensions=matrix_dimensions, agent_id=body.get("agent_id") or "",
        engine="pending", status="running",
    )
    threading.Thread(target=step1_runner.run, args=(run["id"],),
                     name=f"step1-{run['id']}", daemon=True).start()
    return {"ok": True, "id": run["id"], "scene": scene,
            "task_count": task_count, "variant_count": variant_count}


def get(rid: int) -> dict:
    run = store.get(rid)
    if not run:
        return {"ok": False, "error": "run not found"}
    return {"ok": True, "run": run}


def cancel(rid: int) -> dict:
    step1_runner.request_stop(rid)
    return {"ok": True, "id": rid}


# ── 参数 → 泛化维度 关联 ──────────────────────────────────────────────────
_SLUG_TO_DIM = {v[0]: k for k, v in mockgen.DIM_PARAM.items()}


def _param_dim(pname: str, index: int, dims: list[dict]) -> str:
    """参数名 → 泛化维度名。

    先走语义匹配（真 LLM 的参数名与 mock 的不同，如 product_brand / sort_method），
    再退到 mock 的固定 slug 表，最后才做名字包含匹配；都命中不了就返回 "" ——
    以前这里兜底 `dims[index % len(dims)]` 会硬凑一个**错的**维度，不如老实留空。
    """
    names = [d["name"] for d in dims if d.get("name")]
    matched = sm.match_dim(str(pname), names)
    if matched:
        return matched
    if pname in _SLUG_TO_DIM:
        return _SLUG_TO_DIM[pname]
    low = pname.lower()
    for d in dims:
        if d["name"] and (d["name"] in pname or pname in d["name"]):
            return d["name"]
    for d in dims:
        if d["name"] and (d["name"][:2] in low or d["name"] in low):
            return d["name"]
    return ""


def _build_params(planner: dict, dims: list[dict], tasks: list[dict],
                  limit: int | None = MAX_PARAM_ROWS) -> list[dict]:
    space = planner.get("parameter_space") or {}
    if not isinstance(space, dict):
        return []
    text = " ".join(str(t) for t in tasks)
    text += " " + " ".join(json_dumps(t.get("constraints")) for t in tasks)
    rows: list[dict] = []
    for i, (pname, spec) in enumerate(space.items()):
        spec = spec if isinstance(spec, dict) else {}
        values = spec.get("range") if isinstance(spec.get("range"), list) else []
        values = [str(v) for v in values]
        dim = _param_dim(str(pname), i, dims)
        dim_used = sum(1 for t in tasks if dim and dim in (t.get("covered_dimensions") or []))
        used_values = {v for v in values if v and v in text}
        used = max(len(used_values), dim_used)
        range_size = len(values) or max(used, 1)
        used = min(used, range_size)
        rows.append({
            "param": str(pname),
            "dim": dim,
            "value_list": values,
            "values": " · ".join(values[:5]) + (f" 等 {len(values)} 类" if len(values) > 5 else ""),
            "used": used,
            "range": range_size,
            "coverage": round(100 * used / range_size) if range_size else 0,
            "type": spec.get("type") or "",
            "description": spec.get("description") or "",
        })
    rows.sort(key=lambda r: (-r["used"], r["param"]))
    return rows[:limit] if limit else rows


def json_dumps(obj) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return str(obj)


# ── 视图模型 ──────────────────────────────────────────────────────────────
def _phase(status: str, sub: dict) -> str:
    if status == "idle":
        return "idle"
    if status == "completed":
        return "done"
    if status in ("failed", "cancelled"):
        return "failed"
    if sub.get("evaluator") == "running":
        return "evaluating"
    if sub.get("generator") == "running" or sub.get("verifier") == "running":
        return "executing"
    return "modeling"


def build_summary(rid: int) -> dict:
    run = store.get(rid)
    if not run:
        return {"ok": False, "error": "run not found"}
    return summarise(run)


def preview(scene: str, agent_id: str = "") -> dict:
    """场景预览：还没有 run 时，也能看到该场景的树 + 矩阵结构（覆盖进度为 0）。

    走的还是 summarise()，所以结构与真实运行完全一致，不是另一套渲染。
    """
    sc = sm.find_scene(scene)
    view = summarise({
        "id": 0, "status": "idle", "scene": sc["name"] if sc else (scene or ""),
        "steps": {}, "progress": {}, "engine": "preview",
        "agent_id": agent_id, "logs": [], "brief": "", "error": None,
    })
    view["ok"] = True
    view["preview"] = True
    view["data_source"] = "preview"
    return view


def summarise(run: dict) -> dict:
    rid = run.get("id")
    steps = run.get("steps") or {}
    planner = steps.get("planner") if isinstance(steps.get("planner"), dict) else {}
    gen = steps.get("generator") if isinstance(steps.get("generator"), dict) else {}
    ver = steps.get("verifier") if isinstance(steps.get("verifier"), dict) else {}
    evaluator = steps.get("evaluator") if isinstance(steps.get("evaluator"), dict) else {}

    tasks = [t for t in (gen.get("task_set") or []) if isinstance(t, dict)]
    ver_results = [r for r in (ver.get("verification_results") or []) if isinstance(r, dict)]

    scene = run.get("scene") or ""
    sc = sm.find_scene(scene)
    dims = sm.flatten_dims(sc) if sc else []
    if sc:
        scene = sc["name"]
    missing = api_agent.missing_caps(run.get("agent_id"))

    # 已覆盖的泛化维度（三条来源）：
    # 1) mock 的 generator 直接产出 covered_dimensions；
    # 2) 真 LLM 不产出该字段（原项目的提示词里根本没有它），但每条任务都带
    #    parameters（键 = planner.parameter_space 的参数名），
    #    故用「参数名 → 泛化维度」语义映射（sm.match_dim）折算成覆盖维度；
    # 3) 兜底：任务文本里直接出现维度名。
    covered: list[str] = []
    for t in tasks:
        for d in (t.get("covered_dimensions") or []):
            if d and d not in covered:
                covered.append(d)
    dim_names = [d["name"] for d in dims]
    for t in tasks:
        if t.get("covered_dimensions"):
            continue
        for pname in (t.get("parameters") or {}):
            dn = sm.match_dim(str(pname), dim_names)
            if dn and dn not in covered:
                covered.append(dn)
    text = json_dumps(tasks)
    for d in dims:
        if d["name"] not in covered and d["name"] in text:
            covered.append(d["name"])
    covered_set = set(covered)
    cur_dim = None
    if tasks:
        cd = [x for x in (tasks[-1].get("covered_dimensions") or []) if x]
        cur_dim = cd[0] if cd else None

    # r3 任务空间树：场景 → 维度类别 → 泛化维度(anchor P<i>) → 取值
    param_by_dim = {}
    for row in _build_params(planner, dims, tasks, limit=None):
        param_by_dim.setdefault(row["dim"], row)
    tree_cats = []
    for cat in (sc.get("categories") if sc else []) or []:
        cat_dims = []
        for d in cat["dims"]:
            name = d["name"]
            flat = next((x for x in dims if x["name"] == name and x["category"] == cat["name"]), None)
            vals = []
            row = param_by_dim.get(name)
            if row:
                vals = [v for v in (row.get("value_list") or []) if v][:3]
            if not vals:
                # 兜底：用该泛化维度真实点亮的能力列名（13 列口径）
                vals = [cap["cap"] for cap, tier in zip(sm.CAPS13, sm.cap_tiers(d["scores"]))
                        if tier > 0][:3]
            cat_dims.append({
                "id": flat["id"] if flat else "",
                "name": name,
                "status": ("done" if name in covered_set
                           else ("run" if name == cur_dim else "idle")),
                "leaves": vals,
            })
        tree_cats.append({"name": cat["name"], "dims": cat_dims})

    # r4 能力矩阵：行 = 泛化维度，列 = 13 能力；档位由矩阵符号折算，再挖掉智能体不支持的能力
    rows = []
    total = len(dims) * len(sm.CAPS13)
    covered_cells = 0
    reachable = 0
    for d in dims:
        raw = sm.cap_tiers(d["scores"])
        tiers = [0 if sm.CAPS13[i]["cap"] in missing else t for i, t in enumerate(raw)]
        reachable += sum(1 for t in tiers if t > 0)
        active = d["name"] in covered_set
        lit = [i for i, t in enumerate(tiers) if t > 0 and active]
        covered_cells += len(lit)
        rows.append({"dim_id": d["id"], "dim": d["name"], "category": d["category"],
                     "tiers": tiers, "active": active, "lit": lit})

    # r5 六项指标
    total_variants = sum(len(t.get("underspecified_variants") or []) for t in tasks)
    pass_rate = evaluator.get("pass_rate")
    if pass_rate is None:
        pass_rate = (round(100 * sum(1 for r in ver_results if r.get("pass")) / len(ver_results))
                     if ver_results else 0)
    coverage_score = float(evaluator.get("coverage_score") or 0.0)
    metrics = [
        {"key": "tasks", "label": "任务生成数量", "type": "int", "value": len(tasks)},
        {"key": "variants", "label": "变体", "type": "int", "value": total_variants},
        {"key": "dims", "label": "去重维度", "type": "int", "value": len(covered)},
        {"key": "matrix", "label": "矩阵覆盖", "type": "frac",
         "value": [covered_cells, total], "hl": True},
        {"key": "pass", "label": "检查通过率", "type": "pct", "value": int(pass_rate)},
        {"key": "coverage", "label": "覆盖度评分", "type": "dec",
         "value": round(coverage_score, 3), "hl": True},
    ]

    # r3 右侧「已泛化query」
    queries = []
    for t in tasks:
        if t.get("full_instruction"):
            queries.append({"n": len(queries) + 1, "text": t["full_instruction"]})
        for v in (t.get("underspecified_variants") or []):
            if isinstance(v, dict) and v.get("instruction"):
                queries.append({"n": len(queries) + 1, "text": v["instruction"]})

    prog = dict(run.get("progress") or {})
    sub = dict(prog.get("substeps") or {})
    status = run.get("status") or "running"
    engine = run.get("engine") or "unknown"
    # 数据来源：直接决定 r3 的 query / r5 的通过率与覆盖度评分 / r6 的参数取值能不能当真结论
    data_source = {"mock": "mock", "llm": "llm", "llm+mock": "mixed",
                   "pending": "pending"}.get(engine, engine)

    return {
        "ok": True,
        "id": rid,
        "status": status,
        "phase": _phase(status, sub),
        "engine": engine,
        "data_source": data_source,
        "llm_source": run.get("llm_source") or "",   # 本次运行的 LLM 配置来源（可能就是前端上传的智能体配置）
        "llm_model": run.get("llm_model") or "",
        "error": run.get("error"),
        "brief": run.get("brief"),
        "scene": scene,
        "agent_id": run.get("agent_id") or "",
        "missing_caps": missing,
        "progress": {
            "substeps": sub,
            "generator_completed": prog.get("generator_completed", 0),
            "generator_total": prog.get("generator_total", run.get("task_count", 0)),
            "verifier_completed": prog.get("verifier_completed", 0),
            "verifier_total": prog.get("verifier_total", 0),
        },
        "tree": {"scene": scene, "categories": tree_cats,
                 "dims": [{"id": d["id"], "name": d["name"], "category": d["category"],
                           "scores": d["scores"]} for d in dims]},
        "matrix": {
            "caps13": sm.caps13_public(),
            "groups": sm.CAP_GROUP_ORDER,
            "rows": rows,
            "total": total,
            "covered": covered_cells,
            "reachable": reachable,
            "missing": missing,
        },
        "metrics": metrics,
        "params": _build_params(planner, dims, tasks),
        "queries": queries,
        "logs": (run.get("logs") or [])[-200:],
        "tasks": tasks,
    }


def stream_snapshot(rid: int) -> dict | None:
    return store.summary_event(rid)
