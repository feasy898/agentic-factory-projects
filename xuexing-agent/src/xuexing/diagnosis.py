"""诊断引擎：作答序列 -> 知识点掌握度画像。

参考实现：Beta 式逐题贝叶斯更新（考虑猜测率与难度滑率）+ 先序一致性平滑。
行为契约（而非算法）由 tests/contract 冻结：单调性、猜测感知、确定性、先序一致性。
"""
from __future__ import annotations

from datetime import datetime, timezone

from .kpgraph import KPGraph
from .itembank import ItemBank
from .types import Profile, Response


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def slip_from_difficulty(difficulty: float) -> float:
    """P(答错 | 已掌握)：越难的题，掌握了也可能失误。"""
    return _clamp01(0.05 + 0.20 * difficulty)


def _odds_update(mastery: float, lr: float) -> float:
    odds = max(mastery, 1e-4) / max(1.0 - mastery, 1e-4)
    odds *= lr
    return _clamp01(odds / (1.0 + odds))


def diagnose(
    responses: list[Response],
    bank: ItemBank,
    graph: KPGraph,
    learner_id: str = "anon",
    prior: float = 0.5,
) -> Profile:
    if not 0.0 < prior < 1.0:
        raise ValueError("prior must be in (0,1)")
    mastery = {kp.id: prior for kp in graph.kps()}
    evidence = {kp.id: 0 for kp in graph.kps()}

    for r in responses:
        item = bank.get(r.item_id)
        if item is None:
            continue
        g = max(item.effective_guess(), 0.02)
        s = slip_from_difficulty(item.difficulty)
        p_m = _clamp01(1.0 - s)
        p_nm = g
        if p_m <= p_nm:
            p_m = min(p_m + 0.05, 0.99)
        lr_c = p_m / p_nm
        lr_w = (1.0 - p_m) / max(1.0 - p_nm, 1e-4)
        for idx, kp_id in enumerate(item.kps):
            if not graph.has(kp_id):
                continue
            w = 1.0 if idx == 0 else 0.5  # 主知识点权重更高
            lr = lr_c if r.correct else lr_w
            lr_eff = lr ** w if lr >= 1.0 else max(lr ** w, 1e-4)
            mastery[kp_id] = _odds_update(mastery[kp_id], lr_eff)
            evidence[kp_id] += 1

    mastery = _prereq_consistency(mastery, evidence, graph)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return Profile(
        learner_id=learner_id,
        mastery={k: round(v, 6) for k, v in mastery.items()},
        evidence=dict(evidence),
        updated_at=now,
    )


def _prereq_consistency(
    mastery: dict[str, float], evidence: dict[str, int], graph: KPGraph
) -> dict[str, float]:
    """先序一致性平滑（只对有证据的知识点生效，避免无证据链路衰减真实掌握度）：

    - 上行补证：后代有作答证据且掌握 -> 无直接证据的前序掌握度抬到 0.6*后代；
    - 下行折价：前序有作答证据且薄弱 -> 后代掌握度按比例折价；
    - 有直接作答证据的知识点：证据优先，间接传递不覆盖直接证据。
    """
    m = dict(mastery)
    order = graph.topological_order()
    for _ in range(2):
        changed = dict(m)
        for kp_id in order:  # 上行补证（只补无直接证据的前序）
            if evidence.get(kp_id, 0) == 0:
                continue
            for p in graph.prereqs(kp_id):
                if evidence.get(p, 0) == 0:
                    changed[p] = max(changed[p], 0.6 * m[kp_id])
        for kp_id in order:  # 下行折价
            if evidence.get(kp_id, 0) == 0:
                continue
            for p in graph.prereqs(kp_id):
                if evidence.get(p, 0) > 0:
                    changed[kp_id] = min(changed[kp_id], m[kp_id] * (0.4 + 0.6 * m[p]))
        m = changed
    return m


def aggregate_to_clusters(profile: Profile, graph: KPGraph) -> dict[str, float]:
    """知识点掌握度 -> 章节聚类平均。"""
    clusters: dict[str, list[float]] = {}
    for kp in graph.kps():
        clusters.setdefault(kp.cluster, []).append(profile.mastery.get(kp.id, 0.0))
    return {c: round(sum(v) / len(v), 6) for c, v in sorted(clusters.items())}
