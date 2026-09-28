"""契约：ItemBank —— 题目存储与校验规则。"""
import pytest

from xuexing.itembank import ItemBank, ItemBankError
from xuexing.types import Item


def _item(item_id, **kw):
    base = dict(id=item_id, item_type="fill", stem=f"s-{item_id}", answer="x",
                kps=["a"], difficulty=0.5)
    base.update(kw)
    return Item(**base)


def test_add_get_duplicate():
    b = ItemBank()
    b.add(_item("i1"))
    assert b.has("i1") and b.get("i1").id == "i1"
    with pytest.raises(ItemBankError):
        b.add(_item("i1"))


def test_choice_answer_accepts_label_or_text():
    b = ItemBank()
    ok = _item("c1", item_type="choice", options=["A. 1", "B. 2"], answer="B")
    ok2 = _item("c2", item_type="choice", options=["A. 1", "B. 2"], answer="B. 2")
    assert b.validate_item(ok) == []
    assert b.validate_item(ok2) == []
    bad = _item("c3", item_type="choice", options=["A. 1", "B. 2"], answer="C")
    assert any("answer not among options" in e for e in b.validate_item(bad))


def test_validation_rules():
    b = ItemBank()
    assert any("no kp tags" in e for e in b.validate_item(_item("x", kps=[])))
    assert any("difficulty" in e for e in b.validate_item(_item("x", difficulty=1.5)))
    assert any("discrimination" in e for e in b.validate_item(_item("x", discrimination=2.0)))
    assert any("empty stem" in e for e in b.validate_item(_item("x", stem=" ")))
    assert any("item_type" in e for e in b.validate_item(_item("x", item_type="essay")))


def test_by_kp_primary_semantics():
    b = ItemBank()
    b.add(_item("i1", kps=["a", "b"]))
    b.add(_item("i2", kps=["b"]))
    assert [i.id for i in b.by_kp("a", primary_only=True)] == ["i1"]
    assert {i.id for i in b.by_kp("b")} == {"i1", "i2"}


def test_effective_guess_contract():
    assert _item("g1", item_type="choice").effective_guess() == 0.25
    assert _item("g2", item_type="fill").effective_guess() == 0.10
    assert _item("g3", item_type="solve").effective_guess() == 0.02
    assert _item("g4", guess=0.9).effective_guess() == 0.9


def test_validate_all_dedup_and_kp_check():
    b = ItemBank()
    b.add(_item("i1", kps=["ghost"], difficulty=-1))
    errs = b.validate_all(valid_kp_ids={"a"})
    assert any("unknown kp" in e for e in errs) and any("difficulty" in e for e in errs)
