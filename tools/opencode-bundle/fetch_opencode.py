"""
Download opencode CLI release artifacts and verify their SHA-256 checksums.

Uses urllib only (system TLS via Python) because the Windows curl/schannel
stack in this environment cannot acquire credentials.

Usage:  python fetch_opencode.py [version]
        (default: resolve the latest release via the GitHub API)
"""
import hashlib
import json
import os
import sys
import urllib.request
import urllib.error

REPO = "sst/opencode"
UA = "opencode-bundle/1.0"

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")


def api(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


def resolve_version(version):
    if version and version != "latest":
        return version if version.startswith("v") else "v" + version
    return api(f"https://api.github.com/repos/{REPO}/releases/latest")["tag_name"]


def download(url, dest):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        print(f"  [cached] {os.path.basename(dest)} ({os.path.getsize(dest):,} bytes)")
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 // total
                print(f"\r  {os.path.basename(dest)}: {done:,}/{total:,} ({pct}%)", end="", flush=True)
    print()
    os.replace(tmp, dest)
    return dest


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    version = resolve_version(sys.argv[1] if len(sys.argv) > 1 else "latest")
    print(f"opencode version: {version}")

    rel = api(f"https://api.github.com/repos/{REPO}/releases/tags/{version}")
    by_name = {a["name"]: a for a in rel["assets"]}

    wanted = [
        "opencode-linux-x64.tar.gz",
        "opencode-linux-x64-baseline.tar.gz",
    ]

    # Upstream checksum manifest, when the release publishes one.
    checksum_asset = next(
        (n for n in by_name if "checksum" in n.lower() or n.lower() in ("sha256sums", "sha256sum.txt")),
        None,
    )

    base = f"https://github.com/{REPO}/releases/download/{version}"
    manifest = {"version": version, "repo": REPO, "published_at": rel.get("published_at"), "artifacts": []}

    for name in wanted:
        if name not in by_name:
            print(f"!! asset missing upstream: {name}")
            continue
        info = by_name[name]
        print(f"downloading {name} ({info['size']:,} bytes)")
        path = download(info["browser_download_url"], os.path.join(CACHE, name))
        digest = sha256(path)
        manifest["artifacts"].append(
            {"name": name, "size": os.path.getsize(path), "sha256": digest, "url": info["browser_download_url"]}
        )
        print(f"  sha256 {digest}")

    if checksum_asset:
        print(f"downloading upstream manifest {checksum_asset}")
        cp = download(by_name[checksum_asset]["browser_download_url"], os.path.join(CACHE, checksum_asset))
        manifest["upstream_checksum_file"] = os.path.basename(cp)
        print(f"  saved {os.path.basename(cp)}")
    else:
        print("no upstream checksum asset published")

    out = os.path.join(HERE, "checksums.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
