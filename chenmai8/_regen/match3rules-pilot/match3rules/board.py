# -*- coding: utf-8 -*-
"""盘面生成与消除/下落/补位/连消——SPEC.md §2 + §4 的确定性实现。

网格表示：grid[row][col]，row 0 = 顶行，取值 0..colors-1（-1 为重力期空位占位）。
果冻表示：frozenset[(row, col)]。

随机流（卡 §7）：本模块全部 rng 参数都是"无参 callable -> float [0,1)"，
主流由调用方以 mulberry32(meta.seed) 构造后传入；补位流由 game 层以
deriveRng(seed, SPAWN_SALT ^ k) 构造传入 resolve。
"""

from dataclasses import dataclass
from typing import Callable, List, Set, FrozenSet, Tuple

from .constants import (
    FILL_MAX_ATTEMPTS,
    GENERATE_GUARD,
    MAX_WAVES,
    RESHUFFLE_GUARD,
    SCORE_PER_CELL_PER_WAVE,
)
from .spec import score_mode_jelly_count  # noqa: F401 (re-export)

Rng = Callable[[], float]


@dataclass(frozen=True)
class Move:
    """一次交换：from (r1,c1) 向 dir 方向邻格 (r2,c2)。allMoves 只扫 right/down。"""

    r1: int
    c1: int
    r2: int
    c2: int
    dir: str  # "right" | "down"


def swapped_grid(grid: List[List[int]], mv: Move) -> List[List[int]]:
    g = [row[:] for row in grid]
    g[mv.r1][mv.c1], g[mv.r2][mv.c2] = g[mv.r2][mv.c2], g[mv.r1][mv.c1]
    return g


def all_moves(grid: List[List[int]]) -> List[Move]:
    """§8：枚举全部可行交换，只扫 right/down 两个方向去重。"""
    rows, cols = len(grid), len(grid[0])
    moves: List[Move] = []
    for r in range(rows):
        for c in range(cols):
            for dr, dc, d in ((0, 1, "right"), (1, 0, "down")):
                r2, c2 = r + dr, c + dc
                if r2 >= rows or c2 >= cols:
                    continue
                mv = Move(r, c, r2, c2, d)
                if match_mask(swapped_grid(grid, mv)):
                    moves.append(mv)
    return moves


def has_any_move(grid: List[List[int]]) -> bool:
    return bool(all_moves(grid))


# ---------------------------------------------------------------------------
# §2 盘面生成
# ---------------------------------------------------------------------------

def fill_no_matches(cols: int, rows: int, colors: int, rng: Rng) -> List[List[int]]:
    """行优先逐格取 floor(rng()*colors)；与左侧两格或上方两格同色则重抽；
    每格至多 32 次尝试，超限后接受最后一次取值。"""
    g = [[0] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            v = 0
            for _ in range(FILL_MAX_ATTEMPTS):
                v = int(rng() * colors)
                left2 = c >= 2 and g[r][c - 1] == v and g[r][c - 2] == v
                up2 = r >= 2 and g[r - 1][c] == v and g[r - 2][c] == v
                if not (left2 or up2):
                    break
            g[r][c] = v
    return g


def place_jelly(cols: int, rows: int, count: int, rng: Rng) -> FrozenSet[Tuple[int, int]]:
    """Fisher-Yates（自 n-1 降至 1，j=floor(rng()*(i+1))）洗牌 [0..cols*rows)，
    取前 count 个索引为果冻；索引 -> (row, col) = (idx // cols, idx % cols)。"""
    n = cols * rows
    a = list(range(n))
    for i in range(n - 1, 0, -1):
        j = int(rng() * (i + 1))
        a[i], a[j] = a[j], a[i]
    take = min(count, n)
    return frozenset((idx // cols, idx % cols) for idx in a[:take])


def jelly_count(goal_type: str, goal_count: int, cols: int, rows: int) -> int:
    """clear-jelly 模式 = goalCount；score 模式 = min(cols*rows, max(6, round(n*0.25)))。"""
    if goal_type == "score":
        return score_mode_jelly_count(cols, rows)
    return min(goal_count, cols * rows)


def generate(cols: int, rows: int, colors: int, jelly_count_value: int, rng: Rng):
    """fillNoMatches 后若无任何可行步则整体重来（guard <= 200），然后摆果冻。
    同一主流被顺序消耗，故重试盘面各异且全程确定。"""
    grid = None
    for _ in range(GENERATE_GUARD):
        grid = fill_no_matches(cols, rows, colors, rng)
        if has_any_move(grid):
            break
    jelly = place_jelly(cols, rows, jelly_count_value, rng)
    return grid, jelly


def reshuffle(grid: List[List[int]], colors: int, rng: Rng) -> List[List[int]]:
    """死局重排（卡 §2/§5）：保留果冻（由调用方持有），重新 fillNoMatches +
    hasAnyMove 守卫（guard <= 200）。"""
    cols, rows = len(grid[0]), len(grid)
    new_grid = grid
    for _ in range(RESHUFFLE_GUARD):
        new_grid = fill_no_matches(cols, rows, colors, rng)
        if has_any_move(new_grid):
            break
    return new_grid


# ---------------------------------------------------------------------------
# §4 消除 / 下落 / 补位 / 连消
# ---------------------------------------------------------------------------

def match_mask(grid: List[List[int]]) -> Set[Tuple[int, int]]:
    """行、列各扫一遍，同色 run >= 3 即标记（交叉处都算）。"""
    rows, cols = len(grid), len(grid[0])
    mask: Set[Tuple[int, int]] = set()

    for r in range(rows):
        c = 0
        while c < cols:
            v = grid[r][c]
            if v < 0:
                c += 1
                continue
            c2 = c
            while c2 + 1 < cols and grid[r][c2 + 1] == v:
                c2 += 1
            if c2 - c + 1 >= 3:
                for cc in range(c, c2 + 1):
                    mask.add((r, cc))
            c = c2 + 1

    for c in range(cols):
        r = 0
        while r < rows:
            v = grid[r][c]
            if v < 0:
                r += 1
                continue
            r2 = r
            while r2 + 1 < rows and grid[r2 + 1][c] == v:
                r2 += 1
            if r2 - r + 1 >= 3:
                for rr in range(r, r2 + 1):
                    mask.add((rr, c))
            r = r2 + 1

    return mask


@dataclass
class ResolveResult:
    """卡 §4：ResolveResult = { steps[], cleared[], cascades, score, finalGrid }。
    steps 元素为本实现定义的最小视图回放协议（卡未定 schema，见 notes）：
      {"type":"match","wave":w,"cells":[[r,c]..],"score":10*w*n}
      {"type":"fall","moves":[{"from":[r,c],"to":[r,c]}..]}
      {"type":"spawn","cells":[[r,c]..]}   # 顺序 = 补位流消耗顺序（列优先、每列自上而下）
    """

    steps: list
    cleared: list
    cascades: int
    score: int
    finalGrid: list

    def to_dict(self) -> dict:
        return {
            "steps": self.steps,
            "cleared": self.cleared,
            "cascades": self.cascades,
            "score": self.score,
            "finalGrid": self.finalGrid,
        }


def resolve(grid: List[List[int]], colors: int, spawn_rands: Rng) -> ResolveResult:
    """波次循环（至多 64 波）：match -> 重力 -> 补位，无消除即停。

    补位：列优先、每列自上而下扫描 -1 格，逐格 floor(rng()*colors)；
    rng 消耗顺序 = 扫描顺序（补位流可复现的关键）。
    """
    g = [row[:] for row in grid]
    rows, cols = len(g), len(g[0])
    steps: List[dict] = []
    cleared_all: List[list] = []
    score = 0
    wave = 0

    while wave < MAX_WAVES:
        mask = match_mask(g)
        if not mask:
            break
        wave += 1
        cells = sorted(mask)
        wave_score = SCORE_PER_CELL_PER_WAVE * wave * len(cells)
        score += wave_score
        steps.append({
            "type": "match",
            "wave": wave,
            "cells": [[r, c] for (r, c) in cells],
            "score": wave_score,
        })
        cleared_all.extend([[r, c] for (r, c) in cells])
        for (r, c) in cells:
            g[r][c] = -1

        # 重力：每列自底向上压实被清格，记录 {from,to} 位移；顶部空位置 -1
        falls = []
        for c in range(cols):
            new_r = rows - 1
            for r in range(rows - 1, -1, -1):
                if g[r][c] == -1:
                    continue
                if r != new_r:
                    falls.append({"from": [r, c], "to": [new_r, c]})
                    g[new_r][c] = g[r][c]
                    g[r][c] = -1
                new_r -= 1
        steps.append({"type": "fall", "moves": falls})

        # 补位：列优先、每列自上而下
        spawned = []
        for c in range(cols):
            for r in range(rows):
                if g[r][c] == -1:
                    g[r][c] = int(spawn_rands() * colors)
                    spawned.append([r, c])
        steps.append({"type": "spawn", "cells": spawned})

    return ResolveResult(
        steps=steps,
        cleared=cleared_all,
        cascades=wave,
        score=score,
        finalGrid=g,
    )
