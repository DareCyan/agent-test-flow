"""确定"重压缩层"的正确做法，使 docker load 的 layer digest 与 package.sha256 一致。

背景：
  · zip 里放未压缩 tar -> docker 会重新 gzip 该层，digest 与我们在 Windows 上算的不一致
  · tarfile 的内部信息（uname/mtime）几乎肯定是罪魁，需要显式置零/置空

流程：解出层 -> 用 python 重压（mtime=0）-> 打印 digest
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import tarfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DIST = os.path.join(ROOT, "tools", "opencode-cli", "dist")
ZIP = os.path.join(DIST, "opencode-container-1.18.32-linux-amd64.zip")
import zipfile

TARGET_DIGEST = None
with zipfile.ZipFile(ZIP) as z:
    data = z.read("opencode-image.tar")

with tarfile.open(fileobj=io.BytesIO(data)) as tf:
    names = tf.getnames()
print("zip 内条目:", names)

# 找到 opencode 那一层（最大的）
layers = []
for n in names:
    if n.endswith(".tar.gz"):
        with tarfile.open(fileobj=io.BytesIO(data)) as tf:
            info = tf.getmember(n)
            layers.append((n, info.size))

for n, size in layers:
    print(f"  {n}  {size:,} B")

# ── 实验：把最大的那层解压后用 python 重压，看 digest ──────────────
target = max(layers, key=lambda x: x[1])[0]
with tarfile.open(fileobj=io.BytesIO(data)) as tf:
    f = tf.extractfile(target)
    raw = f.read()
print(f"\n目标层 {target}: 解压后 {len(raw):,} B")

# 原始层内成员信息（判断 tarfile 会写入什么）
with tarfile.open(fileobj=io.BytesIO(raw)) as inner:
    for m in inner.getmembers()[:3]:
        print(f"  成员 {m.name}: uname={m.uname!r} gname={m.gname!r} mtime={m.mtime} mode={oct(m.mode)} type={m.type}")


def repack(raw: bytes, zero_meta: bool) -> bytes:
    """把解压的 tar 重新 gzip；zero_meta 时把 uname/gname/mtime 置零。"""
    if not zero_meta:
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6, mtime=0) as g:
            g.write(raw)
        return buf.getvalue()
    # 重写 tar：显式置零元信息
    src = tarfile.open(fileobj=io.BytesIO(raw))
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w", format=src.format) as dst:
        for m in src.getmembers():
            m2 = m
            m2.uid = m2.gid = 0
            m2.uname = m2.gname = ""
            m2.mtime = 0
            m2.pax_headers = {}
            f = src.extractfile(m) if m.isreg() else None
            dst.addfile(m2, f)
    tarb = out.getvalue()
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6, mtime=0) as g:
        g.write(tarb)
    return buf.getvalue()


for zero in (False, True):
    gz = repack(raw, zero)
    d = hashlib.sha256(gz).hexdigest()
    print(f"\nzero_meta={zero}: 重压后 {len(gz):,} B")
    print(f"  digest = {d}")
    print(f"  与 docker manifest 声明的关系：需在容器里 `docker load` 后看实际值")
