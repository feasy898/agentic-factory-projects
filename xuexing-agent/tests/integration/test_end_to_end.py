"""端到端场景：合成学习者（已知真实掌握度）作答 -> 诊断 -> 路线 -> 修复卷。

这是系统的“验收实验”：诊断引擎必须能从作答恢复出掌握度的方向与量级。
"""
import random
from datetime import date

from xuexing.diagnosis import aggregate_to_clusters, diagnose
from xuexing.paper import generate_paper
from xuexing.route import build_plan
from xuexing.types import Response


def _truth_by_cluster(graph, strong_clusters, strong=0.9, weak=0.25):
    truth = {}
    for kp in graph.kps():
        truth[kp.id] = strong if kp.cluster in strong_clusters else weak
    return truth


def _simulate(bank, truth, rng, p_correct_if_mastered=0.9):
    rs = []
    for it in bank.items():
        m = truth.get(it.kps[0], 0.5)
        p = p_correct_if_mastered if m >= 0.65 else it.effective_guess()
        rs.append(Response(it.id, correct=rng.random() < p))
    return rs


def test_diagnosis_recovers_learning_direction(bank, graph):
    rng = random.Random(42)
    truth_strong_rational = _truth_by_cluster(graph, {"有理数"})
    truth_strong_equations = _truth_by_cluster(graph, {"一元一次方程"})

    p1 = diagnose(_simulate(bank, truth_strong_rational, rng), bank, graph, learner_id="L1")
    p2 = diagnose(_simulate(bank, truth_strong_equations, rng), bank, graph, learner_id="L2")

    c1 = aggregate_to_clusters(p1, graph)
    assert c1["有理数"] > c1["一元一次方程"] + 0.15
    c2 = aggregate_to_clusters(p2, graph)
    assert c2["一元一次方程"] > c2["有理数"] + 0.15


def test_diagnosis_accuracy_within_tolerance(bank, graph):
    rng = random.Random(7)
    truth = _truth_by_cluster(graph, {"有理数", "图形初步"})
    rs = _simulate(bank, truth, rng)
    profile = diagnose(rs, bank, graph, learner_id="L3")
    errs = [abs(profile.mastery[k] - truth[k]) for k in truth]
    mae = sum(errs) / len(errs)
    assert mae < 0.30, f"MAE={mae:.3f} too high"


def test_full_loop_diagnose_plan_repair_paper(bank, graph, strategies):
    rng = random.Random(123)
    truth = _truth_by_cluster(graph, {"有理数"})
    profile = diagnose(_simulate(bank, truth, rng), bank, graph, learner_id="L4")

    # 1) 路线：覆盖全部薄弱点，拓扑有效
    plan = build_plan(profile, bank, graph, strategies, date(2026, 9, 28))
    weak = {k for k, m in profile.mastery.items() if m < 0.65}
    assert {s.kp_id for s in plan.steps} == weak
    pos = {s.kp_id: i for i, s in enumerate(plan.steps)}
    for s in plan.steps:
        for p in graph.prereqs(s.kp_id):
            if p in pos:
                assert pos[p] < pos[s.kp_id]

    # 2) 修复卷：按薄弱点蓝图出卷成功
    blueprint = {}
    for kp_id in sorted(weak):
        avail = len(bank.by_kp(kp_id, primary_only=True))
        if avail:
            blueprint[kp_id] = min(2, avail)
    paper = generate_paper(bank, graph, blueprint, seed=99)
    assert len(paper.item_ids) == sum(blueprint.values())

    # 3) 自适应选题：8 题内不重复且不超过每知识点上限
    administered, counts = set(), {}
    for _ in range(8):
        nxt = None
        from xuexing.paper import select_next_item
        nxt = select_next_item(bank, profile, administered, {kp.id for kp in graph.kps()}, counts, per_kp_cap=2)
        if nxt is None:
            break
        administered.add(nxt)
        primary = bank.get(nxt).kps[0]
        counts[primary] = counts.get(primary, 0) + 1
    assert len(administered) >= 5
    assert all(v <= 2 for v in counts.values())
