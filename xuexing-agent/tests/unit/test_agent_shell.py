import json

from xuexing.agent_shell import (
    MockLLM,
    attribute_error,
    draft_item,
    explain_error,
    try_accept_draft,
)
from xuexing.itembank import ItemBank
from xuexing.types import Item, Misconception


class FakeLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        return self.reply


def _misconceptions():
    return [
        Misconception(id="mc_abs_drop", kp_id="kp_absvalue", description="认为|−a|=−a",
                      hint="距离不可能为负", signature=["-5"]),
        Misconception(id="mc_sign_neg", kp_id="kp_rational_add", description="符号法则错误",
                      hint="先定符号再算绝对值", signature=["8"]),
    ]


def _item(item_id, kp, difficulty):
    return Item(id=item_id, item_type="fill", stem=f"题{item_id}", answer="5",
                kps=[kp], difficulty=difficulty)


def test_signature_match_is_deterministic_no_llm():
    llm = FakeLLM("mc_abs_drop")
    mc = attribute_error(_item("i1", "kp_absvalue", 0.2), "-5", _misconceptions(), llm)
    assert mc == "mc_abs_drop"
    assert llm.calls == 0  # 签名命中就不该问 LLM


def test_llm_fallback_when_no_signature_hit():
    llm = FakeLLM("我看是 mc_sign_neg")
    mc = attribute_error(_item("i2", "kp_rational_add", 0.2), "乱写的", _misconceptions(), llm)
    assert mc == "mc_sign_neg"
    assert llm.calls == 1


def test_no_match_returns_none():
    llm = FakeLLM("NONE")
    assert attribute_error(_item("i3", "kp_absvalue", 0.2), "乱写的", _misconceptions(), llm) is None


def test_explain_contains_hint():
    out = explain_error(_item("i4", "kp_absvalue", 0.2), "-5", "距离不可能为负", MockLLM("explainer"))
    assert "距离不可能为负" in out


def test_draft_and_accept_gate(bank, graph):
    valid_kps = {kp.id for kp in graph.kps()}
    draft = draft_item(MockLLM("item_drafter"), "kp_posneg", 0.3)
    ok, errs = try_accept_draft(draft, bank, valid_kps)
    assert ok, errs
    assert bank.has(draft["id"])
    # 同题干再来一份必须被拒（重复）
    draft2 = dict(draft)
    draft2["id"] = draft["id"] + "-x"
    ok2, errs2 = try_accept_draft(draft2, bank, valid_kps)
    assert not ok2 and any("duplicate" in e for e in errs2)


def test_draft_rejected_for_unknown_kp(bank, graph):
    valid_kps = {kp.id for kp in graph.kps()}
    draft = draft_item(MockLLM("item_drafter"), "kp_ghost", 0.3)
    ok, errs = try_accept_draft(draft, bank, valid_kps)
    assert not ok and any("unknown kp" in e for e in errs)
    assert not bank.has(draft["id"])


def test_json_bank_fixture_loadable(root):
    data = json.load(open(f"{root}/data/items/math_grade7_items.json", encoding="utf-8"))
    assert len(data["items"]) >= 40
