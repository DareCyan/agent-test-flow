#!/bin/bash
# 验证 docker load 是否直接支持 .tar.gz（决定安装包该用哪种格式）
set -uo pipefail
echo "docker 版本: $(docker version --format '{{.ServerVersion}}' 2>/dev/null)"
echo
echo "=== 测试：直接 docker load .tar.gz ==="
docker rmi -f opencode:1.18.32 >/dev/null 2>&1 || true
docker load -i /tmp/opencode-container-1.18.32-linux-amd64.tar.gz
echo "  直接 load gz 的 exit=$?"
docker images --format '  {{.Repository}}:{{.Tag}} {{.Size}}' | grep -i opencode || echo "  未加载成功"
echo
echo "=== 对照：gunzip 后再 load ==="
docker rmi -f opencode:1.18.32 >/dev/null 2>&1 || true
gunzip -c /tmp/opencode-container-1.18.32-linux-amd64.tar.gz > /tmp/oc-check.tar
docker load -i /tmp/oc-check.tar
echo "  解压后 load 的 exit=$?"
docker images --format '  {{.Repository}}:{{.Tag}} {{.Size}}' | grep -i opencode || echo "  未加载成功"
rm -f /tmp/oc-check.tar
