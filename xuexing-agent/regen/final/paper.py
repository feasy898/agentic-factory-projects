"""paper —— 静态组卷与 CAT 式自适应选题（重生成正式版）。

唯一权威契约：specs/frozen/paper.spec.md（定稿 v2）。
纯计算模块：无文件/网络 IO，不判分、不更新掌握度，跨调用无状态（I17）。
选题与预测完全确定（I15）；组卷唯一随机源是 seed 驱动的单个 random.Random 实例，
按规格 §3.2/I18 的规范性过程使用（排名序池进入 shuffle）。

鸭子类型参数表面（规格 §2，禁止 import 其所在模块）：
- bank: items() -> 题目列表（id 升序）; by_kp(kp_id, primary_only=True) -> 题目列表（id 升序）
- graph: has(kp_id) -> bool; get(kp_id) -> 带 .name 的对象或 None
- Item 只用 id / difficulty / kps / effective_guess()；Profile 只用 mastery
"""
from __future__ import annotations

import random

from xuexing.types import Paper, Profile

__all__ = ["PaperError", "generate_paper", "predicted_correct", "select_next_item"]

# 选题并列判定容差（规格 §3.4 步骤 4 / I12，冻结值，不得改动）
_TIE_TOL = 1e-12


class PaperError(ValueError):
    """paper 模块所有校验失败的异常类型。"""


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def predicted_correct(
    profile: Profile,
    item_difficulty: float,
    primary_mastery: float,
    guess: float,
) -> float:
    """预测答对概率（I10，公式冻结）。

    p = m * (1 - slip) + (1 - m) * guess，其中 slip = clamp01(0.05 + 0.20 * difficulty)。
    profile 仅为签名兼容保留，不参与计算；纯函数，无随机、无时间、无副作用（I15）。
    """
    slip = _clamp01(0.05 + 0.20 * item_difficulty)
    return primary_mastery * (1.0 - slip) + (1.0 - primary_mastery) * guess


def generate_paper(
    bank,
    graph,
    blueprint: dict[str, int],
    seed: int,
    title: str = "诊断卷",
    difficulty_target: float = 0.5,
    paper_id: str = "",
) -> Paper:
    """按 {知识点 id: 题数} 蓝图组装静态诊断卷（规格 §3.2 / I18，过程冻结）。

    前置校验顺序 I1→I2→I3→I4，任何一条失败抛 PaperError；库存充足性（I5）在逐节
    组装到该节时、随机抽取之前检查。整个组装共用一个 random.Random(seed) 实例；
    每节候选按 (abs(难度-目标), id) 排名，池 = 排名序前 2n 道，保持排名顺序进入
    shuffle，取洗牌后前 n 道按题目 id 升序作为该节 item_ids。

    副作用：无 —— 不修改 bank、graph、输入 blueprint（输出的 blueprint 是等值副本）。
    """
    # I1：空蓝图最先检查，优先于其他一切校验
    if not blueprint:
        raise PaperError("empty blueprint")
    # I2：蓝图引用的 kp 必须存在于图中
    for kp_id in blueprint:
        if not graph.has(kp_id):
            raise PaperError(f"unknown knowledge point: {kp_id}")
    # I3：蓝图计数必须为正
    for kp_id, n in blueprint.items():
        if n <= 0:
            raise PaperError(f"non-positive count for {kp_id}: {n}")
    # I4：难度目标必须在 [0, 1]
    if not 0.0 <= difficulty_target <= 1.0:
        raise PaperError(f"difficulty_target out of range: {difficulty_target}")

    rng = random.Random(seed)
    sections: list[dict] = []
    item_ids: list[str] = []
    for kp_id in sorted(blueprint):  # 节序 = 知识点 id 升序
        n = blueprint[kp_id]
        # I5：库存检查在该节任何随机抽取之前
        candidates = bank.by_kp(kp_id, primary_only=True)
        if len(candidates) < n:
            raise PaperError(f"not enough items for {kp_id}: need {n}, have {len(candidates)}")
        ranked = sorted(candidates, key=lambda it: (abs(it.difficulty - difficulty_target), it.id))
        pool = ranked[: max(n * 2, n)]  # 排名序池，构造时不得重排
        rng.shuffle(pool)  # 共享同一随机流
        picked_ids = [it.id for it in sorted(pool[:n], key=lambda it: it.id)]
        sections.append(
            {
                "kp_id": kp_id,
                "kp_name": graph.get(kp_id).name,
                "item_ids": list(picked_ids),
            }
        )
        item_ids.extend(picked_ids)

    if not paper_id:
        # 规格 §5：seed+蓝图派生的默认 id，同进程稳定，不保证跨进程相同
        paper_id = f"paper-{seed}-{abs(hash(tuple(sorted(blueprint.items())))) % 100000}"

    return Paper(
        paper_id=paper_id,
        title=title,
        blueprint=dict(blueprint),  # 等值副本，不与输入别名共享
        item_ids=item_ids,
        sections=sections,
    )


def select_next_item(
    bank,
    profile: Profile,
    administered: set[str],
    scope: set[str],
    attempt_counts: dict[str, int],
    per_kp_cap: int = 3,
    difficulty_band: tuple[float, float] = (0.2, 0.8),
) -> str | None:
    """CAT 式选题：约束内选预测答对概率最接近 0.5 的题（规格 §3.4 / I9/I12）。

    合格 = 未做过，且 kps 非空且主知识点在 scope 内（空 scope 排除一切题），
    且主知识点计数 < per_kp_cap（缺省 0），且难度在闭区间 band 内。
    选题算法按规格冻结：id 升序流式遍历，仅当 score > best + 1e-12 才替换；
    分差 ∈ (0, 1e-12] 视为并列并保留先出现（更小 id）者。无合格题返回 None。

    副作用：无 —— 不修改 administered / attempt_counts，进度由调用方维护（I17）。
    """
    # I16：难度带校验在任何搜索之前，与题库内容无关
    if not 0.0 <= difficulty_band[0] <= difficulty_band[1] <= 1.0:
        raise PaperError(f"invalid difficulty band: {difficulty_band}")

    best_id: str | None = None
    best_score = -2.0
    for item in bank.items():  # 按 id 升序遍历
        if item.id in administered:
            continue
        if not item.kps or item.kps[0] not in scope:
            continue
        if attempt_counts.get(item.kps[0], 0) >= per_kp_cap:
            continue
        if not difficulty_band[0] <= item.difficulty <= difficulty_band[1]:
            continue
        p = predicted_correct(
            profile,
            item.difficulty,
            profile.mastery.get(item.kps[0], 0.5),
            item.effective_guess(),
        )
        score = -abs(p - 0.5)
        if score > best_score + _TIE_TOL or (
            abs(score - best_score) <= _TIE_TOL and (best_id is None or item.id < best_id)
        ):
            best_id, best_score = item.id, score
    return best_id
