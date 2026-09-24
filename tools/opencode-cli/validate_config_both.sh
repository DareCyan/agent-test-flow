#!/bin/bash
# 验证配置文件在两侧都能用：
#   A) 本项目解析器能取到 api/key/model，且模型端点真的可达
#   B) opencode 容器仍能读同一份文件并真实调用
set -uo pipefail
CFG=/tmp/opencode-config.json
CFGDIR=/etc/opencode
IMG=opencode:1.18.32

echo "=== 文件2 校验 ==="
ls -l "$CFG"
echo "  sha256 = $(sha256sum "$CFG" | awk '{print $1}')"
echo

echo "=== A) 本项目视角：解析顶层扁平键 ==="
python3 - "$CFG" <<'PY'
import json, re, sys, urllib.request, urllib.error
t = open(sys.argv[1], encoding="utf-8").read()
p = json.loads(t)
def first(d, *keys):
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""
api = first(p, "api", "base_url", "api_url", "endpoint", "model_api")
key = first(p, "api_key", "key", "apikey", "access_key", "model_api_key")
model = first(p, "model", "model_name", "model_id")
def mask(k):
    return (k[:4] + "****" + k[-4:]) if len(k) > 10 else "***"
print("  顶层字段:", sorted(p.keys()))
print("  api   =", api)
print("  model =", model)
print("  key   =", mask(key))
# 模拟 probe_model：GET {api}/models
base = api.rstrip("/")
if not re.search(r"/v\d+$", base) and not base.endswith("/chat/completions"):
    base = base + "/v1"
url = base + "/models"
try:
    r = urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": "Bearer " + key}), timeout=20)
    d = json.load(r)
    ids = [m.get("id") for m in (d.get("data") or [])]
    hit = f"，命中 {model}" if model in ids else f"，未含 {model}"
    print(f"  联通性: 可达（GET /models {r.status}，{len(ids)} 个模型{hit}）")
    print("  端点模型:", ids[:8], "..." if len(ids) > 8 else "")
except urllib.error.HTTPError as e:
    print(f"  联通性: HTTP {e.code} {e.reason}")
except Exception as e:
    print(f"  联通性: {type(e).__name__}: {e}")
PY
echo

echo "=== B) opencode 视角：同一份文件挂进容器 ==="
mkdir -p "$CFGDIR" && cp "$CFG" "$CFGDIR/opencode.json" && chmod 600 "$CFGDIR/opencode.json"
docker run --rm -v "$CFGDIR":/root/.config/opencode "$IMG" --version | sed 's/^/  version: /'
echo "  models:"
docker run --rm -v "$CFGDIR":/root/.config/opencode "$IMG" models | sed 's/^/    /'
echo "  真实调用:"
docker run --rm -v "$CFGDIR":/root/.config/opencode "$IMG" run -m simapp/deepseek-flash "只回答两个字：收到" 2>&1 | tail -2 | sed 's/^/    /'
