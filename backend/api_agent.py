# -*- coding: utf-8 -*-
"""r1「智能体接入」后端：上传（二进制 + 配置）→ 逐项识别 → agent profile。

识别出的 profile 决定 r4 能力矩阵里哪一列不点亮（`missing` 能力列），
从而把 r1 与 r4 真正串起来。
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import llm
import scene_matrix as sm
import simplecfg
import store

ROOT = Path(__file__).resolve().parents[1]
UPLOAD_DIR = ROOT / "uploads"
AGENTS_PATH = ROOT / "data" / "agents.json"

# 与原 index 演示同序的 6 项识别
IDENT_STEPS = [
    "智能体接入中…",
    "单轮对话调用方式识别中…",
    "多轮对话调用方式识别中…",
    "配置文件识别中…",
    "模型联通性识别中…",
    "模型协议识别中…",
]

# 上传了「安装说明文件（install.json）」时**追加**的三步。
# 刻意做成条件追加：没有该文件时仍是原来的 6 步 —— 现有验收（"接入 console 输出 6 条识别日志"）
# 与前端节奏都不受影响。
INSTALL_STEPS = [
    "安装说明校验中…",
    "安装步骤解读中…",
    "目标机器连通性预检中…",
]

_agents: dict[str, dict] = {}
_lock = threading.RLock()


def _load() -> None:
    if not AGENTS_PATH.exists():
        return
    try:
        data = json.loads(AGENTS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            _agents.update(data)
    except Exception:
        pass


def _persist() -> None:
    try:
        AGENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        AGENTS_PATH.write_text(json.dumps(_agents, ensure_ascii=False, indent=2),
                               encoding="utf-8")
    except Exception:
        pass


_load()


def get(agent_id: str) -> dict | None:
    with _lock:
        a = _agents.get(agent_id)
        return dict(a) if a else None


def latest() -> dict | None:
    with _lock:
        if not _agents:
            return None
        return dict(list(_agents.values())[-1])


def missing_caps(agent_id: str | None) -> list[str]:
    """agent 不支持的能力列（index 里"每行不点亮的那一列"）。未接入时用默认值。"""
    a = get(agent_id) if agent_id else None
    if not a:
        return [sm.DEFAULT_MISSING_CAP]
    return list((a.get("profile") or {}).get("missing") or []) or [sm.DEFAULT_MISSING_CAP]


def supported_l2(agent_id: str | None) -> list[str]:
    a = get(agent_id) if agent_id else None
    if not a:
        return list(sm.L2_CODES)
    return list((a.get("profile") or {}).get("capabilities") or [])


# ── 配置解析：JSON 与扁平 YAML 共用 backend/simplecfg.py（与后端 LLM 配置同源）──
_parse_config_text = simplecfg.parse_text
_first = simplecfg.first


def mask_key(key: str) -> str:
    """API Key 脱敏：日志与接口响应里只出现掩码，绝不回显完整 key。"""
    key = (key or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return key[:4] + "****" + key[-4:]


def config_text_of(agent_id: str | None) -> str:
    """取该智能体接入时上传的配置原文（落盘在 `uploads/<agent_id>-<文件名>`）。

    用途：step1 的 LLM 来源兜底 —— **前端传什么就用什么**。
    前端在 r1「智能体配置文件」槽位上传的内容，后端原样存了下来，这里读回来给 step1 用。

    注意：必须**按 meta 里记的实际文件名**取。因为上传目录里现在还有「安装说明文件」
    （`<agent_id>-install.json`），若用 `glob(agent_id-*)` 取第一个，两者会互相抢
    （字母序上 install 常排在配置文件前面，把安装说明当成配置去解析 LLM 来源）。
    """
    if not agent_id:
        return ""
    try:
        p = _saved_file(agent_id, "config_saved_name")
        if p is not None:
            return p.read_text(encoding="utf-8", errors="replace")
        for p in sorted(UPLOAD_DIR.glob(f"{agent_id}-*")):
            if p.is_file() and not p.name.endswith(".meta.json") and "install" not in p.name.lower():
                return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return ""


def _saved_file(agent_id: str, key: str) -> Path | None:
    """按 `<agent_id>.meta.json` 里记的文件名取回落盘的上传物（没有则 None）。"""
    try:
        meta_path = UPLOAD_DIR / f"{agent_id}.meta.json"
        if not meta_path.exists():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        name = str(meta.get(key) or "").strip()
        p = UPLOAD_DIR / name if name else None
        return p if (p and p.is_file()) else None
    except Exception:
        return None


def llm_declared(agent_id: str | None) -> dict:
    """智能体配置里声明的 api / key / model（**含明文 key，仅服务端内部使用**）。

    只交给 `llm` 层去真正调模型；接口响应、日志、页面一律用掩码
    （`profile.api_key_masked`），不要把本函数的返回值直接塞进任何响应。
    """
    parsed = _parse_config_text(config_text_of(agent_id))
    return {
        "base_url": _first(parsed, "api", "base_url", "api_url", "endpoint", "model_api") or "",
        "api_key": _first(parsed, "api_key", "key", "apikey", "access_key", "model_api_key") or "",
        "model": _first(parsed, "model", "model_name", "model_id") or "",
    }


def _normalize_base(url: str) -> str:
    base = (url or "").strip().rstrip("/")
    if base and not re.search(r"/v\d+$", base) and not base.endswith("/chat/completions"):
        base = base + "/v1"
    return base


def _http_json(url: str, key: str, payload: dict | None = None, timeout: float = 2.5,
               extra_headers: dict | None = None, bearer: bool = True):
    """极简 HTTP 调用：返回 (status, data)。不抛异常；status=0 表示连接层失败。

    bearer=True 用 `Authorization: Bearer`（OpenAI 兼容），False 用 `x-api-key`（Anthropic 风格）。
    """
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    if key:
        headers["Authorization" if bearer else "x-api-key"] = \
            f"Bearer {key}" if bearer else key
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(body)
            except Exception:
                return resp.status, body
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        return e.code, detail
    except Exception as e:  # URLError / timeout / socket
        return 0, f"{type(e).__name__}: {e}"


_AUTH_CODES = (401, 403, 404, 405)


def _fail_detail(status: int, data) -> str:
    if status in (401, 403):
        return f"鉴权失败（HTTP {status}）"
    if status == 0:
        return f"端点不可达（{str(data)[:70]}）"
    return f"HTTP {status}"


def _content_of(data) -> str:
    """从 OpenAI 兼容响应里取文本内容（choices[0].message.content）。"""
    try:
        return str(data["choices"][0]["message"]["content"] or "")
    except Exception:
        try:
            return str(data["choices"][0]["text"] or "")
        except Exception:
            return ""


def _need(endpoint: str, model: str) -> tuple[str, str]:
    base = _normalize_base(endpoint)
    if not base or not model:
        return "", "未声明 api/model，无法实测"
    return base, ""


def probe_model(endpoint: str, key: str, model: str, timeout: float = 2.5) -> dict:
    """用智能体自己声明的 api/key/model 做一次轻量联通性探测。

    先 GET /models（最省）；端点不提供该方法时退化为一次 max_tokens=1 的最小对话请求。
    返回 {"ok": bool|None, "detail": str, "method": str}；ok=None 表示"没测出来"（鉴权/不可达）。
    """
    base, err = _need(endpoint, model)
    if not base:
        return {"ok": None, "detail": err, "method": ""}

    status, data = _http_json(base + "/models", key, timeout=timeout)
    if status == 200:
        names = []
        if isinstance(data, dict):
            names = [str(m.get("id")) for m in (data.get("data") or []) if isinstance(m, dict)]
        hit = f"，命中 {model}" if model and model in names else ""
        return {"ok": True, "detail": f"实测：可达（GET /models 200，{len(names)} 个模型{hit}）",
                "method": "GET /models"}
    if status in (401, 403):
        return {"ok": None, "detail": "未实测（" + _fail_detail(status, data) + "）", "method": "GET /models"}
    if status not in (404, 405, 400, 0):
        return {"ok": None, "detail": f"未实测（HTTP {status}）", "method": "GET /models"}

    payload = {"model": model or "default",
               "messages": [{"role": "user", "content": "ping"}],
               "max_tokens": 1}
    status2, data2 = _http_json(base + "/chat/completions", key, payload, timeout=timeout)
    if status2 == 200:
        return {"ok": True, "detail": "实测：可达（POST /chat/completions 200）",
                "method": "POST /chat/completions"}
    return {"ok": None, "detail": "未实测（" + _fail_detail(status2, data2) + "）",
            "method": "POST /chat/completions"}


def probe_single_turn(endpoint: str, key: str, model: str, timeout: float = 6.0) -> dict:
    """单轮对话调用方式：真发一条 user 消息，看是否返回非空内容。"""
    base, err = _need(endpoint, model)
    if not base:
        return {"ok": None, "detail": err}
    status, data = _http_json(base + "/chat/completions", key,
                              {"model": model,
                               "messages": [{"role": "user", "content": "只回复 pong"}],
                               "max_tokens": 8}, timeout=timeout)
    if status == 200:
        text = _content_of(data).strip()
        if text:
            return {"ok": True, "detail": f'实测：支持（回复 "{text[:12]}"）'}
        return {"ok": False, "detail": "实测：接口 200 但内容为空"}
    return {"ok": None, "detail": "未实测（" + _fail_detail(status, data) + "）"}


def probe_multi_turn(endpoint: str, key: str, model: str, timeout: float = 6.0) -> dict:
    """多轮对话调用方式：真发两轮（第二轮带上一轮真实回复），看是否记住上下文。"""
    base, err = _need(endpoint, model)
    if not base:
        return {"ok": None, "detail": err}
    first = "我叫小明，请只回复：记住了"
    status1, data1 = _http_json(base + "/chat/completions", key,
                                {"model": model, "messages": [{"role": "user", "content": first}],
                                 "max_tokens": 12}, timeout=timeout)
    if status1 != 200:
        return {"ok": None, "detail": "未实测（第一轮 " + _fail_detail(status1, data1) + "）"}
    reply = _content_of(data1).strip()
    if not reply:
        return {"ok": False, "detail": "实测：第一轮返回空内容"}

    status2, data2 = _http_json(base + "/chat/completions", key,
                                {"model": model,
                                 "messages": [{"role": "user", "content": first},
                                              {"role": "assistant", "content": reply},
                                              {"role": "user", "content": "我叫什么名字？只回复名字"}],
                                 "max_tokens": 12}, timeout=timeout)
    if status2 != 200:
        return {"ok": False,
                "detail": "实测：第二轮被拒（" + _fail_detail(status2, data2) + "），历史消息可能不被支持"}
    text = _content_of(data2)
    if "小明" in text:
        return {"ok": True, "detail": '实测：支持（记住了上一轮提到的"小明"）'}
    return {"ok": False, "detail": f'实测：接受历史但未记住（回 "{text.strip()[:12]}"）'}


def probe_protocol(endpoint: str, key: str, model: str, timeout: float = 6.0) -> dict:
    """模型协议：分别按 OpenAI 兼容与 Anthropic 风格各发一次，看哪种被接受。"""
    base, err = _need(endpoint, model)
    if not base:
        return {"ok": None, "protocol": "", "detail": err}

    st_o, d_o = _http_json(base + "/chat/completions", key,
                           {"model": model, "messages": [{"role": "user", "content": "ping"}],
                            "max_tokens": 4}, timeout=timeout)
    if st_o == 200 and isinstance(d_o, dict) and "choices" in d_o:
        return {"ok": True, "protocol": "openai-compatible",
                "detail": "实测：OpenAI 兼容（/chat/completions 返回 choices）"}

    st_a, d_a = _http_json(base + "/messages", key,
                           {"model": model, "max_tokens": 4,
                            "messages": [{"role": "user", "content": "ping"}]},
                           timeout=timeout, bearer=False,
                           extra_headers={"anthropic-version": "2023-06-01"})
    if st_a == 200 and isinstance(d_a, dict) and ("content" in d_a or "type" in d_a):
        return {"ok": True, "protocol": "anthropic",
                "detail": "实测：Anthropic 风格（/messages 返回 content）"}

    if st_o in (401, 403) or st_a in (401, 403):
        return {"ok": None, "protocol": "", "detail": "未实测（鉴权失败，无法判定协议）"}
    return {"ok": None, "protocol": "",
            "detail": f"未实测（/chat/completions HTTP {st_o}、/messages HTTP {st_a}）"}


def _scrub(parsed: dict) -> dict:
    """回显配置时抹掉 key 类字段。"""
    out = {}
    for k, v in (parsed or {}).items():
        if re.search(r"key|secret|token|password", str(k), re.I):
            out[k] = mask_key(str(v))
        else:
            out[k] = v
    return out


def _build_profile(agent_id: str, binary: dict, config: dict, cfg_text: str,
                   llm_cfg: dict, connectivity: dict | None = None,
                   probes: dict | None = None, install_report: dict | None = None) -> dict:
    probes = probes or {}
    parsed = _parse_config_text(cfg_text)
    name = (parsed.get("name") or parsed.get("agent_name")
            or (Path(binary.get("name") or "agent").stem) or "agent")
    declared_l2 = parsed.get("l2_capabilities") or parsed.get("capabilities") or []
    if isinstance(declared_l2, str):
        declared_l2 = [x.strip() for x in declared_l2.split(",") if x.strip()]

    # 声明的缺失：既支持 L2 编号，也支持 index 的 13 能力列名
    declared_missing = parsed.get("missing_l2") or parsed.get("missing_capabilities") or []
    if isinstance(declared_missing, str):
        declared_missing = [x.strip() for x in declared_missing.split(",") if x.strip()]
    missing_caps: list[str] = []
    for item in declared_missing:
        if item in sm.CAPS13_NAMES:
            missing_caps.append(item)
        else:
            for cap in sm.CAPS13:
                if item in cap["l2"] and cap["cap"] not in missing_caps:
                    missing_caps.append(cap["cap"])

    # 未声明时用默认：无视觉能力（对齐 index 原演示的 图像识别 不点亮）
    if not missing_caps and not declared_l2:
        missing_caps = [sm.DEFAULT_MISSING_CAP]
    missing_l2 = {code for cap in sm.CAPS13 if cap["cap"] in missing_caps for code in cap["l2"]}

    capabilities = [c for c in (declared_l2 or sm.L2_CODES) if c in sm.L2_BY_CODE]
    capabilities = [c for c in capabilities if c not in missing_l2]

    # 智能体自己声明的模型接入信息（api / key / model）——用于联通性识别
    endpoint = _first(parsed, "api", "base_url", "api_url", "endpoint", "model_api")
    api_key = _first(parsed, "api_key", "key", "apikey", "access_key", "model_api_key")
    model = _first(parsed, "model", "model_name", "model_id")
    connectivity = connectivity or {"ok": None, "detail": "未探测", "method": ""}

    def detected_call_modes() -> list:
        """实测通过的调用方式；都测不出来时退回默认值（并由 call_modes_source 标注）。"""
        out = []
        if (probes.get("single_turn") or {}).get("ok") is True:
            out.append("单轮对话")
        if (probes.get("multi_turn") or {}).get("ok") is True:
            out.append("多轮对话")
        return out or ["单轮对话", "多轮对话"]

    probed_protocol = (probes.get("protocol") or {}).get("protocol") or ""
    declared_protocol = _first(parsed, "protocol", "api_protocol")
    any_probe_ok = any((probes.get(k) or {}).get("ok") is True
                       for k in ("single_turn", "multi_turn", "connectivity", "protocol"))

    return {
        "agent_id": agent_id,
        "name": name,
        # 二进制（.zip 安装包）：只记录上传时的文件名/大小；不校验、不落盘、不解析
        "binary": binary.get("name") or "",
        "binary_size": binary.get("size") or "",
        "binary_stored": False,
        "config": config.get("name") or "",
        "config_size": config.get("size") or "",
        "call_modes": parsed.get("call_modes") or detected_call_modes(),
        "call_modes_source": "实测" if any_probe_ok else "按配置声明/默认",
        "protocol": probed_protocol or declared_protocol or (
            "openai-compatible" if endpoint else "未声明"),
        "protocol_source": "实测" if probed_protocol else (
            "按配置声明" if declared_protocol else "未确定"),
        "single_turn": probes.get("single_turn") or {"ok": None, "detail": "未探测"},
        "multi_turn": probes.get("multi_turn") or {"ok": None, "detail": "未探测"},
        "probes": probes,
        "verified": [k for k, v in probes.items()
                     if isinstance(v, dict) and v.get("ok") is True],
        "endpoint": endpoint,
        "model": model or "未声明",
        "api_key_masked": mask_key(api_key),
        "has_api_key": bool(api_key),
        "connectivity": connectivity,
        "capabilities": capabilities,
        "missing": missing_caps or [],
        "missing_l2": sorted(missing_l2),
        "capabilities_source": "配置文件声明" if (declared_l2 or declared_missing) else "默认值（未声明）",
        "llm_configured": bool((llm_cfg.get("llm") or {}).get("configured")),
        "backend_llm_model": ((llm_cfg.get("llm") or {}).get("model") or ""),
        "backend_llm_source": ((llm_cfg.get("llm") or {}).get("config_source") or ""),
        "declared": _scrub(parsed),
        # 安装说明文件（install.json）的处理结果：校验 / AI 解读 / SSH 预检 / 计划（全部脱敏）
        "install": install_report or {},
    }


def _worker(agent_id: str, binary: dict, config: dict, cfg_text: str,
            install_text: str = "", install_name: str = "") -> None:
    llm_cfg = llm.load_config()
    parsed = _parse_config_text(cfg_text)
    endpoint = _first(parsed, "api", "base_url", "api_url", "endpoint", "model_api")
    api_key = _first(parsed, "api_key", "key", "apikey", "access_key", "model_api_key")
    model = _first(parsed, "model", "model_name", "model_id")

    step = 0.35
    t0 = time.time()
    probes: dict = {}
    ins: dict = {}        # 安装说明文件的处理结果（校验 / 解读 / 预检 / 计划）
    doc: dict | None = None
    blocked = ""   # 一旦确认"测不了"（鉴权失败/不可达），后续探测直接标未实测，不再白等网络超时

    def run_probe(name: str, fn):
        """真探测一次；ok=None 表示没测出结论（并短路后续探测）。

        注意：短路时也必须把结果写进 probes —— 否则"端点不可达"这种最常见的情况下，
        profile 里反而看不到任何探测结论与原因。
        """
        nonlocal blocked
        if blocked:
            v = {"ok": None, "detail": f"未实测（{blocked}）"}
        else:
            v = fn()
            if v.get("ok") is None:
                d = str(v.get("detail") or "")
                if "鉴权失败" in d:
                    blocked = "鉴权失败"
                elif "不可达" in d:
                    blocked = "端点不可达"
        probes[name] = v
        return v

    steps = list(IDENT_STEPS) + (list(INSTALL_STEPS) if (install_text or "").strip() else [])
    for i, line in enumerate(steps):
        time.sleep(step)
        ok, text = True, line
        if i == 0:
            text = line + "（安装包按约定不校验、不落盘，只记文件名/大小）"
        elif i == 1:
            v = run_probe("single_turn", lambda: probe_single_turn(endpoint, api_key, model))
            ok, text = v.get("ok"), line + f"（{v.get('detail')}）"
        elif i == 2:
            v = run_probe("multi_turn", lambda: probe_multi_turn(endpoint, api_key, model))
            ok, text = v.get("ok"), line + f"（{v.get('detail')}）"
        elif i == 3:
            if cfg_text.strip():
                keys = list(parsed.keys())
                text = line + f"（实测：解析到 {len(keys)} 个字段 · " \
                    + ", ".join(keys[:5]) + ("…" if len(keys) > 5 else "") + "）"
            else:
                ok = False
                text = line + "（未提供配置文件，取不到 api/key/model）"
        elif i == 4:
            v = run_probe("connectivity", lambda: probe_model(endpoint, api_key, model))
            ok, text = v.get("ok"), line + f"（{v.get('detail')}）"
        elif i == 5:
            v = run_probe("protocol", lambda: probe_protocol(endpoint, api_key, model))
            ok, text = v.get("ok"), line + f"（{v.get('detail')}）"
        elif i == 6:
            # ── 安装说明文件：严格校验（带字段路径的错误） ──
            import install_doc as _ids
            ins["file"] = install_name
            try:
                rep = _ids.validate(_ids.parse(install_text), base_dir=ROOT)
                doc = rep["doc"]
                ins.update({"schema_ok": rep["ok"], "errors": rep["errors"],
                            "warnings": rep["warnings"]})
                if rep["ok"]:
                    import api_install
                    ins["plan"] = api_install.build_plan(doc, agent_id)
                    n_skip = len(doc["skip_checks"])
                    n_step_skip = sum(1 for s in doc["install"]["steps"] if s["skip"])
                    text = (line + f"（实测：{len(doc['install']['steps'])} 个安装步骤"
                            + (f"，其中 {n_step_skip} 步声明 skip" if n_step_skip else "")
                            + f"；跳过校验 {n_skip} 项；{len(rep['warnings'])} 条提醒；"
                            + ("文件已开 execute → 真执行" if _ids.effective_execute(doc)
                               else "文件未开 execute → dry-run") + "）")
                else:
                    ok = False
                    head = "；".join(f"{x['path']}: {x['msg']}" for x in rep["errors"][:2])
                    text = line + f"（失败：{len(rep['errors'])} 处 —— {head}）"
            except Exception as e:  # noqa: BLE001
                ok, doc = False, None
                ins.update({"schema_ok": False, "warnings": [],
                            "errors": [{"path": "", "msg": str(e)}]})
                text = line + f"（失败：{e}）"
        elif i == 7:
            # ── AI 解读：只产出描述性内容（前置条件/风险/待确认），绝不产生命令 ──
            if doc is None:
                ok = None
                text = line + "（跳过：安装说明校验不通过）"
            else:
                import install_ai
                ai = install_ai.interpret(doc, llm.load_config(llm_declared(agent_id)),
                                          timeout_s=120)
                ins["ai"] = ai
                if ai.get("ok"):
                    ok = True
                    tail = ""
                    if ai.get("order_differs"):
                        tail += "；模型建议顺序与文件不一致（仅作提示，不改变执行顺序）"
                    if ai.get("dropped_keys"):
                        tail += ("；已丢弃模型输出的非描述字段 "
                                 + ", ".join(ai["dropped_keys"][:3]) + "（这类字段不会被当成命令执行）")
                    text = (line + f"（实测：{ai['source']} · 前置条件 {len(ai['prerequisites'])} 条"
                            f" · 风险 {len(ai['risk_notes'])} 条"
                            f" · 待确认 {len(ai['questions'])} 条" + tail + "）")
                else:
                    ok = None
                    text = line + f"（{ai.get('reason') or '未解读'}）"
        elif i == 8:
            # ── 目标机器连通性预检（只读探测；失败不阻塞接入） ──
            if doc is None:
                ok = None
                text = line + "（跳过：安装说明校验不通过）"
            else:
                import api_install
                pc = api_install.precheck_ssh(doc)
                ins["precheck"] = pc
                tgt = doc.get("target") or {}
                who = f"{tgt.get('user')}@{tgt.get('host')}:{tgt.get('port')}"
                if pc["status"] == "pass":
                    ok = True
                    text = line + f"（实测：{who} {pc['detail']}）"
                elif pc["status"] == "skipped":
                    ok = None
                    text = line + f"（跳过：{pc['detail']}）"
                else:
                    ok = False
                    text = (line + f"（未通过：{who} {pc['detail']}）"
                                   "—— 不阻塞接入，可在 step3「安装执行」里重试")

        elapsed = time.time() - t0
        entry = {"ts": f"00:{int(elapsed):02d}.{int((elapsed % 1) * 100):02d}",
                 "text": text, "ok": ok}
        with _lock:
            a = _agents.get(agent_id)
            if a is None:
                return
            a["logs"].append(entry)
            _persist()
        store.publish_agent(agent_id, "log", entry)

    profile = _build_profile(agent_id, binary, config, cfg_text, llm_cfg,
                             probes.get("connectivity") or {"ok": None, "detail": "未探测",
                                                            "method": ""},
                             probes, install_report=(ins or None))
    with _lock:
        a = _agents.get(agent_id)
        if a is None:
            return
        a["profile"] = profile
        a["phase"] = "ready"
        _persist()
    store.publish_agent(agent_id, "ready", {"agent_id": agent_id, "profile": profile})


def connect(body: dict) -> dict:
    """创建一次接入：立即返回 agent_id，识别过程由后台线程推进（前端轮询/SSE）。"""
    binary = body.get("binary") or {}
    config = body.get("config") or {}
    cfg_text = body.get("config_content") or ""
    install = body.get("install") or {}
    install_text = body.get("install_content") or ""

    with _lock:
        n = len(_agents) + 1
        agent_id = f"agent-{n}"
        while agent_id in _agents:
            n += 1
            agent_id = f"agent-{n}"
        _agents[agent_id] = {
            "agent_id": agent_id,
            "phase": "connecting",
            "logs": [],
            "profile": None,
            "binary": binary,
            "config": config,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        _persist()

    # 落盘上传物：配置文件与安装说明真存文本（都用于后续执行/追溯），二进制只存元数据
    try:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        cfg_saved = ""
        if cfg_text:
            cfg_saved = f"{agent_id}-{(config.get('name') or 'config.yaml')}"
            (UPLOAD_DIR / cfg_saved).write_text(cfg_text, encoding="utf-8")
        # 安装说明文件单独命名，并把**实际文件名**记进 meta：否则 config_text_of 与
        # 安装流程的取文件都会 glob(agent_id-*) 而互相抢（把配置当安装说明去解析）。
        ins_saved = ""
        if install_text:
            ins_saved = f"{agent_id}-install-{(install.get('name') or 'install.json')}"
            (UPLOAD_DIR / ins_saved).write_text(install_text, encoding="utf-8")
        meta = {"agent_id": agent_id, "binary": binary, "config": config,
                "config_saved": bool(cfg_text), "config_saved_name": cfg_saved,
                "install": install, "install_saved": bool(install_text),
                "install_saved_name": ins_saved}
        (UPLOAD_DIR / f"{agent_id}.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    # 回放演示回退文件（未真实选择文件时，前端会带 fallback 名称）
    threading.Thread(target=_worker,
                     args=(agent_id, binary, config, cfg_text, install_text,
                           install.get("name") or ""),
                     name=f"agent-{agent_id}", daemon=True).start()
    return {"ok": True, "agent_id": agent_id, "steps": len(IDENT_STEPS) + (len(INSTALL_STEPS) if install_text.strip() else 0)}


def status(agent_id: str) -> dict:
    a = get(agent_id)
    if not a:
        return {"ok": False, "error": "agent not found"}
    return {"ok": True, "agent_id": agent_id, "phase": a.get("phase"),
            "logs": a.get("logs") or [], "profile": a.get("profile")}
