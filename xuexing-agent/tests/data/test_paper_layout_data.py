"""数据测试：静态卷排版 × 真实七年级题库（BACKLOG「静态卷 PDF 输出」数据闭环）。

在真实知识库（37 KP × 每点主知识点库存 ≥3 题）上验证排版内核的端到端可打印性，
闭式值实测于 2026-09-29（seed=11、每 KP 2 题、每页 15 题）；2026-09-30 g7
深挖批扩库（129 -> 222 题）后同 seed 重算（2026-10-01 GPU 端实跑）：
- 全图谱蓝图组卷 -> 排版 JSON 的闭式计数（74 题 / 5 页 / 题型分布 22/45/7）；
- 题号 1..74 与卷面顺序保持；37 个节标题块恒紧跟其首题、中文序号连到「三十七」；
- choice 题选项全部解析为唯一 A–D 标签；学生卷无 answer/solution 键；
- 同 seed 重组卷 + 重排版逐位一致（确定性）。
改知识库/题库后若计数变化，须同步更新本文件闭式。
"""
import json

from xuexing.paper import generate_paper
from xuexing.paper_layout import ANSWER_SPACE_RULES, render_paper_layout

PAPER_ID = "paper-grade7-layout"
TITLE = "七年级数学诊断卷"
NOTE = "XX中学数学科"
QPP = 15


def _build_paper(bank, graph):
    return generate_paper(
        bank, graph, {kp.id: 2 for kp in graph.kps()},
        seed=11, title=TITLE, paper_id=PAPER_ID)


def _layout(bank, graph):
    return render_paper_layout(
        _build_paper(bank, graph), bank, questions_per_page=QPP, header_note=NOTE)


def _question_blocks(doc):
    return [b for pg in doc["pages"] for b in pg["blocks"] if b["kind"] == "question"]


def test_real_paper_layout_closed_counts(bank, graph):
    doc = _layout(bank, graph)
    kps = [kp.id for kp in graph.kps()]
    assert doc["question_count"] == 2 * len(kps) == 74
    assert doc["page_count"] == -(-74 // QPP) == 5
    assert doc["by_item_type"] == {"choice": 22, "fill": 45, "solve": 7}
    assert doc["paper_id"] == PAPER_ID and doc["title"] == TITLE


def test_real_numbering_and_order_preserved(bank, graph):
    paper = _build_paper(bank, graph)
    doc = render_paper_layout(paper, bank, questions_per_page=QPP)
    qs = _question_blocks(doc)
    assert [q["number"] for q in qs] == list(range(1, 75))
    assert [q["item_id"] for q in qs] == paper.item_ids
    assert len(paper.item_ids) == len(set(paper.item_ids)) == 74


def test_real_section_blocks_closed_forms(bank, graph):
    doc = _layout(bank, graph)
    sections = []
    for pg in doc["pages"]:
        for i, block in enumerate(pg["blocks"]):
            if block["kind"] == "section":
                sections.append(block["text"])
                # 节标题块不悬空：恒紧跟该节首题
                assert i + 1 < len(pg["blocks"]) and pg["blocks"][i + 1]["kind"] == "question"
    assert len(sections) == 37
    assert sections[0] == "一、绝对值"
    assert sections[1] == "二、代数式"
    assert sections[-1] == "三十七、消元法解二元一次方程组"


def test_real_choice_options_and_answer_spaces(bank, graph):
    doc = _layout(bank, graph)
    for q in _question_blocks(doc):
        assert q["answer_space"] == ANSWER_SPACE_RULES[q["item_type"]]
        if q["item_type"] == "choice":
            assert 2 <= len(q["options"]) <= 26
            labels = [o["label"] for o in q["options"]]
            assert len(set(labels)) == len(labels) and set(labels) <= set("ABCD")
            assert q["options"][0] == {"label": "A", "text": q["options"][0]["text"]}
        else:
            assert q["options"] == []
        assert q["stem"].strip()


def test_real_header_footer_and_no_answer_leak(bank, graph):
    doc = _layout(bank, graph)
    for p, pg in enumerate(doc["pages"], start=1):
        assert pg["page_number"] == p and pg["page_count"] == 5
        assert pg["header"]["text"] == f"{NOTE} · {TITLE} · {PAPER_ID}"
        assert pg["footer"]["text"] == f"第 {p} 页 / 共 5 页"
    # 学生卷完整性：题块键集合封闭，无作答依据字段
    for q in _question_blocks(doc):
        assert set(q) == {"kind", "number", "item_id", "item_type", "stem",
                          "options", "answer_space"}
    dumped = json.dumps(doc, ensure_ascii=False)
    assert '"answer"' not in dumped.replace("answer_space", "")
    assert '"solution"' not in dumped
    assert json.loads(json.dumps(doc, ensure_ascii=False)) == doc  # 全量 JSON 兼容


def test_real_determinism(bank, graph):
    assert _layout(bank, graph) == _layout(bank, graph)
