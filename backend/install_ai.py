# -*- coding: utf-8 -*-
"""安装说明文件的「AI 解读」：把给运维看的说明书读成结构化的前置条件/风险/建议顺序。

**这一层绝对不会产生可执行命令** —— 这是刻意的安全设计：
  · 送进模型的 payload 里没有任何机器凭据（host / user / 私钥 / 口令一律不发）；
  · 模型返回的内容只允许保留白名单字段（summary / prerequisites / risk_notes /
    step_order / questions / assumptions），出现 `command`、`steps[].run` 之类的
    **可执行内容一律丢弃并记账**（`dropped_keys`），前端会把丢弃这件事显示出来；
  · `step_order` 只是「建议顺序」，**不会改变真实执行顺序**（执行一律按文件里的顺序，
    差异只作为 `order_differs` 提示出来）；
  · 模型不可用/返回不合法 → 降级为确定性结果（`source: "fallback"`），绝不让接入失败。
"""

from __future__ import annotations

import json

import install_doc as ids
import llm

ALLOWED_KEYS = ("summary", "prerequisites", "risk_notes", "step_order",
                "questions", "assumptions")
_LIST_KEYS = ("prerequisites", "risk_notes", "step_order", "questions", "assumptions")
MAX_ITEMS = 12
MAX_LEN = 300

PROMPT = """你是一名交付工程师。下面是一份「智能体安装说明文件」的结构化内容（去掉机器凭据后的部分）。
请只做**解读**，不要设计或改写安装步骤，更不要输出任何可执行命令。

请只输出一个 JSON 对象（不要 markdown 围栏、不要解释），字段如下：
{
  "summary": "一句话说清这份说明书要干什么、装到哪",
  "prerequisites": ["执行前必须满足的前置条件，逐条"],
  "risk_notes": ["可能踩坑/有风险的地方，逐条；没有就给空数组"],
  "step_order": ["你建议的步骤执行顺序（只能填给出的 step id，不能增删步骤）"],
  "questions": ["文件里没说清、执行前需要向人确认的问题，逐条"],
  "assumptions": ["你为了理解而做的假设，逐条"]
}

硬性要求：
- 只能引用下面给出的 step id；不得新增、删除或重命名步骤。
- 不得输出任何命令、脚本、shell 片段（包括在 summary 里）。
- 不要复述机器地址、用户名等敏感信息。

安装说明文件（已脱敏）：
"""


def redacted_payload(doc: dict) -> dict:
    """送给模型的脱敏载荷：只有结构、步骤与说明；没有任何凭据。"""
    pkg = doc.get("package") or {}
    tgt = doc.get("target") or {}
    ins = doc.get("install") or {}
    return {
        "agent": doc.get("agent") or {},
        "package": {"name": pkg.get("name"), "source": pkg.get("source"),
                    "has_sha256": bool(pkg.get("sha256"))},
        "target": {"os": tgt.get("os"), "workspace": tgt.get("workspace"),
                   "sudo": bool(tgt.get("sudo")), "auth_method": (tgt.get("auth") or {}).get("method")},
        "install": {"execute": bool(ins.get("execute")), "remote_dir": ins.get("remote_dir"),
                    "steps": [{"id": s.get("id"), "desc": s.get("desc"), "cmd": s.get("cmd")}
                              for s in ids.resolve_steps(doc)]},
        "checks": ids.summary(doc).get("checks"),
        "skip_checks": list(doc.get("skip_checks") or []),
        "notes": doc.get("notes") or "",
    }


def _clean_list(v) -> list[str]:
    out = []
    if isinstance(v, str):
        v = [v]
    if isinstance(v, list):
        for item in v[:MAX_ITEMS]:
            if isinstance(item, (str, int, float)):
                s = str(item).strip()[:MAX_LEN]
                if s:
                    out.append(s)
    return out


def _fallback(reason: str) -> dict:
    return {"ok": False, "source": "fallback", "reason": reason, "summary": "",
            "prerequisites": [], "risk_notes": [], "step_order": [], "step_order_suggested": [],
            "order_differs": False, "questions": [], "assumptions": [], "dropped_keys": []}


def interpret(doc: dict, cfg: dict | None = None, timeout_s: int | None = None) -> dict:
    """解读一份（已校验的）安装说明文件。任何环节失败都降级，不抛异常。"""
    step_ids = [s["id"] for s in ids.resolve_steps(doc)]
    payload = redacted_payload(doc)
    prompt = PROMPT + json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    try:
        conf = cfg or llm.load_config()
        raw = llm.chat(prompt, conf, timeout=timeout_s)
    except Exception as e:  # noqa: BLE001 —— 无 LLM / 调用失败都走降级
        return _fallback(f"未解读（{type(e).__name__}: {e}）")

    parsed = llm.robust_json_parse(raw)
    if not isinstance(parsed, dict):
        return _fallback("未解读（模型输出不是 JSON 对象）")

    out = _fallback("")
    out["ok"] = True
    out["source"] = "llm"
    out["reason"] = ""

    # 白名单过滤：只留描述性字段；其余一律丢弃并记账（模型可能"顺手"给了命令）
    for k in parsed:
        if k not in ALLOWED_KEYS:
            out["dropped_keys"].append(str(k))
    out["summary"] = str(parsed.get("summary") or "").strip()[:MAX_LEN * 2]
    for k in _LIST_KEYS:
        out[k] = _clean_list(parsed.get(k))

    # step_order 只作为建议：过滤成已知 id、去重，且**不影响真实执行顺序**
    suggested = [s for s in out["step_order"] if s in step_ids]
    seen = set()
    suggested = [s for s in suggested if not (s in seen or seen.add(s))]
    out["step_order_suggested"] = suggested
    out["order_differs"] = bool(suggested) and suggested != [s for s in step_ids if s in suggested]
    out["step_order"] = suggested
    out["step_ids"] = step_ids
    return out
