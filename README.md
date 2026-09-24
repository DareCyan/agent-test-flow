# Agent 自动化测试工作台（全新前后端）

**前端** = `index.html` 的结构（原样保留）+ `pipeline.html` 的顶部总流程步骤条；
`index` 整体即 **step1（数据集生成）**，其数据由**真实 step1 后端**驱动。

**后端** = Python 3.12 纯标准库（`http.server` + `threading` + SSE），**零第三方依赖**。

```
┌──────────────────────────────────────────────────────────────────────┐
│ 顶部步骤条 ①数据集生成 待命 ─ ②代码生成APP 待命 ─ ③安装执行 ─ ④判定   │
├──────────────────────────────────────────────────────────────────────┤
│ index 工作台（结构 / 样式 / 渲染算法未改）＝ step1 的全部界面          │
│  r1 智能体接入      r3 任务空间树      ┆ r5 测试质量                  │
│  r2 测试任务输入    r4 评测能力矩阵    ┆ r6 参数覆盖明细              │
└──────────────────────────────────────────────────────────────────────┘
        ▲ 真实数据                        ▲ 真实数据
┌──────────────────────────────────────────────────────────────────────┐
│ /api/agent/*         智能体接入：上传 → 6 项识别 → agent profile      │
│ /api/dataset-ext/*   step1：planner → generator → verifier → evaluator│
│ /api/scene-matrix    场景泛化矩阵（14 场景 / 29 L2 → 13 能力列）      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 一、快速开始

```bat
start.cmd
:: 等价于 python backend/server.py --port 8787
```

浏览器打开 **http://127.0.0.1:8787/** ，然后：

1. 点 **接入智能体**。仓库里 `examples/agent/` **只带模板**（`agent-config.template.yaml` / `.json`），
   按模板填一份配置自己用即可：
   - 左侧「智能体二进制文件」：传一个 `.zip`（只接受 `.zip`，**不校验、不落盘、不解析**）；
   - 右侧「智能体配置文件」：传按模板填好的配置；**里面若声明了 `api / key / model`，
     step1 会直接用它们去调模型**（见下文「接真实 LLM」）。
   两个槽位都不选也行，会用演示回退文件；
2. 点 **提交测试任务**（brief 可从 `examples/briefs/` 复制）；
3. 观察 r1→r6 六个区域随真实 step1 进度联动，顶部步骤条 step1 由「待命」→「运行中」→「完成」。

> 仓库里不含**填好的**示例配置与示例安装包（`examples/agent/shopping-agent.*`、`shopping-agent-v2.zip`）：
> 它们按约定只留在本地（`.gitignore` 已排除，避免把真实 key 提交上去），不影响上面的流程。

> 必须通过 `http://127.0.0.1:8787/` 打开。若直接双击 `index.html`（`file://`），
> 浏览器会因跨源拒绝 `/api/*`，页面会**自动回退到原有演示动画**（不会白屏或报错）。

其他参数：

```bat
python backend/server.py --host 0.0.0.0 --port 9000
```

### 接真实 LLM（可选）

**两条路，任选一条**：

1. **就用你在 r1 上传的智能体配置文件**（最省事）：那份配置里的 `api / key / model`
   本来只用于接入探测，现在 **step1 也会直接拿它调模型** —— 前端传什么就用什么。
   即：不需要新建任何文件，在 r1 上传按模板填好的配置（含 `api / key / model`）→ 提交测试任务，
   顶部徽标会从 `mock` 变成 `LLM <你的模型名>`，四个区域的数据来源标记从 `mock 数据` 变成 `LLM 实测`。
2. **建 `backend/config.yaml`**（想独立于智能体配置时用）：

```bat
copy backend\config.example.yaml backend\config.yaml
:: 只要填 api / key / model 三项
```

```yaml
api: https://api.openai.com/v1     # 也接受 base_url / api_url / endpoint（缺 /v1 自动补）
key: sk-REPLACE-WITH-YOUR-KEY      # 也接受 api_key / apikey（页面与日志只显示掩码）
model: gpt-4o-mini                 # 也接受 model_name / model_id
timeout: 300                       # 可选，单次调用超时秒数，默认 300
fallback_to_mock: true             # 可选，默认 true
```

**优先级：环境变量 `LLM_*` > `backend/config.yaml|yml|json` > r1 上传的智能体配置 > mock。**

- 全局配置文件 **一个都不建也能跑真 LLM**（走第 1 条路）；两边都没有 → 确定性 mock。
- `config.json` 同时兼容扁平写法与旧版 `{"llm": {...}}` 嵌套写法，不用改老配置。
- 文件带 **UTF-8 BOM** 也没问题（Windows 记事本保存的 yaml/json 会带 BOM）。
- 环境变量：`LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` / `LLM_TIMEOUT_S`。
- **到底哪个来源生效**：看本次 run 的 `llm_source` 字段、r1 的运行日志「引擎: LLM … · 来源 …」，
  或 `GET /api/health` 的 `llm_config_source`（它只反映全局配置，不含上传的智能体配置）。
- `fallback_to_mock: true`（默认）：某步调用失败会降级 mock、打 `[降级]` 日志并把整轮跑完，
  四个区域的标记变成 `部分 mock`；设为 `false` 则整轮判失败并写 `steps.__failed__`。
- **超时别调小**：推理模型（qwen3.8-max 等）单次 verifier 调用实测要 **~245s**（含 3 万+ 字推理）。
  默认已从 180s 提到 300s；调小会导致该步反复超时→降级，页面看起来「还是 mock」。同理，
  真 LLM 下单条任务就要几分钟，`任务数` 建议先用 2~4 试水（4 条整轮约 10~15 分钟）。

---

## 二、目录结构

```
agent-test-flow/
├─ PLAN.md                       方案（含数据映射与验收标准）
├─ README.md
├─ start.cmd
├─ backend/
│  ├─ server.py                  HTTP 路由 / 静态托管 / SSE（纯标准库）
│  ├─ api_agent.py               r1：接配置 + 真实探测（单轮/多轮/联通性/协议）+ agent profile
│  ├─ api_dataset.py             step1 接口 + summary 聚合（唯一聚合点）+ 场景预览
│  ├─ step1_runner.py            四步编排：并发 / 重试 3 次 / 逐条进度 / 降级
│  ├─ llm.py                     OpenAI 兼容 chat + 稳健 JSON 解析 + 配置读取（json/yaml）
│  ├─ simplecfg.py               JSON / 扁平 YAML 共用解析（含 BOM 容错）
│  ├─ mockgen.py                 确定性 mock 生成器（无 LLM 时同构产出）
│  ├─ prompts.py                 P/G/V 三段提示词（逐字迁自原项目 dataset_ext_prompts.py）
│  ├─ scene_matrix.py            矩阵解析 + 29 L2 + 29→13 映射 + 档位折算
│  ├─ data/scene_matrix.md       矩阵原文（由 data/scene_matrix.js.src 抽出，保留出处）
│  ├─ config.example.yaml        后端 LLM 配置模板（推荐用这个）
│  └─ config.example.json        同一配置的 JSON 版
├─ frontend/
│  ├─ index.html                 index 原文件 + 步骤条 markup + 真实数据接线
│  ├─ css/pipeline-bar.css       步骤条样式（取自原 css/pipeline.css 的 .mp-step-*）
│  └─ js/api.js                  唯一新增的传输层（fetch + SSE + 探测）
├─ tools/
│  ├─ verify_backend.py          后端验收（91 项断言）
│  ├─ verify_config.py           LLM 配置读取验收（json / yaml / BOM / 优先级，17 项）
│  ├─ e2e_frontend.mjs           前端端到端验收（live 75 项 / demo 39 项）
│  ├─ probe_endpoints.py         外网与本地模型端点可达性诊断
│  ├─ extract_matrix.py          从 scene-matrix.js 抽矩阵（一次性，可重跑）
│  └─ extract_inline.py          抽内联脚本供 node --check 语法校验
├─ examples/                     示例文件（说明见 examples/README.md）
│  ├─ agent/agent-config.template.yaml / .json     配置文件模板（**仓库里只提交这两个**）
│  ├─ agent/shopping-agent.yaml / .json            ← 本地成品示例（不进仓库：可能含真实 key）
│  ├─ agent/shopping-agent-v2.zip                  ← 本地示例安装包（不进仓库）
│  └─ briefs/01-电商购物.md / 02-本地生活.md / 03-出行服务.md
├─ data/runs/*.json              step1 运行记录（不进仓库）
└─ uploads/                      上传物（不进仓库；配置文件存文本，zip 只存文件名/大小）
```

---

## 三、接口一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 服务与 LLM 配置状态（前端据此判断 live/demo） |
| GET | `/api/scene-matrix` | 29 个 L2 能力 + 13 个能力列 + 14 个场景的三层维度 |
| GET | `/api/scene-preview?scene=&agent_id=` | **场景预览**：不跑 run 也能拿到该场景的树 + 矩阵结构（复用同一个聚合函数，覆盖进度为 0） |
| POST | `/api/agent/connect` | 智能体接入：`{binary:{name,size}, config:{name,size}, config_content}` → `{agent_id}`。`binary` 是 `.zip` 安装包（**不校验/不落盘/不解析**），`config_content` 是配置文件原文（解析出 `api / key / model`） |
| GET | `/api/agent/status?id=` | 接入进度：6 条识别日志（三态 `✓` 实测通过 / `!` 实测未通过 / `–` 未实测）+ `profile`（`endpoint` / `model` / `api_key_masked` / `probes{single_turn,multi_turn,connectivity,protocol}` / `call_modes_source`、`protocol_source`、`capabilities_source` / `capabilities` / `missing`） |
| GET | `/api/agent/stream?id=` | 接入过程 SSE（`log` / `ready`） |
| POST | `/api/dataset-ext/runs` | 启动 step1：`{brief, scene, task_count, variant_count, agent_id, matrix_dimensions, execute}` → `{id}` |
| GET | `/api/dataset-ext/run?id=` | 原始契约：`run.steps{planner,generator,verifier,evaluator}`（与原项目一致） |
| GET | `/api/dataset-ext/run/summary?id=` | **前端视图模型**：树 / 矩阵 / 6 项指标 / 参数明细 / query / 进度 / `data_source`（`llm` / `mock` / `mixed` / `preview`） |
| GET | `/api/dataset-ext/stream?id=` | step1 进度 SSE（`snapshot` / `status` / `step` / `progress` / `log`） |
| POST | `/api/dataset-ext/runs/cancel` | 停止某次运行 `{id}` |

`/api/dataset-ext/runs` + `steps{planner,generator,verifier,evaluator}` +
`__failed__` 标记与原项目的 dataset-ext 契约逐字一致，**因此日后可以平滑接回原项目**。

---

## 四、数据映射（index 区域 ← 真实 step1 产出）

| index 区域 | 真实数据来源 |
|---|---|
| r1 智能体接入 | 左槽 `.zip` 安装包（只记文件名/大小，**不校验、不落盘、不解析**）；右槽配置文件**真读真解析**出 `api / key / model`，并用它做 **4 项真实探测**：单轮（1 次最小对话）、多轮（2 轮，验证是否真的记住上一轮说的名字）、联通性（`GET /models`，无此方法则退化为最小对话请求）、协议（分别按 OpenAI 兼容与 Anthropic 风格各试一次）。测不出来的一律标「未实测」，**不打勾**。key 全程只回显掩码 |
| r2 测试任务输入 | brief + **场景（14 个真实场景可选，切换即按真实矩阵预览维度规模）+ 任务数 + 变体数**，三者一起作为 step1 的真实输入（以前这三项都写死在代码里） |
| r3 任务空间树 | 场景泛化矩阵：场景 → 维度类别(5) → 泛化维度(14)，锚点 `P1..P14` 与矩阵行一一对应；行点亮态由「已被生成任务覆盖」驱动；**标题旁有数据来源标记**（`mock 数据` / `部分 mock` / `LLM 实测`），悬停写明哪部分是矩阵真结构、哪部分是本次生成结果 |
| r3 右侧 console | `generator.task_set[].full_instruction` + 欠指定变体，逐条回放（标题显示真实条数）；卡片**默认吃满右侧剩余宽度**、可拖分隔条改窄/改宽（记忆在本机），悬停 query 看全文 |
| r4 评测能力矩阵 | 行 = 14 个泛化维度；列 = 13 个能力（由 29 个 L2 映射而来）；档位 `t1/t2/t3` ← 矩阵符号 `○/△/●`；`missing` 能力列（默认「图像识别」，即无视觉能力）整列不点亮；**同样带数据来源标记** |
| r5 测试质量 | 任务数 / 变体数 / 去重维度 / 矩阵覆盖 `[实际点亮格, 维度数×13]` / 检查通过率 / 覆盖度评分；**标题旁有数据来源标记**（`mock 数据` / `部分 mock` / `LLM 实测`），mock 时明确提示不能当质量结论 |
| r6 参数覆盖明细 | `planner.parameter_space` 每个参数一行；「关联维度」由参数名反查泛化维度；「已用/范围」= 被数据集实际用到的取值数 / 取值空间大小；同样带数据来源标记 |

**29 → 13 能力映射**（`backend/scene_matrix.py` 的 `CAPS13`，唯一主观判断处，改一处即可）：
| index 能力列 | 映射的 L2 |
|---|---|
| 识别·图像识别 / 文字识别 / 页面元素识别 | `1.4` / `1.3` / `1.1+1.2` |
| 规划·任务规划 / 行动规划 / 路径规划 | `4.1+4.3` / `4.4` / `4.2` |
| 行动·点击操作 / 输入操作 / 页面跳转 / 工具调用 | `6.1` / `6.2` / `6.3~6.6` / `6.7+6.8` |
| 判定·状态判定 / 结果判定 / 约束检查 | `2.1+2.3` / `2.2+2.4` / `3.1~3.5 + 5.1~5.4` |

折算规则：一列取所辖 L2 的最大符号值（`-`0 / `○`0.3 / `△`0.6 / `●`1.0）→ 量化成 `t0`(不亮)/`t1`/`t2`/`t3`。

**参数名 → 泛化维度 的语义映射**（`backend/scene_matrix.py` 的 `PARAM_DIM_KEYWORDS` + `match_dim()`，同样是一处可改的启发式）：

真 LLM 的 planner 会自己给参数命名（`product_brand` / `sort_method` / `invoice_requirement`…），
mock 用的是另一套（`brand` / `sort_by` / `invoice_type`），所以这里用
「英文关键词 → 维度名里的中文词」配对打分：**先按整词命中**（避免 `spec` 误命中 `special`），
整词都不中才退回子串匹配（`specification` 能对上 `spec`）；取配对数最多的维度，一个都不中返回 `""`
（r6 的「关联维度」列显示 `—`，不硬凑一个错维度）。实测对 `qwen3.8-max` 产出的 15 个参数名
命中 14 个（唯一未命中的 `purchase_purpose` 确实是矩阵里没有的额外参数），
`delivery_address`/`delivery_method` 也能正确分开落到「配送地址」/「配送方式」。

**覆盖维度的三条来源**（真 LLM 与 mock 的 task 形状不同，`api_dataset.summarise()` 里统一折算）：

1. mock 的 generator 直接产出 `covered_dimensions`；
2. 真 LLM **不产出**该字段（原项目的提示词里根本没有它），但每条任务都带 `parameters`
   （键 = planner 的参数名）→ 用上面的语义映射折算成覆盖维度；
3. 兜底：任务文本里直接出现维度名。

> 这就是「真 LLM 跑完 r3 树全不亮、r4 矩阵 0/182、覆盖度评分 0.000」的根因，已修复。

---

## 五、验收

```bat
:: 后端（服务需已启动）
python tools\verify_backend.py                     :: → 91 passed, 0 failed
python tools\verify_config.py                      :: → 17 passed, 0 failed（json/yaml/BOM/优先级）

:: 前端端到端（需 jsdom，见下）
set ATF_JSDOM=%TEMP%\atf-jsdom\node_modules\jsdom\lib\api.js
node tools\e2e_frontend.mjs --mode live            :: → 75 passed, 0 failed
node tools\e2e_frontend.mjs --mode demo            :: → 39 passed, 0 failed
```

前端 E2E 覆盖：index 结构与七区域完整、步骤条 4 步且 2/3/4 恒「待命」、
r1 接入 6 条日志（三态标记）+ Agent Ready、完整跑通到 `done`、树 20 行 / 矩阵 182 格 /
点亮格 = 后端 `covered`、r5 六项与后端一致、r6 行数 = 参数空间、
query 条数 = 任务+变体、`missing` 列全行不点亮、
**step1 的 LLM 来源 = 前端上传的智能体配置（`agent-config`），端点不可达时降级为 `llm+mock`、
四个区域标 `部分 mock`、日志有 `[降级]`、顶部徽标同步变成 `部分 mock`**、
r3/r4 tooltip 写明「真结构 vs 本次生成」、**生成台默认吃满（CSS `calc` 常量与 JS 常量一致，
不再有写死宽度）、拖拽夹到 140–900px 且写进 localStorage、双击回到吃满（清内联宽度 + 清记忆）**、
幽灵文字来自真实事件（不含演示装饰文案）、**换场景重跑后矩阵格数随该场景维度数变化**、
无未捕获 JS 错误。

> E2E 里 r1 上传的是一份**端点必然不可达**的配置（`http://127.0.0.1:9/v1`）：
> 既能验证「前端传什么就用什么」这条新链路，又让降级路径确定、快速、**不产生任何真实外呼**。

`demo` 模式让 `/api/*` 全部失败，验证**后端不可用时自动回退演示动画**且无报错。

jsdom 只在开发时用于自动化验收，**不是运行依赖**：

```bat
mkdir %TEMP%\atf-jsdom && cd %TEMP%\atf-jsdom
npm install jsdom --no-save --cache %TEMP%\atf-npmcache
```

> 本机沙箱内 Chrome/Edge 的调试端口被禁（`--remote-debugging-port` 无法监听），
> 因此 E2E 用 jsdom + fetch/EventSource 垫片驱动**同一份前端代码**；
> 垫片会真连后端的 `/api/dataset-ext/stream`，顺带验证 SSE 事件格式。
> 真实浏览器观感请自行打开 http://127.0.0.1:8787/ 确认。

---

## 六、实现说明与已知边界

**数据来源可信度（当前状态，逐项）**

| 部分 | 现在是什么 |
|---|---|
| HTTP / SSE / 并发编排 / 聚合计算 / 落盘 | ✅ 真 |
| 场景矩阵（14 场景 × 29 L2 → 13 能力列） | ✅ 真（矩阵值来自原项目；**29→13 的映射表是按语义编的**，见 §4） |
| 配置文件解析（`api / key / model`） | ✅ 真读真解析 |
| 单轮 / 多轮 / 联通性 / 协议 四项识别 | ✅ **真探测**；测不出来时显示「未实测 –」并写明原因，不再无条件打勾 |
| 「智能体接入中」这一行 | ⛔ 脚本化文字（安装包按约定不校验、不落盘） |
| `.zip` 安装包内容 | ⛔ 从不离开浏览器（只发文件名/大小）——**有意如此** |
| 场景 / 任务数 / 变体数 | ✅ 真实输入并驱动后端（以前写死在代码里） |
| step1 的 `task_set` / 变体 / 参数取值 | 🔵/✅ **取决于 LLM 来源**：没配也没在 r1 上传带 `api/key/model` 的配置 → mock（编排与算法是真的，**输入是规则生成的**）；配了或用上传的配置 → 就是真 LLM 产出（`engine=llm`，标记 `LLM 实测`） |
| r5 的检查通过率 / 覆盖度评分 | 🔵/✅ 真公式；输入随上面的来源变。mock 时标题旁标 `mock 数据`，**别当结论** |
| 覆盖维度（r3 点亮 / r4 点亮格） | ✅ 真折算：mock 用 generator 的 `covered_dimensions`，真 LLM 用 task 的 `parameters` + 语义映射（见 §4），两者都来自本次生成结果 |
| 评分标度（0~1 vs 3~5） | ✅ 已按实际值域自动识别并折算，真 LLM 的 `0.95` 不会被当成「未覆盖」（mock 行为不变） |
| r1 的单轮/多轮探测 | 🟡 对推理模型可能报「接口 200 但内容为空」（模型只出 `reasoning_content`）→ 显示 ✗ + 原因，属**如实报告**而非误判 |
| r3 树 / r4 矩阵 | ✅ 结构与档位是真的（场景泛化矩阵 + 29→13 映射）；🔵 但「覆盖到哪些维度」来自本次生成结果，无 LLM 时是 mock → r3/r4 标题旁同样标 `mock 数据`，悬停可看「哪部分真、哪部分本次生成」。**注意：矩阵同一场景每次跑完长得一样，变化的是「亮哪几行」——档位是矩阵固有的考察强度，不是实测结果** |
| 幽灵文字 | ✅ 真实事件（`任务 2/4` / `校验 3/4` / `已覆盖 商品品类`） |
| 能力矩阵里"不点亮的那一列" | 🟡 取自配置文件声明（默认"无视觉能力"）；真要做成**实测**需要真机跑智能体 |
| 步骤条 2/3/4 | ⛔ 占位（需要 OHOS SDK + 真机，本次范围外） |
| 后端不通时的整页演示 | ⛔ 全假，但**显式标注**（徽标显示「演示模式」+ 琥珀点） |

配上可用 LLM（`backend/config.yaml` 或 **r1 上传的智能体配置**）后，上面 🔵 的行会变成 ✅
（`data_source` 从 `mock` 变 `llm`、标记变 `LLM 实测`）；若该步调用失败，则是 `llm+mock` / `部分 mock`。

**为真实数据做的必要改动（其余渲染算法与 CSS 未动）**

- **step1 的 LLM 来源接上「前端上传的智能体配置」**：`api_agent.llm_declared(agent_id)` 把 r1
  上传的配置文件读回来解析 `api/key/model`，作为 `llm.load_config(override=…)` 的兜底来源
  （优先级：环境变量 > `backend/config.yaml` > 上传的智能体配置 > mock）。
  明文 key 只在这个函数里交给 LLM 层，接口响应/日志/页面一律走掩码。
- **默认超时 180s → 300s**：实测推理模型单次 verifier 调用要 ~245s，180s 会让该步反复超时→降级。
- **覆盖维度折算**（真 LLM 没有 `covered_dimensions`）：用 task 的 `parameters` 键 +
  `scene_matrix.match_dim()` 语义映射折算，见 §4。
- **评分标度自适应**：`compute_evaluator_metrics()` 按实际值域判断 0~1 / 3~5 并归一化后再判阈值，
  修掉「真 LLM 的 0.95 被 `>= 3.0` 判成未覆盖 → 覆盖度永远 0.000」；mock 的计算结果一字不变。
- 树的第 4 层（取值）**仅在放得下时渲染**：真实矩阵是 14 个泛化维度、连取值共 60+ 行，
  会超出 r3 面板高度，故默认渲染「场景 → 维度类别 → 泛化维度」三层（20 行）；
  取值本身在 r6 参数覆盖明细里已完整呈现。
- 矩阵的 `grid-template-rows` 改为按数据动态生成（CSS 里写死的 7 行装不下 14 个维度）。
- `r3-status` / `r4-status` 覆盖文案改为按真实进度计算（原来硬编码「92%」/「全量覆盖」）。
- 生成台（r3 右侧「已泛化query」）原来写死 120px，长 query 只剩开头几个字。现在**默认吃满右侧剩余宽度**：
  `width:min(calc(100% - 171px),900px)`（171 = 树最小宽度 160 + 分隔条 11），所以窗口越宽生成台越宽，
  且**不写死任何像素默认值**。想改窄就拖分隔条 `.r3-split`：拖拽写内联 px 宽度并记忆到
  `localStorage['atf.genConsoleWidth.v2']`（键带版本号，避免旧默认值残留）；
  双击分隔条清掉内联宽度与记忆、回到「吃满」。未手动拖过时宽度由 CSS 自适应（窗口缩放自动跟随），
  手动拖过后只做边界夹回（下界 140px / 上限 900px，上限与 CSS 的 `min()` 是同一常量，E2E 有防漂移断言）。
  query 行同时带上 `title`，悬停可看全文。
- `#r3-src` / `#r4-src` 这两个数据来源标记位**以前是空的**（`applySourceTags()` 只写 r5/r6），
  看的人无从判断 r3/r4 可信度；现在四处统一标注 `mock 数据` / `部分 mock` / `LLM 实测`，
  且 r3/r4 的 tooltip 分别写明哪部分是矩阵真结构、哪部分是本次生成结果；
  顶部徽标也改成**以本次 run 的引擎为准**（否则用了上传配置的 LLM，健康检查仍报 `mock`）。

**口径变化（与演示数字的差异，属预期）**

- r4 分母统一为 **182 = 14 维度 × 13 能力**（演示态 r4 用的 7 维度玩具集分母是 91，
  而同一页的 r5 又写 59/182，本身就自相矛盾）。
- `covered` 的定义是「数据集**实际**覆盖到的格数」：执行期从 0 递增，
  最终 ≤ `reachable`（本例 127，即扣掉无视觉能力那一列后的可达上界）≤ 182。
- mock 模式下 `task_count=4` 会覆盖 12 个维度 → 约 `111/182`；`task_count=2` → 约 `56/182`。

**降级与失败语义**

- 未配置 LLM（环境变量/配置文件/上传的智能体配置都没有 `api`+`model`）→ `engine=mock`，跑同构的确定性 mock。
- 配置了 LLM 但调用失败（超时/连接拒绝/返回结构异常，各重试 3 次）→ 该步降级为 mock，
  日志里给出显式 `[降级]` warning，`engine=llm+mock`，整轮**仍能跑完**（可观测、不静默）。
- `llm.fallback_to_mock=false` 时改为硬失败：`status=failed` + `steps.__failed__='planner'|'generator'|'verifier'`。

**已知边界**

- **真 LLM 很慢**：推理模型（qwen3.8-max）单次调用实测 200~250s（planner 6.9K 字提示词、
  verifier 6.6K 字提示词 + 3 万+ 字推理）。`task_count=4` 整轮约 **10~15 分钟**
  （planner 1 次 → generator 4 并发 → verifier 4 并发）。想快点先把任务数设成 2；
  页面不会卡死，期间有 `任务 x/y` / `校验 x/y` 的幽灵文字与逐行点亮。
- **单轮/多轮探测**对推理模型可能返回「接口 200 但内容为空」（只出 `reasoning_content`）→
  该行显示 ✗ 并写明原因。这是**如实报告**（README 的约定是测不出来不许打勾），不是链路坏了；
  step1 的实际调用不受影响（长提示词下模型会正常给出 `content`）。
- **`start.cmd` 必须保持 CRLF 换行且只用 ASCII 文案**：cmd.exe 解析 LF-only 的 `.cmd`
  会吃掉行首单词（表现为 `'ython' is not recognized`、`'[ERROR]' is not recognized`，
  并把 `if (...) else (...)` 的分支文案打乱）。因此该文件用 `goto` 分支而非括号块，
  中文提示交给 Python（`server.py` 的启动横幅仍是中文）。
  修改后请确认：`CRLF=41, bare-LF=0, non-ASCII bytes=0`。
- 重复启动会先探活端口再给友好提示并退出码 2（Windows 的 `SO_REUSEADDR` 允许第二个进程
  重复 bind 同一端口并静默生效，只靠 bind 报错拦不住），不会出现「两个实例都在跑」。
- r1 上传：**左槽只接受 `.zip`**（拖拽不限），后端**不校验、不落盘、不解析**——只把文件名/大小记进
  `profile.binary / binary_size`（`binary_stored: false`）；**右槽配置文件真读真解析**，
  取其 `api / key / model` 做联通性实测。key 在页面、日志、接口响应里都只有掩码
  （`profile.api_key_masked`，`profile.declared` 已对 key/secret/token/password 类字段掩码），
  完整配置原文仍原样保存在本机 `uploads/` 以便复现接入过程。
- 智能体配置里的 `api/key/model` **只用于联通性探测**，不会拿去跑数据集生成；
  step1 的 LLM 仍来自 `backend/config.json`（或 `LLM_*` 环境变量），两者互相独立。
- 步骤条 2/3/4 本次**只有占位**（恒「待命」），无页面、无接口。
- 并发上限 `DATASET_EXT_CONCURRENCY`（默认 4）；LLM 单次超时默认 180s。
- 运行记录落在 `data/runs/*.json`，为最简 JSON 存储（无数据库）。
