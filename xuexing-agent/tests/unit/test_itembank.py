import pytest

from xuexing.itembank import ItemBank, ItemBankError
from xuexing.types import Item


def _item(item_id, **kw):
    base = dict(
        id=item_id, item_type="fill", stem=f"题{item_id}", answer="1",
        kps=["kp_a"], difficulty=0.5,
    )
    base.update(kw)
    return Item(**base)


def test_duplicate_raises():
    b = ItemBank()
    b.add(_item("i1"))
    with pytest.raises(ItemBankError):
        b.add(_item("i1"))


def test_validate_choice_answer_must_be_in_options():
    b = ItemBank()
    bad = _item("c1", item_type="choice", options=["A. 1", "B. 2"], answer="C")
    errs = b.validate_item(bad)
    assert any("answer not among options" in e for e in errs)
    good = _item("c2", item_type="choice", options=["A. 1", "B. 2"], answer="B")
    assert b.validate_item(good) == []


def test_validate_ranges_and_kp_tags():
    b = ItemBank()
    errs = b.validate_item(_item("i1", difficulty=1.5))
    assert any("difficulty" in e for e in errs)
    errs = b.validate_item(_item("i2", kps=[]))
    assert any("no kp tags" in e for e in errs)


def test_by_kp_primary_vs_any():
    b = ItemBank()
    b.add(_item("i1", kps=["kp_a", "kp_b"]))
    b.add(_item("i2", kps=["kp_b"]))
    assert [i.id for i in b.by_kp("kp_a", primary_only=True)] == ["i1"]
    assert [i.id for i in b.by_kp("kp_b")] == ["i1", "i2"]


def test_validate_all_reports_all_errors():
    b = ItemBank()
    b.add(_item("i1", item_type="choice", options=["A. 1"], answer="1"))
    b.add(_item("i2", difficulty=-0.1))
    errs = b.validate_all(valid_kp_ids={"kp_a"})
    assert len(errs) == 2
    assert any("i1" in e for e in errs) and any("i2" in e for e in errs)


def test_effective_guess_defaults():
    assert _item("i1", item_type="choice").effective_guess() == 0.25
    assert _item("i2", item_type="solve").effective_guess() == 0.02
    assert _item("i3", guess=0.9).effective_guess() == 0.9
