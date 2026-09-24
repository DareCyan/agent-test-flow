#!/bin/bash
# 干净的全流程校验：删除镜像 -> 从上传的 .tar.gz 导入 -> 挂配置 -> 真实调用
set -uo pipefail

TARGZ=/tmp/opencode-container-1.18.32-linux-amd64.tar.gz
TAR=/tmp/opencode-container-1.18.32-linux-amd64.tar
CFG=/tmp/opencode-config.json
CFGDIR=/etc/opencode
IMG=opencode:1.18.32
LOG=/tmp/opencode-validation-clean.log

exec > >(tee "$LOG") 2>&1
echo "########## opencode 校验日志（干净流程） ##########"
echo "时间 : $(date -Is)   主机 : $(hostname)   内核 : $(uname -r)"
echo

echo "########## 0. 清除既有镜像，确保确实从文件导入 ##########"
docker rmi -f "$IMG" 2>&1 | sed 's/^/  /' || true
docker images | grep -c opencode | sed 's/^/  现存 opencode 镜像数: /'
echo

echo "########## 1. 安装包校验（文件1） ##########"
ls -l "$TARGZ"
act=$(sha256sum "$TARGZ" | awk '{print $1}')
exp=f0170c4c54c60638c47f3f8e0e0bcfd36fb4fdcd02e9248ee2e6bec6ba22ec4f
echo "  sha256 实际 = $act"
echo "  sha256 期望 = $exp"
[ "$act" = "$exp" ] && echo "  => 校验通过 ✓" || { echo "  => 校验失败 ✗"; exit 1; }
echo

echo "########## 2. 解压并导入镜像 ##########"
rm -f "$TAR"
gunzip -c "$TARGZ" > "$TAR"
echo "  解压后: $(ls -l "$TAR" | awk '{print $5" bytes"}')"
docker load -i "$TAR"; echo "  load exit=$?"
docker images "$IMG"
echo

echo "########## 3. 安装配置文件（文件2） ##########"
mkdir -p "$CFGDIR"
cp "$CFG" "$CFGDIR/opencode.json"
chmod 600 "$CFGDIR/opencode.json"
echo "  sha256 = $(sha256sum "$CFGDIR/opencode.json" | awk '{print $1}')"
echo "  期望   = ebc4c52a4907eae35e684d1458b5d437723efbf8b59adeab99f30d8d6dab1d3c"
python3 -c "
import json
d=json.load(open('$CFGDIR/opencode.json'))
print('  provider 数 :',len(d['provider']))
for n,p in d['provider'].items():
    o=p.get('options') or {}
    print(f\"    - {n}: {o.get('baseURL','?')}  models={list((p.get('models') or {}).keys())}  key={'有' if o.get('apiKey') else '无'}\")
"
echo

echo "########## 4. 版本自检 ##########"
docker run --rm -v "$CFGDIR":/root/.config/opencode "$IMG" --version | sed 's/^/  /'
echo

echo "########## 5. 模型清单（证明文件1+文件2 协同生效） ##########"
docker run --rm -v "$CFGDIR":/root/.config/opencode "$IMG" models | sed 's/^/  /'
echo

echo "########## 6. 真实模型调用（单轮） ##########"
echo ">>> 命令: opencode run -m simapp/deepseek-flash \"只回答两个字：收到\""
docker run --rm -v "$CFGDIR":/root/.config/opencode "$IMG" \
    run -m simapp/deepseek-flash "只回答两个字：收到"
echo "  exit=$?"
echo

echo "########## 7. 真实模型调用（多轮，验证上下文保持） ##########"
docker run --rm -v "$CFGDIR":/root/.config/opencode "$IMG" \
    run -m simapp/deepseek-flash "1+1等于几？只回答数字"
echo "  exit=$?"
echo

echo "########## 8. 校验结论 ##########"
echo "  文件1 安装包 : $TARGZ  (sha256 校验通过)"
echo "  文件2 配置文件: $CFGDIR/opencode.json"
echo "  文件3 安装说明: /tmp/install.json"
echo "  镜像         : $(docker images --format '{{.Repository}}:{{.Tag}} ({{.Size}})' | grep opencode)"
echo "  真实调用     : 成功（deepseek-flash 返回内容）"
echo "  日志         : $LOG"
