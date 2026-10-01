"""diagnosis —— 诊断引擎（终版重生成实现，按冻结契约 specs/frozen/diagnosis.spec.md）。

把学习者的作答序列折叠成知识点掌握度画像：逐题对所涉知识点做感知猜测率与
难度滑率的 odds 贝叶斯更新，再做恰好 2 轮先序一致性平滑（Jacobi 快照语义），
最终值一次性 round(·, 6)。除 updated_at 外同输入同输出。
"""
from __future__ import annotations

from datetime import datetime, timezone

from xuexing.types import Profile, Response

__all__ = ["aggregate_to_clusters", "diagnose", "slip_from_difficulty"]

# ---- 契约绑定的数值常量（spec §3.1 / §3.2.2 / §3.2.3 / §3.2.4）----
_PRIOR_ERROR = "prior must be in (0,1)"
_ODDS_FLOOR = 1e-4      # odds 分子/分母、衰减似然比的统一下限
_GUESS_FLOOR = 0.02     # 猜测率下限
_GUARD_STEP = 0.05      # 高猜度护栏：p_m 抬升量
_GUARD_CAP = 0.99       # 高猜度护栏：p_m 封顶
_LIFT_FACTOR = 0.6      # 上行补证系数：ch[p] = max(ch[p], 0.6 * m[d])
_DISCOUNT_BASE = 0.4    # 下行折价基数：ch[k] = min(ch[k], m[k] * (0.4 + 0.6 * m[p]))
_SMOOTH_ROUNDS = 2      # 先序平滑轮数（恰好 2，不多不少）
_UPDATED_AT_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def slip_from_difficulty(difficulty: float) -> float:
    """P(答错 | 已掌握) = clamp01(0.05 + 0.20 * difficulty)；输出不做任何舍入。"""
    return _clamp01(0.05 + 0.20 * difficulty)


def _likelihood_ratio(item) -> tuple[float, float]:
    """步骤 B2：单题似然比 (lr_c, lr_w)。与当前掌握度无关，每题只算一次。"""
    p_nm = max(item.effective_guess(), _GUESS_FLOOR)
    p_m = _clamp01(1.0 - slip_from_difficulty(item.difficulty))
    if p_m <= p_nm:  # 高猜度护栏：修正后的 p_m 同时进入 lr_c 与 lr_w
        p_m = min(p_m + _GUARD_STEP, _GUARD_CAP)
    lr_c = p_m / p_nm
    lr_w = (1.0 - p_m) / max(1.0 - p_nm, _ODDS_FLOOR)
    return lr_c, lr_w


def diagnose(responses: list[Response], bank, graph, learner_id: str = "anon",
             prior: float = 0.5) -> Profile:
    """把作答序列折叠成 Profile（spec §3.2，步骤 A–D 全部为绑定条款）。"""
    # ---- 步骤 A：校验先于任何其他工作（空 responses 也必须抛）----
    if not (0.0 < prior < 1.0):
        raise ValueError(_PRIOR_ERROR)

    kps = list(graph.kps())
    ids = [kp.id for kp in kps]
    mastery: dict[str, float] = {kp_id: prior for kp_id in ids}
    evidence: dict[str, int] = {kp_id: 0 for kp_id in ids}

    # ---- 步骤 B：逐题更新（按 responses 列表顺序逐条执行）----
    for r in responses:
        item = bank.get(r.item_id)
        if item is None:  # B1 题库中不存在：整条跳过
            continue
        lr_c, lr_w = _likelihood_ratio(item)
        # B3 按声明顺序，可含重复 id（重复按出现次数分别处理）
        for idx, kp_id in enumerate(item.kps):
            if not graph.has(kp_id):  # 图外知识点：仅跳过该知识点
                continue
            w = 1.0 if idx == 0 else 0.5
            lr = lr_c if r.correct else lr_w
            lr_eff = lr ** w if lr >= 1.0 else max(lr ** w, _ODDS_FLOOR)
            odds = (max(mastery[kp_id], _ODDS_FLOOR)
                    / max(1.0 - mastery[kp_id], _ODDS_FLOOR))
            odds *= lr_eff
            mastery[kp_id] = _clamp01(odds / (1.0 + odds))
            evidence[kp_id] += 1

    # ---- 步骤 C：先序一致性平滑（恰好 2 轮；读快照 m、写副本 ch，轮内顺序无关）----
    m = mastery
    for _ in range(_SMOOTH_ROUNDS):
        ch = dict(m)
        # C1 上行补证：有证据后代把零证据直接前序抬到 0.6 * m[d]（多后代取 max）
        for kp in kps:
            if evidence[kp.id] > 0:
                lift = _LIFT_FACTOR * m[kp.id]
                for p in graph.prereqs(kp.id):
                    if evidence[p] == 0:
                        ch[p] = max(ch[p], lift)
        # C2 下行折价：有证据前序按 m[k] * (0.4 + 0.6 * m[p]) 逐前序 min（逐轮复利）
        for kp in kps:
            if evidence[kp.id] > 0:
                mk = m[kp.id]
                for p in graph.prereqs(kp.id):
                    if evidence[p] > 0:
                        ch[kp.id] = min(ch[kp.id], mk * (_DISCOUNT_BASE + _LIFT_FACTOR * m[p]))
        m = ch

    # ---- 步骤 D：输出构造（仅在最终值上一次性 round；键序随 graph.kps()）----
    return Profile(
        learner_id=learner_id,
        mastery={kp_id: round(m[kp_id], 6) for kp_id in ids},
        evidence={kp_id: evidence[kp_id] for kp_id in ids},
        updated_at=datetime.now(timezone.utc).strftime(_UPDATED_AT_FMT),
    )


def aggregate_to_clusters(profile: Profile, graph) -> dict[str, float]:
    """按知识点的 cluster 字段求算术平均（缺失按 0.0），键按标签升序。纯函数。"""
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for kp in graph.kps():  # 成员累加顺序按 graph.kps() 返回顺序
        label = kp.cluster
        totals[label] = totals.get(label, 0.0) + profile.mastery.get(kp.id, 0.0)
        counts[label] = counts.get(label, 0) + 1
    return {label: round(totals[label] / counts[label], 6) for label in sorted(totals)}
