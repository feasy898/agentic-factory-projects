"""契约：agent_shell —— 错因归因、讲解、出题草稿与入库门。"""
from xuexing.agent_shell import (
    MockLLM,
    attribute_error,
    draft_item,
    explain_error,
    try_accept_draft,
)
from xuexing.itembank import ItemBank
from xuexing.types import Item, Misconception


class ScriptedLLM:
    """契约测试专用：固定回复、记录调用次数。"""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        return self.reply


def _mcs():
    return [
        Misconception(id="mc_x", kp_id="a", description="误解X", hint="提示X", signature=["9"]),
        Misconception(id="mc_y", kp_id="a", description="误解Y", hint="提示Y", signature=["7"]),
    ]


def _item(item_id="i1", kp="a"):
    return Item(id=item_id, item_type="fill", stem=f"s-{item_id}", answer="5", kps=[kp], difficulty=0.4)


def test_signature_hit_is_deterministic_and_skips_llm():
    llm = ScriptedLLM("anything")
    assert attribute_error(_item(), "9", _mcs(), llm) == "mc_x"
    assert llm.calls == 0


def test_llm_fallback_and_none():
    llm = ScriptedLLM("我认为是 mc_y")
    assert attribute_error(_item(), "weird", _mcs(), llm) == "mc_y"
    assert llm.calls == 1
    assert attribute_error(_item(), "weird", _mcs(), ScriptedLLM("NONE")) is None
    assert attribute_error(_item(), "", _mcs(), ScriptedLLM("mc_x")) is None  # 空答案不归因


def test_explain_carries_hint():
    out = explain_error(_item(), "9", "提示X", MockLLM("explainer"))
    assert "提示X" in out and out.strip()


def test_draft_item_returns_json_dict():
    draft = draft_item(MockLLM("item_drafter"), "a", 0.3)
    assert draft["kps"] == ["a"] and draft["stem"] and draft["answer"]
    assert 0.0 <= draft["difficulty"] <= 1.0


def test_accept_gate(small_bank):
    kps = {"a"}
    draft = draft_item(MockLLM("item_drafter"), "a", 0.3)
    ok, errs = try_accept_draft(draft, small_bank, kps)
    assert ok and not errs and small_bank.has(draft["id"])
    dup = dict(draft, id=draft["id"] + "-2")
    ok2, errs2 = try_accept_draft(dup, small_bank, kps)
    assert not ok2 and any("duplicate" in e for e in errs2)


def test_accept_gate_rejects_and_does_not_mutate(small_bank):
    size_before = len(small_bank.items())
    ok, errs = try_accept_draft({"id": "bad1", "item_type": "fill", "stem": "x",
                                 "answer": "1", "kps": ["ghost"], "difficulty": 0.5},
                                small_bank, {"a"})
    assert not ok and any("unknown kp" in e for e in errs)
    assert len(small_bank.items()) == size_before
    ok2, errs2 = try_accept_draft({"id": "bad2", "item_type": "fill", "stem": "y",
                                   "answer": "1", "kps": ["a"], "difficulty": 2.0},
                                  small_bank, {"a"})
    assert not ok2 and any("difficulty" in e for e in errs2)
