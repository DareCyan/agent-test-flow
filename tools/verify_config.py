# -*- coding: utf-8 -*-
"""LLM 配置读取验收（对应 PLAN.md 第二层：从 json 或 yaml 读取）。

    python tools/verify_config.py [--base http://127.0.0.1:8787]

覆盖：
  · backend/config.yaml / config.yml / config.json 三种文件名
  · 扁平键值写法 与 旧版 {"llm": {...}} 嵌套写法
  · UTF-8 BOM（Windows 记事本保存的 YAML 会带 BOM —— 必须still能读）
  · 文件优先级 yaml > yml > json；文件不存在时回落 mock
会临时改写 backend/config.* 并**在结束时恢复原状**。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
CANDIDATES = ["config.yaml", "config.yml", "config.json"]
BASE = ""

PASS = FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f" · {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f" · {detail}" if detail else ""))


def health() -> dict:
    try:
        with urllib.request.urlopen(BASE + "/api/health", timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def write_cfg(name: str, text: str, bom: bool) -> None:
    for c in CANDIDATES:                      # 只留当前这一个配置文件
        p = BACKEND / c
        if p.exists():
            p.unlink()
    data = text.encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    (BACKEND / name).write_bytes(data)


def clear_cfg() -> None:
    for c in CANDIDATES:
        p = BACKEND / c
        if p.exists():
            p.unlink()


YAML_FLAT = "api: http://127.0.0.1:9/v1\nkey: sk-yamltest-abcdefghijklmnop\nmodel: yaml-model\n"
JSON_FLAT = '{"api":"http://127.0.0.1:9/v1","key":"sk-json-abcdefghijklmnop","model":"flat-json-model"}'
JSON_NESTED = ('{"llm":{"base_url":"http://127.0.0.1:9/v1",'
               '"api_key":"sk-nested-abcdefghijklmnop","model":"nested-json-model"}}')


def main() -> int:
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8787")
    BASE = ap.parse_args().base

    backup: dict[str, bytes] = {}
    for c in CANDIDATES:
        p = BACKEND / c
        if p.exists():
            backup[c] = p.read_bytes()
    print(f"（原有配置文件 {len(backup)} 个，测试结束会恢复）")

    try:
        print("\n== 1. 无配置文件 → 回落 mock ==")
        clear_cfg()
        h = health()
        check("健康检查可达", h.get("ok") is True, str(h.get("error", ""))[:60])
        check("未配置 LLM 时 engine=mock", h.get("engine") == "mock", str(h.get("engine")))
        check("config_source 为空", not h.get("llm_config_source"), repr(h.get("llm_config_source")))

        print("\n== 2. config.yaml（扁平写法）==")
        write_cfg("config.yaml", YAML_FLAT, bom=False)
        h = health()
        check("读到 yaml 的 model", h.get("llm_model") == "yaml-model", str(h.get("llm_model")))
        check("source = config.yaml", h.get("llm_config_source") == "config.yaml",
              str(h.get("llm_config_source")))
        check("api+model 齐全 → llm_configured=True", h.get("llm_configured") is True)
        check("engine=llm", h.get("engine") == "llm", str(h.get("engine")))

        print("\n== 3. config.yaml 带 UTF-8 BOM（Windows 记事本保存）==")
        write_cfg("config.yaml", YAML_FLAT, bom=True)
        h = health()
        check("BOM 不影响首行键 api", h.get("llm_configured") is True)
        check("BOM 下仍读到 model", h.get("llm_model") == "yaml-model", str(h.get("llm_model")))

        print("\n== 4. config.yml（另一种扩展名）==")
        write_cfg("config.yml", YAML_FLAT, bom=False)
        h = health()
        check("source = config.yml", h.get("llm_config_source") == "config.yml",
              str(h.get("llm_config_source")))
        check("model 读到", h.get("llm_model") == "yaml-model")

        print("\n== 5. config.json 扁平写法 ==")
        write_cfg("config.json", JSON_FLAT, bom=False)
        h = health()
        check("source = config.json", h.get("llm_config_source") == "config.json",
              str(h.get("llm_config_source")))
        check("model = flat-json-model", h.get("llm_model") == "flat-json-model",
              str(h.get("llm_model")))

        print("\n== 6. config.json 旧版嵌套写法 {\"llm\": {...}} ==")
        write_cfg("config.json", JSON_NESTED, bom=True)
        h = health()
        check("嵌套写法仍兼容（且带 BOM）", h.get("llm_model") == "nested-json-model",
              str(h.get("llm_model")))
        check("llm_configured=True", h.get("llm_configured") is True)

        print("\n== 7. 优先级 yaml > json ==")
        write_cfg("config.yaml", YAML_FLAT, bom=False)
        (BACKEND / "config.json").write_text(JSON_NESTED, encoding="utf-8")
        h = health()
        check("同时存在时取 config.yaml", h.get("llm_config_source") == "config.yaml",
              str(h.get("llm_config_source")))
        check("model 来自 yaml", h.get("llm_model") == "yaml-model", str(h.get("llm_model")))
    finally:
        clear_cfg()
        for name, data in backup.items():
            (BACKEND / name).write_bytes(data)
        print(f"\n（已恢复原有配置文件：{', '.join(backup) or '无'}）")

    print("\n" + "=" * 56)
    print(f"  配置读取验收: {PASS} passed, {FAIL} failed")
    print("=" * 56)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
