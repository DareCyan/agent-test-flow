# opencode CLI — offline bundle (linux-x64)

Self-contained installer for the **opencode** coding-agent CLI, version **1.18.32**.
No network access is required to install or verify it.

> Detailed, server-specific instructions: **[INSTALL.md](INSTALL.md)**

## Quick start (on the target Linux host)

```bash
unzip opencode-cli-v1.18.32-linux-x64-offline.zip
cd opencode-v1.18.32-linux-x64

sudo ./install.sh     # installs to /usr/local/bin/opencode
./verify.sh           # offline verification, 6 checks
opencode --version    # -> 1.18.32
```

## Contents

| File | Purpose |
| --- | --- |
| `opencode-linux-x64.tar.gz` | Upstream release archive containing the `opencode` binary |
| `install.sh` | Verify checksum, unpack, install, self-test |
| `verify.sh` | Offline post-install verification (exit 0 = all passed) |
| `SHA256SUMS` | SHA-256 of every file in this bundle |
| `INSTALL.md` | Full server-specific installation guide |
| `LICENSE` | Upstream license |
| `upstream-install.sh.reference` | Official network installer, for reference only |

## Install options

```bash
./install.sh --prefix /opt    # install into /opt/bin
./install.sh --user           # install into ~/.opencode/bin (no root)
./install.sh --force          # replace an existing installation
```

## Requirements

- Linux, x86-64, glibc (verified against Ubuntu 24.04.4 LTS, glibc 2.39)
- `tar`, `gzip`, `sha256sum` (present on any standard Ubuntu install)

## Notes

- Installing and verifying the CLI is fully offline.
- Actually **running** an agent still needs network access to your model provider.
- Do **not** run `opencode upgrade` or `upstream-install.sh.reference` on a host
  without internet egress — they fetch from GitHub.

Binaries are redistributed from the upstream release; see `LICENSE`.
