# -*- coding: utf-8 -*-
"""一次性工具：从 scene-matrix.js 抽出 SCENE_MATRIX_MD 模板字符串，落成 md 数据文件。"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
src = (ROOT / "backend" / "data" / "scene_matrix.js.src").read_text(encoding="utf-8")
i = src.index("`")
j = src.rindex("`")
md = src[i + 1:j].strip("\n")

out = ROOT / "backend" / "data" / "scene_matrix.md"
out.write_text(md, encoding="utf-8", newline="\n")

scenes = re.findall(r"^###\s+(.+)$", md, re.M)
rows = [l for l in md.splitlines()
        if l.startswith("|") and "维度类别" not in l and not set(l) <= set("|- \t")]
print("scenes:", len(scenes), scenes)
print("dim rows total:", len(rows))
ec = [int(x) for x in re.findall(r"\|\s*([\d.]+)\s*$", md, re.M) if False]
# 电商购物 一个场景的维度行数与类别
sec = md.split("### 1.1")[1].split("### 1.2")[0]
r11 = [l for l in sec.splitlines()
       if l.startswith("|") and "维度类别" not in l and not set(l) <= set("|- \t")]
cats = []
for l in r11:
    c = [x.strip() for x in l.strip("|").split("|")][0]
    if c not in cats:
        cats.append(c)
print("电商购物 dims:", len(r11), "categories:", cats)
print("bytes:", out.stat().st_size)
