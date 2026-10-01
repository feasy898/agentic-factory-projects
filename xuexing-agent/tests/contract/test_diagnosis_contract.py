"""契约：diagnosis —— 诊断引擎的可观测行为（算法自由，行为必须一致）。"""
import pytest

from xuexing.diagnosis import aggregate_to_clusters, diagnose, slip_from_difficulty
from xuexing.types import Response


def test_determinism(small_bank, small_graph):
    rs = [Response("a1", True), Response("a2", False)]
    p1 = diagnose(rs, small_bank, small_graph, learner_id="u")
    p2 = diagnose(rs, small_bank, small_graph, learner_id="u")
    assert p1.mastery == p2.mastery and p1.evidence == p2.evidence


def test_correct_above_prior_wrong_below(small_bank, small_graph):
    up = diagnose([Response("a1", True), Response("a2", True), Response("a3", True)],
                  small_bank, small_graph).mastery["a"]
    down = diagnose([Response("a1", False), Response("a2", False), Response("a3", False)],
                    small_bank, small_graph).mastery["a"]
    assert up > 0.6 and down < 0.4


def test_monotone_in_number_of_correct(small_bank, small_graph):
    m1 = diagnose([Response("a1", True)], small_bank, small_graph).mastery["a"]
    m3 = diagnose([Response("a1", True), Response("a2", True), Response("a3", True)],
                  small_bank, small_graph).mastery["a"]
    assert m3 > m1 > 0.5


def test_guess_aware(small_bank, small_graph):
    # d1 是选择题 guess=0.25；d2 填空题 guess 默认 0.1 —— 同为答对，高猜测题的证据力更弱
    hi = diagnose([Response("d1", True)], small_bank, small_graph).mastery["d"]
    lo = diagnose([Response("d2", True)], small_bank, small_graph).mastery["d"]
    assert lo > hi > 0.5


def test_unknown_item_ignored(small_bank, small_graph):
    p = diagnose([Response("ghost", True)], small_bank, small_graph)
    assert p.mastery["a"] == 0.5 and p.evidence["a"] == 0


def test_prereq_fill_only_without_direct_evidence(small_bank, small_graph):
    # b 答对 -> 无直接证据的 a 被补证抬升
    p = diagnose([Response("b1", True), Response("b2", True)], small_bank, small_graph)
    assert p.mastery["a"] > 0.5
    assert p.mastery["b"] > p.mastery["a"]
    # a 有直接负证据时，间接补证不得覆盖直接证据
    p2 = diagnose([Response("a1", False), Response("a2", False), Response("b1", True), Response("b2", True)],
                  small_bank, small_graph)
    assert p2.mastery["a"] < 0.5


def test_evidence_and_confidence(small_bank, small_graph):
    p = diagnose([Response("a1", True), Response("a2", False)], small_bank, small_graph)
    assert p.evidence["a"] == 2 and p.evidence["b"] == 0
    assert p.confidence("a") > p.confidence("b")


def test_slip_monotone():
    assert slip_from_difficulty(0.9) > slip_from_difficulty(0.1) > 0


def test_cluster_aggregation(small_bank, small_graph):
    p = diagnose([Response("a1", True)], small_bank, small_graph)
    clusters = aggregate_to_clusters(p, small_graph)
    assert set(clusters) == {"c1", "c2"}
    assert all(0 <= v <= 1 for v in clusters.values())


def test_invalid_prior_rejected(small_bank, small_graph):
    with pytest.raises(ValueError):
        diagnose([], small_bank, small_graph, prior=1.0)
