# -*- coding: utf-8 -*-
"""场景泛化矩阵：解析 `data/scene_matrix.md`（原文来自原项目 datasetext/scene-matrix.js），
并提供 29 个 L2 能力 → index 页面 13 个能力列的映射与档位折算。

对外三个概念：
  scenes      场景 → 维度类别 → 泛化维度（含每个泛化维度在 29 个 L2 上的考察强度）
  L2_INFO     29 个 L2 能力元数据（编号/L1/名称/说明）
  CAPS13      index「评测能力矩阵」的 13 列（识别/规划/行动/判定 四组），每列辖若干 L2
"""

from __future__ import annotations

import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
MATRIX_MD_PATH = DATA_DIR / "scene_matrix.md"

# ── 29 个 L2 能力（逐字取自原项目 scene-gen.js 的 L2_INFO）────────────────────
L2_INFO = [
    {"c": "1.1", "l1": "感知", "l2": "视觉感知-元素识别", "d": "识别页面元素位置与存在性"},
    {"c": "1.2", "l1": "感知", "l2": "视觉感知-状态识别", "d": "识别元素状态(置灰/可用、选中/未选中)"},
    {"c": "1.3", "l1": "感知", "l2": "视觉感知-文字识别", "d": "识别页面文字内容,理解当前页面状态"},
    {"c": "1.4", "l1": "感知", "l2": "多模态感知融合", "d": "融合视觉、文本、布局信息"},
    {"c": "2.1", "l1": "反思", "l2": "单步反思-动作验证", "d": "验证单次操作是否生效"},
    {"c": "2.2", "l1": "反思", "l2": "单步反思-结果校验", "d": "校验操作结果是否符合预期"},
    {"c": "2.3", "l1": "反思", "l2": "全局反思-进度评估", "d": "评估任务整体完成进度"},
    {"c": "2.4", "l1": "反思", "l2": "全局反思-策略调整", "d": "根据反馈调整策略"},
    {"c": "3.1", "l1": "推理", "l2": "常识推理-领域知识", "d": "掌握领域常识(如外卖份量)"},
    {"c": "3.2", "l1": "推理", "l2": "逻辑推理-因果推断", "d": "推断操作因果关系"},
    {"c": "3.3", "l1": "推理", "l2": "数学推理-数值计算", "d": "日期计算、价格排序、数量计算"},
    {"c": "3.4", "l1": "推理", "l2": "空间推理-位置关系", "d": "理解页面空间布局"},
    {"c": "3.5", "l1": "推理", "l2": "语义推理-意图理解", "d": "理解用户真实意图"},
    {"c": "4.1", "l1": "规划", "l2": "任务分解-步骤规划", "d": "将任务拆解为原子步骤"},
    {"c": "4.2", "l1": "规划", "l2": "路径规划-导航路径", "d": "规划从当前到目标页面的路径"},
    {"c": "4.3", "l1": "规划", "l2": "资源规划-效率优化", "d": "控制操作轮次,避免冗余"},
    {"c": "4.4", "l1": "规划", "l2": "异常处理-容错恢复", "d": "处理登录弹窗、缺货、验证码等"},
    {"c": "5.1", "l1": "记忆", "l2": "短期记忆-上下文保持", "d": "保持多轮对话中的指令上下文"},
    {"c": "5.2", "l1": "记忆", "l2": "长期记忆-用户偏好", "d": "记忆用户习惯偏好"},
    {"c": "5.3", "l1": "记忆", "l2": "知识记忆-领域知识库", "d": "记忆APP功能路径、业务规则"},
    {"c": "5.4", "l1": "记忆", "l2": "工作记忆-状态维护", "d": "维护当前任务中间状态"},
    {"c": "6.1", "l1": "执行", "l2": "动作执行-点击精度", "d": "精确点击目标元素中心"},
    {"c": "6.2", "l1": "执行", "l2": "动作执行-输入准确性", "d": "准确输入搜索词、填写表单"},
    {"c": "6.3", "l1": "执行", "l2": "动作执行-滑动操作", "d": "正确执行滑动操作"},
    {"c": "6.4", "l1": "执行", "l2": "动作执行-手势操作", "d": "执行长按、双击、拖拽、缩放"},
    {"c": "6.5", "l1": "执行", "l2": "动作序列-时序控制", "d": "等待页面加载完成后再执行"},
    {"c": "6.6", "l1": "执行", "l2": "动作序列-原子性保证", "d": "保证多步操作的原子性"},
    {"c": "6.7", "l1": "执行", "l2": "工具调用-API调用", "d": "正确调用openApp等底层API"},
    {"c": "6.8", "l1": "执行", "l2": "工具调用-工具选择", "d": "选择正确的工具/APP执行任务"},
]
L2_CODES = [x["c"] for x in L2_INFO]
L2_BY_CODE = {x["c"]: x for x in L2_INFO}

# ── index 页面的 13 个能力列：29 → 13 的映射表（唯一的主观判断处，改这里即可）──
# 分组沿用 index 的四组「识别 / 规划 / 行动 / 判定」；
# L1 归属：感知→识别、规划→规划、执行→行动、反思+推理+记忆→判定。
CAPS13 = [
    {"group": "识别", "cap": "图像识别",     "l2": ["1.4"]},
    {"group": "识别", "cap": "文字识别",     "l2": ["1.3"]},
    {"group": "识别", "cap": "页面元素识别", "l2": ["1.1", "1.2"]},
    {"group": "规划", "cap": "任务规划",     "l2": ["4.1", "4.3"]},
    {"group": "规划", "cap": "行动规划",     "l2": ["4.4"]},
    {"group": "规划", "cap": "路径规划",     "l2": ["4.2"]},
    {"group": "行动", "cap": "点击操作",     "l2": ["6.1"]},
    {"group": "行动", "cap": "输入操作",     "l2": ["6.2"]},
    {"group": "行动", "cap": "页面跳转",     "l2": ["6.3", "6.4", "6.5", "6.6"]},
    {"group": "行动", "cap": "工具调用",     "l2": ["6.7", "6.8"]},
    {"group": "判定", "cap": "状态判定",     "l2": ["2.1", "2.3"]},
    {"group": "判定", "cap": "结果判定",     "l2": ["2.2", "2.4"]},
    {"group": "判定", "cap": "约束检查",     "l2": ["3.1", "3.2", "3.3", "3.4", "3.5",
                                                   "5.1", "5.2", "5.3", "5.4"]},
]
CAPS13_NAMES = [x["cap"] for x in CAPS13]
CAP_GROUP_ORDER = ["识别", "规划", "行动", "判定"]
# index 页面里「无视觉能力」默认不点亮的列（智能体接入时由 agent profile 覆盖）
DEFAULT_MISSING_CAP = "图像识别"

# 矩阵符号 → 考察强度（取自原项目 scene-gen.js 的 SYM）
SYM = {"-": 0.0, "○": 0.3, "△": 0.6, "●": 1.0}


def score_to_tier(v: float) -> int:
    """考察强度 → index 的档位：t0 不点亮 / t1 低频 / t2 中频 / t3 高频。"""
    if v >= 1.0:
        return 3
    if v >= 0.6:
        return 2
    if v > 0:
        return 1
    return 0


def clean_scene_name(raw: str) -> str:
    """'1.1 电商购物' → '电商购物'。"""
    return re.sub(r"^\s*[\d.]+\s+", "", (raw or "").strip()).strip()


def parse_matrix(md: str | None = None) -> list[dict]:
    """解析矩阵 markdown → [{name, categories:[{name, dims:[{name, scores:{l2:0.6}}]}]}]。"""
    if md is None:
        md = MATRIX_MD_PATH.read_text(encoding="utf-8")
    scenes: list[dict] = []
    cur = None
    cur_cat = None
    for line in md.splitlines():
        m = re.match(r"^###\s+(.+)$", line)
        if m:
            cur = {"name": clean_scene_name(m.group(1)), "raw_name": m.group(1).strip(),
                   "categories": []}
            scenes.append(cur)
            cur_cat = None
            continue
        if not cur or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or cells[0] == "维度类别" or set(line.strip()) <= set("|- \t"):
            continue
        cat, dim = cells[0], cells[1]
        if not dim:
            continue
        scores: dict[str, float] = {}
        for i, code in enumerate(L2_CODES):
            if i + 2 >= len(cells):
                break
            sym = cells[i + 2]
            if sym in SYM:
                scores[code] = SYM[sym]
        if not cur_cat or cur_cat["name"] != cat:
            cur_cat = {"name": cat, "dims": []}
            cur["categories"].append(cur_cat)
        cur_cat["dims"].append({"name": dim, "scores": scores})
    return scenes


_SCENES: list[dict] | None = None


def scenes() -> list[dict]:
    global _SCENES
    if _SCENES is None:
        _SCENES = parse_matrix()
    return _SCENES


def scene_names() -> list[str]:
    return [s["name"] for s in scenes()]


def find_scene(name: str) -> dict | None:
    if not name:
        return None
    for s in scenes():
        if s["name"] == name or s.get("raw_name") == name:
            return s
    # 宽松匹配：包含关系
    for s in scenes():
        if name in s["name"] or s["name"] in name:
            return s
    return scenes()[0] if scenes() else None


def dim_scores(dim: dict) -> dict[str, float]:
    return dim.get("scores") or {}


def cap_strength(scores: dict[str, float], cap: dict) -> float:
    """一个能力列在其辖下 L2 上的考察强度 = 取最大值。"""
    return max((scores.get(code, 0.0) for code in cap["l2"]), default=0.0)


def cap_tiers(scores: dict[str, float]) -> list[int]:
    """泛化维度 → 13 个能力列的原始档位（未考虑智能体自身能力缺口）。"""
    return [score_to_tier(cap_strength(scores, cap)) for cap in CAPS13]


def flatten_dims(scene: dict) -> list[dict]:
    """场景 → 扁平化的泛化维度列表（带类别名与稳定 id P1..Pn，与矩阵行一一对应）。"""
    out = []
    for cat in scene.get("categories", []):
        for d in cat.get("dims", []):
            out.append({
                "id": f"P{len(out) + 1}",
                "name": d["name"],
                "category": cat["name"],
                "scores": d.get("scores") or {},
            })
    return out


def matrix_stat(scene_name: str, missing_caps: list[str] | None = None) -> dict:
    """矩阵覆盖统计：total = 维度数 × 13；covered = 自然点亮且智能体支持的能力格数。"""
    scene = find_scene(scene_name) or {"categories": []}
    dims = flatten_dims(scene)
    missing = set(missing_caps if missing_caps is not None else [DEFAULT_MISSING_CAP])
    total = len(dims) * len(CAPS13)
    covered = 0
    for d in dims:
        for i, t in enumerate(cap_tiers(d["scores"])):
            if t > 0 and CAPS13_NAMES[i] not in missing:
                covered += 1
    return {"total": total, "covered": covered, "dims": len(dims), "caps": len(CAPS13),
            "missing": sorted(missing)}


def l2_public() -> list[dict]:
    return [dict(x) for x in L2_INFO]


def caps13_public() -> list[dict]:
    return [dict(x) for x in CAPS13]


# ── 参数名（拉丁 slug）→ 泛化维度 的语义匹配 ────────────────────────────────
# 为什么需要：真 LLM 的 planner 会自己给参数命名（product_brand / sort_method /
# invoice_requirement…），mock 用的是另一套（brand / sort_by / invoice_type），
# 所以不能靠一张固定 slug 表。这里用「英文关键词 → 维度名里的中文词」配对打分，
# 取命中配对数最多的那个维度；一个都命中不了就返回 ""（不硬凑一个错维度）。
# 与 CAPS13 一样：这是本文件里的一处启发式，改这里即可。
PARAM_DIM_KEYWORDS = (
    ("category", "品类"), ("cuisine", "餐饮"), ("dish", "菜品"), ("name", "名称"),
    ("brand", "品牌"), ("merchant", "商家"), ("store", "店铺"), ("shop", "店铺"),
    ("spec", "规格"), ("size", "规格"), ("portion", "分量"), ("model", "型号"),
    ("price", "价格"), ("budget", "价格"), ("cost", "价格"), ("amount", "金额"),
    ("condition", "条件"), ("state", "状态"), ("status", "状态"), ("type", "类型"),
    ("condition", "状态"), ("method", "方式"), ("way", "方式"), ("mode", "模式"),
    ("requirement", "要求"), ("req", "要求"), ("preference", "偏好"), ("pref", "偏好"),
    ("special", "特殊"), ("addon", "加料"), ("extra", "加料"),
    ("level", "等级"), ("grade", "等级"), ("sort", "排序"), ("order", "排序"),
    ("filter", "筛选"), ("tag", "标签"), ("label", "标签"), ("condition", "筛选条件"),
    ("review", "评价"), ("rating", "评价"), ("comment", "评价"),
    ("quantity", "数量"), ("count", "数量"), ("number", "数量"),
    ("address", "地址"), ("location", "位置"), ("city", "城市"), ("destination", "目的地"),
    ("origin", "出发地"), ("departure", "出发"), ("arrival", "到达"), ("via", "途经"),
    ("delivery", "配送"), ("shipping", "配送"), ("express", "快递"), ("logistics", "物流"),
    ("pickup", "自提"), ("time", "时间"), ("date", "日期"), ("duration", "时长"),
    ("period", "周期"), ("frequency", "频率"), ("term", "期限"), ("schedule", "日程"),
    ("remind", "提醒"), ("calendar", "日历"),
    ("invoice", "发票"), ("receipt", "发票"), ("tax", "税"),
    ("after_sales", "售后"), ("return", "退换"), ("refund", "退"), ("warranty", "保修"),
    ("platform", "平台"), ("channel", "渠道"), ("app", "应用"),
    ("taste", "口味"), ("flavor", "口味"), ("sugar", "糖度"), ("temperature", "温度"),
    ("topping", "加料"), ("ingredient", "配料"), ("spicy", "辣"), ("ice", "冰"),
    ("purpose", "用途"), ("reason", "原因"), ("goal", "目标"), ("target", "目标"),
    ("cabin", "舱位"), ("seat", "座位"), ("flight", "航班"), ("airline", "航空公司"),
    ("train", "车次"), ("hotel", "酒店"), ("room", "房型"), ("route", "路线"),
    ("navigation", "导航"), ("avoid", "避让"), ("traffic", "实时"), ("vehicle", "车型"),
    ("cinema", "影院"), ("hall", "影厅"), ("movie", "影片"), ("film", "影片"),
    ("ticket", "票务"), ("play", "播放"), ("playlist", "播放列表"), ("download", "下载"),
    ("storage", "存储"), ("quality", "质量"), ("content", "内容"), ("news", "资讯"),
    ("novel", "小说"), ("reading", "阅读"), ("browse", "浏览"),
    ("setting", "设置"), ("switch", "开关"), ("mode", "模式"), ("permission", "权限"),
    ("privacy", "隐私"), ("notice", "通知"), ("notification", "通知"),
    ("payment", "支付"), ("pay", "支付"), ("security", "安全"), ("verify", "验证"),
    ("limit", "限额"), ("accuracy", "精度"), ("photo", "拍摄"), ("watermark", "水印"),
    ("shutter", "快门"), ("clean", "清理"), ("backup", "备份"), ("cloud", "云存储"),
    ("battery", "省电"), ("screen", "屏幕"), ("charge", "充电"), ("sensor", "感知"),
    ("warning", "预警"), ("emergency", "应急"), ("care", "关怀"), ("accessibility", "辅助"),
    ("page", "页面"), ("function", "功能"), ("module", "模块"), ("path", "路径"),
    ("query", "查询"), ("search", "查询"), ("scope", "范围"), ("range", "范围"),
    ("account", "账户"), ("consumption", "消费"), ("checkin", "签到"), ("coupon", "券"),
    ("point", "积分"), ("coin", "金币"), ("rule", "规则"), ("activity", "活动"),
    ("style", "风格"), ("audience", "受众"), ("interaction", "互动"), ("document", "文档"),
    ("collab", "协作"), ("file", "文件"), ("share", "分享"), ("tool", "工具"),
    ("sport", "运动"), ("device", "设备"), ("data", "数据"), ("record", "记录"),
    ("resource", "资源"), ("subject", "学科"), ("difficulty", "难度"), ("progress", "进度"),
    ("exam", "考试"), ("certification", "认证"), ("product", "产品"), ("risk", "风险"),
    ("yield", "收益"), ("investment", "投资"), ("fund", "资金"),
)


def _param_tokens(slug: str) -> list[str]:
    """把参数名切成英文词：product_brand → ['product','brand']；camelCase 也算一个词。"""
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", slug or "").lower()
    return [t for t in re.findall(r"[a-z0-9]+", s) if t]


def match_dim(slug: str, dim_names: list[str]) -> str:
    """参数名 → 泛化维度名（启发式）。

    匹配分两轮：先按「整词」命中关键词表（避免 spec 误命中 special 这种前缀误判），
    整词一个都没命中时才退回子串匹配（specification 这种长词能对上 spec）。
    命中多个维度时取「配对数最多」的那个；严格并列取先出现的；一个都不中返回 ""。
    """
    if not slug or not dim_names:
        return ""
    tokens = _param_tokens(slug)
    cn_words = {cn for en, cn in PARAM_DIM_KEYWORDS if en in tokens}
    if not cn_words:
        low = slug.lower()
        cn_words = {cn for en, cn in PARAM_DIM_KEYWORDS if en in low}
    best, best_score = "", 0
    for name in dim_names:
        score = sum(1 for cn in cn_words if cn and cn in name)
        if score > best_score:
            best, best_score = name, score
    return best


def scenes_public() -> list[dict]:
    """给前端的场景结构：省掉原始 md 里没用的字段，保留 dims/scores。"""
    out = []
    for s in scenes():
        out.append({
            "name": s["name"],
            "categories": [
                {"name": c["name"],
                 "dims": [{"name": d["name"], "scores": dict(d.get("scores") or {})}
                          for d in c["dims"]]}
                for c in s["categories"]
            ],
        })
    return out
