"""契约：kt —— KT 时序追踪的可观测行为（同族于 diagnosis 的证据语义 + 遗忘曲线衰减）。

数值条款全部为手算可复核的闭式值（分数 -> round 6）：
a2(fill, 难0.5): slip=0.15, p_m=0.85, p_nm=0.10, lr_c=8.5, lr_w=1/6；
b1(fill, 难0.3): lr_c=8.9；d1(choice, 猜0.25): lr_c=3.4。
"""
import csv

import pytest

from xuexing.kt import (
    KTEvent,
    KTSnapshot,
    load_xes3g5m_csv,
    to_profile,
    trace,
    xes3g5m_row,
)
from xuexing.types import Item


def _add_item(bank, item_id, kps, difficulty=0.5, item_type="fill"):
    bank.add(Item(id=item_id, item_type=item_type, stem=f"stem-{item_id}", answer="ans",
                  kps=kps, difficulty=difficulty))


# ---------- 确定性与可重放 ----------

def test_determinism(small_bank, small_graph):
    evs = [KTEvent("a2", True, 0.0), KTEvent("b1", True, 3.0), KTEvent("a2", False, 7.0)]
    assert trace(evs, small_bank, small_graph) == trace(evs, small_bank, small_graph)


def test_empty_events(small_bank, small_graph):
    assert trace([], small_bank, small_graph) == []


def test_prefix_replay_consistency(small_bank, small_graph):
    # 可重放：重放任意前缀得到的最后一个快照，与全程轨迹对应位置逐字段相等
    evs = [KTEvent("a2", True, 0.0), KTEvent("b1", True, 3.0), KTEvent("a2", False, 7.0),
           KTEvent("d1", True, 8.0), KTEvent("b2", False, 21.0)]
    full = trace(evs, small_bank, small_graph)
    assert len(full) == 5
    for i in range(1, len(evs) + 1):
        prefix = trace(evs[:i], small_bank, small_graph)
        assert prefix[-1] == full[i - 1]


# ---------- 轨迹可解释性：闭式数值 ----------

def test_correct_evidence_closed_form(small_bank, small_graph):
    # 先验 0.5，odds=1；a2 答对 lr_c=8.5 -> odds=8.5 -> m=17/19
    snap = trace([KTEvent("a2", True, 0.0)], small_bank, small_graph)[0]
    assert snap.mastery["a"] == 0.894737  # round(17/19, 6)
    assert snap.evidence["a"] == 1
    assert snap.mastery["b"] == snap.mastery["c"] == snap.mastery["d"] == 0.5


def test_half_life_then_wrong_closed_form(small_bank, small_graph):
    # 第 7 天衰减恰为 17/38（半衰期=7）；答错再乘 lr_w=1/6 -> odds=17/126 -> m=17/143
    snaps = trace([KTEvent("a2", True, 0.0), KTEvent("a2", False, 7.0)],
                  small_bank, small_graph)
    assert snaps[0].mastery["a"] == 0.894737
    assert snaps[1].mastery["a"] == 0.118881  # round(17/143, 6)
    assert snaps[1].evidence["a"] == 2


def test_decay_exactly_halves_at_half_life(small_bank, small_graph):
    # 同一时钟走到第 7 天，a 无新证据 -> 掌握度恰为证据时刻的一半（17/38）
    snaps = trace([KTEvent("a2", True, 0.0), KTEvent("b1", True, 7.0)],
                  small_bank, small_graph)
    assert snaps[1].mastery["a"] == 0.447368  # round(17/38, 6) = 0.894737... / 2
    assert snaps[1].evidence["a"] == 1        # 衰减不消耗证据计数
    # b1(fill, 难0.3) 答对 lr_c=8.9 -> m = 8.9/9.9
    assert snaps[1].mastery["b"] == 0.898990
    assert snaps[1].evidence["b"] == 1


def test_decay_monotone_without_new_evidence(small_bank, small_graph):
    # 无新证据的知识点掌握度随时间严格递减（遗忘曲线），且证据计数不变
    evs = [KTEvent("a2", True, 0.0), KTEvent("b1", True, 3.0), KTEvent("b1", True, 10.0)]
    snaps = trace(evs, small_bank, small_graph)
    a1, a2, a3 = (s.mastery["a"] for s in snaps)
    assert a1 == 0.894737 and a2 == 0.664787 and a3 == 0.332393
    assert a1 > a2 > a3 > 0.0
    assert all(s.evidence["a"] == 1 for s in snaps)
    # 从未被作答的知识点恒为先验
    assert all(s.mastery["c"] == 0.5 for s in snaps)


def test_correct_lifts_wrong_drops_at_same_clock(small_bank, small_graph):
    base = trace([KTEvent("a2", True, 0.0)], small_bank, small_graph)[0].mastery["a"]
    decayed = 0.447368  # 第 7 天衰减基线（17/38）
    up = trace([KTEvent("a2", True, 0.0), KTEvent("a2", True, 7.0)],
               small_bank, small_graph)[-1].mastery["a"]
    down = trace([KTEvent("a2", True, 0.0), KTEvent("a2", False, 7.0)],
                 small_bank, small_graph)[-1].mastery["a"]
    assert up == 0.873112  # 衰减后答对：odds=17/21*8.5=289/42 -> m=289/331
    assert down == 0.118881
    assert decayed < up and down < decayed < base


def test_consecutive_correct_same_day_increases(small_bank, small_graph):
    # 同日连对：衰减因子为 1（Δ=0），掌握度严格上升
    snaps = trace([KTEvent("a2", True, 0.0), KTEvent("a2", True, 0.0)],
                  small_bank, small_graph)
    assert snaps[0].mastery["a"] == 0.894737
    assert snaps[1].mastery["a"] == 0.986348  # round(289/293, 6)
    assert snaps[1].mastery["a"] > snaps[0].mastery["a"]


def test_guess_aware_same_family_as_diagnosis(small_bank, small_graph):
    # 同为答对：选择题 guess=0.25 证据力弱于填空 guess=0.1
    hi = trace([KTEvent("d2", True, 0.0)], small_bank, small_graph)[0].mastery["d"]
    lo = trace([KTEvent("d1", True, 0.0)], small_bank, small_graph)[0].mastery["d"]
    assert hi == 0.894737 and lo == 0.772727  # lr_c=8.5 vs 3.4 -> 17/19 vs 17/22
    assert 0.5 < lo < hi


def test_multi_kp_primary_full_secondary_half(small_bank, small_graph):
    _add_item(small_bank, "ab1", ["a", "b"], difficulty=0.5)
    snap = trace([KTEvent("ab1", True, 0.0)], small_bank, small_graph)[0]
    # 主知识点权重 1.0：与同参数单知识点题完全一致
    assert snap.mastery["a"] == 0.894737
    assert snap.mastery["b"] == 0.744603  # round(sqrt(8.5)/(1+sqrt(8.5)), 6)
    assert 0.5 < snap.mastery["b"] < snap.mastery["a"]
    assert snap.evidence["a"] == snap.evidence["b"] == 1


# ---------- 容错行为 ----------

def test_unknown_item_dropped_and_clock_untouched(small_bank, small_graph):
    # 查不到的 item 整条跳过：不产生快照、不推进衰减时钟（遥折不变性）
    clean = trace([KTEvent("a2", True, 0.0), KTEvent("b1", True, 7.0)],
                  small_bank, small_graph)
    ghosted = trace([KTEvent("a2", True, 0.0), KTEvent("ghost", True, 7.0),
                     KTEvent("b1", True, 7.0)], small_bank, small_graph)
    assert len(ghosted) == 2
    assert [s.item_id for s in ghosted] == ["a2", "b1"]
    assert ghosted == clean


def test_graph_outside_kp_skipped(small_bank, small_graph):
    _add_item(small_bank, "az1", ["a", "zz"], difficulty=0.5)
    snap = trace([KTEvent("az1", True, 0.0)], small_bank, small_graph)[0]
    assert set(snap.mastery) == {"a", "b", "c", "d"}
    assert "zz" not in snap.evidence
    assert snap.evidence["a"] == 1


def test_snapshots_always_complete_and_in_range(small_bank, small_graph):
    evs = [KTEvent("a2", True, 0.0), KTEvent("b2", False, 3.0), KTEvent("c1", True, 100.0)]
    for snap in trace(evs, small_bank, small_graph):
        assert isinstance(snap, KTSnapshot)
        assert set(snap.mastery) == {"a", "b", "c", "d"}
        assert all(0.0 <= v <= 1.0 for v in snap.mastery.values())
        assert all(v >= 0 for v in snap.evidence.values())


def test_to_profile(small_bank, small_graph):
    snaps = trace([KTEvent("a2", True, 0.0), KTEvent("a2", False, 7.0)],
                  small_bank, small_graph)
    prof = to_profile(snaps[-1], "u1")
    assert prof.learner_id == "u1"
    assert prof.mastery == snaps[-1].mastery
    assert prof.evidence == snaps[-1].evidence
    assert prof.confidence("a") == pytest.approx(2 / 5)  # evidence=2 -> 2/(2+3)
    # 复制语义：改画像不影响快照
    prof.mastery["a"] = -1.0
    assert snaps[-1].mastery["a"] == 0.118881


# ---------- 输入校验 ----------

def test_invalid_params_rejected_even_with_empty_events(small_bank, small_graph):
    for bad_prior in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError):
            trace([], small_bank, small_graph, prior=bad_prior)
    for bad_h in (0.0, -1.0, float("nan")):
        with pytest.raises(ValueError):
            trace([], small_bank, small_graph, half_life_days=bad_h)


def test_invalid_days_rejected(small_bank, small_graph):
    with pytest.raises(ValueError):
        trace([KTEvent("a2", True, -1.0)], small_bank, small_graph)
    with pytest.raises(ValueError):  # 非降序被拒
        trace([KTEvent("a2", True, 5.0), KTEvent("b1", True, 3.0)],
              small_bank, small_graph)
    with pytest.raises(ValueError):  # NaN 经链式比较拒绝
        trace([KTEvent("a2", True, float("nan"))], small_bank, small_graph)
    with pytest.raises(ValueError):  # 非数字
        trace([KTEvent("a2", True, "3")], small_bank, small_graph)
    # 同日多事件合法
    assert len(trace([KTEvent("a2", True, 0.0), KTEvent("b1", True, 0.0)],
                     small_bank, small_graph)) == 2


# ---------- XES3G5M 对接 ----------

ROW = {"uid": "17", "questions": "101 102 103", "responses": "1 0 1",
       "timestamps": "0 86400000 172800000", "selectmasks": "1 1 1"}


def test_xes3g5m_row_mapping():
    uid, evs = xes3g5m_row(ROW)
    assert uid == "17"
    assert [(e.item_id, e.correct, e.day) for e in evs] == [
        ("101", True, 0.0), ("102", False, 1.0), ("103", True, 2.0)]


def test_xes3g5m_row_separator_and_mask_tolerance():
    comma = dict(ROW, questions="101,102,103", responses="1,0,1", timestamps="0,86400000,172800000")
    assert xes3g5m_row(comma)[1] == xes3g5m_row(ROW)[1]
    # 填充位（selectmasks="-1"）剔除后与未填充序列完全一致
    padded = dict(ROW, questions="101 102 103 -1 -1", responses="1 0 1 0 0",
                  timestamps="0 86400000 172800000 0 0", selectmasks="1 1 1 -1 -1")
    assert xes3g5m_row(padded)[1] == xes3g5m_row(ROW)[1]
    assert xes3g5m_row(dict(ROW, selectmasks="-1 -1 -1")) == ("17", [])
    # selectmasks 列缺失/空单元格 -> 全选
    nomask = {k: v for k, v in ROW.items() if k != "selectmasks"}
    assert xes3g5m_row(nomask)[1] == xes3g5m_row(ROW)[1]


def test_xes3g5m_row_day_conversion():
    _, evs = xes3g5m_row(dict(ROW, timestamps="0 3600000 86400000"))
    assert evs[1].day == 1 / 24  # 1 小时 = 1/24 天（IEEE 除法唯一结果）
    assert evs[2].day == 1.0


def test_xes3g5m_row_errors():
    for col in ("uid", "questions", "responses", "timestamps"):
        bad = {k: v for k, v in ROW.items() if k != col}
        with pytest.raises(ValueError):
            xes3g5m_row(bad)
    with pytest.raises(ValueError):  # 长度不齐
        xes3g5m_row(dict(ROW, responses="1 0"))
    with pytest.raises(ValueError):  # 掩码长度不齐
        xes3g5m_row(dict(ROW, selectmasks="1 1"))
    with pytest.raises(ValueError):  # 非法作答 token
        xes3g5m_row(dict(ROW, responses="1 2 1"))
    with pytest.raises(ValueError):  # 非法时间戳 token
        xes3g5m_row(dict(ROW, timestamps="0 x 2"))


def test_load_xes3g5m_csv(tmp_path):
    path = tmp_path / "seq.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["uid", "questions", "responses", "timestamps", "selectmasks"])
        w.writerow(["7", "101 102", "1 0", "0 86400000", "1 1"])
        w.writerow(["9", "201", "1", "5000", "1"])
    loaded = load_xes3g5m_csv(str(path))
    assert [uid for uid, _ in loaded] == ["7", "9"]
    assert [(e.item_id, e.correct, e.day) for e in loaded[0][1]] == [
        ("101", True, 0.0), ("102", False, 1.0)]
    assert loaded[1][1][0].day == 0.0
    assert load_xes3g5m_csv(str(path)) == loaded  # 文件 IO 亦确定
