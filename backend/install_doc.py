# -*- coding: utf-8 -*-
"""安装说明文件（`install.json`）的格式规范、解析与严格校验。

它是「把 zip 装到目标机器上」的唯一依据：**机器 SSH 信息、安装包来源、安装步骤、
校验项、跳过开关**全在这一个文件里。r1 接入时上传并预检，step3「安装执行」真正执行时
复用同一份解析 —— 两条流程不会各解析一套。

三条硬约束（设计上刻意如此，别改）：
  1. **可执行的命令只有文件里明写的 `steps[].run`**。AI 只解读说明文字（notes/desc）并
     规范化顺序，绝不生成命令 —— 见 `api_agent` 的 `interpret` 调用点。
  2. **默认 dry-run**：只有 `install.execute = true` 才真执行（`effective_execute()`）。
  3. **跳过有两种粒度**：全局 `skip_checks` 白名单 + 步骤级 `steps[].skip`；
     两者都会原样记进执行报告（"为什么没校验/没执行"必须可追溯）。

本模块只做「解析 + 校验 + 变量展开」，**不碰网络、不碰 SSH**，所以能纯单测。
字段规范见 README「安装说明文件」一节，模板见 examples/agent/install.template.json。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

SPEC_VERSION = 1

# 可被 skip_checks 跳过的校验项（白名单；写错名字会报错而不是静默不跳）
CHECK_IDS = ("ssh_reachable", "remote_os", "disk_space", "zip_sha256", "post_health")
CHECK_LABELS = {
    "ssh_reachable": "目标机器 SSH 可达",
    "remote_os": "目标机器系统与声明一致",
    "disk_space": "目标机器磁盘空间足够",
    "zip_sha256": "安装包 sha256 与声明一致",
    "post_health": "安装后健康检查（各步骤的 check）",
}
SOURCE_KINDS = ("local", "url", "upload")
AUTH_METHODS = ("key",)          # 只支持密钥：Windows 上密码认证没有稳的非交互做法
OS_KINDS = ("linux", "windows", "auto")
DEFAULT_PORT = 22
DEFAULT_TIMEOUT_S = 180
DEFAULT_REMOTE_DIR = "/tmp/{agent}-install"
MAX_TIMEOUT_S = 3600

_TOP_KEYS = ("schema_version", "agent", "package", "target", "install",
             "checks", "skip_checks", "notes")
_STEP_KEYS = ("id", "desc", "run", "check", "timeout_s", "skip", "sudo")
_PKG_KEYS = ("name", "source", "path", "url", "sha256", "keep_remote")
_TARGET_KEYS = ("host", "port", "user", "auth", "os", "workspace", "sudo")
_AUTH_KEYS = ("method", "private_key", "passphrase")
_INSTALL_KEYS = ("remote_dir", "execute", "steps")
_AGENT_KEYS = ("name", "version")

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,40}$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_SIZE_RE = re.compile(r"^\d+(\.\d+)?\s*([KMGT]i?B?|B)?$", re.I)
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

# 命令里允许出现的占位符（校验未知占位符，避免 {wrokspace} 这种拼错静默生效）
PLACEHOLDERS = ("agent", "version", "zip", "zip_name", "zip_sha256", "zip_url",
                "remote_dir", "workspace", "host", "port", "user")


class DocError(Exception):
    """解析层失败（连 JSON 都不是）。校验层的失败走 report，不抛。"""


# ── 解析 ───────────────────────────────────────────────────────────────────
def parse(text: str) -> dict:
    """把安装说明文件文本解析成 dict。只接受 JSON。

    为什么只收 JSON：这个文件要表达「步骤列表 + 每步多个字段」，而仓库里的
    simplecfg 只支持扁平 `k: v`（不引 PyYAML 是既定约束），YAML 表达不了嵌套步骤。
    """
    if text is None:
        raise DocError("安装说明文件为空")
    stripped = str(text).lstrip("\ufeff").strip()
    if not stripped:
        raise DocError("安装说明文件为空")
    if not stripped.startswith("{"):
        raise DocError("安装说明文件必须是 JSON 对象（以 { 开头）；"
                       "YAML 不支持嵌套的安装步骤，请用 install.template.json 改写")
    try:
        data = json.loads(stripped)
    except Exception as e:
        raise DocError(f"JSON 解析失败：{e}") from e
    if not isinstance(data, dict):
        raise DocError("安装说明文件的顶层必须是 JSON 对象")
    return data


def load_file(path: str | Path) -> dict:
    return parse(Path(path).read_text(encoding="utf-8", errors="replace"))


# ── 校验 ───────────────────────────────────────────────────────────────────
def _is_str(v) -> bool:
    return isinstance(v, str)


def _ignorable(key) -> bool:
    """`_` 开头的键是注释（本仓库模板的既有约定，见 agent-config.template.json），静默忽略。"""
    return isinstance(key, str) and key.startswith("_")


def _s(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def _bool(v, default=False) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        low = v.strip().lower()
        if low in ("1", "true", "yes", "on"):
            return True
        if low in ("0", "false", "no", "off", ""):
            return False
    if isinstance(v, (int, float)):
        return bool(v)
    return default


def _int(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and re.fullmatch(r"-?\d+", v.strip()):
        return int(v.strip())
    return None


def validate(raw: dict, *, base_dir: str | Path | None = None) -> dict:
    """严格校验：返回 {ok, errors, warnings, doc(已归一化并填默认值)}。

    errors 会让整份文件判失败（ok=False）；warnings 不拦，但会显示出来。
    只写"未知字段"不算错误（向后兼容），但要显式 warn —— 免得拼错的字段静默失效。
    """
    errors: list[dict] = []
    warnings: list[dict] = []
    e = lambda path, msg: errors.append({"path": path, "msg": msg})       # noqa: E731
    w = lambda path, msg: warnings.append({"path": path, "msg": msg})     # noqa: E731

    if not isinstance(raw, dict):
        return {"ok": False, "errors": [{"path": "", "msg": "顶层必须是对象"}],
                "warnings": [], "doc": None}

    for k in raw:
        if k not in _TOP_KEYS and not _ignorable(k):
            w(k, "未知字段（已忽略；如果是拼写错误，请对照 README 的字段表）")

    ver = _int(raw.get("schema_version"))
    if ver is None:
        e("schema_version", "必填，且必须是整数（当前规范版本是 1）")
    elif ver != SPEC_VERSION:
        e("schema_version", f"不支持的版本 {ver}（本工具支持 {SPEC_VERSION}）")

    agent = raw.get("agent") if isinstance(raw.get("agent"), dict) else {}
    if raw.get("agent") is not None and not isinstance(raw.get("agent"), dict):
        e("agent", "必须是对象")
    for k in agent:
        if k not in _AGENT_KEYS and not _ignorable(k):
            w(f"agent.{k}", "未知字段（已忽略）")

    doc: dict = {
        "schema_version": SPEC_VERSION,
        "agent": {"name": _s(agent.get("name")), "version": _s(agent.get("version"))},
        "package": {}, "target": {}, "install": {},
        "checks": {}, "skip_checks": [], "notes": _s(raw.get("notes")),
    }

    # ── package ──
    pkg = raw.get("package")
    if not isinstance(pkg, dict):
        e("package", "必填，且必须是对象（至少要有 name）")
        pkg = {}
    for k in pkg:
        if k not in _PKG_KEYS and not _ignorable(k):
            w(f"package.{k}", "未知字段（已忽略）")
    pkg_out = {"name": _s(pkg.get("name")), "source": _s(pkg.get("source")) or "local",
               "path": _s(pkg.get("path")), "url": _s(pkg.get("url")),
               "sha256": _s(pkg.get("sha256")).lower(),
               "keep_remote": _bool(pkg.get("keep_remote"), False)}
    if not pkg_out["name"]:
        e("package.name", "必填：安装包文件名（要装的那个 .zip）")
    if pkg_out["source"] not in SOURCE_KINDS:
        e("package.source", f"必须是 {'/'.join(SOURCE_KINDS)} 之一（当前 \"{pkg_out['source']}\"）")
    if pkg_out["source"] == "local" and not pkg_out["path"]:
        e("package.path", "source=local 时必填：本机（工作台所在机器）上的 .zip 路径")
    if pkg_out["source"] == "local" and pkg_out["path"] and base_dir is not None:
        p = Path(pkg_out["path"])
        if not p.is_absolute():
            p = Path(base_dir) / p
        if not p.exists():
            w("package.path", f"本机找不到该文件：{p}（真执行前请确认）")
    if pkg_out["source"] == "url":
        if not pkg_out["url"]:
            e("package.url", "source=url 时必填：目标机器能直接下载的地址")
        elif not re.match(r"^https?://", pkg_out["url"]):
            e("package.url", "必须是 http:// 或 https:// 开头的地址")
    if pkg_out["sha256"] and not _SHA256_RE.match(pkg_out["sha256"]):
        e("package.sha256", "必须是 64 位十六进制（sha256 摘要）")
    doc["package"] = pkg_out

    # ── target ──
    tgt = raw.get("target")
    if not isinstance(tgt, dict):
        e("target", "必填，且必须是对象（机器 SSH 信息）")
        tgt = {}
    for k in tgt:
        if k not in _TARGET_KEYS and not _ignorable(k):
            w(f"target.{k}", "未知字段（已忽略）")
    port = _int(tgt.get("port"))
    if tgt.get("port") is not None and port is None:
        e("target.port", "必须是整数")
    if port is None:
        port = DEFAULT_PORT
    if not (1 <= port <= 65535):
        e("target.port", f"端口越界：{port}")

    auth = tgt.get("auth") if isinstance(tgt.get("auth"), dict) else {}
    if tgt.get("auth") is not None and not isinstance(tgt.get("auth"), dict):
        e("target.auth", "必须是对象")
    for k in auth:
        if k not in _AUTH_KEYS and not _ignorable(k):
            w(f"target.auth.{k}", "未知字段（已忽略）")
    auth_out = {"method": _s(auth.get("method")) or "key",
                "private_key": _s(auth.get("private_key")),
                "passphrase": auth.get("passphrase") if isinstance(auth.get("passphrase"), str) else ""}
    if auth_out["method"] not in AUTH_METHODS:
        e("target.auth.method", f"只支持 {'/'.join(AUTH_METHODS)}（密钥认证）："
                                "Windows 上密码认证没有稳定的非交互做法")
    if not auth_out["private_key"]:
        e("target.auth.private_key", "必填：本机上的私钥路径（如 C:/Users/me/.ssh/id_ed25519）")
    elif base_dir is not None and not Path(auth_out["private_key"]).exists():
        w("target.auth.private_key", f"本机找不到该私钥：{auth_out['private_key']}")
    if auth_out["passphrase"]:
        w("target.auth.passphrase", "已填写口令。本工具**不代持**口令：请先 `ssh-add` 到 ssh-agent，"
                                    "否则非交互调用会失败（该字段在接口与日志里只出现掩码）")

    tgt_out = {
        "host": _s(tgt.get("host")), "port": port, "user": _s(tgt.get("user")),
        "auth": auth_out, "os": _s(tgt.get("os")) or "auto",
        "workspace": _s(tgt.get("workspace")), "sudo": _bool(tgt.get("sudo"), False),
    }
    if not tgt_out["host"]:
        e("target.host", "必填：目标机器地址（IP 或域名）")
    if not tgt_out["user"]:
        e("target.user", "必填：SSH 登录用户")
    if tgt_out["os"] not in OS_KINDS:
        e("target.os", f"必须是 {'/'.join(OS_KINDS)} 之一（当前 \"{tgt_out['os']}\"）")
    if not tgt_out["workspace"]:
        tgt_out["workspace"] = f"/opt/{doc['agent']['name'] or 'agent'}"
        w("target.workspace", f"未声明，按默认值 {tgt_out['workspace']}（真装前请确认）")
    doc["target"] = tgt_out

    # ── install ──
    ins = raw.get("install")
    if not isinstance(ins, dict):
        e("install", "必填，且必须是对象（至少要有 steps）")
        ins = {}
    for k in ins:
        if k not in _INSTALL_KEYS and not _ignorable(k):
            w(f"install.{k}", "未知字段（已忽略）")
    remote_dir = _s(ins.get("remote_dir"))
    if not remote_dir:
        remote_dir = DEFAULT_REMOTE_DIR.replace("{agent}", doc["agent"]["name"] or "agent")
    elif "{remote_dir}" in remote_dir:
        e("install.remote_dir", "remote_dir 不能引用 {remote_dir}（自己）")
    else:
        for name in _PLACEHOLDER_RE.findall(remote_dir):
            if name not in PLACEHOLDERS:
                e("install.remote_dir", f"未知占位符 {{{name}}}（可用：{', '.join(PLACEHOLDERS)}）")
        # remote_dir 自己也支持占位符（如 {agent}），用「remote_dir 留空」的上下文展开
        remote_dir = expand(remote_dir, context({
            "agent": doc["agent"], "package": pkg_out, "target": tgt_out,
            "install": {"remote_dir": ""}}))
    steps_raw = ins.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        e("install.steps", "必填，且必须是非空数组：安装步骤（每步一个 run 命令）")
        steps_raw = []
    steps: list[dict] = []
    seen_ids: set[str] = set()
    for i, st in enumerate(steps_raw):
        p = f"install.steps[{i}]"
        if not isinstance(st, dict):
            e(p, "每一步必须是对象")
            continue
        for k in st:
            if k not in _STEP_KEYS and not _ignorable(k):
                w(f"{p}.{k}", "未知字段（已忽略）")
        sid = _s(st.get("id")) or f"step{i + 1}"
        if not _ID_RE.match(sid):
            e(f"{p}.id", f"id 只能是字母数字与 _.-（当前 \"{sid}\"）")
        if sid in seen_ids:
            e(f"{p}.id", f"id 重复：{sid}")
        seen_ids.add(sid)
        run = _s(st.get("run"))
        if not run:
            e(f"{p}.run", "必填：要在这台机器上执行的命令（唯一可执行来源；AI 不会替你生成命令）")
        tmo = _int(st.get("timeout_s"))
        if st.get("timeout_s") is not None and tmo is None:
            e(f"{p}.timeout_s", "必须是整数秒")
        if tmo is None:
            tmo = DEFAULT_TIMEOUT_S
        elif not (1 <= tmo <= MAX_TIMEOUT_S):
            e(f"{p}.timeout_s", f"越界：1~{MAX_TIMEOUT_S} 秒")
        steps.append({"id": sid, "desc": _s(st.get("desc")), "run": run,
                      "check": _s(st.get("check")), "timeout_s": tmo,
                      "skip": _bool(st.get("skip"), False),
                      "sudo": _bool(st.get("sudo"), tgt_out["sudo"])})
    doc["install"] = {"remote_dir": remote_dir,
                      "execute": _bool(ins.get("execute"), False), "steps": steps}

    # ── checks / skip_checks ──
    checks = raw.get("checks") if isinstance(raw.get("checks"), dict) else {}
    if raw.get("checks") is not None and not isinstance(raw.get("checks"), dict):
        e("checks", "必须是对象")
    for k, v in checks.items():
        if k not in CHECK_IDS:
            w(f"checks.{k}", f"未知校验项（可用：{', '.join(CHECK_IDS)}）")
            continue
        if k == "disk_space":
            if isinstance(v, str) and not _SIZE_RE.match(v.strip()):
                e("checks.disk_space", f"空间写法不对：\"{v}\"（例：1G、500M）")
            elif not isinstance(v, (str, bool)) and not isinstance(v, (int, float)):
                e("checks.disk_space", "应为容量字符串（如 1G）或布尔值")
        elif not isinstance(v, bool):
            e(f"checks.{k}", "应为布尔值 true/false")
    doc["checks"] = {k: v for k, v in checks.items() if k in CHECK_IDS}

    skips = raw.get("skip_checks")
    if skips is None:
        skips = []
    if not isinstance(skips, list):
        e("skip_checks", "必须是数组，例如 [\"disk_space\", \"zip_sha256\"]")
        skips = []
    out_skips: list[str] = []
    for i, s in enumerate(skips):
        name = _s(s)
        if name not in CHECK_IDS:
            e(f"skip_checks[{i}]", f"未知校验项 \"{name}\"（可用：{', '.join(CHECK_IDS)}）"
                                   "—— 写错名字不会静默跳过，只会报错")
            continue
        if name not in out_skips:
            out_skips.append(name)
    doc["skip_checks"] = out_skips

    # ── 占位符：只允许 PLACEHOLDERS 里的名字 ──
    for path, text in ([("package.path", pkg_out["path"]), ("package.url", pkg_out["url"])]
                       + [(f"install.steps[{i}].run", s["run"]) for i, s in enumerate(steps)]
                       + [(f"install.steps[{i}].check", s["check"]) for i, s in enumerate(steps)]):
        for name in _PLACEHOLDER_RE.findall(text or ""):
            if name not in PLACEHOLDERS:
                e(path, f"未知占位符 {{{name}}}（可用：{', '.join(PLACEHOLDERS)}）")

    return {"ok": not errors, "errors": errors, "warnings": warnings, "doc": doc}


# ── 归一化后的读取辅助 ──────────────────────────────────────────────────────
def effective_execute(doc: dict, override: bool | None = None) -> bool:
    """是否真执行。文件里 `install.execute=true` 才真装；override 只是**进一步收紧**用。

    override=False 可强制 dry-run（UI 上的"只预览"）；override=True 不能把默认 dry-run
    的文档变成真执行 —— 真执行必须由文件本身显式声明。
    """
    declared = bool((doc.get("install") or {}).get("execute"))
    if override is False:
        return False
    return declared


def check_enabled(doc: dict, check_id: str) -> bool:
    """该校验项是否启用：显式关掉（checks.x=false）或写进 skip_checks 都算不启用。"""
    if check_id in (doc.get("skip_checks") or []):
        return False
    v = (doc.get("checks") or {}).get(check_id)
    if v is None:
        return True                     # 未声明 = 默认开启
    if isinstance(v, bool):
        return v
    return bool(_s(v))                  # disk_space="1G" 这类：有值即开启


def skip_reason(doc: dict, check_id: str) -> str:
    if check_id in (doc.get("skip_checks") or []):
        return "文件 skip_checks 显式跳过"
    if (doc.get("checks") or {}).get(check_id) is False:
        return "文件 checks 里显式关闭"
    return ""


def context(doc: dict) -> dict:
    """变量展开的上下文：命令里能用的占位符取值。"""
    pkg = doc.get("package") or {}
    tgt = doc.get("target") or {}
    return {
        "agent": (doc.get("agent") or {}).get("name") or "agent",
        "version": (doc.get("agent") or {}).get("version") or "",
        "zip": pkg.get("path") or pkg.get("name") or "",
        "zip_name": pkg.get("name") or "",
        "zip_sha256": pkg.get("sha256") or "",
        "zip_url": pkg.get("url") or "",
        "remote_dir": (doc.get("install") or {}).get("remote_dir") or "",
        "workspace": tgt.get("workspace") or "",
        "host": tgt.get("host") or "",
        "port": str(tgt.get("port") or DEFAULT_PORT),
        "user": tgt.get("user") or "",
    }


def expand(text: str, ctx: dict) -> str:
    """展开 {占位符}；未知的保持原样（validate 已把未知占位符拦成 error）。"""
    return _PLACEHOLDER_RE.sub(lambda m: str(ctx.get(m.group(1), m.group(0))), text or "")


def resolve_steps(doc: dict) -> list[dict]:
    """把步骤里的占位符展开成可直接执行的命令（含 sudo 前缀与跳过原因）。"""
    ctx = context(doc)
    out = []
    for st in ((doc.get("install") or {}).get("steps") or []):
        cmd = expand(st.get("run") or "", ctx)
        check = expand(st.get("check") or "", ctx)
        if st.get("sudo"):
            cmd = "sudo -n " + cmd
            if check:
                check = "sudo -n " + check
        out.append({**st, "cmd": cmd, "check_cmd": check,
                    "skip_reason": "步骤声明 skip=true" if st.get("skip") else ""})
    return out


def mask_secret(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    return "****" if len(s) <= 6 else s[:2] + "****" + s[-2:]


def masked(doc: dict) -> dict:
    """给接口/日志用：去掉口令，私钥路径只留文件名。"""
    d = json.loads(json.dumps(doc or {}, ensure_ascii=False))
    auth = ((d.get("target") or {}).get("auth") or {})
    if auth.get("passphrase"):
        auth["passphrase"] = mask_secret(auth["passphrase"])
        auth["passphrase_present"] = True
    key = auth.get("private_key") or ""
    if key:
        auth["private_key_file"] = key.replace("\\", "/").rsplit("/", 1)[-1]
        auth["private_key"] = mask_secret(key)
    return d


def summary(doc: dict) -> dict:
    """给 profile / 前端用的紧凑摘要（不含任何秘密）。"""
    pkg = doc.get("package") or {}
    tgt = doc.get("target") or {}
    ins = doc.get("install") or {}
    steps = resolve_steps(doc)
    return {
        "ok": True,
        "agent": doc.get("agent"),
        "package": {k: pkg.get(k) for k in ("name", "source", "path", "url", "sha256", "keep_remote")},
        "target": {"host": tgt.get("host"), "port": tgt.get("port"), "user": tgt.get("user"),
                   "os": tgt.get("os"), "workspace": tgt.get("workspace"), "sudo": tgt.get("sudo"),
                   "auth_method": (tgt.get("auth") or {}).get("method"),
                   "private_key_file": ((tgt.get("auth") or {}).get("private_key") or "")
                       .replace("\\", "/").rsplit("/", 1)[-1],
                   "passphrase_present": bool((tgt.get("auth") or {}).get("passphrase"))},
        "install": {"remote_dir": ins.get("remote_dir"), "execute": bool(ins.get("execute")),
                    "steps": [{"id": s["id"], "desc": s["desc"], "cmd": s["cmd"],
                               "check_cmd": s["check_cmd"], "timeout_s": s["timeout_s"],
                               "skip": s["skip"], "skip_reason": s["skip_reason"]} for s in steps]},
        "checks": {cid: {"enabled": check_enabled(doc, cid), "label": CHECK_LABELS[cid],
                         "reason": skip_reason(doc, cid)} for cid in CHECK_IDS},
        "skip_checks": list(doc.get("skip_checks") or []),
        "effective_execute": effective_execute(doc),
        "notes": doc.get("notes") or "",
    }
