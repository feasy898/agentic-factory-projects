from xuexing.diagnosis import aggregate_to_clusters, diagnose, slip_from_difficulty
from xuexing.itembank import ItemBank
from xuexing.types import Item, Response


def _bank(items):
    b = ItemBank()
    for it in items:
        b.add(it)
    return b


def _one(item_id, kp, difficulty, guess=None, item_type="fill"):
    return Item(id=item_id, item_type=item_type, stem=item_id, answer="x",
                kps=[kp], difficulty=difficulty, guess=guess)


def test_correct_raises_mastery_wrong_lowers(graph, bank):
    rs = [Response(item_id=i, correct=True) for i in ("m7_010", "m7_011", "m7_012")]
    p = diagnose(rs, bank, graph, prior=0.5)
    assert p.mastery["kp_rational_add"] > 0.6
    rs2 = [Response(item_id=i, correct=False) for i in ("m7_010", "m7_011", "m7_012")]
    p2 = diagnose(rs2, bank, graph, prior=0.5)
    assert p2.mastery["kp_rational_add"] < 0.4


def test_monotonicity_more_correct_higher(graph, bank):
    items = ["m7_010", "m7_011", "m7_012"]
    m3 = diagnose([Response(i, True) for i in items], bank, graph).mastery["kp_rational_add"]
    m1 = diagnose([Response(items[0], True)], bank, graph).mastery["kp_rational_add"]
    assert m3 > m1 > 0.5


def test_guess_aware_update(graph):
    g = graph  # kp 独立于 bank
    b = _bank([_one("i1", "kp_posneg", difficulty=0.2, guess=0.9),
               _one("i2", "kp_posneg", difficulty=0.2, guess=0.05)])
    from xuexing.kpgraph import KPGraph
    from xuexing.types import KnowledgePoint
    kg = KPGraph()
    kg.add_kp(KnowledgePoint(id="kp_posneg", name="x", subject="math", grade=7, cluster="c"))
    p_low_guess = diagnose([Response("i2", True)], b, kg)
    p_high_guess = diagnose([Response("i1", True)], b, kg)
    assert p_low_guess.mastery["kp_posneg"] > p_high_guess.mastery["kp_posneg"]


def test_deterministic(graph, bank):
    rs = [Response("m7_007", True), Response("m7_016", False)]
    a = diagnose(rs, bank, graph, learner_id="u1")
    b = diagnose(rs, bank, graph, learner_id="u1")
    assert a.mastery == b.mastery and a.evidence == b.evidence


def test_prereq_consistency_upward_fill(graph, bank):
    # 只答对 kp_power 的题（先序 kp_rational_mul 无证据），平滑应把先序抬到 prior 之上
    p = diagnose([Response("m7_016", True), Response("m7_018", True)], bank, graph)
    assert p.mastery["kp_rational_mul"] > 0.5
    assert p.mastery["kp_power"] > p.mastery["kp_rational_mul"]


def test_evidence_counts(graph, bank):
    rs = [Response("m7_007", True), Response("m7_009", False)]
    p = diagnose(rs, bank, graph)
    assert p.evidence["kp_absvalue"] == 2
    assert p.evidence["kp_posneg"] == 0
    assert p.confidence("kp_absvalue") > p.confidence("kp_posneg")


def test_aggregate_clusters(graph, bank):
    p = diagnose([Response("m7_010", True)], bank, graph)
    clusters = aggregate_to_clusters(p, graph)
    assert set(clusters) == {"有理数", "整式加减", "一元一次方程", "图形初步"}
    assert all(0.0 <= v <= 1.0 for v in clusters.values())


def test_slip_monotone_in_difficulty():
    assert slip_from_difficulty(0.9) > slip_from_difficulty(0.1)
    assert abs(slip_from_difficulty(0.5) - 0.15) < 1e-9


def test_invalid_prior_raises(graph, bank):
    try:
        diagnose([], bank, graph, prior=1.0)
        raise AssertionError("should raise")
    except ValueError:
        pass
