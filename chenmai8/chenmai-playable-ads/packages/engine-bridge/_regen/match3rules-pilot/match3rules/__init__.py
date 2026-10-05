# -*- coding: utf-8 -*-
"""match3rules —— 三消规则卡（SPEC.md，冻结 v1.0.0）的独立 Python 复算实现。

范围（重生成试验四特性）：
  1. 盘面生成（含 LCG 盐）        board.generate / rng.*
  2. 可行步检测                    solver.all_moves / solver.has_any_move
  3. nearWin 序列生成              game.try_swap / game.near_win_sequence
  4. hint 坐标（视口 CSS 像素）    solver.Layout / solver.project_hint / game.hint

唯一权威：包根目录 SPEC.md（复制自规则卡）。测试：tests/frozen.py（冻结 eval）。
"""

from .board import (  # noqa: F401
    ResolveResult,
    all_moves,
    fill_no_matches,
    generate,
    has_any_move,
    jelly_count,
    match_mask,
    place_jelly,
    reshuffle,
    resolve,
    score_mode_jelly_count,
)
from .constants import *  # noqa: F401,F403
from .game import (  # noqa: F401
    GameState,
    do_reshuffle,
    find_winning_moves,
    generate_winnable,
    hint,
    k_of,
    new_game,
    near_win_sequence,
    simulate_play,
    simulate_swap,
    swap_would_win,
    try_swap,
)
from .jsnum import imul32, js_round, to_i32, to_u32  # noqa: F401
from .rng import (  # noqa: F401
    RESHUFFLE_SALT,
    SPAWN_SALT,
    derive_rng,
    derive_seed,
    mulberry32,
    reshuffle_rng,
    spawn_rng,
)
from .solver import (  # noqa: F401
    BestMove,
    Layout,
    Move,
    best_move,
    cell_center,
    eval_clear,
    eval_score,
    project_hint,
)
from .spec import make_t, normalize_spec, sprite_key_for  # noqa: F401
from .textures import fnv1a, piece_style  # noqa: F401

__version__ = "1.0.0"
