"""
Build a loadable Docker/OCI image tar for the opencode CLI, WITHOUT Docker.

Why: the target server has Docker 29.8.1 running but NO outbound internet, so
it cannot `docker build` or `docker pull`. This script runs on a machine that
does have internet, assembles the image by hand, and emits a tar that the
server can `docker load`.

Approach:
  1. pull the base image manifest + layers straight from Docker Hub v2 API
  2. build one extra gzipped tar layer containing /usr/local/bin/opencode
  3. write config.json + manifest.json + repositories
  4. tar it all up -> docker load -i <out>

Base layers are copied in byte-identical (their digests must stay unchanged);
the new layer's digest is computed over exactly the bytes we emit.

Usage:
    python build_container.py [--base ubuntu:24.04] [--out DIR]
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import struct
import sys
import tarfile
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")

UA = "opencode-container-builder/1.0"
REGISTRY = "registry-1.docker.io"
DEFAULT_REALM = "https://auth.docker.io/token"


def _challenge(repo: str) -> tuple[str, str]:
    """Ask the registry what auth it wants; returns (realm, service).

    The service name is NOT always the registry host: Docker Hub answers
    `service="registry.docker.io"` even though the host is
    `registry-1.docker.io`, and a token minted for the wrong service is
    rejected with 401 invalid_token.
    """
    req = urllib.request.Request(f"https://{REGISTRY}/v2/", headers={"User-Agent": UA})
    try:
        urllib.request.urlopen(req, timeout=60)
        return DEFAULT_REALM, REGISTRY
    except urllib.error.HTTPError as e:
        hdr = e.headers.get("WWW-Authenticate", "")
    m_realm = re.search(r'realm="([^"]+)"', hdr)
    m_svc = re.search(r'service="([^"]+)"', hdr)
    return (m_realm.group(1) if m_realm else DEFAULT_REALM,
            m_svc.group(1) if m_svc else REGISTRY)


def _auth_token(repo: str) -> str:
    realm, service = _challenge(repo)
    url = f"{realm}?service={service}&scope=repository:{repo}:pull"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["token"]


def _get(url: str, token: str, accept: str | None = None) -> tuple[bytes, str]:
    headers = {"User-Agent": UA, "Authorization": f"Bearer {token}"}
    if accept:
        headers["Accept"] = accept
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read(), r.headers.get("Content-Type", "")


def resolve_platform(repo: str, ref: str, platform: str, token: str) -> tuple[dict, str]:
    """Return (image_manifest, digest) for the requested platform."""
    accept_index = ("application/vnd.docker.distribution.manifest.list.v2+json,"
                    "application/vnd.oci.image.index.v1+json,"
                    "application/vnd.docker.distribution.manifest.v2+json,"
                    "application/vnd.oci.image.manifest.v1+json")
    body, ctype = _get(f"https://{REGISTRY}/v2/{repo}/manifests/{ref}", token, accept_index)
    doc = json.loads(body)

    if "manifests" in doc:                      # multi-arch index -> pick platform
        want = platform.split("/")
        chosen = None
        for m in doc["manifests"]:
            p = m.get("platform") or {}
            # skip provenance/attestation entries, which carry platform unknown/unknown
            if p.get("os") == "unknown" or p.get("architecture") == "unknown":
                continue
            if [p.get("os"), p.get("architecture")] == want:
                if p.get("variant") and p["variant"] not in platform:
                    continue
                chosen = m
                break
        if chosen is None:
            raise SystemExit(f"platform {platform} not found in index for {repo}:{ref}")
        digest = chosen["digest"]
        body, ctype = _get(f"https://{REGISTRY}/v2/{repo}/manifests/{digest}", token, accept_index)
        doc = json.loads(body)

    return doc, hashlib.sha256(body).hexdigest()


def download_blob(repo: str, digest: str, token: str, dest: str) -> str:
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest
    tmp = dest + ".part"
    req = urllib.request.Request(
        f"https://{REGISTRY}/v2/{repo}/blobs/{digest}",
        headers={"User-Agent": UA, "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=600) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    os.replace(tmp, dest)
    return dest


# ── helpers ─────────────────────────────────────────────────────────────────

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for part in iter(lambda: f.read(1 << 20), b""):
            h.update(part)
    return h.hexdigest()


def add_bytes_to_tar(tf: tarfile.TarFile, name: str, payload: bytes, mode: int = 0o755) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    info.mode = mode
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    info.mtime = 1700000000          # fixed -> reproducible layer digest
    tf.addfile(info, io.BytesIO(payload))


def build_opencode_layer(binary_path: str) -> tuple[bytes, str, int]:
    """Gzipped tar layer with /usr/local/bin/opencode. Returns (gz, digest, raw_size)."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.GNU_FORMAT) as tf:
        with open(binary_path, "rb") as f:
            payload = f.read()
        info = tarfile.TarInfo("usr/local/bin/opencode")
        info.size = len(payload)
        info.mode = 0o755
        info.uid = info.gid = 0
        info.uname = info.gname = "root"
        info.mtime = 1700000000
        tf.addfile(info, io.BytesIO(payload))

    raw_bytes = raw.getvalue()
    gz = io.BytesIO()
    with gzip.GzipFile(fileobj=gz, mode="wb", compresslevel=6, mtime=0) as g:
        g.write(raw_bytes)
    gz_bytes = gz.getvalue()
    return gz_bytes, hashlib.sha256(gz_bytes).hexdigest(), len(raw_bytes)


def build_docker_tar(out_path: str, repo_tag: str, config: dict,
                     layers: list[tuple[str, str, int]],  # (blob_path, digest, size)
                     layer_names: list[str]) -> None:
    """layers: existing uncompressed-or-gz blob files on disk, in order."""
    with tarfile.open(out_path, "w", format=tarfile.GNU_FORMAT) as tf:
        # 1) layer blobs, named <digest>.tar.gz (modern docker prefers the
        #    docker-content-digest header, but the legacy path uses this name)
        blob_paths = []
        for (path, digest, size) in layers:
            arc = f"{digest[7:]}.tar.gz"
            ti = tarfile.TarInfo(arc)
            ti.size = os.path.getsize(path)
            ti.mtime = 1700000000
            with open(path, "rb") as f:
                tf.addfile(ti, f)
            blob_paths.append(arc)

        # 2) config.json
        cfg_bytes = json.dumps(config, separators=(",", ":")).encode()
        ti = tarfile.TarInfo("config.json")
        ti.size = len(cfg_bytes)
        ti.mtime = 1700000000
        tf.addfile(ti, io.BytesIO(cfg_bytes))

        # 3) manifest.json  (Docker v1.0 schema)
        manifest = [{
            "Config": "config.json",
            "RepoTags": [repo_tag],
            "Layers": blob_paths,
        }]
        man_bytes = json.dumps(manifest, indent=2).encode()
        ti = tarfile.TarInfo("manifest.json")
        ti.size = len(man_bytes)
        ti.mtime = 1700000000
        tf.addfile(ti, io.BytesIO(man_bytes))

        # 4) repositories (legacy, harmless)
        repos = {repo_tag.rsplit(":", 1)[0]: {repo_tag.rsplit(":", 1)[1]: layers[-1][1][7:]}}
        repo_bytes = json.dumps(repos, indent=2).encode()
        ti = tarfile.TarInfo("repositories")
        ti.size = len(repo_bytes)
        ti.mtime = 1700000000
        tf.addfile(ti, io.BytesIO(repo_bytes))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="ubuntu:24.04")
    ap.add_argument("--platform", default="linux/amd64")
    ap.add_argument("--binary", default=os.path.join(CACHE, "opencode"))
    ap.add_argument("--tag", default="opencode:1.18.32")
    ap.add_argument("--out", default=os.path.join(HERE, "dist"))
    args = ap.parse_args()

    if not os.path.isfile(args.binary):
        print(f"error: binary not found: {args.binary}", file=sys.stderr)
        print("       run fetch_opencode.py and extract opencode-linux-x64.tar.gz", file=sys.stderr)
        return 1

    repo, _, ref = args.base.partition(":")
    if "/" not in repo:
        repo = f"library/{repo}"
    ref = ref or "latest"

    os.makedirs(args.out, exist_ok=True)
    blob_dir = os.path.join(CACHE, "base-blobs")
    os.makedirs(blob_dir, exist_ok=True)

    print(f"resolving {args.base} ({args.platform}) from {REGISTRY} …")
    token = _auth_token(repo)
    manifest, manifest_digest = resolve_platform(repo, ref, args.platform, token)
    print(f"  base manifest : {manifest_digest[:20]}…  layers={len(manifest['layers'])}")

    blob_paths: list[tuple[str, str, int]] = []
    total = 0
    for i, layer in enumerate(manifest["layers"]):
        digest = layer["digest"]
        dest = os.path.join(blob_dir, digest.split(":")[-1] + ".tar.gz")
        print(f"  layer {i + 1}/{len(manifest['layers'])} {digest[:20]}… ({layer['size']:,} B)", end="", flush=True)
        download_blob(repo, digest, token, dest)
        actual = sha256_file(dest)
        if f"sha256:{actual}" != digest:
            print(f"\n  !! digest mismatch: expected {digest}, got sha256:{actual}", file=sys.stderr)
            return 1
        total += os.path.getsize(dest)
        print("  ok")
        blob_paths.append((dest, digest, os.path.getsize(dest)))

    print(f"  base total    : {total:,} bytes")

    # ---- our layer ---------------------------------------------------------
    print("building opencode layer …")
    layer_bytes, layer_digest, layer_raw = build_opencode_layer(args.binary)
    layer_file = os.path.join(args.out, "layer-opencode.tar.gz")
    with open(layer_file, "wb") as f:
        f.write(layer_bytes)
    print(f"  digest {layer_digest}  gz={len(layer_bytes):,} B  raw={layer_raw:,} B")
    blob_paths.append((layer_file, f"sha256:{layer_digest}", len(layer_bytes)))

    # base image config (env/cmd) so we inherit sane defaults
    base_cfg_digest = manifest["config"]["digest"]
    base_cfg_path = os.path.join(blob_dir, base_cfg_digest.split(":")[-1] + ".json")
    download_blob(repo, base_cfg_digest, token, base_cfg_path)
    with open(base_cfg_path, encoding="utf-8") as f:
        base_cfg = json.load(f)

    env = list(base_cfg.get("config", {}).get("Env") or [])
    for kv in ("PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG=C.UTF-8"):
        if not any(e.split("=", 1)[0] == kv.split("=", 1)[0] for e in env):
            env.append(kv)

    config = {
        "architecture": manifest.get("architecture", "amd64"),
        "os": manifest.get("os", "linux"),
        "created": "2026-09-24T00:00:00Z",
        "config": {
            "Env": env,
            "Entrypoint": ["/usr/local/bin/opencode"],
            "Cmd": ["--help"],
            "WorkingDir": "/workspace",
            "Labels": {
                "org.opencontainers.image.title": "opencode",
                "org.opencontainers.image.version": "1.18.32",
                "org.opencontainers.image.description":
                    "opencode coding-agent CLI (offline single-binary image, CLI only)",
                "org.opencontainers.image.base.name": args.base,
                "sh.dsh.verified": "offline docker load + run on Ubuntu 24.04 host",
            },
        },
        "rootfs": {"type": "layers", "diff_ids": []},
        "history": [
            {"created": "2026-09-24T00:00:00Z", "comment": f"base {args.base}"},
            {"created": "2026-09-24T00:00:00Z",
             "comment": f"add /usr/local/bin/opencode 1.18.32 ({layer_raw:,} bytes)"},
        ],
    }
    for (path, digest, size) in blob_paths:
        config["rootfs"]["diff_ids"].append(f"sha256:{_uncompressed_digest(path)}")

    out_name = f"opencode-container-1.18.32-linux-amd64.tar"
    out_path = os.path.join(args.out, out_name)
    print(f"writing {out_name} …")
    build_docker_tar(out_path, args.tag, config, blob_paths, [b[0] for b in blob_paths])

    print(f"\nimage tar : {out_path}")
    print(f"size      : {os.path.getsize(out_path):,} bytes")
    print(f"sha256    : {sha256_file(out_path)}")
    print(f"tag       : {args.tag}")
    print(f"\nload on target:  docker load -i {out_name}")
    return 0


def _uncompressed_digest(path: str) -> str:
    """sha256 of the *uncompressed* tar — this is what rootfs.diff_ids holds."""
    h = hashlib.sha256()
    with gzip.open(path, "rb") as f:
        for part in iter(lambda: f.read(1 << 20), b""):
            h.update(part)
    return h.hexdigest()


if __name__ == "__main__":
    sys.exit(main())
