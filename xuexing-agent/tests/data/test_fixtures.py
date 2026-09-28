"""知识库（数据）校验：图谱、题库、策略、误解四类资产的完整性。"""
import json


def test_kpgraph_is_valid_dag(graph):
    assert graph.validate() == []
    order = graph.topological_order()
    assert len(order) == len(graph.kps())


def test_kpgraph_coverage_and_metadata(graph):
    for kp in graph.kps():
        assert kp.name and kp.cluster and kp.standard_ref, f"{kp.id} missing metadata"
        assert 7 <= kp.grade <= 9
    clusters = {kp.cluster for kp in graph.kps()}
    assert clusters == {"有理数", "整式加减", "一元一次方程", "图形初步"}


def test_items_reference_valid_kps(bank, graph):
    errs = bank.validate_all(valid_kp_ids={kp.id for kp in graph.kps()})
    assert errs == [], errs


def test_every_kp_has_at_least_one_primary_item(bank, graph):
    missing = [kp.id for kp in graph.kps() if not bank.by_kp(kp.id, primary_only=True)]
    assert missing == [], f"kps without items: {missing}"


def test_misconception_refs_valid(bank, graph, root):
    data = json.load(open(f"{root}/data/misconceptions/math_misconceptions.json", encoding="utf-8"))
    kp_ids = {kp.id for kp in graph.kps()}
    mc_ids = set()
    for mc in data["misconceptions"]:
        assert mc["kp_id"] in kp_ids, mc["id"]
        assert mc["hint"], f"{mc['id']} missing hint"
        mc_ids.add(mc["id"])
    for it in bank.items():
        for m in it.misconceptions:
            assert m in mc_ids, f"{it.id}: unknown misconception {m}"


def test_strategies_have_evidence_and_fallback(strategies):
    all_s = strategies.strategies()
    assert len(all_s) >= 5
    for s in all_s:
        assert s.evidence, f"{s.id} missing evidence"
    # 兜底策略：任意 (mastery, grade) 都能选出策略
    for m in (0.05, 0.5, 0.95):
        for g in (3, 7, 9):
            strategies.select(m, g)
