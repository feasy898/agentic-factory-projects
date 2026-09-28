"""学习路线规划器：掌握度画像 + 知识图谱 + 策略库 -> 有序学习计划。"""
from __future__ import annotations

from datetime import date

from .itembank import ItemBank
from .pedagogy import StrategyLibrary
from .scheduler import ReviewLog, schedule
from .types import LearningPlan, PlanStep, Profile, ReviewEntry
from .kpgraph import KPGraph


class RouteError(ValueError):
    pass


def build_plan(
    profile: Profile,
    bank: ItemBank,
    graph: KPGraph,
    strategies: StrategyLibrary,
    today: date,
    mastery_threshold: float = 0.65,
    session_size: int = 4,
) -> LearningPlan:
    """生成学习计划。

    规则：
    - 薄弱点 = mastery < mastery_threshold 的知识点；
    - 顺序：先序未修完者不得提前（拓扑有效），同级按 (后代数*缺口) 优先；
    - 每个步骤按掌握度/年级从策略库选策略；
    - 已达标知识点生成间隔复习日程。
    """
    if not 0.0 < mastery_threshold < 1.0:
        raise RouteError("mastery_threshold out of (0,1)")
    if session_size < 1:
        raise RouteError("session_size must be >=1")

    weak = {k for k, m in profile.mastery.items() if m < mastery_threshold and graph.has(k)}
    planned: list[str] = []
    remaining = set(weak)
    while remaining:
        pickable = [
            k for k in remaining
            if all(p not in weak or p in planned for p in graph.prereqs(k))
        ]
        if not pickable:
            raise RouteError("no pickable weak kp: prerequisite deadlock")
        impact = {k: len(graph.descendants(k)) for k in pickable}
        gap = {k: mastery_threshold - profile.mastery.get(k, 0.0) for k in pickable}
        k = sorted(pickable, key=lambda x: (-(impact[x] * gap[x]), x))[0]
        planned.append(k)
        remaining.discard(k)

    steps: list[PlanStep] = []
    for kp_id in planned:
        kp = graph.get(kp_id)
        m = profile.mastery.get(kp_id, 0.0)
        try:
            strat = strategies.select(m, kp.grade if kp else 7)
        except RouteError:
            raise
        except Exception:
            raise RouteError(f"strategy selection failed for {kp_id}")
        steps.append(
            PlanStep(
                kp_id=kp_id,
                strategy_id=strat.id,
                rationale=f"mastery={m:.2f} < {mastery_threshold}; {strat.evidence}",
                target_mastery=max(0.85, mastery_threshold + 0.2),
            )
        )

    reviews: list[ReviewEntry] = []
    for kp in graph.kps():
        m = profile.mastery.get(kp.id, 0.0)
        if m >= mastery_threshold:
            entry = schedule(kp.id, [ReviewLog(rating=2, days_since_last=0)], today)
            reviews.append(entry)

    return LearningPlan(
        learner_id=profile.learner_id,
        steps=steps,
        reviews=reviews,
        created_at=today.isoformat(),
    )
