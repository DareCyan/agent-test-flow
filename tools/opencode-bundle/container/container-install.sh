#!/bin/bash
#
# Container-mode install & verification for the opencode CLI.
#
# Runs ON THE TARGET SERVER. Assumes the image tar has been copied to /tmp.
# The server does NOT need internet: the image is imported, not built.
#
#   bash container-install.sh [image-tar] [tag]
#
#   image-tar : path to a tar produced by build_container.py or `docker save`
#               (default: /tmp/opencode-container-1.18.32-linux-amd64.tar)
#   tag       : image tag to load as (default: opencode:1.18.32)

set -uo pipefail

TAR="${1:-/tmp/opencode-container-1.18.32-linux-amd64.tar}"
IMG="${2:-opencode:1.18.32}"
EXPECTED_INNER_SHA="513f500a1a5ea1dc7d865547ac87b32a8936334e8d5abd5b3ff585c45a170080"

c_grn=$'\033[0;32m'; c_red=$'\033[0;31m'; c_off=$'\033[0m'
ok()   { printf '  %sPASS%s %s\n' "$c_grn" "$c_off" "$1"; }
bad()  { printf '  %sFAIL%s %s\n' "$c_red" "$c_off" "$1"; }

pass=0; fail=0
check() { if [ "$1" = "0" ]; then ok "$2"; pass=$((pass+1)); else bad "$2"; fail=$((fail+1)); fi; }

echo "opencode 容器化安装"
echo "============================================="

# ---- 0. 前置 --------------------------------------------------------------
command -v docker >/dev/null 2>&1
check $? "docker 可用"

[ -f "$TAR" ]
check $? "镜像文件存在: $TAR"

# ---- 1. 导入 --------------------------------------------------------------
echo "--- docker load ---"
if docker load -i "$TAR" >/tmp/oc-load.log 2>&1; then
    ok "docker load 成功"
    sed 's/^/      /' /tmp/oc-load.log
    pass=$((pass+1))
else
    bad "docker load 失败"
    sed 's/^/      /' /tmp/oc-load.log
    fail=$((fail+1))
fi

docker image inspect "$IMG" >/dev/null 2>&1
check $? "镜像已就位: $IMG"

# ---- 2. 元数据 ------------------------------------------------------------
echo "--- 镜像元数据 ---"
docker inspect "$IMG" --format '  Entrypoint : {{json .Config.Entrypoint}}'
docker inspect "$IMG" --format '  Cmd        : {{json .Config.Cmd}}'
docker inspect "$IMG" --format '  WorkingDir : {{.Config.WorkingDir}}'
docker inspect "$IMG" --format '  Os/Arch    : {{.Os}}/{{.Architecture}}  Layers={{len .RootFS.Layers}}'

# ---- 3. 容器内运行 --------------------------------------------------------
echo "--- 容器内运行 ---"
ver=$(docker run --rm "$IMG" --version 2>&1)
[ "$ver" = "1.18.32" ]
check $? "容器内 opencode --version == 1.18.32  (实际: $ver)"

docker run --rm "$IMG" --help 2>&1 | grep -q 'Commands:'
check $? "容器内 opencode --help 输出正常"

docker run --rm "$IMG" debug paths 2>&1 | grep -q '^data'
check $? "容器内 opencode debug paths 正常（离线可用）"

# ---- 4. 二进制一致性 ------------------------------------------------------
echo "--- 二进制一致性 ---"
inner=$(docker run --rm --entrypoint sha256sum "$IMG" /usr/local/bin/opencode 2>/dev/null | awk '{print $1}' | tr -d '[:space:]')
[ "$inner" = "$EXPECTED_INNER_SHA" ]
check $? "容器内二进制 sha256 与官方产物一致"

size=$(docker run --rm --entrypoint stat "$IMG" -c '%s' /usr/local/bin/opencode 2>/dev/null | tr -d '[:space:]')
[ "$size" = "185165952" ]
check $? "容器内二进制大小 == 185,165,952  (实际: $size)"

mode=$(docker run --rm --entrypoint stat "$IMG" -c '%a' /usr/local/bin/opencode 2>/dev/null | tr -d '[:space:]')
[ "$mode" = "755" ]
check $? "容器内二进制权限 == 755  (实际: $mode)"

# ---- 5. 挂载工作目录 ------------------------------------------------------
echo "--- 挂载工作目录 ---"
WS=$(mktemp -d)
docker run --rm -v "$WS:/workspace" "$IMG" --version >/dev/null 2>&1
check $? "以 -v $WS:/workspace 运行成功"
rmdir "$WS" 2>/dev/null

# 注意：不能用 --entrypoint sh 测 WORKDIR —— 覆盖 entrypoint 会丢掉 WORKDIR。
# 这里走 env 转发，保留 ENTRYPOINT，让 WORKDIR 正常生效。
docker run --rm --entrypoint /usr/bin/env "$IMG" sh -c '[ "$(pwd)" = "/workspace" ]' >/dev/null 2>&1
check $? "默认工作目录是 /workspace"

# ---- 汇总 -----------------------------------------------------------------
echo "============================================="
printf '镜像      : %s\n' "$IMG"
printf '结果      : %s%d 通过%s, %s%d 失败%s\n' \
    "$c_grn" "$pass" "$c_off" "$([[ $fail -gt 0 ]] && printf '%s' "$c_red")" "$fail" "$c_off"
echo
echo "常用命令："
echo "  docker run --rm $IMG --version"
echo "  docker run --rm -it -v \$PWD:/workspace $IMG"
echo "  docker run --rm -v \$PWD:/workspace $IMG run \"帮我看看这个仓库\""

[ $fail -eq 0 ] || exit 1
