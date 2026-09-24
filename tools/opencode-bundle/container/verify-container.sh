#!/bin/bash
# 在目标服务器上：docker load 镜像 -> 起容器 -> 容器内验证 opencode
set -uo pipefail

TAR=/tmp/opencode-container-1.18.32-linux-amd64.tar
IMG=opencode:1.18.32
EXPECT_INNER=513f500a1a5ea1dc7d865547ac87b32a8936334e8d5ab5b3ff585c45a170080

echo "===[1] 镜像 tar 校验 ==="
ls -l "$TAR"
echo "sha256: $(sha256sum "$TAR" | awk '{print $1}')"
echo "expect: 024cb35a4f446b063a7463aed04841d25b8af0c02c675bb07d0bead1f9638c1b"
echo

echo "===[2] docker load ==="
docker load -i "$TAR"; echo "load exit=$?"
echo

echo "===[3] docker images ==="
docker images "$IMG"
echo

echo "===[4] 镜像元数据（Entrypoint/Cmd/WorkingDir/Layers） ==="
docker inspect "$IMG" --format 'Entrypoint={{json .Config.Entrypoint}} Cmd={{json .Config.Cmd}} WorkingDir={{.Config.WorkingDir}}'
docker inspect "$IMG" --format 'Size={{.Size}} Os={{.Os}} Arch={{.Architecture}}'
docker inspect "$IMG" --format 'Layers={{len .RootFS.Layers}}'
echo

echo "===[5] 容器内跑 opencode ==="
docker run --rm "$IMG" --version; echo "  --version exit=$?"
docker run --rm "$IMG" --help 2>&1 | head -8
docker run --rm "$IMG" debug paths | head -4
echo

echo "===[6] 容器内二进制与宿主机是否同一份 ==="
inner=$(docker run --rm --entrypoint sha256sum "$IMG" /usr/local/bin/opencode | awk '{print $1}')
echo "  container: $inner"
echo "  expected : $EXPECT_INNER"
[ "$inner" = "$EXPECT_INNER" ] && echo "  一致 ✓" || echo "  不一致 ✗"
echo

echo "===[7] 容器内 ELF 架构 ==="
docker run --rm --entrypoint readelf "$IMG" -h /usr/local/bin/opencode 2>/dev/null | grep -E 'Class:|Type:|Machine:' || echo "  (镜像里没有 readelf，属正常：只装了 CLI)"
echo

echo "===[8] 挂载工作目录跑一次 ==="
docker run --rm -v /tmp/oc-workspace:/workspace "$IMG" --version
docker run --rm "$IMG" sh -c 'echo "容器内 pwd=$(pwd)"; ls -l /usr/local/bin/opencode'
echo

echo "===[9] 镜像内是否含 python3/git（CLI 自身的可选依赖） ==="
for t in python3 git node; do
  if docker run --rm --entrypoint sh "$IMG" -c "command -v $t" >/dev/null 2>&1; then
    echo "  $t: 有"
  else
    echo "  $t: 无（ubuntu:24.04 基础镜像本来就没有，非必需）"
  fi
done
echo

echo "===[10] 容器安全/资源基线 ==="
docker run --rm "$IMG" --version >/dev/null && echo "  默认运行正常（非特权）"
docker ps -a --format '{{.Names}}' | head -5
docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}'
