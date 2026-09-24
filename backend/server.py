# -*- coding: utf-8 -*-
"""agent-test-flow 后端：Python 3.12 纯标准库（http.server + threading + SSE）。

启动：
    python backend/server.py --port 8787
    python backend/server.py --port 8787 --host 0.0.0.0
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import queue
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import api_agent          # noqa: E402
import api_dataset        # noqa: E402
import api_install        # noqa: E402
import llm                # noqa: E402
import scene_matrix as sm  # noqa: E402
import step1_runner       # noqa: E402
import store              # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"

SSE_HEARTBEAT_S = 15


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "agent-test-flow/1.0"

    # ── 基础工具 ──────────────────────────────────────────────────────────
    def log_message(self, fmt, *args):  # 收敛默认噪声日志
        pass

    def _json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionError):
            pass

    def _read_json(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0:
            return {}
        try:
            data = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _query(self) -> dict:
        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

    def _int(self, value, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    # ── GET ───────────────────────────────────────────────────────────────
    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        q = self._query()
        try:
            if path == "/api/health":
                cfg = llm.load_config()
                llm_cfg = cfg.get("llm") or {}
                self._json({
                    "ok": True,
                    "service": "agent-test-flow",
                    "llm_configured": bool(llm_cfg.get("configured")),
                    "llm_model": llm_cfg.get("model") or "",
                    "llm_config_source": llm_cfg.get("config_source") or "",
                    "engine": "llm" if llm_cfg.get("configured") else "mock",
                    "llm_timeout_s": llm_cfg.get("timeout"),
                    "llm_max_tokens": llm_cfg.get("max_tokens"),
                    "llm_max_tokens_used": llm.max_tokens_effective(),
                    "dataset_concurrency": step1_runner._concurrency(),
                    "scenes": len(sm.scene_names()),
                    "caps13": len(sm.CAPS13),
                    "l2": len(sm.L2_CODES),
                })
                return
            if path == "/api/scene-matrix":
                self._json({"ok": True,
                            "l2_info": sm.l2_public(),
                            "caps13": sm.caps13_public(),
                            "groups": sm.CAP_GROUP_ORDER,
                            "scenes": sm.scenes_public()})
                return
            if path == "/api/scene-preview":
                self._json(api_dataset.preview(q.get("scene") or "", q.get("agent_id") or ""))
                return
            if path == "/api/agent/status":
                self._json(api_agent.status(q.get("id") or ""))
                return
            if path == "/api/agent/stream":
                self._sse_agent(q.get("id") or "")
                return
            if path == "/api/dataset-ext/run":
                self._json(api_dataset.get(self._int(q.get("id"))))
                return
            if path == "/api/dataset-ext/run/summary":
                self._json(api_dataset.build_summary(self._int(q.get("id"))))
                return
            if path == "/api/dataset-ext/stream":
                self._sse_dataset(self._int(q.get("id")))
                return
            if path == "/api/install/run":
                self._json(api_install.get(self._int(q.get("id"))))
                return
            if path == "/api/install/latest":
                self._json({"ok": True, "run": api_install.latest_for(q.get("agent_id") or "")})
                return
            if path == "/api/install/stream":
                self._sse_install(q.get("agent_id") or "")
                return
            if path in ("/", "/index.html"):
                self._static("index.html")
                return
            if path.startswith("/api/"):
                self._json({"ok": False, "error": f"unknown api: {path}"}, 404)
                return
            self._static(path.lstrip("/"))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    # ── POST ──────────────────────────────────────────────────────────────
    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        body = self._read_json()
        try:
            if path == "/api/agent/connect":
                self._json(api_agent.connect(body))
                return
            if path == "/api/dataset-ext/runs":
                self._json(api_dataset.create(body))
                return
            if path in ("/api/dataset-ext/runs/cancel", "/api/dataset-ext/cancel"):
                self._json(api_dataset.cancel(int(body.get("id") or 0)))
                return
            if path == "/api/install/runs":
                self._json(api_install.create(body))
                return
            if path in ("/api/install/runs/cancel", "/api/install/cancel"):
                self._json(api_install.cancel(int(body.get("id") or 0)))
                return
            if path == "/api/install/plan":
                # 只看计划（不执行任何东西）：r1 接入后预览、step3 页面「先看要跑什么」都用它
                self._json(api_install.plan_preview(body.get("agent_id") or "",
                                                    body.get("install_content") or ""))
                return
            self._json({"ok": False, "error": f"unknown api: {path}"}, 404)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    # ── 静态资源 ──────────────────────────────────────────────────────────
    def _static(self, rel: str) -> None:
        rel = unquote(rel or "").split("?")[0]
        candidate = (FRONTEND / rel).resolve() if rel else (FRONTEND / "index.html")
        try:
            candidate.relative_to(FRONTEND.resolve())
        except ValueError:
            self.send_error(403)
            return
        if candidate.is_dir():
            candidate = candidate / "index.html"
        if not candidate.exists() or not candidate.is_file():
            self.send_error(404, f"not found: {rel}")
            return
        data = candidate.read_bytes()
        ctype = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionError):
            pass

    # ── SSE ───────────────────────────────────────────────────────────────
    def _sse_headers(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    @staticmethod
    def _event(name: str, data) -> bytes:
        try:
            payload = json.dumps(data, ensure_ascii=False)
        except Exception:
            payload = "{}"
        return f"event: {name}\ndata: {payload}\n\n".encode("utf-8")

    def _pump(self, q: queue.Queue, snapshot: dict | None, done_when=None) -> None:
        """把队列里的事件推给浏览器；无事件时定期发心跳保活。"""
        self._sse_headers()
        if snapshot is not None:
            self.wfile.write(self._event("snapshot", snapshot))
            self.wfile.flush()
        while True:
            try:
                name, data = q.get(timeout=SSE_HEARTBEAT_S)
            except queue.Empty:
                try:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionError, OSError):
                    return
                if done_when is not None and done_when():
                    return
                continue
            try:
                self.wfile.write(self._event(name, data))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionError, OSError):
                return

    def _sse_dataset(self, rid: int) -> None:
        run = store.get(rid)
        if not run:
            self._json({"ok": False, "error": "run not found"}, 404)
            return
        q = store.subscribe(rid)
        try:
            self._pump(q, api_dataset.build_summary(rid),
                       done_when=lambda: (store.get(rid) or {}).get("status") in
                       ("completed", "failed", "cancelled"))
        finally:
            store.unsubscribe(rid, q)

    def _sse_agent(self, agent_id: str) -> None:
        if not api_agent.get(agent_id):
            self._json({"ok": False, "error": "agent not found"}, 404)
            return
        q = store.subscribe_agent(agent_id)
        try:
            self._pump(q, api_agent.status(agent_id),
                       done_when=lambda: (api_agent.get(agent_id) or {}).get("phase") == "ready")
        finally:
            store.unsubscribe_agent(agent_id, q)

    def _sse_install(self, agent_id: str) -> None:
        """step3 安装执行的进度 SSE。

        用 `<agent_id>#install` 这个**独立的字符串频道**：既复用 store 现成的订阅/广播，
        又不会和 r1 接入过程（agent_id 频道）抢事件。
        """
        key = f"{agent_id}#install"
        q = store.subscribe_agent(key)
        try:
            self._pump(q, api_install.latest_for(agent_id),
                       done_when=lambda: (api_install.latest_for(agent_id) or {})
                       .get("status") in ("completed", "failed", "cancelled"))
        finally:
            store.unsubscribe_agent(key, q)


def _port_in_use(host: str, port: int) -> bool:
    """预检端口是否已有服务在监听。

    Windows 下 SO_REUSEADDR 允许两个进程重复 bind 同一端口（第二个静默生效），
    只靠 bind 的 OSError 拦不住，所以先连一次探活。
    """
    import socket
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.4)
            return s.connect_ex((probe_host, port)) == 0
    except OSError:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="agent-test-flow 后端")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()

    cfg = llm.load_config()
    llm_cfg = cfg.get("llm") or {}
    if _port_in_use(args.host, args.port):
        print(f"[server] {args.host}:{args.port} 已被占用 —— 上一个实例可能还在运行。")
        print(f"[server] 直接使用现有实例: http://{args.host}:{args.port}/")
        print(f"[server] 或换端口启动:   python backend/server.py --port {args.port + 1}")
        return 2
    try:
        srv = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as e:
        print(f"[server] 无法监听 {args.host}:{args.port} —— {e}")
        print(f"[server] 换端口试试: python backend/server.py --port {args.port + 1}")
        return 2
    srv.daemon_threads = True
    url = f"http://{args.host}:{args.port}/"
    print("=" * 64)
    print("  Agent 自动化测试工作台 · 前后端已启动")
    print(f"  页面: {url}")
    print(f"  step1 引擎: {'LLM ' + llm_cfg.get('model', '') if llm_cfg.get('configured') else 'mock（未配置 LLM，开箱可跑）'}")
    _src = llm_cfg.get("config_source") or ""
    print("  LLM 配置: " + (_src if _src else
                            "未找到 backend/config.yaml | config.yml | config.json（可用 LLM_* 环境变量）"))
    print(f"  场景矩阵: {len(sm.scene_names())} 场景 · {len(sm.L2_CODES)} 个 L2 能力 → {len(sm.CAPS13)} 个能力列")
    print("  停止: Ctrl+C")
    print("=" * 64)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[server] 已停止")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
