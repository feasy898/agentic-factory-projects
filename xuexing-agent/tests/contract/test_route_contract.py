"""契约：route —— 学习路线规划。"""
from datetime import date

import pytest

from xuexing.diagnosis import diagnose
from xuexing.route import RouteError, build_plan
from xuexing.types import Response

TODAY = date(2026, 9, 28)


def _profile(bank, graph, wrong_kp, correct_all_others=True):
    rs = []
    for it in bank.items():
        if it.kps[0] == wrong_kp:
            rs.append(Response(it.id, False))
        else:
            rs.append(Response(it.id, True))
    return diagnose(rs, bank, graph, learner_id="u")


def test_plan_covers_weak_and_respects_topology(bank, graph, strategies):
    profile = _profile(bank, graph, "kp_rational_add")
    plan = build_plan(profile, bank, graph, strategies, TODAY)
    weak = {k for k, m in profile.mastery.items() if m < 0.65}
    assert {s.kp_id for s in plan.steps} == weak
    pos = {s.kp_id: i for i, s in enumerate(plan.steps)}
    for s in plan.steps:
        for p in graph.prereqs(s.kp_id):
            if p in pos:
                assert pos[p] < pos[s.kp_id]


def test_reviews_only_mastered_and_future(bank, graph, strategies):
    profile = _profile(bank, graph, "kp_power")
    plan = build_plan(profile, bank, graph, strategies, TODAY)
    mastered = {k for k, m in profile.mastery.items() if m >= 0.65}
    assert {r.kp_id for r in plan.reviews} <= mastered
    assert all(r.due > TODAY.isoformat() for r in plan.reviews)
    assert "kp_power" not in {r.kp_id for r in plan.reviews}


def test_steps_have_strategy_and_target(bank, graph, strategies):
    profile = _profile(bank, graph, "kp_eq_solve")
    plan = build_plan(profile, bank, graph, strategies, TODAY)
    assert plan.steps
    for s in plan.steps:
        assert strategies.get(s.strategy_id) is not None
        assert 0.5 < s.target_mastery <= 1.0
        m = profile.mastery[s.kp_id]
        if m < 0.4:
            assert s.strategy_id == "s_worked_example"


def test_param_validation(bank, graph, strategies):
    profile = _profile(bank, graph, "kp_power")
    with pytest.raises(RouteError):
        build_plan(profile, bank, graph, strategies, TODAY, mastery_threshold=1.5)
    with pytest.raises(RouteError):
        build_plan(profile, bank, graph, strategies, TODAY, session_size=0)


def test_deterministic(bank, graph, strategies):
    profile = _profile(bank, graph, "kp_power")
    p1 = build_plan(profile, bank, graph, strategies, TODAY)
    p2 = build_plan(profile, bank, graph, strategies, TODAY)
    assert [s.kp_id for s in p1.steps] == [s.kp_id for s in p2.steps]
    assert [(r.kp_id, r.due) for r in p1.reviews] == [(r.kp_id, r.due) for r in p2.reviews]
