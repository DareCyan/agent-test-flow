#!/bin/bash
# 严格按 install.json 的步骤执行，把每条命令真实跑一遍并记录日志
set -uo pipefail

DOC=/tmp/install.json
REMOTE_DIR=/tmp/opencode-install
CFGDIR=/etc/opencode
VERSION=1.18.32
LOG=/tmp/install-json-run-$(date +%Y%m%d-%H%M%S).log

exec > >(tee "$LOG") 2>&1
echo "########## 按 install.json 执行安装 ##########"
echo "时间 : $(date -Is)   主机 : $(hostname)"
echo "文档 : $DOC"
echo

# 准备：把安装包和配置放到 remote_dir，模拟安装说明的前置条件
mkdir -p "$REMOTE_DIR"
cp /tmp/opencode-container-1.18.32-linux-amd64.tar.gz "$REMOTE_DIR/"
cp /tmp/opencode-config.json "$REMOTE_DIR/opencode.json"
echo "前置：$REMOTE_DIR 内容"
ls -l "$REMOTE_DIR" | sed 's/^/  /'
echo

# 用 python 把占位符按 install.json 的语义展开，然后逐条执行
python3 - "$DOC" <<'PY' > /tmp/install-steps.sh
import json, sys
doc = json.load(open(sys.argv[1], encoding='utf-8'))
ctx = {
    "agent": doc["agent"]["name"],
    "version": doc["agent"]["version"],
    "zip": doc["package"]["path"].rsplit("/", 1)[-1],
    "zip_name": doc["package"]["name"],
    "zip_sha256": doc["package"]["sha256"],
    "remote_dir": doc["install"]["remote_dir"].replace("{agent}", doc["agent"]["name"]),
    "workspace": doc["target"]["workspace"],
    "host": doc["target"]["host"],
    "port": str(doc["target"]["port"]),
    "user": doc["target"]["user"],
}
def expand(s):
    for k, v in ctx.items():
        s = s.replace("{" + k + "}", v)
    return s

print("# 由 install.json 自动生成，ctx=%s" % json.dumps(ctx, ensure_ascii=False))
for st in doc["install"]["steps"]:
    if st.get("skip"):
        print(f'echo "--- 步骤 {st["id"]}: 声明 skip，跳过 ---"')
        continue
    run = expand(st["run"])
    chk = expand(st.get("check") or "")
    print(f'echo "--- 步骤 {st["id"]}: {st.get("desc","")} ---"')
    print(f'echo "$ {run}"')
    print(f'{run}; _rc=$?; echo "  exit=$_rc"')
    if chk:
        print(f'echo "  校验: {chk}"')
        print(f'{chk} && echo "  check=OK" || echo "  check=FAIL"')
PY
echo "生成的执行脚本（占位符已按 install.json 展开）："
cat /tmp/install-steps.sh | sed 's/^/    /'
echo
echo "########## 逐条执行 ##########"
bash -x /tmp/install-steps.sh 2>&1 | grep -vE '^\+' | sed 's/^/  /' || true
echo
echo "########## 执行后状态 ##########"
docker images --format '  {{.Repository}}:{{.Tag}}  {{.Size}}' | grep -i opencode || echo "  无 opencode 镜像"
echo "  配置: $(ls -l "$CFGDIR/opencode.json" 2>/dev/null | awk '{print $1, $5, $9}')"
echo "  日志: $LOG"
