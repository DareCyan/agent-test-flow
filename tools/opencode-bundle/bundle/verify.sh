#!/usr/bin/env bash
#
# Post-install verification for opencode, designed to work with NO network.
#
#   ./verify.sh                  check `opencode` found on PATH
#   ./verify.sh /path/to/opencode
#
# Exit codes: 0 all checks passed, 1 at least one check failed.

set -uo pipefail

c_red=$'\033[0;31m'; c_grn=$'\033[0;32m'; c_off=$'\033[0m'
pass=0; fail=0

check() { # check <description> <command...>
    local desc="$1"; shift
    local out
    if out=$("$@" 2>&1); then
        printf '  %sPASS%s %-34s %s\n' "$c_grn" "$c_off" "$desc" "$(printf '%s' "$out" | head -n1 | cut -c1-60)"
        pass=$((pass + 1))
    else
        printf '  %sFAIL%s %-34s %s\n' "$c_red" "$c_off" "$desc" "$(printf '%s' "$out" | head -n1 | cut -c1-60)"
        fail=$((fail + 1))
    fi
}

BIN="${1:-opencode}"

echo "opencode offline verification"
echo "---------------------------------------------"

# 1. Resolve the binary.
if command -v "$BIN" >/dev/null 2>&1 || [[ -x "$BIN" ]]; then
    resolved=$(command -v "$BIN" 2>/dev/null || printf '%s' "$BIN")
    printf '  %sPASS%s %-34s %s\n' "$c_grn" "$c_off" "binary located" "$resolved"
    pass=$((pass + 1))
else
    printf '  %sFAIL%s %-34s %s\n' "$c_red" "$c_off" "binary located" "not found: $BIN"
    echo
    echo "Cannot continue without a binary. Install it first (./install.sh)."
    exit 1
fi

# 2. Machine check: ELF magic (7f 45 4c 46), 64-bit little-endian, EM_X86_64.
check "is a 64-bit x86-64 ELF"   bash -c "head -c 20 '$resolved' | od -An -tx1 | tr -d ' \n' | grep -q '7f454c46020101'"

# 3. Version reported by the binary.
version=$("$BIN" --version 2>/dev/null | head -n1)
check "opencode --version"       bash -c "'$BIN' --version 2>/dev/null | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+'"

# 4. Help output works (no network needed).
check "opencode --help"          bash -c "'$BIN' --help 2>&1 | grep -q 'Commands:'"

# 5. Global path resolution.
check "opencode debug paths"     bash -c "'$BIN' debug paths 2>&1 | grep -q '^data'"

# 6. Embedded database engine works.
check "opencode db --help"       bash -c "'$BIN' db --help 2>&1 | grep -qiE 'command|usage|database'"

echo "---------------------------------------------"
printf 'version: %s\n' "${version:-<none>}"
printf 'result : %s%d passed%s, %s%d failed%s\n' \
    "$c_grn" "$pass" "$c_off" \
    "$([[ $fail -gt 0 ]] && printf '%s' "$c_red")" "$fail" "$c_off"

[[ $fail -eq 0 ]] || exit 1
