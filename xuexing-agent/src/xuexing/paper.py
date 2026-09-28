"""出卷引擎：静态诊断卷组装（blueprint 驱动）+ 自适应逐题选题（CAT 式）。"""
from __future__ import annotations

import random
from datetime import datetime, timezone

from .diagnosis import slip_from_difficulty
from .itembank import ItemBank
from .kpgraph import KPGraph
from .types import Paper, Profile


class PaperError(ValueError):
    pass


def generate_paper(
    bank: ItemBank,
    graph: KPGraph,
    blueprint: dict[str, int],
    seed: int,
    title: str = "诊断卷",
    difficulty_target: float = 0.5,
    paper_id: str = "",
) -> Paper:
    """按 {知识点: 题数} 蓝图组装静态卷。确定性：同输入+同 seed 恒等输出。"""
    if not blueprint:
        raise PaperError("empty blueprint")
    for kp_id, n in blueprint.items():
        if not graph.has(kp_id):
            raise PaperError(f"blueprint references unknown kp {kp_id}")
        if n <= 0:
            raise PaperError(f"blueprint count must be positive for {kp_id}")
        if not 0.0 <= difficulty_target <= 1.0:
            raise PaperError("difficulty_target out of [0,1]")

    rng = random.Random(seed)
    chosen: list[str] = []
    sections: list[dict] = []
    for kp_id in sorted(blueprint):
        n = blueprint[kp_id]
        candidates = bank.by_kp(kp_id, primary_only=True)
        if len(candidates) < n:
            raise PaperError(f"not enough items for {kp_id}: need {n}, have {len(candidates)}")
        ranked = sorted(candidates, key=lambda i: (abs(i.difficulty - difficulty_target), i.id))
        # 在分数相近的前 2n 道里随机抽 n 道，避免每份卷子完全一样
        pool = ranked[: max(n * 2, n)]
        rng.shuffle(pool)
        picked = sorted(pool[:n], key=lambda i: i.id)
        chosen.extend(i.id for i in picked)
        sections.append(
            {
                "kp_id": kp_id,
                "kp_name": graph.get(kp_id).name if graph.get(kp_id) else kp_id,
                "item_ids": [i.id for i in picked],
            }
        )
    pid = paper_id or f"paper-{seed}-{abs(hash(tuple(sorted(blueprint.items())))) % 100000}"
    return Paper(paper_id=pid, title=title, blueprint=dict(blueprint), item_ids=chosen, sections=sections)


def predicted_correct(profile: Profile, item_difficulty: float, primary_mastery: float, guess: float) -> float:
    """给定主知识点掌握度，预测该题答对概率。"""
    s = slip_from_difficulty(item_difficulty)
    p_m = 1.0 - s
    return primary_mastery * p_m + (1.0 - primary_mastery) * guess


def select_next_item(
    bank: ItemBank,
    profile: Profile,
    administered: set[str],
    scope: set[str],
    attempt_counts: dict[str, int],
    per_kp_cap: int = 3,
    difficulty_band: tuple[float, float] = (0.2, 0.8),
) -> str | None:
    """CAT 式选题：在约束内选“预测对半开”的题（信息量最大代理指标）。

    约束：未做过、主知识点在 scope 内、该知识点未超 per_kp_cap。
    确定性：信息量并列时取 id 最小者。无可选题返回 None。
    """
    if not 0.0 <= difficulty_band[0] <= difficulty_band[1] <= 1.0:
        raise PaperError("bad difficulty_band")
    best_id: str | None = None
    best_score = -2.0
    for item in bank.items():
        if item.id in administered:
            continue
        if not item.kps or item.kps[0] not in scope:
            continue
        if attempt_counts.get(item.kps[0], 0) >= per_kp_cap:
            continue
        if not difficulty_band[0] <= item.difficulty <= difficulty_band[1]:
            continue
        m = profile.mastery.get(item.kps[0], 0.5)
        p = predicted_correct(profile, item.difficulty, m, item.effective_guess())
        score = -abs(p - 0.5)
        if score > best_score + 1e-12 or (abs(score - best_score) <= 1e-12 and (best_id is None or item.id < best_id)):
            best_score = score
            best_id = item.id
    return best_id
