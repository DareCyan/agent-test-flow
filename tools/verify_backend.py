# -*- coding: utf-8 -*-
"""后端验收脚本（对应 PLAN.md §八）。

    python tools/verify_backend.py [--base http://127.0.0.1:8787]

逐条断言并打印 PASS/FAIL；任一失败以退出码 1 结束。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f" · {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f" · {detail}" if detail else ""))
    return bool(cond)


def req(base: str, path: str, method: str = "GET", body: dict | None = None):
    url = base.rstrip("/") + path
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}", "body": e.read().decode("utf-8", "replace")[:300]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8787")
    ap.add_argument("--task-count", type=int, default=4)
    ap.add_argument("--variant-count", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=900, help="等待 step1 完成的秒数")
    args = ap.parse_args()
    base = args.base

    print("\n== 1. 健康检查与场景矩阵 ==")
    h = req(base, "/api/health")
    check("GET /api/health → ok", h.get("ok") is True, f"engine={h.get('engine')}")
    mx = req(base, "/api/scene-matrix")
    check("GET /api/scene-matrix → ok", mx.get("ok") is True)
    check("29 个 L2 能力", len(mx.get("l2_info") or []) == 29, f"{len(mx.get('l2_info') or [])}")
    check("13 个能力列", len(mx.get("caps13") or []) == 13, f"{len(mx.get('caps13') or [])}")
    scenes = mx.get("scenes") or []
    check("14 个场景", len(scenes) == 14, f"{len(scenes)}")
    ec = next((s for s in scenes if s["name"] == "电商购物"), None)
    check("电商购物存在", ec is not None)
    dims = [d for c in (ec or {}).get("categories", []) for d in c["dims"]]
    cats = [c["name"] for c in (ec or {}).get("categories", [])]
    check("电商购物 = 5 类别 / 14 泛化维度", len(cats) == 5 and len(dims) == 14,
          f"cats={cats} dims={len(dims)}")
    check("14 × 13 = 182", len(dims) * 13 == 182, f"{len(dims) * 13}")

    print("\n== 2. r1 智能体接入（zip 安装包 + 配置文件 api/key/model）==")
    example_cfg = Path(__file__).resolve().parents[1] / "examples" / "agent" / "shopping-agent.yaml"
    if example_cfg.exists():
        cfg_text = example_cfg.read_text(encoding="utf-8")
        src = "examples/agent/shopping-agent.yaml"
    else:
        cfg_text = ("name: shopping-agent-v2\napi: https://api.openai.com/v1\n"
                    "key: sk-demo-1234567890abcdefghijklmn\nmodel: gpt-4o-mini\n"
                    "missing_capabilities: [图像识别]\n")
        src = "内联配置"
    raw_key = "sk-demo-1234567890abcdefghijklmn"
    a = req(base, "/api/agent/connect", "POST", {
        "binary": {"name": "shopping-agent-v2.zip", "size": "1.8 KB"},
        "config": {"name": "shopping-agent.yaml", "size": "1.8 KB"},
        "config_content": cfg_text,
    })
    check("POST /api/agent/connect → 返回 agent_id", a.get("ok") is True and bool(a.get("agent_id")),
          str(a.get("agent_id")))
    agent_id = a.get("agent_id") or ""
    deadline = time.time() + 40
    st = {}
    while time.time() < deadline:
        st = req(base, f"/api/agent/status?id={agent_id}")
        if st.get("phase") == "ready":
            break
        time.sleep(0.4)
    check("接入完成（phase=ready）", st.get("phase") == "ready", str(st.get("phase")))
    logs = st.get("logs") or []
    check("识别日志 6 条", len(logs) == 6, f"{len(logs)}")
    prof = st.get("profile") or {}
    check(f"配置文件被真实解析（{src}）",
          prof.get("name") == "shopping-agent-v2", f"name={prof.get('name')}")
    check("解析出智能体的 api（endpoint）",
          prof.get("endpoint") == "https://api.openai.com/v1", str(prof.get("endpoint")))
    check("解析出智能体的 model", prof.get("model") == "gpt-4o-mini", str(prof.get("model")))
    check("API Key 已脱敏（只回显掩码）",
          prof.get("api_key_masked") == "sk-d****klmn" and prof.get("has_api_key") is True,
          str(prof.get("api_key_masked")))
    blob = json.dumps(st, ensure_ascii=False)
    check("完整 key 不出现在任何接口响应里", raw_key not in blob, "已脱敏")
    check("declared 里的 key 类字段也被掩码",
          "sk-demo-1234" not in json.dumps(prof.get("declared") or {}, ensure_ascii=False))
    conn = prof.get("connectivity") or {}
    check("联通性探测三态合法（True/False/None 且有结论）",
          conn.get("ok") in (True, False, None) and bool(conn.get("detail")),
          f"ok={conn.get('ok')} detail={conn.get('detail')}")
    check("测不出结论时写明「未实测」",
          conn.get("ok") is not None or "未实测" in str(conn.get("detail")),
          str(conn.get("detail")))
    for name, label in (("single_turn", "单轮"), ("multi_turn", "多轮"), ("protocol", "协议")):
        v = (prof.get("probes") or {}).get(name) or {}
        check(f"{label}对话/协议探测有结论（三态 + detail）",
              v.get("ok") in (True, False, None) and bool(v.get("detail")),
              f"ok={v.get('ok')} · {str(v.get('detail'))[:70]}")
    check("6 行日志的 ok 全是三态标记",
          len(logs) == 6 and all(l.get("ok") in (True, False, None) for l in logs),
          str([l.get("ok") for l in logs]))
    check("凡未实测的行，文案里都写明「未实测」",
          all("未实测" in l.get("text", "") for l in logs if l.get("ok") is None),
          str([l.get("text", "")[:16] for l in logs if l.get("ok") is None]))
    check("调用方式 / 协议 / 能力都标注了来源",
          bool(prof.get("call_modes_source")) and bool(prof.get("protocol_source"))
          and bool(prof.get("capabilities_source")),
          f"call_modes={prof.get('call_modes_source')} · protocol={prof.get('protocol_source')}"
          f" · caps={prof.get('capabilities_source')}")
    check("第 5 步的 ok 标记与探测结论一致",
          next((l.get("ok") for l in logs if "模型联通性" in l.get("text", "")), "missing")
          == conn.get("ok"), f"conn.ok={conn.get('ok')}")
    check("zip 安装包只记元数据、不落盘",
          prof.get("binary") == "shopping-agent-v2.zip" and prof.get("binary_stored") is False,
          f"binary={prof.get('binary')} stored={prof.get('binary_stored')}")
    check("missing 能力列 = 图像识别", prof.get("missing") == ["图像识别"], str(prof.get("missing")))
    check("capabilities 排除 missing 的 L2（1.4）",
          "1.4" not in (prof.get("capabilities") or []), f"{len(prof.get('capabilities') or [])}/29")

    print("\n== 3. step1 数据集生成 ==")
    # step1 的 LLM 来源兜底 = 「前端上传的智能体配置」里声明的 api/key/model。
    # 这里专门注册一个端点必然不可达的智能体：既验证新链路，又让失败/降级路径
    # 快速、确定、且不产生任何外呼（不烧 key）。
    dead = req(base, "/api/agent/connect", "POST", {
        "binary": {"name": "dead-endpoint-agent.zip", "size": "1 KB"},
        "config": {"name": "dead-endpoint-agent.yaml", "size": "1 KB"},
        "config_content": ("name: dead-endpoint-agent\n"
                           "api: http://127.0.0.1:9/v1\n"
                           "key: sk-dead-000000000000\n"
                           "model: dead-model\n"
                           "missing_capabilities: [图像识别]\n"),
    })
    step1_agent = dead.get("agent_id") or agent_id
    dl = time.time() + 40
    while time.time() < dl:
        if req(base, f"/api/agent/status?id={step1_agent}").get("phase") == "ready":
            break
        time.sleep(0.4)
    run = req(base, "/api/dataset-ext/runs", "POST", {
        "brief": "测试该智能体完成电商购物任务的能力，覆盖商品属性、筛选条件、订单配置、售后属性等维度。",
        "scene": "电商购物",
        "task_count": args.task_count,
        "variant_count": args.variant_count,
        "agent_id": step1_agent,
        "execute": True,
        "matrix_dimensions": {
            "scene": "电商购物",
            "categories": [{"name": c["name"], "dims": [d["name"] for d in c["dims"]]}
                           for c in (ec or {}).get("categories", [])],
        },
    })
    check("POST /api/dataset-ext/runs → id", run.get("ok") is True and run.get("id"),
          f"id={run.get('id')} scene={run.get('scene')}")
    rid = run.get("id")
    check("scene 回显正确（UTF-8 往返）", run.get("scene") == "电商购物", str(run.get("scene")))
    early = req(base, f"/api/dataset-ext/run/summary?id={rid}")
    check("planner 阶段就能安全取 summary（不 500）", early.get("ok") is True,
          str(early.get("error"))[:80])

    t0 = time.time()
    summary = {}
    while time.time() - t0 < args.timeout:
        summary = req(base, f"/api/dataset-ext/run/summary?id={rid}")
        if summary.get("status") in ("completed", "failed", "cancelled"):
            break
        time.sleep(1.0)
    check("step1 结束于 completed", summary.get("status") == "completed",
          f"status={summary.get('status')} engine={summary.get('engine')} err={summary.get('error')}")

    raw = req(base, f"/api/dataset-ext/run?id={rid}")
    steps = ((raw.get("run") or {}).get("steps") or {})
    check("steps 含 planner/generator/verifier/evaluator",
          all(k in steps for k in ("planner", "generator", "verifier", "evaluator")),
          str(sorted(steps.keys())))
    tasks = ((steps.get("generator") or {}).get("task_set") or [])
    check(f"task_set 长度 = {args.task_count}", len(tasks) == args.task_count, f"{len(tasks)}")
    variants = sum(len(t.get("underspecified_variants") or []) for t in tasks)
    check(f"变体总数 = {args.task_count * args.variant_count}",
          variants == args.task_count * args.variant_count, f"{variants}")
    vr = ((steps.get("verifier") or {}).get("verification_results") or [])
    check("verifier 逐任务结果数 = 任务数", len(vr) == len(tasks), f"{len(vr)}")
    check("verifier 每条含 5 维评分",
          all(len((r.get("scores") or {})) == 5 for r in vr),
          str(sorted((vr[0].get("scores") or {}).keys()) if vr else ""))
    ev = steps.get("evaluator") or {}
    check("evaluator 产出 coverage_score", isinstance(ev.get("coverage_score"), (int, float)),
          f"coverage_score={ev.get('coverage_score')}")
    check("evaluator 标出本次评分标度（真 LLM=1.0 / mock=5.0）",
          ev.get("score_scale") in (1.0, 5.0), f"score_scale={ev.get('score_scale')}")

    h = req(base, "/api/health")
    if h.get("llm_configured"):
        check("已配全局 LLM：优先于上传的智能体配置",
              summary.get("engine") == "llm", f"engine={summary.get('engine')}")
    else:
        check("step1 的 LLM 来源 = 上传的智能体配置（agent-config）",
              "agent-config" in str(summary.get("llm_source")), str(summary.get("llm_source")))
        check("llm_model 回显本次用的模型名", summary.get("llm_model") == "dead-model",
              str(summary.get("llm_model")))
        check("端点不可达 → 该步降级为 llm+mock，data_source=mixed（前端标「部分 mock」）",
              summary.get("engine") == "llm+mock" and summary.get("data_source") == "mixed",
              f"engine={summary.get('engine')} data_source={summary.get('data_source')}")
        check("降级在运行日志里显式标注 [降级]（可观测、不静默）",
              any("[降级]" in (l.get("text") or "") for l in (summary.get("logs") or [])),
              str(summary.get("engine")))

    print("\n== 4. summary 视图模型（前端 r3/r4/r5/r6 的口径）==")
    tree = summary.get("tree") or {}
    tree_dims = tree.get("dims") or []
    check("tree 场景正确", tree.get("scene") == "电商购物", str(tree.get("scene")))
    check("tree 类别数 = 5", len(tree.get("categories") or []) == 5,
          f"{len(tree.get('categories') or [])}")
    check("tree 泛化维度 = 14", len(tree_dims) == 14, f"{len(tree_dims)}")
    check("tree 每个维度带 P<i> 锚点与取值",
          all(d.get("id", "").startswith("P") for d in tree_dims)
          and all(len(d.get("dims") or []) >= 0 for c in tree.get("categories") or []
                  for d in c.get("dims") or []))
    leaves = sum(len(d.get("leaves") or []) for c in tree.get("categories") or []
                 for d in c.get("dims") or [])
    check("树的第 4 层（取值）非空", leaves > 0, f"leaves={leaves}")

    m = summary.get("matrix") or {}
    check("矩阵 total = 维度数 × 13 = 182", m.get("total") == len(tree_dims) * 13 == 182,
          f"total={m.get('total')}")
    check("矩阵 rows = 14，每行 13 档", len(m.get("rows") or []) == 14
          and all(len(r.get("tiers") or []) == 13 for r in m.get("rows") or []))
    check("矩阵 cols = 13 个能力列", len(m.get("caps13") or []) == 13)
    mi = [c["cap"] for c in m.get("caps13") or []].index("图像识别")
    check("智能体不支持的能力列全行不点亮",
          all((r.get("tiers") or [0] * 13)[mi] == 0 for r in m.get("rows") or []),
          "图像识别列全 0")
    check("covered ≤ reachable ≤ total",
          0 < (m.get("covered") or 0) <= (m.get("reachable") or 0) <= (m.get("total") or 0),
          f"covered={m.get('covered')} reachable={m.get('reachable')} total={m.get('total')}")

    metrics = summary.get("metrics") or []
    labels = [x.get("label") for x in metrics]
    check("r5 六项指标齐全", labels == ["任务生成数量", "变体", "去重维度", "矩阵覆盖",
                                        "检查通过率", "覆盖度评分"], str(labels))
    by = {x.get("key"): x for x in metrics}
    check("任务生成数量 = task_set 长度", by.get("tasks", {}).get("value") == len(tasks))
    check("变体 = 变体总数", by.get("variants", {}).get("value") == variants)
    frac = by.get("matrix", {}).get("value") or [0, 0]
    check("矩阵覆盖分数项 = [covered, 182]",
          frac[1] == 182 and frac[0] == m.get("covered"), str(frac))
    check("检查通过率 = evaluator.pass_rate",
          by.get("pass", {}).get("value") == ev.get("pass_rate"),
          f"{by.get('pass', {}).get('value')}%")
    check("覆盖度评分 = evaluator.coverage_score（3 位小数）",
          abs(float(by.get("coverage", {}).get("value") or 0)
              - float(ev.get("coverage_score") or 0)) < 0.001,
          str(by.get("coverage", {}).get("value")))

    params = summary.get("params") or []
    space = (steps.get("planner") or {}).get("parameter_space") or {}
    check("r6 参数明细行数 = min(参数空间, 8)",
          len(params) == min(len(space), 8), f"params={len(params)} space={len(space)}")
    check("r6 每行含 参数/关联维度/取值/已用-范围/覆盖率",
          all(all(k in p for k in ("param", "dim", "values", "used", "range", "coverage"))
              for p in params))
    check("r6 关联维度非空且命中真实维度",
          all(p.get("dim") in [d["name"] for d in tree_dims] for p in params),
          str(sorted({p.get("dim") for p in params})))
    check("r6 覆盖率 = used/range",
          all(p.get("coverage") == round(100 * p["used"] / p["range"]) if p["range"] else True
              for p in params))
    queries = summary.get("queries") or []
    check("r3 已泛化 query = 任务 + 变体", len(queries) == len(tasks) + variants, f"{len(queries)}")
    check("progress 子步全部 completed",
          set((summary.get("progress") or {}).get("substeps", {}).values()) == {"completed"})
    check("phase = done", summary.get("phase") == "done", str(summary.get("phase")))
    # 本次 run 的 LLM 来源可能是「上传的智能体配置」（声明了不可达端点 → 降级 mixed），
    # 也可能是全局 LLM 配置；两种都不该是「没标来源」。
    if h.get("llm_configured"):
        check("summary 数据来源 = llm（全局 LLM 配置）",
              summary.get("data_source") == "llm", str(summary.get("data_source")))
    else:
        check("summary 数据来源 = mixed（上传配置被采纳但端点不可达 → 该步降级）",
              summary.get("data_source") == "mixed", str(summary.get("data_source")))

    print("\n== 5. 原始契约（可回接原项目）==")
    check("GET /api/dataset-ext/run 返回 run.steps", bool(raw.get("ok") and steps))
    check("无 __failed__ 标记", "__failed__" not in steps)

    print("\n== 6. 场景预览（不跑 run 也能取真实结构）==")
    pv = req(base, "/api/scene-preview?scene=" + urllib.parse.quote("本地生活"))
    check("GET /api/scene-preview → ok", pv.get("ok") is True, str(pv.get("error"))[:60])
    check("预览用的是请求的场景", (pv.get("tree") or {}).get("scene") == "本地生活",
          str((pv.get("tree") or {}).get("scene")))
    pdims = len(((pv.get("tree") or {}).get("dims") or []))
    check("预览矩阵 total = 维度数 × 13",
          (pv.get("matrix") or {}).get("total") == pdims * 13,
          f"dims={pdims} total={(pv.get('matrix') or {}).get('total')}")
    check("预览覆盖进度为 0", (pv.get("matrix") or {}).get("covered") == 0)
    check("预览 data_source = preview", pv.get("data_source") == "preview",
          str(pv.get("data_source")))
    check("预览 phase = idle", pv.get("phase") == "idle", str(pv.get("phase")))
    pv_ec = req(base, "/api/scene-preview?scene=" + urllib.parse.quote("电商购物"))
    check("换场景预览维度数随之变化",
          len(((pv_ec.get("tree") or {}).get("dims") or [])) == 14,
          f"电商购物 dims={len(((pv_ec.get('tree') or {}).get('dims') or []))}")

    print("\n== 7. LLM 配置读取（json / yaml）==")
    h = req(base, "/api/health")
    check("健康检查暴露 llm_config_source 字段", "llm_config_source" in h,
          f"source={h.get('llm_config_source')!r}")

    print("\n== 8. 无 agent / 无 LLM 时的纯 mock 路径 ==")
    r8 = req(base, "/api/dataset-ext/runs", "POST", {
        "brief": "不关联智能体的最小运行", "scene": "电商购物",
        "task_count": 1, "variant_count": 0, "execute": True})
    s8, t8 = {}, time.time()
    while time.time() - t8 < 90:
        s8 = req(base, f"/api/dataset-ext/run/summary?id={r8.get('id')}")
        if s8.get("status") in ("completed", "failed"):
            break
        time.sleep(0.5)
    check("无 agent 的最简 run 能跑完", s8.get("status") == "completed", str(s8.get("status")))
    if h.get("llm_configured"):
        check("已配全局 LLM：无 agent 的 run 用全局配置", s8.get("engine") == "llm",
              f"engine={s8.get('engine')}")
    else:
        check("未配 LLM 且无 agent：engine=mock、data_source=mock（页面标「mock 数据」）",
              s8.get("engine") == "mock" and s8.get("data_source") == "mock",
              f"engine={s8.get('engine')} data_source={s8.get('data_source')}")
        check("纯 mock 下 r3/r4 仍有内容（去重维度 > 0）",
              next((m["value"] for m in (s8.get("metrics") or []) if m["key"] == "dims"), 0) > 0,
              str([m for m in (s8.get("metrics") or []) if m["key"] == "dims"]))

    print("\n== 9. 真 LLM 数据形态的纯函数校验（不需要跑模型）==")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    try:
        import api_dataset
        import scene_matrix as smx
        import step1_runner as s1r

        session = next(s for s in smx.scenes() if s["name"] == "电商购物")
        dim_names = [d["name"] for c in session["categories"] for d in c["dims"]]
        # run45 里真 LLM 实际给出的参数名（qwen3.8-max）
        real_slugs = ["platform", "product_category", "product_brand", "product_spec",
                      "price_upper", "product_condition", "sort_method", "filter_tags",
                      "review_dimension", "purchase_quantity", "purchase_purpose",
                      "delivery_address", "delivery_method", "invoice_requirement", "after_sales"]
        mapped = [smx.match_dim(x, dim_names) for x in real_slugs]
        check("参数名语义映射能覆盖真 LLM 的参数命名",
              sum(1 for m in mapped if m) >= 14, f"{sum(1 for m in mapped if m)}/{len(real_slugs)}")
        check("delivery_address / delivery_method 不会挤到同一个维度",
              len({smx.match_dim("delivery_address", dim_names),
                   smx.match_dim("delivery_method", dim_names)}) == 2,
              f"{smx.match_dim('delivery_address', dim_names)} / "
              f"{smx.match_dim('delivery_method', dim_names)}")
        check("spec 不会误命中 special（整词优先）",
              smx.match_dim("special_req", ["规格分量", "特殊要求"]) == "特殊要求",
              str(smx.match_dim("special_req", ["规格分量", "特殊要求"])))
        check("映射不到维度时返回空（不再硬凑一个错维度）",
              smx.match_dim("zzz_unknown_zzz", dim_names) == "",
              repr(smx.match_dim("zzz_unknown_zzz", dim_names)))

        # 真 LLM 的 task 形态：有 parameters（值=planner 参数名），covered_dimensions 为空
        fake_task = {"task_id": "task-1", "domain": "住", "scenario": "购物",
                     "parameters": {k: "x" for k in real_slugs},
                     "full_instruction": "在淘宝上买两套床上四件套，走普通快递",
                     "underspecified_variants": [], "covered_dimensions": []}
        view = api_dataset.summarise({
            "id": 0, "status": "completed", "scene": "电商购物", "engine": "llm",
            "agent_id": "", "brief": "", "logs": [], "progress": {},
            "steps": {"planner": {"parameter_space": {
                          k: {"type": "categorical", "range": ["a", "b"], "description": "d"}
                          for k in real_slugs}},
                      "generator": {"task_set": [fake_task]}}})
        rows = (view.get("matrix") or {}).get("rows") or []
        active = sum(1 for r in rows if r.get("active"))
        check("真 LLM 的任务（无 covered_dimensions）也能折算出覆盖维度",
              active >= 13, f"active={active}/{len(rows)}")
        check("折算后矩阵真的有格点亮（而不是 0/182）",
              (view.get("matrix") or {}).get("covered", 0) > 0,
              f"covered={(view.get('matrix') or {}).get('covered')}/{(view.get('matrix') or {}).get('total')}")
        check("r5 去重维度 > 0",
              next((m["value"] for m in view["metrics"] if m["key"] == "dims"), 0) > 0,
              str(next((m["value"] for m in view["metrics"] if m["key"] == "dims"), None)))
        # r6 只回 min(参数空间, 8) 行（MAX_PARAM_ROWS），这里校验这 8 行的关联维度都合法
        row_dims = [p["dim"] for p in view["params"]]
        check("r6 关联维度命中真实维度，命中不了的留空（不瞎猜）",
              bool(row_dims) and all(d in dim_names or d == "" for d in row_dims)
              and sum(1 for d in row_dims if d) >= len(row_dims) - 1,
              str(row_dims))

        # 评分标度：真 LLM 给 0~1，mock 给 3~5，两者都不能被算成 0 覆盖度
        real_v = [{"task_id": "t1", "pass": True,
                   "scores": {"clarity": 0.95, "completeness": 1.0, "consistency": 0.97,
                              "feasibility": 0.95, "constraint_coverage": 0.9}}]
        m_real = s1r.compute_evaluator_metrics(real_v, 1)
        m_mock = s1r.compute_evaluator_metrics(
            [{"task_id": "t1", "pass": True,
              "scores": {"clarity": 5, "completeness": 5, "consistency": 5,
                         "feasibility": 5, "constraint_coverage": 5}}], 1)
        check("0~1 标度的真评分不被 `>=3.0` 误判（宽度/覆盖度都不为 0）",
              m_real["coverage_score"] > 0 and m_real["covered_capabilities"] == 5,
              f"coverage={m_real['coverage_score']} width={m_real['width']} scale={m_real['score_scale']}")
        check("5 分制（mock）行为不变：满分 → 覆盖度 1.0",
              m_mock["coverage_score"] == 1.0 and m_mock["score_scale"] == 5.0,
              f"coverage={m_mock['coverage_score']}")
    except Exception as e:  # noqa: BLE001
        check("纯函数校验可执行", False, f"{type(e).__name__}: {e}")

    print("\n" + "=" * 56)
    print(f"  结果: {PASS} passed, {FAIL} failed")
    print("=" * 56)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
