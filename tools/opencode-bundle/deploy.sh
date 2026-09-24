#!/bin/bash
#
# Deploy and verify the opencode offline bundle ON THE TARGET SERVER.
#
# Run this on the server, as root, pointing at the extracted bundle directory:
#
#   scp opencode-cli-<ver>-linux-x64-offline.zip root@<SERVER_IP>:/tmp/
#   ssh root@<SERVER_IP>
#   cd /tmp && unzip -o opencode-cli-<ver>-linux-x64-offline.zip
#   bash /tmp/opencode-v<ver>-linux-x64/deploy.sh
#
# It is read-mostly: it verifies the archive, installs, and self-tests.
# Nothing is downloaded; the host needs no internet access.
#
# Pass a path to the extracted bundle dir as $1, or run it from inside it.

set -uo pipefail

DIR="${1:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)}"
cd "$DIR" || { echo "cannot enter $DIR"; exit 1; }

echo "===[1] bundle contents ==="
ls -l
echo

echo "===[2] verify SHA256SUMS ==="
if command -v sha256sum >/dev/null 2>&1; then
    sha256sum -c SHA256SUMS; echo "exit=$?"
else
    echo "sha256sum unavailable; skipping"
fi
echo

echo "===[3] shell syntax ==="
for s in install.sh verify.sh; do
    bash -n "$s" && echo "  $s: syntax OK" || echo "  $s: SYNTAX ERROR"
done
echo

echo "===[4] install ==="
bash ./install.sh --force
echo "install exit=$?"
echo

echo "===[5] where is it ==="
type -a opencode
echo

echo "===[6] offline verification ==="
bash ./verify.sh
echo "verify exit=$?"
echo

echo "===[7] binary facts ==="
BIN=$(command -v opencode)
ls -l "$BIN"
sha256sum "$BIN"
readelf -h "$BIN" 2>/dev/null | grep -E 'Class:|Type:|Machine:'

echo
echo "===[8] runtime smoke ==="
opencode --version
opencode debug paths | head -3
