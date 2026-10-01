# -*- coding: utf-8 -*-
"""§12 数值算例逐值比对（本 gate 新增步——本轮核心断言）。

对回炉后规则卡 SPEC.md §12 的算例 A-F 逐值复算，另附 §11 纯派生表（卡面标注"已过真实
gate"的已知答案）。卡面 §12："本节算例是卡面的可执行验收物：镜像实现须逐条复算相符。"

记法换算：卡面 §12 用扁平 idx（= row*cols + col，行优先）与 {idx, piece} 对；本实现按冻结
eval 记法用 [row, col] 对——比对前统一换算为扁平 idx 后逐值比对。

已知分歧（回炉后卡面 vs 冻结 eval，均以冻结 eval 为准、在本 gate 记录为 info 项）：
- §12-D cleared "去重并集" 7 格 vs 冻结 len(cleared)==9（跨波不去重）：比对去重投影。
- §12-D 波形 "两波都无 fall 步" vs 冻结波形恒含 fall 步（moves==[]）：比对位移值（零位移）。

用法：python gate_examples.py  -> 打印 JSON 报告，退出码 0 = 逐值全符。
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from match3rules import (Layout, Move, SPAWN_SALT, all_moves, best_move, derive_seed,
                         eval_clear, eval_score, fnv1a, has_any_move, hint, js_round, mulberry32,
                         piece_style, resolve, swap_would_win, k_of)
from match3rules.game import GameState


# --- 比对脚手架 --------------------------------------------------------------

RESULTS = {}


def check(example, name, got, expect):
    ok = got == expect
    RESULTS[example]["checks"][name] = {"ok": ok, "got": _jsonable(got), "expect": _jsonable(expect)}
    return ok


def info(example, name, got, expect, note):
    """分歧记录项：不计入失败，但如实记入报告（卡面 vs 冻结 eval 记法/语义分歧的换算说明）。"""
    RESULTS[example]["checks"][name] = {"ok": True, "got": _jsonable(got),
                                        "expect": _jsonable(expect), "info": note}


def _jsonable(v):
    if isinstance(v, tuple):
        return [_jsonable(x) for x in v]
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    if isinstance(v, (int, float, str, bool)) or v is None:
        return v
    if isinstance(v, Move):
        return {"move": [v.row1, v.col1, v.row2, v.col2, v.dir]}
    return repr(v)


class ScriptedRng:
    """按脚本产色：第 i 次调用使 floor(x*colors) == values[i]（§12-D/E 的补位流逐抽注入）。"""

    def __init__(self, values, colors):
        self.values = list(values)
        self.colors = colors
        self.i = 0

    def __call__(self):
        assert self.i < len(self.values), "补位脚本耗尽：补位流消耗次数超出算例"
        v = self.values[self.i]
        self.i += 1
        return (v + 0.5) / self.colors


def flat(cell, cols):
    """[row, col] -> 扁平 idx = row*cols + col（卡面 §12 记法）。"""
    return cell[0] * cols + cell[1]


def flat_pairs(cells, cols):
    return [flat(c, cols) for c in cells]


def dedup_first(seq):
    """去重并保留首次出现序（§12 cleared 的"去重并集（按首次清除顺序）"）。"""
    seen, out = set(), []
    for v in seq:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


# --- 算例 --------------------------------------------------------------------

GRID_NEARWIN = [  # §12-B：3x3，colors=3，恰一合法步
    [1, 0, 1],
    [2, 1, 2],
    [0, 0, 2],
]
JELLY_ROW0 = frozenset({(0, 0), (0, 1), (0, 2)})

GRID_LATIN = [  # §12-C：3x3 拉丁方死局盘
    [0, 1, 2],
    [1, 2, 0],
    [2, 0, 1],
]

GRID_CASCADE = [  # §12-D：5 列 x 3 行，colors=2，两级连消
    [0, 1, 0, 1, 1],
    [0, 1, 1, 0, 1],
    [0, 1, 0, 1, 0],
]

GRID_GRAVITY = [  # §12-E：3x3，colors=2，重力位移观测盘
    [1, 1, 0],
    [0, 0, 0],
    [1, 0, 1],
]


def example_a():
    """算例 A——seed 首 5 抽（§7 mulberry32 内联块的向量，t|61 真源口径 = 重冻后的冻结
    oracle frozen.py:112-128 逐值复算；2026-09-29 属主裁决，此前误按 *61 变体）。"""
    ex = "A_seed_first5"
    RESULTS[ex] = {"title": "算例A seed首5抽+deriveSeed混合", "checks": {}}
    c = RESULTS[ex]["checks"]

    r1 = mulberry32(1)
    got1 = [r1() for _ in range(5)]
    c["A1_mulberry32(1)_first5@6dp"] = {
        "ok": all(abs(g - e) <= 5e-7 for g, e in zip(got1, [0.627074, 0.002736, 0.527447, 0.981051, 0.968378])),
        "got": [round(v, 6) for v in got1],
        "expect": [0.627074, 0.002736, 0.527447, 0.981051, 0.968378],
    }
    c["A1b_mulberry32(1)_first_full_precision"] = {
        "ok": got1[0] == 0.6270739405881613,
        "got": repr(got1[0]), "expect": repr(0.6270739405881613),
    }
    r42 = mulberry32(42)
    got42 = [r42() for _ in range(5)]
    c["A2_mulberry32(42)_first5@6dp"] = {
        "ok": all(abs(g - e) <= 5e-7 for g, e in zip(got42, [0.601104, 0.448291, 0.852466, 0.669734, 0.174814])),
        "got": [round(v, 6) for v in got42],
        "expect": [0.601104, 0.448291, 0.852466, 0.669734, 0.174814],
    }
    c["A3_deriveSeed(42, SPAWN_SALT^1)"] = {
        "ok": derive_seed(42, SPAWN_SALT ^ 1) == 0xDAFAF010,
        "got": hex(derive_seed(42, SPAWN_SALT ^ 1)), "expect": "0xdafaf010",
    }
    c["A4_deriveSeed(9, 0x5117^1)"] = {
        "ok": derive_seed(9, 0x5117 ^ 1) == 0x2647FEEF,
        "got": hex(derive_seed(9, 0x5117 ^ 1)), "expect": "0x2647feef",
    }


def example_b():
    """算例 B——恰一合法步盘：allMoves 恰为 [{x:1,y:0,dir:"down"}]，bestMove 将胜。"""
    ex = "B_exactly_one_move"
    RESULTS[ex] = {"title": "算例B 恰一合法步盘", "checks": {}}
    check(ex, "B1_allMoves==[{x:1,y:0,dir:down}](=Move(0,1,1,1,down))",
          all_moves(GRID_NEARWIN), [Move(0, 1, 1, 1, "down")])
    check(ex, "B2_hasAnyMove", has_any_move(GRID_NEARWIN), True)

    bm = best_move(GRID_NEARWIN, 3, 42, 1, "clear-jelly", 3, JELLY_ROW0)
    check(ex, "B3_bestMove.move", bm.move, Move(0, 1, 1, 1, "down"))
    check(ex, "B4_bestMove.win", bm.win, True)
    check(ex, "B5_bestMove.progress", bm.progress, 3)
    check(ex, "B6_bestMove.value==eval_clear(3,score,cascades)",
          bm.value, eval_clear(3, bm.result.score, bm.result.cascades))

    sw = GameState(cols=3, rows=3, colors=3, seed=42, goal_type="clear-jelly",
                   goal_count=3, moves=5, grid=[r[:] for r in GRID_NEARWIN],
                   jelly=frozenset(JELLY_ROW0), moves_left=5)
    check(ex, "B7_果冻=row0三格_该步将胜", swap_would_win(sw, Move(0, 1, 1, 1, "down"), k_of(sw)), True)
    sw2 = GameState(cols=3, rows=3, colors=3, seed=42, goal_type="clear-jelly",
                    goal_count=3, moves=5, grid=[r[:] for r in GRID_NEARWIN],
                    jelly=frozenset({(1, 0)}), moves_left=5)
    check(ex, "B8_果冻改取(1,0)_同一步合法但非胜",
          swap_would_win(sw2, Move(0, 1, 1, 1, "down"), k_of(sw2)), False)


def example_c():
    """算例 C——死局盘：allMoves=[]、hasAnyMove=false；playing hint 返回 null 并触发
    doReshuffle（0x5117 流，k=1）。"""
    ex = "C_dead_board"
    RESULTS[ex] = {"title": "算例C 死局盘", "checks": {}}
    check(ex, "C1_allMoves", all_moves(GRID_LATIN), [])
    check(ex, "C2_hasAnyMove", has_any_move(GRID_LATIN), False)

    st = GameState(cols=3, rows=3, colors=3, seed=9, goal_type="clear-jelly",
                   goal_count=3, moves=5, grid=[r[:] for r in GRID_LATIN],
                   jelly=frozenset({(1, 1)}), moves_left=5)
    got = hint(st, Layout(cell=60))
    check(ex, "C3_playing_hint_null", got, None)
    # 重排流逐值复刻：deriveRng(seed, 0x5117 ^ k)，k = moves - movesLeft + 1 = 1；
    # 守卫与冻结 eval s2 同构（首盘 + 至多 199 次重来，同一主流连续消耗）。
    from match3rules import RESHUFFLE_SALT, RESHUFFLE_GUARD, derive_rng, fill_no_matches
    rng = derive_rng(9, RESHUFFLE_SALT ^ 1)
    expect = fill_no_matches(3, 3, 3, rng)
    if not has_any_move(expect):
        for _ in range(RESHUFFLE_GUARD - 1):
            expect = fill_no_matches(3, 3, 3, rng)
            if has_any_move(expect):
                break
    check(ex, "C4_hint触发doReshuffle且盘面==0x5117流k=1复刻", st.grid, expect)
    check(ex, "C5_果冻保留", st.jelly, frozenset({(1, 1)}))


def example_d():
    """算例 D——两级连消盘波形（补位流脚本 [0,1,1,0,0,1,0,1,0] 逐抽注入）。"""
    ex = "D_cascade_wave"
    RESULTS[ex] = {"title": "算例D 两级连消盘波形", "checks": {}}
    cols = 5
    q = ScriptedRng([0, 1, 1, 0, 0, 1, 0, 1, 0], 2)
    res = resolve([r[:] for r in GRID_CASCADE], 2, q)

    check(ex, "D1_补位流恰消耗9次", q.i, 9)
    check(ex, "D2_cascades", res.cascades, 2)
    check(ex, "D3_score=120(60+60)", res.score, 120)

    wave_types = [s["type"] for s in res.steps]
    info(ex, "D4_波形(冻结eval恒含fall步;卡面§12省略空fall步)",
         wave_types, ["match", "fall", "spawn", "match", "fall", "spawn"],
         "冻结 eval pin 波形含 moves==[] 的 fall 步；卡面 §12-D 记 'match→spawn→match→spawn'。"
         "两记法下位移值同断言（见 D8）：两波 fall 位移均为空。")

    m1 = next(s for s in res.steps if s["type"] == "match" and s["wave"] == 1)
    m2 = next(s for s in res.steps if s["type"] == "match" and s["wave"] == 2)
    s1 = [s for s in res.steps if s["type"] == "spawn"][0]
    s2 = [s for s in res.steps if s["type"] == "spawn"][1]

    check(ex, "D5_波1match.cells扁平升序", flat_pairs(m1["cells"], cols), [0, 1, 5, 6, 10, 11])
    check(ex, "D6_波1spawn.cells列优先自上而下(idx,piece)",
          [(flat(c, cols), p) for c, p in zip(s1["cells"], s1["pieces"])],
          [(0, 0), (5, 1), (10, 1), (1, 0), (6, 0), (11, 1)])
    check(ex, "D7_波2match.cells扁平升序", flat_pairs(m2["cells"], cols), [0, 1, 2])
    check(ex, "D8_波2spawn.cells(idx,piece)",
          [(flat(c, cols), p) for c, p in zip(s2["cells"], s2["pieces"])],
          [(0, 0), (1, 1), (2, 0)])

    falls = [s for s in res.steps if s["type"] == "fall"]
    check(ex, "D9_两波fall位移均为空(整列/顶行被清贴底不动)",
          [f["moves"] for f in falls], [[], []])

    cleared_flat = flat_pairs(res.cleared, cols)
    check(ex, "D10_cleared去重投影(按首次清除序)=[0,1,5,6,10,11,2]7格",
          dedup_first(cleared_flat), [0, 1, 5, 6, 10, 11, 2])
    info(ex, "D10b_cleared原始长度", len(res.cleared), 9,
         "冻结 eval pin len(cleared)==9（跨波不去重，frozen.py:393）；卡面 §4/§12-D"
         "'去重并集'=7 格。按冻结 eval 实现；D10 的去重投影与 §12 逐值一致。")

    check(ex, "D11_终盘", res.finalGrid,
          [[0, 1, 0, 1, 1], [1, 0, 1, 0, 1], [1, 1, 0, 1, 0]])
    from match3rules import match_mask
    check(ex, "D12_终盘无消(波3补位后无消即停)", match_mask(res.finalGrid) == set(), True)


def example_e():
    """算例 E——重力位移观测盘（补位脚本 [0,1,0]）。"""
    ex = "E_gravity_moves"
    RESULTS[ex] = {"title": "算例E 重力位移观测盘", "checks": {}}
    cols = 3
    res = resolve([r[:] for r in GRID_GRAVITY], 2, ScriptedRng([0, 1, 0], 2))

    m1 = res.steps[0]
    check(ex, "E1_波1match.cells=[3,4,5]", flat_pairs(m1["cells"], cols), [3, 4, 5])
    fall = res.steps[1]
    check(ex, "E2_fall.moves扁平{from,to}序",
          [(flat(f["from"], cols), flat(f["to"], cols)) for f in fall["moves"]],
          [(0, 3), (1, 4), (2, 5)])
    spawn = res.steps[2]
    check(ex, "E3_spawn.cells=[0,1,2]列优先自上而下", flat_pairs(spawn["cells"], cols), [0, 1, 2])
    check(ex, "E4_spawn.pieces=[0,1,0]", spawn["pieces"], [0, 1, 0])
    check(ex, "E5_cascades", res.cascades, 1)
    check(ex, "E6_score=30", res.score, 30)
    check(ex, "E7_终盘", res.finalGrid, [[0, 1, 0], [1, 1, 0], [1, 0, 1]])


def example_f():
    """算例 F——评价值与取整。"""
    ex = "F_eval_and_rounding"
    RESULTS[ex] = {"title": "算例F 评价值与取整", "checks": {}}
    check(ex, "F1_eval_clear(0,30,1)=75", eval_clear(0, 30, 1), 75)
    check(ex, "F2_eval_clear(1,30,1)=1075", eval_clear(1, 30, 1), 1075)
    check(ex, "F3_eval_clear(2,45,3)=2135", eval_clear(2, 45, 3), 2000 + 90 + 45)
    check(ex, "F4_eval_score(30,2)=330", eval_score(30, 2), 330)
    check(ex, "F5_js_round(2.5)=3", js_round(2.5), 3)
    check(ex, "F6_js_round(0.5)=1", js_round(0.5), 1)
    check(ex, "F7_js_round(-2.5)=-2", js_round(-2.5), -2)
    check(ex, "F8_js_round(24.5)=25", js_round(24.5), 25)


def example_s11():
    """§11 纯派生表（卡面"已过真实 gate"的已知答案）：FNV 向量 + piece-0..4 外观表。"""
    ex = "S11_fnv_palette"
    RESULTS[ex] = {"title": "§11 FNV/形状/调色板已知答案", "checks": {}}
    check(ex, "S1_fnv1a('')", fnv1a(""), 2166136261)
    check(ex, "S2_fnv1a('a')=0xe40c292c", hex(fnv1a("a")), "0xe40c292c")
    check(ex, "S3_fnv1a('foobar')=0xbf9cf968", hex(fnv1a("foobar")), "0xbf9cf968")

    expect_table = [
        (0, "piece-0", 0x60244B58, "circle", 3, 0x4D96FF),
        (1, "piece-1", 0x61244CEB, "hexagon", 2, 0x2EC4B6),
        (2, "piece-2", 0x62244E7E, "triangle", 1, 0xFFC145),
        (3, "piece-3", 0x63245011, "square", 0, 0xFF5A5F),
        (4, "piece-4", 0x642451A4, "diamond", 6, 0x9ADF5D),
    ]
    for i, key, h, shape, palette, color in expect_table:
        st = piece_style(key, i)
        check(ex, "S4_i%d_hash" % i, fnv1a(key), h)
        check(ex, "S4_i%d_shape(h%%5)" % i, st["shape"], shape)
        check(ex, "S4_i%d_palette((h+i)%%7)" % i, st["palette"], palette)
        check(ex, "S4_i%d_color" % i, st["color"], color)


def run_all():
    for fn in (example_a, example_b, example_c, example_d, example_e, example_f, example_s11):
        fn()
    report = {
        "step": "§12 数值算例逐值比对（+§11 纯派生表）",
        "examples": RESULTS,
        "all_ok": all(c["ok"] for r in RESULTS.values() for c in r["checks"].values()),
        "total_checks": sum(len(r["checks"]) for r in RESULTS.values()),
        "failed_checks": [f"{ex}.{name}" for ex, r in RESULTS.items()
                          for name, c in r["checks"].items() if not c["ok"]],
    }
    return report


def main():
    report = run_all()
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
