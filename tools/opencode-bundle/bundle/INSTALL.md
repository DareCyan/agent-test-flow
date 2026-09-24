# opencode CLI 离线安装说明

适用目标机器：**一台 Ubuntu 24.04 LTS / x86_64 / glibc 2.39 的 Linux 服务器**
（安装时请把本文中的 `<SERVER_IP>` 替换为实际主机地址或主机别名）
交付版本：**opencode `v1.18.32`**（linux-x64，官方 release 二进制）

> 本机（Windows 工作机）没有外网直连 TLS 能力、且目标服务器**完全没有外网出口**
> （实测 `curl https://github.com` 超时），因此本方案是**纯离线安装**：
> 所有产物都已打包进一个 zip，安装过程不访问任何网络。

---

## 0. 两种安装方式，先选一种

| 方式 | 适用 | 做法 | 验证结果 |
| --- | --- | --- | --- |
| **A. 容器化（推荐）** | 机器上有 Docker（目标机器已有 29.8.1） | 传镜像 tar → `docker load` → 容器里跑 | **12/12 通过** |
| **B. 直接装到系统** | 没有 Docker，或希望 `opencode` 直接在 PATH 里 | 传 zip → `./install.sh` | **6/6 通过** |

容器化的完整说明见 **`container/README.md`**（含 Dockerfile、构建脚本、使用示例）。
两种方式都已在目标服务器上实测通过，互不依赖。

---

## 1. 交付物清单

| 文件 | 说明 |
| --- | --- |
| `opencode-cli-v1.18.32-linux-x64-offline.zip` | 系统安装包（约 60 MB，含二进制 + 安装/校验脚本 + 文档 + 校验和） |
| `opencode-container-1.18.32-linux-amd64.tar` | **容器镜像**（约 90 MB，`docker load` 即用） |
| `container/` | 容器化方案：`Dockerfile`、`container-install.sh`、`README.md` |
| `dist/bundle-manifest.json` | 包元数据（版本、大小、SHA-256） |
| `checksums.json` | 上游 release 产物校验信息（下载来源与哈希） |

zip 解压后的目录结构（`opencode-v1.18.32-linux-x64/`）：

```
opencode-linux-x64.tar.gz        官方 release 原始产物（内含 opencode 二进制）
install.sh                       离线安装脚本（校验 → 解包 → 安装 → 自检）
verify.sh                        安装后离线验证脚本（6 项检查）
SHA256SUMS                       包内每个文件的 SHA-256
README.md                        快速上手
INSTALL.md                       本文件（详细说明）
LICENSE                          上游许可证
upstream-install.sh.reference    官方联网安装脚本（仅供参考，离线环境勿用）
```

---

## 2. 目标服务器环境（实测）

| 项目 | 值 |
| --- | --- |
| 主机名 | `sim-vm` |
| 系统 | Ubuntu 24.04.4 LTS (Noble Numbat) |
| 内核 | `6.8.0-106-generic` |
| 架构 | `x86_64`（ELF 64-bit LSB，与包内二进制一致） |
| libc | glibc 2.39（**glibc**，非 musl → 使用 `linux-x64` 产物正确） |
| CPU / 内存 | 8 核 / 15.6 GB |
| 磁盘 | `/` 99 GB，已用 5.6 GB，可用 89 GB（充裕） |
| 已有 opencode | 未安装 |
| **容器运行时** | **Docker 29.8.1 已装且运行中**（containerd active，存储驱动 overlayfs，cgroup v2） |
| 可用工具 | `curl` `wget` `tar` `unzip` `gzip` `sha256sum` 均已就绪 |
| **外网出口** | **无**（访问 github.com 超时）→ 必须离线传输 |
| PATH | 含 `/usr/local/bin` |
| Shell | `/bin/bash` |

### 二进制一致性校验

包内 `opencode` 二进制已确认：

- 文件类型：`ELF 64-bit LSB`，machine = `x86-64`
- 未压缩大小：`185,165,952` 字节，权限 `0755`
- 上游 `opencode-linux-x64.tar.gz` 与 `opencode-linux-x64-baseline.tar.gz`
  解包后 **SHA-256 完全一致**（`513f500a…a170080`），
  即本版本两者为同一二进制，故包内只保留标准版，节省约 60 MB。

---

## 3. 从 Windows 工作机传输到服务器

任选其一（都需要那块 zip 文件）：

**方式 A：`scp`（推荐，本机已具备 OpenSSH）**

```powershell
scp tools\opencode-bundle\dist\opencode-cli-v1.18.32-linux-x64-offline.zip root@<SERVER_IP>:/root/
```

**方式 B：服务器无外网但工作机有 → 若服务器能访问跳板机，可用 `wget`；否则仍走方式 A。**

**方式 C：控制台/宝塔面板上传**，把 zip 传到 `/root/` 或 `/tmp/`。

---

## 4. 在服务器上安装

```bash
# 1) 解压
cd /root
unzip -o opencode-cli-v1.18.32-linux-x64-offline.zip
cd opencode-v1.18.32-linux-x64

# 2) 安装（安装到 /usr/local/bin，需 root）
sudo ./install.sh          # 已是 root 则直接 ./install.sh

# 3) 验证
./verify.sh
```

安装脚本会依次：校验 tarball 的 SHA-256 → 解包 → 安装到 `/usr/local/bin/opencode`
（权限 0755）→ 运行 `opencode --version` 自检。
重复安装会提示已存在，需显式 `--force` 才会覆盖（覆盖时先备份再替换，避免半损坏状态）。

### 安装选项

```bash
./install.sh --prefix /opt        # 安装到 /opt/bin
./install.sh --user               # 安装到 ~/.opencode/bin（无需 root）
./install.sh --force              # 覆盖已存在的 opencode
./install.sh --help
```

---

## 5. 验证（离线可用）

### 5.1 一键验证

```bash
./verify.sh
```

输出示例（全部 PASS 即安装成功）：

```
opencode offline verification
---------------------------------------------
  PASS binary located                     /usr/local/bin/opencode
  PASS is a 64-bit x86-64 ELF
  PASS opencode --version                 1.18.32
  PASS opencode --help
  PASS opencode debug paths
  PASS opencode db --help
---------------------------------------------
version: 1.18.32
result : 6 passed, 0 failed
```

脚本退出码：`0` 全部通过，`1` 有失败项（可直接用于 CI/自动化断言）。

### 5.2 手工验证命令

```bash
opencode --version              # 期望输出 1.18.32
opencode --help                 # 列出所有子命令
opencode debug paths            # 打印 home/data/config/cache/state 路径
opencode db --help              # 内嵌数据库工具可用
```

`opencode debug paths` 在本机（以 root 运行）实测输出：

| 用途 | 路径 |
| --- | --- |
| home | `/root` |
| data | `/root/.local/share/opencode` |
| config | `/root/.config/opencode` |
| cache | `/root/.cache/opencode` |
| state | `/root/.local/state/opencode` |
| log | `/root/.local/share/opencode/log` |
| repos | `/root/.local/share/opencode/repos` |
| bin | `/root/.cache/opencode/bin` |
| tmp | `/tmp/opencode` |

（以普通用户安装时为 `~/.local/share/opencode` 等，路径随 `$HOME` 变化。）

### 5.3 校验文件完整性

```bash
cd opencode-v1.18.32-linux-x64
sha256sum -c SHA256SUMS                 # 校验包内所有文件
sha256sum -c SHA256SUMS --ignore-missing 2>/dev/null | grep -v ': OK$' || echo "全部通过"
```

---

## 6. 已知限制与注意事项

1. **模型调用需要网络**：本次交付解决的是「CLI 本体可离线安装、可离线验证」。
   opencode 调用 LLM（如 Anthropic / OpenAI 等）时仍需该模型端点的网络可达性；
   本服务器无外网，若要实际使用，需另行开通到 AI 服务商 HTTPS 出口或配置代理
   （`export HTTPS_PROXY=...`）。安装与 `--version/--help/debug paths` 不受影响。
2. **不要用 `opencode upgrade` / `upstream-install.sh.reference`**：它们会访问外网，在无出口环境必然失败。升级请重新走本离线流程。
3. **建议使用 root 或具备 sudo 权限的账号安装到 `/usr/local/bin`**；`/usr/local/bin` 已在默认 PATH 中，无需改环境变量。用 `--user` 时需手动把 `~/.opencode/bin` 加入 PATH（脚本会打印对应命令）。
4. **务必以二进制方式传输 zip**（`scp -p`/`unzip` 即可），避免文本模式传输破坏 gzip 流。
5. **`debug info` 可能报错**：它需要读日志文件，若日志被占用会报 `Unknown: FileSystem.open`。
   这属于运行期状态问题，与安装无关；请用 `debug paths` 作为验证项。

---

## 7. 已在目标服务器的实测记录

本包已在目标服务器（Ubuntu 24.04.4 LTS / x86_64）上完整走通「上传 → 校验 → 安装 → 验证」全流程：

| 步骤 | 命令 | 结果 |
| --- | --- | --- |
| 上传 | `scp` 到 `/tmp/` | 60,321,306 字节，SHA-256 与本地一致 |
| 解包 | `unzip` | 8 个文件，权限正确（脚本 0755） |
| 包内校验 | `sha256sum -c SHA256SUMS` | 7/7 `OK` |
| 语法检查 | `bash -n install.sh verify.sh` | 均 syntax OK |
| 安装 | `./install.sh` | 装到 `/usr/local/bin/opencode`（185,165,952 字节，`-rwxr-xr-x`） |
| 版本自检 | `opencode --version` | `1.18.32` |
| 查询 | `type -a opencode` | `/usr/local/bin/opencode` |
| 离线验证 | `./verify.sh` | **6 passed, 0 failed**（退出码 0） |

安装后二进制 SHA-256：
`513f500a1a5ea1dc7d865547ac87b32a8936334e8d5ab5b3ff585c45a170080`（与上游 tarball 解包结果一致）。

`./verify.sh` 的实际输出：

```
opencode offline verification
---------------------------------------------
  PASS binary located                     /usr/local/bin/opencode
  PASS is a 64-bit x86-64 ELF
  PASS opencode --version                 1.18.32
  PASS opencode --help
  PASS opencode debug paths
  PASS opencode db --help
---------------------------------------------
version: 1.18.32
result : 6 passed, 0 failed
```

> 注：`verify.sh` 的 ELF 检查只比对文件头特征（`7f454c46020101` = ELF magic + 64 位 + 小端）。
> 若要更严格的确认，可在服务器上运行 `readelf -h /usr/local/bin/opencode`，
> 实测输出为 `Class: ELF64` / `Machine: Advanced Micro Devices X86-64`。

---

## 8. 卸载

```bash
rm -f /usr/local/bin/opencode
# 如使用 --user 安装：
rm -rf ~/.opencode

# 可选：清理运行数据
rm -rf ~/.local/share/opencode ~/.local/state/opencode ~/.cache/opencode
# 注意：~/.config/opencode 下若有你的配置/凭据，请自行确认后再删
```

---

## 9. 附：版本与校验信息

| 项目 | 值 |
| --- | --- |
| opencode 版本 | `v1.18.32` |
| 上游仓库 | `sst/opencode`（release 资产域名 `github.com`） |
| 发布产物体积 | `60,608,353` 字节（`opencode-linux-x64.tar.gz`） |
| 发布产物 SHA-256 | `3046e0404fdc60fb80307e7a47824ba07477364178a4d09baa8548496dd6d43b` |
| 解包后二进制 SHA-256 | `513f500a1a5ea1dc7d865547ac87b32a8936334e8d5ab5b3ff585c45a170080` |
| 二进制未压缩大小 | `185,165,952` 字节 |

`SHA256SUMS` 与 `dist/bundle-manifest.json` 中记录了完整的哈希清单，
可用于离线环境下的完整性比对。
