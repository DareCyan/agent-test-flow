# -*- coding: utf-8 -*-
"""最简 run 存储：内存态 + data/runs/{id}.json 落盘，并为 SSE 提供订阅/广播。

不引数据库。写入频率受控（每条任务完成时写一次），单机演示完全够用。
"""

from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "data" / "runs"

_lock = threading.RLock()
_runs: dict[int, dict] = {}
_subs: dict[int, list[queue.Queue]] = {}
_log_subs: dict[str, list[queue.Queue]] = {}
MAX_LOGS = 800


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _path(rid: int) -> Path:
    return RUNS_DIR / f"{rid}.json"


def _persist(run: dict) -> None:
    try:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        _path(run["id"]).write_text(
            json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _next_id() -> int:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    ids = []
    for p in RUNS_DIR.glob("*.json"):
        try:
            ids.append(int(p.stem))
        except ValueError:
            continue
    return (max(ids) + 1) if ids else 1


def create(**fields) -> dict:
    with _lock:
        rid = _next_id()
        run = {
            "id": rid,
            "status": "running",
            "steps": {},
            "logs": [],
            "progress": {"substeps": {"planner": "idle", "generator": "idle",
                                      "verifier": "idle", "evaluator": "idle"},
                         "generator_completed": 0, "verifier_completed": 0},
            "created_at": _now(),
            "updated_at": _now(),
        }
        run.update(fields)
        _runs[rid] = run
        _subs.setdefault(rid, [])
        _persist(run)
        return dict(run)


def get(rid: int) -> dict | None:
    with _lock:
        run = _runs.get(rid)
        if run is None:
            p = _path(rid)
            if p.exists():
                try:
                    run = json.loads(p.read_text(encoding="utf-8"))
                    _runs[rid] = run
                except Exception:
                    return None
        return run


def update(rid: int, **fields) -> dict | None:
    with _lock:
        run = _runs.get(rid)
        if run is None:
            return None
        run.update(fields)
        run["updated_at"] = _now()
        _persist(run)
    publish(rid, "status", _status_event(run))
    return run


def set_step(rid: int, step: str, value) -> None:
    """写 steps.<step> 并广播 step 事件（逐条任务完成时调用）。"""
    with _lock:
        run = _runs.get(rid)
        if run is None:
            return
        run.setdefault("steps", {})[step] = value
        run["updated_at"] = _now()
        _persist(run)
    publish(rid, "step", {"step": step, "value": value})


def set_progress(rid: int, **progress) -> None:
    with _lock:
        run = _runs.get(rid)
        if run is None:
            return
        p = run.setdefault("progress", {})
        for k, v in progress.items():
            if k == "substeps":
                p.setdefault("substeps", {}).update(v or {})
            else:
                p[k] = v
        _persist(run)
    publish(rid, "progress", dict(run.get("progress") or {}))


def log(rid: int, text: str, level: str = "muted") -> None:
    entry = {"ts": time.strftime("%H:%M:%S"), "level": level, "text": str(text)}
    with _lock:
        run = _runs.get(rid)
        if run is None:
            return
        logs = run.setdefault("logs", [])
        logs.append(entry)
        if len(logs) > MAX_LOGS:
            del logs[:-MAX_LOGS]
        _persist(run)
    publish(rid, "log", entry)


def _status_event(run: dict) -> dict:
    return {"id": run.get("id"), "status": run.get("status"),
            "progress": dict(run.get("progress") or {}),
            "engine": run.get("engine"), "error": run.get("error")}


def summary_event(rid: int) -> dict | None:
    """给 SSE 用的紧凑状态快照（前端首帧/断线重连时用）。"""
    run = get(rid)
    if not run:
        return None
    return _status_event(run)


# ── SSE 订阅 ────────────────────────────────────────────────────────────────
def subscribe(rid: int) -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=512)
    with _lock:
        _subs.setdefault(rid, []).append(q)
    return q


def unsubscribe(rid: int, q: queue.Queue) -> None:
    with _lock:
        if q in _subs.get(rid, []):
            _subs[rid].remove(q)


def publish(rid: int, event: str, data: dict) -> None:
    with _lock:
        targets = list(_subs.get(rid, []))
    payload = (event, data)
    for q in targets:
        try:
            q.put_nowait(payload)
        except queue.Full:
            pass


# ── 智能体接入的日志订阅（id = agent_id）────────────────────────────────────
def subscribe_agent(agent_id: str) -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=256)
    with _lock:
        _log_subs.setdefault(agent_id, []).append(q)
    return q


def unsubscribe_agent(agent_id: str, q: queue.Queue) -> None:
    with _lock:
        if q in _log_subs.get(agent_id, []):
            _log_subs[agent_id].remove(q)


def publish_agent(agent_id: str, event: str, data: dict) -> None:
    with _lock:
        targets = list(_log_subs.get(agent_id, []))
    for q in targets:
        try:
            q.put_nowait((event, data))
        except queue.Full:
            pass
