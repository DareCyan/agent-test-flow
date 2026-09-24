# -*- coding: utf-8 -*-
"""step3「安装执行」：按安装说明文件（install_doc）把 zip 装到目标机器上。

流程（每一步都留痕；dry-run 会把「本来会跑什么」完整列出来）：
  1. 取文件（r1 上传的那份，或请求里内联）→ 重新严格校验（防绕过）
  2. 计划：展开占位符、标出每个跳过项与原因
  3. 预检：ssh_reachable / remote_os / disk_space / zip_sha256（可被 skip_checks 跳过）
  4. 传输安装包：local → scp；url → 目标机器自己下载；upload → 用 r1 上传/装机时补传的 zip
  5. 逐步执行 steps[].run（步骤 skip=true 的跳过）→ 每步跑它的 check
  6. 汇总：哪些过了/失败了/为什么跳过

**dry-run（默认）与真执行只差两件事**：不传文件、不跑步骤命令。预检照做（那才是"预检"的价值），
并且每个步骤在报告里以 status="dry-run" + 完整命令出现。

命令来源只有两处，且都可追溯：文件里的 `steps[].run`（kind=step），以及本模块按 `package.source`
拼出来的传输命令（kind=transfer，会在计划里明示）。AI 不参与产生任何命令。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path

import install_doc as ids
import ssh_client
import store

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "data" / "install_runs"
UPLOAD_DIR = ROOT / "uploads"
MAX_PACKAGE_BYTES = 64 * 1024 * 1024        # 装机时补传的 zip 上限，别把内存吃光

_runs: dict[int, dict] = {}
_lock = threading.RLock()
_stop: set[int] = set()


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _ts(t0: float) -> str:
    return f"00:{int(time.time() - t0):02d}.{int((time.time() - t0) % 1 * 100):02d}"


def _path(rid: int) -> Path:
    return RUNS_DIR / f"{rid}.json"


def _persist(run: dict) -> None:
    try:
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        _path(run["id"]).write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _load_all() -> None:
    if not RUNS_DIR.exists():
        return
    for p in sorted(RUNS_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("id"), int):
                _runs[data["id"]] = data
        except Exception:
            continue


_load_all()


def _next_id() -> int:
    return (max(_runs) + 1) if _runs else 1


def _publish(run: dict) -> None:
    """进度事件走 store 的字符串订阅频道（key = `<agent_id>#install`），复用现有 SSE 管线。"""
    store.publish_agent(f"{run.get('agent_id')}#install", "install", run)


def _log(run: dict, text: str, level: str = "muted", t0: float | None = None) -> None:
    with _lock:
        run.setdefault("logs", []).append(
            {"ts": _ts(t0) if t0 is not None else time.strftime("%H:%M:%S"),
             "level": level, "text": str(text)})
        run["updated_at"] = _now()
        _persist(run)
    _publish(run)


def _set(run: dict, **fields) -> None:
    with _lock:
        run.update(fields)
        run["updated_at"] = _now()
        _persist(run)
    _publish(run)


def _stopped(rid: int) -> bool:
    with _lock:
        return rid in _stop


# ── 取文件 ─────────────────────────────────────────────────────────────────
def _doc_text_of(agent_id: str) -> tuple[str, str]:
    """r1 上传的安装说明文件原文。

    必须按 `<agent_id>.meta.json` 里记的 `install_saved_name` 取：上传目录里同时有智能体
    配置文件，用 `glob(agent_id-*)` 取第一个会让两者互相抢（把配置文件当安装说明解析）。
    """
    if not agent_id:
        return "", ""
    try:
        meta_path = UPLOAD_DIR / f"{agent_id}.meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            name = str(meta.get("install_saved_name") or "").strip()
            p = UPLOAD_DIR / name if name else None
            if p and p.is_file():
                return p.read_text(encoding="utf-8", errors="replace"), p.name
    except Exception:
        pass
    try:                                    # 兜底：文件名里带 install 的（手工放置/老数据）
        for p in sorted(UPLOAD_DIR.glob(f"{agent_id}-*install*")):
            if p.is_file() and not p.name.endswith(".meta.json"):
                return p.read_text(encoding="utf-8", errors="replace"), p.name
    except Exception:
        pass
    return "", ""


def load_doc(agent_id: str, inline: str = "") -> tuple[dict | None, dict, str]:
    """返回 (doc, meta, error)。doc=None 表示取不到/校验不过（error 里写明原因）。"""
    text, fname = (inline, "inline-install.json") if (inline or "").strip() else _doc_text_of(agent_id)
    if not text.strip():
        return None, {}, "该智能体没有安装说明文件：请在 r1 上传 install.json（见 README 的字段表）"
    try:
        raw = ids.parse(text)
    except ids.DocError as e:
        return None, {"file": fname}, f"安装说明文件解析失败：{e}"
    rep = ids.validate(raw, base_dir=ROOT)
    meta = {"file": fname, "ok": rep["ok"], "errors": rep["errors"], "warnings": rep["warnings"]}
    if not rep["ok"]:
        head = "；".join(f"{x['path']}: {x['msg']}" for x in rep["errors"][:3])
        return None, meta, f"安装说明文件校验不通过（{len(rep['errors'])} 处）：{head}"
    return rep["doc"], meta, ""


# ── 工具 ───────────────────────────────────────────────────────────────────
def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_size(s) -> int:
    """把 "1G" / "500M" / "2GiB" 折算成字节；true/None → 0（表示"不检查具体容量"）。"""
    if isinstance(s, bool):
        return 0
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([KMGT]?)(?:i?B?)?\s*$", str(s or ""), re.I)
    if not m:
        return 0
    mult = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}
    return int(float(m.group(1)) * mult.get(m.group(2).upper(), 1))


def _check_entry(cid: str, enabled: bool, reason: str = "") -> dict:
    return {"id": cid, "label": ids.CHECK_LABELS[cid], "enabled": bool(enabled),
            "skip_reason": reason if not enabled else "", "status": "pending", "detail": ""}


def _resolve_local_zip(doc: dict, agent_id: str) -> tuple[Path | None, str]:
    """按 package.source 找到本机上的 zip（url 不需要本机文件）。返回 (path, error)。"""
    pkg = doc.get("package") or {}
    src = pkg.get("source")
    if src == "url":
        return None, ""
    if src == "upload":
        for cand in sorted(UPLOAD_DIR.glob(f"{agent_id}-*")):
            if cand.is_file() and cand.suffix.lower() == ".zip":
                return cand, ""
        return None, ("package.source=upload，但后端没有这个 zip（r1 只记了文件名/大小）。"
                      "两种做法：① 在 step3 页面重新选择安装包（会随请求补传）；"
                      "② 把 package.source 改成 local 并给 path")
    path = Path(pkg.get("path") or "")
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        return None, f"package.path 指向的文件不存在：{path}"
    return path, ""


# ── 计划 ───────────────────────────────────────────────────────────────────
def build_plan(doc: dict, agent_id: str) -> dict:
    steps = ids.resolve_steps(doc)
    return {
        "doc": ids.summary(doc),
        "target": f"{(doc.get('target') or {}).get('user')}@{(doc.get('target') or {}).get('host')}"
                  f":{(doc.get('target') or {}).get('port')}",
        "package": (doc.get("package") or {}).get("name"),
        "execute": ids.effective_execute(doc),
        "steps": [{"kind": "step", "id": s["id"], "desc": s["desc"], "cmd": s["cmd"],
                   "check_cmd": s["check_cmd"], "timeout_s": s["timeout_s"],
                   "skip": s["skip"], "skip_reason": s["skip_reason"]} for s in steps],
        "skips": [{"id": cid, "reason": ids.skip_reason(doc, cid)}
                  for cid in ids.CHECK_IDS if not ids.check_enabled(doc, cid)],
    }


# ── 预检 ───────────────────────────────────────────────────────────────────
def _ssh_probe(m: ssh_client.Machine) -> dict:
    """SSH 可达性探测（只读：echo 一行）。r1 预检与 step3 预检共用，避免两套判定。"""
    r = ssh_client.ssh_run(m, "echo installer-ok", 15)
    return {"status": "pass" if r["ok"] else "fail",
            "detail": (f"连上了（{r['ms']}ms，echo 有回显）" if r["ok"]
                       else f"连不上：{(r.get('err') or '未知错误')[:160]}"),
            "show": r.get("show", ""), "code": r.get("code"), "target": m.dest}


def precheck_ssh(doc: dict) -> dict:
    """给 r1 接入用的 SSH 预检：只读探测，**不执行任何安装动作**。"""
    if not ids.check_enabled(doc, "ssh_reachable"):
        return {"status": "skipped", "detail": ids.skip_reason(doc, "ssh_reachable") or "已关闭"}
    return _ssh_probe(ssh_client.Machine(doc.get("target") or {}))


def _check_os(m: ssh_client.Machine, doc: dict) -> dict:
    declared = ((doc.get("target") or {}).get("os")) or "auto"
    r = ssh_client.ssh_run(m, "uname -s 2>/dev/null || ver", 15)
    if not r["ok"]:
        return {"status": "fail", "detail": f"取不到目标系统信息：{(r.get('err') or '')[:120]}"}
    text = (r.get("out") or "").strip()
    low = text.lower()
    detected = ("windows" if ("windows" in low or "microsoft" in low)
                else "linux" if "linux" in low else text[:40] or "未知")
    if declared == "auto":
        return {"status": "pass", "detail": f"声明 auto；实测 {detected}（{text[:60]}）"}
    if declared == detected:
        return {"status": "pass", "detail": f"声明与实测一致：{detected}（{text[:60]}）"}
    return {"status": "fail", "detail": f"声明 {declared}，但实测 {detected}（{text[:60]}）"}


def _check_disk(m: ssh_client.Machine, doc: dict, need: int) -> dict:
    remote_dir = (doc.get("install") or {}).get("remote_dir") or "/tmp"
    if not need:
        return {"status": "skipped", "detail": "checks.disk_space 只写了 true，没给容量，不做具体比对"}
    probe = (f"df -Pk {remote_dir} 2>/dev/null | tail -1 | awk '{{print $4}}'")
    r = ssh_client.ssh_run(m, probe, 15)
    if not r["ok"]:
        return {"status": "warn", "detail": f"取不到磁盘信息（{remote_dir} 可能不存在）："
                                            f"{(r.get('err') or '')[:100]}"}
    try:
        avail_kb = int((r.get("out") or "0").strip().split()[0])
    except Exception:
        return {"status": "warn", "detail": f"磁盘信息解析不出来：{(r.get('out') or '')[:60]}"}
    avail = avail_kb * 1024
    ok = avail >= need
    return {"status": "pass" if ok else "fail",
            "detail": f"{remote_dir} 可用 {avail / 1024 / 1024:.0f}MB / 需要 {need / 1024 / 1024:.0f}MB"}


def _check_zip_sha(doc: dict, local_zip: Path | None) -> dict:
    declared = ((doc.get("package") or {}).get("sha256")) or ""
    if not declared:
        return {"status": "skipped", "detail": "文件里没有 package.sha256，无法比对"}
    if local_zip is None:
        return {"status": "skipped", "detail": "package.source=url，本机没有包可比对 sha256"}
    got = _sha256_file(local_zip)
    ok = got.lower() == declared.lower()
    return {"status": "pass" if ok else "fail",
            "detail": f"本机包 {got[:16]}… / 声明 {declared[:16]}…"}


# ── 主流程 ─────────────────────────────────────────────────────────────────
def _worker(rid: int, body: dict) -> None:
    t0 = time.time()
    run = _runs.get(rid)
    if run is None:
        return
    try:
        agent_id = run.get("agent_id") or ""
        doc, meta, err = load_doc(agent_id, body.get("install_content") or "")
        if doc is None:
            _log(run, f"[预检] 失败：{err}", "error", t0)
            return _finish(run, "failed", error=err)
        _set(run, doc_file=meta.get("file") or "", warnings=meta.get("warnings") or [])
        for w in (meta.get("warnings") or [])[:5]:
            _log(run, f"[文件] 提醒 {w['path']}：{w['msg']}", "warning", t0)

        plan = build_plan(doc, agent_id)
        _set(run, phase="planning", plan=plan)
        _log(run, f"[计划] 目标 {plan['target']} · 包 {plan['package']} · "
                  f"{len(plan['steps'])} 步 · "
                  f"{'真执行' if plan['execute'] else 'dry-run（文件未开 install.execute）'}", "muted", t0)
        for s in plan["skips"]:
            _log(run, f"[跳过] 校验项 {s['id']}：{s['reason']}", "warning", t0)

        m = ssh_client.Machine(doc.get("target") or {})
        _log(run, f"[预检] ssh 客户端 {ssh_client.ssh_version()}；私钥 {m.key_label()}；目标 {m.dest}", "muted", t0)

        # ── 预检 ──
        _set(run, phase="checking")
        checks: list[dict] = []
        need = parse_size((doc.get("checks") or {}).get("disk_space"))
        local_zip, zip_err = _resolve_local_zip(doc, agent_id)
        ssh_failed = False
        for cid in [c for c in ids.CHECK_IDS if c != "post_health"]:
            enabled = ids.check_enabled(doc, cid)
            entry = _check_entry(cid, enabled, ids.skip_reason(doc, cid))
            if not enabled:
                entry.update(status="skipped", detail=entry["skip_reason"])
            elif ssh_failed:
                # SSH 都连不上，后面的探测必然也连不上：直接短路，别每条都白等一个 ConnectTimeout
                entry.update(status="skipped", detail="目标机器 SSH 不可达，未再探测")
            elif cid == "ssh_reachable":
                entry.update(_ssh_probe(m))
                ssh_failed = entry["status"] == "fail"
            elif cid == "remote_os":
                entry.update(_check_os(m, doc))
            elif cid == "disk_space":
                entry.update(_check_disk(m, doc, need))
            elif cid == "zip_sha256":
                entry.update(_check_zip_sha(doc, local_zip))
            else:
                entry.update(status="skipped", detail="无此校验")
            checks.append(entry)
            _log(run, f"[预检] {entry['label']}：{entry['status']} · {entry['detail']}",
                 "success" if entry["status"] == "pass" else
                 ("error" if entry["status"] == "fail" else "warning"), t0)
            _set(run, checks=checks)
            if _stopped(rid):
                return _finish(run, "cancelled", error="已取消")
        blocked = [c for c in checks if c["status"] == "fail"]
        if blocked:
            # 预检失败：不继续（真实装机里，连不上机器还往下走只会留下半装状态）
            for c in blocked:
                if c["id"] == "ssh_reachable":
                    return _finish(run, "failed", checks=checks,
                                   error=f"目标机器不可达，已中止：{c['detail']}")
            return _finish(run, "failed", checks=checks,
                           error=f"预检未通过：{blocked[0]['label']} —— {blocked[0]['detail']}")

        # ── 传输 ──
        execute = bool(plan["execute"]) and body.get("dry_run") is not False
        _set(run, phase="transferring", execute=execute)
        remote_dir = (doc.get("install") or {}).get("remote_dir") or "/tmp"
        pkg = doc.get("package") or {}
        transfer = {"status": "pending", "detail": "", "show": "", "kind": "transfer"}
        if zip_err:
            return _finish(run, "failed", checks=checks, transfer=transfer, error=zip_err)
        if not execute:
            transfer.update(status="dry-run",
                            detail=f"dry-run：不会传输（本来会把 {pkg.get('name')} 放到 {remote_dir}/）")
            _log(run, f"[传输] dry-run：跳过传输，本应把 {pkg.get('name')} 传到 {remote_dir}/",
                 "warning", t0)
        else:
            mk = ssh_client.ssh_run(m, f"mkdir -p {remote_dir}", 30)
            if not mk["ok"]:
                transfer.update(status="fail", detail=f"建远端目录失败：{(mk.get('err') or '')[:140]}",
                                show=mk.get("show", ""))
                _set(run, transfer=transfer)
                return _finish(run, "failed", checks=checks, transfer=transfer,
                               error=f"建远端目录失败：{remote_dir}")
            if pkg.get("source") == "url":
                cmd = (f"cd {remote_dir} && curl -fL --retry 2 -o {pkg.get('name')} {pkg.get('url')}")
                r = ssh_client.ssh_run(m, cmd, 900)
            else:
                r = ssh_client.scp_put(m, str(local_zip), remote_dir, 900)
            transfer.update(status="ok" if r["ok"] else "fail",
                            detail=(f"已传到 {remote_dir}/（{r['ms']}ms）" if r["ok"]
                                    else f"传输失败：{(r.get('err') or '')[:160]}"),
                            show=r.get("show", ""), code=r.get("code"),
                            via=("目标机器下载" if pkg.get("source") == "url" else "scp"))
            _set(run, transfer=transfer)
            _log(run, f"[传输] {transfer['detail']}", "success" if r["ok"] else "error", t0)
            if not r["ok"]:
                return _finish(run, "failed", checks=checks, transfer=transfer,
                               error=f"安装包传输失败：{transfer['detail']}")

        # ── 逐步执行 ──
        _set(run, phase="installing")
        steps_out: list[dict] = []
        failed = ""
        for s in plan["steps"]:
            item = {"id": s["id"], "desc": s["desc"], "cmd": s["cmd"],
                    "check_cmd": s["check_cmd"], "timeout_s": s["timeout_s"],
                    "status": "pending", "out": "", "err": "", "ms": 0,
                    "check": {"status": "none", "detail": ""},
                    "skip_reason": s["skip_reason"], "kind": "step"}
            if s["skip"]:
                item["status"] = "skipped"
                _log(run, f"[步骤] 跳过 {s['id']}：{s['skip_reason']}", "warning", t0)
            elif failed:
                item["status"] = "skipped"
                item["skip_reason"] = "前一步失败，已中断"
            elif not execute:
                item["status"] = "dry-run"
                _log(run, f"[步骤] dry-run {s['id']}：本来会跑 `{s['cmd']}`", "muted", t0)
            else:
                r = ssh_client.ssh_run(m, s["cmd"], s["timeout_s"])
                item.update(status="ok" if r["ok"] else "fail", out=(r.get("out") or "")[-2000:],
                            err=(r.get("err") or "")[-2000:], ms=r.get("ms", 0),
                            code=r.get("code"))
                _log(run, f"[步骤] {s['id']} {'完成' if r['ok'] else '失败'}（{r['ms']}ms）"
                          + (f" · {item['err'][:140]}" if not r["ok"] else ""),
                     "success" if r["ok"] else "error", t0)
                if not r["ok"]:
                    failed = s["id"]
                if r["ok"] and s["check_cmd"]:
                    cr = ssh_client.ssh_run(m, s["check_cmd"], min(120, s["timeout_s"]))
                    item["check"] = {"status": "pass" if cr["ok"] else "fail",
                                     "detail": (cr.get("out") or cr.get("err") or "")[-400:],
                                     "cmd": s["check_cmd"]}
                    _log(run, f"[校验] {s['id']} 的 check {'通过' if cr['ok'] else '未通过'}"
                              + ("" if cr["ok"] else f"：{(cr.get('err') or '')[:120]}"),
                         "success" if cr["ok"] else "warning", t0)
            steps_out.append(item)
            _set(run, steps=steps_out)
            if _stopped(rid):
                return _finish(run, "cancelled", checks=checks, steps=steps_out, transfer=transfer,
                               error="已取消")

        # ── post_health：按各步 check 汇总 ──
        ph_enabled = ids.check_enabled(doc, "post_health")
        ph = _check_entry("post_health", ph_enabled, ids.skip_reason(doc, "post_health"))
        if not ph_enabled:
            ph.update(status="skipped", detail=ph["skip_reason"])
        elif not execute:
            ph.update(status="dry-run", detail="dry-run：没有真跑步骤，无健康检查结果")
        else:
            checks_with = [s for s in steps_out if s["check"].get("status") in ("pass", "fail")]
            bad = [s for s in checks_with if s["check"]["status"] == "fail"]
            if not checks_with:
                ph.update(status="warn", detail="所有步骤都没写 check，没有可汇总的健康检查")
            elif bad:
                ph.update(status="fail",
                          detail=f"{len(bad)} 个步骤的 check 未通过：{', '.join(s['id'] for s in bad)}")
            else:
                ph.update(status="pass", detail=f"{len(checks_with)} 个步骤的 check 全部通过")
        checks.append(ph)
        _log(run, f"[校验] {ph['label']}：{ph['status']} · {ph['detail']}",
             "success" if ph["status"] in ("pass", "dry-run") else
             ("error" if ph["status"] == "fail" else "warning"), t0)

        skipped_steps = [s["id"] for s in steps_out if s["status"] == "skipped"]
        skipped_checks = [c["id"] for c in checks if c["status"] == "skipped"]
        bad_checks = [c["id"] for c in checks if c["status"] == "fail"]
        failed_steps = [s["id"] for s in steps_out if s["status"] == "fail"]
        ok = not (bad_checks or failed_steps)
        result = {"ok": ok, "dry_run": not execute,
                  "failed_at": failed or (bad_checks[0] if bad_checks else ""),
                  "failed_steps": failed_steps, "failed_checks": bad_checks,
                  "skipped_steps": skipped_steps, "skipped_checks": skipped_checks,
                  "elapsed_ms": int((time.time() - t0) * 1000)}
        _log(run, ("[完成] " if ok else "[失败] ")
                  + (f"dry-run 预检通过：{len(steps_out)} 步待执行" if not execute
                     else f"{len(steps_out)} 步：成功 {sum(1 for s in steps_out if s['status'] == 'ok')}、"
                          f"失败 {len(failed_steps)}、跳过 {len(skipped_steps)}")
                  + f" · 跳过校验 {skipped_checks or '无'}", "success" if ok else "error", t0)
        return _finish(run, "completed" if ok else "failed", checks=checks, steps=steps_out,
                       transfer=transfer, result=result,
                       error="" if ok else f"安装未通过：{result['failed_at']}")
    except Exception as e:  # noqa: BLE001
        _log(run, f"[异常] {type(e).__name__}: {e}", "error", t0)
        return _finish(run, "failed", error=f"{type(e).__name__}: {e}")
    finally:
        with _lock:
            _stop.discard(rid)


def _finish(run: dict, status: str, **fields) -> None:
    fields.setdefault("error", run.get("error") or "")
    _set(run, status=status, phase="done", **fields)


# ── 对外接口 ───────────────────────────────────────────────────────────────
def create(body: dict) -> dict:
    """创建一次安装执行。body: {agent_id, install_content?, package_b64?, package_name?, dry_run?}"""
    agent_id = (body.get("agent_id") or "").strip()
    inline = body.get("install_content") or ""
    if not agent_id and not inline.strip():
        return {"ok": False, "error": "要么给 agent_id（用 r1 上传的安装说明），要么内联 install_content"}

    # 装机时补传的 zip（source=upload 时需要）
    pkg_b64 = body.get("package_b64") or ""
    saved = ""
    if pkg_b64:
        try:
            raw = base64.b64decode(pkg_b64.split(",")[-1], validate=False)
        except Exception as e:
            return {"ok": False, "error": f"安装包 base64 解析失败：{e}"}
        if len(raw) > MAX_PACKAGE_BYTES:
            return {"ok": False, "error": f"安装包太大（>{MAX_PACKAGE_BYTES // 1024 // 1024}MB）"}
        name = os.path.basename(body.get("package_name") or "package.zip")
        if not name.lower().endswith(".zip"):
            name += ".zip"
        try:
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            path = UPLOAD_DIR / f"{agent_id or 'adhoc'}-{name}"
            path.write_bytes(raw)
            saved = path.name
        except Exception as e:
            return {"ok": False, "error": f"安装包落盘失败：{e}"}

    with _lock:
        rid = _next_id()
        run = {"id": rid, "agent_id": agent_id or "adhoc", "status": "running", "phase": "starting",
               "dry_run": body.get("dry_run") is not False, "checks": [], "steps": [],
               "transfer": {}, "logs": [], "plan": {}, "result": {}, "error": "",
               "package_saved": saved,
               "created_at": _now(), "updated_at": _now()}
        _runs[rid] = run
        _persist(run)
    _log(run, f"[启动] step3 安装执行（run #{rid}）· 智能体 {run['agent_id']}"
              + (f" · 补传安装包 {saved}" if saved else ""), "muted")

    threading.Thread(target=_worker, args=(rid, dict(body)), name=f"install-{rid}",
                     daemon=True).start()
    return {"ok": True, "id": rid, "agent_id": run["agent_id"], "dry_run": run["dry_run"]}


def get(rid: int) -> dict:
    with _lock:
        run = _runs.get(rid)
    if not run:
        return {"ok": False, "error": "install run not found"}
    return {"ok": True, "run": run}


def latest_for(agent_id: str) -> dict | None:
    with _lock:
        rows = [r for r in _runs.values() if r.get("agent_id") == agent_id]
    return dict(max(rows, key=lambda r: r["id"])) if rows else None


def cancel(rid: int) -> dict:
    with _lock:
        if rid not in _runs:
            return {"ok": False, "error": "install run not found"}
        _stop.add(rid)
    return {"ok": True, "id": rid}


def plan_preview(agent_id: str, inline: str = "") -> dict:
    """只看计划（r1 接入时的预检展示、前端"先看要跑什么"都用它）。不执行任何东西。"""
    doc, meta, err = load_doc(agent_id, inline)
    if doc is None:
        return {"ok": False, "error": err, "meta": meta}
    return {"ok": True, "meta": meta, "plan": build_plan(doc, agent_id),
            "checks": {cid: {"enabled": ids.check_enabled(doc, cid),
                             "label": ids.CHECK_LABELS[cid],
                             "reason": ids.skip_reason(doc, cid)} for cid in ids.CHECK_IDS}}
