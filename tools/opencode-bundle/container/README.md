# opencode CLI —— 容器化安装

在 **无外网** 的目标机器上用 Docker 跑 opencode。
镜像在**有外网的机器上**构建，导出成 tar 传过去导入 —— 目标机器不需要 pull/build。

已在一台真实服务器上完整验证通过（见文末实测记录）。

---

## 1. 为什么不能直接在目标机器上 build

实测目标服务器（Ubuntu 24.04.4 / x86_64）：

| 项目 | 情况 |
|---|---|
| Docker | **29.8.1 已装且运行中**（containerd active） |
| 存储驱动 / cgroup | `overlayfs` / cgroup v2 |
| 内核容器能力 | overlay、userns、全部 namespace 就绪 |
| 现有镜像 | 仅 `hello-world` |
| **外网出口** | **无**（访问 github.com 超时） |

所以 `docker build` / `docker pull` 在目标机器上都拿不到 base image。
结论：**离线导入**（`docker load`）是唯一可行路径。

---

## 2. 镜像内容

基于 `ubuntu:24.04`（单层）+ 一层加入 `/usr/local/bin/opencode`。

为什么基础镜像用 `ubuntu:24.04` 而**不装任何额外包**：

```
readelf -d opencode 的真实 DT_NEEDED：
    libc.so.6            ← glibc
    ld-linux-x86-64.so.2 ← 动态加载器
    libpthread.so.0
    libdl.so.2
    libm.so.6
```

二进制里能搜到 `libasound / libpulse / libsecret / libglib` 等字符串，
但它们**不是 DT_NEEDED**，而是 `dlopen` 可选加载（音频、系统密钥环）。
缺失只会让对应功能优雅降级，`--version / --help / debug / db` 全部正常。
所以不需要 `apt-get install` 一堆库，镜像保持最小。

| 元数据 | 值 |
|---|---|
| Entrypoint | `["/usr/local/bin/opencode"]` |
| Cmd | `["--help"]` |
| WorkingDir | `/workspace` |
| Os/Arch | `linux/amd64` |
| Layer 数 | 2 |
| 镜像大小 | 90.3 MB（磁盘占用 363 MB） |

---

## 3. 构建镜像（在有外网的机器上）

### 方式 A：本仓库的纯 Python 构建器（**不需要装 Docker**）

```bash
python tools/opencode-bundle/build_container.py
```

它会直接从 Docker Hub registry 拉 `ubuntu:24.04` 的层、手工拼出可 `docker load`
的镜像 tar，输出：

```
dist/opencode-container-1.18.32-linux-amd64.tar
```

输出里的 `sha256` 就是传输后要核对的校验值。

### 方式 B：标准 Dockerfile

`Dockerfile` 也在本目录，等价内容。需要把二进制放到构建上下文：

```bash
mkdir -p build-ctx && cp <解包出来的opencode> build-ctx/opencode
cp Dockerfile build-ctx/
cd build-ctx
docker build -t opencode:1.18.32 .
docker save opencode:1.18.32 -o opencode-container-1.18.32-linux-amd64.tar
```

> 本目录的 `Dockerfile` 里 `RUN /usr/local/bin/opencode --version` 是构建期冒烟测试，
> 二进制有问题会直接让构建失败，而不是等到运行时才发现。

---

## 4. 在目标机器上安装

```bash
# 1) 从工作机传过去
scp opencode-container-1.18.32-linux-amd64.tar root@<SERVER_IP>:/tmp/

# 2) 在目标机器上导入 + 验证（一键）
bash container-install.sh
```

或手动：

```bash
docker load -i /tmp/opencode-container-1.18.32-linux-amd64.tar
docker run --rm opencode:1.18.32 --version     # 应输出 1.18.32
```

`container-install.sh [镜像tar] [tag]` 会做 12 项检查并在失败时返回非 0：

- docker 可用、镜像文件存在
- `docker load` 成功、镜像就位
- 元数据（Entrypoint / Cmd / WorkingDir / Os-Arch / 层数）
- 容器内 `--version` == `1.18.32`、`--help` 正常、`debug paths` 正常
- 容器内二进制 sha256 == 官方产物、大小 == 185,165,952、权限 == 755
- 挂载 `-v <dir>:/workspace` 可运行、默认工作目录是 `/workspace`

---

## 5. 日常使用

```bash
# 版本 / 帮助
docker run --rm opencode:1.18.32 --version

# 在你的项目目录里起交互式 TUI
docker run --rm -it -v "$PWD:/workspace" opencode:1.18.32

# 非交互跑一句话
docker run --rm -v "$PWD:/workspace" opencode:1.18.32 run "帮我看看这个仓库"

# 起 headless server
docker run --rm -p 8734:8734 -v "$PWD:/workspace" opencode:1.18.32 serve
```

进入 shell 排查问题：

```bash
docker run --rm -it --entrypoint /usr/bin/env opencode:1.18.32 sh
```

---

## 6. 注意事项

1. **模型调用仍需网络**。容器化解决的是"CLI 在无外网机器上可安装可运行"；
   真正调用 LLM 时容器需要能访问模型端点（`--network` / 代理
   `-e HTTPS_PROXY=...`）。`--version / --help / debug / db / models` 不需要网络。
2. **不要用 `--entrypoint sh` 测 WORKDIR**。覆盖 entrypoint 会丢掉 `WORKDIR`，
   看起来像"工作目录不对"。要保留 ENTRYPOINT 就用
   `--entrypoint /usr/bin/env ... sh -c ...`。
3. **持久化**。容器是无状态的，数据在 `/root/.local/share/opencode` 等路径下，
   需要保留就挂卷：`-v oc-data:/root/.local/share/opencode`。
4. **二进制体积**。单文件 185 MB，`overlayfs` 下镜像磁盘占用约 363 MB（层解压后）。
   磁盘紧张时注意。
5. **升级**。无外网环境下 `opencode upgrade` 会失败；升级要重新构建镜像 + `docker load`，
   并更新 `container-install.sh` 里的 `EXPECTED_INNER_SHA` 与版本号。

---

## 7. 实测记录（在目标服务器上）

| 步骤 | 结果 |
|---|---|
| 镜像 tar 上传 | 90,337,280 字节，sha256 与本地一致 |
| `docker load` | `Loaded image: opencode:1.18.32` |
| 镜像元数据 | Entrypoint/Cmd/WorkingDir 均正确，Layers=2，amd64 |
| 容器内 `--version` | `1.18.32` |
| 容器内二进制 | sha256 一致、185,165,952 字节、mode 755 |
| 挂载运行 | `-v <dir>:/workspace` 正常，默认工作目录 `/workspace` |
| `container-install.sh` | **12 通过, 0 失败（退出码 0）** |

> 排查记录：第一版 `container-install.sh` 报"容器内二进制 sha256 不一致"。
> 根因**不是镜像**，而是脚本里的 `EXPECTED_INNER_SHA` 常量**少抄了一个 `d`**（63 位而非 64 位）。
> 用 `Get-FileHash` 对官方 tarball 解包结果重新取值后修正，比对通过。
> 遇到哈希比对失败时，先打印两侧长度（`${#var}`）——63 vs 64 这种问题一眼可见。
