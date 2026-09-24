# Agent 测试工作台（前后端新建）· 实施方案

> 目标：在空项目 `C:\Users\dcy\Documents\agent-test-flow` 下搭一套新的前后端。
> 前端 = `index.html` 的结构（原样不动）+ `pipeline.html` 的顶部步骤条，**index 整体即 step1**；
> step1 的数据由原 pipeline 的 step1 后端（数据集生成：计划→生成→检查→评估）真实驱动。
> 后端要最简：Python 3.12 纯标准库（http.server + threading + SSE），零第三方依赖。

---

## 一、现状对照（已完成阅读与溯源）

### 1.1 前端 A：`index.html`（Agent 自动化测试工作台，825 行，单文件）

| 区域 | 内容 | 现状数据来源 |
|---|---|---|
| r7 | 顶部 44px 预留条（`<header class="r7">`） | 空 —— **步骤条就落在这里** |
| r1 | 智能体接入：二进制 + 配置文件上传、接入按钮、接入 console | 纯演示（6 行日志定时器） |
| r2 | 测试任务输入：自然语言 brief + 提交 | 纯演示（`DEMO.task.text`） |
| r3 | 任务空间树：场景→维度类别→维度→属性 + 右侧「已泛化query」console | 纯演示（`DEMO.tree.dims` 7 个维度） |
| r4 | 评测能力矩阵：维度 × 13 能力（识别/规划/行动/判定），三档点亮 | 纯演示（`DEMO.caps` + `tier` 规则） |
| r5 | 测试质量 6 项指标（任务数/变体/去重维度/矩阵覆盖/通过率/覆盖度） | 纯演示，且**延迟结算** |
| r6 | 参数覆盖明细表（参数/关联维度/取值分布/已用/范围/覆盖率） | 纯演示（`DEMO.r6.rows`） |

状态机：`idle → connecting → ready → modeling → executing → evaluating → done`（`body[data-phase]` 驱动阶段显隐）。
已有 `window.__demo` 调试钩子，可直接做自动化验收。

### 1.2 前端 B：`pipeline.html`（总流程，1064 行）

- DOM 顶部即步骤条：`.mp-step-bar > .mp-steps > 4×.mp-step[data-step]`（数据集生成 / 代码生成APP / 安装执行 / 判定），每步含 `.mp-step-icon > .mp-step-num` 与 `.mp-step-text > .mp-step-name + .mp-step-status`；步骤间 `.mp-step-connector`。
- 状态类：`is-active / is-completed / is-error / is-selected`；样式在 `dev/frontend/css/pipeline.css` 第 14–123 行。
- step→workflow 映射：`{1:'dataset-ext', 2:'code-sim', 3:'img-sim', 4:null}`。
- 驱动方式两种：① 前端直驱 `wfDatasetExtStart()`；② 后端 `PipelineController` 驱动（`POST /api/pipeline/start` + SSE `/api/pipeline/stream`）。

### 1.3 原 step1 后端（要"结合"的就是这一块）

链路：`POST /api/dataset-ext/runs {brief, task_count, variant_count, execute:true}` → 后台线程 `_dataset_ext_execute_worker`（`dev/scripts/console/device.py:1289`）→ 写 `dataset_ext_runs.steps` → 前端轮询 `GET /api/dataset-ext/run?id=N`。

四步实质：

| 步 | 类型 | 输入 | 产出（写入 `steps.<id>`） |
|---|---|---|---|
| planner | LLM ×1（重试 3 次） | brief + 场景维度 | `domain_scenarios / parameter_space / constraint_templates / underspecification_plan / combination_rules` |
| generator | LLM ×N 并行 | planner 产物 | `{task_set:[{task_id, domain, scenario, full_instruction, constraints, underspecified_variants[], covered_dimensions[]}]}` |
| verifier | LLM ×N 并行 | 每条任务 | `{verification_results:[{task_id, pass, scores{clarity,completeness,consistency,feasibility,constraint_coverage}, ...}], overall_pass}` |
| evaluator | **程序化，无 LLM** | 前序产物 | `{total_tasks, total_variants, ...}`；`PipelineController._compute_evaluator_metrics` 另算 5 项指标（信息熵/宽度/均衡度/深度/覆盖度 + covered/total capabilities） |

提示词原文：`dev/scripts/console/dataset_ext_prompts.py`（`MD_P_AGENT_PROMPT` / `MD_G_AGENT_PROMPT` / `MD_V_AGENT_PROMPT`，可逐字搬迁）。
失败约定：`steps.__failed__ = 'planner'|'generator'|'verifier'|'unknown'`，`status='failed'`。

相关文件位置：`device.py`（_dataset_ext_execute_worker）、`pipeline_controller.py:459`（_run_step1）、`pipeline_controller.py:947`（_sync_step1_detail）、`server.py:3313`（_handle_dataset_ext_create）。

### 1.4 关键发现：真实维度矩阵就在仓库里，且与 index 的数字自洽

`dev/frontend/datasetext/scene-matrix.js` 的 `SCENE_MATRIX_MD` 是「场景 → 维度类别 → 泛化维度 × L2 能力(1.1~6.8)」矩阵原文，取值符号 `-/○/△/●`。
`dev/frontend/scene-gen.js` 定义 `L2_INFO`（29 个 L2 能力，分 感知/反思/推理/规划/记忆/执行 6 组）与 `SYM = {'-':0,'○':0.3,'△':0.6,'●':1.0}`，并把选中的三层维度结构 (`wf._matrixDimensions`) 传给计划步。

**电商购物场景实际是 14 个泛化维度**（商品属性 5 + 筛选条件 3 + 交易属性 4 + 售后属性 1 + 平台属性 1）。
而 index 的演示数字 `r5.矩阵覆盖 = 59/182`：**182 = 14 × 13** —— 正好等于「真实 14 维度 × index 13 能力列」。
说明 index 的能力矩阵本就是按真实矩阵设计的，13 列 × 14 维度口径天然吻合（r4 里 0/91 只是演示当天用的 7 维度玩具集，7×13=91）。

结论：**r3 树 / r4 矩阵 / r5 指标 / r6 参数明细都能由真实 step1 数据算出来，不需要造数据。**

---

## 二、结合方案总览

```
┌────────────────────────────────────────────────────────────────┐
│ 顶部步骤条（来自 pipeline.html）                                │
│  ①数据集生成(运行中) ── ②代码生成APP(待命) ── ③安装执行 ── ④判定 │
├────────────────────────────────────────────────────────────────┤
│ index 工作台（结构、样式、渲染函数全部不动）＝ step1 的全部界面  │
│  r1 智能体接入      r3 任务空间树      ┆ r5 测试质量            │
│  r2 测试任务输入    r4 评测能力矩阵    ┆ r6 参数覆盖明细        │
└────────────────────────────────────────────────────────────────┘
        ↑ 真实数据                     ↑ 真实数据
┌────────────────────────────────────────────────────────────────┐
│ 新后端（Python 纯标准库，最简）                                  │
│  /api/agent/*        智能体接入：上传 → 6 项识别 → agent profile │
│  /api/dataset-ext/*  step1 四步：planner→generator→verifier→eval │
│  /api/scene-matrix   真实矩阵原文 + 29 L2 + 29→13 映射           │
└────────────────────────────────────────────────────────────────┘
```

**数据映射表（index 区域 ← 真实 step1 产出）**

| index 区域 | 真实数据来源 |
|---|---|
| r1 智能体接入 | 新接口 `/api/agent/connect`（上传 bin/config → 识别单轮/多轮调用方式、配置文件、模型联通性、协议）→ 产出 `agent.capabilities`（支持的 L2 集合） |
| r2 测试任务输入 | brief 直接作为 planner 输入 |
| r3 任务空间树 | `SCENE_MATRIX_MD` 解析出的 场景→维度类别→泛化维度（选中场景），行点亮态由 `progress.substeps/generator_completed/covered_dimensions` 驱动 |
| r3 右侧「已泛化query」 | `generator.task_set[].full_instruction` + `underspecified_variants` 逐条实时滚动 |
| r4 评测能力矩阵 | 行 = 真实泛化维度（14），列 = index 的 13 个能力（由 29 L2 映射而来），档位 `t1/t2/t3` ← 矩阵符号 `○/△/●`；不点亮的列 ← agent 不支持的 L2（如无视觉能力） |
| r5 测试质量 6 项 | `任务数=len(task_set)`、`变体=Σvariants`、`去重维度=覆盖到的泛化维度数`、`矩阵覆盖=[已点亮格, 维度数×13]`、`检查通过率=verifier pass 占比`、`覆盖度评分=evaluator.coverage_score` |
| r6 参数覆盖明细 | 行 = `planner.parameter_space` 的每个参数；「关联维度」由参数名↔维度映射，「取值分布」= `range/description`，「已用/范围」= 生成中被该参数覆盖的任务数 / 取值空间大小，「覆盖率」= 二者之比 |

---

## 三、目标目录结构（新建，全部在空项目内）

```
agent-test-flow/
├─ PLAN.md                     # 本文件
├─ README.md                   # 启动方式 / 接口一览
├─ start.cmd                   # python backend/server.py --port 8787
├─ backend/
│  ├─ server.py                # HTTP 路由 + 静态托管 + SSE 订阅（~300 行）
│  ├─ api_agent.py             # r1：上传落盘 + 6 项识别 + agent profile
│  ├─ api_dataset.py           # step1 接口：create / get / summary / stream / cancel
│  ├─ step1_runner.py          # 四步编排：并发、重试 3 次、逐条进度、失败标记
│  ├─ llm.py                   # OpenAI 兼容 chat/completions + 稳健 JSON 解析 + mock 降级
│  ├─ prompts.py               # P/G/V 三段提示词（逐字迁自 dataset_ext_prompts.py）
│  ├─ scene_matrix.py          # SCENE_MATRIX_MD + L2_INFO(29) + 29→13 映射 + markdown 解析
│  ├─ store.py                 # run 记录落盘 JSON（最简，不引 SQLite）
│  └─ config.example.json      # llm.base_url / api_key / model / timeout
├─ frontend/
│  ├─ index.html               # index.html 原文件 + 步骤条 + 接线（唯一被改的文件）
│  └─ js/api.js                # 唯一新增：传输层 + 演示回退
├─ data/runs/*.json            # 运行记录
└─ uploads/                    # 上传的二进制 / 配置文件
```

---

## 四、后端接口契约（最简但完整）

### 4.1 智能体接入

```
POST /api/agent/connect        { binary:{name,size}, config:{name,size} }
  → { ok:true, agent_id:"agent-1" }

GET  /api/agent/status?id=agent-1
  → { ok:true, phase:"connecting|ready",
      logs:[{ts:"00:01.20", text:"单轮对话调用方式识别中…", ok:true}, ...],   # 6 行
      profile:{ name:"shopping-agent-v2", call_modes:["单轮对话","多轮对话"],
                protocol:"openai-compatible", model:"...",
                capabilities:["1.1","1.2","1.3","2.1",...],   # 支持
                missing:["1.4"] } }                            # 不支持（→ r4 不点亮的列）
```

### 4.2 scene matrix

```
GET /api/scene-matrix
  → { ok:true,
      l2_info:[{c:"1.1", l1:"感知", l2:"视觉感知-元素识别", d:"识别页面元素位置与存在性"}, ... 29 项],
      caps13:[{group:"识别", cap:"图像识别", l2:["1.4"]}, ... 13 项],
      scenes:[{name:"电商购物", categories:[{name:"商品属性",
                dims:[{name:"商品品类", scores:{"1.1":0.6,"1.2":0.3,...}}]}]}] }
```

### 4.3 step1 数据集生成（对齐原契约，便于日后接回原项目）

```
POST /api/dataset-ext/runs
  { brief, scene:"电商购物", task_count:4, variant_count:2,
    matrix_dimensions:{scene, categories:[{name, dims:[names]}]},
    agent_id:"agent-1", execute:true }
  → { ok:true, id:7 }

GET  /api/dataset-ext/run?id=7          # 原始契约，逐字对齐老项目
  → { ok:true, run:{ id, status:"running|completed|failed",
        steps:{ planner:{...}, generator:{task_set:[...]},
                verifier:{verification_results:[...], overall_pass},
                evaluator:{...}, __failed__:"verifier"? } } }

GET  /api/dataset-ext/run/summary?id=7  # 新增：前端视图模型（聚合只在后端做一次）
  → { ok:true, status, phase,
      progress:{ substeps:{planner,generator,verifier,evaluator},
                 generator_completed:2, generator_total:4,
                 verifier_completed:0, verifier_total:4 },
      tree:{ scene, categories:[{name, dims:[{name, status:"idle|run|done"}]}] },
      matrix:{ caps13:[...13], rows:[{dim_id:"P1", dim:"商品品类", tiers:[13 档]}],
               covered:59, total:182, missing:["图像识别"] },
      metrics:[{key:"matrix", label:"矩阵覆盖", type:"frac", value:[59,182], hl:true}, ...6 项],
      params:[{param:"platform", dim:"平台属性", values:"淘宝 · 京东 · …",
               used:12, range:30, coverage:40}, ...],
      queries:[{n:1, text:"请在淘宝买羽绒服"}, ...] }

GET  /api/dataset-ext/stream?id=7       # SSE: event: status | step | log
```

### 4.4 step1 四步编排（`step1_runner.py`）

1. **planner**：LLM ×1（重试 3 次）→ `domain_scenarios / parameter_space / constraint_templates / underspecification_plan`；把 `matrix_dimensions` 注入提示词（补上老后端缺的那一环）。
2. **generator**：`ThreadPoolExecutor(max_workers=min(4, task_count))` 逐条生成，每完成 1 条即更新 `steps` + 广播 SSE（前端右侧 query console 实时滚动）。
3. **verifier**：并行逐条校验，产出 `pass + 5 维 scores`。
4. **evaluator**：程序化汇总 6 项指标（含 29→13 映射后的覆盖格计数）。

**降级策略**：`llm.py` 读不到 key/base_url 或首次调用失败 → 同一编排流程走确定性 mock 生成器（同样产出上述结构，秒级返回），前端表现完全一致。保证「没 key 也能开箱跑通」。

**失败约定**：任一步失败 → `status='failed'` + `steps.__failed__`，SSE 推 error，前端步骤条标 `is-error`。

### 4.5 29 → 13 能力映射（`scene_matrix.py` 中一张可改的配置表）

| index 能力列（13） | 映射的 L2（29） |
|---|---|
| 识别·图像识别 | 1.4 多模态感知融合 |
| 识别·文字识别 | 1.3 视觉感知-文字识别 |
| 识别·页面元素识别 | 1.1 元素识别、1.2 状态识别 |
| 规划·任务规划 | 4.1 任务分解、4.3 资源规划 |
| 规划·行动规划 | 4.4 异常处理 |
| 规划·路径规划 | 4.2 路径规划 |
| 行动·点击操作 | 6.1 点击精度 |
| 行动·输入操作 | 6.2 输入准确性 |
| 行动·页面跳转 | 6.3 滑动、6.4 手势、6.5 时序、6.6 原子性 |
| 行动·工具调用 | 6.7 API 调用、6.8 工具选择 |
| 判定·状态判定 | 2.1 动作验证、2.3 进度评估 |
| 判定·结果判定 | 2.2 结果校验、2.4 策略调整 |
| 判定·约束检查 | 3.1–3.5 推理、5.1–5.4 记忆 |

折算规则：一列取所辖 L2 的最大符号值（0 / 0.3 / 0.6 / 1.0）→ 量化成 `t0(不亮) / t1 / t2 / t3`；0 值即不点亮。
该表独立成 dict，若你对某列归属有不同意见，改一处即可。

---

## 五、前端改动点（外科式，尽量不动结构）

**只有 4 处改动，全部在 `index.html`（保留单文件、内联 CSS 原样不动）：**

1. `<header class="r7"></header>` → 填入步骤条 markup（`.mp-step-bar/.mp-steps/4×.mp-step`，id 用 `mp-step1-status`…），新增一份从 `css/pipeline.css` 抽出来的 `.mp-step-*` 样式（内联或 `frontend/css/pipeline-bar.css`）。
2. `<head>` 末尾加 `<script src="js/api.js" defer></script>`。
3. `connect()` / `run()` 两个函数体替换为真实调用（**其余渲染函数一律不动**）：
   - `connect()`：`api.agentConnect()` → 用后端 `logs` 逐行渲染到 r1 console → `setPhase('ready')`。
   - `run()`：`api.startDataset({brief})` → `api.streamSummary(id, onUpdate)`；
     `onUpdate(view)` 里用真实数据重建树/矩阵/指标/明细，并按 `progress` 推进 `setPhase`；`completed` 时 `finalizeR5()` + 用 `view.params` 渲染 r6。
4. 新增 `updateStepBar(n, status)`，与 `setPhase()` 同步顶部 4 个步骤状态（step1 `is-active` → `is-completed`；2/3/4 保持「待命」占位）。

**渲染层数据源切换（低风险改法）**：把 `DIMS / CAPS / DEMO.r5.items / DEMO.r6.rows` 的读取点从常量改为 `state.view`（后端 summary），**`DEMO` 常量整体保留作兜底**。`buildTree/buildMatrix/buildR5/buildR6/fitTree` 的算法与 CSS 一行不改 —— 它们本来就是数据驱动的。

**演示回退（零回归）**：`js/api.js` 探测后端；`/api/health` 不通或接口非 2xx → 自动切到今天这套纯演示动画（`runDemo()`），页面任何情况下都能完整演示。
`window.__demo` 钩子保留，并新增 `window.__api = { connected, view() }` 供自动化验收。

**步骤条 2/3/4**：只渲染与显示「待命」占位，不做页面、不做接口、不推进状态（按你的选择）。

---

## 六、数据流与状态机

```
点「接入智能体」→ POST /api/agent/connect → 轮询 /api/agent/status(400ms)
   → r1 console 逐行输出 6 条识别日志 → profile.capabilities 存下
   → setPhase('ready')  + 顶部 step1 置 is-active

点「提交测试任务」→ POST /api/dataset-ext/runs {execute:true} → 拿 id
   → EventSource /api/dataset-ext/stream?id=N
   → modeling：等首个 step 事件
   → executing：树按 dims 逐行点亮 + 矩阵按 tiers 逐格点亮 + query console 追加
                 （节奏按真实进度事件；每步加 60~120ms 最小间隔，避免瞬间闪完无观感）
   → evaluating：planner/generator/verifier 完成、指标结算延迟
   → done：finalizeR5() + r6 参数明细表 + 顶部 step1 置 is-completed，2/3/4 仍「待命」
失败 → 步骤条 is-error + r1/r6 区域显示错误信息
```

---

## 七、里程碑

| # | 内容 | 交付判据 |
|---|---|---|
| M1 | 后端骨架 + 静态托管 + `/api/health`；index.html 拷入并加步骤条 | 浏览器打开 `127.0.0.1:8787`，7 区域与步骤条正常显示，纯演示动画仍可跑 |
| M2 | `scene_matrix.py` + `/api/scene-matrix` + `summary` 聚合 + mock | `curl` 能拿到 14 维度/13 列/182 总格、6 项指标、参数明细行 |
| M3 | `step1_runner.py` 四步 + 提示词迁入 + 并发/重试 + SSE | mock 与真 LLM 两条路径都能从 `running` 走到 `completed`，`steps` 四个 key 齐全 |
| M4 | r1 智能体接入后端（上传 → 6 项识别 → profile → missing 列） | 上传两个文件后 r1 输出 6 行日志，r4 对应能力列不点亮 |
| M5 | 前端接线 + 演示回退 + 端到端验收 | 全流程 7 区域联动真实数据；后端关掉仍能完整演示 |

---

## 八、验收标准

**后端**（脚本化，curl/PowerShell）
1. `GET /api/health` → `{ok:true}`。
2. `POST /api/dataset-ext/runs {execute:true, task_count:2, variant_count:1}` → 拿 id；轮询 `/api/dataset-ext/run` 直到 `completed`；断言 `steps` 含 `planner/generator/verifier/evaluator`，`generator.task_set` 长度 = task_count。
3. `GET /api/dataset-ext/run/summary?id=N` 断言：`matrix.total == len(tree dims) * 13`、`metrics` 6 项、`params.length == len(planner.parameter_space)`。
4. 拔掉 key 再跑一次 → 走 mock，仍 `completed`（降级可用）。

**前端**（浏览器 + `window.__api` 钩子）
5. 阶段流转：`idle → connecting → ready → modeling → executing → evaluating → done`。
6. 树行数 = 后端 `tree` 行数；矩阵列数 = 13；`#r4-count` 的分母 = 182。
7. r5 六项数值与 `view.metrics` 完全一致（含 `59/182` 形式的分数项）；r6 行数 = `view.params.length`。
8. 顶部 step1 从「运行中」→「完成」，2/3/4 始终「待命」。
9. 关掉后端再打开页面 → 自动回退演示动画，无白屏、无控制台报错。

---

## 九、待确认 / 风险

| 项 | 说明与建议 |
|---|---|
| 29→13 映射归属 | 见 §4.5，属判断项。默认表已按语义分组（感知→识别、规划→规划、执行→行动、反思+推理+记忆→判定），可一处改。 |
| r4/r5 口径变化 | 演示里 r4 用 7 维度玩具集（分母 91），r5 用真实 14×13（分母 182），本来就不自洽；接真数据后统一为 **14 维度 × 13 列 = 182**，r4 显示 `59/182`。 |
| 树行数变化 | 电商购物从演示的 7 维度变成真实 14 维度（5 类别）；`fitTree()` 已按容器高度自适应行高，视觉不会溢出。 |
| LLM 耗时 | 真 LLM 下 planner 1 次 + generator N 次 + verifier N 次（每条典型 10~60s）。已用并发 + 逐条 SSE 进度解决观感；超时 `STEP1_TIMEOUT_S` 可配。 |
| 提示词口径 | 逐字迁入不重写，避免生成质量漂移；只在外层追加 `matrix_dimensions` 动态段。 |
| 2/3/4 步 | 本次只占位。日后接回原项目时，契约已对齐（`/api/dataset-ext/*` + step_details 形状），可平滑替换 `PipelineController`。 |

---

## 十、实施结果（M1–M5 已完成）

### 验收数据

| 套件 | 结果 |
|---|---|
| `python tools/verify_backend.py` | **49 passed, 0 failed** |
| `node tools/e2e_frontend.mjs --mode live` | **31 passed, 0 failed** |
| `node tools/e2e_frontend.mjs --mode demo` | **17 passed, 0 failed** |

端到端实测：14 场景 / 29 L2 / 13 能力列；电商购物 **14 维度 × 13 能力 = 182 格**；
`task_count=4` 的 mock 运行覆盖 12 维度 → `覆盖格 111/182`·`路径 12/14`·`r5=4|8|12|111/182|50%|0.634`，
页面 r5 六项与后端 `metrics` 逐项一致，r6 8 行 = 参数空间行数。

### 与方案的三处偏离（均已实测确认）

1. **树默认渲染 3 层**：真实矩阵含取值层共 60+ 行，超出 r3 面板高度且 `fitTree` 的行高下限是 14px，
   会裁掉大半棵树。改为「场景 → 维度类别 → 泛化维度」（20 行，与原演示观感一致）；
   取值层在放得下时（≤34 行）仍会自动带上，且取值本身在 r6 已完整呈现。
   *若希望始终显示 4 层并改为滚动条，把 `buildTreeKids()` 里的 `rows(full)<=34` 改为 `true`，
   同时把 `#r3 .tree` 的 `overflow:hidden` 改成 `auto` 即可。*
2. **失败语义更软**：配置了 LLM 但调用失败时，默认**降级为 mock 并打 `[降级]` warning**
   （可观测、不静默、整轮仍能跑完），而非直接 `failed`；
   `llm.fallback_to_mock=false` 时保持方案原定的硬失败 + `steps.__failed__`。
3. **前端 E2E 用 jsdom 而非真实浏览器**：本机沙箱禁止 Chrome/Edge 监听
   `--remote-debugging-port`（实测两个浏览器都无法建立调试端口），
   故用 jsdom + fetch/EventSource 垫片驱动同一份前端代码；垫片真连后端 SSE，顺带验证事件格式。
   真实浏览器观感需人工打开页面确认。

### 过程中修掉的真实缺陷

- **`build_summary` 在 planner 阶段会 500**：树取值兜底用 29 个 L2 编号去索引 13 个能力档位（`IndexError`）。
  该缺陷只在「第一次轮询落在 planner 完成之前」时触发 —— 前端首帧必然命中，属必现。
  已改为 13 列口径，并在 `verify_backend.py` 增加回归断言「planner 阶段就能安全取 summary」。
- **`r3-status` 谎报全量覆盖**：文案硬编码 `DIMS.length/DIMS.length`，
  实际只覆盖 12/14 时会显示「已覆盖 14/14」。已改为按真实 `doneDims` 计算。
- 演示态 `r4-status` 的硬编码「92%」改为按 `litCount/TOTAL_CELLS` 计算（演示态仍为 92%，无回归）。

### 最终文件清单

后端 10 个文件（`server.py` / `api_agent.py` / `api_dataset.py` / `step1_runner.py` /
`llm.py` / `mockgen.py` / `prompts.py` / `scene_matrix.py` / `store.py` / `data/scene_matrix.md`），
前端 3 个（`index.html` + `css/pipeline-bar.css` + `js/api.js`），
工具 4 个（`verify_backend.py` / `e2e_frontend.mjs` / `extract_matrix.py` / `extract_inline.py`），
外加 `README.md` / `PLAN.md` / `start.cmd` / `.gitignore`。

---

## 十一、后续修订：生成台宽度 + r3/r4 数据来源标记

### 11.1 生成台（r3 右侧「已泛化query」）宽度

原实现 `.gen-console{width:120px}` 是写死的，长 query 只剩开头几个字。现在的语义：

| 状态 | 行为 |
|---|---|
| 默认（未手动拖过） | **吃满右侧剩余宽度**：CSS `width:min(calc(100% - 171px),900px)`，171 = 树最小 160 + 分隔条 11；不写死任何像素默认值，窗口缩放自动跟随 |
| 手动拖拽 | `.r3-split` 分隔条（可见阶段与生成台同步），写内联 px 宽度，记忆在 `localStorage['atf.genConsoleWidth.v2']`（键带版本号，旧默认值不残留） |
| 双击分隔条 | 清掉内联宽度与记忆 → 回到「吃满」 |
| 边界 | 手动下界 `GEN_W_MIN=140`、上限 `GEN_W_MAX=900`（与 CSS 的 `min()` 同一常量，E2E 有防漂移断言）；树始终至少 160px |

另有：query 行带 `title`，悬停看全文（宽度再大也可能截断）。

### 11.2 r3/r4 的「像 mock」问题与处置

**诊断**：`#r3-src` / `#r4-src` 两个标记位在 DOM 里一直存在，但 `applySourceTags()` 只写了
`r5-src` / `r6-src`，所以只有 r5/r6 标了「mock 数据」，r3/r4 一直空着；加上当时
`/api/health` 返回 `llm_configured:false`（`engine=mock`），r3/r4 的覆盖结果确实来自
`mockgen._covered_dims()` 的哈希规则 —— 看的人无从区分「哪部分是真结构、哪部分是生成结果」。

**处置**（不改矩阵/树的口径，只把可信度说清楚）：

- `applySourceTags()` 扩展到 r3/r4/r5/r6 四处，统一 `mock 数据` / `部分 mock` / `LLM 实测`；
- r3 tooltip：真部分 = 场景泛化矩阵的结构 + `P1..Pn` 锚点 + 行内取值；本次生成部分 = 哪几行点亮；
- r4 tooltip：真部分 = 14 维度 × 13 能力（29 L2 映射）+ `○/△/●` 折算的档位 + 能力缺口整列；
  本次生成部分 = 点亮格是否落到该维度；
- 明确写进 README §六：**矩阵档位是矩阵固有的考察强度，不是实测结果** ——
  同一场景每次跑完矩阵长得一样，变化的是「亮哪几行」；要变成真实测需要真机跑智能体。

### 11.3 修订后的验收

| 套件 | 结果 |
|---|---|
| `python tools/verify_backend.py` | **91 passed, 0 failed** |
| `python tools/verify_config.py` | **17 passed, 0 failed** |
| `node tools/e2e_frontend.mjs --mode live` | **75 passed, 0 failed** |
| `node tools/e2e_frontend.mjs --mode demo` | **39 passed, 0 failed** |

新增断言：生成台默认吃满（CSS `calc` 的 reserve/cap 与 JS 常量一致，防漂移）/ 不再有写死宽度 /
默认态无内联宽度且未标记手动 / 分隔条样式 / 向右拖到底夹到 140px 且写 localStorage /
向左拖到底夹到上限 / 双击清内联宽度与记忆回到吃满 / 树最小宽度常量自洽 /
r3+r4 数据来源标记 = `mock 数据` / r3+r4 tooltip 含「场景泛化矩阵」「covered_dimensions」
「29 个 L2」「能力缺口」/ query 行 `title` = 完整指令。
原来的 «生成台已收窄到 120px» 断言随之删除。

---

## 十二、接入真 LLM 后暴露的四个真实缺陷（已修）

背景：用户要求「r5/r6 不要 mock」，并要求 **直接用 r1 上传的智能体配置文件里的 key**
（`examples/agent/shopping-agent.json`：火山网关 + `qwen3.8-max`）。

### 12.1 step1 的 LLM 来源 = 前端上传的智能体配置

原设计里「智能体配置的 api/key/model 只用于接入探测，step1 另用 `backend/config.yaml`」——
用户要求改成 **前端传什么就用什么**：

- `api_agent.config_text_of(agent_id)`：把 r1 落盘在 `uploads/<agent_id>-<name>` 的配置原文读回来；
- `api_agent.llm_declared(agent_id)`：解析出 `api/key/model`（**含明文 key，仅服务端内部使用**）；
- `llm.load_config(override=…)`：**兜底**来源；优先级 = 环境变量 `LLM_*` > `backend/config.yaml|yml|json`
  > 上传的智能体配置 > mock。生效来源写进 run 记录与日志（`llm_source` / `llm_model`）；
- 前端顶部徽标改成**以本次 run 的引擎为准**（`MODEL.engine` 优先于 `health.engine`），
  否则用了上传配置也会显示 `mock`。

### 12.2 四个缺陷（真跑一轮才暴露）

| # | 现象 | 根因 | 修复 |
|---|---|---|---|
| A | r3 树全不亮、r4 矩阵 `0/182`、r5 去重维度 0 | 真 LLM **不产出** `covered_dimensions`（原项目提示词里没有这个字段，是 mock 自己加的），而 `summarise()` 只认它 | 新增「参数名 → 泛化维度」语义映射 `scene_matrix.match_dim()`，用 task 的 `parameters` 折算覆盖维度（mock 路径不变） |
| B | 整轮非常慢、verifier 反复超时 → 降级成「部分 mock」 | 单次调用超时默认 180s，而该推理模型单次 verifier 实测 **244.7s**（含 3 万+ 字推理） | 默认超时 180s → **300s**，并在 `config.example.yaml` / README 写明「别调小」 |
| C | r6「关联维度」串行错位（`purchase_quantity` → 配送地址） | `_param_dim()` 只认 mock 的固定 slug 表，真 LLM 的参数名（`product_brand`/`sort_method`…）落不进去，兜底 `dims[i % n]` 会**硬凑一个错维度** | 先走语义映射；命中不了返回 `""`（前端显示 `—`），不再瞎猜 |
| D | 「覆盖度评分」真 LLM 下恒为 `0.000` | `compute_evaluator_metrics()` 按 mock 的 3~5 标度写死 `>= 3.0` 与 `/10.0`，而提示词要求 0.0~1.0 | 按实际值域自动识别标度（`score_scale`）并归一化后再判阈值；**mock 结果一字不变**（5 分制下与原公式等价） |

### 12.3 「参数名 → 泛化维度」映射的实测效果

对 `qwen3.8-max` 实际给出的 15 个参数名：命中 **14/15**
（唯一未命中的 `purchase_purpose` 确实是矩阵里没有的额外参数），
且 `delivery_address`/`delivery_method` 正确分开落到「配送地址」/「配送方式」——
这两个在原实现里会挤到同一个维度。匹配策略：先整词（避免 `spec` 误命中 `special`）、
再子串（`specification` 能对上 `spec`）、取配对数最多者。

### 12.4 真 LLM 的耗时特征（重要）

单次调用实测 200~250s（planner 6.9K 字提示词 / verifier 6.6K 字 + 3 万+ 字推理）。
`task_count=1` 整轮约 **11~12 分钟**；`task_count=4`（默认）约 **10~15 分钟**。
前端不会卡死：期间有 `任务 x/y`、`校验 x/y` 幽灵文字与逐行点亮。试水建议先把任务数设成 2。

### 12.5 新增的验收断言

- 后端：step1 用**端点必然不可达**的智能体配置 → `engine=llm+mock`、`data_source=mixed`、
  `llm_source` 含 `agent-config`、日志有 `[降级]`（**不产生任何真实外呼**，确定且快速）；
  另加一节纯函数校验：真 LLM 数据形态（有 `parameters`、无 `covered_dimensions`）的覆盖折算、
  `match_dim` 的整词/子串行为、0~1 与 3~5 两种标度的评估结果。
- 前端：E2E 上传的也是不可达端点 → 断言「来源 = agent-config」「四处标记 = 部分 mock」
  「日志有 `[降级]`」「徽标 = 部分 mock」。

