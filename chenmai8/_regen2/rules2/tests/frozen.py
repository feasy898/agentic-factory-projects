# -*- coding: utf-8 -*-
"""冻结 eval（重生成试验）——tests/frozen.py。

铁律：本文件在冻结后一字不改；断言全部转写自 SPEC.md（= 规则卡 match3-rules-card.md
冻结 v1.0.0），出处以 §编号标注。凡卡面给出常数/公式/边界值处，逐条断言；
卡面未给输出向量的地方，采用两类已知答案补强并在 docstring 注明来源：
  (a) 外部公认测试向量（FNV-1a 的 "a"/"foobar"）；
  (b) 冻结时刻内联的规范算法定义转写（mulberry32 公版），作为独立对照 oracle。
其余已知答案为本包从卡面规则手工推导的构造盘面（推导过程写在各测试 docstring）。

oracle 重冻：t|61 真源口径（规则卡 §7/§12，2026-09-29 属主裁决）——_mulberry32_reference
第二乘数原转写误写常数 `* 61`，与规则卡 §7 钉死的 bryc 公版真源 `t | 61`（模板 rng.ts 原文；
§12 向量 mulberry32(1) 首抽=0.6270739405881613 佐证）不符，本次只改该一处转写并整体重冻，
其余断言一字未动。
"""

import pytest

from match3rules import (
    BACKGROUND_COLOR,
    DRAG_CELL_RATIO,
    DRAG_THRESHOLD_MIN_PX,
    EVAL_CLEAR_CASCADE_WEIGHT,
    EVAL_CLEAR_JELLY_WEIGHT,
    EVAL_CLEAR_SCORE_WEIGHT,
    EVAL_SCORE_CASCADE_WEIGHT,
    EVAL_SCORE_WEIGHT,
    FALL_MS,
    FILL_MAX_ATTEMPTS,
    GENERATE_GUARD,
    INVALID_SWAP_MS,
    MATCH_MS,
    MAX_WAVES,
    PF_END_BUDGET_S,
    RESHUFFLE_BUSY_MS,
    RESHUFFLE_GUARD,
    RESHUFFLE_SALT,
    RESHUFFLE_SNAP_MS,
    SIMULATE_RETRY,
    SPAWN_MS,
    SPAWN_SALT,
    WAVE_DELAYS_MS,
    GameState,
    Layout,
    Move,
    all_moves,
    best_move,
    cell_center,
    derive_rng,
    derive_seed,
    do_reshuffle,
    eval_clear,
    eval_score,
    fill_no_matches,
    fnv1a,
    generate,
    generate_winnable,
    has_any_move,
    hint,
    imul32,
    jelly_count,
    js_round,
    k_of,
    make_t,
    match_mask,
    mulberry32,
    normalize_spec,
    piece_style,
    place_jelly,
    project_hint,
    resolve,
    reshuffle,
    score_mode_jelly_count,
    simulate_play,
    sprite_key_for,
    swap_would_win,
    try_swap,
)
from match3rules.solver import swapped_grid
from match3rules.rng import spawn_rng as _spawn_rng


# ---------------------------------------------------------------------------
# 脚手架：脚本化 rng / 计数 rng / 冻结的对照 oracle
# ---------------------------------------------------------------------------

class ScriptedRng:
    """按脚本产色：第 i 次调用使 int(x*colors) == values[i]。

    原理：(v+0.5)/colors * colors = v+0.5（小整数二进制精确）-> int 截断回 v。
    队列耗尽即断言失败（多消耗补位流 = 实现偏离预期）。
    """

    def __init__(self, values, colors):
        self.values = list(values)
        self.colors = colors
        self.i = 0

    def __call__(self):
        assert self.i < len(self.values), "ScriptedRng 队列耗尽：补位流消耗次数超出脚本"
        v = self.values[self.i]
        self.i += 1
        return (v + 0.5) / self.colors


class CountingRng:
    """恒返 0.0 并计调用次数——用于 pin 补位流消耗次数。"""

    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return 0.0


def _mulberry32_reference(seed):
    """mulberry32 规范公共定义（bryc 版）在冻结时刻的内联转写——独立对照 oracle。
    来源标注：(b) 类已知答案；实现若偏离此转写即刻失败。
    oracle 重冻（2026-09-29 属主裁决）：第二乘数 = t|61 真源口径（规则卡 §7/§12，
    模板 rng.ts 原文；此前误转写为常数 *61，mulberry32(1) 首抽应为 0.6270739405881613）。"""
    a = seed & 0xFFFFFFFF
    if a >= 0x80000000:
        a -= 0x100000000
    box = {"a": a}

    def rnd():
        s = (box["a"] + 0x6D2B79F5) & 0xFFFFFFFF
        box["a"] = s - 0x100000000 if s >= 0x80000000 else s
        t = s
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t = (t ^ ((t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296

    return rnd


# 冻结构造盘面 ---------------------------------------------------------------

GRID_CASCADE = [
    # 5 列 x 3 行，colors=2。col0=[0,0,0]、col1=[1,1,1] 首波各成 run3；
    # 交手工排布使第二波在补位脚本 [0,1,1,0,0,1] 下恰成 row0 run3，第三波补位后无消。
    [0, 1, 0, 1, 1],
    [0, 1, 1, 0, 1],
    [0, 1, 0, 1, 0],
]

GRID_NEARWIN = [
    # 3x3，colors=3，无初始消；12 个候选相邻交换逐一手工验证，恰有唯一合法步：
    #   A: down (0,1)-(1,1) -> row0 [1,1,1]（清 3 格）。
    # 果冻取 row0 三格时 A 将胜（progress 3）；果冻取 (1,0) 时 A 非胜（供 failBait/负局）。
    [1, 0, 1],
    [2, 1, 2],
    [0, 0, 2],
]
JELLY_ROW0 = frozenset({(0, 0), (0, 1), (0, 2)})

GRID_LATIN = [
    # 3x3 拉丁方，colors=3：行列皆三色互异 -> 无初始消且任何相邻交换都不成 run
    # （交换只触及所在行/列各一格，行内本就互异；列原本三值互异，改一格至多成对不成三）。
    # -> allMoves 为空（死局盘）。
    [0, 1, 2],
    [1, 2, 0],
    [2, 0, 1],
]


def _nearwin_state(goal=3, moves=5, attract_near_win=False, fail_bait_armed=False, seed=42,
                   jelly=None):
    return GameState(
        cols=3, rows=3, colors=3, seed=seed,
        goal_type="clear-jelly", goal_count=goal, moves=moves,
        grid=[row[:] for row in GRID_NEARWIN],
        jelly=frozenset(JELLY_ROW0 if jelly is None else jelly), moves_left=moves,
        attract_near_win=attract_near_win, fail_bait_armed=fail_bait_armed,
    )


# ---------------------------------------------------------------------------
# §1 参数与宽容归一
# ---------------------------------------------------------------------------

def test_s1_normalize_defaults():
    s = normalize_spec({})
    assert s["cols"] == 6 and s["rows"] == 6
    assert s["moves"] == 15
    assert s["colors"] == 5
    assert s["goalCount"] == 30
    assert s["goalType"] == "clear-jelly"
    assert s["spriteKeys"] == ["piece-0", "piece-1", "piece-2", "piece-3", "piece-4"]
    assert s["seed"] == 1
    assert s["difficulty"]["targetLevel"] == 0.5
    assert s["attract"]["firstClickSucceed"] is True
    assert s["tutorial"]["gesture"] == "drag"


def test_s1_normalize_clamps_template_ranges():
    s = normalize_spec({"cols": 2, "rows": 10, "moves": 0, "colors": 1, "goalCount": 0})
    assert s["cols"] == 3 and s["rows"] == 9 and s["moves"] == 1 and s["colors"] == 2 and s["goalCount"] == 1
    s = normalize_spec({"cols": 9, "rows": 3, "moves": 61, "colors": 8, "goalCount": 500})
    assert s["cols"] == 9 and s["rows"] == 3 and s["moves"] == 60 and s["colors"] == 7 and s["goalCount"] == 400


def test_s1_normalize_goalType_mapping():
    # 非 "score" 一律 clear-jelly
    assert normalize_spec({"goalType": "score"})["goalType"] == "score"
    assert normalize_spec({"goalType": "clearJelly"})["goalType"] == "clear-jelly"
    assert normalize_spec({"goalType": None})["goalType"] == "clear-jelly"


def test_s1_normalize_seed():
    assert normalize_spec({"seed": 123})["seed"] == 123
    assert normalize_spec({"seed": 0})["seed"] == 0
    assert normalize_spec({"seed": 2 ** 31})["seed"] == 0x7FFFFFFF
    assert normalize_spec({})["seed"] == 1


def test_s1_normalize_misc():
    assert normalize_spec({"difficulty": {"targetLevel": 1.5}})["difficulty"]["targetLevel"] == 1.0
    assert normalize_spec({"difficulty": {"targetLevel": -0.1}})["difficulty"]["targetLevel"] == 0.0
    assert normalize_spec({"difficulty": {"targetLevel": 0.75}})["difficulty"]["targetLevel"] == 0.75
    assert normalize_spec({"tutorial": {"gesture": "tap"}})["tutorial"]["gesture"] == "tap"
    # 卡面字面：非 "tap" 一律 "drag"（大小写敏感）
    assert normalize_spec({"tutorial": {"gesture": "TAP"}})["tutorial"]["gesture"] == "drag"
    assert normalize_spec({"attract": {"firstClickSucceed": False}})["attract"]["firstClickSucceed"] is False
    # spriteKeys >=1 即可
    assert normalize_spec({"spriteKeys": ["x"]})["spriteKeys"] == ["x"]
    assert normalize_spec({"spriteKeys": []})["spriteKeys"] == ["piece-0", "piece-1", "piece-2", "piece-3", "piece-4"]
    # qc 钳制 1-10 / 5-300；卡未给缺省 -> 缺省 None（卡面缺口，如实保留）
    assert normalize_spec({"qc": {"maxLoadSec": 0.5, "autoplayTimeoutSec": 301}})["qc"] == {
        "maxLoadSec": 1.0, "autoplayTimeoutSec": 300.0}
    assert normalize_spec({"qc": {"maxLoadSec": 11, "autoplayTimeoutSec": 4}})["qc"] == {
        "maxLoadSec": 10.0, "autoplayTimeoutSec": 5.0}
    assert normalize_spec({})["qc"] == {"maxLoadSec": None, "autoplayTimeoutSec": None}


def test_s1_make_t_three_level_fallback():
    texts = {"zh": {"title": "消除"}, "en": {"title": "Match", "play": "Play"}}
    t = make_t(texts, "zh")
    assert t("title") == "消除"          # 当前语言
    assert t("play") == "Play"           # -> 默认语言 en
    t2 = make_t({"de": {"play": "Los"}}, "fr", default_lang="de")
    assert t2("play") == "Los"           # -> 默认语言 de
    assert t2("nope") == "nope"          # -> 键名本身


def test_s1_sprite_key_modulo():
    keys = ["a", "b", "c"]
    assert sprite_key_for(0, keys) == "a"
    assert sprite_key_for(2, keys) == "c"
    assert sprite_key_for(4, keys) == "b"   # i % spriteKeys.length


# ---------------------------------------------------------------------------
# §2 盘面生成
# ---------------------------------------------------------------------------

def test_s2_score_mode_jelly_count_formula():
    # min(cols*rows, max(6, round(cols*rows*0.25)))；round 为 JS Math.round（.5 向上）
    assert score_mode_jelly_count(6, 6) == 9      # 9.0
    assert score_mode_jelly_count(6, 7) == 11     # 10.5 -> JS 11（Python round 会给 10，此处 pin JS 语义）
    assert score_mode_jelly_count(3, 3) == 6      # 2.25 -> 2 -> max(6,2)
    assert score_mode_jelly_count(4, 4) == 6      # 4 -> max(6,4)
    assert score_mode_jelly_count(7, 7) == 12     # 12.25
    assert score_mode_jelly_count(9, 9) == 20     # 20.25
    assert score_mode_jelly_count(3, 9) == 7      # 6.75 -> 7
    assert score_mode_jelly_count(5, 5) == 6      # 6.25 -> 6
    assert score_mode_jelly_count(9, 4) == 9      # 9 -> 9
    assert jelly_count("score", 30, 6, 6) == 9
    assert jelly_count("clear-jelly", 30, 3, 3) == 9   # clear-jelly = goalCount（钳到格数）


def test_s2_fill_no_matches_consumes_32_attempts_per_conflicting_cell():
    # colors=1 时每格每抽必与"左二/上二"同色（若存在）：无参照格 1 抽、单参照格 1 抽、
    # 双参照格 32 抽（至多 32 次尝试，超限接受最后一次）。3x3 消耗 = 34+34+96 = 164。
    rng = CountingRng()
    g = fill_no_matches(3, 3, 1, rng)
    assert rng.calls == 164
    assert all(v == 0 for row in g for v in row)
    # 全 0 盘：三行三列各成 run3 -> 全部 9 格被标记
    assert match_mask(g) == {(r, c) for r in range(3) for c in range(3)}


def test_s2_generate_invariants_and_determinism():
    for seed in range(1, 31):
        rng = mulberry32(seed)
        grid, jelly = generate(6, 6, 5, 9, rng)
        # 无初始三连（fillNoMatches 的定义性输出）
        assert match_mask(grid) == set()
        # 必有可行步（generate 的 hasAnyMove 守卫）
        assert has_any_move(grid)
        # 果冻数量正确、落点在盘内
        assert len(jelly) == 9
        assert all(0 <= r < 6 and 0 <= c < 6 for (r, c) in jelly)
        # 同 seed 全程确定（主流 mulberry32(seed)）
        grid2, jelly2 = generate(6, 6, 5, 9, mulberry32(seed))
        assert grid2 == grid and jelly2 == jelly


def test_s2_place_jelly_deterministic():
    j1 = place_jelly(6, 6, 9, mulberry32(7))
    j2 = place_jelly(6, 6, 9, mulberry32(7))
    j3 = place_jelly(6, 6, 9, mulberry32(8))
    assert j1 == j2 and len(j1) == 9
    assert j1 != j3


def test_s2_reshuffle_keeps_jelly_and_restores_moves():
    st = GameState(cols=3, rows=3, colors=3, seed=9, goal_type="clear-jelly",
                   goal_count=3, moves=5,
                   grid=[row[:] for row in GRID_LATIN], jelly=frozenset({(1, 1)}), moves_left=5)
    assert all_moves(GRID_LATIN) == []      # 前置：死局盘
    g1 = do_reshuffle(st)
    assert (1, 1) in st.jelly               # 保留果冻
    assert has_any_move(g1)                 # 守卫后必有可行步
    # 流一致：deriveRng(seed, 0x5117 ^ k)，k = moves - movesLeft + 1 = 1
    rng = derive_rng(9, RESHUFFLE_SALT ^ 1)
    expect = fill_no_matches(3, 3, 3, rng)
    if not has_any_move(expect):            # 复刻 guard <= 200 重来
        for _ in range(RESHUFFLE_GUARD - 1):
            expect = fill_no_matches(3, 3, 3, rng)
            if has_any_move(expect):
                break
    assert g1 == expect
    # 同 seed 确定性
    st2 = GameState(cols=3, rows=3, colors=3, seed=9, goal_type="clear-jelly",
                    goal_count=3, moves=5,
                    grid=[row[:] for row in GRID_LATIN], jelly=frozenset({(1, 1)}), moves_left=5)
    assert do_reshuffle(st2) == g1


# ---------------------------------------------------------------------------
# §3 交换
# ---------------------------------------------------------------------------

def test_s3_constants():
    assert DRAG_THRESHOLD_MIN_PX == 18 and DRAG_CELL_RATIO == 0.35
    assert INVALID_SWAP_MS == 110
    from match3rules.constants import drag_threshold_px
    assert drag_threshold_px(40) == 18      # max(18, 40*0.35)=max(18,14)
    assert drag_threshold_px(60) == 21      # max(18, 21)
    assert drag_threshold_px(100) == 35
    assert drag_threshold_px(0) == 18


def test_s3_invalid_swap_bounce_no_cost():
    st = _nearwin_state()
    r = try_swap(st, 0, 0, 1, 0)            # 同色相邻交换 -> 无三连
    assert r["ok"] is False and r["reason"] == "invalid"
    assert st.moves_left == 5               # 不消耗步数


def test_s3_busy_ended_ignored():
    st = _nearwin_state()
    st.busy = True
    assert try_swap(st, 0, 1, 1, 1)["reason"] == "busy"
    st.busy, st.ended = False, True
    assert try_swap(st, 0, 1, 1, 1)["reason"] == "ended"
    st.ended = False
    assert try_swap(st, 0, 0, 2, 0)["reason"] == "notAdjacent"


# ---------------------------------------------------------------------------
# §4 消除 / 下落 / 补位 / 连消
# ---------------------------------------------------------------------------

def test_s4_match_mask_runs_and_crossings():
    g = [
        [0, 0, 0, 1],
        [0, 1, 1, 1],
        [0, 1, 0, 1],
        [1, 1, 0, 1],
    ]
    m = match_mask(g)
    # 行 run：row0 (0,0..2)；row1 (1,1..3)；row2/row3 无
    assert {(0, 0), (0, 1), (0, 2)} <= m
    assert {(1, 1), (1, 2), (1, 3)} <= m
    # 列 run：col0 rows0-2；col1 rows1-3；col3 全列
    assert {(0, 0), (1, 0), (2, 0)} <= m
    assert {(1, 1), (2, 1), (3, 1)} <= m
    assert {(0, 3), (1, 3), (2, 3), (3, 3)} <= m
    # col2 = [0,1,0,0]：rows2-3 只成对不成 run；(2,2)/(3,2) 也不属任何行 run
    assert (2, 2) not in m and (3, 2) not in m
    # 交叉处都算：交点 (1,1)（row1 run x col1 run）与 (1,3)（row1 run x col3 run）
    assert (1, 1) in m and (1, 3) in m
    assert m == {(0, 0), (0, 1), (0, 2), (1, 0), (2, 0),
                 (1, 1), (1, 2), (1, 3), (2, 1), (3, 1),
                 (0, 3), (1, 3), (2, 3), (3, 3)}


def test_s4_resolve_cascade_known_answer():
    # 脚本补位流（colors=2）：
    #   波2 六抽 [0,1,1,0,0,1] -> col0=[0,1,1], col1=[0,0,1]，row0 成 [0,0,0]
    #   波3 三抽 [0,1,0]      -> row0 成 [0,1,0,1,1]，无消即停
    q = ScriptedRng([0, 1, 1, 0, 0, 1, 0, 1, 0], 2)
    res = resolve([row[:] for row in GRID_CASCADE], 2, q)
    assert q.i == 9                          # 补位流恰消耗 9 次
    assert res.cascades == 2
    assert res.score == 120                  # 波1: 10*1*6=60；波2: 10*2*3=60 —— 第 w 波每格 10*w
    assert len(res.cleared) == 9
    assert {tuple(rc) for rc in res.cleared} == {
        (0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1),   # 波1: col0+col1
        (0, 0), (0, 1), (0, 2),                            # 波2: row0
    }
    # 波次步骤（match -> fall -> spawn 交替）
    assert [s["type"] for s in res.steps] == ["match", "fall", "spawn", "match", "fall", "spawn"]
    assert res.steps[0]["cells"] == [[0, 0], [0, 1], [1, 0], [1, 1], [2, 0], [2, 1]]
    assert res.steps[0]["score"] == 60 and res.steps[0]["wave"] == 1
    assert res.steps[3]["cells"] == [[0, 0], [0, 1], [0, 2]]
    assert res.steps[3]["score"] == 60 and res.steps[3]["wave"] == 2
    # 被清格是整列 -> 重力无位移
    assert res.steps[1]["moves"] == [] and res.steps[4]["moves"] == []
    # 补位顺序 = 列优先、每列自上而下（补位流可复现的关键）
    assert res.steps[2]["cells"] == [[0, 0], [1, 0], [2, 0], [0, 1], [1, 1], [2, 1]]
    assert res.steps[5]["cells"] == [[0, 0], [0, 1], [0, 2]]
    # 卡面 ResolveResult 五键
    assert set(res.to_dict().keys()) == {"steps", "cleared", "cascades", "score", "finalGrid"}
    # 终盘无消
    assert match_mask(res.finalGrid) == set()
    assert res.finalGrid == [
        [0, 1, 0, 1, 1],
        [1, 0, 1, 0, 1],
        [1, 1, 0, 1, 0],
    ]


def test_s4_resolve_gravity_records_moves():
    # 构造"中段成消、上下留存"的位移观测盘：row1 三连被清后，row0 三格各下落一格，
    # 顶部三格由补位流回填（脚本全 0 后无二次成消）。
    g = [
        [1, 1, 0],
        [0, 0, 0],
        [1, 0, 1],
    ]
    # 前置校验唯一初始 run：row1；col0=[1,0,1]、col1=[1,0,0]、col2=[0,0,1] 均否
    assert match_mask(g) == {(1, 0), (1, 1), (1, 2)}
    # 波2 补位脚本 [0,1,0]：row0=[0,1,0]（全 0 会造出 [0,0,0] 三连），col1=[1,1,0]、col2=[0,0,1] 均不成 run
    res = resolve(g, 2, ScriptedRng([0, 1, 0], 2))
    # 波数 = match 波次：仅波1 成消，补位后无消除即停 -> cascades == 1
    assert res.cascades == 1
    assert res.score == 30                  # 仅波1：10*1*3
    # 重力位移 {from,to}：row0 三格各 [0,c] -> [1,c]（自底向上压实）
    assert res.steps[1]["moves"] == [
        {"from": [0, 0], "to": [1, 0]},
        {"from": [0, 1], "to": [1, 1]},
        {"from": [0, 2], "to": [1, 2]},
    ]
    # 补位列优先、自上而下回填顶部三格
    assert res.steps[2]["cells"] == [[0, 0], [0, 1], [0, 2]]
    assert res.finalGrid == [
        [0, 1, 0],
        [1, 1, 0],
        [1, 0, 1],
    ]
    assert match_mask(res.finalGrid) == set()


def test_s4_wave_cap_64():
    # colors=1：每波整盘重消 -> 触及 64 波防死循环上限
    g = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
    res = resolve(g, 1, lambda: 0.0)
    assert res.cascades == MAX_WAVES == 64
    assert res.score == sum(10 * w * 9 for w in range(1, 65)) == 187200


# ---------------------------------------------------------------------------
# §5 计分与胜负
# ---------------------------------------------------------------------------

def test_s5_progress_jelly_cleared():
    q = ScriptedRng([0, 1, 1, 0, 0, 1, 0, 1, 0], 2)
    res = resolve([row[:] for row in GRID_CASCADE], 2, q)
    jelly = {(0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1)}   # col0+col1 六格果冻
    progress = len({tuple(rc) for rc in res.cleared} & jelly)
    assert progress == 6                       # clear-jelly 进度 = 已清果冻数


def test_s5_win_and_lose_predicates():
    # 胜：结算后 progress >= goalCount
    st = _nearwin_state(goal=3)
    r = try_swap(st, 0, 1, 1, 1)               # 唯一合法步 A 清 3 果冻
    assert r["ok"] is True and r["win"] is True and st.ended is True and st.win is True
    # 负：movesLeft <= 0（A 合法但目标不可达，1 步耗尽）
    st2 = _nearwin_state(goal=999, moves=1)
    r2 = try_swap(st2, 0, 1, 1, 1)
    assert r2["ok"] is True and st2.moves_left == 0
    assert st2.ended is True and st2.win is False


# ---------------------------------------------------------------------------
# §6 nearWin / failBait
# ---------------------------------------------------------------------------

def test_s6_nearwin_bounce_once_then_real_win():
    st = _nearwin_state(goal=3, attract_near_win=True)
    assert swap_would_win(st, Move(0, 1, 1, 1, "down"), k_of(st)) is True
    r = try_swap(st, 0, 1, 1, 1)
    assert r["ok"] is False and r["reason"] == "nearWin"
    assert st.moves_left == 5                  # 不耗步
    assert st.near_win_done is True            # 只触发一次
    # 呈现序列：先按非法交换回弹、再真实结算获胜
    seq = r["sequence"]
    assert seq[0]["act"] == "invalidSwap" and seq[0]["consumeMove"] is False
    assert seq[1]["act"] == "resolve" and seq[1]["outcome"] == "win" and seq[1]["consumeMove"] is True
    # 下次同样交换将真实结算获胜 —— 且用同一 k=1 补位流（先捕获盐再扣步数）
    r2 = try_swap(st, 0, 1, 1, 1)
    assert r2["ok"] is True and r2["k"] == 1
    assert r2["win"] is True and st.ended is True
    # 与直接用 deriveRng(seed, SPAWN_SALT ^ 1) 结算完全一致（同流）
    direct = resolve(swapped_grid(GRID_NEARWIN, Move(0, 1, 1, 1, "down")), 3,
                     derive_rng(42, SPAWN_SALT ^ 1))
    assert r2["result"]["finalGrid"] == direct.finalGrid
    assert r2["result"]["score"] == direct.score


def test_s6_nearwin_disabled_resolves_immediately():
    st = _nearwin_state(goal=3, attract_near_win=False)
    r = try_swap(st, 0, 1, 1, 1)
    assert r["ok"] is True and r["win"] is True and st.near_win_done is False


def test_s6_failbait_first_nonwinning_legal_swap_bounces_once():
    # 果冻取 (1,0)：A 合法但非胜（progress 0 < 999）
    st = _nearwin_state(goal=999, fail_bait_armed=True, jelly={(1, 0)})
    r = try_swap(st, 0, 1, 1, 1)               # A：合法且非胜
    assert r["ok"] is False and r["reason"] == "failBait"
    assert st.moves_left == 5 and st.fail_bait_done is True
    r2 = try_swap(st, 0, 1, 1, 1)              # 只一次：第二次真实结算
    assert r2["ok"] is True and st.moves_left == 4


def test_s6_failbait_not_armed_or_winning_swap_skips():
    st = _nearwin_state(goal=999, fail_bait_armed=False, jelly={(1, 0)})
    r = try_swap(st, 0, 1, 1, 1)
    assert r["ok"] is True                     # 未武装不回弹
    # 将胜的交换不吃 failBait（failBait 只管"非胜"合法交换）
    st2 = _nearwin_state(goal=3, fail_bait_armed=True)
    r2 = try_swap(st2, 0, 1, 1, 1)
    assert r2["ok"] is True and r2["win"] is True and st2.fail_bait_done is False


# ---------------------------------------------------------------------------
# §7 随机流与盐值
# ---------------------------------------------------------------------------

def test_s7_salt_constants():
    assert SPAWN_SALT == 0x51ED270B
    assert RESHUFFLE_SALT == 0x5117


def test_s7_mulberry32_matches_reference_transcription():
    for seed in (0, 1, 2, 42, 123456789, 0x7FFFFFFF):
        a, b = mulberry32(seed), _mulberry32_reference(seed)
        for _ in range(1000):
            assert a() == b()


def test_s7_imul32_is_low_32_of_product():
    assert imul32(3, 4) == 12
    assert imul32(0xFFFFFFFF, 2) == 0xFFFFFFFE
    assert imul32(0x10000, 0x10000) == 0
    for a, b in ((0xDEADBEEF, 0x9E3779B9), (0x51ED270B, 0x9E3779B9), (123456789, 987654321)):
        assert imul32(a, b) == (a * b) % 2 ** 32


def test_s7_derive_rng_identity():
    # deriveRng = mulberry32((seed ^ imul(salt, 0x9e3779b9)) >>> 0)
    for seed in (0, 1, 42, 0x7FFFFFFF):
        for salt in (SPAWN_SALT, RESHUFFLE_SALT, 0xDEADBEEF):
            expect_seed = (seed ^ ((salt * 0x9E3779B9) % 2 ** 32)) % 2 ** 32
            assert derive_seed(seed, salt) == expect_seed
            a, b = derive_rng(seed, salt), mulberry32(expect_seed)
            for _ in range(100):
                assert a() == b()


def test_s7_streams_differ_by_salt_and_k():
    s1 = [_spawn_rng(7, 1)() for _ in range(5)]
    s2 = [_spawn_rng(7, 2)() for _ in range(5)]
    sr = [derive_rng(7, RESHUFFLE_SALT ^ 1)() for _ in range(5)]
    assert s1 != s2 and s1 != sr


def test_s7_k_formula_and_salt_capture_before_decrement():
    st = _nearwin_state(moves=5)
    assert k_of(st) == 1                       # moves - movesLeft + 1 = 5-5+1
    st2 = _nearwin_state(goal=999, moves=5)
    r = try_swap(st2, 0, 1, 1, 1)
    assert r["k"] == 1                         # 捕获于扣步数之前
    assert st2.moves_left == 4 and k_of(st2) == 2


def test_s7_same_spawn_stream_for_estimate_and_settlement():
    # nearWin 预估 / 真实结算 / hint 投影 / 生成期 simulatePlay 四者同流（构造性验证前三者）
    st = _nearwin_state(goal=999)
    mv = Move(0, 1, 1, 1, "down")
    k = k_of(st)
    estimate = resolve(swapped_grid(st.grid, mv), 3, derive_rng(st.seed, SPAWN_SALT ^ k))
    r = try_swap(st, 0, 1, 1, 1)
    assert r["result"]["finalGrid"] == estimate.finalGrid
    assert r["result"]["score"] == estimate.score
    assert r["result"]["cascades"] == estimate.cascades


# ---------------------------------------------------------------------------
# §8 求解器与 hint
# ---------------------------------------------------------------------------

def test_s8_eval_formulas():
    # clear-jelly：果冻*1000 + score*2 + cascades*15
    assert eval_clear(0, 30, 1) == 75
    assert eval_clear(1, 30, 1) == 1075
    assert eval_clear(2, 45, 3) == 2000 + 90 + 45
    assert (EVAL_CLEAR_JELLY_WEIGHT, EVAL_CLEAR_SCORE_WEIGHT, EVAL_CLEAR_CASCADE_WEIGHT) == (1000, 2, 15)
    # score 模式：score*10 + cascades*15
    assert eval_score(30, 2) == 330
    assert (EVAL_SCORE_WEIGHT, EVAL_SCORE_CASCADE_WEIGHT) == (10, 15)


def test_s8_all_moves_scans_right_down_only():
    # 构造盘 12 个候选交换逐一手工验证：恰有唯一合法步 down(0,1)-(1,1)（见 GRID_NEARWIN 注）
    moves = all_moves(GRID_NEARWIN)
    assert moves == [Move(0, 1, 1, 1, "down")]
    assert all(m.dir in ("right", "down") for m in moves)
    assert all_moves(GRID_LATIN) == []
    assert has_any_move(GRID_NEARWIN) is True and has_any_move(GRID_LATIN) is False


def test_s8_best_move_picks_max_eval():
    # 唯一候选 A：清 3 果冻 -> win，eval = eval_clear(3, score, cascades)
    bm = best_move(GRID_NEARWIN, 3, 42, 1, "clear-jelly", 3, JELLY_ROW0)
    assert bm.move == Move(0, 1, 1, 1, "down")
    assert bm.win is True and bm.progress == 3
    assert bm.value == eval_clear(bm.jelly_cleared, bm.result.score, bm.result.cascades)


def test_s8_hint_projection_css_pixels():
    # 世界坐标 = CSS 像素；cellCenter 四舍五入取整；type 语义 = 从 (x,y) 格向该方向交换
    h = project_hint(Move(1, 2, 1, 3, "right"), Layout(cell=60, ox=0, oy=0))
    assert h == {"x": 150, "y": 90, "type": "swap-right"}     # (2+0.5)*60=150, (1+0.5)*60=90
    h2 = project_hint(Move(0, 0, 1, 0, "down"), Layout(cell=50))
    assert h2 == {"x": 25, "y": 25, "type": "swap-down"}
    # 四舍五入为 JS Math.round（.5 向上）：4.5+20=24.5 -> 25（Python round 会给 24）
    x, y = cell_center(Layout(cell=40, ox=4.5, oy=0.0), 0, 0)
    assert x == 25 and isinstance(x, int) and isinstance(y, int)
    assert js_round(2.5) == 3 and js_round(0.5) == 1 and js_round(-2.5) == -2


def test_s8_hint_end_to_end_and_null_cases():
    layout = Layout(cell=60)
    st = _nearwin_state()
    h = hint(st, layout)
    bm = best_move(st.grid, st.colors, st.seed, k_of(st), st.goal_type, st.goal_count, st.jelly)
    assert h == project_hint(bm.move, layout)
    assert h["type"] in ("swap-up", "swap-down", "swap-left", "swap-right")
    assert isinstance(h["x"], int) and isinstance(h["y"], int)
    # null：playing 无步（此时会触发 doReshuffle，hint 返回 null）
    dead = _nearwin_state()
    dead.grid = [row[:] for row in GRID_LATIN]
    dead.colors = 3
    assert hint(dead, layout) is None
    # null：busy / ended
    st.busy = True
    assert hint(st, layout) is None
    st.busy, st.ended = False, True
    assert hint(st, layout) is None
    st.ended = False
    # 教程相位：有步 -> 返回 demo（= bestMove）坐标；无步 -> 无 demo 返回 null
    st.phase = "tutorial"
    assert hint(st, layout) == project_hint(bm.move, layout)
    tut_dead = _nearwin_state()
    tut_dead.grid = [row[:] for row in GRID_LATIN]
    tut_dead.colors = 3
    tut_dead.phase = "tutorial"
    assert hint(tut_dead, layout) is None


# ---------------------------------------------------------------------------
# §7 推论：生成期可玩性 ⇔ hint 引导必胜
# ---------------------------------------------------------------------------

def test_s7_corollary_generate_winnable():
    results = []
    for seed in (1, 2, 3, 4, 5, 6):
        gw = generate_winnable(cols=4, rows=4, colors=4, seed=seed,
                               goal_type="clear-jelly", goal_count=6, moves=10)
        assert gw["attempt"] <= SIMULATE_RETRY == 64
        # 确定性：同 seed 重跑逐位一致
        gw2 = generate_winnable(cols=4, rows=4, colors=4, seed=seed,
                                goal_type="clear-jelly", goal_count=6, moves=10)
        assert gw["grid"] == gw2["grid"] and gw["jelly"] == gw2["jelly"] and gw["attempt"] == gw2["attempt"]
        # ⇔：对最终盘面按 hint 同款贪心重放，结果一致
        st = GameState(cols=4, rows=4, colors=4, seed=seed, goal_type="clear-jelly",
                       goal_count=6, moves=10, grid=[row[:] for row in gw["grid"]],
                       jelly=frozenset(gw["jelly"]), moves_left=10)
        replay = simulate_play(st)
        assert replay["win"] == gw["won"]
        # 未告警 ⇒ 必可胜
        if not gw["warned"]:
            assert gw["won"] is True
        results.append(gw)
    # 卡面"64 次仍不可胜概率上不会发生"：六个 seed 至少一个直接找到可胜盘面
    assert any(g["won"] for g in results)


def test_s7_simulate_play_includes_attract_and_reshuffle_streams():
    # attract 剧本不破坏可胜性：nearWin 弹一次后同交换真实获胜
    st = _nearwin_state(goal=3, attract_near_win=True)
    sim = simulate_play(st)
    assert sim["win"] is True
    assert any(t.get("reason") == "nearWin" for t in sim["trace"])
    # 死局重排走 0x5117 流：死局盘 + 不可达目标 -> 必现 reshuffle 且 k=1
    st2 = GameState(cols=3, rows=3, colors=3, seed=11, goal_type="clear-jelly",
                    goal_count=999, moves=2,
                    grid=[row[:] for row in GRID_LATIN], jelly=frozenset(), moves_left=2)
    sim2 = simulate_play(st2)
    assert sim2["win"] is False and sim2["ended"] is True
    rs = [t for t in sim2["trace"] if t["act"] == "reshuffle"]
    assert rs and rs[0]["k"] == 1
    if len(rs) > 1:
        assert rs[1]["k"] == 2                 # 第 k 步重排流的 k 随步数推进
    assert sim2["moves_left"] == 0


# ---------------------------------------------------------------------------
# §11 素材缺失行为（纯派生部分）
# ---------------------------------------------------------------------------

def test_s11_fnv1a_known_vectors():
    # FNV 常数（卡面）：2166136261 / 16777619
    assert fnv1a("") == 2166136261
    # 外部公认测试向量
    assert fnv1a("a") == 0xE40C292C
    assert fnv1a("foobar") == 0xBF9CF968


def test_s11_piece_style_derivation():
    h = fnv1a("piece-0")
    st = piece_style("piece-0", 3)
    assert st["shape"] in ("circle", "diamond", "square", "triangle", "hexagon")
    assert st["shape"] == ["circle", "diamond", "square", "triangle", "hexagon"][h % 5]
    assert st["palette"] == (h + 3) % 7
    assert 0 <= st["palette"] <= 6


# ---------------------------------------------------------------------------
# 冻结常数总表（卡面全部数值）
# ---------------------------------------------------------------------------

def test_frozen_constants_table():
    assert (FILL_MAX_ATTEMPTS, GENERATE_GUARD, RESHUFFLE_GUARD) == (32, 200, 200)
    assert MAX_WAVES == 64
    assert (MATCH_MS, FALL_MS, SPAWN_MS) == (150, 160, 170)
    assert WAVE_DELAYS_MS == (170, 180, 190)
    assert RESHUFFLE_SNAP_MS == 280 and RESHUFFLE_BUSY_MS == 560
    assert SIMULATE_RETRY == 64
    assert PF_END_BUDGET_S == 45
    assert BACKGROUND_COLOR == 0x141B34
