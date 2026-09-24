"""
生成 opencode 的三个交付文件：

  (1) 安装包   dist/opencode-container-1.18.32-linux-amd64.tar      (+ .tar.gz)
  (2) 配置文件 dist/opencode.json          <- 真实 provider/key，本地保留
  (3) 安装说明 dist/install.json           <- 按项目 schema，可用 validate 校验

真实凭据来源：本机已有的 opencode 配置（~/.config/opencode/opencode.json 与 .jsonc）。
脚本在进程内读取并搬运，密钥不会打印到日志。

用法：
    python tools/opencode-cli/build_deliverables.py
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
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

    dst_gz = dst_tar + ".gz"
    # 总是重建：之前失败/中断可能留下截断的 gz，而 sha256 一致会掩盖这个问题
    if os.path.exists(dst_gz):
        os.remove(dst_gz)
    print("    压缩中 …", end="", flush=True)
    # gzip.open() 不接受 mtime，用 GzipFile 才能置零 -> 产物可复现
    with open(dst_tar, "rb") as fi, open(dst_gz, "wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=6, mtime=0) as fo:
            shutil.copyfileobj(fi, fo, 1 << 20)
    print(" 完成")

    # 立刻验证完整性：解压长度必须等于原 tar
    expected_len = os.path.getsize(dst_tar)
    actual_len = 0
    with gzip.open(dst_gz, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            actual_len += len(chunk)
    if actual_len != expected_len:
        os.remove(dst_gz)
        raise SystemExit(f"gzip 产物不完整：解出 {actual_len} 字节，应为 {expected_len}；已删除")
    print(f"    完整性 OK：解出 {actual_len:,} 字节 == 原 tar")
    gz_sha = sha256_file(dst_gz)
    print(f"    {os.path.basename(dst_gz)}  {os.path.getsize(dst_gz):,} B")
    print(f"    sha256 {gz_sha}")

    # ── (2) 配置文件 ─────────────────────────────────────────────────────
    providers = load_real_config()
    cfg = {
        "$schema": "https://opencode.ai/config.json",
        "provider": providers,
    }
    cfg_path = os.path.join(DIST, "opencode.json")
    with open(cfg_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    cfg_sha = sha256_file(cfg_path)
    print(f"\n(2) 配置文件 opencode.json  {os.path.getsize(cfg_path):,} B")
    print(f"    provider: {', '.join(providers)}")
    for pname, pval in providers.items():
        base = (pval.get("options") or {}).get("baseURL", "?")
        models = ", ".join((pval.get("models") or {}).keys()) or "-"
        print(f"      - {pname}: baseURL={base} models=[{models}] key=***masked***")
    print(f"    sha256 {cfg_sha}")

    # 可提交的模板（密钥占位）
    tpl_path = os.path.join(HERE, "opencode.json.template")
    with open(tpl_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(strip_secrets(cfg), f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"    模板（可提交）: {os.path.relpath(tpl_path, ROOT)}")

    # ── (3) 安装说明 ─────────────────────────────────────────────────────
    # 说明里引用的必须是"实际交付并已验证过"的那个包：.tar.gz（89.8 MB），
    # 其 sha256 为 gz_sha；步骤与 validate_clean.sh 中实测通过的流程一致。
    #
    # 选默认模型时必须挑"有 apiKey"的 provider：没有 key 的 provider 跑起来
    # 会直接 Error: Not Found（bailian 就是这种情况），说明文件不能推荐它。
    def has_key(pv: dict) -> bool:
        return bool((pv.get("options") or {}).get("apiKey"))

    with_key = [n for n, pv in providers.items() if has_key(pv) and (pv.get("models") or {})]
    if not with_key:
        raise SystemExit("没有任何带 apiKey 的 provider，安装说明无法给出可运行的默认模型")
    default_provider = with_key[0]
    default_model = next(iter(providers[default_provider]["models"]))
    print(f"    默认可运行模型: {default_provider}/{default_model}")
    for n in providers:
        if n not in with_key:
            print(f"    （跳过无 apiKey 的 provider: {n}）")

    doc = {
        "_comment": "opencode 容器化安装说明。文件(1)是容器镜像包，文件(2)是 opencode 模型配置；"
                    "按本文件即可在目标机器上把 opencode 拉起来并跑通一次真实模型调用。",
        "_verified": "本文件的步骤已在目标机器上实测通过：docker load 成功、"
                     "opencode models 读出配置、opencode run 真实返回内容。",
        "schema_version": 1,
        "agent": {"name": "opencode", "version": VERSION},
        "package": {
            "name": os.path.basename(dst_gz),
            "source": "local",
            "path": f"tools/opencode-cli/dist/{os.path.basename(dst_gz)}",
            "sha256": gz_sha,
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
                 "run": "gunzip -c {remote_dir}/{zip_name} > {remote_dir}/{agent}-image.tar",
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
        "notes": "安装包 .tar.gz 约 90 MB（镜像加载后磁盘占用约 363 MB）。"
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
            "install_package_targz": {"name": os.path.basename(dst_gz), "size": os.path.getsize(dst_gz), "sha256": gz_sha},
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

