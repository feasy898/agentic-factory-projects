"""契约：grading —— 主观题判分接口（归一化规则表 + 判分确定性）。

全部数值/布尔条款为手算可复核的闭式值（N1–N5 规则表 + IEEE 解析 + 1e-9 相对
容差，实测于 CPython 3.12 x64）。Item 鸭子类型自封闭，不依赖 data/ 夹具；
唯一例外是文末供 Response 的类型断言（types 属冻结契约面）。
"""
import dataclasses

import pytest

from xuexing.grading import (
    GRADE_TOLERANCE,
    UNIT_ALIASES,
    GradingError,
    grade,
    grade_choice,
    grade_fill,
    grade_to_response,
    normalize_answer,
    numeric_equal,
    parse_numeric,
    split_unit,
)
from xuexing.types import Item, Response


def _item(item_type="fill", answer="1/2", options=None, item_id="g1"):
    return Item(
        id=item_id, item_type=item_type, stem="stem", answer=answer,
        kps=["k"], difficulty=0.5, options=options or [],
    )


# ---------- 常量冻结（I1 前置） ----------

def test_frozen_constants():
    assert GRADE_TOLERANCE == 1e-9
    assert issubclass(GradingError, ValueError)
    # 规范闭包：每个值自身也是键
    assert all(v in UNIT_ALIASES for v in UNIT_ALIASES.values())
    # 别名归一（冻结的对照点）
    assert UNIT_ALIASES["公里"] == "千米"
    assert UNIT_ALIASES["平方公里"] == "平方千米"
    assert UNIT_ALIASES["公斤"] == "千克"
    assert UNIT_ALIASES["时"] == "小时"
    assert UNIT_ALIASES["分钟"] == "分"
    # 规范形自映射
    for canon in ("千米", "米", "千克", "元", "分", "小时", "度"):
        assert UNIT_ALIASES[canon] == canon


# ---------- N1–N5 归一化规则表（I1/I2） ----------

NORMALIZE_TABLE = [
    # N1 全角折叠
    ("３.５", "3.5"),
    ("１２３４５", "12345"),
    ("ＡＢｃ", "abc"),
    ("１，２３４", "1234"),
    ("　X＋１　", "x+1"),          # U+3000 空格 + 全角加号
    ("ｃ．ａ", "c.a"),
    # N2 空白折叠
    ("  3.5   元 ", "3.5 元"),
    ("a\n\tb", "a b"),
    # N3 尾部剥离
    ("3.5。", "3.5"),
    ("3 。", "3"),
    ("c.", "c"),
    ("三角形、", "三角形"),
    # N4 千分位逗号
    ("1,234", "1234"),
    ("1,234,567", "1234567"),
    ("1,234.5", "1234.5"),
    ("12,34", "12,34"),            # 非 3 位分组 → 保留
    ("1,2345", "1,2345"),          # 第 4 位仍是数字 → 保留
    ("(4,1)", "(4,1)"),            # 坐标逗号保留
    ("(-1,-1)", "(-1,-1)"),
    ("x=5，y=2", "x=5,y=2"),       # 逗号后非数字 → 保留
    # N5 小写化
    ("ACE", "ace"),
    ("X+1", "x+1"),
    # 组合
    ("３.５元", "3.5元"),
    ("－300元", "-300元"),         # 全角负号 U+FF0D
    ("＜", "<"),
]


@pytest.mark.parametrize("raw,expected", NORMALIZE_TABLE)
def test_normalize_rule_table(raw, expected):
    assert normalize_answer(raw) == expected


@pytest.mark.parametrize("raw,_", NORMALIZE_TABLE)
def test_normalize_idempotent_on_rule_table(raw, _):
    assert normalize_answer(normalize_answer(raw)) == normalize_answer(raw)


def test_normalize_rejects_non_str():
    for bad in (None, 5, 3.5, True, b"3", ["3"]):
        with pytest.raises(GradingError):
            normalize_answer(bad)


# ---------- parse_numeric（§3.3 全表） ----------

PARSE_TABLE = [
    # 百分数
    ("50%", 0.5), ("50 %", 0.5), ("-50%", -0.5), ("1/2%", 0.005),
    ("1 1/2%", 0.015), ("50%%", None),
    # 带分数
    ("1 1/2", 1.5), ("1 2/4", 1.5), ("-1 1/2", -1.5), ("1 1 / 2", 1.5),
    ("1 1/0", None),
    # 分数
    ("1/2", 0.5), ("2/4", 0.5), ("1 / 2", 0.5), ("1 /2", 0.5), ("0/5", 0.0),
    ("3/0", None), ("-1/2", -0.5),
    # 小数
    ("0.5", 0.5), ("-8", -8.0), ("+3", 3.0), (".5", 0.5), ("3.", 3.0),
    ("1e3", 1000.0),
    # 不可解析
    ("", None), ("abc", None), ("1 2", None), ("--1", None), ("3..5", None),
    ("nan", None), ("inf", None), ("Infinity", None),
]


@pytest.mark.parametrize("text,expected", PARSE_TABLE)
def test_parse_numeric_table(text, expected):
    assert parse_numeric(text) == expected


def test_parse_numeric_rejects_non_str():
    for bad in (None, 42, True, 0.5):
        with pytest.raises(GradingError):
            parse_numeric(bad)


# ---------- split_unit（§3.4 全表） ----------

SPLIT_TABLE = [
    ("3.5元", ("3.5", "元")),
    ("2千米", ("2", "千米")),
    ("2公里", ("2", "千米")),
    ("3平方米", ("3", "平方米")),      # 长后缀优先于 米
    ("3平方公里", ("3", "平方千米")),
    ("30分钟", ("30", "分")),
    ("30分", ("30", "分")),
    ("2时", ("2", "小时")),
    ("2小时", ("2", "小时")),
    ("2公斤", ("2", "千克")),
    ("3 米", ("3", "米")),             # 剩余部 strip
    ("50%", ("50%", None)),            # % 不是单位
    ("元", ("元", None)),              # 纯单位词不拆
    ("2kg", ("2kg", None)),            # 表外写法
    ("1小时30分", ("1小时30", "分")),
]


@pytest.mark.parametrize("text,expected", SPLIT_TABLE)
def test_split_unit_table(text, expected):
    assert split_unit(text) == expected


def test_split_unit_does_not_normalize():
    # 本函数不做归一化：尾部空格阻断单位命中
    assert split_unit("3.5元 ") == ("3.5元 ", None)
    assert split_unit(normalize_answer(" 3.5 元 ")) == ("3.5", "元")


# ---------- numeric_equal（§3.5 ε 语义） ----------

def test_numeric_equal_tolerance_semantics():
    assert numeric_equal(1 / 3, float("0." + "3" * 16)) is True
    assert numeric_equal(1 / 3, 0.33) is False
    assert numeric_equal(0.5, 0.5 + 5e-10) is True
    assert numeric_equal(1.0, 1.0 + 2e-9) is False
    assert numeric_equal(0.0, 1e-12) is True
    assert numeric_equal(0.5, 0.25) is False
    cases = [(1 / 3, 0.3333333333333333), (0.5, 0.5 + 5e-10), (0.5, 0.25)]
    for a, b in cases:  # 交换对称
        assert numeric_equal(a, b) == numeric_equal(b, a)


# ---------- grade_fill（§3.7 行为表） ----------

def test_numeric_equivalence_closure():
    it = _item(answer="1/2")
    for good in ("0.5", "2/4", "50%", "１/２", "1 /2", "0.5 "):
        assert grade_fill(it, good) is True, good
    # 闭包：规范值两两互判
    forms = ["0.5", "1/2", "2/4", "50%"]
    for a in forms:
        for b in forms:
            assert grade_fill(_item(answer=a), b) is True, (a, b)


def test_fill_unknown_and_empty_answers():
    it = _item(answer="1/2")
    assert grade_fill(it, None) is False          # 未作答
    assert grade_fill(it, "") is False
    assert grade_fill(it, "   ") is False
    assert grade_fill(it, "abc") is False
    assert grade(it, None) is False


def test_unit_gate():
    assert grade_fill(_item(answer="-300元"), "－300元") is True
    assert grade_fill(_item(answer="-300元"), " -300 元 ") is True
    assert grade_fill(_item(answer="-300元"), "-300") is False      # 缺单位
    assert grade_fill(_item(answer="-300元"), "-300米") is False    # 异单位
    assert grade_fill(_item(answer="-300元"), "-600元") is False
    assert grade_fill(_item(answer="-300元"), "负300元") is False   # 字面支
    assert grade_fill(_item(answer="2米"), "2 米") is True
    assert grade_fill(_item(answer="2米"), "2") is False
    assert grade_fill(_item(answer="2米"), "2公里") is False        # 别名≠换算
    assert grade_fill(_item(answer="2米"), "2千米") is False        # 无换算
    assert grade_fill(_item(answer="2米"), "两米") is False
    assert grade_fill(_item(answer="30%"), "0.3") is True           # % 是数值不是单位
    assert grade_fill(_item(answer="30%"), "3/10") is True
    assert grade_fill(_item(answer="30%"), "30 %") is True
    assert grade_fill(_item(answer="30%"), "0.31") is False
    assert grade_fill(_item(answer="30%"), "0.3元") is False
    assert grade_fill(_item(answer="1 1/2"), "1.5") is True
    assert grade_fill(_item(answer="1 1/2"), "3/2") is True
    assert grade_fill(_item(answer="1 1/2"), "１ １/２") is True
    assert grade_fill(_item(answer="1 1/2"), "1 2/4") is True
    assert grade_fill(_item(answer="1 1/2"), "11/2") is False       # 5.5


def test_literal_string_branch():
    assert grade_fill(_item(answer="x+1"), "X＋1") is True
    assert grade_fill(_item(answer="x+1"), "x + 1") is True
    assert grade_fill(_item(answer="x+1"), "x+2") is False
    assert grade_fill(_item(answer="x+1"), "2x+1") is False
    assert grade_fill(_item(answer="鸡6只，兔4只"), "鸡 6 只，兔 4 只") is True
    assert grade_fill(_item(answer="鸡6只，兔4只"), "鸡7只，兔4只") is False
    assert grade_fill(_item(answer="<"), "<") is True
    assert grade_fill(_item(answer="<"), "＞") is False
    assert grade_fill(_item(answer="<"), "≤") is False


def test_coordinate_comma():
    it = _item(answer="(4,1)")
    assert grade_fill(it, "(4,1)") is True
    assert grade_fill(it, "(4, 1)") is True       # 等值键删空白
    assert grade_fill(it, "(4，1)") is True       # 全角逗号折叠后仍保坐标
    assert grade_fill(it, "(4,2)") is False
    assert grade_fill(it, "(41)") is False        # 千分位规则未吃掉坐标逗号


# ---------- grade_choice（§3.8） ----------

def _choice_item(answer="C", options=None, item_id="c1"):
    if options is None:
        options = ["A. -2a>-2b", "B. ac²>bc²", "C. a-1>b-1", "D. 1/a<1/b"]
    return _item(item_type="choice", answer=answer, options=options, item_id=item_id)


def test_grade_choice_label_and_text():
    it = _choice_item()
    for good in ("C", "c", "c.", " C ", "C. a-1>b-1", "c．a-1>b-1"):
        assert grade(it, good) is True, good
    for bad in ("A", "D", "a-1>b-1", "E", "2", "", "   "):
        assert grade(it, bad) is False, bad
    assert grade(it, None) is False


def test_grade_choice_answer_stored_as_full_text():
    it = _choice_item(answer="A. x≤3",
                      options=["A. x≤3", "B. x≥3", "C. x≤-3", "D. x>3"])
    assert grade(it, "a") is True
    assert grade(it, "A") is True
    assert grade(it, "b") is False
    assert grade(it, "x≤3") is False               # 全文片段不算


def test_grade_choice_chinese_labels():
    it = _choice_item(answer="乙", options=["甲. 3", "乙. 4"])
    assert grade(it, "乙") is True
    assert grade(it, "甲") is False
    assert grade(it, "3") is False


def test_grade_choice_invalid_item_raises_but_none_short_circuits():
    bad = _choice_item(answer="E")                 # 答案不在选项中
    assert grade(bad, None) is False               # 未作答短路优先
    with pytest.raises(GradingError):
        grade(bad, "A")
    empty = _choice_item(answer="A", options=[])
    with pytest.raises(GradingError):
        grade(empty, "A")


# ---------- 分派与错误（I7） ----------

def test_grade_dispatch_and_errors():
    assert grade(_item(item_type="solve", answer="4"), "4.0") is True
    assert grade(_item(item_type="solve", answer="4"), "4") is True
    assert grade(_item(item_type="solve", answer="4"), "5") is False
    assert grade(_item(item_type="fill", answer="1/2"), "50%") is True
    for bad_type in ("true_false", "", "multi"):
        with pytest.raises(GradingError):
            grade(_item(item_type=bad_type, answer="1/2"), "0.5")
    with pytest.raises(GradingError):
        grade(_item(answer="1/2"), 5)              # 非 str 非 None
    with pytest.raises(GradingError):
        grade(_item(answer="1/2"), 0.5)


# ---------- grade_to_response（I8） ----------

def test_grade_to_response():
    it = _choice_item(item_id="c9")
    r = grade_to_response(it, "c")
    assert isinstance(r, Response)
    assert r.item_id == "c9"
    assert r.correct is True
    assert r.learner_answer == "c"
    assert r.response_ms is None
    r2 = grade_to_response(it, "A", 1234)
    assert r2.correct is False
    assert r2.response_ms == 1234
    assert grade_to_response(it, "c") == r         # dataclass 相等可复判


# ---------- 确定性与纯度（I9/I10） ----------

def test_determinism():
    it = _choice_item()
    fill = _item(answer="-300元")
    assert {grade(it, "c") for _ in range(30)} == {True}
    assert {grade(it, "A") for _ in range(30)} == {False}
    assert {grade(fill, "－300元") for _ in range(30)} == {True}
    assert {normalize_answer("３.５。") for _ in range(30)} == {"3.5"}
    assert {parse_numeric("1 1/2") for _ in range(30)} == {1.5}
    assert {split_unit("2公里") for _ in range(30)} == {("2", "千米")}


def test_purity():
    it = _choice_item()
    before = dataclasses.asdict(it)
    grade(it, "c. a-1>b-1")
    grade(it, "A")
    assert dataclasses.asdict(it) == before
