"""Validate the three examples/agent/ files through the REAL backend code paths.

- install.json   -> backend.install_doc.validate()  (strict schema)
- yaml/json cfg  -> the same parsing the r1 slot uses (read_declared_config)
- zip            -> shape + the assertion install.json makes about it
"""
from __future__ import annotations

import json
import os
import sys
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))

AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
print(f"repo root: {ROOT}\n")

# ---------------------------------------------------------------- install.json
import install_doc  # noqa: E402

for name in ("shopping-agent-install.json",):
    path = os.path.join(AGENT_DIR, name)
    print(f"=== validate {name} ===")
    try:
        raw = install_doc.load_file(path)
    except install_doc.DocError as e:
        print(f"  PARSE FAIL: {e}")
        continue
    rep = install_doc.validate(raw, base_dir=ROOT)
    print(f"  ok       : {rep['ok']}")
    if rep["errors"]:
        for e in rep["errors"]:
            print(f"  ERROR    : [{e['path']}] {e['msg']}")
    if rep["warnings"]:
        for w in rep["warnings"]:
            print(f"  warning  : [{w['path']}] {w['msg']}")
    if not rep["errors"]:
        s = install_doc.summary(rep["doc"])
        print(f"  agent    : {s.get('agent')} {s.get('version')}")
        print(f"  target   : {s.get('host')}:{s.get('port')} user={s.get('user')} "
              f"auth={s.get('auth_method')} key={s.get('private_key_file')}")
        print(f"  package  : {s.get('package')}")
        steps = install_doc.resolve_steps(rep["doc"])
        print(f"  steps    : {len(steps)}")
        for st in steps:
            skipped = " [SKIP]" if st.get("skip") else ""
            print(f"     - {st.get('id'):<8} {st.get('desc','')}{skipped}")
        md = install_doc.masked(rep["doc"])
        print(f"  masked key path: {md.get('target',{}).get('auth',{}).get('private_key')}")
    print()

# ------------------------------------------------------------- config (yaml/json)
print("=== parse real config through backend path ===")
import api_agent  # noqa: E402

for name in ("shopping-agent.yaml", "agent-config.template.yaml"):
    path = os.path.join(AGENT_DIR, name)
    print(f"-- {name}")
    try:
        parsed = api_agent._parse_config_text(open(path, encoding="utf-8").read())
    except Exception as e:
        print(f"   parse error: {type(e).__name__}: {e}")
        continue
    b = api_agent._first(parsed, "api", "base_url", "api_url", "endpoint", "model_api") or ""
    k = api_agent._first(parsed, "api_key", "key", "apikey", "access_key", "model_api_key") or ""
    m = api_agent._first(parsed, "model", "model_name", "model_id") or ""
    print(f"   api    : {b}")
    print(f"   model  : {m}")
    print(f"   key    : {api_agent.mask_key(k) if k else '<none>'}  (has_api_key={bool(k)})")
print()

# ---------------------------------------------------------------------- the zip
print("=== zip shape + install.json assertion ===")
zpath = os.path.join(AGENT_DIR, "shopping-agent-v2.zip")
with zipfile.ZipFile(zpath) as z:
    names = z.namelist()
    print(f"  members: {names}")
    print(f"  has agent.py (the verify step assertion): {'agent.py' in names}")
