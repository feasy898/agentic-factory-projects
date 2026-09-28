import pytest

from xuexing.kpgraph import KPGraph, KPGraphError
from xuexing.types import KnowledgePoint


def _kp(kp_id, prereqs=None):
    return KnowledgePoint(id=kp_id, name=kp_id, subject="math", grade=7, cluster="c", prereqs=prereqs or [])


def test_topological_order_respects_prereqs(graph):
    order = graph.topological_order()
    assert len(order) == len(graph.kps())
    pos = {k: i for i, k in enumerate(order)}
    for kp in graph.kps():
        for p in kp.prereqs:
            assert pos[p] < pos[kp.id]


def test_ancestors_and_descendants(graph):
    anc = graph.ancestors("kp_absvalue")
    assert anc == {"kp_numberline", "kp_posneg", "kp_opposite"}
    desc = graph.descendants("kp_posneg")
    assert "kp_absvalue" in desc and "kp_mixed_ops" in desc and "kp_posneg" not in desc


def test_prereqs_direct(graph):
    assert set(graph.prereqs("kp_absvalue")) == {"kp_numberline", "kp_opposite"}
    assert graph.prereqs("kp_posneg") == []


def test_cycle_detected():
    g = KPGraph()
    g.add_kp(_kp("a"))
    g.add_kp(_kp("b"))
    g.add_kp(_kp("c"))
    g.add_edge("a", "b")
    g.add_edge("b", "c")
    g.add_edge("c", "a")
    errs = g.validate()
    assert any("cycle" in e for e in errs)


def test_duplicate_kp_raises():
    g = KPGraph()
    g.add_kp(_kp("a"))
    with pytest.raises(KPGraphError):
        g.add_kp(_kp("a"))


def test_unknown_edge_endpoint_raises():
    g = KPGraph()
    g.add_kp(_kp("a"))
    with pytest.raises(KPGraphError):
        g.add_edge("a", "ghost")


def test_frontier_requires_mastered_prereqs(graph):
    mastery = {kp.id: 0.9 for kp in graph.kps()}
    mastery["kp_numberline"] = 0.2
    frontier = graph.frontier(mastery, threshold=0.65)
    assert "kp_numberline" in frontier  # 自身薄弱且先序 posneg 已掌握
    assert "kp_absvalue" not in frontier  # 先序 numberline 未掌握，被挡住


def test_frontier_sorted_by_impact(graph):
    mastery = {kp.id: 0.0 for kp in graph.kps()}
    frontier = graph.frontier(mastery, threshold=0.65)
    assert frontier[0] == "kp_posneg"  # 后代最多，影响最大
    assert frontier[1] == "kp_geometry_basic"
