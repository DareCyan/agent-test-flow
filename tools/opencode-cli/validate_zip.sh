#!/bin/bash
# 用新的 .zip 安装包按 install.json 重新走一遍（unzip -> docker load -> 真实调用）
set -uo pipefail
ZIP=/tmp/opencode-container-1.18.32-linux-amd64.zip
REMOTE_DIR=/tmp/opencode-install
CFGDIR=/etc/opencode
IMG=opencode:1.18.32
cd "$REMOTE_DIR" || { mkdir -p "$REMOTE_DIR"; cd "$REMOTE_DIR"; }

echo "=== 文件1 校验（zip） ==="
ls -l "$ZIP"
act=$(sha256sum "$ZIP" | awk '{print $1}')
exp=484967a7fa3efa1976fb545adfae628ff562bca31aca4d746d14ef158230e163
echo "  实际 = $act"
echo "  期望 = $exp"
[ "$act" = "$exp" ] && echo "  => 通过 ✓" || echo "  => 失败 ✗"
cp "$ZIP" "$REMOTE_DIR/"

echo
echo "=== 清除镜像，确保从文件导入 ==="
docker rmi -f "$IMG" >/dev/null 2>&1; docker images | grep -c opencode | sed 's/^/  现存: /'

echo
echo "=== 步骤 unpack: unzip ==="
rm -f "$REMOTE_DIR/opencode-image.tar"
unzip -o "$REMOTE_DIR/opencode-container-1.18.32-linux-amd64.zip" -d "$REMOTE_DIR"
echo "  check: $(test -s "$REMOTE_DIR/opencode-image.tar" && echo OK || echo FAIL)"

echo
echo "=== 步骤 load-image ==="
docker load -i "$REMOTE_DIR/opencode-image.tar"
echo "  check: $(docker image inspect "$IMG" >/dev/null 2>&1 && echo OK || echo FAIL)"

echo
echo "=== 步骤 install-config / smoke / verify-config ==="
mkdir -p "$CFGDIR" && cp "$REMOTE_DIR/opencode.json" "$CFGDIR/opencode.json" && chmod 600 "$CFGDIR/opencode.json"
docker run --rm -v "$CFGDIR":/root/.config/opencode "$IMG" --version
docker run --rm -v "$CFGDIR":/root/.config/opencode "$IMG" models | tail -4

echo
echo "=== 步骤 run-agent（真实模型调用） ==="
docker run --rm -v "$CFGDIR":/root/.config/opencode "$IMG" run -m simapp/deepseek-flash "只回答两个字：收到"
echo "  exit=$?"

echo
echo "=== 结论 ==="
docker images --format '  {{.Repository}}:{{.Tag}} {{.Size}}' | grep -i opencode
