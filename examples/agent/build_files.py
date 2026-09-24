"""
Build the three usable files in examples/agent/:
  1. shopping-agent-v2.zip        - coherent demo install package
  2. shopping-agent.yaml          - real config (carries the real credentials)
  3. shopping-agent-install.json  - already good; validated separately

The real credentials are copied straight from the existing local-only
shopping-agent.json (which holds the real gateway URL + key) in-process, so
the secret value is never printed or placed in an intermediate artifact.
"""
from __future__ import annotations

import json
import os
import shutil
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(HERE, "_pkg")
ZIP = os.path.join(HERE, "shopping-agent-v2.zip")
REAL = os.path.join(HERE, "shopping-agent.json")      # local-only, holds real creds
YAML = os.path.join(HERE, "shopping-agent.yaml")

# ---------------------------------------------------------------- 1. the zip
if not os.path.isdir(PKG):
    raise SystemExit(f"missing package source dir: {PKG}")

members = ["agent.py", "requirements.txt", "manifest.json", "README.txt", "legacy_init.sh"]
missing = [m for m in members if not os.path.isfile(os.path.join(PKG, m))]
if missing:
    raise SystemExit(f"missing package members: {missing}")

if os.path.exists(ZIP):
    os.remove(ZIP)

# Unix modes: scripts 0755, data 0644.
MODES = {"agent.py": 0o755, "legacy_init.sh": 0o755}

with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for name in members:
        src = os.path.join(PKG, name)
        zi = zipfile.ZipInfo.from_file(src, name)
        zi.external_attr = (MODES.get(name, 0o644) & 0xFFFF) << 16
        zi.compress_type = zipfile.ZIP_DEFLATED
        with open(src, "rb") as fh:
            z.writestr(zi, fh.read())

print(f"wrote {os.path.basename(ZIP)} ({os.path.getsize(ZIP):,} bytes)")
with zipfile.ZipFile(ZIP) as z:
    for i in z.infolist():
        print(f"   {oct(i.external_attr >> 16):>7}  {i.file_size:>6,}  {i.filename}")

# --------------------------------------------------------------- 2. the yaml
with open(REAL, encoding="utf-8") as f:
    real = json.load(f)

api = real.get("api") or real.get("base_url") or ""
key = real.get("key") or real.get("api_key") or ""
model = real.get("model") or ""
if not (api and key and model):
    raise SystemExit("shopping-agent.json is missing api/key/model")

yaml_text = f'''# ============================================================================
#  示例：电商购物智能体 · 真实配置（可直接上传到 r1「智能体配置文件」槽位）
#
#  ⚠ 本文件含【真实 key】，所以只存在于本地、不进仓库：
#     .gitignore 第 15 行的 `examples/agent/*` 把它排除在外。
#     需要提交的是 agent-config.template.yaml（占位 key），不是本文件。
#
#  预期接入结果（6 步识别日志）：
#    智能体接入中…                    ✓
#    单轮对话调用方式识别中…           ✓
#    多轮对话调用方式识别中…           ✓
#    配置文件识别中…                  ✓
#    模型联通性识别中…                ← 用下面的 api/key/model 真实探测
#    模型协议识别中…                  ✓
#
#  与 template 的区别：template 里的 key 是占位串，探测必然得到 401；
#  本文件是真实凭据，第 5 步会显示「可达（GET /models 200，N 个模型…）」。
#  完整 key 不会回显到页面/日志/接口，只出现脱敏掩码（profile.api_key_masked）。
# ============================================================================

name: {real.get("name") or "shopping-agent-v2"}

# ---- 必填三项（智能体自己的模型接入信息） ----
api: {api}
key: {key}
model: {model}

# ---- 可选 ----
protocol: {real.get("protocol") or "openai-compatible"}
call_modes: [{", ".join(real.get("call_modes") or ["单轮对话", "多轮对话"])}]

# 该智能体没有视觉能力 → r4 能力矩阵里「图像识别」整列不点亮
missing_capabilities: [{", ".join(real.get("missing_capabilities") or ["图像识别"])}]

# 也可按 L2 编号声明，或正向声明支持哪些能力（三选一，见 template）：
# missing_l2: [1.4]
# l2_capabilities: [1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.5, 4.1, 4.2, 4.3, 4.4, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8]
'''
with open(YAML, "w", encoding="utf-8", newline="\n") as f:
    f.write(yaml_text)

print(f"wrote {os.path.basename(YAML)} ({os.path.getsize(YAML):,} bytes)")
print(f"   api   = {api}")
print(f"   model = {model}")
print(f"   key   = ***masked*** (len={len(key)})")
