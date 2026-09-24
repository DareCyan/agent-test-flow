# opencode 容器化交付（三个文件）

在目标机器上用 **三个文件** 把 opencode 拉起来并跑通一次真实模型调用。
已在真实服务器上逐条实测通过（见文末日志）。

## 三个文件

| # | 文件 | 作用 | 体积 |
|---|---|---|---|
| 1 | `dist/opencode-container-1.18.32-linux-amd64.zip` | 安装包：**真 zip**（拉链格式），内含镜像 tar，`unzip` 后 `docker load` | 90.3 MB |
| 2 | `dist/opencode.json` | 配置文件：**一份文件同时服务两个消费者**（见下） | 1.4 KB |
| 3 | `dist/install.json` | 安装说明：按它逐条执行即可完成安装与校验 | 3.4 KB |

### 文件 2 为什么是"双层"结构

它要同时被两个东西读，两边的格式要求**互相冲突**：

| 消费者 | 读什么 | 格式要求 |
|---|---|---|
| 本项目 r1「智能体配置文件」槽位 | `api` / `key` / `model` | **必须顶层扁平键**（`backend/simplecfg.py` 明确「不支持嵌套层级」） |
| opencode 容器 | `provider.<name>.{npm,options,models}` | **必须嵌套**，`provider` 是对象 |

所以同一份 JSON 里**顶层放扁平接入层，同时带 provider 层**，各取所需：

```jsonc
{
  "api":   "https://api.deepseek.com",   // ← 本项目 r1 读这里
  "key":   "sk-…",
  "model": "deepseek-flash",
  "opencode_provider": "simapp",          // 给人看 opencode 该用哪个
  "opencode_model":    "simapp/deepseek-flash",

  "provider": {                           // ← opencode 容器读这里
    "simapp": { "npm": "@ai-sdk/openai-compatible",
                "options": { "baseURL": "https://api.deepseek.com", "apiKey": "sk-…" },
                "models": { "deepseek-flash": { "name": "deepseek-flash" } } }
  }
}
```

> 只放 `provider` 那一层（我第一版的做法）会导致 r1 的
> 「单轮/多轮/联通性/协议」全部显示「未声明 api/model，无法实测」——
> 因为本项目只认扁平键。
>
> 顺带：这份配置还会被 `llm.load_config()` 当作**兜底**，让 r1 的
> 「AI 解读」拿到 LLM 配置（`backend/config.yaml` 故意没写 api/key/model，
> 走的就是 `config.yaml + agent-config(前端上传的智能体配置)` 这条链）。

### 另外两个文件

> **文件 1 为什么是 .zip**：前端二进制槽位的 `accept` 过滤是 `.zip`，且后端的安装包命名也补 `.zip`。
> zip 里放的是**未压缩的镜像 tar**（zip 用 store 模式）——镜像层本身已是 gzip，
> 再压缩几乎没有收益（省 0.6 MB），所以不去折腾压缩率。
> `docker load` 其实直接支持 `.tar.gz`，做成 zip 只是为了配合前端过滤。
>
> 文件 1 是**镜像包**而不是能联网拉取的镜像：目标机器不需要外网即可导入。
> 但 opencode **调用模型时**需要能访问文件 2 里的 `baseURL`。

文件 2、3 含真实 API Key / 机器信息，**只在本地保留、不进仓库**（`.gitignore` 已覆盖 `dist/`）。
可提交的同构模板是 `opencode.json.template`（key 已替换为占位符）。

## 在前端上传（r1 三个槽位）

| 槽位 | label（`accept`） | 上传文件 |
|---|---|---|
| 左 | 智能体二进制文件（`.zip`） | `opencode-container-1.18.32-linux-amd64.zip` |
| 右 | 智能体配置文件（`.yaml,.yml,.json`） | `opencode.json` |
| 三 | 安装说明文件（`.json`，可选） | `install.json` |

> 后端对左槽的 zip **不校验、不落盘、不解析**，只记文件名与大小
> （`profile.binary / binary_size`，`binary_stored: false`），所以 90 MB 也只是记个大小。
> 装机时"补传包"的 64 MB 上限（`api_install.py` 的 `MAX_PACKAGE_BYTES`）
> 只作用于 `package.source = "upload"`；本说明用的是 `source = "local"`，不受该上限影响。

## 使用流程

```bash
# 工作机 -> 目标机器
scp dist/opencode-container-1.18.32-linux-amd64.zip  root@<SERVER_IP>:/tmp/
scp dist/opencode.json                               root@<SERVER_IP>:/tmp/
scp dist/install.json                                root@<SERVER_IP>:/tmp/

# 目标机器上，按 install.json 执行（也可用本项目 step3 的「安装执行」）
unzip -o /tmp/opencode-container-1.18.32-linux-amd64.zip -d /tmp/opencode-install
docker load -i /tmp/opencode-install/opencode-image.tar
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
| `unpack` | `unzip -o …zip -d /tmp/opencode-install` | 解出 `opencode-image.tar`，check=**OK** |
| `load-image` | `docker load -i …opencode-image.tar` | `Loaded image: opencode:1.18.32`，check=**OK** |
| `install-config` | `cp opencode.json /etc/opencode/ && chmod 600` | exit=0，check=**OK** |
| `smoke` | 容器内 `--version` | `1.18.32`，check=**OK** |
| `verify-config` | 容器内 `models` | 读出 12 个模型（含配置里的 4 个） |
| `run-agent` | 容器内 `run -m simapp/deepseek-flash "只回答两个字：收到"` | **返回「收到」，exit=0** |

### 方式二：干净流程校验（删镜像 -> 从上传的 zip 导入 -> 真实调用）

```
文件1 校验
  sha256 实际 = 484967a7fa3efa1976fb545adfae628ff562bca31aca4d746d14ef158230e163
  sha256 期望 = 484967a7fa3efa1976fb545adfae628ff562bca31aca4d746d14ef158230e163
  => 通过 ✓
现存 opencode 镜像: 0        （先删干净，确保确实从文件导入）
步骤 unpack       : extracting opencode-image.tar   check=OK
步骤 load-image   : Loaded image: opencode:1.18.32  check=OK
smoke             : 1.18.32
verify-config     : bailian/GLM5 … simapp/deepseek-flash …
--- run-agent（真实模型调用） ---
> build · deepseek-flash
收到                              (exit=0)
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
1. 从 `tools/opencode-bundle/dist/` 取镜像 tar，打成真 zip（内含 `opencode-image.tar`），
   并**校验 zip 内 tar 读回长度 == 原 tar**
2. 从本机 `~/.config/opencode/` 读取真实 provider 配置，写出 `dist/opencode.json`；
   同时写出脱敏模板 `opencode.json.template`
3. 写出 `dist/install.json`（包名/sha256 与第 1 步的实际产物对齐，默认模型选有 apiKey 的）

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
