"""学习路线规划器（终版重生成，按冻结契约 specs/frozen/route.spec.md 实现）。

把掌握度画像映射为学习计划：薄弱知识点排成拓扑有效、按"影响×缺口"优先的
步骤序列；已达标知识点生成间隔复习日程。纯函数式：不读时钟、无随机、无 IO。

单文件约束：仅标准库 + xuexing.types 绝对导入；对 graph/strategies 只经入参
对象调用其公开方法（has/prereqs/descendants/kps/get、select）。复习日程按
I10 的调度器等价数值内联（单条 rating=2 日志 → interval_days=2、ease=2.5、
due=today+2 天），不 import scheduler。bank 仅为签名占位（I15），session_size
仅参与入口校验。
"""
from __future__ import annotations

import datetime

from xuexing.types import LearningPlan, PlanStep, Profile, ReviewEntry

__all__ = ["RouteError", "build_plan"]


class RouteError(ValueError):
    """route 模块唯一异常类型。"""


def build_plan(
    profile: Profile,
    bank,
    graph,
    strategies,
    today: datetime.date,
    mastery_threshold: float = 0.65,
    session_size: int = 4,
) -> LearningPlan:
    """由画像生成学习计划。

    mastery_threshold 须在开区间 (0,1)，session_size 须 >=1；违反抛 RouteError，
    两参同时非法先报 mastery_threshold。
    """
    # ---- 参数校验（I12：入口 fail-fast；非数值类型让比较抛原生 TypeError，不包装）----
    if not 0 < mastery_threshold < 1:
        raise RouteError("mastery_threshold out of (0,1)")
    if session_size < 1:
        raise RouteError("session_size must be >=1")

    # 弱点集：mastery 低于阈值的图内键（图外键过滤，I1 细化）；恰等于阈值视为达标。
    weak = {
        kp
        for kp, m in profile.mastery.items()
        if m < mastery_threshold and graph.has(kp)
    }
    target_mastery = max(0.85, mastery_threshold + 0.2)

    # ---- 第一阶段：贪心全序（I3/I4/I5）----
    order: list[str] = []
    placed: set[str] = set()
    remaining = set(weak)
    while remaining:
        # 只有"弱且未排入"的声明 prereq 阻塞；门控仅依据 graph.prereqs 声明，不要求边存在。
        pickable = [
            kp
            for kp in remaining
            if all(p not in weak or p in placed for p in graph.prereqs(kp))
        ]
        if not pickable:
            raise RouteError("no pickable weak kp: prerequisite deadlock")
        # impact×gap 最大者；平局按 kp_id 升序（key 含唯一 id，set 迭代序不影响输出）。
        best = min(
            pickable,
            key=lambda kp: (
                -(
                    len(graph.descendants(kp))
                    * (mastery_threshold - profile.mastery.get(kp, 0.0))
                ),
                kp,
            ),
        )
        order.append(best)
        placed.add(best)
        remaining.remove(best)

    # ---- 第二阶段：步骤构造（I6/I7/I8；包装范围仅限 strategies.select）----
    steps: list[PlanStep] = []
    for kp_id in order:
        m = profile.mastery[kp_id]
        grade = graph.get(kp_id).grade
        try:
            strategy = strategies.select(m, grade)
        except RouteError:
            raise
        except Exception:
            # 裸 raise：隐式链（__context__=原异常、__cause__ 保持 None），不得用 raise ... from。
            raise RouteError(f"strategy selection failed for {kp_id}")
        steps.append(
            PlanStep(
                kp_id=kp_id,
                strategy_id=strategy.id,
                rationale=f"mastery={m:.2f} < {mastery_threshold}; {strategy.evidence}",
                target_mastery=target_mastery,
            )
        )

    # ---- 复习日程（I9/I10/I11）：图内达标节点；kp_id 升序为本模块输出属性，显式排序 ----
    due = (today + datetime.timedelta(days=2)).isoformat()
    reviews = [
        ReviewEntry(kp_id=kp.id, due=due, interval_days=2, ease=2.5)
        for kp in sorted(graph.kps(), key=lambda kp: kp.id)
        if profile.mastery.get(kp.id, 0.0) >= mastery_threshold
    ]

    return LearningPlan(
        learner_id=profile.learner_id,
        steps=steps,
        reviews=reviews,
        created_at=today.isoformat(),
    )
