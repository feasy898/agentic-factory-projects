# -*- coding: utf-8 -*-
"""求解器与 hint（卡面 §8）+ 生成期可玩性模拟（卡面 §7 推论）。

- bestMove：枚举全部可行交换（allMoves 只扫 right/down 两方向去重），每个候选用同一补位流
  deriveRng(seed, SPAWN_SALT ^ k) 完整模拟连消；评价值 clear-jelly = 果冻*1000 + score*2 +
  cascades*15，score 模式 = score*10 + cascades*15。并列取优（回炉钉死）：严格更大才替换，
  并列时取 allMoves 序靠前（扫描序 = 行优先 row 外层、col 内层，dir 内层 right->down）；
  每个候选各自新建流（候选间同流、逐候选重置，保证可比）。
- hint 布局数学（回炉成文）：cellCenter(x,y) = (originX + x*cell + cell/2,
  originY + y*cell + cell/2)，出口 Math.round 取整（js_round）。
- Move 记法（与冻结 eval 一致）：Move(row1, col1, row2, col2, dir)——卡面 §12-B 的
  {x:1, y:0, dir:"down"} 与 Move(0, 1, 1, 1, "down") 是同一步（x=col、y=row）。
"""

from .board import do_reshuffle, match_mask, resolve
from .constants import (EVAL_CLEAR_CASCADE_WEIGHT, EVAL_CLEAR_JELLY_WEIGHT, EVAL_CLEAR_SCORE_WEIGHT,
                        EVAL_SCORE_CASCADE_WEIGHT, EVAL_SCORE_WEIGHT, SIMULATE_RETRY, SPAWN_SALT)
from .jsnum import js_round
from .rng import derive_rng


class Move:
    """候选交换：from (row1, col1) to (row2, col2)，dir ∈ up|down|left|right。"""

    __slots__ = ("row1", "col1", "row2", "col2", "dir")

    def __init__(self, row1, col1, row2, col2, dir):
        self.row1 = row1
        self.col1 = col1
        self.row2 = row2
        self.col2 = col2
        self.dir = dir

    def _key(self):
        return (self.row1, self.col1, self.row2, self.col2, self.dir)

    def __eq__(self, other):
        return isinstance(other, Move) and self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

    def __repr__(self):
        return "Move(%r, %r, %r, %r, %r)" % self._key()


class Layout:
    """§8 hint 布局参数化（抽离视口后可离线复算）：cell 格宽、ox/oy 棋盘原点。"""

    def __init__(self, cell, ox=0, oy=0):
        self.cell = cell
        self.ox = ox
        self.oy = oy


class BestMove:
    """bestMove 结果：move / win / progress / value / jelly_cleared / result。"""

    def __init__(self, move, win, progress, value, jelly_cleared, result):
        self.move = move
        self.win = win
        self.progress = progress
        self.value = value
        self.jelly_cleared = jelly_cleared
        self.result = result


def swapped_grid(grid, move):
    """交换 move 两格后的新盘（不改原盘）。"""
    g = [row[:] for row in grid]
    g[move.row1][move.col1], g[move.row2][move.col2] = \
        g[move.row2][move.col2], g[move.row1][move.col1]
    return g


def all_moves(grid):
    """枚举全部可行交换：只扫 right/down 两方向去重；
    扫描序 = 行优先（row 外层、col 内层），dir 内层 right->down。"""
    rows, cols = len(grid), len(grid[0])
    out = []
    for r in range(rows):
        for c in range(cols):
            for dr, dc, d in ((0, 1, "right"), (1, 0, "down")):
                r2, c2 = r + dr, c + dc
                if r2 >= rows or c2 >= cols:
                    continue
                mv = Move(r, c, r2, c2, d)
                if match_mask(swapped_grid(grid, mv)):
                    out.append(mv)
    return out


def has_any_move(grid):
    return len(all_moves(grid)) > 0


def eval_clear(jelly_cleared, score, cascades):
    """§8：clear-jelly 评价值 = 果冻*1000 + score*2 + cascades*15。"""
    return (jelly_cleared * EVAL_CLEAR_JELLY_WEIGHT + score * EVAL_CLEAR_SCORE_WEIGHT
            + cascades * EVAL_CLEAR_CASCADE_WEIGHT)


def eval_score(score, cascades):
    """§8：score 模式评价值 = score*10 + cascades*15。"""
    return score * EVAL_SCORE_WEIGHT + cascades * EVAL_SCORE_CASCADE_WEIGHT


def best_move(grid, colors, seed, k, goal_type, goal_count, jelly):
    """§8：评价值最大者；并列时 allMoves 序靠前（严格更大才替换）。"""
    jelly = set(jelly)
    best = None
    for mv in all_moves(grid):
        res = resolve(swapped_grid(grid, mv), colors, derive_rng(seed, SPAWN_SALT ^ k))
        jelly_cleared = len({tuple(c) for c in res.cleared} & jelly)
        progress = res.score if goal_type == "score" else jelly_cleared
        win = progress >= goal_count
        if goal_type == "score":
            value = eval_score(res.score, res.cascades)
        else:
            value = eval_clear(jelly_cleared, res.score, res.cascades)
        if best is None or value > best.value:  # 严格更大才替换 -> 并列取扫描序靠前
            best = BestMove(mv, win, progress, value, jelly_cleared, res)
    return best


def cell_center(layout, x, y):
    """§8：格 (x=col, y=row) 中心，Math.round 取整（js_round）。返回 (cx, cy) 整数对。"""
    cx = js_round(layout.ox + x * layout.cell + layout.cell / 2)
    cy = js_round(layout.oy + y * layout.cell + layout.cell / 2)
    return cx, cy


def project_hint(move, layout):
    """§8：hint 出口 {x, y, type}，type = swap-<dir>（语义 = 从 (x,y) 格向该方向与邻格交换）。"""
    cx, cy = cell_center(layout, move.col1, move.row1)
    return {"x": cx, "y": cy, "type": "swap-" + move.dir}


def hint(state, layout):
    """§8：playing 相位返回 bestMove 投影；null 情形——busy / ended；playing 无步
    （此时触发 doReshuffle）；教程相位无 demo。教程相位返回 tutorialDemo（= bestMove，
    无最优步时取 allMoves[0]）坐标。"""
    if state.busy or state.ended:
        return None
    if state.phase == "tutorial":
        mv = best_move(state.grid, state.colors, state.seed, k_of(state),
                       state.goal_type, state.goal_count, state.jelly)
        if mv is None:
            moves = all_moves(state.grid)
            mv = BestMove(moves[0], False, 0, 0, 0, None) if moves else None
        return project_hint(mv.move, layout) if mv is not None else None
    bm = best_move(state.grid, state.colors, state.seed, k_of(state),
                   state.goal_type, state.goal_count, state.jelly)
    if bm is None:
        do_reshuffle(state)  # playing 无步 -> 自动重排，hint 返回 null
        return None
    return project_hint(bm.move, layout)


def k_of(state):
    """§7：第 k 次玩家交换 / 第 k 步死局重排的 k = moves - movesLeft + 1。"""
    return state.moves - state.moves_left + 1


def simulate_play(state):
    """§7 推论：按 hint 同款贪心（bestMove）重放整局，流与真实游玩完全一致。

    trace 记录 reshuffle（死局重排，k = moves - movesLeft + 1）与 nearWin 回弹
    （不耗步，同一交换下次真实结算）；返回 {win, ended, moves_left, trace}。
    """
    s = state.copy()
    trace = []
    while not s.ended:
        k = k_of(s)
        bm = best_move(s.grid, s.colors, s.seed, k, s.goal_type, s.goal_count, s.jelly)
        if bm is None:
            do_reshuffle(s)
            trace.append({"act": "reshuffle", "k": k})
            if best_move(s.grid, s.colors, s.seed, k, s.goal_type, s.goal_count, s.jelly) is None:
                s.ended = True   # 防御：守卫 200 次后仍无步（概率上不会发生）
                s.win = False
            continue
        if bm.win and s.attract_near_win and not s.near_win_done:
            s.near_win_done = True  # nearWin 回弹一次，不耗步；同一交换下次真实结算
            trace.append({"act": "invalidSwap", "reason": "nearWin", "k": k,
                          "consumeMove": False})
            continue
        res = resolve(swapped_grid(s.grid, bm.move), s.colors, derive_rng(s.seed, SPAWN_SALT ^ k))
        s.grid = res.finalGrid
        s.moves_left -= 1
        entry = {"act": "resolve", "k": k, "consumeMove": True,
                 "score": res.score, "cascades": res.cascades}
        if s.goal_type == "score":
            progress = res.score
        else:
            progress = len({tuple(c) for c in res.cleared} & set(s.jelly))
        if progress >= s.goal_count:
            s.ended, s.win = True, True
            entry["outcome"] = "win"
        elif s.moves_left <= 0:
            s.ended, s.win = True, False
            entry["outcome"] = "lose"
        trace.append(entry)
    return {"win": s.win is True, "ended": s.ended, "moves_left": s.moves_left, "trace": trace}


def generate_winnable(cols, rows, colors, seed, goal_type, goal_count, moves):
    """§2/§7：生成期 64 次重试找 simulatePlay 可胜盘面。

    mulberry32(seed) 主流只构造一次，各次 generate 顺序消耗同一主流（回炉钉死）；
    64 次仍不可胜则告警并按最后盘面放行（warned=True，概率上不会发生）。
    """
    from .board import generate, jelly_count
    from .game import GameState

    main = mulberry32_once(seed)
    count = jelly_count(goal_type, goal_count, cols, rows)
    attempt = 0
    grid, jelly = None, None
    won = False
    while attempt < SIMULATE_RETRY:
        attempt += 1
        grid, jelly = generate(cols, rows, colors, count, main)
        st = GameState(cols=cols, rows=rows, colors=colors, seed=seed,
                       goal_type=goal_type, goal_count=goal_count, moves=moves,
                       grid=[row[:] for row in grid], jelly=frozenset(jelly),
                       moves_left=moves)
        if simulate_play(st)["win"]:
            won = True
            break
    return {"grid": grid, "jelly": jelly, "attempt": attempt, "won": won,
            "warned": not won}


def mulberry32_once(seed):
    """主流构造点（§7：create() 只构造一次并持有）。"""
    from .rng import mulberry32
    return mulberry32(seed)
