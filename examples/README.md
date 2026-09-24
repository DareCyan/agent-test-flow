# 示例测试文件

一组可直接用于演示 / 自测的示例文件。**都是纯占位内容，不含真实凭据**。

---

## r1「接入智能体」的三个槽位

三个槽位各对应一个可用文件，都在 `examples/agent/` 下（**含凭据/机器信息的只留本地，不进仓库**）：

| # | 槽位 | 文件 | 进仓库？ |
|---|---|---|---|
| 1 | 智能体安装包（.zip） | `agent/shopping-agent-v2.zip` | 否 |
| 2 | 智能体配置文件 | `agent/shopping-agent.yaml` | 否（含真实 key） |
| 3 | 安装说明文件（install.json） | `agent/shopping-agent-install.json` | 否（含机器地址/私钥路径） |

三个文件是**配套**的：

- 配置文件里的 `name`（`shopping-agent-v2`）与安装包的 `manifest.json` 一致；
- install.json 的 `package.path` 指向**第 1 个 zip**，其 `verify` 步骤断言
  `{workspace}/agent.py` 存在 —— 而该 zip 里确实有 `agent.py`，所以这条断言能通过；
- install.json 的 `agent.version`（2.0.3）与包内 `manifest.json`、`agent.py --version` 一致。

---

## 1. 智能体安装包（r1 左侧槽位 · 智能体二进制文件）

| 文件 | 说明 |
|---|---|
| `agent/shopping-agent-v2.zip` | 示例安装包（3.5 KB：`agent.py` + `requirements.txt` + `manifest.json` + `README.txt` + `legacy_init.sh`）· **本地文件，不进仓库** |
| `agent/_pkg/` | 上面 zip 的**源码目录**（解压后的样子）· **进仓库**（纯占位、无凭据） |
| `agent/build_files.py` | 由 `_pkg/` 重新打包出 zip，并生成含真实 key 的 `shopping-agent.yaml` · **进仓库** |

`agent.py` 是**能真跑**的占位实现（只用标准库）：`python agent.py --info` / `--health`。

上传约定：

- 槽位只接受 **`.zip`**（文件选择框的过滤条件；拖拽不做限制）；
- 后端**不校验、不落盘、不解析**这个 zip —— 只把上传时的**文件名和大小**记进接入结果，
  用于页面展示（`profile.binary / binary_size`，且 `binary_stored: false`）；
- 所以内容是什么都无所谓，换成真实安装包也不会改变行为；
  但**要跑通 step3 的 install 流程**，包里就得有 install.json 断言的东西（见上）。

## 2. 智能体配置文件（r1 右侧槽位 · 智能体配置文件）

| 文件 | 说明 |
|---|---|
| `agent/agent-config.template.yaml` | **模板**：三项必填 + 全部可选字段，逐行带注释 · 进仓库 |
| `agent/agent-config.template.json` | 同一模板的 JSON 版 · 进仓库 |
| `agent/shopping-agent.yaml` | **可用的真实配置**（含真实 key）· **本地文件，不进仓库** |

> **提交约定**：`examples/agent/` 走 `.gitignore` 的 `examples/agent/*` 全排除 + 例外放行。
> 放行的是模板、`_pkg/` 源码和两个脚本；**不放行**的是 zip、`shopping-agent.yaml`、
> `shopping-agent-install.json` —— 它们含真实 key / 机器地址 / 私钥路径。
> 想跑真 LLM，就把 `api / key / model` 填进自己上传的配置，或写进
> `backend/config.yaml`（同样不进仓库）。

必填三项 —— 就是智能体自己的模型接入信息，用于「**模型联通性识别**」实测：

```yaml
api: https://api.openai.com/v1     # 模型服务地址（缺 /v1 自动补）
key: sk-REPLACE-WITH-YOUR-KEY      # API Key
model: gpt-4o-mini                 # 模型名
```

同义键也认：`base_url` / `api_url` / `endpoint`、`api_key` / `apikey`、`model_name` / `model_id`。

**联通性怎么判**（`backend/api_agent.py` 的 `probe_model`）：

1. `GET {api}/models`（最省 token）；200 → 可达，并报出模型数量、命中则标出 `model`；
2. 该端点没有 `/models`（404/405/400）→ 退化为一次 `max_tokens=1` 的最小对话请求；
3. `401/403` → 鉴权失败；连接不上 → 报具体错误。整体超时 2.5s。

示例文件里的 `key` 是占位串，所以第 5 步会显示 **鉴权失败（HTTP 401）—— 这是预期结果**；
换成真实 key 就会变成「可达（GET /models 200，N 个模型，命中 gpt-4o-mini）」。
把 `api` 和 `key` 整行删掉，则显示「未声明 api，跳过实测」。

> 探测**只读**这两个字段，不会拿你的 key 去跑数据集生成 ——
> step1 用的仍是 `backend/config.json`（或 `LLM_*` 环境变量）里那套 LLM 配置，两者互相独立。

### Key 的存放与回显

- 页面、日志、接口响应里**只出现脱敏掩码**（`sk-d****klmn`，见 `profile.api_key_masked`）；
- 配置文件原文会原样保存在本机 `uploads/`（便于复现接入过程），**不会**回显给前端；
- 接口返回的 `profile.declared` 已对 `key / secret / token / password` 类字段做掩码。

### 可选：能力声明

不写任何能力声明时，默认「支持全部 29 个 L2 能力，仅缺 `图像识别`」
（对应 r4 能力矩阵里整列不点亮的那一列）。想改动就用下面任一种写法：

```yaml
missing_capabilities: [图像识别]      # 按 index 的 13 个能力列名
# missing_l2: [1.4]                   # 或按 L2 编号
# l2_capabilities: [1.1, 1.2, 1.3]    # 或正向声明支持哪些 L2
```

L2 编号表见 `GET /api/scene-matrix` 的 `l2_info`（也可在页面 r4 悬停查看能力列）。

## 3. 安装说明文件（r1 第三个槽位 · install.json）

| 文件 | 说明 |
|---|---|
| `agent/install.template.json` | **模板**：全部字段 + 逐条规则注释 · 进仓库 |
| `agent/shopping-agent-install.json` | **可用的真实说明**（指向本机 + 真实私钥路径）· **本地文件，不进仓库** |

这份文件决定 **step3「安装执行」** 怎么装机。要点：

- **只支持密钥认证**：`target.auth.method` 只能是 `key`，且 `private_key` 必填
  （`backend/install_doc.py` 的 `AUTH_METHODS = ("key",)` —— 口令认证在 Windows 上没有
  稳的非交互做法，所以不提供）。想让本机之外的目标机器可用，界面里得先有可用的私钥；
- **默认 dry-run**：`install.execute: false`，只有文件里显式写 `true` 才真执行；
- **可执行命令只有 `install.steps[].run`**，AI 只解读 `desc/notes` 并规范化顺序，不生成命令；
- 命令里可用占位符：`{zip} {zip_name} {zip_sha256} {workspace} {remote_dir} {host} {port} {user} {agent} {version}`，
  写错名字（如 `{wrokspace}`）会在校验阶段直接报错，不会静默生效。

`shopping-agent-install.json` 的 `verify` 步骤断言 `{workspace}/agent.py`，
正好对应第 1 个槽位那个 zip 的内容 —— 三个文件是配套的。

> 它当前的 `target` 是 `127.0.0.1:22`。本机 22 端口没有 sshd（服务 Stopped），
> 所以真连接会失败 —— 这正好用来验证**失败路径的报错是否清楚**；dry-run 不受影响。

## 4. 测试任务简述（r2 输入框）

| 文件 | 说明 |
|---|---|
| `briefs/01-电商购物.md` | 对应矩阵里的「电商购物」场景 |
| `briefs/02-本地生活.md` | 对应「本地生活」场景 |
| `briefs/03-出行服务.md` | 对应「出行服务」场景 |

直接把内容粘进 r2 的文本框再点「提交测试任务」即可。
注意：后端只把 brief 作为 planner 的输入文本，**不会**根据 brief 自动切换场景 ——
场景由前端启动时选的场景决定（默认 `电商购物`，即 `matrix_dimensions.scene`）。

---

## 5. 附：后端 LLM 配置（不属于"示例测试文件"，但常一起用）

想让 step1 跑**真 LLM** 时用它，模板是 `backend/config.example.yaml`（或 `.json`）：

```bat
copy backend\config.example.yaml backend\config.yaml
```

```yaml
api: https://api.openai.com/v1
key: sk-REPLACE-WITH-YOUR-KEY
model: gpt-4o-mini
```

**注意别和上面的智能体配置文件混了** —— 两者完全独立：

| | 智能体配置文件 | 后端 LLM 配置 |
|---|---|---|
| 放哪 | r1 右槽**上传** | 放 `backend/config.yaml`（或 `.yml` / `.json`） |
| 谁在用 | 只用于 r1 的四项**探测**（单轮/多轮/联通性/协议） | 用于 **step1 数据集生成**（planner/generator/verifier） |
| 换了会怎样 | 只影响接入识别那一屏 | 影响 r3 的 query、r5 的通过率/覆盖度评分、r6 的参数取值（从 mock 变真实） |

文件优先级 `config.yaml` > `config.yml` > `config.json`，三个都不建就走内置 mock；
生效的是哪个，看启动横幅的「LLM 配置」一行或 `GET /api/health` 的 `llm_config_source`。
`python tools/verify_config.py` 可以一次验完 json/yaml/BOM/优先级。

---

## 一次完整演示的推荐顺序


1. `start.cmd` 启动，打开 http://127.0.0.1:8787/
2. r1 三个槽位分别上传：
   - 左槽（安装包）`agent/shopping-agent-v2.zip`
   - 右槽（配置文件）`agent/shopping-agent.yaml`
   - 第三槽（安装说明）`agent/shopping-agent-install.json`

   点「接入智能体」。
3. 看 6 行识别日志（第 5 行的联通性结论即来自你上传的配置；用真实 key 的
   `shopping-agent.yaml` 会显示「可达…」，用模板里的占位 key 则是「鉴权失败 401」）
4. 进 step3「安装执行」：先看 dry-run 计划（4 步，`legacy` 标 SKIP），再按需开 `execute`
5. r2 粘贴 `briefs/01-电商购物.md` 的内容，点「提交测试任务」
6. 观察 r3 树 / r4 矩阵 / r5 指标 / r6 参数明细随真实 step1 进度联动，顶部 step1 由「运行中」变「完成」
