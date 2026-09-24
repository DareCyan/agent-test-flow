# -*- coding: utf-8 -*-
"""确定性 mock 数据集生成器。

用途：LLM 未配置或调用失败时，仍然产出与真 LLM 完全同构的 planner/generator/verifier
结果，让整条流水线与前端渲染保持一致（不造假指标，只是数据源换成可复现的规则生成）。
"""

from __future__ import annotations

import hashlib

# 与 index 页面演示池同源的 query 模板（真实运行时会与场景维度拼接）
QUERY_POOL = [
    "请在淘宝买", "请在京东买", "请在拼多多买", "帮我找一件羽绒服", "买双跑步鞋",
    "50 元以内的蓝牙耳机", "300 元以内的机械键盘", "买两箱牛奶", "找一款适合老人用的手机",
    "买一个 24 寸行李箱", "比价 AirPods 和漫步者", "下单前看看店铺评分",
    "帮我看看这块手表是不是正品", "给学生党推荐一款平板", "买猫粮哪个牌子好",
    "买台空气炸锅", "双11 买冰箱划算吗", "帮我订一箱矿泉水", "找条修身牛仔裤", "买个体重秤",
]

# 泛化维度名 → 参数名（拉丁 slug），用于 planner.parameter_space 与 r6「参数覆盖明细」
DIM_PARAM = {
    "商品品类": ("product_category", "categorical", ["数码", "服饰", "食品", "家居", "美妆", "母婴", "运动", "图书"]),
    "商品品牌": ("brand", "categorical", ["华为", "苹果", "小米", "优衣库", "耐克", "美的", "海尔", "格力"]),
    "商品规格": ("specification", "categorical", ["尺寸", "颜色", "容量", "材质", "版本", "重量"]),
    "商品价格": ("price_upper", "numerical", ["50", "100", "300", "500", "1000", "3000", "8000"]),
    "商品状态": ("item_state", "categorical", ["新品", "二手", "预售", "现货", "特价", "临期"]),
    "排序方式": ("sort_by", "categorical", ["销量", "价格", "好评", "新品", "综合", "距离"]),
    "筛选标签": ("filter_tag", "categorical", ["包邮", "次日达", "7天无理由", "官方旗舰", "百亿补贴"]),
    "评价维度": ("review_metric", "categorical", ["评分", "追评", "带图评论", "差评率", "问答"]),
    "购买数量": ("quantity", "numerical", ["1", "2", "3", "5", "10", "一箱", "一打"]),
    "配送地址": ("delivery_address", "textual", ["家", "公司", "学校", "父母家"]),
    "配送方式": ("delivery_method", "categorical", ["快递", "同城", "自提", "次日达", "预约送达"]),
    "发票需求": ("invoice_type", "categorical", ["不开发票", "电子普票", "增值税专票", "纸质发票"]),
    "售后保障": ("after_sales", "categorical", ["7天无理由", "15天换货", "一年保修", "上门维修", "价保"]),
    "电商平台": ("platform", "categorical", ["淘宝", "京东", "拼多多", "抖音", "小红书", "唯品会"]),
    "餐饮品类": ("cuisine", "categorical", ["快餐", "火锅", "日料", "饮品", "烧烤"]),
    "口味偏好": ("taste", "categorical", ["微辣", "不辣", "少糖", "多冰", "常温"]),
    "温度要求": ("temperature", "categorical", ["常温", "加冰", "热的", "常温少冰"]),
    "糖度要求": ("sugar_level", "categorical", ["全糖", "七分糖", "半糖", "无糖"]),
}

STRATEGIES = ["Delete", "Vaguify", "Genericize"]
SEVERITIES = ["high", "medium", "low"]
AMBIGUITY = ["outcome-critical", "divergent", "benign"]
SCORE_DIMS = ["clarity", "completeness", "consistency", "feasibility", "constraint_coverage"]


def _seed(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)


def _pick(seq: list, seed: int, offset: int = 0):
    return seq[(seed + offset) % len(seq)] if seq else None


def param_for(dim_name: str, index: int) -> dict:
    """泛化维度 → 参数定义（未知维度给一个通用兜底）。"""
    if dim_name in DIM_PARAM:
        name, ptype, rng = DIM_PARAM[dim_name]
    else:
        name, ptype, rng = f"param_{index}", "categorical", ["取值A", "取值B", "取值C"]
    return {"name": name, "type": ptype, "range": rng,
            "distribution": "weighted" if ptype == "categorical" else "uniform",
            "distribution_config": {},
            "description": f"{dim_name}维度的取值空间",
            "constraints": []}


def mock_planner(brief: str, scene: str, dims: list[dict]) -> dict:
    parameter_space = {}
    for i, d in enumerate(dims):
        p = param_for(d["name"], i)
        parameter_space[p["name"]] = {k: v for k, v in p.items() if k != "name"}
    return {
        "domain_scenarios": [scene],
        "parameter_space": parameter_space,
        "constraint_templates": {
            "Positive": [f"必须完成 {scene} 场景下的核心动作"],
            "Negative": ["禁止购买超出预算上限的商品"],
            "Conditional": ["若用户表达了送礼意图，则优先高端包装"],
            "Iterative": ["对多个对象重复应用同一约束"],
            "Subjective": ["选择'性价比最高'的方案"],
        },
        "underspecification_plan": {
            "dimensions": {"Goal": "目标未明确", "Constraint": "约束边界模糊",
                           "Input": "关键输入缺失", "Context": "上下文缺失"},
            "severity_levels": {"high": "直接改变任务结果", "medium": "可能产生分歧", "low": "影响较小"},
        },
        "combination_rules": {"cross_platform": False, "temporal_chain": False},
        "_mock": True,
        "_brief": brief,
    }


def _covered_dims(dims: list[dict], task_count: int, brief: str = "") -> list[dict]:
    """mock 覆盖的维度：由 brief 决定性地挑一批，跨类别散布。

    之前是"取前 3×任务数 个维度"，于是总是上 N 行整片亮、下面整片暗 —— 一眼就是假数据。
    现在按 (brief + 维度名) 的哈希确定性排序后取 n 个，再按原顺序返回：
    不同 brief 覆盖的维度会真的不一样（行为随输入变），但仍是 mock（页面上有来源标记）。
    """
    n = max(1, min(len(dims), int(round(2.2 * max(1, task_count)))))
    if n >= len(dims):
        return list(dims)
    seed = _seed("cover|" + (brief or "mock-seed"))
    picked = sorted(dims, key=lambda d: (seed + _seed(str(d.get("name")))) % 99991)[:n]
    keep = {d["name"] for d in picked}
    return [d for d in dims if d["name"] in keep]


def mock_generator(planner: dict, dims: list[dict], task_count: int, variant_count: int) -> list[dict]:
    scene = (planner.get("domain_scenarios") or ["购物"])[0]
    covered = _covered_dims(dims, task_count, str(planner.get("_brief") or ""))
    params = planner.get("parameter_space") or {}
    tasks: list[dict] = []
    for n in range(task_count):
        my_dims = [d for i, d in enumerate(covered) if i % task_count == n] or covered[:1]
        seed = _seed(f"{scene}-{n}-{task_count}-{variant_count}")
        base = _pick(QUERY_POOL, seed, n)
        target = my_dims[0]["name"] if my_dims else scene
        # 用该维度关联参数的取值拼一条更具体的指令
        pname = param_for(target, 0)["name"]
        rng = (params.get(pname) or {}).get("range") or []
        val = _pick(rng, seed, n) if rng else ""
        instruction = f"{base}{val}，并覆盖{target}属性" if val else f"{base}{target}相关的商品"
        variants = []
        for v in range(variant_count):
            vs = _seed(f"{scene}-{n}-{v}-variant")
            variants.append({
                "variant_id": f"task-{n + 1}-v{v + 1}",
                "instruction": instruction.replace(val, "") if val else instruction,
                "severity": _pick(SEVERITIES, vs, v),
                "ambiguity_class": _pick(AMBIGUITY, vs, v),
                "underspecified_segments": [
                    {"strategy": _pick(STRATEGIES, vs, v + 1), "segment": val or target}
                ],
            })
        tasks.append({
            "task_id": f"task-{n + 1}",
            "domain": scene,
            "scenario": f"{scene}·{target}",
            "full_instruction": instruction,
            "constraints": {"positive": [f"必须覆盖{target}"], "conditional": [], "subjective": []},
            "underspecified_variants": variants,
            "covered_dimensions": [d["name"] for d in my_dims],
            "cross_platform": False,
            "temporal_chain": False,
        })
    return tasks


def mock_verifier(task: dict) -> dict:
    """确定性 5 维评分 → 通过率约 7 成、覆盖度评分落在 0.4~0.7（与演示量级一致）。"""
    seed = _seed("v" + str(task.get("task_id")) + str(task.get("full_instruction"))[:40])
    # 3~5 分为主、偶尔 2 分：让 width/balance/depth 三项乘积落在真实可解释的区间
    scores = {d: 3 + (seed >> (i * 3)) % 3 for i, d in enumerate(SCORE_DIMS)}
    weak = SCORE_DIMS[(seed >> 4) % len(SCORE_DIMS)]
    if seed % 3 == 0:
        scores[weak] = 2
    passed = (seed % 10) >= 3
    return {
        "task_id": task.get("task_id", ""),
        "pass": passed,
        "scores": scores,
        "issues": [] if passed else ["约束覆盖不足，缺少明确的价格上限"],
        "suggestions": "建议补充可度量的约束边界" if not passed else "",
        "final_ambiguity_class": (task.get("underspecified_variants") or [{}])[0].get("ambiguity_class", ""),
        "severity_verified": True,
        "new_task_risk": False,
        "_mock": True,
    }


def mock_dim_scores(dim: dict) -> dict:
    return dim.get("scores") or {}
