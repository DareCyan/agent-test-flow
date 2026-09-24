#!/usr/bin/env bash
#
# Offline installer for the opencode CLI.
#
# Installs a self-contained `opencode` binary from this bundle. No network
# access is required or attempted.
#
#   ./install.sh                 install to /usr/local/bin (needs root)
#   ./install.sh --prefix DIR    install to DIR/bin
#   ./install.sh --user          install to ~/.opencode/bin (no root)
#   ./install.sh --force         overwrite an existing opencode binary
#
# Exit codes: 0 ok, 1 usage/precondition error, 2 checksum mismatch.

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
APP=opencode

PREFIX=/usr/local
USE_USER_DIR=false
FORCE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prefix)
            [[ -n "${2:-}" ]] || { echo "error: --prefix needs a directory" >&2; exit 1; }
            PREFIX="$2"; shift 2 ;;
        --user)
            USE_USER_DIR=true; shift ;;
        --force)
            FORCE=true; shift ;;
        -h|--help)
            sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)
            echo "error: unknown option '$1' (try --help)" >&2; exit 1 ;;
    esac
done

c_red=$'\033[0;31m'; c_grn=$'\033[0;32m'; c_ylw=$'\033[0;33m'; c_off=$'\033[0m'
info() { printf '%s==>%s %s\n' "$c_grn" "$c_off" "$*"; }
warn() { printf '%s!==%s %s\n' "$c_ylw" "$c_off" "$*" >&2; }
die()  { printf '%serr%s %s\n' "$c_red" "$c_off" "$*" >&2; exit 1; }

# ---------------------------------------------------------------- locate binary
TARBALL=$(find "$SCRIPT_DIR" -maxdepth 2 -name 'opencode-linux-x64*.tar.gz' -type f | head -n1)
[[ -n "$TARBALL" ]] || die "no opencode-linux-x64*.tar.gz found in $SCRIPT_DIR"

if $USE_USER_DIR; then
    BIN_DIR="$HOME/.opencode/bin"
else
    BIN_DIR="$PREFIX/bin"
fi

info "bundle     : $SCRIPT_DIR"
info "archive    : $(basename "$TARBALL")"
info "target dir : $BIN_DIR"

# ------------------------------------------------------------- verify checksum
if [[ -f "$SCRIPT_DIR/SHA256SUMS" ]]; then
    info "verifying SHA-256 of $(basename "$TARBALL")"
    expected=$(awk -v n="$(basename "$TARBALL")" '$2==n || $2=="*"n {print $1}' "$SCRIPT_DIR/SHA256SUMS")
    if [[ -n "$expected" ]]; then
        actual=$(sha256sum "$TARBALL" | awk '{print $1}')
        if [[ "$actual" != "$expected" ]]; then
            die "checksum mismatch for $(basename "$TARBALL")
     expected $expected
     actual   $actual"
        fi
        info "checksum OK ($actual)"
    else
        warn "no checksum entry for $(basename "$TARBALL"); skipping"
    fi
else
    warn "SHA256SUMS not present; skipping integrity check"
fi

# ------------------------------------------------------------- extract stage
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

info "extracting archive"
tar -xzf "$TARBALL" -C "$STAGE"
[[ -f "$STAGE/$APP" ]] || die "archive did not contain '$APP'"
chmod 0755 "$STAGE/$APP"

# ------------------------------------------------------------ install binary
if [[ -e "$BIN_DIR/$APP" && "$FORCE" != true ]]; then
    existing=$("$BIN_DIR/$APP" --version 2>/dev/null || echo "unknown")
    warn "already installed at $BIN_DIR/$APP (version: $existing)"
    warn "re-run with --force to replace it"
    exit 0
fi

mkdir -p "$BIN_DIR" 2>/dev/null || die "cannot create $BIN_DIR (need root, or use --user)"
[[ -w "$BIN_DIR" ]] || die "$BIN_DIR is not writable (need root, or use --user)"

hold=""
[[ -e "$BIN_DIR/$APP" ]] && hold="$BIN_DIR/.$APP.old.$$"
[[ -n "$hold" ]] && mv "$BIN_DIR/$APP" "$hold"
install -m 0755 "$STAGE/$APP" "$BIN_DIR/$APP"
[[ -n "$hold" ]] && rm -f "$hold"

info "installed $BIN_DIR/$APP ($(du -h "$BIN_DIR/$APP" | cut -f1))"

# ------------------------------------------------------------- PATH guidance
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        warn "$BIN_DIR is not on your PATH. Add it with:"
        if $USE_USER_DIR; then
            echo "    export PATH=\"$BIN_DIR:\$PATH\""
            echo "    grep -qF '$BIN_DIR' ~/.bashrc || echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.bashrc"
        else
            echo "    export PATH=\"$BIN_DIR:\$PATH\""
        fi
        ;;
esac

# ----------------------------------------------------------------- final check
info "verifying installation"
ver=$("$BIN_DIR/$APP" --version 2>&1) || die "installed binary failed to run"
printf '%s  ok %s %s --version -> %s%s\n' "$c_grn" "$c_off" "$APP" "$ver" "$c_off"
info "done. Run '$APP --help' to get started."
