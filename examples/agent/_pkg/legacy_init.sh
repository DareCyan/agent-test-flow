#!/bin/sh
# 旧版初始化脚本（保底存在）。
#
# install.json 里 id=legacy 的步骤指向本文件，但声明了 "skip": true，
# 所以正常执行不会跑它；保留文件是为了让"计划里列出的每一步都真实存在"。
#
# 若哪天要真跑，它做的只是建出日志目录。
set -e
WORKSPACE="${1:-.}"
mkdir -p "$WORKSPACE/logs"
echo "legacy_init: ensured $WORKSPACE/logs"
