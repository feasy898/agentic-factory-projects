"""recommend —— 「知识点掌握 -> 母题推荐」引擎（误解标签针对性选题）。

行为契约（specs/drafts/recommend.spec.md，本文件为参考实现）：
- 选题规则：误解标签优先。Tier 1 = 主知识点题且带有"误解库中绑定到该知识点的
  误解标签"；Tier 2 = 其余主知识点题；每层内 (difficulty, id) 升序，Tier 1 在前。
- 三个入口：recommend_for_kp（单知识点选题）、recommend_for_profile（画像级，
  弱知识点最弱优先）、attach_recommendations（把推荐挂到 route 产出的
  LearningPlan.steps，PlanStep.recommended_item_ids）。
- 纯函数：不判分、不更新掌握度、不做拓扑排序、不出卷、无随机、无时钟、无 IO。

注入装载约束（见 specs/drafts/recommend.spec.md §2）：不用 from __future__ import
annotations——dataclass 字符串注解在 _regen_recommend 顶层模块名下会触发未受保护的
sys.modules 解析；注解直接写真实对象。
"""
from dataclasses import dataclass

from xuexing.types import LearningPlan, PlanStep

__all__ = [
    "RecommendError",
    "Recommendation",
    "recommend_for_kp",
    "recommend_for_profile",
    "attach_recommendations",
]


class RecommendError(ValueError):
    """recommend 模块所有校验失败的异常类型。"""


@dataclass
class Recommendation:
    """一个薄弱知识点的推荐题集（kp_id 互异；item_ids 可为空列表）。"""

    kp_id: str
    item_ids: list


# ---------- 内部工具 ----------

def _validated_limit(limit) -> object:
    """limit 校验：None 放行（不截断）；否则 int 且非 bool 且 >=1。"""
    if limit is None:
        return None
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise RecommendError(f"limit must be None or an int, got {limit!r}")
    if limit < 1:
        raise RecommendError(f"limit must be >=1, got {limit!r}")
    return limit


def _misconception_ids(misconceptions, kp_id) -> set:
    """绑定到 kp_id 的误解 id 集合；None/空 -> 空集（集合语义，输入顺序无关）。"""
    if misconceptions is None:
        return set()
    return {mc.id for mc in misconceptions if mc.kp_id == kp_id}


def _by_difficulty_then_id(items) -> list:
    return sorted(items, key=lambda it: (it.difficulty, it.id))


# ---------- 核心：单知识点选题 ----------

def recommend_for_kp(kp_id, bank, misconceptions=None, limit=None) -> list:
    """为主知识点 kp_id 产出有序推荐题 id 列表。

    池 = bank.by_kp(kp_id, primary_only=True)；Tier 1 = 带 M 中标签者（M 为绑定到
    kp_id 的误解 id 集），Tier 2 = 其余；各层 (difficulty, id) 升序，Tier 1 在前。
    池空（含未知 kp）返回 []；limit 为前缀截断。返回新列表，纯函数。
    """
    checked_limit = _validated_limit(limit)
    mc_ids = _misconception_ids(misconceptions, kp_id)
    targeted = []
    general = []
    for it in bank.by_kp(kp_id, primary_only=True):
        if mc_ids and set(it.misconceptions) & mc_ids:
            targeted.append(it)
        else:
            general.append(it)
    ordered = _by_difficulty_then_id(targeted) + _by_difficulty_then_id(general)
    ids = [it.id for it in ordered]
    if checked_limit is not None:
        ids = ids[:checked_limit]
    return ids


# ---------- 画像级：知识点掌握 -> 推荐 ----------

def recommend_for_profile(profile, bank, misconceptions=None,
                          mastery_threshold=0.65, limit=None) -> list:
    """由掌握度画像产出薄弱知识点的推荐列表（最弱优先，平局按 kp_id 升序）。

    校验先于计算：threshold 须在开区间 (0,1)（恰等阈值视为达标），先于 limit 校验。
    每个弱 kp 恰一个 Recommendation；不做图过滤，池空的 kp 产出空 item_ids。
    """
    if not 0 < mastery_threshold < 1:
        raise RecommendError("mastery_threshold out of (0,1)")
    checked_limit = _validated_limit(limit)
    weak = [(m, kp) for kp, m in profile.mastery.items() if m < mastery_threshold]
    # (mastery, kp_id) 升序：kp_id 唯一，float 精确比较，set 迭代序不影响输出。
    weak.sort()
    return [
        Recommendation(
            kp_id=kp,
            item_ids=recommend_for_kp(kp, bank, misconceptions, checked_limit),
        )
        for _, kp in weak
    ]


# ---------- 挂载：把推荐填进学习计划步骤 ----------

def attach_recommendations(plan, bank, misconceptions=None, limit=None):
    """返回新 LearningPlan：每步 recommended_item_ids = recommend_for_kp(该步 kp)。

    输入 plan 不被修改：steps 为新列表、原四字段逐项复制；reviews 为新列表、
    条目对象复用（ReviewEntry 按值对象对待）；learner_id/created_at 原样保留。
    重复 kp 的步骤各自独立计算；plan 缺字段让原生异常传播，不包装。
    """
    checked_limit = _validated_limit(limit)
    steps = [
        PlanStep(
            kp_id=s.kp_id,
            strategy_id=s.strategy_id,
            rationale=s.rationale,
            target_mastery=s.target_mastery,
            recommended_item_ids=recommend_for_kp(
                s.kp_id, bank, misconceptions, checked_limit),
        )
        for s in plan.steps
    ]
    return LearningPlan(
        learner_id=plan.learner_id,
        steps=steps,
        reviews=list(plan.reviews),
        created_at=plan.created_at,
    )
