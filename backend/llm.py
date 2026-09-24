# -*- coding: utf-8 -*-
"""LLM 调用层：OpenAI 兼容 chat/completions + 稳健 JSON 解析 + 配置读取。

无配置或调用失败时由上层（step1_runner）降级为确定性 mock，因此本模块只负责
"能调就调"，不负责降级决策。
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

import simplecfg

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
# 同一份配置可以是 JSON 也可以是扁平 YAML，先找到哪个用哪个（顺序即优先级）
CONFIG_CANDIDATES = ("config.yaml", "config.yml", "config.json")
CONFIG_PATH = BACKEND_DIR / "config.json"   # 兼容旧引用

_DEFAULT_TIMEOUT = 300
# 默认 300s：实测推理模型（如 qwen3.8-max）单次 verifier 调用就要 ~245s（含 3 万+ 字推理），
# 180s 会让该步超时→降级 mock。慢模型请在 config.yaml 里把 timeout 调大。
_DEFAULT_MAX_TOKENS = 32768
# 默认 32768：给推理模型的长 JSON 输出留足余量，只砍掉极端长尾（不设上限时它会一路吐到几万字，
# 单次调用能拖到十几分钟）。**别调太小**——截断的 JSON 解析不出来 → 重试 → 最后仍降级 mock。
# 设 0 表示显式关闭，请求体里不带 max_tokens。
_max_tokens: int | None = None   # 最近一次实际生效值，供 /api/health 观测
_last_error: str = ""


def find_config_file() -> Path | None:
    for name in CONFIG_CANDIDATES:
        p = BACKEND_DIR / name
        if p.exists():
            return p
    return None


def file_config() -> dict:
    """读 `backend/config.*` 的原始键值（扁平 YAML 或 JSON）。

    与 load_config 的区别：这里不做 base_url/model 的兜底与归一化，只给
    「行为参数」（timeout / max_tokens / 并发 / fallback_to_mock）用，
    这样即使配置文件里不写 api/key/model（仍然用 r1 上传的智能体配置），
    也能单独把行为参数调大。
    """
    path = find_config_file()
    if path is None:
        return {}
    try:
        return simplecfg.parse_text(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_config(override: dict | None = None) -> dict:
    """配置优先级：环境变量 > backend/config.yaml > config.yml > config.json > override。

    两种文件格式用同一套解析（backend/simplecfg.py）：JSON 对象，或扁平 `k: v` YAML。
    键名兼容 api / base_url / api_url、key / api_key、model / model_name；
    也接受 {"llm": {...}} 这种嵌套写法（旧 config.json 不用改）。

    `override` 是**兜底**来源：由 step1 传入「本次运行的智能体配置里声明的 api/key/model」
    （来自 r1 前端上传的配置文件，见 api_agent.llm_declared）。**前端传什么就用什么** ——
    也就是说：没人另行配置 LLM 时，就用上传的智能体配置去调模型；反之以上级来源为准。
    """
    path = find_config_file()
    raw: dict = {}
    if path is not None:
        try:
            raw = simplecfg.parse_text(path.read_text(encoding="utf-8"))
        except Exception:
            raw = {}

    llm: dict = {
        "base_url": (simplecfg.deep_first(raw, "base_url", "api", "api_url",
                                          "endpoint", "openai_base_url") or "").rstrip("/"),
        "api_key": simplecfg.deep_first(raw, "api_key", "key", "apikey",
                                        "access_key", "openai_api_key"),
        "model": simplecfg.deep_first(raw, "model", "model_name", "model_id"),
        "timeout": simplecfg.deep_first(raw, "timeout", "timeout_s"),
        "max_tokens": simplecfg.deep_first(raw, "max_tokens", "max_output_tokens", "maxtokens"),
        "temperature": simplecfg.deep_first(raw, "temperature"),
        "fallback_to_mock": simplecfg.deep_bool(raw, "fallback_to_mock", True),
        "config_source": path.name if path else "",
        "config_path": str(path) if path else "",
    }

    overrides = []
    if os.environ.get("LLM_BASE_URL"):
        llm["base_url"] = os.environ["LLM_BASE_URL"]
        overrides.append("LLM_BASE_URL")
    if os.environ.get("LLM_API_KEY"):
        llm["api_key"] = os.environ["LLM_API_KEY"]
        overrides.append("LLM_API_KEY")
    if os.environ.get("LLM_MODEL"):
        llm["model"] = os.environ["LLM_MODEL"]
        overrides.append("LLM_MODEL")
    if os.environ.get("LLM_TIMEOUT_S"):
        try:
            llm["timeout"] = int(os.environ["LLM_TIMEOUT_S"])
            overrides.append("LLM_TIMEOUT_S")
        except ValueError:
            pass
    if os.environ.get("LLM_MAX_TOKENS"):
        try:
            llm["max_tokens"] = int(os.environ["LLM_MAX_TOKENS"])
            overrides.append("LLM_MAX_TOKENS")
        except ValueError:
            pass
    if overrides:
        llm["config_source"] = (llm["config_source"] + " + " if llm["config_source"] else "") \
            + "env:" + ",".join(overrides)

    # 兜底：上面两个来源都没给出 base_url + model 时，用 override（前端上传的智能体配置）
    ov = override or {}
    if not (llm.get("base_url") and llm.get("model")):
        o_base = (ov.get("base_url") or "").strip().rstrip("/")
        o_model = (ov.get("model") or "").strip()
        o_key = (ov.get("api_key") or "").strip()
        if o_base and o_model:
            llm["base_url"] = o_base
            llm["model"] = o_model
            if o_key:
                llm["api_key"] = o_key
            llm["config_source"] = (llm["config_source"] + " + " if llm["config_source"] else "") \
                + "agent-config(前端上传的智能体配置)"
            llm["from_agent_config"] = True

    base = (llm.get("base_url") or "").rstrip("/")
    if base and not re.search(r"/v\d+$", base) and not base.endswith("/chat/completions"):
        base = base + "/v1"
    llm["base_url"] = base
    try:
        llm["timeout"] = int(llm["timeout"]) if llm.get("timeout") else _DEFAULT_TIMEOUT
    except (TypeError, ValueError):
        llm["timeout"] = _DEFAULT_TIMEOUT
    try:
        # 0 / 负数 = 显式关闭（请求体里不带 max_tokens），其它值按上限原样下发
        llm["max_tokens"] = (int(llm["max_tokens"]) if llm.get("max_tokens") not in (None, "")
                             else _DEFAULT_MAX_TOKENS)
    except (TypeError, ValueError):
        llm["max_tokens"] = _DEFAULT_MAX_TOKENS
    try:
        llm["temperature"] = float(llm["temperature"]) if llm.get("temperature") not in (None, "") else 0.7
    except (TypeError, ValueError):
        llm["temperature"] = 0.7
    llm["configured"] = bool(base and llm.get("model"))
    return {"llm": llm}


def last_error() -> str:
    return _last_error


def max_tokens_effective() -> int | None:
    """最近一次请求实际下发的 max_tokens；None = 未启用（或还没调过 LLM）。"""
    return _max_tokens


def is_configured(cfg: dict | None = None) -> bool:
    cfg = cfg or load_config()
    return bool((cfg.get("llm") or {}).get("configured"))


def chat(prompt: str, cfg: dict | None = None, timeout: int | None = None,
         max_tokens: int | None = None) -> str:
    """调 OpenAI 兼容 /chat/completions，返回 assistant 文本。失败抛异常。

    `timeout` / `max_tokens` 不传就用配置值（默认 300s / 32768）；
    `max_tokens=0` 表示这一次显式不带该字段（交由服务端默认）。
    """
    global _last_error, _max_tokens
    cfg = cfg or load_config()
    llm = cfg.get("llm") or {}
    base, key, model = llm.get("base_url", ""), llm.get("api_key", ""), llm.get("model", "")
    if not base or not model:
        _last_error = "LLM 未配置（缺 base_url / model）"
        raise RuntimeError(_last_error)

    mt = llm.get("max_tokens") if max_tokens is None else max_tokens
    try:
        mt = int(mt) if mt not in (None, "") else _DEFAULT_MAX_TOKENS
    except (TypeError, ValueError):
        mt = _DEFAULT_MAX_TOKENS
    _max_tokens = mt if mt > 0 else None

    url = base if base.endswith("/chat/completions") else base + "/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": float(llm.get("temperature", 0.7) or 0.7),
    }
    if mt > 0:
        payload["max_tokens"] = mt
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout or int(llm.get("timeout") or _DEFAULT_TIMEOUT)) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        _last_error = f"HTTP {e.code}: {detail}"
        raise RuntimeError(_last_error) from e
    except Exception as e:  # URLError / timeout / socket
        _last_error = f"{type(e).__name__}: {e}"
        raise RuntimeError(_last_error) from e

    try:
        data = json.loads(raw)
        content = data["choices"][0]["message"]["content"]
    except Exception as e:
        _last_error = f"响应结构异常: {raw[:200]}"
        raise RuntimeError(_last_error) from e
    if not isinstance(content, str) or not content.strip():
        _last_error = "模型返回空内容"
        raise RuntimeError(_last_error)
    return content


# ── 稳健 JSON 解析（移植自原项目 _robust_json_parse 的等价实现）──────────────
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def robust_json_parse(raw: str):
    """尽力从模型输出里抠出 JSON：剥围栏 → 直接 parse → 截取首个 {...} / [...] → 修尾逗号。"""
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    text = str(raw).strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    for candidate in (text, _first_balanced(text, "{", "}"), _first_balanced(text, "[", "]")):
        if not candidate:
            continue
        for attempt in (candidate, re.sub(r",\s*([}\]])", r"\1", candidate)):
            try:
                return json.loads(attempt)
            except Exception:
                continue
    return None


def _first_balanced(text: str, open_ch: str, close_ch: str) -> str | None:
    """截取首个括号平衡片段（忽略字符串内的括号）。"""
    start = text.find(open_ch)
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def extract_first(parsed, key: str) -> dict | None:
    """兼容三种返回形态取首个 dict（移植自原项目同名函数）。"""
    if not parsed:
        return None
    if isinstance(parsed, list):
        return parsed[0] if parsed and isinstance(parsed[0], dict) else None
    if isinstance(parsed, dict):
        val = parsed.get(key)
        if isinstance(val, list):
            return val[0] if val and isinstance(val[0], dict) else None
        if isinstance(val, dict):
            return val
        return parsed
    return None
