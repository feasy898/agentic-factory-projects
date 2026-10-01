# -*- coding: utf-8 -*-
"""match3rules——三消规则卡（SPEC.md = match3-rules-card.md 回炉版冻结 v1.0.0）的
独立 Python 复算实现（重生成试验第二轮，只凭回炉后规则卡 + 冻结 eval 从零实现）。

模块结构（依赖单向：constants/jsnum/rng -> board -> solver -> game；spec/textures 独立）：
- constants  卡面常数总表
- jsnum      JS 数值语义镜像（Math.round / int(v,d,lo,hi)）
- rng        mulberry32（t|61 真源口径 = 重冻 oracle，2026-09-29 属主裁决）/ deriveRng / 盐值流
- board      fillNoMatches / generate / placeJelly / resolve / doReshuffle
- solver     allMoves / bestMove / eval / hint 投影 / simulatePlay / generateWinnable
- game       GameState / trySwap / swapWouldWin
- spec       normalizeSpec / makeT / spriteKeys
- textures   FNV-1a / 形状 / 调色板（素材缺失纯派生部分）
"""

from .constants import (BACKGROUND_COLOR, DRAG_CELL_RATIO, DRAG_THRESHOLD_MIN_PX,
                        EVAL_CLEAR_CASCADE_WEIGHT, EVAL_CLEAR_JELLY_WEIGHT,
                        EVAL_CLEAR_SCORE_WEIGHT, EVAL_SCORE_CASCADE_WEIGHT, EVAL_SCORE_WEIGHT,
                        FALL_MS, FILL_MAX_ATTEMPTS, GENERATE_GUARD, INVALID_SWAP_MS, MATCH_MS,
                        MAX_WAVES, PF_END_BUDGET_S, RESHUFFLE_BUSY_MS, RESHUFFLE_GUARD,
                        RESHUFFLE_SALT, RESHUFFLE_SNAP_MS, SIMULATE_RETRY, SPAWN_MS, SPAWN_SALT,
                        WAVE_DELAYS_MS)
from .jsnum import js_round
from .rng import derive_rng, derive_seed, imul32, mulberry32, spawn_rng
from .board import (ResolveResult, do_reshuffle, fill_no_matches, generate, jelly_count,
                    match_mask, place_jelly, resolve, reshuffle, score_mode_jelly_count)
from .solver import (BestMove, Layout, Move, all_moves, best_move, cell_center, eval_clear,
                     eval_score, generate_winnable, has_any_move, hint, k_of, project_hint,
                     simulate_play, swapped_grid)
from .game import GameState, swap_would_win, try_swap
from .spec import DEFAULT_SPRITE_KEYS, make_t, normalize_spec, sprite_key_for
from .textures import PALETTE, SHAPES, fnv1a, piece_style

__all__ = [
    # 常数
    "BACKGROUND_COLOR", "DRAG_CELL_RATIO", "DRAG_THRESHOLD_MIN_PX",
    "EVAL_CLEAR_CASCADE_WEIGHT", "EVAL_CLEAR_JELLY_WEIGHT", "EVAL_CLEAR_SCORE_WEIGHT",
    "EVAL_SCORE_CASCADE_WEIGHT", "EVAL_SCORE_WEIGHT", "FALL_MS", "FILL_MAX_ATTEMPTS",
    "GENERATE_GUARD", "INVALID_SWAP_MS", "MATCH_MS", "MAX_WAVES", "PF_END_BUDGET_S",
    "RESHUFFLE_BUSY_MS", "RESHUFFLE_GUARD", "RESHUFFLE_SALT", "RESHUFFLE_SNAP_MS",
    "SIMULATE_RETRY", "SPAWN_MS", "SPAWN_SALT", "WAVE_DELAYS_MS",
    "DEFAULT_SPRITE_KEYS", "PALETTE", "SHAPES",
    # 类型
    "BestMove", "GameState", "Layout", "Move", "ResolveResult",
    # 函数
    "all_moves", "best_move", "cell_center", "derive_rng", "derive_seed", "do_reshuffle",
    "eval_clear", "eval_score", "fill_no_matches", "fnv1a", "generate", "generate_winnable",
    "has_any_move", "hint", "imul32", "jelly_count", "js_round", "k_of", "make_t",
    "match_mask", "mulberry32", "normalize_spec", "piece_style", "place_jelly",
    "project_hint", "resolve", "reshuffle", "score_mode_jelly_count", "simulate_play",
    "spawn_rng", "sprite_key_for", "swap_would_win", "try_swap", "swapped_grid",
]
