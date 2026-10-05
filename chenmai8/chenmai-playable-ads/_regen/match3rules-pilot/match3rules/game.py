# -*- coding: utf-8 -*-
"""游戏状态机——SPEC.md §5 计分胜负 / §6 nearWin·failBait / §7 k 与流的一致性。

k 的计算：moves - movesLeft + 1（trySwap 先捕获盐再扣步数，保证预估/结算/hint 三者同一 k）。
死局重排流：deriveRng(seed, 0x5117 ^ k)，doReshuffle 与 simulatePlay 重排同流。
"""

import copy
from dataclasses import dataclass, field
from typing import FrozenSet, List, Optional, Tuple

from .board import (
    ResolveResult,
    all_moves,
    generate,
    jelly_count,
    match_mask,
    reshuffle,
    resolve,
)
from .constants import SIMULATE_RETRY
from .rng import RESHUFFLE_SALT, SPAWN_SALT, derive_rng, mulberry32
from .solver import BestMove, Layout, Move, best_move, project_hint, swapped_grid


@dataclass
class GameState:
    cols: int
    rows: int
    colors: int
    seed: int
    goal_type: str                 # "clear-jelly" | "score"
    goal_count: int
    moves: int
    grid: List[List[int]]
    jelly: FrozenSet[Tuple[int, int]] = field(default_factory=frozenset)
    moves_left: int = 0
    score: int = 0
    jelly_cleared: int = 0
    phase: str = "playing"         # "tutorial" | "playing" | "end"
    busy: bool = False
    ended: bool = False
    win: Optional[bool] = None
    attract_near_win: bool = False
    near_win_done: bool = False
    fail_bait_armed: bool = False  # 教程结束后武装
    fail_bait_done: bool = False
    tutorial_demo: Optional[Move] = None

    def clone(self) -> "GameState":
        return copy.deepcopy(self)

    @property
    def progress(self) -> int:
        """§5：clear-jelly 进度 = 已清果冻数；score 模式进度 = score。"""
        return self.score if self.goal_type == "score" else self.jelly_cleared

    def has_move(self) -> bool:
        return bool(all_moves(self.grid))


def new_game(cols, rows, colors, seed, goal_type, goal_count, moves,
             attract_near_win=False, main_rng=None) -> GameState:
    """以主流 mulberry32(seed) 生成盘面并摆果冻（卡 §2）。"""
    rng = main_rng if main_rng is not None else mulberry32(seed)
    n_jelly = jelly_count(goal_type, goal_count, cols, rows)
    grid, jelly = generate(cols, rows, colors, n_jelly, rng)
    return GameState(
        cols=cols, rows=rows, colors=colors, seed=seed,
        goal_type=goal_type, goal_count=goal_count, moves=moves,
        grid=grid, jelly=jelly, moves_left=moves,
        attract_near_win=attract_near_win,
    )


def k_of(state: GameState) -> int:
    """§7：k = moves - movesLeft + 1。"""
    return state.moves - state.moves_left + 1


def swap_cells(state: GameState, r1: int, c1: int, r2: int, c2: int) -> Move:
    return Move(r1, c1, r2, c2, "right" if r1 == r2 else "down")


# ---------------------------------------------------------------------------
# §6 nearWin / failBait 预估（与真实结算同一补位流）
# ---------------------------------------------------------------------------

def simulate_swap(state: GameState, mv: Move, k: int) -> ResolveResult:
    """用与真实结算同一补位流（deriveRng(seed, SPAWN_SALT ^ k)）预估该交换的完整连消。"""
    return resolve(swapped_grid(state.grid, mv), state.colors, derive_rng(state.seed, SPAWN_SALT ^ k))


def swap_would_win(state: GameState, mv: Move, k: int) -> bool:
    res = simulate_swap(state, mv, k)
    if state.goal_type == "score":
        progress = res.score
    else:
        # 与真实结算一致：果冻按去重格数计（见 solver.best_move 同注）
        progress = len({(rc[0], rc[1]) for rc in res.cleared} & state.jelly)
    return progress >= state.goal_count


def is_legal_swap(state: GameState, mv: Move) -> bool:
    return bool(match_mask(swapped_grid(state.grid, mv)))


def near_win_sequence(state: GameState, mv: Move, k: int) -> list:
    """§6 nearWin 呈现序列：该次交换按非法交换回弹呈现（不耗步），只触发一次；
    下次同样交换将真实结算获胜。"""
    return [
        {"act": "invalidSwap", "swap": [mv.r1, mv.c1, mv.r2, mv.c2],
         "reason": "nearWin", "consumeMove": False, "ms": 110},
        {"act": "resolve", "swap": [mv.r1, mv.c1, mv.r2, mv.c2],
         "consumeMove": True, "outcome": "win"},
    ]


def find_winning_moves(state: GameState, k: Optional[int] = None) -> List[Move]:
    """全部"若将胜"的合法交换（nearWin 预估同流）。"""
    k = k_of(state) if k is None else k
    return [mv for mv in all_moves(state.grid) if swap_would_win(state, mv, k)]


# ---------------------------------------------------------------------------
# trySwap（§3 输入 + §5 结算 + §6 剧本）
# ---------------------------------------------------------------------------

def try_swap(state: GameState, r1: int, c1: int, r2: int, c2: int) -> dict:
    """busy/ended 忽略；相邻校验；非法交换回弹不耗步；nearWin/failBait 各只触发一次。"""
    if state.busy:
        return {"ok": False, "reason": "busy"}
    if state.ended:
        return {"ok": False, "reason": "ended"}
    if (abs(r1 - r2) + abs(c1 - c2)) != 1:
        return {"ok": False, "reason": "notAdjacent"}

    mv = swap_cells(state, r1, c1, r2, c2)
    if not is_legal_swap(state, mv):
        # §3 animateInvalidSwap：110ms 回弹，不消耗步数
        return {"ok": False, "reason": "invalid", "present": "invalidSwapBounce"}

    # 先捕获盐（k），再扣步数 —— 预估/结算/hint 三者同一 k（§7）
    k = k_of(state)

    # §6 nearWin：合法交换若将胜 -> 按非法交换回弹呈现（不耗步），只触发一次
    if (state.phase == "playing" and state.attract_near_win
            and not state.near_win_done and swap_would_win(state, mv, k)):
        state.near_win_done = True
        return {"ok": False, "reason": "nearWin", "present": "invalidSwapBounce",
                "sequence": near_win_sequence(state, mv, k)}

    # §6 failBait：教程结束后第一个"非胜"合法交换回弹一次（不耗步），只一次
    if (state.phase == "playing" and state.fail_bait_armed
            and not state.fail_bait_done and not swap_would_win(state, mv, k)):
        state.fail_bait_done = True
        return {"ok": False, "reason": "failBait", "present": "invalidSwapBounce"}

    # ---- 真实结算 ----
    state.moves_left -= 1
    res = resolve(swapped_grid(state.grid, mv), state.colors, derive_rng(state.seed, SPAWN_SALT ^ k))
    cleared_set = {(rc[0], rc[1]) for rc in res.cleared}
    gained = len(cleared_set & state.jelly)
    state.jelly = state.jelly - cleared_set
    state.jelly_cleared += gained
    state.score += res.score
    state.grid = res.finalGrid

    won = state.progress >= state.goal_count          # §5 胜：结算后 progress >= goalCount
    lost = state.moves_left <= 0                       # §5 负：movesLeft <= 0
    if won:
        state.ended, state.win, state.phase = True, True, "end"
    elif lost:
        state.ended, state.win, state.phase = True, False, "end"
    else:
        if state.phase == "tutorial":
            # §9：首次合法交换结算后教程提前结束
            state.phase = "playing"
        if not state.has_move():
            do_reshuffle(state)                        # §5 死局自动重排（不耗步）

    return {"ok": True, "k": k, "result": res.to_dict(),
            "gainedJelly": gained, "win": state.win, "ended": state.ended}


# ---------------------------------------------------------------------------
# 死局重排（§2/§5/§7）
# ---------------------------------------------------------------------------

def do_reshuffle(state: GameState) -> List[List[int]]:
    """死局重排流：deriveRng(seed, 0x5117 ^ k)；保留果冻；不耗步。"""
    rng = derive_rng(state.seed, RESHUFFLE_SALT ^ k_of(state))
    state.grid = reshuffle(state.grid, state.colors, rng)
    return state.grid


# ---------------------------------------------------------------------------
# hint（§8）
# ---------------------------------------------------------------------------

def hint(state: GameState, layout: Layout) -> Optional[dict]:
    """返回 null 的情形：教程相位无 demo；busy/ended；playing 无步（此时会触发 doReshuffle）。"""
    if state.busy or state.ended:
        return None
    moves = all_moves(state.grid)
    if state.phase == "tutorial":
        demo = best_move(state.grid, state.colors, state.seed, k_of(state),
                         state.goal_type, state.goal_count, state.jelly) if moves else None
        if demo is None and moves:            # 无最优步时取 allMoves[0]
            demo_move = moves[0]
        else:
            demo_move = demo.move if demo else None
        if demo_move is None:                 # 教程相位无 demo
            return None
        if state.tutorial_demo is None:
            state.tutorial_demo = demo_move
        return project_hint(demo_move, layout)
    if state.phase != "playing":
        return None
    if not moves:
        return None                            # 触发 doReshuffle 的情形
    bm = best_move(state.grid, state.colors, state.seed, k_of(state),
                   state.goal_type, state.goal_count, state.jelly)
    return project_hint(bm.move, layout)


# ---------------------------------------------------------------------------
# simulatePlay 与生成期可玩性（§7 推论）
# ---------------------------------------------------------------------------

def simulate_play(state: GameState, max_iters: int = 1000) -> dict:
    """按 hint 同款贪心（bestMove）自玩至胜/负。含死局重排与 attract 剧本（同真实游玩），
    因此"该盘面 simulatePlay 可胜" ⇔ "QC 按 hint 引导必然可胜"（§7 推论的构造性成立）。"""
    s = state.clone()
    trace = []
    it = 0
    while not s.ended and it < max_iters:
        it += 1
        if not s.has_move():
            do_reshuffle(s)
            trace.append({"act": "reshuffle", "k": k_of(s)})
            continue
        bm: Optional[BestMove] = best_move(s.grid, s.colors, s.seed, k_of(s),
                                           s.goal_type, s.goal_count, s.jelly)
        if bm is None:
            break
        mv = bm.move
        r = try_swap(s, mv.r1, mv.c1, mv.r2, mv.c2)
        trace.append({"act": "swap", "ok": r["ok"], "reason": r.get("reason")})
    return {
        "win": s.win,
        "ended": s.ended,
        "score": s.score,
        "jelly_cleared": s.jelly_cleared,
        "moves_left": s.moves_left,
        "state": s,
        "trace": trace,
    }


def generate_winnable(cols, rows, colors, seed, goal_type, goal_count, moves,
                      attract_near_win=False, retries: int = SIMULATE_RETRY) -> dict:
    """生成期可玩性保证（§7 推论）：64 次重试找 simulatePlay 可胜盘面；
    仍不可胜则告警（warned=True）并按最后盘面放行（卡：概率上不会发生）。
    每次重试继续消耗同一主流（卡未明说重期间隔流，见 notes）。"""
    rng = mulberry32(seed)
    last = None
    for attempt in range(1, retries + 1):
        n_jelly = jelly_count(goal_type, goal_count, cols, rows)
        grid, jelly = generate(cols, rows, colors, n_jelly, rng)
        st = GameState(cols=cols, rows=rows, colors=colors, seed=seed,
                       goal_type=goal_type, goal_count=goal_count, moves=moves,
                       grid=grid, jelly=jelly, moves_left=moves,
                       attract_near_win=attract_near_win)
        sim = simulate_play(st)
        last = {"grid": grid, "jelly": jelly, "sim": sim, "attempt": attempt}
        if sim["win"]:
            return {"grid": grid, "jelly": jelly, "attempt": attempt,
                    "won": True, "warned": False, "sim": sim}
    return {"grid": last["grid"], "jelly": last["jelly"], "attempt": last["attempt"],
            "won": last["sim"]["win"], "warned": True, "sim": last["sim"]}
