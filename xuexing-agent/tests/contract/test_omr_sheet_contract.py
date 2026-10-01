"""契约：omr_sheet —— OMR 答题卡对接规范（题号-选项映射 + OMRChecker 输出适配层）。

全部数值条款为手算可复核的闭式值（实测于 CPython 3.12 x64）。
paper/bank 均按鸭子类型自封闭小夹具（Paper 用真实 types.Paper，bank 用最小 items()
桩），不依赖 data/ 夹具；跨模块锁定（paper_layout.parse_option / grading.grade_choice
一致性、generate_paper 端到端）在测试内 import 对方模块断言，被测模块间零 import。
"""
import copy
import json

import pytest

from xuexing.omr_sheet import (
    BLOCK_DIRECTION,
    FIELD_PREFIX,
    MAX_BUBBLES,
    MODE_MANUAL,
    MODE_OMR,
    OMR_VERSION,
    OMRError,
    RESULTS_FILE_ID_COLUMN,
    build_answer_sheet,
    field_label,
    natural_sort_key,
    parse_field_ranges,
    parse_omr_results,
    parse_option,
    to_responses,
)
from xuexing.types import Paper, Response


# ---------- 自封闭小夹具 ----------

class _DuckItem:
    def __init__(self, item_id, item_type, answer, options=None, stem="题"):
        self.id = item_id
        self.item_type = item_type
        self.stem = stem
        self.answer = answer
        self.options = list(options or [])
        self.solution = f"SOL-{item_id}"
        self.misconceptions = ["mc-x"]


class _DuckBank:
    def __init__(self, items):
        self._items = list(items)

    def items(self):
        return list(self._items)


ITEMS = [
    _DuckItem("c1", "choice", "B", ["A. 0", "B. -2/3", "C. +1.5", "D. 2026"]),
    _DuckItem("f1", "fill", "-300元"),
    _DuckItem("s1", "solve", "x=12"),
    _DuckItem("f2", "fill", "5/6"),
    _DuckItem("c2", "choice", "2", ["2", "3"]),  # 无显式标签 -> 按位回退 A/B
]
BANK = _DuckBank(ITEMS)

SECTIONS = [
    {"kp_id": "a", "kp_name": "有理数", "item_ids": ["c1", "f1"]},
    {"kp_id": "b", "kp_name": "一元一次方程", "item_ids": ["s1", "f2", "c2"]},
]


def _paper(sections=SECTIONS, item_ids=None, paper_id="paper-77", title="七年级诊断卷"):
    return Paper(
        paper_id=paper_id,
        title=title,
        blueprint={},
        item_ids=item_ids if item_ids is not None else
        [iid for s in sections for iid in s["item_ids"]],
        sections=[dict(s) for s in sections],
    )


def _sheet(**kw):
    return build_answer_sheet(_paper(**kw), BANK)


def _row(marks, file_id="scan001.jpg", extra_cols=None):
    values = dict(extra_cols or {})
    values.update(marks)
    return {"file_id": file_id, "values": values}


RESULTS_CSV = (
    "file_id,input_path,output_path,score,q1,q2,q3,q5\r\n"
    "scan001.jpg,in/001.jpg,out/001.jpg,1.0,B,,A,C\r\n"
    "scan002.jpg,in/002.jpg,out/002.jpg,2.0,AC,B,A,\r\n"
)


# ---------- I1 常量冻结 ----------

def test_frozen_constants():
    assert OMR_VERSION == "1"
    assert FIELD_PREFIX == "q"
    assert MODE_OMR == "omr" and MODE_MANUAL == "manual"
    assert BLOCK_DIRECTION == "horizontal"
    assert MAX_BUBBLES == 26
    assert RESULTS_FILE_ID_COLUMN == "file_id"
    assert issubclass(OMRError, ValueError)


# ---------- I2 选项标签解析（与 paper_layout 跨模块锁定） ----------

def test_parse_option_closed_forms():
    assert parse_option("A. 0", 0) == ("A", "0")
    assert parse_option("b、题干", 0) == ("B", "题干")
    assert parse_option("C）文本", 0) == ("C", "文本")
    assert parse_option("D．四", 0) == ("D", "四")
    assert parse_option("2", 1) == ("B", "2")
    assert parse_option("(4,1)", 3) == ("D", "(4,1)")
    assert parse_option("  B. 2  ", 0) == ("B", "2")
    assert parse_option("A.", 0) == ("A", "")


def test_parse_option_matches_paper_layout_on_battery():
    from xuexing.paper_layout import parse_option as pl_parse_option

    battery = ["A. 0", "b、题", "C）x", "2", "（4,1）", "x=5", "A.", "E．正",
               "25%", "π/2", "  D. 2  ", "a)项", "Z、廿六"]
    for position in range(0, 26, 5):
        for text in battery:
            if not text.strip():
                continue
            assert parse_option(text, position) == pl_parse_option(text, position), (
                text, position)


def test_parse_option_input_guards():
    for bad_args in (("", 0), (None, 0), (5, 0), ("x", 26), ("x", -1),
                     ("x", True), ("x", 1.0)):
        with pytest.raises(OMRError):
            parse_option(*bad_args)


# ---------- I3 列名/字段串/自然排序闭式 ----------

def test_field_label_closed_forms():
    assert field_label(1) == "q1"
    assert field_label(5) == "q5"
    assert field_label(105) == "q105"
    for bad in (0, -2, True, 2.0, "3", None):
        with pytest.raises(OMRError):
            field_label(bad)


def test_parse_field_ranges_closed_forms():
    assert parse_field_ranges([1, 2, 3, 4]) == ["q1..4"]
    assert parse_field_ranges([1, 3]) == ["q1", "q3"]
    assert parse_field_ranges([1, 2, 4, 5, 6]) == ["q1..2", "q4..6"]
    assert parse_field_ranges([9, 10, 11]) == ["q9..11"]
    assert parse_field_ranges([5]) == ["q5"]
    assert parse_field_ranges([]) == []
    assert parse_field_ranges([4, 1, 4, 2]) == ["q1..2", "q4"]  # 去重升序
    for bad_numbers in ("1", [0], [True], [1.0], [-1], None, {"q1"}):
        with pytest.raises(OMRError):
            parse_field_ranges(bad_numbers)


def test_natural_sort_key_closed_forms():
    assert natural_sort_key("q12") == ["q", 12]
    assert natural_sort_key("q1") == ["q", 1]
    assert natural_sort_key("roll") == ["roll", 0]
    assert natural_sort_key("q2") < natural_sort_key("q10")
    assert sorted(["q10", "q2", "q1"], key=natural_sort_key) == ["q1", "q2", "q10"]
    for bad in ("", None, 5):
        with pytest.raises(OMRError):
            natural_sort_key(bad)


# ---------- I4/I5 sheet 映射闭环 + 不泄答案 ----------

def test_sheet_top_level_shape_and_question_entries():
    doc = _sheet()
    assert set(doc) == {
        "format_version", "paper_id", "title", "question_count", "omr_count",
        "manual_count", "questions", "output_columns", "field_blocks",
    }
    assert doc["format_version"] == "1"
    assert doc["paper_id"] == "paper-77"
    assert doc["title"] == "七年级诊断卷"
    assert doc["question_count"] == 5
    assert doc["omr_count"] == 2 and doc["manual_count"] == 3
    qs = doc["questions"]
    assert [q["number"] for q in qs] == [1, 2, 3, 4, 5]
    assert [q["item_id"] for q in qs] == ["c1", "f1", "s1", "f2", "c2"]
    assert [q["mode"] for q in qs] == ["omr", "manual", "manual", "manual", "omr"]
    assert [q["field_label"] for q in qs] == ["q1", None, None, None, "q5"]
    assert qs[0]["bubble_values"] == ["A", "B", "C", "D"]
    assert qs[0]["options"] == [
        {"label": "A", "text": "0"}, {"label": "B", "text": "-2/3"},
        {"label": "C", "text": "+1.5"}, {"label": "D", "text": "2026"},
    ]
    assert qs[1] == {"number": 2, "item_id": "f1", "mode": "manual",
                     "field_label": None, "bubble_values": [], "options": []}
    assert qs[4]["bubble_values"] == ["A", "B"]  # 无显式标签 -> 位置回退
    assert qs[4]["options"] == [{"label": "A", "text": "2"}, {"label": "B", "text": "3"}]
    assert all(set(q) == {"number", "item_id", "mode", "field_label",
                          "bubble_values", "options"} for q in qs)


def test_sheet_output_columns_and_field_blocks_closed():
    doc = _sheet()
    assert doc["output_columns"] == ["q1", "q5"]
    assert doc["field_blocks"] == [
        {"name": "block1", "field_labels": ["q1"],
         "bubble_values": ["A", "B", "C", "D"], "direction": "horizontal"},
        {"name": "block2", "field_labels": ["q5"],
         "bubble_values": ["A", "B"], "direction": "horizontal"},
    ]


def test_sheet_field_block_merging_rules():
    four = _DuckItem("c4", "choice", "A", ["A. 1", "B. 2", "C. 3", "D. 4"])
    bank = _DuckBank([four, ITEMS[1]])
    # 同节、同气泡表；遇手工题断段 -> q1 / q3 各成一段（手工题只占题号，不出列）
    secs = [{"kp_name": "甲", "item_ids": ["c4", "f1", "c4"]}]
    doc = build_answer_sheet(_paper(sections=secs), bank)
    assert doc["field_blocks"] == [
        {"name": "block1", "field_labels": ["q1"],
         "bubble_values": ["A", "B", "C", "D"], "direction": "horizontal"},
        {"name": "block2", "field_labels": ["q3"],
         "bubble_values": ["A", "B", "C", "D"], "direction": "horizontal"}]
    # 跨节 -> 断段；气泡表不同 -> 断段；编号仍贯穿全卷
    two = _DuckItem("c2x", "choice", "B", ["A. 1", "B. 2"])
    bank2 = _DuckBank([four, two])
    secs2 = [
        {"kp_name": "甲", "item_ids": ["c4", "c4"]},
        {"kp_name": "乙", "item_ids": ["c2x"]},
    ]
    doc2 = build_answer_sheet(_paper(sections=secs2), bank2)
    assert doc2["output_columns"] == ["q1", "q2", "q3"]
    assert doc2["field_blocks"] == [
        {"name": "block1", "field_labels": ["q1..2"],
         "bubble_values": ["A", "B", "C", "D"], "direction": "horizontal"},
        {"name": "block2", "field_labels": ["q3"],
         "bubble_values": ["A", "B"], "direction": "horizontal"},
    ]
    # 全 manual 卷 -> 无 blocks、output_columns 空
    doc3 = build_answer_sheet(
        _paper(sections=[{"kp_name": "甲", "item_ids": ["f1"]}], item_ids=["f1"]),
        _DuckBank([ITEMS[1]]))
    assert doc3["field_blocks"] == [] and doc3["output_columns"] == []
    assert doc3["omr_count"] == 0 and doc3["manual_count"] == 1


def test_sheet_no_answer_or_stem_leakage():
    doc = _sheet()
    dumped = json.dumps(doc, ensure_ascii=False)
    assert "ANS" not in dumped and "SOL-" not in dumped
    assert "answer" not in dumped
    assert "solution" not in dumped
    assert "stem" not in dumped
    assert "misconception" not in dumped


def test_sheet_repeated_item_id_numbers_by_occurrence():
    doc = build_answer_sheet(
        _paper(sections=[{"kp_name": "甲", "item_ids": ["c2", "c2"]}],
               item_ids=["c2", "c2"]),
        BANK)
    qs = doc["questions"]
    assert [(q["number"], q["field_label"]) for q in qs] == [(1, "q1"), (2, "q2")]
    assert qs[0]["options"] == qs[1]["options"]  # 两次出现同映射
    assert qs[0] is not qs[1]  # 不别名


# ---------- build_answer_sheet 完整性门 ----------

def test_sheet_build_errors():
    with pytest.raises(OMRError):
        _sheet(sections=[], item_ids=[])  # 空卷
    secs = [{"kp_name": "甲", "item_ids": ["ghost"]}]
    with pytest.raises(OMRError):
        build_answer_sheet(_paper(sections=secs), BANK)  # 未知题
    bank = _DuckBank([_DuckItem("u1", "essay", "任答")])
    with pytest.raises(OMRError):
        build_answer_sheet(
            _paper(sections=[{"kp_name": "甲", "item_ids": ["u1"]}], item_ids=["u1"]),
            bank)  # 未知题型
    for bad_item in (_DuckItem("b1", "choice", "A", ["A. 1"]),          # <2 选项
                     _DuckItem("b2", "choice", "A", ["A. 1", "A. 2"]),  # 标签重复
                     _DuckItem("b3", "choice", "A", ["1", "A. 2"])):    # 回退撞显式
        bank = _DuckBank(ITEMS + [bad_item])
        with pytest.raises(OMRError):
            build_answer_sheet(
                _paper(sections=[{"kp_name": "甲", "item_ids": [bad_item.id]}],
                       item_ids=[bad_item.id]), bank)
    many = _DuckItem("big", "choice", "A", [f"{chr(65 + i)}. 选项{i}" for i in range(27)])
    with pytest.raises(OMRError):
        build_answer_sheet(
            _paper(sections=[{"kp_name": "甲", "item_ids": ["big"]}],
                   item_ids=["big"]),
            _DuckBank([many]))  # >26 选项
    dup = _DuckBank([_DuckItem("f1", "fill", "一"), _DuckItem("f1", "fill", "二")])
    with pytest.raises(OMRError):
        build_answer_sheet(_paper(sections=[], item_ids=["f1"]), dup)  # bank 重复 id


def test_sheet_malformed_paper_and_bank_surfaces_rejected():
    class _NoSections:
        paper_id, title, item_ids = "p", "t", ["f1"]

    class _NoItemsBank:
        pass

    class _BadItemsBank:
        def items(self):
            return 42

    with pytest.raises(OMRError):
        build_answer_sheet(_NoSections(), BANK)
    with pytest.raises(OMRError):
        build_answer_sheet(_paper(), _NoItemsBank())
    with pytest.raises(OMRError):
        build_answer_sheet(_paper(), _BadItemsBank())
    for bad_sections in ("x", ["x"], [{"kp_name": "甲"}], [{"item_ids": [3]}],
                        [{"kp_name": 5, "item_ids": ["c1"]}]):
        with pytest.raises(OMRError):
            build_answer_sheet(
                Paper(paper_id="p", title="t", blueprint={}, item_ids=[],
                      sections=bad_sections), BANK)
    with pytest.raises(OMRError):
        build_answer_sheet(_paper(sections=[], item_ids="c1"), BANK)


# ---------- I6 CSV 解析闭式 ----------

def test_parse_results_closed_form_and_row_order():
    rows = parse_omr_results(RESULTS_CSV)
    assert rows == [
        {"file_id": "scan001.jpg",
         "values": {"input_path": "in/001.jpg", "output_path": "out/001.jpg",
                    "score": "1.0", "q1": "B", "q2": "", "q3": "A", "q5": "C"}},
        {"file_id": "scan002.jpg",
         "values": {"input_path": "in/002.jpg", "output_path": "out/002.jpg",
                    "score": "2.0", "q1": "AC", "q2": "B", "q3": "A", "q5": ""}},
    ]
    assert rows[0]["values"]["score"] == "1.0"  # score 照录字符串


def test_parse_results_quoted_cells_bom_and_blank_lines():
    text = (
        chr(0xFEFF) + "file_id,note,q1\r\n"
        "\r\n"
        '"scan, 001.jpg","含,逗号",B\r\n'
    )
    rows = parse_omr_results(text)
    assert rows == [{"file_id": "scan, 001.jpg",
                     "values": {"note": "含,逗号", "q1": "B"}}]


def test_parse_results_header_only_returns_empty():
    assert parse_omr_results("file_id,q1,q2\r\n") == []


def test_parse_results_errors():
    for bad in (
        "",                        # 无表头
        "\r\n\r\n",                # 仅空行
        "input_path,q1\r\na.jpg,B\r\n",   # 缺 file_id 列
        "file_id,q1,q1\r\na.jpg,B,C\r\n",  # 表头重复
        "file_id,,q1\r\na.jpg,B,C\r\n",    # 表头空单元格
        "file_id,q1\r\na.jpg,B,EXTRA\r\n",  # 行长于表头
        "file_id,q1,q2\r\na.jpg,B\r\n",     # 行短于表头
        "file_id,q1\r\n ,B\r\n",   # file_id 空白
    ):
        with pytest.raises(OMRError):
            parse_omr_results(bad)
    with pytest.raises(OMRError):
        parse_omr_results(b"file_id,q1\r\n")  # 非 str
    with pytest.raises(OMRError):
        parse_omr_results(None)


# ---------- I7/I8/I9 to_responses 语义 ----------

def test_to_responses_closed_form_happy_path():
    responses = to_responses(_row({"q1": "B", "q5": "A"}), _sheet(), BANK)
    assert responses == [
        Response(item_id="c1", correct=True, learner_answer="B. -2/3",
                 response_ms=None),
        Response(item_id="c2", correct=True, learner_answer="2", response_ms=None),
    ]
    # 学习者选错：q5 涂 B（原文 "3"）
    wrong = to_responses(_row({"q1": "A", "q5": "B"}), _sheet(), BANK)
    assert wrong == [
        Response(item_id="c1", correct=False, learner_answer="A. 0",
                 response_ms=None),
        Response(item_id="c2", correct=False, learner_answer="3", response_ms=None),
    ]


def test_to_responses_unmarked_multimarked_lowercase():
    # 未涂 -> None/False；小写归一后可判（learner_answer 仍是 options 原文全串）；
    # 多涂恒错且保留拼接串
    responses = to_responses(_row({"q1": "b", "q5": ""}), _sheet(), BANK)
    assert responses == [
        Response(item_id="c1", correct=True, learner_answer="B. -2/3",
                 response_ms=None),
        Response(item_id="c2", correct=False, learner_answer=None, response_ms=None),
    ]
    multi = to_responses(_row({"q1": "AC", "q5": "A"}), _sheet(), BANK)
    assert multi[0] == Response(item_id="c1", correct=False,
                                learner_answer="AC", response_ms=None)
    assert multi[1].correct is True
    # 手工题跳过：只产 omr 题的 Response
    assert len(responses) == 2 and {r.item_id for r in responses} == {"c1", "c2"}


def test_to_responses_answers_resolved_by_label_or_text():
    # c1 答案 "B"（标签路）；c2 答案 "2"（正文路，因无显式标签）
    assert to_responses(_row({"q1": "B", "q5": "A"}), _sheet(), BANK)[0].correct
    assert to_responses(_row({"q1": "D", "q5": "B"}), _sheet(), BANK)[0].correct is False


def test_to_responses_cross_locked_with_grading():
    from xuexing.grading import grade_choice

    cases = [
        {"q1": "B", "q5": "A"}, {"q1": "A", "q5": "B"}, {"q1": "b", "q5": ""},
        {"q1": "AC", "q5": "A"}, {"q1": "", "q5": ""}, {"q1": "C", "q5": "B"},
    ]
    for marks in cases:
        for response in to_responses(_row(marks), _sheet(), BANK):
            item = next(it for it in BANK.items() if it.id == response.item_id)
            assert response.correct == grade_choice(item, response.learner_answer), (
                marks, response)


def test_to_responses_errors_and_integrity_gates():
    sheet = _sheet()
    with pytest.raises(OMRError):
        to_responses(_row({"q1": "B"}), sheet, BANK)          # 缺 q5 列
    with pytest.raises(OMRError):
        to_responses(_row({"q1": "AX", "q5": "A"}), sheet, BANK)  # 未知涂点字符
    with pytest.raises(OMRError):
        to_responses(_row({"q1": "B", "q5": "A"}), "sheet", BANK)  # sheet 非 dict
    with pytest.raises(OMRError):
        to_responses({"q1": "B", "q5": "A"}, sheet, BANK)      # row 缺 values
    with pytest.raises(OMRError):
        to_responses(_row({"q1": "B", "q5": "A"}), {**sheet, "format_version": "2"},
                     BANK)  # 版本不符
    # sheet/bank 漂移：题型变 / 气泡表不一致 / 未知题 / bank 重复 id
    drifted_bank = _DuckBank([
        _DuckItem("c1", "fill", "B"), ITEMS[1], ITEMS[2], ITEMS[3], ITEMS[4]])
    with pytest.raises(OMRError):
        to_responses(_row({"q1": "B", "q5": "A"}), sheet, drifted_bank)
    stale = {**sheet, "questions": [
        {**sheet["questions"][0], "bubble_values": ["A", "B"]},
        sheet["questions"][1], sheet["questions"][2], sheet["questions"][3],
        sheet["questions"][4]]}
    with pytest.raises(OMRError):
        to_responses(_row({"q1": "A", "q5": "A"}), stale, BANK)
    ghost = {**sheet, "questions": [
        {**sheet["questions"][0], "item_id": "ghost"},
        sheet["questions"][1], sheet["questions"][2], sheet["questions"][3],
        sheet["questions"][4]]}
    with pytest.raises(OMRError):
        to_responses(_row({"q1": "A", "q5": "A"}), ghost, BANK)
    with pytest.raises(OMRError):
        to_responses(_row({"q1": "B", "q5": "A"}), sheet,
                     _DuckBank(ITEMS + [ITEMS[0]]))
    # answer 无法解析（题目本身坏）
    broken = _DuckBank([
        _DuckItem("c1", "choice", "Z", ["A. 0", "B. -2/3", "C. +1.5", "D. 2026"]),
        ITEMS[1], ITEMS[2], ITEMS[3], ITEMS[4]])
    with pytest.raises(OMRError):
        to_responses(_row({"q1": "B", "q5": "A"}), sheet, broken)
    # sheet 结构损坏：题号重复 / 列名重复 / 未知 mode / number 非法
    q = sheet["questions"]
    with pytest.raises(OMRError):
        to_responses(_row({"q1": "B", "q5": "A"}),
                     {**sheet, "questions": [q[0], q[1], q[2], q[3], q[0]]}, BANK)
    with pytest.raises(OMRError):
        to_responses(_row({"q1": "B", "q5": "A", "q6": "A"}),
                     {**sheet, "questions": [q[0], q[1], q[2], q[3],
                                             {**q[4], "field_label": "q1"}]}, BANK)
    with pytest.raises(OMRError):
        to_responses(_row({"q1": "B", "q5": "A"}),
                     {**sheet, "questions": [q[0], q[1], q[2], q[3],
                                             {**q[4], "mode": "scan"}]}, BANK)
    for bad_number in (0, -1, True, "1", 2.0, None):
        with pytest.raises(OMRError):
            to_responses(_row({"q1": "B", "q5": "A"}),
                         {**sheet, "questions": [q[0], q[1], q[2], q[3],
                                                 {**q[4], "number": bad_number}]},
                         BANK)


# ---------- I10 纯函数性 / 确定性 / JSON 兼容 ----------

def test_purity_inputs_not_mutated():
    paper = _paper()
    bank = _DuckBank(ITEMS)
    snap_sections = copy.deepcopy(paper.sections)
    snap_items = copy.deepcopy([vars(it) for it in bank.items()])
    sheet = build_answer_sheet(paper, bank)
    build_answer_sheet(paper, bank)
    row = _row({"q1": "B", "q5": "A"})
    snap_row = copy.deepcopy(row)
    parse_omr_results(RESULTS_CSV)
    to_responses(row, sheet, bank)
    assert paper.sections == snap_sections
    assert [vars(it) for it in bank.items()] == snap_items
    assert row == snap_row


def test_determinism_and_json_serializable():
    s1, s2 = _sheet(), _sheet()
    assert s1 == s2
    assert json.dumps(s1, ensure_ascii=False, sort_keys=True) == \
        json.dumps(s2, ensure_ascii=False, sort_keys=True)
    assert json.loads(json.dumps(s1, ensure_ascii=False)) == s1
    rows1 = parse_omr_results(RESULTS_CSV)
    rows2 = parse_omr_results(RESULTS_CSV)
    assert rows1 == rows2
    assert json.loads(json.dumps(rows1, ensure_ascii=False)) == rows1


# ---------- I11 真实卷端到端（generate_paper -> sheet -> Responses） ----------

def test_feeds_generate_paper_end_to_end(small_bank, small_graph):
    from xuexing.paper import generate_paper

    paper = generate_paper(
        small_bank, small_graph, {"a": 1, "b": 2, "c": 1, "d": 1}, seed=5)
    sheet = build_answer_sheet(paper, small_bank)
    assert sheet["question_count"] == len(paper.item_ids)
    assert sheet["question_count"] == sheet["omr_count"] + sheet["manual_count"]
    omr_items = [iid for iid in paper.item_ids
                 if next(it for it in small_bank.items()
                         if it.id == iid).item_type == "choice"]
    assert sheet["omr_count"] == len(omr_items)
    assert [q["field_label"] for q in sheet["questions"]
            if q["mode"] == MODE_OMR] == sheet["output_columns"]
    assert sheet["output_columns"] == sorted(sheet["output_columns"],
                                             key=natural_sort_key)
    # 全对卡：把每道 choice 题的正确气泡涂上 -> 全部 correct
    marks = {}
    for q in sheet["questions"]:
        if q["mode"] != MODE_OMR:
            continue
        item = next(it for it in small_bank.items() if it.id == q["item_id"])
        target = item.answer.strip().upper()
        labels = q["bubble_values"]
        texts = [o["text"] for o in q["options"]]
        idx = labels.index(target) if target in labels else \
            [t.strip().upper() for t in texts].index(target)
        marks[q["field_label"]] = labels[idx]
    csv_lines = [",".join([RESULTS_FILE_ID_COLUMN] + sheet["output_columns"])]
    csv_lines.append(",".join(["scan01.jpg"] +
                              [marks[c] for c in sheet["output_columns"]]))
    rows = parse_omr_results("\r\n".join(csv_lines) + "\r\n")
    responses = to_responses(rows[0], sheet, small_bank)
    assert len(responses) == len(omr_items)
    assert all(isinstance(r, Response) for r in responses)
    assert all(r.correct for r in responses)
