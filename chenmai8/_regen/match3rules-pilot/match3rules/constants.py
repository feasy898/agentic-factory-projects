# -*- coding: utf-8 -*-
"""规则卡（SPEC.md）中的全部冻结常数，按出处小节标注。"""

# --- §2 盘面生成 ---
FILL_MAX_ATTEMPTS = 32          # fillNoMatches 每格至多 32 次尝试，超限接受最后一次取值
GENERATE_GUARD = 200            # generate 无可行步整体重来，guard <= 200
RESHUFFLE_GUARD = 200           # reshuffle 同样 guard <= 200

# --- §3 交换 ---
DRAG_THRESHOLD_MIN_PX = 18      # max(18, cell*0.35)
DRAG_CELL_RATIO = 0.35
INVALID_SWAP_MS = 110           # animateInvalidSwap：110ms 滑过去再弹回，不消耗步数

# --- §4 消除/下落/补位/连消 ---
MAX_WAVES = 64                  # 波次循环至多 64 波（防死循环上限）
MATCH_MS = 150
FALL_MS = 160
SPAWN_MS = 170
WAVE_DELAYS_MS = (170, 180, 190)

# --- §5 计分 ---
SCORE_PER_CELL_PER_WAVE = 10    # 第 w 波每格 10*w 分
RESHUFFLE_SNAP_MS = 280         # 死局重排不耗步，280ms 后 snap
RESHUFFLE_BUSY_MS = 560         # 560ms 解 busy

# --- §7 生成期可玩性 ---
SIMULATE_RETRY = 64             # 生成期 64 次重试找 simulatePlay 可胜盘面，仍不可胜则告警放行

# --- §8 求解器评价权重 ---
EVAL_CLEAR_JELLY_WEIGHT = 1000  # clear-jelly: 果冻*1000 + score*2 + cascades*15
EVAL_CLEAR_SCORE_WEIGHT = 2
EVAL_CLEAR_CASCADE_WEIGHT = 15
EVAL_SCORE_WEIGHT = 10          # score 模式: score*10 + cascades*15
EVAL_SCORE_CASCADE_WEIGHT = 15

# --- §9 ---
BACKGROUND_COLOR = 0x141B34

# --- §12 验收 ---
PF_END_BUDGET_S = 45            # 门项 4：pf:end <= 45s


def drag_threshold_px(cell: float) -> float:
    """SPEC §3：位移阈值 max(18, cell*0.35) 像素。"""
    return max(DRAG_THRESHOLD_MIN_PX, cell * DRAG_CELL_RATIO)
