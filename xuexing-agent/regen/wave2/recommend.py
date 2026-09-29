"""recommend — 知识点掌握 -> 母题推荐（误解标签针对性选题 + 计划步骤挂载）。

冻结契约：specs/frozen/recommend.spec.md。纯规划模块：不判分、不更新掌握度、
不做拓扑排序、不出卷、不持久化。三个入口均为纯函数，输出只依赖入参值。

依赖约束：仅标准库 + xuexing.types（绝对导入）；单文件、无相对导入、
不使用 from __future__ import annotations（顶层装载为 _regen_recommend）。
"""
from dataclasses import dataclass

from xuexing.types import LearningPlan, PlanStep


class RecommendError(ValueError):
    """本模块唯一异常类型：所有领域校验失败抛它。"""


@dataclass
class Recommendation:
    """一条推荐：薄弱知识点 -> 有序练习题 id（可为空列表）。"""

    kp_id: str
    item_ids: list[str]


def _validated_limit(limit):
    """limit 校验（§3.3）：None 不截断；否则必须 int 且非 bool 且 >= 1。

    str/float/bool/NaN 等一切非 int 与 <1 的 int 一律抛 RecommendError，无例外。
    """
    if limit is None:
        return None
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise RecommendError(
            f"limit 必须为 None 或 int 且 >= 1，得到 {limit!r}"
        )
    return limit


def _misconception_ids(misconceptions, kp_id):
    """M = {mc.id for mc in misconceptions if mc.kp_id == kp_id}。

    misconceptions=None -> 空集；重复 id 容忍（集合语义）；输入顺序无关。
    条目缺 id/kp_id 属性时原生异常传播，不包装。
    """
    if misconceptions is None:
        return set()
    return {mc.id for mc in misconceptions if mc.kp_id == kp_id}


def recommend_for_kp(kp_id, bank, misconceptions=None, limit=None):
    """为一个知识点产出有序练习题 id：Tier 1（误解针对性）在前 + Tier 2 在后。

    校验先于任何计算：limit 校验为函数体第一条语句，先于误解库消费、
    先于 bank.by_kp 调用——空池不豁免非法 limit。池空（含未知 kp）容忍返回 []。
    """
    limit = _validated_limit(limit)
    m_ids = _misconception_ids(misconceptions, kp_id)
    pool = bank.by_kp(kp_id, primary_only=True)

    tier1 = []
    tier2 = []
    for item in pool:
        if set(item.misconceptions) & m_ids:
            tier1.append(item)
        else:
            tier2.append(item)
    # 唯一排序来源：每层内 (difficulty, id) 升序；不依赖 by_kp 的返回序。
    tier1.sort(key=lambda it: (it.difficulty, it.id))
    tier2.sort(key=lambda it: (it.difficulty, it.id))

    ordered = [it.id for it in tier1] + [it.id for it in tier2]
    return ordered if limit is None else ordered[:limit]  # 前缀截断；超池长全量返回


def recommend_for_profile(profile, bank, misconceptions=None,
                          mastery_threshold=0.65, limit=None):
    """掌握度 -> 推荐：mastery < threshold 的知识点各产出恰一个 Recommendation。

    校验先于任何计算且先查 threshold 后查 limit：谓词精确为
    not (0 < mastery_threshold < 1)——NaN 落网抛 RecommendError；非数值类型
    比较时原生 TypeError 原样透传不包装。恰等于阈值视为达标不推荐。
    弱点按 (mastery 升序, kp_id 升序) 排列（最弱优先）；图外键照常产出（可空 ids）。
    """
    if not (0 < mastery_threshold < 1):
        raise RecommendError(
            f"mastery_threshold 必须在开区间 (0, 1) 内，得到 {mastery_threshold!r}"
        )
    limit = _validated_limit(limit)

    weak = [(m, kp) for kp, m in profile.mastery.items() if m < mastery_threshold]
    weak.sort()  # (mastery, kp_id) 升序：最弱优先，平局按 kp_id 码点序
    return [
        Recommendation(
            kp_id=kp,
            item_ids=recommend_for_kp(kp, bank, misconceptions, limit),
        )
        for _m, kp in weak
    ]


def attach_recommendations(plan, bank, misconceptions=None, limit=None):
    """把推荐挂到学习计划步骤上，返回新 LearningPlan，输入 plan 不被修改。

    limit 校验在入口无条件执行：先于步骤遍历、先于 plan.steps 属性访问——
    空步骤/无 steps 属性的计划不豁免非法 limit。plan 本身不做校验，
    鸭子失配（缺字段/缺方法）时原生异常传播。步骤用共享 xuexing.types.PlanStep
    构造（禁止影子复制）；reviews 为新列表、条目对象复用原对象。
    """
    limit = _validated_limit(limit)

    new_steps = [
        PlanStep(
            kp_id=step.kp_id,
            strategy_id=step.strategy_id,
            rationale=step.rationale,
            target_mastery=step.target_mastery,
            recommended_item_ids=recommend_for_kp(
                step.kp_id, bank, misconceptions, limit
            ),
        )
        for step in plan.steps
    ]
    new_reviews = list(plan.reviews)
    return LearningPlan(
        learner_id=plan.learner_id,
        steps=new_steps,
        reviews=new_reviews,
        created_at=plan.created_at,
    )
