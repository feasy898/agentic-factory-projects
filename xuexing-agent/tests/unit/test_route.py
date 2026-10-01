from datetime import date

import pytest

from xuexing.diagnosis import diagnose
from xuexing.route import RouteError, build_plan
from xuexing.types import Response


def _diagnose_all(bank, graph, correct_items, learner="u"):
    rs = [Response(i, True) for i in correct_items]
    return diagnose(rs, bank, graph, learner_id=learner)


def test_plan_covers_all_weak_kps(bank, graph, strategies):
    profile = _diagnose_all(bank, graph, [])  # 全部 prior 0.5 < 0.65
    plan = build_plan(profile, bank, graph, strategies, date(2026, 9, 28))
    weak = {k for k, m in profile.mastery.items() if m < 0.65}
    planned = {s.kp_id for s in plan.steps}
    assert planned == weak


def test_plan_topological_order(bank, graph, strategies):
    profile = _diagnose_all(bank, graph, [])
    plan = build_plan(profile, bank, graph, strategies, date(2026, 9, 28))
    pos = {s.kp_id: i for i, s in enumerate(plan.steps)}
    for s in plan.steps:
        for p in graph.prereqs(s.kp_id):
            if p in pos:
                assert pos[p] < pos[s.kp_id]


def test_plan_strategy_matches_mastery_band(bank, graph, strategies):
    # 构造：一元一次方程全错（低掌握），其余全对（高掌握）
    eq_items = [i.id for i in bank.by_kp("kp_eq_concept", primary_only=True)]
    eq_items += [i.id for i in bank.by_kp("kp_eq_solve", primary_only=True)]
    eq_items += [i.id for i in bank.by_kp("kp_eq_apply", primary_only=True)]
    rs = []
    for it in bank.items():
        if it.id in eq_items:
            rs.append(Response(it.id, False))
        elif it.kps[0].startswith("kp_"):
            rs.append(Response(it.id, True))
    profile = diagnose(rs, bank, graph, learner_id="u")
    plan = build_plan(profile, bank, graph, strategies, date(2026, 9, 28))
    assert plan.steps, "should have weak steps"
    for s in plan.steps:
        m = profile.mastery[s.kp_id]
        if m < 0.4:
            assert s.strategy_id == "s_worked_example"
        else:
            assert s.strategy_id == "s_retrieval"


def test_reviews_only_for_mastered(bank, graph, strategies):
    rs = [Response(i, True) for i in ("m7_010", "m7_011", "m7_012", "m7_013", "m7_014")]
    profile = diagnose(rs, bank, graph, learner_id="u")
    plan = build_plan(profile, bank, graph, strategies, date(2026, 9, 28))
    review_kps = {r.kp_id for r in plan.reviews}
    for kp_id in review_kps:
        assert profile.mastery[kp_id] >= 0.65
    assert all(r.due > "2026-09-28" for r in plan.reviews)


def test_invalid_params_raise(bank, graph, strategies):
    profile = diagnose([], bank, graph)
    with pytest.raises(RouteError):
        build_plan(profile, bank, graph, strategies, date(2026, 9, 28), mastery_threshold=0.0)
    with pytest.raises(RouteError):
        build_plan(profile, bank, graph, strategies, date(2026, 9, 28), session_size=0)
