# -*- coding: utf-8 -*-
"""把 index.html 里的内联脚本抽出来，用于 `node --check` 语法校验。"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
out = ROOT / "build"
out.mkdir(exist_ok=True)
for i, b in enumerate(blocks):
    p = out / f"inline_{i}.js"
    p.write_text(b, encoding="utf-8", newline="\n")
    print(f"inline_{i}.js lines={b.count(chr(10)) + 1} bytes={len(b.encode('utf-8'))}")
print("external scripts:", re.findall(r'<script[^>]*src="([^"]+)"', html))
print("css links:", re.findall(r'<link[^>]*href="([^"]+)"', html))
