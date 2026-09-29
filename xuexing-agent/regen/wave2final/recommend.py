"""recommend — 知识点掌握 -> 母题推荐（误解标签针对性选题 + 计划步骤挂载）。

冻结契约：specs/frozen/recommend.spec.md。纯规划：不判分、不更新掌握度、
不做拓扑排序、不出卷、不持久化。唯一排序来源：题目 (difficulty, id) 升序、
弱点 (mastery, kp_id) 升序；校验一律先于任何池/步骤/画像访问。
"""
from dataclasses import dataclass

from xuexing.types import LearningPlan, PlanStep, Profile


class RecommendError(ValueError):
    """领域校验失败（limit / mastery_threshold 非法）；鸭子失配的原生异常不在此列。"""


@dataclass
class Recommendation:
    kp_id: str
    item_ids: list[str]


def _validated_limit(limit):
    """limit 校验：None 放行；否则必须 int 且非 bool 且 >=1，违反抛 RecommendError。

    NaN/str/float 等一切非 int（bool 先于 int 判定排除）与 <1 的 int 均抛，无例外。
    """
    if limit is None:
        return None
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise RecommendError(f"limit must be None or an int >= 1, got {limit!r}")
    return limit


def _misconception_ids(misconceptions, kp_id):
    """M = 绑定到 kp_id 的误解标签 id 集合；None/空 -> 空集；集合语义（顺序无关、容忍重复）。"""
    if misconceptions is None:
        return set()
    return {mc.id for mc in misconceptions if mc.kp_id == kp_id}


def _ranked_ids(kp_id, bank, misconceptions):
    """Tier1（误解针对性）在前 + Tier2（一般巩固）在后，层内 (difficulty, id) 升序。

    不依赖 by_kp 的返回序；目标 kp 仅作次要知识点的题由 primary_only=True 永不进入池。
    """
    target = _misconception_ids(misconceptions, kp_id)
    tier1: list = []
    tier2: list = []
    for item in bank.by_kp(kp_id, primary_only=True):
        (tier1 if target & set(item.misconceptions) else tier2).append(item)
    tier1.sort(key=lambda it: (it.difficulty, it.id))
    tier2.sort(key=lambda it: (it.difficulty, it.id))
    return [it.id for it in tier1 + tier2]


def recommend_for_kp(kp_id, bank, misconceptions=None, limit=None) -> list[str]:
    limit = _validated_limit(limit)
    ids = _ranked_ids(kp_id, bank, misconceptions)
    if limit is not None:
        ids = ids[:limit]  # 前缀截断；limit 超池长自然全量返回
    return ids


def recommend_for_profile(profile: Profile, bank, misconceptions=None,
                          mastery_threshold: float = 0.65,
                          limit=None) -> list[Recommendation]:
    if not (0 < mastery_threshold < 1):
        # 谓词精确形式：NaN 两处比较皆 False -> 抛 RecommendError；
        # 非数值类型在此比较处抛原生 TypeError，原样透传不包装。
        raise RecommendError(
            f"mastery_threshold must be within (0, 1), got {mastery_threshold!r}")
    limit = _validated_limit(limit)
    weak = sorted(
        (kp for kp, m in profile.mastery.items() if m < mastery_threshold),
        key=lambda kp: (profile.mastery[kp], kp),
    )
    return [
        Recommendation(kp_id=kp,
                       item_ids=recommend_for_kp(kp, bank, misconceptions, limit))
        for kp in weak
    ]


def attach_recommendations(plan, bank, misconceptions=None,
                           limit=None) -> LearningPlan:
    limit = _validated_limit(limit)  # 入口无条件校验：先于步骤遍历、先于 plan.steps 访问
    steps = [
        PlanStep(
            kp_id=step.kp_id,
            strategy_id=step.strategy_id,
            rationale=step.rationale,
            target_mastery=step.target_mastery,
            recommended_item_ids=recommend_for_kp(step.kp_id, bank,
                                                  misconceptions, limit),
        )
        for step in plan.steps
    ]
    return LearningPlan(
        learner_id=plan.learner_id,
        steps=steps,
        reviews=list(plan.reviews),  # 新列表、条目对象复用（按值对象对待，不深拷贝）
        created_at=plan.created_at,
    )
