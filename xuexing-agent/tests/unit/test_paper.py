import pytest

from xuexing.paper import PaperError, generate_paper, select_next_item
from xuexing.diagnosis import diagnose
from xuexing.types import Response


BLUEPRINT = {"kp_rational_add": 2, "kp_eq_solve": 2, "kp_absvalue": 2}


def test_blueprint_counts_and_no_duplicates(bank, graph):
    p = generate_paper(bank, graph, BLUEPRINT, seed=7)
    assert len(p.item_ids) == 6 and len(set(p.item_ids)) == 6
    by_sec = {s["kp_id"]: set(s["item_ids"]) for s in p.sections}
    assert by_sec["kp_rational_add"] and by_sec["kp_eq_solve"] and by_sec["kp_absvalue"]
    for s in p.sections:
        assert len(s["item_ids"]) == BLUEPRINT[s["kp_id"]]
        for iid in s["item_ids"]:
            assert bank.get(iid).kps[0] == s["kp_id"]


def test_determinism_same_seed(bank, graph):
    a = generate_paper(bank, graph, BLUEPRINT, seed=42)
    b = generate_paper(bank, graph, BLUEPRINT, seed=42)
    assert a.item_ids == b.item_ids


def test_unknown_kp_raises(bank, graph):
    with pytest.raises(PaperError):
        generate_paper(bank, graph, {"kp_ghost": 1}, seed=1)


def test_insufficient_items_raises(bank, graph):
    with pytest.raises(PaperError):
        generate_paper(bank, graph, {"kp_angles": 2}, seed=1)


def test_select_next_respects_scope_cap_and_administered(bank, graph):
    profile = diagnose([], bank, graph)  # 全 prior=0.5
    scope = {"kp_rational_add"}
    counts = {"kp_rational_add": 3}
    assert select_next_item(bank, profile, set(), scope, counts, per_kp_cap=3) is None
    counts = {"kp_rational_add": 1}
    first = select_next_item(bank, profile, set(), scope, counts, per_kp_cap=3)
    assert first is not None
    second = select_next_item(bank, profile, {first}, scope, counts, per_kp_cap=3)
    assert second is not None and second != first
    first = select_next_item(bank, profile, set(), scope, counts, per_kp_cap=3)
    assert first is not None
    second = select_next_item(bank, profile, {first}, scope, counts, per_kp_cap=3)
    assert second is not None and second != first
    # cap=2 且已计 2 次：即使还有没做过的题也必须停止（内容平衡约束）
    third = select_next_item(bank, profile, {first, second}, scope, {"kp_rational_add": 2}, per_kp_cap=2)
    assert third is None


def test_select_next_is_argmax_information(bank, graph):
    profile = diagnose([Response("m7_007", True)], bank, graph)
    scope = {kp.id for kp in graph.kps()}
    from xuexing.paper import predicted_correct
    chosen = select_next_item(bank, profile, set(), scope, {}, per_kp_cap=99)
    assert chosen is not None
    it = bank.get(chosen)
    best = max(
        (predicted_correct(profile, x.difficulty, profile.mastery.get(x.kps[0], 0.5), x.effective_guess()) for x in bank.items()),
        key=lambda p: -abs(p - 0.5),
    )
    got = predicted_correct(profile, it.difficulty, profile.mastery.get(it.kps[0], 0.5), it.effective_guess())
    assert abs(got - 0.5) <= abs(best - 0.5) + 1e-9
