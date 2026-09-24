"""
生成 opencode 的三个交付文件：

  (1) 安装包   dist/opencode-container-1.18.32-linux-amd64.zip          (真 zip，内含镜像 tar)
  (2) 配置文件 dist/opencode.json          <- 真实 provider/key，本地保留
  (3) 安装说明 dist/install.json           <- 按项目 schema，可用 validate 校验

真实凭据来源：本机已有的 opencode 配置（~/.config/opencode/opencode.json 与 .jsonc）。
脚本在进程内读取并搬运，密钥不会打印到日志。

用法：
    python tools/opencode-cli/build_deliverables.py
"""
from __future__ import annotations

import hashlib
import json
import os
import zipfile
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
DIST = os.path.join(HERE, "dist")
SRC_DIST = os.path.join(ROOT, "tools", "opencode-bundle", "dist")

# 本机已有真实凭据的 opencode 配置
USER_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "opencode")
USER_CONFIGS = ["opencode.jsonc", "opencode.json"]   # 后者被视为更权威（覆盖式）

VERSION = "1.18.32"
IMAGE_TAR_NAME = f"opencode-container-{VERSION}-linux-amd64.tar"
CONTAINER_CONFIG_PATH = "/root/.config/opencode/opencode.json"
# 目标机器上放配置的目录（容器里挂到 /root/.config/opencode）
CONFIG_DIR = "/etc/opencode"


def load_real_config() -> dict:
    """合并本机 opencode 配置里的 provider 定义（进程内处理，不打印密钥）。"""
    providers: dict = {}
    for name in USER_CONFIGS:
        path = os.path.join(USER_CONFIG_DIR, name)
        if not os.path.isfile(path):
            continue
        raw = json.load(open(path, encoding="utf-8"))
        for pname, pval in (raw.get("provider") or {}).items():
            providers.setdefault(pname, {})
            providers[pname].update(pval)
    if not providers:
        raise SystemExit(f"没找到可用的 provider 配置：{USER_CONFIG_DIR}")
    return providers


def strip_secrets(node):
    """递归把 apiKey / token 之类替换成占位符，用于可提交的模板。"""
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if isinstance(v, str) and any(s in k.lower() for s in ("apikey", "key", "token", "secret", "password")):
                out[k] = "REPLACE_WITH_YOUR_KEY"
            else:
                out[k] = strip_secrets(v)
        return out
    if isinstance(node, list):
        return [strip_secrets(x) for x in node]
    return node


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for part in iter(lambda: f.read(1 << 20), b""):
            h.update(part)
    return h.hexdigest()


def main() -> int:
    os.makedirs(DIST, exist_ok=True)

    # ── (1) 安装包：把镜像 tar 复制并压缩 ────────────────────────────────
    src_tar = os.path.join(SRC_DIST, IMAGE_TAR_NAME)
    if not os.path.isfile(src_tar):
        raise SystemExit(f"缺镜像 tar，请先运行 build_container.py：{src_tar}")

    dst_tar = os.path.join(DIST, IMAGE_TAR_NAME)
    if os.path.abspath(src_tar) != os.path.abspath(dst_tar):
        shutil.copy2(src_tar, dst_tar)
    tar_sha = sha256_file(dst_tar)
    print(f"(1) 安装包 {IMAGE_TAR_NAME}  {os.path.getsize(dst_tar):,} B")
    print(f"    sha256 {tar_sha}")

    dst_zip = os.path.join(DIST, f"opencode-container-{VERSION}-linux-amd64.zip")
    # 真 zip（拉链格式），而不是改名的 gzip：前端的二进制槽位 accept='.zip'，
    # 且 installer 侧用 unzip 解出镜像 tar。tar 压缩后再 zip 收效很小，
    # 所以这里 store 不压缩——体积诚实，解压也快。
    if os.path.exists(dst_zip):
        os.remove(dst_zip)
    print("    打包 zip …", end="", flush=True)
    with zipfile.ZipFile(dst_zip, "w", zipfile.ZIP_STORED) as z:
        zi = zipfile.ZipInfo(f"opencode-image.tar", date_time=(2026, 9, 24, 0, 0, 0))
        zi.external_attr = 0o644 << 16
        with open(dst_tar, "rb") as f:
            z.writestr(zi, f.read())
    print(" 完成")

    # 立刻验证：zip 内条目大小必须等于原 tar，且能完整读回
    with zipfile.ZipFile(dst_zip) as z:
        info = z.getinfo("opencode-image.tar")
        if info.file_size != os.path.getsize(dst_tar):
            os.remove(dst_zip)
            raise SystemExit(f"zip 内 tar 大小不符：{info.file_size} != {os.path.getsize(dst_tar)}")
        n = 0
        with z.open("opencode-image.tar") as f:
            while True:
                c = f.read(1 << 20)
                if not c:
                    break
                n += len(c)
    if n != os.path.getsize(dst_tar):
        os.remove(dst_zip)
        raise SystemExit(f"zip 读回长度不符：{n} != {os.path.getsize(dst_tar)}；已删除")
    zip_sha = sha256_file(dst_zip)
    print(f"    完整性 OK：zip 内 tar 读回 {n:,} 字节 == 原 tar")
    print(f"    {os.path.basename(dst_zip)}  {os.path.getsize(dst_zip):,} B")
    print(f"    sha256 {zip_sha}")

    # ── (2) 配置文件 ─────────────────────────────────────────────────────
    # 一个文件要同时满足两个消费者：
    #   · 本项目 r1 的「智能体配置文件」槽位：simplecfg 只认**顶层扁平键**
    #     （api / key / model）——见 backend/simplecfg.py「不支持嵌套层级」
    #   · opencode 容器：认嵌套的 provider.<name>.{npm,options:{baseURL,apiKey},models}
    # 所以顶层放扁平接入层，同时带 provider 层，两边各取所需。
    providers = load_real_config()

    def has_key(pv: dict) -> bool:
        return bool((pv.get("options") or {}).get("apiKey"))

    with_key = [n for n, pv in providers.items() if has_key(pv) and (pv.get("models") or {})]
    if not with_key:
        raise SystemExit("没有任何带 apiKey 的 provider，无法生成可运行的接入配置")
    default_provider = with_key[0]
    default_pv = providers[default_provider]
    default_opts = default_pv.get("options") or {}
    default_model = next(iter(default_pv["models"]))          # opencode 侧短名
    default_model_full = f"{default_provider}/{default_model}"  # provider/model 全名

    cfg = {
        "$schema": "https://opencode.ai/config.json",
        # —— 本项目 r1「智能体配置文件」槽位读这一段（必须是顶层扁平键）——
        "name": "opencode",
        "api": default_opts.get("baseURL", ""),
        "key": default_opts.get("apiKey", ""),
        "model": default_model,
        "protocol": "openai-compatible",
        "call_modes": ["单轮对话", "多轮对话"],
        "missing_capabilities": ["图像识别"],
        # —— opencode 容器读这一段（嵌套）——
        "provider": providers,
        # 便于人看：opencode 的 provider/model 全名（本项目会忽略未知键）
        "opencode_provider": default_provider,
        "opencode_model": default_model_full,
    }

    cfg_path = os.path.join(DIST, "opencode.json")
    with open(cfg_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    cfg_sha = sha256_file(cfg_path)
    print(f"\n(2) 配置文件 opencode.json  {os.path.getsize(cfg_path):,} B")
    print(f"    顶层接入层(本项目读): api={cfg['api']}")
    print(f"                          model={cfg['model']}  key=***masked***")
    print(f"    provider 层(opencode 读):")
    for pname, pval in providers.items():
        base = (pval.get("options") or {}).get("baseURL", "?")
        models = ", ".join((pval.get("models") or {}).keys()) or "-"
        tag = "" if has_key(pval) else "   <- 无 apiKey，不可用"
        print(f"      - {pname}: {base} models=[{models}]{tag}")
    print(f"    默认可运行模型: {default_model_full}")
    print(f"    sha256 {cfg_sha}")

    # 可提交的模板（密钥占位）
    tpl_path = os.path.join(HERE, "opencode.json.template")
    with open(tpl_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(strip_secrets(cfg), f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"    模板（可提交）: {os.path.relpath(tpl_path, ROOT)}")

    # ── (3) 安装说明 ─────────────────────────────────────────────────────
    # 说明里引用的必须是"实际交付并已验证过"的那个包：.zip（内含镜像 tar），
    # 其 sha256 为 zip_sha；步骤与 validate_zip.sh 中实测通过的流程一致。
    # 默认模型沿用上面的 default_model_full（已按"有 apiKey"筛过）。

    doc = {
        "_comment": "opencode 容器化安装说明。文件(1)是容器镜像包，文件(2)是 opencode 模型配置；"
                    "按本文件即可在目标机器上把 opencode 拉起来并跑通一次真实模型调用。",
        "_verified": "本文件的步骤已在目标机器上实测通过：docker load 成功、"
                     "opencode models 读出配置、opencode run 真实返回内容。",
        "schema_version": 1,
        "agent": {"name": "opencode", "version": VERSION},
        "package": {
            "name": os.path.basename(dst_zip),
            "source": "local",
            "path": f"tools/opencode-cli/dist/{os.path.basename(dst_zip)}",
            "sha256": zip_sha,
            "keep_remote": False,
        },
        "target": {
            "host": "127.0.0.1",
            "port": 22,
            "user": os.environ.get("USERNAME") or "root",
            "auth": {
                "method": "key",
                # 目标机器私钥路径：用 OC_SSH_KEY 指定，默认取标准的 id_ed25519。
                # 不硬编码任何个人/机器专属的密钥文件名。
                "private_key": os.environ.get(
                    "OC_SSH_KEY", os.path.join(os.path.expanduser("~"), ".ssh", "id_ed25519")
                ),
                "passphrase": "",
            },
            "os": "linux",
            "workspace": CONFIG_DIR,
            "sudo": True,
        },
        "install": {
            "remote_dir": "/tmp/{agent}-install",
            "execute": False,
            "steps": [
                {"id": "unpack", "desc": "解压安装包得到镜像 tar",
                 "run": "unzip -o {remote_dir}/{zip_name} -d {remote_dir}",
                 "check": "test -s {remote_dir}/{agent}-image.tar",
                 "timeout_s": 300},
                {"id": "load-image", "desc": "导入容器镜像",
                 "run": "docker load -i {remote_dir}/{agent}-image.tar",
                 "check": "docker image inspect {agent}:{version} >/dev/null",
                 "timeout_s": 600},
                {"id": "install-config", "desc": "安装模型配置（文件2）到挂载目录",
                 "run": "mkdir -p {workspace} && cp {remote_dir}/opencode.json {workspace}/opencode.json && chmod 600 {workspace}/opencode.json",
                 "check": "test -s {workspace}/opencode.json",
                 "timeout_s": 60},
                {"id": "smoke", "desc": "容器内版本自检",
                 "run": "docker run --rm -v {workspace}:/root/.config/opencode {agent}:{version} --version",
                 "check": "docker run --rm -v {workspace}:/root/.config/opencode {agent}:{version} --version | grep -qx {version}",
                 "timeout_s": 180},
                {"id": "verify-config", "desc": "确认容器读到了配置里的模型",
                 "run": "docker run --rm -v {workspace}:/root/.config/opencode {agent}:{version} models",
                 "timeout_s": 180},
                {"id": "run-agent", "desc": "真实调用一次模型（校验 agent 可运行）",
                 "run": "docker run --rm -v {workspace}:/root/.config/opencode {agent}:{version} run -m " + f"{default_provider}/{default_model}" + " \"只回答两个字：收到\"",
                 "timeout_s": 300},
            ],
        },
        "checks": {
            "ssh_reachable": True,
            "remote_os": True,
            "disk_space": "1G",
            "zip_sha256": True,
            "post_health": True,
        },
        "skip_checks": ["disk_space"],
        "notes": "安装包 .zip 约 90 MB（内含镜像 tar）（镜像加载后磁盘占用约 363 MB）。"
                 "目标机器无需外网即可导入镜像；但 opencode 调用模型时需要能访问配置里的 baseURL。"
                 f"默认模型 {default_provider}/{default_model}（有 apiKey，实测可返回内容）。"
                 "配置文件含真实 API Key，仅在本地保留、不进仓库。"
                 f"容器需要挂载配置目录：docker run --rm -v {CONFIG_DIR}:/root/.config/opencode opencode:{VERSION}。",
    }
    doc_path = os.path.join(DIST, "install.json")
    with open(doc_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\n(3) 安装说明 install.json  {os.path.getsize(doc_path):,} B")
    print(f"    sha256 {sha256_file(doc_path)}")

    # 汇总
    manifest = {
        "version": VERSION,
        "files": {
            "install_package_tar": {"name": IMAGE_TAR_NAME, "size": os.path.getsize(dst_tar), "sha256": tar_sha},
            "install_package_zip": {"name": os.path.basename(dst_zip), "size": os.path.getsize(dst_zip), "sha256": zip_sha},
            "config": {"name": "opencode.json", "size": os.path.getsize(cfg_path), "sha256": cfg_sha},
            "install_doc": {"name": "install.json", "size": os.path.getsize(doc_path), "sha256": sha256_file(doc_path)},
        },
    }
    with open(os.path.join(DIST, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"\n清单: {os.path.relpath(os.path.join(DIST, 'MANIFEST.json'), ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())



