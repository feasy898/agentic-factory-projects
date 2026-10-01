# -*- coding: utf-8 -*-
"""求解器与 hint——SPEC.md §8。

- allMoves：只扫 right/down 两个方向去重。
- bestMove：每个候选用同一补位流（deriveRng(seed, SPAWN_SALT ^ k)）完整模拟连消；
  评价值 clear-jelly：果冻*1000 + score*2 + cascades*15；score 模式：score*10 + cascades*15。
- hint 坐标系：视口 CSS 像素（画布铺满视口，世界坐标 = CSS 像素；cellCenter 四舍五入取整）；
  返回 {x, y, type}，type ∈ swap-up|swap-down|swap-left|swap-right（语义 = 从 (x,y) 格向该方向与邻格交换）。
"""

from dataclasses import dataclass
from typing import List, Optional

from .constants import (
    EVAL_CLEAR_CASCADE_WEIGHT,
    EVAL_CLEAR_JELLY_WEIGHT,
    EVAL_CLEAR_SCORE_WEIGHT,
    EVAL_SCORE_CASCADE_WEIGHT,
    EVAL_SCORE_WEIGHT,
)
from .board import Move, all_moves, match_mask, resolve, swapped_grid  # noqa: F401 (re-export)
from .jsnum import js_round
from .rng import SPAWN_SALT, derive_rng


# ---------------------------------------------------------------------------
# 评价（卡 §8 公式）
# ---------------------------------------------------------------------------

def eval_clear(jelly_cleared: int, score: int, cascades: int) -> int:
    """clear-jelly：果冻*1000 + score*2 + cascades*15。"""
    return (jelly_cleared * EVAL_CLEAR_JELLY_WEIGHT
            + score * EVAL_CLEAR_SCORE_WEIGHT
            + cascades * EVAL_CLEAR_CASCADE_WEIGHT)


def eval_score(score: int, cascades: int) -> int:
    """score 模式：score*10 + cascades*15。"""
    return score * EVAL_SCORE_WEIGHT + cascades * EVAL_SCORE_CASCADE_WEIGHT


@dataclass
class BestMove:
    move: Move
    value: int
    win: bool
    progress: int          # 该候选结算后的进度（clear-jelly: 果冻数 / score: 分数）
    jelly_cleared: int
    result: object         # ResolveResult


def best_move(grid, colors, seed, k, goal_type, goal_count, jelly=frozenset()) -> Optional[BestMove]:
    """枚举 allMoves，每个候选用同一补位流 deriveRng(seed, SPAWN_SALT ^ k)
    完整模拟连消；严格更大才替换（并列取 allMoves 顺序靠前者——卡未定，见 notes）。
    """
    best: Optional[BestMove] = None
    for mv in all_moves(grid):
        res = resolve(swapped_grid(grid, mv), colors, derive_rng(seed, SPAWN_SALT ^ k))
        # 果冻按去重格数计（果冻只清一次：补位新棋子不带果冻，同格多波重复消除不重复计）
        jelly_cleared = len({(rc[0], rc[1]) for rc in res.cleared} & set(jelly))
        if goal_type == "score":
            value = eval_score(res.score, res.cascades)
            progress = res.score
        else:
            value = eval_clear(jelly_cleared, res.score, res.cascades)
            progress = jelly_cleared
        win = progress >= goal_count
        if best is None or value > best.value:
            best = BestMove(mv, value, win, progress, jelly_cleared, res)
    return best


# ---------------------------------------------------------------------------
# hint 坐标（视口 CSS 像素）
# ---------------------------------------------------------------------------

@dataclass
class Layout:
    """卡 §8 只规定坐标系（画布铺满视口、世界坐标 = CSS 像素、cellCenter 四舍五入取整），
    未规定棋盘在视口内的布局数学（格宽/原点）；故布局为显式参数，见 notes。"""

    cell: float   # 单格边长（CSS 像素）
    ox: float = 0.0  # 棋盘原点（第 0 格左上角）x
    oy: float = 0.0  # 棋盘原点 y


def cell_center(layout: Layout, c: int, r: int):
    """cellCenter 四舍五入取整（JS Math.round 语义）。"""
    return (
        js_round(layout.ox + (c + 0.5) * layout.cell),
        js_round(layout.oy + (r + 0.5) * layout.cell),
    )


def project_hint(mv: Move, layout: Layout) -> dict:
    """{x, y, type}，type = swap-<方向>，语义 = 从 (x,y) 格向该方向与邻格交换。"""
    x, y = cell_center(layout, mv.c1, mv.r1)
    return {"x": x, "y": y, "type": "swap-" + mv.dir}
