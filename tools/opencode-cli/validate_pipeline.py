"""用后端真实代码链，验证上传的 opencode.json 能让「AI 解读」拿到 LLM 配置。

模拟 r1 接入时后端做的事：
  1. 读上传的配置文本 -> simplecfg.parse_text（与 api_agent 一致）
  2. 取 api/key/model -> _first
  3. 组装 override 交给 llm.load_config（backend/config.yaml 故意没写这三项，
     所以要靠第 120-133 行的"兜底用前端上传的智能体配置"）
  4. 检查 base_url / model 是否解析成功
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import api_agent      # noqa: E402
import llm            # noqa: E402
import simplecfg      # noqa: E402

CFG = os.path.join(ROOT, "tools", "opencode-cli", "dist", "opencode.json")
if not os.path.isfile(CFG):
    raise SystemExit(f"missing config: {CFG}")

text = open(CFG, encoding="utf-8").read()

print("=== 1) 解析上传的配置（与 r1 一致） ===")
parsed = simplecfg.parse_text(text)
print("   顶层字段:", sorted(parsed.keys()))

api = api_agent._first(parsed, "api", "base_url", "api_url", "endpoint", "model_api") or ""
key = api_agent._first(parsed, "api_key", "key", "apikey", "access_key", "model_api_key") or ""
model = api_agent._first(parsed, "model", "model_name", "model_id") or ""
print(f"   api={api}")
print(f"   model={model}")
print(f"   key={api_agent.mask_key(key)} (has_api_key={bool(key)})")

assert api and model, "本项目仍取不到 api/model"
print("   => 本项目识别通过 ✓")
print()

print("=== 2) 后端 LLM 配置解析（含对前端上传配置的兜底） ===")
override = {"base_url": api, "api_key": key, "model": model}
cfg = llm.load_config(override)
# 注意：load_config 返回的是 {"llm": {...}, ...}，真正的配置在 cfg["llm"] 里。
node = cfg.get("llm") or cfg
safe = {k: ("***" if "key" in k.lower() else v) for k, v in node.items()}
for k in sorted(safe):
    print(f"   {k} = {safe[k]}")

print()
ok = bool(node.get("base_url")) and bool(node.get("model")) and bool(node.get("api_key"))
print("=== 3) 结论 ===")
print(f"   config_source     = {node.get('config_source')}")
print(f"   from_agent_config = {node.get('from_agent_config')}")
print(f"   configured        = {node.get('configured')}")
print("   => AI 解读可用的 LLM 配置已就位 ✓" if ok else "   => 仍缺配置 ✗")
sys.exit(0 if ok else 1)
