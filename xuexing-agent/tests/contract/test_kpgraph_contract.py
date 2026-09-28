"""契约：KPGraph —— 图操作与查询语义。"""
import pytest

from xuexing.kpgraph import KPGraph, KPGraphError
from xuexing.types import KnowledgePoint


def _kp(kp_id, prereqs=None, cluster="c1"):
    return KnowledgePoint(id=kp_id, name=kp_id, subject="math", grade=7, cluster=cluster, prereqs=prereqs or [])


def test_topological_order_places_prereqs_first(small_graph):
    order = small_graph.topological_order()
    pos = {k: i for i, k in enumerate(order)}
    assert len(order) == 4
    assert pos["a"] < pos["b"] < pos["c"]


def test_cycle_is_rejected():
    g = KPGraph()
    for k in ("a", "b", "c"):
        g.add_kp(_kp(k))
    g.add_edge("a", "b")
    g.add_edge("b", "c")
    g.add_edge("c", "a")
    assert g.validate(), "cycle must be reported"
    with pytest.raises(Exception):
        g.topological_order()


def test_duplicate_and_unknown_errors():
    g = KPGraph()
    g.add_kp(_kp("a"))
    with pytest.raises(KPGraphError):
        g.add_kp(_kp("a"))
    with pytest.raises(KPGraphError):
        g.add_edge("a", "ghost")
    with pytest.raises(KPGraphError):
        g.add_edge("a", "a")


def test_ancestors_transitive(small_graph):
    assert small_graph.ancestors("c") == {"a", "b"}
    assert small_graph.descendants("a") == {"b", "c"}
    assert small_graph.prereqs("c") == ["b"]


def test_frontier_semantics(small_graph):
    mastery = {"a": 0.9, "b": 0.2, "c": 0.1, "d": 0.9}
    frontier = small_graph.frontier(mastery, threshold=0.65)
    assert "b" in frontier          # 弱且先序 a 已掌握
    assert "c" not in frontier      # 先序 b 未掌握
    assert "a" not in frontier and "d" not in frontier  # 已达标


def test_validate_reports_missing_edge_declaration():
    g = KPGraph()
    g.add_kp(_kp("a"))
    g.add_kp(_kp("b", prereqs=["a"]))
    assert g.validate() != []  # 声明了 prereq 但没加边
    g.add_edge("a", "b")
    assert g.validate() == []


def test_get_and_has(small_graph):
    assert small_graph.has("a") and not small_graph.has("z")
    assert small_graph.get("a").name == "甲"
    assert small_graph.get("z") is None
