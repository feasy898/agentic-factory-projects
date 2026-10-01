# -*- coding: utf-8 -*-
"""卡面常数总表（SPEC.md = match3-rules-card.md 回炉版冻结 v1.0.0）。

每个常数标注卡面出处；冻结 eval 的 test_frozen_constants_table 逐一对应。
"""


def drag_threshold_px(cell):
    """§3：拖拽位移阈值 = max(18, cell*0.35) 像素，主轴定方向。"""
    return max(DRAG_THRESHOLD_MIN_PX, cell * DRAG_CELL_RATIO)


# §2 盘面生成 -----------------------------------------------------------------
FILL_MAX_ATTEMPTS = 32   # fillNoMatches 每格至多尝试次数，超限接受最后一次取值
GENERATE_GUARD = 200     # generate 的 hasAnyMove 守卫（整体重来上限）
RESHUFFLE_GUARD = 200    # 死局重排守卫（fillNoMatches + hasAnyMove 重来上限）
MAX_WAVES = 64           # resolve 波次循环上限（防死循环）

# §3 交换 ---------------------------------------------------------------------
DRAG_THRESHOLD_MIN_PX = 18
DRAG_CELL_RATIO = 0.35
INVALID_SWAP_MS = 110    # animateInvalidSwap：110ms 滑过去再弹回，不耗步

# §4 波次动画时长（逻辑镜像仅作常数记录；逻辑立即生效）-----------------------
MATCH_MS = 150           # match 缩消
FALL_MS = 160
SPAWN_MS = 170
WAVE_DELAYS_MS = (170, 180, 190)  # 波间 delay

# §5 死局重排呈现 -------------------------------------------------------------
RESHUFFLE_SNAP_MS = 280  # 不耗步，280ms 后 snap
RESHUFFLE_BUSY_MS = 560  # 560ms 解 busy

# §7 随机流 -------------------------------------------------------------------
SPAWN_SALT = 0x51ED270B  # 补位流盐：deriveRng(seed, SPAWN_SALT ^ k)
RESHUFFLE_SALT = 0x5117  # 死局重排流盐：deriveRng(seed, 0x5117 ^ k)
SIMULATE_RETRY = 64      # 生成期 simulatePlay 可胜重试上限（64 次仍不可胜则告警放行）

# §8 求解器评价值权重 ---------------------------------------------------------
EVAL_CLEAR_JELLY_WEIGHT = 1000    # clear-jelly：果冻*1000 + score*2 + cascades*15
EVAL_CLEAR_SCORE_WEIGHT = 2
EVAL_CLEAR_CASCADE_WEIGHT = 15
EVAL_SCORE_WEIGHT = 10            # score 模式：score*10 + cascades*15
EVAL_SCORE_CASCADE_WEIGHT = 15

# §9/§13 ----------------------------------------------------------------------
BACKGROUND_COLOR = 0x141B34
PF_END_BUDGET_S = 45

# §1 qc 缺省（2026-09-29 回炉钉死：maxLoadSec 缺省 2 钳 1-10；autoplayTimeoutSec 缺省 45 钳 5-300）。
# 注意：冻结 eval pin 归一输出的缺省为 None（其冻结时点卡面未给缺省），故卡面缺省值
# 以消费侧常量形式留在此处，normalize_spec 输出 None 表示"未提供，消费时取下方缺省"。
QC_MAX_LOAD_SEC_DEFAULT = 2
QC_AUTOPLAY_TIMEOUT_SEC_DEFAULT = 45
