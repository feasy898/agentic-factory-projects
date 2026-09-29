"""契约：paper_layout —— 静态卷打印友好排版（题号/选项/留白/页眉/分页）。

全部数值条款为手算可复核的闭式值（实测于 CPython 3.12 x64）。
paper/bank 均按鸭子类型自封闭小夹具（Paper 用真实 types.Paper，bank 用最小
items() 桩），不依赖 data/ 夹具；唯一例外是 test_feeds_generate_paper
（供 paper 组装的端到端可组装性，与 test_blueprint_contract 同例）。
"""
import copy
import json

import pytest

from xuexing.paper_layout import (
    ANSWER_SPACE_RULES,
    DEFAULT_QUESTIONS_PER_PAGE,
    FORMAT_VERSION,
    HEADER_SEPARATOR,
    LayoutError,
    parse_option,
    render_paper_layout,
    section_ordinal,
)
from xuexing.types import Paper


# ---------- 自封闭小夹具 ----------

class _DuckItem:
    def __init__(self, item_id, item_type, stem, options=None, answer=""):
        self.id = item_id
        self.item_type = item_type
        self.stem = stem
        self.options = list(options or [])
        self.answer = answer or f"ANS-{item_id}"
        self.solution = f"SOL-{item_id}"


class _DuckBank:
    def __init__(self, items):
        self._items = list(items)

    def items(self):
        return list(self._items)


ITEMS = [
    _DuckItem("c1", "choice", "选出负数：（　）", ["A. 0", "B. -2/3", "C. +1.5", "D. 2026"]),
    _DuckItem("f1", "fill", "收入500元记作+500元，支出300元记作____。"),
    _DuckItem("s1", "solve", "解方程：x + 8 = 20。"),
    _DuckItem("f2", "fill", "计算：1/2 + 1/3 = ____。"),
    _DuckItem("c2", "choice", "1 + 1 =（　）", ["2", "3"]),  # 无显式标签 -> 按位回退 A/B
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
        item_ids=item_ids if item_ids is not None else [iid for s in sections for iid in s["item_ids"]],
        sections=[dict(s) for s in sections],
    )


def _default_doc(**kw):
    return render_paper_layout(_paper(**kw), BANK, questions_per_page=2)


def _question_blocks(doc):
    out = []
    for page in doc["pages"]:
        for block in page["blocks"]:
            if block["kind"] == "question":
                out.append(block)
    return out


# ---------- 常量冻结 ----------

def test_frozen_constants():
    assert FORMAT_VERSION == "1"
    assert HEADER_SEPARATOR == " · "
    assert DEFAULT_QUESTIONS_PER_PAGE == 10
    assert ANSWER_SPACE_RULES == {
        "choice": {"style": "bracket", "lines": 0},
        "fill": {"style": "underline", "lines": 1},
        "solve": {"style": "ruled", "lines": 6},
    }
    assert set(ANSWER_SPACE_RULES) == {"choice", "fill", "solve"}
    assert issubclass(LayoutError, ValueError)


# ---------- 顶层形状 + 题号闭式 ----------

def test_top_level_shape_and_numbering():
    doc = _default_doc()
    assert set(doc) == {
        "format_version", "paper_id", "title", "question_count",
        "page_count", "by_item_type", "pages",
    }
    assert doc["format_version"] == "1"
    assert doc["paper_id"] == "paper-77"
    assert doc["title"] == "七年级诊断卷"
    assert doc["question_count"] == 5
    assert doc["page_count"] == 3
    assert doc["by_item_type"] == {"choice": 2, "fill": 2, "solve": 1}  # 键码点升序
    # 题号 1..N 贯穿全卷，item_id 严格按节×卷面顺序
    assert [q["number"] for q in _question_blocks(doc)] == [1, 2, 3, 4, 5]
    assert [q["item_id"] for q in _question_blocks(doc)] == ["c1", "f1", "s1", "f2", "c2"]
    assert all(set(q) == {"kind", "number", "item_id", "item_type", "stem",
                          "options", "answer_space"}
               for q in _question_blocks(doc))


def test_single_page_when_qpp_covers_all():
    doc = render_paper_layout(_paper(), BANK, questions_per_page=100)
    assert doc["page_count"] == 1
    blocks = doc["pages"][0]["blocks"]
    assert [b["kind"] for b in blocks] == [
        "section", "question", "question", "section", "question", "question", "question",
    ]
    assert blocks[0]["text"] == "一、有理数"
    assert blocks[3]["text"] == "二、一元一次方程"


def test_repeated_item_id_numbers_by_occurrence():
    secs = [
        {"kp_name": "甲", "item_ids": ["f1"]},
        {"kp_name": "乙", "item_ids": ["f1", "s1"]},
    ]
    doc = render_paper_layout(_paper(sections=secs), BANK, questions_per_page=10)
    assert [(q["number"], q["item_id"]) for q in _question_blocks(doc)] == [
        (1, "f1"), (2, "f1"), (3, "s1"),
    ]
    q1, q2, _ = _question_blocks(doc)
    assert q1 is not q2  # 两次出现互不别名
    assert q1["stem"] == q2["stem"] == ITEMS[1].stem
    q1["stem"] = "tampered"
    fresh = render_paper_layout(_paper(sections=secs), BANK)
    assert _question_blocks(fresh)[0]["stem"] == ITEMS[1].stem  # 输出不被污染


# ---------- 选项解析（题号/选项条款） ----------

def test_choice_options_labeled_and_parsed():
    doc = _default_doc()
    qs = {q["item_id"]: q for q in _question_blocks(doc)}
    assert qs["c1"]["options"] == [
        {"label": "A", "text": "0"},
        {"label": "B", "text": "-2/3"},
        {"label": "C", "text": "+1.5"},
        {"label": "D", "text": "2026"},
    ]
    # 无显式标签 -> 按位置回退 A/B，正文整串保留
    assert qs["c2"]["options"] == [{"label": "A", "text": "2"}, {"label": "B", "text": "3"}]
    # 非 choice 题不排选项
    assert qs["f1"]["options"] == [] and qs["s1"]["options"] == []


def test_parse_option_closed_forms():
    assert parse_option("A. 0", 0) == ("A", "0")
    assert parse_option("b、题干", 0) == ("B", "题干")  # 小写标签归一大写
    assert parse_option("C）文本", 0) == ("C", "文本")
    assert parse_option("D．四", 0) == ("D", "四")
    assert parse_option("2", 1) == ("B", "2")  # 无标签 -> 按位置回退
    assert parse_option("（4,1）", 0) == ("A", "（4,1）")
    assert parse_option("(4,1)", 3) == ("D", "(4,1)")
    assert parse_option("x=5", 0) == ("A", "x=5")
    assert parse_option("  B. 2  ", 0) == ("B", "2")
    assert parse_option("A.", 0) == ("A", "")  # 正文可为空串


def test_parse_option_input_guards():
    for bad_args in (("", 0), (None, 0), (5, 0), ("x", 26), ("x", -1), ("x", True), ("x", 1.0)):
        with pytest.raises(LayoutError):
            parse_option(*bad_args)


# ---------- 留白规则（留白条款） ----------

def test_answer_space_frozen_per_type():
    doc = _default_doc()
    qs = {q["item_id"]: q for q in _question_blocks(doc)}
    assert qs["c1"]["answer_space"] == {"style": "bracket", "lines": 0}
    assert qs["f1"]["answer_space"] == {"style": "underline", "lines": 1}
    assert qs["f2"]["answer_space"] == {"style": "underline", "lines": 1}
    assert qs["s1"]["answer_space"] == {"style": "ruled", "lines": 6}


def test_answer_space_fresh_dicts_not_aliases():
    doc = _default_doc()
    q1 = _question_blocks(doc)[0]
    q1["answer_space"]["lines"] = 99
    q1["answer_space"]["style"] = "tampered"
    assert ANSWER_SPACE_RULES["fill"]["lines"] == 1  # 常量表不被污染
    fresh = _default_doc()
    assert _question_blocks(fresh)[1]["answer_space"] == {"style": "underline", "lines": 1}


# ---------- 页眉/页脚（页眉条款） ----------

def test_header_and_footer_closed_forms():
    doc = _default_doc()
    assert doc["page_count"] == 3
    for p, page in enumerate(doc["pages"], start=1):
        assert page["page_number"] == p and page["page_count"] == 3
        assert set(page) == {"page_number", "page_count", "header", "footer", "blocks"}
        assert page["header"]["title"] == "七年级诊断卷"
        assert page["header"]["paper_id"] == "paper-77"
        assert page["header"]["note"] == ""
        assert page["header"]["text"] == "七年级诊断卷 · paper-77"
        assert page["footer"]["text"] == f"第 {p} 页 / 共 3 页"


def test_header_note_segments_stripped_and_joined():
    doc = render_paper_layout(
        _paper(title="  七年级诊断卷  "), BANK, questions_per_page=2, header_note="  XX中学数学科  ")
    header = doc["pages"][0]["header"]
    assert header["note"] == "XX中学数学科"
    assert header["title"] == "  七年级诊断卷  "  # title 原样保留
    assert header["text"] == "XX中学数学科 · 七年级诊断卷 · paper-77"


def test_header_all_blank_segments_give_empty_text():
    doc = render_paper_layout(_paper(paper_id="", title=""), BANK)
    assert doc["pages"][0]["header"]["text"] == ""


# ---------- 分页闭式 + 节标题块 ----------

def test_pagination_closed_form_and_section_block_placement():
    doc = _default_doc()  # qpp=2, N=5 -> 3 页
    p1, p2, p3 = doc["pages"]
    assert [(b["kind"], b.get("number") or b.get("text")) for b in p1["blocks"]] == [
        ("section", "一、有理数"), ("question", 1), ("question", 2),
    ]
    assert [(b["kind"], b.get("number") or b.get("text")) for b in p2["blocks"]] == [
        ("section", "二、一元一次方程"), ("question", 3), ("question", 4),
    ]
    assert [(b["kind"], b.get("number") or b.get("text")) for b in p3["blocks"]] == [
        ("question", 5),
    ]


def test_two_section_headers_can_share_one_page():
    doc = render_paper_layout(_paper(), BANK, questions_per_page=3)
    assert doc["page_count"] == 2
    kinds = [b["kind"] for b in doc["pages"][0]["blocks"]]
    assert kinds == ["section", "question", "question", "section", "question"]
    texts = [b["text"] for b in doc["pages"][0]["blocks"] if b["kind"] == "section"]
    assert texts == ["一、有理数", "二、一元一次方程"]


def test_section_ordinal_closed_forms():
    for n, text in ((1, "一"), (2, "二"), (9, "九"), (10, "十"), (11, "十一"),
                    (19, "十九"), (20, "二十"), (21, "二十一"), (90, "九十"),
                    (99, "九十九"), (100, "100"), (101, "101")):
        assert section_ordinal(n) == text, n
    for bad in (0, -3, True, 2.0, "3", None):
        with pytest.raises(LayoutError):
            section_ordinal(bad)


def test_section_ordinal_used_in_block_text_and_name_stripped():
    secs = [{"kp_name": "  有理数  ", "item_ids": ["f1"]}]
    doc = render_paper_layout(_paper(sections=secs), BANK)
    assert doc["pages"][0]["blocks"][0]["text"] == "一、有理数"


def test_named_empty_section_not_rendered_and_skips_ordinal():
    secs = [
        {"kp_name": "甲节", "item_ids": ["f1"]},
        {"kp_name": "空节", "item_ids": []},
        {"kp_name": "乙节", "item_ids": ["s1"]},
    ]
    doc = render_paper_layout(_paper(sections=secs), BANK)
    section_texts = [b["text"] for pg in doc["pages"] for b in pg["blocks"] if b["kind"] == "section"]
    assert section_texts == ["一、甲节", "二、乙节"]  # 空节不占节序号
    dumped = json.dumps(doc, ensure_ascii=False)
    assert "空节" not in dumped


def test_unnamed_sections_no_block_but_questions_flow():
    secs = [{"kp_id": "a", "item_ids": ["f1", "s1"]}]
    doc = render_paper_layout(_paper(sections=secs), BANK)
    assert [b["kind"] for b in doc["pages"][0]["blocks"]] == ["question", "question"]
    assert [q["number"] for q in _question_blocks(doc)] == [1, 2]


def test_empty_sections_falls_back_to_item_ids_single_section():
    doc = render_paper_layout(_paper(sections=[], item_ids=["f1", "s1"]), BANK)
    assert doc["question_count"] == 2 and doc["page_count"] == 1
    assert [b["kind"] for b in doc["pages"][0]["blocks"]] == ["question", "question"]
    assert doc["by_item_type"] == {"fill": 1, "solve": 1}


# ---------- 完整性门（不出残卷） ----------

def test_unknown_item_id_rejected():
    secs = [{"kp_name": "甲", "item_ids": ["ghost"]}]
    with pytest.raises(LayoutError) as ei:
        render_paper_layout(_paper(sections=secs), BANK)
    assert "ghost" in str(ei.value)


def test_duplicate_bank_ids_rejected():
    dup = _DuckBank([_DuckItem("f1", "fill", "题一"), _DuckItem("f1", "fill", "题二")])
    with pytest.raises(LayoutError):
        render_paper_layout(_paper(sections=[], item_ids=["f1"]), dup)


def test_choice_needs_two_options_and_unique_labels():
    cases = [
        _DuckItem("bad1", "choice", "题", ["A. 1"]),                  # <2 个选项
        _DuckItem("bad2", "choice", "题", ["A. 1", "A. 2"]),          # 解析标签重复
        _DuckItem("bad3", "choice", "题", ["1", "A. 2"]),             # 回退 A 撞显式 A
    ]
    for it in cases:
        bank = _DuckBank(ITEMS + [it])
        with pytest.raises(LayoutError):
            render_paper_layout(
                _paper(sections=[{"kp_name": "甲", "item_ids": [it.id]}]), bank)


def test_unknown_item_type_rejected():
    bank = _DuckBank(ITEMS + [_DuckItem("u1", "essay", "论述题")])
    with pytest.raises(LayoutError):
        render_paper_layout(
            _paper(sections=[{"kp_name": "甲", "item_ids": ["u1"]}]), bank)


def test_blank_or_non_str_stem_rejected():
    for it in (_DuckItem("b1", "fill", "   "), _DuckItem("b2", "fill", None)):
        bank = _DuckBank(ITEMS + [it])
        with pytest.raises(LayoutError):
            render_paper_layout(
                _paper(sections=[{"kp_name": "甲", "item_ids": [it.id]}]), bank)


def test_empty_paper_rejected():
    with pytest.raises(LayoutError):
        render_paper_layout(_paper(sections=[], item_ids=[]), BANK)
    with pytest.raises(LayoutError):
        render_paper_layout(_paper(sections=[{"kp_name": "甲", "item_ids": []}]), BANK)


def test_bad_questions_per_page_rejected():
    for bad in (0, -2, True, "3", 3.0, None):
        with pytest.raises(LayoutError):
            render_paper_layout(_paper(), BANK, questions_per_page=bad)


def test_bad_header_note_rejected():
    with pytest.raises(LayoutError):
        render_paper_layout(_paper(), BANK, header_note=5)


def test_malformed_paper_and_bank_surfaces_rejected():
    class _NoSections:
        paper_id, title, item_ids = "p", "t", ["f1"]

    class _BadItemsBank:
        def items(self):
            return 42

    class _NoItemsBank:
        pass

    class _BadIdBank:
        def items(self):
            return [_DuckItem("ok", "fill", "题"), _DuckItem(None, "fill", "题")]

    with pytest.raises(LayoutError):
        render_paper_layout(_NoSections(), BANK)
    with pytest.raises(LayoutError):
        render_paper_layout(_paper(), _NoItemsBank())
    with pytest.raises(LayoutError):
        render_paper_layout(_paper(), _BadItemsBank())
    with pytest.raises(LayoutError):
        render_paper_layout(_paper(), _BadIdBank())
    for bad_sections in ("x", ["x"], [{"kp_name": "甲"}], [{"item_ids": [3]}],
                        [{"kp_name": 5, "item_ids": ["f1"]}]):
        # 畸形节无法过 _paper 的规整拷贝，直接以原始容器构造 Paper
        with pytest.raises(LayoutError):
            render_paper_layout(
                Paper(paper_id="p", title="t", blueprint={}, item_ids=[],
                      sections=bad_sections),
                BANK,
            )
    # sections 为空但 item_ids 不是列表
    with pytest.raises(LayoutError):
        render_paper_layout(_paper(sections=[], item_ids="f1"), BANK)


# ---------- 学生卷完整性：不泄答案 ----------

def test_no_answer_or_solution_leakage():
    doc = _default_doc()
    dumped = json.dumps(doc, ensure_ascii=False)
    assert "ANS-" not in dumped and "SOL-" not in dumped  # 桩题目的 answer/solution 均带前缀
    assert "answer" not in dumped.replace("answer_space", "")  # 仅 answer_space 合法
    assert "solution" not in dumped
    assert "misconception" not in dumped


# ---------- 纯函数性 / 确定性 / JSON 可序列化 ----------

def test_purity_inputs_not_mutated():
    paper = _paper()
    bank = _DuckBank(ITEMS)
    snap_sections = copy.deepcopy(paper.sections)
    snap_items = copy.deepcopy([vars(it) for it in bank.items()])
    render_paper_layout(paper, bank, questions_per_page=2, header_note="注")
    assert paper.sections == snap_sections
    assert [vars(it) for it in bank.items()] == snap_items
    assert len(bank.items()) == 5


def test_determinism_and_json_serializable():
    d1 = _default_doc()
    d2 = _default_doc()
    assert d1 == d2
    assert json.dumps(d1, ensure_ascii=False, sort_keys=True) == \
        json.dumps(d2, ensure_ascii=False, sort_keys=True)
    assert json.loads(json.dumps(d1, ensure_ascii=False)) == d1  # 全量 JSON 兼容


# ---------- 供 generate_paper（端到端可组装性） ----------

def test_feeds_generate_paper(small_bank, small_graph):
    from xuexing.paper import generate_paper

    paper = generate_paper(
        small_bank, small_graph, {"a": 1, "b": 2, "c": 1, "d": 1}, seed=5)
    doc = render_paper_layout(paper, small_bank, questions_per_page=2)
    assert doc["question_count"] == 5 and doc["page_count"] == 3
    qs = _question_blocks(doc)
    assert [q["number"] for q in qs] == [1, 2, 3, 4, 5]
    assert [q["item_id"] for q in qs] == paper.item_ids  # 卷面顺序保持
    section_texts = [b["text"] for pg in doc["pages"] for b in pg["blocks"]
                     if b["kind"] == "section"]
    assert section_texts == ["一、甲", "二、乙", "三、丙", "四、丁"]  # 节序号 + 图谱名
    assert doc["pages"][-1]["footer"]["text"] == "第 3 页 / 共 3 页"
