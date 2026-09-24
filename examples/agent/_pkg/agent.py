#!/usr/bin/env python3
"""shopping-agent-v2 —— 示例智能体（占位实现，用于 r1/r7 安装流程演示）。

这个文件的意义不是"能真正购物"，而是让安装说明里的校验步骤有东西可校验：
  install.json 的 verify 步骤断言 `{workspace}/agent.py` 存在，本文件就是它。

真实接入时，把本包替换成被测智能体自己的安装包即可 —— 后端只记录文件名与
大小（binary_stored: false），不解析包内容，所以替换不会改变流程行为。
"""
from __future__ import annotations

import argparse
import json
import socket
import sys

__version__ = "2.0.3"

CAPABILITIES = ["单轮对话", "多轮对话"]
# 该示例智能体没有视觉能力 → r4 能力矩阵里「图像识别」整列不点亮
MISSING_CAPABILITIES = ["图像识别"]


def install_step(workspace: str) -> dict:
    """模拟安装步骤：真实智能体在这里做初始化（建索引、拉模型、写配置）。"""
    return {
        "ok": True,
        "workspace": workspace,
        "message": "shopping-agent-v2 初始化完成（示例实现，未做实际工作）",
    }


def health_check(port: int = 8000) -> dict:
    """返回一个固定端口是否在监听，供安装后的 post_health 检查参考。"""
    with socket.socket() as s:
        s.settimeout(1.0)
        listening = s.connect_ex(("127.0.0.1", port)) == 0
    return {"ok": listening, "port": port, "listening": listening}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="shopping-agent-v2 (示例智能体)")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--workspace", default=".", help="工作目录")
    p.add_argument("--health", action="store_true", help="只检查 8000 端口")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--info", action="store_true", help="打印包信息（JSON）")
    args = p.parse_args(argv)

    if args.info:
        print(json.dumps({
            "name": "shopping-agent-v2",
            "version": __version__,
            "capabilities": CAPABILITIES,
            "missing_capabilities": MISSING_CAPABILITIES,
            "runtime": "ohos-agent-runtime/1.2",
        }, ensure_ascii=False, indent=2))
        return 0

    if args.health:
        result = health_check(args.port)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["ok"] else 1

    print(json.dumps(install_step(args.workspace), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
