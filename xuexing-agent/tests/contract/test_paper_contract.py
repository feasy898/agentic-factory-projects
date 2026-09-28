"""契约：paper —— 静态组卷与自适应选题。"""
import pytest

from xuexing.diagnosis import diagnose
from xuexing.paper import PaperError, generate_paper, select_next_item
from xuexing.types import Response


def test_blueprint_assembly(small_bank, small_graph):
    p = generate_paper(small_bank, small_graph, {"a": 2, "d": 2}, seed=5)
    assert sorted(p.item_ids) == sorted(["a1", "a2", "d1", "d2"])
    assert len(set(p.item_ids)) == len(p.item_ids)
    for sec in p.sections:
        assert len(sec["item_ids"]) == p.blueprint[sec["kp_id"]]
        for iid in sec["item_ids"]:
            assert small_bank.get(iid).kps[0] == sec["kp_id"]


def test_same_seed_same_paper(small_bank, small_graph):
    a = generate_paper(small_bank, small_graph, {"a": 2}, seed=9)
    b = generate_paper(small_bank, small_graph, {"a": 2}, seed=9)
    assert a.item_ids == b.item_ids and a.sections == b.sections


def test_blueprint_errors(small_bank, small_graph):
    with pytest.raises(PaperError):
        generate_paper(small_bank, small_graph, {}, seed=1)
    with pytest.raises(PaperError):
        generate_paper(small_bank, small_graph, {"ghost": 1}, seed=1)
    with pytest.raises(PaperError):
        generate_paper(small_bank, small_graph, {"a": 99}, seed=1)
    with pytest.raises(PaperError):
        generate_paper(small_bank, small_graph, {"a": 0}, seed=1)


def test_selector_constraints(small_bank, small_graph):
    profile = diagnose([], small_bank, small_graph)
    assert select_next_item(small_bank, profile, set(), {"a"}, {"a": 3}, per_kp_cap=3) is None
    got = []
    counts = {}
    for _ in range(3):
        nxt = select_next_item(small_bank, profile, set(got), {"a"}, counts, per_kp_cap=3)
        assert nxt is not None
        assert nxt not in got
        got.append(nxt)
        counts["a"] = counts.get("a", 0) + 1
    assert select_next_item(small_bank, profile, set(got), {"a"}, counts, per_kp_cap=3) is None


def test_selector_scope_and_administered(small_bank, small_graph):
    profile = diagnose([], small_bank, small_graph)
    assert select_next_item(small_bank, profile, {"a1", "a2", "a3"}, {"a"}, {}, per_kp_cap=9) is None
    outside = select_next_item(small_bank, profile, set(), {"b"}, {}, per_kp_cap=9)
    assert small_bank.get(outside).kps[0] == "b"


def test_selector_picks_max_information(small_bank, small_graph):
    from xuexing.paper import predicted_correct
    profile = diagnose([Response("a1", True)], small_bank, small_graph)
    chosen = select_next_item(small_bank, profile, set(), {"a", "b", "c", "d"}, {}, per_kp_cap=99)
    it = small_bank.get(chosen)
    p_chosen = abs(predicted_correct(profile, it.difficulty, profile.mastery[it.kps[0]], it.effective_guess()) - 0.5)
    for other in small_bank.items():
        p_other = abs(predicted_correct(profile, other.difficulty, profile.mastery[other.kps[0]], other.effective_guess()) - 0.5)
        assert p_chosen <= p_other + 1e-9
