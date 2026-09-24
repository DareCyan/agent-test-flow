"""
Package the opencode CLI into a self-contained, offline-installable ZIP bundle.

Reads the artifacts downloaded by fetch_opencode.py from ./cache and emits
./dist/opencode-cli-<version>-linux-x64-offline.zip

The bundle is deliberately self-contained: the target server has no outbound
internet, so nothing may be fetched at install time.

Usage:  python build_bundle.py
"""
import hashlib
import json
import os
import shutil
import subprocess
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
BUNDLE = os.path.join(HERE, "bundle")
DIST = os.path.join(HERE, "dist")

# Files inside bundle/ that must be installed with the executable bit set.
EXECUTABLES = {"install.sh", "verify.sh"}
# Files that must use Unix line endings.
UNIX_TEXT = {"install.sh", "verify.sh", "SHA256SUMS", "README.md", "INSTALL.md"}


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for part in iter(lambda: f.read(chunk), b""):
            h.update(part)
    return h.hexdigest()


def normalize_line_endings(path):
    """CRLF -> LF. Shell scripts written on Windows must not keep CRLF."""
    with open(path, "rb") as f:
        data = f.read()
    fixed = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    if fixed != data:
        with open(path, "wb") as f:
            f.write(fixed)
        return True
    return False


def main():
    with open(os.path.join(HERE, "checksums.json"), encoding="utf-8") as f:
        manifest = json.load(f)

    version = manifest["version"]
    artifacts = manifest["artifacts"]
    if not artifacts:
        raise SystemExit("no artifacts recorded; run fetch_opencode.py first")

    primary = next(a for a in artifacts if a["name"] == "opencode-linux-x64.tar.gz")

    stage = os.path.join(HERE, "stage")
    shutil.rmtree(stage, ignore_errors=True)
    top = os.path.join(stage, f"opencode-{version}-linux-x64")
    os.makedirs(top)

    # ---- binary archive -----------------------------------------------------
    src = os.path.join(CACHE, primary["name"])
    shutil.copy2(src, os.path.join(top, primary["name"]))
    print(f"staged {primary['name']} ({os.path.getsize(src):,} bytes)")

    # ---- support files ------------------------------------------------------
    for name in sorted(os.listdir(BUNDLE)):
        s = os.path.join(BUNDLE, name)
        if os.path.isfile(s):
            shutil.copy2(s, os.path.join(top, name))
            print(f"staged {name}")

    # The upstream installer is included for reference only (it needs network).
    ref = os.path.join(CACHE, "upstream-install")
    if os.path.exists(ref):
        shutil.copy2(ref, os.path.join(top, "upstream-install.sh.reference"))
        print("staged upstream-install.sh.reference")

    # ---- line endings -------------------------------------------------------
    for name in UNIX_TEXT:
        p = os.path.join(top, name)
        if os.path.exists(p) and normalize_line_endings(p):
            print(f"normalized line endings: {name}")
    for name in os.listdir(top):
        p = os.path.join(top, name)
        if name.endswith(".sh.reference") and normalize_line_endings(p):
            print(f"normalized line endings: {name}")

    # ---- checksums ----------------------------------------------------------
    names = [n for n in sorted(os.listdir(top)) if n != "SHA256SUMS"]
    lines = []
    for n in names:
        if n == f"opencode-{version}-linux-x64" :
            continue
        lines.append(f"{sha256(os.path.join(top, n))}  {n}")
    with open(os.path.join(top, "SHA256SUMS"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote SHA256SUMS ({len(lines)} entries)")

    # ---- emit zip -----------------------------------------------------------
    os.makedirs(DIST, exist_ok=True)
    zip_name = f"opencode-cli-{version}-linux-x64-offline.zip"
    zip_path = os.path.join(DIST, zip_name)

    compression = zipfile.ZIP_DEFLATED
    try:
        subprocess.run(
            ["tar", "--version"], capture_output=True, check=True, shell=False
        )
    except Exception:
        pass

    with zipfile.ZipFile(zip_path, "w", compression, compresslevel=6) as z:
        for root, dirs, files in os.walk(stage):
            dirs.sort()
            for fn in sorted(files):
                full = os.path.join(root, fn)
                arc = os.path.relpath(full, stage).replace(os.sep, "/")
                zi = zipfile.ZipInfo.from_file(full, arc)
                # Preserve Unix mode (0755 for scripts/binaries, 0644 otherwise).
                mode = 0o755 if fn in EXECUTABLES or fn.endswith(".sh.reference") else 0o644
                zi.external_attr = (mode & 0xFFFF) << 16
                zi.compress_type = compression
                with open(full, "rb") as fh:
                    z.writestr(zi, fh.read())

    print(f"\nzip: {zip_path}")
    print(f"size: {os.path.getsize(zip_path):,} bytes")
    print(f"zip sha256: {sha256(zip_path)}")

    # Record bundle metadata for the docs / report.
    meta = {
        "version": version,
        "zip": zip_name,
        "zip_size": os.path.getsize(zip_path),
        "zip_sha256": sha256(zip_path),
        "binary_tarball": primary["name"],
        "binary_tarball_sha256": primary["sha256"],
        "binary_inner_sha256": None,
        "contents": names + ["SHA256SUMS"],
    }
    with open(os.path.join(DIST, "bundle-manifest.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    print("wrote dist/bundle-manifest.json")


if __name__ == "__main__":
    main()
