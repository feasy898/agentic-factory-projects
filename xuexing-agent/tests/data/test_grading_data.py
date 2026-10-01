"""数据测试：grading 判分接口 × 真实题库（data/items/math_grade7_items.json）的自洽性。

任何入库题目的标准答案必须能被判分器判对（自判恒真）；答案归一化后不得为空
（规则表不得吞掉真实内容）；choice 题任一异于答案的标签必须判错。
"""
import pytest

from xuexing.grading import grade, grade_choice, normalize_answer


def test_every_item_self_grades_true(bank):
    for it in bank.items():
        assert grade(it, it.answer) is True, f"item {it.id}: 自判失真"


def test_no_answer_normalizes_to_empty(bank):
    for it in bank.items():
        assert normalize_answer(it.answer) != "", f"item {it.id}: 答案被归一化清空"


def test_choice_other_labels_grade_false(bank):
    checked = 0
    for it in bank.items():
        if it.item_type != "choice":
            continue
        labels = [o.strip().split(".")[0].strip() for o in it.options]
        answer = it.answer.strip()
        assert answer in labels, f"item {it.id}: 答案不在标签中"
        for other in labels:
            if other != answer:
                assert grade_choice(it, other) is False, \
                    f"item {it.id}: 错误选项 {other} 被判对"
                checked += 1
    assert checked > 0  # 真实库存确有 choice 干扰项可核对


def test_fill_numeric_answer_accepts_equivalent_form(bank):
    # 含单位/百分数的真实答案，其全角/加空格变体必须判对（抽样对照）
    targets = {it.id: it for it in bank.items() if it.answer in ("-300元", "30%")}
    assert set(targets)  # 防数据漂移：这两个对照点必须存在
    for it in targets.values():
        variant = ("－300 元" if it.answer == "-300元" else "3/10")
        assert grade(it, variant) is True, f"item {it.id}: 等值变体 {variant} 判错"
