#!/bin/bash
# 在目标机器上用三个文件校验并运行 opencode，全程记录真实日志
set -uo pipefail

TARGZ=/tmp/opencode-container-1.18.32-linux-amd64.tar.gz
TAR=/tmp/opencode-container-1.18.32-linux-amd64.tar
CFG=/tmp/opencode-config.json
CFGDIR=/etc/opencode
IMG=opencode:1.18.32
LOG=/tmp/opencode-validation-$(date +%Y%m%d-%H%M%S).log

exec > >(tee "$LOG") 2>&1
echo "########## opencode 校验日志 ##########"
echo "时间     : $(date -Is)"
echo "主机     : $(hostname)  $(uname -r)"
echo "日志文件 : $LOG"
echo

echo "########## 1. 三个文件到位确认 ##########"
echo "--- (1) 安装包 ---"
ls -l "$TARGZ" "$TAR" 2>/dev/null
echo "  tar.gz sha256 = $(sha256sum "$TARGZ" 2>/dev/null | awk '{print $1}')"
echo "  期望          = 83ca6f8e5b5eb447a712126e5d57f6fc3b35284982a362809f13ea388a3378d8"
echo "--- (2) 配置文件 ---"
ls -l "$CFG"
echo "  config sha256 = $(sha256sum "$CFG" 2>/dev/null | awk '{print $1}')"
echo "  期望          = ebc4c52a4907eae35e684d1458b5d437723efbf8b59adeab99f30d8d6dab1d3c"
echo "--- (3) 安装说明 ---"
ls -l /tmp/install.json
python3 -c "import json;d=json.load(open('/tmp/install.json'));print('  schema_version =',d['schema_version']);print('  agent =',d['agent']);print('  steps =',[s['id'] for s in d['install']['steps']])"
echo

echo "########## 2. 导入镜像 (docker load) ##########"
gunzip -kf "$TARGZ" 2>/dev/null || true
ls -l "$TAR"
docker load -i "$TAR"
echo "load exit=$?"
docker images "$IMG"
echo

echo "########## 3. 安装配置文件 ##########"
mkdir -p "$CFGDIR"
cp "$CFG" "$CFGDIR/opencode.json"
chmod 600 "$CFGDIR/opencode.json"
ls -l "$CFGDIR/"
echo "容器内路径: /root/.config/opencode/opencode.json"
echo

echo "########## 4. 容器内自检：版本 ##########"
docker run --rm -v "$CFGDIR":/root/.config/opencode "$IMG" --version
echo "exit=$?"
echo

echo "########## 5. 容器内读取模型配置（证明第 2 个文件生效） ##########"
docker run --rm -v "$CFGDIR":/root/.config/opencode "$IMG" models
echo "exit=$?"
echo

echo "########## 6. 容器内真实调用模型 ##########"
PROMPT="只回答两个字：收到"
echo "--- 尝试 provider/model 组合 ---"
for m in "simapp/deepseek-flash" "simapp/deepseek-v4-pro" "simapp/deepseek-chat"; do
    echo ">>> opencode run -m $m"
    out=$(timeout 120 docker run --rm -v "$CFGDIR":/root/.config/opencode "$IMG" run -m "$m" "$PROMPT" 2>&1)
    rc=$?
    echo "$out" | head -20 | sed 's/^/    /'
    echo "    exit=$rc"
    if [ $rc -eq 0 ] && [ -n "$out" ]; then
        echo ">>> 成功：$m"
        export WORKING_MODEL="$m"
        break
    fi
done

echo
echo "########## 7. 结果汇总 ##########"
echo "镜像     : $(docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' | grep opencode || echo '未加载')"
echo "配置     : $CFGDIR/opencode.json"
echo "可用模型 : ${WORKING_MODEL:-未找到可调用的模型}"
echo "日志     : $LOG"
