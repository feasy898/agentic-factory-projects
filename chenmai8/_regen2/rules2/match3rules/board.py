# -*- coding: utf-8 -*-
"""盘面与结算（卡面 §2/§4/§5）：fillNoMatches / generate / placeJelly / resolve / doReshuffle。

记法约定（与冻结 eval 一致，可执行验收物）：
- match_mask / jelly / cleared / 重力位移用 (row, col)（= 扁平 idx = row*cols + col 的行优先序）；
  卡面 §4/§12 用扁平 idx 表述同一序（idx = y*cols + x，y=row、x=col），两者逐值可互转。
- steps[] 键名按冻结 eval 用 "type"（卡面记作 t）。
- cleared 按首次清除顺序逐波追加。注意：卡面 §4"全程去重并集"与冻结 eval 的
  len(cleared)==9（跨波不去重）相抵，按冻结 eval 实现不去重；§12-D 的去重投影
  [0,1,5,6,10,11,2] 与本实现逐值一致（gate 算例 D 复核）。
- fall 步：冻结 eval pin 波形恒含 fall 步（无位移时 moves==[]）；卡面 §4"无位移整个省略"
  与之相抵，同样按冻结 eval 实现恒含 fall 步（§12-D 断言的"两波零位移"值不变）。
"""

import math

from .constants import FILL_MAX_ATTEMPTS, GENERATE_GUARD, MAX_WAVES, RESHUFFLE_GUARD, RESHUFFLE_SALT
from .jsnum import js_round
from .rng import derive_rng


def match_mask(grid):
    """§4：行、列各扫一遍，同色 run>=3 即标记（交叉处都算）。返回 {(row, col)}。"""
    rows, cols = len(grid), len(grid[0])
    mask = set()
    for r in range(rows):
        run = 1
        for c in range(1, cols + 1):
            if c < cols and grid[r][c] == grid[r][c - 1]:
                run += 1
            else:
                if run >= 3:
                    for k in range(c - run, c):
                        mask.add((r, k))
                run = 1
    for c in range(cols):
        run = 1
        for r in range(1, rows + 1):
            if r < rows and grid[r][c] == grid[r - 1][c]:
                run += 1
            else:
                if run >= 3:
                    for k in range(r - run, r):
                        mask.add((k, c))
                run = 1
    return mask


def fill_no_matches(cols, rows, colors, rng):
    """§2：行优先逐格取 floor(rng()*colors)；若与左侧两格或上方两格同色则重抽
    （每格至多 FILL_MAX_ATTEMPTS 次尝试，超限接受最后一次取值）。"""
    g = [[0] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            v = 0
            for _ in range(FILL_MAX_ATTEMPTS):
                v = math.floor(rng() * colors)
                if (c >= 2 and g[r][c - 1] == v and g[r][c - 2] == v) or \
                   (r >= 2 and g[r - 1][c] == v and g[r - 2][c] == v):
                    continue  # 成 run，重抽
                break
            g[r][c] = v
    return g


def place_jelly(cols, rows, count, rng):
    """§2 placeJelly：Fisher-Yates 洗牌 [0..cols*rows)（同一 rng 流），取前 count 格为果冻。

    方向（回炉钉死）：for i = total-1; i > 0; i--（自 n-1 降至 1 降序），
    j = floor(rng()*(i+1))，swap(order[i], order[j])；首个抽号来自 i = total-1。
    索引→格映射（回炉钉死）：行优先，(row, col) = (idx // cols, idx % cols)。
    """
    total = cols * rows
    order = list(range(total))
    for i in range(total - 1, 0, -1):
        j = math.floor(rng() * (i + 1))
        order[i], order[j] = order[j], order[i]
    return {(idx // cols, idx % cols) for idx in order[:max(0, min(count, total))]}


def score_mode_jelly_count(cols, rows):
    """§2：min(cols*rows, max(6, round(cols*rows*0.25)))，round = JS Math.round（.5 向上）。"""
    return min(cols * rows, max(6, js_round(cols * rows * 0.25)))


def jelly_count(goal_type, goal_count, cols, rows):
    """§2：clear-jelly = goalCount（钳到格数，冻结 eval pin）；score = score_mode_jelly_count。"""
    if goal_type == "score":
        return score_mode_jelly_count(cols, rows)
    return max(0, min(cols * rows, goal_count))


def generate(cols, rows, colors, jelly_cnt, rng):
    """§2：fillNoMatches -> 无任何可行步则整体重来（guard<=GENERATE_GUARD）-> 摆果冻。

    生成期 64 次重试的流消耗方式（回炉钉死）：mulberry32(meta.seed) 只构造一次并持有，
    每次重试的 fillNoMatches（含逐格重抽）+ hasAnyMove 守卫重盘 + placeJelly 顺序消耗
    同一主流，不重置、不换流。
    """
    from .solver import has_any_move  # 延迟导入防循环依赖（solver 依赖本模块）

    g = None
    for _ in range(GENERATE_GUARD):
        g = fill_no_matches(cols, rows, colors, rng)
        if has_any_move(g):
            break
    jelly = place_jelly(cols, rows, jelly_cnt, rng)
    return g, jelly


def reshuffle(cols, rows, colors, rng):
    """§2 死局重排核：重新 fillNoMatches + hasAnyMove 守卫（guard<=RESHUFFLE_GUARD）。"""
    from .solver import has_any_move  # 延迟导入防循环依赖（solver 依赖本模块）

    g = None
    for _ in range(RESHUFFLE_GUARD):
        g = fill_no_matches(cols, rows, colors, rng)
        if has_any_move(g):
            break
    return g


def do_reshuffle(state):
    """§2/§5/§7：死局自动重排——保留果冻、不耗步。

    流 = deriveRng(seed, 0x5117 ^ k)；k = moves - movesLeft + 1（回炉钉死：重排发生时的
    k = 即将进行的玩家交换序号；重排不耗步、同一 k 在重排后仍用于下一步补位流）。
    """
    k = state.moves - state.moves_left + 1
    g = reshuffle(state.cols, state.rows, state.colors,
                  derive_rng(state.seed, RESHUFFLE_SALT ^ k))
    state.grid = g
    return g


class ResolveResult:
    """§4：ResolveResult = {steps[], cleared[], cascades, score, finalGrid}。"""

    def __init__(self, steps, cleared, cascades, score, final_grid):
        self.steps = steps
        self.cleared = cleared
        self.cascades = cascades
        self.score = score
        self.finalGrid = final_grid

    def to_dict(self):
        return {
            "steps": [dict(s) for s in self.steps],
            "cleared": [list(c) for c in self.cleared],
            "cascades": self.cascades,
            "score": self.score,
            "finalGrid": [row[:] for row in self.finalGrid],
        }

    def __getitem__(self, key):
        """键访问与属性访问等价（冻结 eval 对 try_swap 结果用 r["result"]["finalGrid"] 取值）。"""
        if key in ("steps", "cleared", "cascades", "score", "finalGrid"):
            return getattr(self, key)
        raise KeyError(key)


def resolve(grid, colors, rng):
    """§4：波次循环（至多 MAX_WAVES 波，防死循环上限）match -> 重力 -> 补位，无消除即停。

    - match：matchMask 本波被清格，升序记录；score += cells.length * 10 * w。
    - 重力：每列自底向上压实被清格，记录 {from,to} 位移；顶部空位先置 -1。
    - 补位：列优先（x 外层）、每列自上而下（y 内层）扫描 -1 格，逐格当场
      floor(rng()*colors) 出子（rng 消耗顺序 = 扫描顺序，补位流可复现的关键）。
    """
    g = [row[:] for row in grid]
    rows, cols = len(g), len(g[0])
    steps, cleared = [], []
    cascades = 0
    score = 0
    for wave in range(1, MAX_WAVES + 1):
        mask = match_mask(g)
        if not mask:
            break
        cascades = wave
        cells = sorted(mask)  # (row, col) 行优先 = 扁平 idx 升序
        gained = len(cells) * 10 * wave
        score += gained
        steps.append({"type": "match", "cells": [[r, c] for (r, c) in cells],
                      "score": gained, "wave": wave})
        cleared.extend([r, c] for (r, c) in cells)
        for (r, c) in cells:
            g[r][c] = None
        # 重力：每列自底向上压实
        moves = []
        for c in range(cols):
            write = rows - 1
            for r in range(rows - 1, -1, -1):
                if g[r][c] is not None:
                    if r != write:
                        g[write][c] = g[r][c]
                        g[r][c] = None
                        moves.append({"from": [r, c], "to": [write, c]})
                    write -= 1
            for r in range(write, -1, -1):  # 顶部空位先置 -1
                g[r][c] = -1
        steps.append({"type": "fall", "moves": moves})
        # 补位：列优先、每列自上而下
        spawn_cells, spawn_pieces = [], []
        for c in range(cols):
            for r in range(rows):
                if g[r][c] == -1:
                    p = math.floor(rng() * colors)
                    g[r][c] = p
                    spawn_cells.append([r, c])
                    spawn_pieces.append(p)
        steps.append({"type": "spawn", "cells": spawn_cells, "pieces": spawn_pieces})
    return ResolveResult(steps, cleared, cascades, score, g)
