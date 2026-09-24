# opencode 容器化交付（三个文件）

在目标机器上用 **三个文件** 把 opencode 拉起来并跑通一次真实模型调用。
已在真实服务器上逐条实测通过（见文末日志）。

## 三个文件

| # | 文件 | 作用 | 体积 |
|---|---|---|---|
| 1 | `dist/opencode-container-1.18.32-linux-amd64.tar.gz` | 安装包：opencode 的容器镜像，`docker load` 即用 | 89.8 MB |
| 2 | `dist/opencode.json` | 配置文件：模型 provider / baseURL / apiKey / 模型名，挂给容器用 | 1.1 KB |
| 3 | `dist/install.json` | 安装说明：按它逐条执行即可完成安装与校验 | 3.5 KB |

> 文件 1 是**镜像包**而不是能联网拉取的镜像：目标机器不需要外网即可导入。
> 但 opencode **调用模型时**需要能访问文件 2 里的 `baseURL`。

文件 2、3 含真实 API Key / 机器信息，**只在本地保留、不进仓库**（`.gitignore` 已覆盖 `dist/`）。
可提交的同构模板是 `opencode.json.template`（key 已替换为占位符）。

## 使用流程

```bash
# 工作机 -> 目标机器
scp dist/opencode-container-1.18.32-linux-amd64.tar.gz  root@<SERVER_IP>:/tmp/
scp dist/opencode.json                                  root@<SERVER_IP>:/tmp/
scp dist/install.json                                   root@<SERVER_IP>:/tmp/

# 目标机器上，按 install.json 执行（也可用本项目 step3 的「安装执行」）
gunzip -c /tmp/opencode-container-1.18.32-linux-amd64.tar.gz > /tmp/oc-image.tar
docker load -i /tmp/oc-image.tar
mkdir -p /etc/opencode
cp /tmp/opencode.json /etc/opencode/opencode.json && chmod 600 /etc/opencode/opencode.json
```

日常使用（配置目录必须挂上，否则容器读不到模型）：

```bash
docker run --rm -v /etc/opencode:/root/.config/opencode opencode:1.18.32 --version
docker run --rm -v /etc/opencode:/root/.config/opencode opencode:1.18.32 models
docker run --rm -v /etc/opencode:/root/.config/opencode opencode:1.18.32 run -m simapp/deepseek-flash "你好"
```

---

## 实测日志（在目标服务器上）

### 方式一：按 `install.json` 逐条执行

| 步骤 | 命令 | 结果 |
|---|---|---|
| `unpack` | `gunzip -c …tar.gz > opencode-image.tar` | exit=0，check=**OK** |
| `load-image` | `docker load -i …` | `Loaded image: opencode:1.18.32`，check=**OK** |
| `install-config` | `cp opencode.json /etc/opencode/ && chmod 600` | exit=0，check=**OK** |
| `smoke` | 容器内 `--version` | `1.18.32`，check=**OK** |
| `verify-config` | 容器内 `models` | 读出 12 个模型（含配置里的 4 个） |
| `run-agent` | 容器内 `run -m simapp/deepseek-flash "只回答两个字：收到"` | **返回「收到」，exit=0** |

### 方式二：干净流程校验（删镜像 -> 从上传文件导入 -> 真实调用）

```
sha256 实际 = f0170c4c54c60638c47f3f8e0e0bcfd36fb4fdcd02e9248ee2e6bec6ba22ec4f
sha256 期望 = f0170c4c54c60638c47f3f8e0e0bcfd36fb4fdcd02e9248ee2e6bec6ba22ec4f
=> 校验通过 ✓
docker load exit=0
--- 真实模型调用 ---
> build · deepseek-flash
收到                (exit=0)

> build · deepseek-flash
2                   (exit=0)
```

---

## 配置里的 provider 情况（实测）

| provider | baseURL | 有 apiKey | 实测可用 |
|---|---|---|---|
| `simapp` | `https://api.deepseek.com` | ✅ | ✅ **可调用**（默认用它） |
| `yunbailian` | `https://danshscope.aliyuncs.com/compatible-mode/v1` | ✅ | ⚠️ 该域名 DNS 解析失败 |
| `bailian` | `https://token-plan.cn-beijing.maas.aliyuncs.com/apps/anthropic/v1` | ❌ | ❌ 会返回 `Error: Not Found` |

因此安装说明里的默认模型选的是 **`simapp/deepseek-flash`** ——
选 provider 时必须挑**有 apiKey** 的，否则跑起来直接报 `Not Found`。

> 这个坑是实测踩出来的：第一版安装说明按字母序取第一个 provider，选中了没有 key 的
> `bailian`，`run-agent` 步骤返回 `Error: Not Found`（exit=1）。已改为按"有 apiKey + 有模型"筛选。

---

## 重新生成

```bash
python tools/opencode-cli/build_deliverables.py
```

它会：
1. 从 `tools/opencode-bundle/dist/` 取镜像 tar，产出 `.tar.gz` 并**校验解压长度 == 原 tar**
2. 从本机 `~/.config/opencode/` 读取真实 provider 配置，写出 `dist/opencode.json`；
   同时写出脱敏模板 `opencode.json.template`
3. 写出 `dist/install.json`（包名/sha256 与第 1 步的实际产物对齐，默认模型选有 key 的）

## 已知限制

1. **`install.json` 的 SSH 安装路径**：项目校验器只支持密钥认证
   （`backend/install_doc.py` 的 `AUTH_METHODS = ("key",)`），所以它不能直接驱动
   密码认证的目标机器。上面的实测是用等价的本地脚本执行的。
2. **镜像名会触发 registry 查询**：本地没有 `opencode:1.18.32` 时，
   `docker run` 会尝试去 registry 拉取并失败（报 `not in the allowlist`）。
   先 `docker load` 即可，这是正常的 docker 行为。
3. **升级**：无外网环境下 `opencode upgrade` 会失败；升级需重新构建镜像 +
   `docker load`。
4. **数据持久化**：容器无状态，需要保留会话/凭据时挂卷
   `-v oc-data:/root/.local/share/opencode`。
