"""判定 zip 内"镜像 tar"的结构，以及 docker 会校验的 layer digest 关系。"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import tarfile
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ZIP = os.path.join(ROOT, "tools", "opencode-cli", "dist",
                   "opencode-container-1.18.32-linux-amd64.zip")

with zipfile.ZipFile(ZIP) as z:
    print("zip 成员:", z.namelist())
    image = max(z.infolist(), key=lambda i: i.file_size).filename
    data = z.read(image)

print(f"\n内层文件: {image}  {len(data):,} B")
print("  首 4 字节:", data[:4].hex(), "(1f8b08xx=gzip / tar 的会是文件名)")

is_tar = True
try:
    tf = tarfile.open(fileobj=io.BytesIO(data))
except tarfile.TarError as exc:
    is_tar = False
    print("  tarfile 打不开:", exc)

if is_tar:
    with tf:
        print("  ★ tarfile 能打开 => 内层是【未压缩 tar】")
        print("  成员:", tf.getnames())
        manifest = json.load(tf.extractfile("manifest.json"))
        config = json.load(tf.extractfile("config.json"))
        layers = manifest[0]["Layers"]
        print("  manifest Layers:", layers)
        print("  config.rootfs.diff_ids:", config["rootfs"]["diff_ids"])

        target = layers[-1]
        gz = tf.extractfile(target).read()
        raw = gzip.decompress(gz)
        gz_sha = hashlib.sha256(gz).hexdigest()
        raw_sha = hashlib.sha256(raw).hexdigest()
        print(f"\n  层 {target}")
        print(f"    gz 大小 : {len(gz):,} B")
        print(f"    原始大小: {len(raw):,} B")
        print(f"    sha256(gz)  = {gz_sha}")
        print(f"    sha256(raw) = {raw_sha}")
        print(f"    config.diff_ids[1] = {config['rootfs']['diff_ids'][1]}")
        print()
        print("  => 层文件名 == sha256(gz) ? ", target.split(".")[0] == gz_sha)
        print("  => diff_id  == sha256(raw) ? ",
              config["rootfs"]["diff_ids"][1] == "sha256:" + raw_sha)

print(f"\n内层文件自身 sha256 = {hashlib.sha256(data).hexdigest()}")
print(f"   （若内层=未压缩 tar，这个值不是 docker 校验的那个 digest）")
print(f"zip 文件 sha256     = {hashlib.sha256(open(ZIP,'rb').read()).hexdigest()}")
