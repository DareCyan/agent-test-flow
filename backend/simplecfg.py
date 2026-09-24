# -*- coding: utf-8 -*-
"""最简配置解析：JSON 与「扁平 k: v」YAML 双格式共用。

用同一套规则服务两个地方：
  · 智能体配置文件（r1 上传，含 api / key / model）
  · 后端 LLM 配置（backend/config.yaml 或 config.json）

支持范围（够用即止，不引 PyYAML）：
  key: value              # 字符串（引号可有可无）
  key: [a, b, c]          # 数组
  key: true / false       # 布尔
  key: 123                # 数字
  # 注释                  # 行首或行尾的 # 之后都当注释
不支持嵌套层级（不要写 `agent:\n  api: ...` 这种缩进结构）。
"""

from __future__ import annotations

import json
import re

_KV_RE = re.compile(r"^([A-Za-z_][\w\-.]*)\s*[:=]\s*(.+)$")


def parse_text(text: str) -> dict:
    """把 JSON 或扁平 YAML 文本解析成 dict；解析不出来就返回 {}。

    会先剥掉 UTF-8 BOM —— Windows 记事本 / 部分编辑器保存的 .yaml/.json 会带 BOM，
    否则第一行的键（或整个 JSON）会被当成非法字符而整份失效。
    """
    out: dict = {}
    if not text or not text.strip():
        return out
    stripped = text.lstrip("\ufeff").strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            if isinstance(data, dict):
                return data
        except Exception:
            pass  # 退化为按行解析，容忍半截 JSON
    for line in stripped.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-") or line.startswith("{"):
            continue
        m = _KV_RE.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip().strip('"\'')
        if val.startswith("[") and val.endswith("]"):
            out[key] = [x.strip().strip('"\'') for x in val[1:-1].split(",") if x.strip()]
        elif val.lower() in ("true", "false"):
            out[key] = val.lower() == "true"
        elif re.fullmatch(r"-?\d+", val):
            out[key] = int(val)
        elif re.fullmatch(r"-?\d*\.\d+", val):
            out[key] = float(val)
        else:
            out[key] = val
    return out


def first(parsed: dict, *keys, default: str = "") -> str:
    """按顺序取第一个非空字段（兼容 base_url / api / api_url 这类等价写法）。"""
    for k in keys:
        v = (parsed or {}).get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)):
            return str(v)
    return default


def as_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def deep_first(parsed: dict, *keys, default: str = "") -> str:
    """先在本层找，再在 llm / model / agent 这类常见子节点里找一层。"""
    v = first(parsed, *keys)
    if v:
        return v
    for sub in ("llm", "model", "agent", "config"):
        node = (parsed or {}).get(sub)
        if isinstance(node, dict):
            v = first(node, *keys)
            if v:
                return v
    return default


def deep_bool(parsed: dict, key: str, default: bool = False) -> bool:
    if isinstance((parsed or {}).get(key), (bool, str, int)):
        return as_bool((parsed or {}).get(key), default)
    for sub in ("llm", "model", "agent", "config"):
        node = (parsed or {}).get(sub)
        if isinstance(node, dict) and key in node:
            return as_bool(node.get(key), default)
    return default
