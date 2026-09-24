#!/bin/bash
# 端到端校验：文件1(zip) + 文件2(config) + 文件3(install.json) 一起用
# 期望的 sha256 从 MANIFEST.json 读取，避免硬编码过期
set -uo pipefail
ZIP=/tmp/opencode-container-1.18.32-linux-amd64.zip
CFG=/tmp/opencode-config.json
DOC=/tmp/install.json
MANIFEST=/tmp/MANIFEST.json
REMOTE_DIR=/tmp/opencode-install
CFGDIR=/etc/opencode
IMG=opencode:1.18.32

PY_SHA=$(python3 -c "
import json,hashlib,sys
m=json.load(open('$MANIFEST'))
f=m['files']['install_package_zip']
h=hashlib.sha256(open('$ZIP','rb').read()).hexdigest()
print(f\"{f['sha256']} {h} {'OK' if f['sha256']==h else 'MISMATCH'}\")
" 2>&1)

echo "=== 文件1 安装包 zip ==="
ls -l "$ZIP"
echo "  期望 sha256 : $(echo "$PY_SHA" | awk '{print $1}')"
echo "  实际 sha256 : $(echo "$PY_SHA" | awk '{print $2}')"
echo "  比对        : $(echo "$PY_SHA" | awk '{print $3}')"
echo

echo "=== 文件2 配置文件 ==="
ls -l "$CFG"
python3 - "$CFG" <<'PY'
import json,sys
p=json.load(open(sys.argv[1],encoding="utf-8"))
print("  顶层接入层(本项目):", {k:p.get(k) for k in ("api","model")}, "key=" + ("有" if p.get("key") else "无"))
print("  provider 层(opencode):", list((p.get("provider") or {}).keys()))
PY
echo

echo "=== 文件3 安装说明 ==="
ls -l "$DOC"
python3 -c "
import json
d=json.load(open('$DOC'))
print('  package:',d['package']['name'])
print('  steps  :',[s['id'] for s in d['install']['steps']])
"
echo

echo "=== 清除镜像，确保从文件导入 ==="
docker rmi -f "$IMG" >/dev/null 2>&1
echo "  现存 opencode 镜像: $(docker images | grep -c opencode)"
echo

echo "=== 按 install.json 的前 5 步执行 ==="
mkdir -p "$REMOTE_DIR"
cp "$ZIP" "$REMOTE_DIR/"; cp "$CFG" "$REMOTE_DIR/opencode.json"
cd "$REMOTE_DIR"
echo "--- unpack ---"
unzip -o "$REMOTE_DIR/opencode-container-1.18.32-linux-amd64.zip" -d "$REMOTE_DIR" >/dev/null
echo "  check: $(test -s opencode-image.tar && echo OK || echo FAIL)"
echo "--- load-image ---"
docker load -i opencode-image.tar | sed 's/^/  /'
echo "  check: $(docker image inspect "$IMG" >/dev/null 2>&1 && echo OK || echo FAIL)"
echo "--- install-config ---"
mkdir -p "$CFGDIR" && cp opencode.json "$CFGDIR/opencode.json" && chmod 600 "$CFGDIR/opencode.json"
echo "  check: $(test -s "$CFGDIR/opencode.json" && echo OK || echo FAIL)"
echo "--- smoke ---"
docker run --rm -v "$CFGDIR":/root/.config/opencode "$IMG" --version | sed 's/^/  /'
echo "--- verify-config ---"
docker run --rm -v "$CFGDIR":/root/.config/opencode "$IMG" models | sed 's/^/  /'
echo

echo "=== run-agent：真实模型调用 ==="
docker run --rm -v "$CFGDIR":/root/.config/opencode "$IMG" run -m simapp/deepseek-flash "只回答两个字：收到" 2>&1 | tail -2 | sed 's/^/  /'
echo

echo "=== 结论 ==="
docker images --format '  {{.Repository}}:{{.Tag}} {{.Size}}' | grep -i opencode
