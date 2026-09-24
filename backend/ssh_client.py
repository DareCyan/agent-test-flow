# -*- coding: utf-8 -*-
"""SSH/SCP 传输层：把 install_doc 里的目标机器信息变成真实的 ssh/scp 调用。

只干三件事：拼命令、跑命令、如实回报（退出码 / stdout / stderr / 耗时）。
**不判断业务**（"装成功没有"由 api_install 决定），所以这一层很小、很好测。

约定：
  · 只支持密钥认证（`-i <私钥>`）；`BatchMode=yes` 让缺密钥/口令时**立刻失败**而不是挂住等输入。
  · `StrictHostKeyChecking=accept-new`：首次连接自动记 known_hosts，避免交互式提问卡死。
  · 展示用的命令里私钥只留文件名；真正的 argv 里才是完整路径。
  · 超时一律 kill 掉，并把 `timeout` 标出来（不要让一条卡住的命令拖住整个安装）。
"""

from __future__ import annotations

import os
import subprocess
import time

SSH_BIN = os.environ.get("ATF_SSH_BIN") or "ssh"
SCP_BIN = os.environ.get("ATF_SCP_BIN") or "scp"
CONNECT_TIMEOUT_S = int(os.environ.get("ATF_SSH_CONNECT_TIMEOUT") or 10)


class Machine:
    """一台待安装的目标机器（由 install_doc 的 target 段构造）。"""

    def __init__(self, target: dict):
        self.host = (target or {}).get("host") or ""
        self.port = int((target or {}).get("port") or 22)
        self.user = (target or {}).get("user") or ""
        auth = (target or {}).get("auth") or {}
        self.private_key = auth.get("private_key") or ""
        self.passphrase = auth.get("passphrase") or ""
        self.os = (target or {}).get("os") or "auto"

    @property
    def dest(self) -> str:
        return f"{self.user}@{self.host}"

    def key_label(self) -> str:
        return (self.private_key or "").replace("\\", "/").rsplit("/", 1)[-1] or "-"

    def opts(self, port_flag: str = "-p") -> list[str]:
        """公共选项。注意 **ssh 的端口是 `-p`、scp 是 `-P`**，别混（混了就是静默连 22）。"""
        o = ["-o", "BatchMode=yes",                     # 绝不交互：拿不到凭据就直接失败
             "-o", f"ConnectTimeout={CONNECT_TIMEOUT_S}",
             "-o", "StrictHostKeyChecking=accept-new",  # 首次连接自动写 known_hosts
             port_flag, str(self.port)]
        if self.private_key:
            o = ["-i", self.private_key] + o
        return o

    def show(self, remote_cmd: str) -> str:
        """给人看的等价命令（私钥只留文件名）。"""
        parts = ["ssh"]
        if self.private_key:
            parts += ["-i", self.key_label()]
        parts += [f"-p {self.port}", self.dest, repr(remote_cmd)]
        return " ".join(parts)


def _run(argv: list[str], timeout_s: float) -> dict:
    t0 = time.time()
    try:
        p = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                           timeout=max(1.0, float(timeout_s)), stdin=subprocess.DEVNULL)
        return {"ok": p.returncode == 0, "code": p.returncode,
                "out": (p.stdout or "").strip(), "err": (p.stderr or "").strip(),
                "ms": int((time.time() - t0) * 1000), "timeout": False}
    except subprocess.TimeoutExpired as e:
        return {"ok": False, "code": None,
                "out": (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes)
                       else (e.stdout or ""),
                "err": f"超时（>{timeout_s}s）", "ms": int((time.time() - t0) * 1000), "timeout": True}
    except FileNotFoundError as e:
        return {"ok": False, "code": None, "out": "", "err": f"找不到可执行文件：{e}",
                "ms": int((time.time() - t0) * 1000), "timeout": False}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "code": None, "out": "", "err": f"{type(e).__name__}: {e}",
                "ms": int((time.time() - t0) * 1000), "timeout": False}


def ssh_run(machine: Machine, remote_cmd: str, timeout_s: float = 60) -> dict:
    """在目标机器上跑一条命令。返回 _run 的结果 + 可展示的命令与目标。"""
    res = _run([SSH_BIN] + machine.opts() + [machine.dest, remote_cmd], timeout_s)
    res["show"] = machine.show(remote_cmd)
    res["target"] = machine.dest
    return res


def scp_put(machine: Machine, local_path: str, remote_dir: str,
            timeout_s: float = 600) -> dict:
    """把本机文件传到目标机器的目录（先确保目录存在由调用方负责）。"""
    remote = f"{machine.dest}:{remote_dir.rstrip('/')}/"
    argv = [SCP_BIN] + machine.opts("-P") + [local_path, remote]
    res = _run(argv, timeout_s)
    res["show"] = " ".join(["scp"] + ([f"-i {machine.key_label()}"] if machine.private_key else [])
                           + [f"-P {machine.port}",
                              f"{os.path.basename(local_path)} → {remote}"])
    res["target"] = machine.dest
    return res


def ssh_version() -> str:
    """本机 ssh 客户端版本（预检里展示一行环境信息，便于排查）。"""
    r = _run([SSH_BIN, "-V"], 10)
    return ((r.get("err") or "") + (r.get("out") or "")).strip().splitlines()[0] if (
        r.get("err") or r.get("out")) else "未知"
