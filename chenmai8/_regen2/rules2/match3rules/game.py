# -*- coding: utf-8 -*-
"""玩法状态机（卡面 §3/§5/§6/§7）：GameState / try_swap / swap_would_win。

- trySwap：busy/ended 时忽略；相位非 playing 且非教程时忽略。
- 非法交换（无三连）→ animateInvalidSwap 回弹，不消耗步数。
- k 捕获顺序（卡面 §7，回炉钉死）：trySwap 先捕获盐（k = moves - movesLeft + 1）再扣步数，
  保证 nearWin 预估 / 真实结算 / hint 投影三者同一 k。
- nearWin（§6）：某次合法交换若将胜（用与真实结算同一补位流预估），且 attract.nearWin=true
  且未触发过 → 按非法交换回弹呈现（不耗步），只一次；下次同样交换将真实结算获胜。
- failBait（§6）：教程结束后的第一个"非胜"合法交换回弹一次（不耗步），只一次；
  将胜的交换不吃 failBait。
- 胜负（§5）：结算后 progress >= goalCount → 胜；否则 movesLeft <= 0 → 负。
  clear-jelly 进度 = 已清果冻数（按去重集合计，防跨波重复计数）；score 模式进度 = score。
"""

from .board import match_mask, resolve
from .constants import SPAWN_SALT
from .rng import derive_rng
from .solver import Move, swapped_grid


class GameState:
    """一局玩法逻辑态（模板侧相位机/动画不在镜像范围，相位以 phase 字段记录）。

    jelly 元素 = (row, col)；grid = row 优先二维数组。
    """

    def __init__(self, cols, rows, colors, seed, goal_type, goal_count, moves,
                 grid, jelly, moves_left,
                 attract_near_win=False, fail_bait_armed=False,
                 phase="playing", busy=False, ended=False, win=None,
                 near_win_done=False, fail_bait_done=False):
        self.cols = cols
        self.rows = rows
        self.colors = colors
        self.seed = seed
        self.goal_type = goal_type
        self.goal_count = goal_count
        self.moves = moves
        self.grid = grid
        self.jelly = jelly
        self.moves_left = moves_left
        self.attract_near_win = attract_near_win
        self.fail_bait_armed = fail_bait_armed
        self.phase = phase
        self.busy = busy
        self.ended = ended
        self.win = win
        self.near_win_done = near_win_done
        self.fail_bait_done = fail_bait_done

    def copy(self):
        return GameState(
            cols=self.cols, rows=self.rows, colors=self.colors, seed=self.seed,
            goal_type=self.goal_type, goal_count=self.goal_count, moves=self.moves,
            grid=[row[:] for row in self.grid], jelly=frozenset(self.jelly),
            moves_left=self.moves_left,
            attract_near_win=self.attract_near_win,
            fail_bait_armed=self.fail_bait_armed,
            phase=self.phase, busy=self.busy, ended=self.ended, win=self.win,
            near_win_done=self.near_win_done, fail_bait_done=self.fail_bait_done,
        )


def _progress_of(state, result):
    """§5：clear-jelly 进度 = 已清果冻数（去重集合，防跨波重复计数）；score 模式 = score。"""
    if state.goal_type == "score":
        return result.score
    return len({tuple(c) for c in result.cleared} & set(state.jelly))


def _direction_of(y1, x1, y2, x2):
    if y2 == y1 + 1:
        return "down"
    if y2 == y1 - 1:
        return "up"
    if x2 == x1 + 1:
        return "right"
    return "left"


def swap_would_win(state, move, k):
    """§6：用与真实结算同一补位流 deriveRng(seed, SPAWN_SALT ^ k) 预估该交换是否将胜。"""
    result = resolve(swapped_grid(state.grid, move), state.colors,
                     derive_rng(state.seed, SPAWN_SALT ^ k))
    return _progress_of(state, result) >= state.goal_count


def try_swap(state, y1, x1, y2, x2):
    """§3 输入入口（tap-tap 点选两相邻格；坐标 = (row, col)，与冻结 eval 记法一致）。

    返回 dict：非法/回弹 {"ok": False, "reason": ...}；合法结算
    {"ok": True, "k": k, "win": ..., "progress": ..., "result": ResolveResult}。
    """
    if state.busy:
        return {"ok": False, "reason": "busy"}
    if state.ended:
        return {"ok": False, "reason": "ended"}
    if state.phase not in ("playing", "tutorial"):
        return {"ok": False, "reason": "phase"}
    if abs(y1 - y2) + abs(x1 - x2) != 1:
        return {"ok": False, "reason": "notAdjacent"}

    move = Move(y1, x1, y2, x2, _direction_of(y1, x1, y2, x2))
    swapped = swapped_grid(state.grid, move)
    if not match_mask(swapped):
        return {"ok": False, "reason": "invalid"}  # animateInvalidSwap，不耗步

    # §7 回炉钉死：先捕获盐（k）再扣步数——预估/结算/hint 三者同一 k
    k = state.moves - state.moves_left + 1

    would_win = swap_would_win(state, move, k)

    # §6 nearWin：将胜 + 开关开 + 未触发过 → 按非法交换回弹，只一次，不耗步
    if would_win and state.attract_near_win and not state.near_win_done:
        state.near_win_done = True
        return {"ok": False, "reason": "nearWin", "k": k,
                "sequence": [
                    {"act": "invalidSwap", "consumeMove": False},
                    {"act": "resolve", "outcome": "win", "consumeMove": True},
                ]}

    # §6 failBait：教程结束后的第一个"非胜"合法交换回弹一次，不耗步
    if (not would_win) and state.fail_bait_armed and not state.fail_bait_done:
        state.fail_bait_done = True
        return {"ok": False, "reason": "failBait", "k": k}

    # 真实结算：同一补位流
    result = resolve(swapped, state.colors, derive_rng(state.seed, SPAWN_SALT ^ k))
    state.grid = result.finalGrid
    state.moves_left -= 1
    progress = _progress_of(state, result)
    if progress >= state.goal_count:
        state.ended = True
        state.win = True
    elif state.moves_left <= 0:
        state.ended = True
        state.win = False
    return {"ok": True, "k": k, "win": state.win is True, "progress": progress,
            "result": result}
