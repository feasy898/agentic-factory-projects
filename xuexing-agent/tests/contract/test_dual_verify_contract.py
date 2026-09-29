"""契约：dual_verify —— 双代理独立复验题库的确定性内核。

自封闭：全部夹具为字面 dict/str，不依赖 data/。只测公开 API 行为（比对规则表、
三值裁决、v2 记录合法性与纯回填、bank 顺序闭式、仲裁行、纯函数性），不测内部实现。
与 grading/itembank_v2 的一致性为跨模块行为锁定（测试可 import 多模块，实现不可）。
"""
import copy

import pytest

from xuexing.dual_verify import (
    COMPARISON_TOLERANCE,
    DualVerifyError,
    DualVerifyReport,
    UNIT_ALIASES,
    VERDICT_AGREE,
    VERDICT_DISAGREE,
    VERDICT_INCOMPLETE,
    answers_match,
    arbitration_rows,
    backfill_item,
    make_record,
    normalize_answer,
    verification_record,
    verify_bank,
    verify_item,
)
from xuexing.grading import GRADE_TOLERANCE, UNIT_ALIASES as GRADING_UNIT_ALIASES, normalize_answer as grading_normalize
from xuexing.itembank_v2 import validate_item_v2


def _fill(item_id="i1", answer="2", **over):
    base = {
        "id": item_id,
        "item_type": "fill",
        "stem": "s",
        "answer": answer,
        "kps": ["kp"],
        "difficulty": 0.5,
        "source": "original",
    }
    base.update(over)
    return base


def _choice(item_id="c1", answer="B", options=None, **over):
    base = {
        "id": item_id,
        "item_type": "choice",
        "stem": "s",
        "answer": answer,
        "kps": ["kp"],
        "difficulty": 0.5,
        "source": "original",
        "options": options if options is not None else ["A. 1", "B. 2", "C. 3", "D. 4"],
    }
    base.update(over)
    return base


# ---------- I1 常量冻结 ----------


def test_schema_constants():
    assert COMPARISON_TOLERANCE == GRADE_TOLERANCE == 1e-9
    assert UNIT_ALIASES == GRADING_UNIT_ALIASES
    assert (VERDICT_AGREE, VERDICT_DISAGREE, VERDICT_INCOMPLETE) == ("agree", "disagree", "incomplete")


# ---------- I2 归一化对齐 grading ----------


def test_normalize_matches_grading_on_battery():
    battery = [
        "－３００元", "２X", "  a   b  ", "1,234", "（4,1）", "X>2", "3或7。",
        "ＹＥＳ！", "0.50", "√2", "ＡＢＣ，ＤＥＦ；１２３", "", "　全程　。",
    ]
    for s in battery:
        assert normalize_answer(s) == grading_normalize(s), s


def test_normalize_rejects_non_str():
    for bad in (None, 42, ["x"], 3.14):
        with pytest.raises(DualVerifyError):
            normalize_answer(bad)


# ---------- I3 比对规则表 ----------


def test_match_literal_and_numeric():
    assert answers_match("左", "左") is True
    assert answers_match("左", "右") is False
    assert answers_match("25.25", "25.25") is True
    assert answers_match("1/2", "0.5") is True
    assert answers_match("50%", "1/2") is True
    assert answers_match("1/3", "0.33") is False
    assert answers_match("-300元", "-300元") is True
    assert answers_match("-300元", "-300") is False  # 单位门：key 带单位提案缺单位
    assert answers_match("80平方厘米", "80平方厘米") is True
    assert answers_match("80平方厘米", "80厘米") is False  # 异单位


def test_match_choice_labels_and_fulltext():
    opts = ["A. 1", "B. 2", "C. 3", "D. 4"]
    assert answers_match("B", "B", item_type="choice", options=opts) is True
    assert answers_match("B. 2", "B", item_type="choice", options=opts) is True
    assert answers_match("B", "b", item_type="choice", options=opts) is True  # N5 小写化
    assert answers_match("A", "B", item_type="choice", options=opts) is False
    assert answers_match("B", "3", item_type="choice", options=opts) is False


def test_match_multianswer_sets_and_prefixes():
    assert answers_match("3或7", "7或3") is True
    assert answers_match("-2或-8", "-8或-2") is True
    assert answers_match("x=5，y=2", "y=2，x=5") is True
    assert answers_match("x₁=7或x₂=-1", "x₂=-1或x₁=7") is True
    assert answers_match("16或18", "16或17") is False
    assert answers_match("3或7", "3") is False  # 数量不等
    assert answers_match("(4,1)", "(4,1)") is True  # ASCII 逗号不拆分
    assert answers_match("(-1,0)和(3,0)", "(3,0)和(-1,0)") is True


def test_match_literal_fallback_for_expressions():
    assert answers_match("x>2", "x>2") is True
    assert answers_match("x>2", "x≥2") is False
    assert answers_match("3.5×10^6", "3.5×10^6") is True
    assert answers_match("2√2+3", "2√2 + 3") is True  # 空白不敏感兜底
    assert answers_match("1:3", "1/3") is False  # 比号不与分数互化


def test_match_input_guards():
    with pytest.raises(DualVerifyError):
        answers_match(42, "2")
    with pytest.raises(DualVerifyError):
        answers_match("2", None)
    with pytest.raises(DualVerifyError):
        answers_match("2", "2", item_type="proof")
    with pytest.raises(DualVerifyError):
        answers_match("B", "B", item_type="choice", options=["A. 1"])
    with pytest.raises(DualVerifyError):
        answers_match("B", "B", item_type="choice", options=None)


# ---------- I4/I5 verify_item 裁决语义与输入守卫 ----------


def test_verify_item_verdicts():
    item = _fill()
    agree = verify_item(item, {"solver-a": "2", "solver-b": "2"})
    assert agree["item_id"] == "i1"
    assert agree["verdict"] == VERDICT_AGREE
    assert agree["statuses"] == (("solver-a", "match"), ("solver-b", "match"))

    disagree = verify_item(item, {"solver-a": "2", "solver-b": "3"})
    assert disagree["verdict"] == VERDICT_DISAGREE
    assert disagree["statuses"] == (("solver-a", "match"), ("solver-b", "mismatch"))

    # 有 mismatch 压倒 match 多数：分歧即仲裁，不因第三人一致而回填
    contested = verify_item(item, {"a": "2", "b": "3", "c": "2"})
    assert contested["verdict"] == VERDICT_DISAGREE

    incomplete_one = verify_item(item, {"solver-a": "2"})
    assert incomplete_one["verdict"] == VERDICT_INCOMPLETE
    incomplete_none = verify_item(item, {})
    assert incomplete_none["verdict"] == VERDICT_INCOMPLETE
    # no_answer 永不产生 mismatch：1 match + 1 缺席 → incomplete 而非分歧
    gap = verify_item(item, {"solver-a": "2", "solver-b": ""})
    assert gap["verdict"] == VERDICT_INCOMPLETE
    assert gap["statuses"] == (("solver-a", "match"), ("solver-b", "no_answer"))
    for absent in (None, 42, ["2"], "   "):
        st = verify_item(item, {"b": absent})["statuses"]
        assert st == (("b", "no_answer"),)


def test_verify_item_choice_item():
    item = _choice()
    ok = verify_item(item, {"a": "B", "b": "B. 2"})
    assert ok["verdict"] == VERDICT_AGREE
    bad = verify_item(item, {"a": "B", "b": "C"})
    assert bad["verdict"] == VERDICT_DISAGREE


def test_verify_item_input_guards():
    with pytest.raises(DualVerifyError):
        verify_item("not-a-dict", {"a": "2"})
    with pytest.raises(DualVerifyError):
        verify_item(_fill(id="  "), {"a": "2"})
    with pytest.raises(DualVerifyError):
        verify_item(_fill(answer="  "), {"a": "2"})
    with pytest.raises(DualVerifyError):
        verify_item(_fill(item_type="proof"), {"a": "2"})
    with pytest.raises(DualVerifyError):
        verify_item({"id": "c", "item_type": "choice", "answer": "A"}, {"a": "A"})
    with pytest.raises(DualVerifyError):
        verify_item(_fill(), ["2", "2"])
    with pytest.raises(DualVerifyError):
        verify_item(_fill(), {" lead": "2"})  # agent id 带首尾空白
    with pytest.raises(DualVerifyError):
        verify_item(_fill(), {"": "2"})


# ---------- I6 记录合法性与诚实回填 ----------


def test_record_only_for_agree_and_passes_itembank_v2():
    agree = verify_item(_fill(), {"b": "2", "a": "2"})
    rec = verification_record(agree)
    assert rec == {"agents": ["a", "b"], "answers_agree": True}
    assert validate_item_v2(_fill(verification=rec)) == []

    for result in (
        verify_item(_fill(), {"a": "2", "b": "3"}),  # disagree
        verify_item(_fill(), {"a": "2"}),  # incomplete
        verify_item(_fill(), {}),  # incomplete 空
    ):
        assert verification_record(result) is None


def test_make_record_sorted_dedup_and_floor():
    assert make_record(["b", "a"]) == {"agents": ["a", "b"], "answers_agree": True}
    assert make_record(["c", "a", "b", "a"]) == {"agents": ["a", "b", "c"], "answers_agree": True}
    rec = make_record(["z", "a"])
    assert validate_item_v2(_fill(verification=rec)) == []
    for few in ([], ["only-one"], ("x",)):
        with pytest.raises(DualVerifyError):
            make_record(few)
    with pytest.raises(DualVerifyError):
        make_record(["a", " a"])


def test_backfill_pure_and_validated():
    item = _fill()
    snapshot = copy.deepcopy(item)
    rec = {"agents": ["a", "b"], "answers_agree": True}
    out = backfill_item(item, rec)
    assert item == snapshot  # 入参不被修改
    assert out["verification"] == rec
    assert list(out)[:-1] == list(item)  # 原键原序，verification 追加在末尾
    assert validate_item_v2(out) == []

    unchanged = backfill_item(item, None)
    assert unchanged == item and "verification" not in unchanged
    assert unchanged is not item

    for bad in ({"agents": ["a"], "answers_agree": True},
                {"agents": ["a", "b"], "answers_agree": False},
                {"agents": ["a", "b"]}, "yes", 42):
        with pytest.raises(DualVerifyError):
            backfill_item(item, bad)


# ---------- I7/I8 bank 级顺序闭式与仲裁行 ----------


def _bank():
    return [
        _fill("i1", "2"),
        _fill("i2", "3或7"),
        _choice("i3", "B"),
        _fill("i4", "5"),
    ]


def _answers():
    return {
        "i1": {"a": "2", "b": "2"},
        "i2": {"a": "7或3", "b": "3或7"},  # a 走 R4 集合等值，b 走 R1 全串等值
        "i3": {"a": "B", "b": "C"},
        # i4 缺条目 → 空 dict → incomplete
    }


def test_verify_bank_order_and_closed_form():
    report = verify_bank(_bank(), _answers())
    assert isinstance(report, DualVerifyReport)
    assert report.item_ids == ("i1", "i2", "i3", "i4")
    assert report.verdicts == (
        ("i1", VERDICT_AGREE),
        ("i2", VERDICT_AGREE),
        ("i3", VERDICT_DISAGREE),
        ("i4", VERDICT_INCOMPLETE),
    )
    assert report.agreed_item_ids == ("i1", "i2")
    assert report.disputed_item_ids == ("i3",)
    assert report.incomplete_item_ids == ("i4",)
    assert report.records == (
        ("i1", {"agents": ["a", "b"], "answers_agree": True}),
        ("i2", {"agents": ["a", "b"], "answers_agree": True}),
        ("i3", None),
        ("i4", None),
    )
    assert report.counts() == {"agree": 2, "disagree": 1, "incomplete": 1}
    fresh = report.counts()
    fresh["agree"] = 999
    assert report.counts()["agree"] == 2  # 每次新 dict


def test_arbitration_rows_shape_and_order():
    rows = arbitration_rows(_bank(), _answers())
    assert rows == (
        {"item_id": "i3", "key_answer": "B", "agent": "b", "proposed": "C"},
    )
    # 同题多代理分歧：行按代理 id 升序
    items = [_fill("x1", "5")]
    rows2 = arbitration_rows(items, {"x1": {"z": "6", "a": "4", "m": "5"}})
    assert [(r["agent"], r["proposed"]) for r in rows2] == [("a", "4"), ("z", "6")]
    # 无分歧 → 空 tuple
    assert arbitration_rows(_bank(), {"i1": {"a": "2", "b": "2"}}) == ()


def test_verify_bank_input_guards():
    with pytest.raises(DualVerifyError):
        verify_bank(_bank(), ["nope"])
    with pytest.raises(DualVerifyError):
        arbitration_rows(_bank(), "nope")
    with pytest.raises(DualVerifyError):
        verify_bank([_fill(answer="")], {})


# ---------- I9 纯函数性 ----------


def test_purity_inputs_not_modified_and_repeatable():
    items = _bank()
    answers = _answers()
    snap_items = copy.deepcopy(items)
    snap_answers = copy.deepcopy(answers)
    first = verify_bank(items, answers)
    rows_first = arbitration_rows(items, answers)
    verify_item(items[0], answers["i1"])
    assert items == snap_items and answers == snap_answers
    assert verify_bank(items, answers) == first
    assert arbitration_rows(items, answers) == rows_first
    # 输出不得别名入参内部对象：改写首次输出的记录，不影响再次调用的输出与入参
    first.records[0][1]["agents"].append("intruder")
    assert verify_bank(items, answers).records[0][1]["agents"] == ["a", "b"]
    assert items == snap_items
