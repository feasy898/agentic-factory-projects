"""契约：server（新模块 API 端点）—— kt/blueprint/grading/recommend/itembank_v2/
standard_coverage 的 HTTP 暴露（specs/drafts/server.spec.md）。

薄胶水层行为契约：端点输出必须与直接调用内核函数逐字段等价（I1 内核等价），
错误映射固定（领域 ValueError→400、资源缺失→404、形态违规→422、绝不 500）。
闭式值全部现算核实（夹具值见各测试注释；grade7 真实数据闭式在
tests/integration/test_module_apis.py）：
- /trace：g_half(kp a, fill, d=0.3) 对@0 错@7 → 首快照 a=0.89899（odds 1→×8.9），
  末快照 a=0.090741 = round(979/10789, 6)（×0.5 衰减再 ×0.11/0.9 负证据），
  无证据 kp 保持 prior 0.5；
- /blueprint：targets [b,a] budget 4 缺省配比 → 最大余数法 记忆2/理解1/应用1，
  counts {"a":3,"b":1}（C2 均分后 C3 无零格）；
- /recommend：kp b 池 Tier1=[b_t1(0.3),b_t2(0.6)]（带绑定到 b 的误解标签），
  Tier2=[b_g1(0.1), b_g2(0.2, 标签属于外 KP)] → ["b_t1","b_t2","b_g1","b_g2"]。
"""
from datetime import date
import json

import pytest
from fastapi.testclient import TestClient

from xuexing.blueprint import build_blueprint
from xuexing.itembank import ItemBank
from xuexing.kpgraph import KPGraph
from xuexing.kt import KTEvent, to_profile, trace
from xuexing.pedagogy import StrategyLibrary
from xuexing.recommend import (
    attach_recommendations,
    recommend_for_kp,
    recommend_for_profile,
)
from xuexing.route import build_plan
from xuexing.server import create_app
from xuexing.standard_coverage import check_coverage_dicts
from xuexing.types import Item, KnowledgePoint, Misconception, Strategy


# ---------- 自封闭夹具（不依赖 data/；闭式值见文件头） ----------

@pytest.fixture
def graph():
    g = KPGraph()
    g.add_kp(KnowledgePoint(id="a", name="甲", subject="math", grade=7, cluster="c1"))
    g.add_kp(KnowledgePoint(id="b", name="乙", subject="math", grade=7, cluster="c1", prereqs=["a"]))
    g.add_kp(KnowledgePoint(id="c", name="丙", subject="math", grade=7, cluster="c2", prereqs=["b"]))
    g.add_kp(KnowledgePoint(id="d", name="丁", subject="math", grade=7, cluster="c2"))
    for kp in g.kps():
        for p in kp.prereqs:
            g.add_edge(p, kp.id)
    return g


@pytest.fixture
def bank():
    b = ItemBank()

    def add(item_id, kp, difficulty, item_type="fill", options=None,
            answer="ans", guess=None, mcs=()):
        b.add(Item(
            id=item_id, item_type=item_type, stem=f"stem-{item_id}", answer=answer,
            kps=[kp], difficulty=difficulty, options=options or [], guess=guess,
            misconceptions=list(mcs),
        ))

    add("g_half", "a", 0.3, answer="1/2")
    add("g_unit", "a", 0.4, answer="0.5米")
    add("g_lit", "a", 0.5, answer="x+1")
    add("g_choice", "d", 0.5, item_type="choice", options=["A. 1", "B. 2"],
        answer="B", guess=0.25)
    add("b_t1", "b", 0.3, mcs=["mc_b1"])
    add("b_t2", "b", 0.6, mcs=["mc_b2"])
    add("b_g1", "b", 0.1)
    add("b_g2", "b", 0.2, mcs=["mc_foreign"])
    return b


@pytest.fixture
def strategies():
    lib = StrategyLibrary()
    lib.add(Strategy(id="s_low", name="低", description="d", priority=10,
                     evidence="E1", mastery_lt=0.4))
    lib.add(Strategy(id="s_fallback", name="兜底", description="d", priority=0,
                     evidence="E2"))  # 无条件兜底
    return lib


@pytest.fixture
def mcs():
    return [
        Misconception(id="mc_b1", kp_id="b", description="d1", hint="h1"),
        Misconception(id="mc_b2", kp_id="b", description="d2", hint="h2"),
        Misconception(id="mc_foreign", kp_id="c", description="d3", hint="h3"),
    ]


@pytest.fixture
def client(bank, graph, strategies, mcs):
    return TestClient(create_app(bank, graph, strategies, mcs))


@pytest.fixture
def topics():
    return {"domains": [{"domain": "数与代数", "themes": [{"theme": "数与式", "topics": [
        {"id": "T1", "name": "有理数", "requirement": "理解有理数的意义", "aliases": ["有理数"]},
        {"id": "T2", "name": "方程", "requirement": "能解一元一次方程", "aliases": ["一元一次方程"]},
        {"id": "T3", "name": "函数", "requirement": "函数初步", "aliases": ["函数"]},
    ]}]}]}


def _seed_profile(client, learner_id="kt-1"):
    """经 /trace 存一份画像：a 弱(0.090741)，b/c/d 恰 0.5。"""
    r = client.post("/trace", json={
        "learner_id": learner_id,
        "events": [{"item_id": "g_half", "correct": True, "day": 0.0},
                   {"item_id": "g_half", "correct": False, "day": 7.0}]})
    assert r.status_code == 200
    return r.json()


def _seed_events():
    return [KTEvent("g_half", True, 0.0), KTEvent("g_half", False, 7.0)]


# ---------- /trace ----------

def test_trace_matches_kernel_and_closed_form(client, bank, graph):
    r = client.post("/trace", json={
        "events": [{"item_id": "g_half", "correct": True, "day": 0.0},
                   {"item_id": "g_half", "correct": False, "day": 7.0}]})
    assert r.status_code == 200
    out = r.json()
    kernel = trace(_seed_events(), bank, graph)  # I1 内核等价
    assert out["learner_id"] is None and out["profile_saved"] is False
    assert out["snapshots"] == [
        {"day": s.day, "item_id": s.item_id, "correct": s.correct,
         "mastery": s.mastery, "evidence": s.evidence} for s in kernel]
    # 闭式：首快照 odds 1→×8.9 → 0.89899；末快照 round(979/10789, 6)=0.090741
    assert out["snapshots"][0]["mastery"]["a"] == 0.89899
    assert out["snapshots"][1]["mastery"]["a"] == 0.090741
    assert out["snapshots"][1]["mastery"]["b"] == 0.5  # 无证据：不衰减、保持 prior
    assert out["snapshots"][1]["evidence"] == {"a": 2, "b": 0, "c": 0, "d": 0}


def test_trace_skips_unknown_items(client):
    r = client.post("/trace", json={"events": [
        {"item_id": "ghost", "correct": True, "day": 0.0},
        {"item_id": "g_half", "correct": True, "day": 1.0}]})
    assert r.status_code == 200
    snaps = r.json()["snapshots"]
    assert len(snaps) == 1  # 题库外事件：无快照、不推时钟（I9）
    assert (snaps[0]["item_id"], snaps[0]["day"]) == ("g_half", 1.0)


def test_trace_semantic_errors_400(client):
    ok = [{"item_id": "g_half", "correct": True, "day": 1.0}]
    assert client.post("/trace", json={"events": [  # day 降序
        {"item_id": "g_half", "correct": True, "day": 2.0},
        {"item_id": "g_half", "correct": True, "day": 1.0}]}).status_code == 400
    assert client.post("/trace", json={"events": ok, "prior": 0.0}).status_code == 400
    assert client.post("/trace", json={"events": ok, "prior": 1.0}).status_code == 400
    assert client.post("/trace", json={"events": ok, "half_life_days": 0}).status_code == 400
    # NaN day：pydantic 放行（allow_inf_nan），内核链式比较拒绝 → 400
    nan_body = json.dumps({"events": [{"item_id": "g_half", "correct": True,
                                       "day": float("nan")}]}, allow_nan=True)
    nan_r = client.post("/trace", content=nan_body.encode("utf-8"),
                        headers={"Content-Type": "application/json"})
    assert nan_r.status_code == 400


def test_trace_schema_error_422(client):
    assert client.post("/trace", json={"events": [
        {"item_id": 123, "correct": True, "day": 0.0}]}).status_code == 422
    assert client.post("/trace", json={"events": [
        {"item_id": "g_half", "correct": True, "day": "abc"}]}).status_code == 422


def test_trace_saves_profile_and_composes(client):
    out = _seed_profile(client)
    assert out["profile_saved"] is True and out["learner_id"] == "kt-1"
    final = out["snapshots"][-1]
    p = client.get("/learners/kt-1/profile")
    assert p.status_code == 200
    assert p.json()["mastery"] == final["mastery"]  # I6 共享 store
    assert p.json()["evidence"] == final["evidence"]
    rec = client.post("/recommend", json={"learner_id": "kt-1"})
    assert rec.status_code == 200  # 画像可直接喂 /recommend
    assert rec.json()["recommendations"][0]["kp_id"] == "a"


def test_trace_empty_events(client):
    r = client.post("/trace", json={"events": []})
    assert r.status_code == 200 and r.json()["snapshots"] == []
    assert client.post("/trace", json={"events": [],
                                       "learner_id": "kt-x"}).status_code == 400


# ---------- /blueprint ----------

def test_blueprint_matches_kernel_and_closed_form(client, graph):
    r = client.post("/blueprint", json={"targets": ["b", "a"], "budget": 4})
    assert r.status_code == 200
    out = r.json()
    bp = build_blueprint(["b", "a"], 4, graph)
    assert out["targets"] == ["a", "b"]  # 排序去重
    assert out["ratios"] == bp.ratios == {"记忆": 0.4, "理解": 0.4, "应用": 0.2}
    assert out["counts"] == bp.counts() == {"a": 3, "b": 1}  # 闭式（最大余数法）
    assert out["allocation"] == bp.allocation == {
        "a": {"记忆": 1, "理解": 1, "应用": 1}, "b": {"记忆": 1}}
    assert out["dimension_totals"] == bp.dimension_totals == {"记忆": 2, "理解": 1, "应用": 1}
    assert [d["dimension"] for d in out["per_dimension"]] == ["记忆", "理解", "应用"]
    assert [d["difficulty_target"] for d in out["per_dimension"]] == [0.2, 0.5, 0.8]
    assert sum(out["counts"].values()) == out["budget"] == 4


def test_blueprint_deterministic_and_order_independent(client):
    r1 = client.post("/blueprint", json={"targets": ["b", "a"], "budget": 4})
    r2 = client.post("/blueprint", json={"targets": ["b", "a"], "budget": 4})
    r3 = client.post("/blueprint", json={"targets": ["a", "b"], "budget": 4})
    assert r1.json() == r2.json() == r3.json()  # 同输入同输出 + 输入顺序无关
    assert r1.content == r2.content  # 逐字节相等（无时间戳字段，I3）


def test_blueprint_errors_400(client):
    assert client.post("/blueprint", json={"targets": ["ghost"],
                                           "budget": 1}).status_code == 400
    assert client.post("/blueprint", json={"targets": ["a", "b"],
                                           "budget": 1}).status_code == 400
    assert client.post("/blueprint", json={"targets": ["a"], "budget": 1,
                                           "ratios": {"记忆": 0}}).status_code == 400
    assert client.post("/blueprint", json={"targets": [],
                                           "budget": 1}).status_code == 400


def test_blueprint_feeds_papers_diagnostic(client):
    counts = client.post("/blueprint", json={
        "targets": ["a", "b"], "budget": 4}).json()["counts"]
    r = client.post("/papers/diagnostic", json={"blueprint": counts, "seed": 7})
    assert r.status_code == 200  # 组装闭环：蓝图 counts 直接出卷
    paper = r.json()
    assert len(paper["item_ids"]) == 4 and set(paper["blueprint"]) == {"a", "b"}


# ---------- /grade ----------

def test_grade_numeric_equivalence(client):
    for ans in ("0.5", "50%", "2/4", "1/2"):
        assert client.post("/grade", json={"item_id": "g_half",
                                           "learner_answer": ans}).json()["correct"] is True
    for ans in ("1/3", "0.6"):
        assert client.post("/grade", json={"item_id": "g_half",
                                           "learner_answer": ans}).json()["correct"] is False


def test_grade_unit_gate_no_conversion(client):
    cases = [("0.5米", True), ("0.5 米", True),   # 空白折叠后同单位
             ("50厘米", False), ("0.5", False)]   # 异单位/缺单位判错，不换算
    for ans, want in cases:
        assert client.post("/grade", json={"item_id": "g_unit",
                                           "learner_answer": ans}).json()["correct"] is want
    assert client.post("/grade", json={"item_id": "g_half",
                                       "learner_answer": "0.5米"}).json()["correct"] is False


def test_grade_literal_and_choice(client):
    assert client.post("/grade", json={"item_id": "g_lit",
                                       "learner_answer": "X + 1"}).json()["correct"] is True
    assert client.post("/grade", json={"item_id": "g_lit",
                                       "learner_answer": "x+2"}).json()["correct"] is False
    for ans, want in (("B", True), ("B. 2", True), ("A", False), ("C", False), (None, False)):
        r = client.post("/grade", json={"item_id": "g_choice", "learner_answer": ans})
        assert r.json()["correct"] is want
    assert client.post("/grade", json={"item_id": "g_half",
                                       "learner_answer": None}).json()["correct"] is False


def test_grade_response_shape_is_kernel_response(client):
    r = client.post("/grade", json={"item_id": "g_half", "learner_answer": "50%"})
    assert r.status_code == 200
    assert r.json() == {"item_id": "g_half", "correct": True,
                        "learner_answer": "50%", "response_ms": None}


def test_grade_unknown_item_404(client):
    assert client.post("/grade", json={"item_id": "ghost",
                                       "learner_answer": "x"}).status_code == 404
    assert client.post("/grade", json={"answers": [
        {"item_id": "g_half", "learner_answer": "0.5"},
        {"item_id": "ghost", "learner_answer": "x"}]}).status_code == 404  # 原子（I4）


def test_grade_batch_order_and_shape(client):
    payload = {"answers": [
        {"item_id": "g_half", "learner_answer": "50%"},
        {"item_id": "g_choice", "learner_answer": "A"},
        {"item_id": "g_lit", "learner_answer": "x+1"}]}
    r1 = client.post("/grade", json=payload)
    r2 = client.post("/grade", json=payload)
    assert r1.status_code == 200 and r1.json() == r2.json()
    out = r1.json()
    assert out["mode"] == "batch" and out["n"] == 3
    assert [x["item_id"] for x in out["results"]] == ["g_half", "g_choice", "g_lit"]
    assert [x["correct"] for x in out["results"]] == [True, False, True]
    assert all(set(x) == {"item_id", "correct", "learner_answer", "response_ms"}
               for x in out["results"])


def test_grade_mode_dispatch(client):
    assert client.post("/grade", json={}).status_code == 400  # 皆空
    r = client.post("/grade", json={"item_id": "g_half", "learner_answer": "0.5",
                                    "answers": [{"item_id": "g_choice",
                                                 "learner_answer": "B"}]})
    assert r.json()["mode"] == "batch" and r.json()["n"] == 1  # 并存时批量优先（I5）


# ---------- /recommend ----------

def test_recommend_kp_mode_matches_kernel(client, bank, mcs):
    r = client.post("/recommend", json={"kp_id": "b"})
    assert r.status_code == 200
    assert r.json() == {"mode": "kp", "kp_id": "b",
                        "item_ids": ["b_t1", "b_t2", "b_g1", "b_g2"]}  # Tier1 在前（闭式）
    assert r.json()["item_ids"] == recommend_for_kp("b", bank, mcs)  # 内核等价
    lim = client.post("/recommend", json={"kp_id": "b", "limit": 2})
    assert lim.json()["item_ids"] == ["b_t1", "b_t2"]
    # 未知 kp：与内核一致返回 200 + []，不 404（I9）
    assert client.post("/recommend", json={"kp_id": "ghost"}).json() == {
        "mode": "kp", "kp_id": "ghost", "item_ids": []}


def test_recommend_profile_mode_weakest_first(client, bank, graph, mcs):
    _seed_profile(client)  # a≈0.09 弱，b/c/d=0.5
    r = client.post("/recommend", json={"learner_id": "kt-1"})
    assert r.status_code == 200 and r.json()["mode"] == "profile"
    got = [(x["kp_id"], x["item_ids"]) for x in r.json()["recommendations"]]
    assert got == [
        ("a", ["g_half", "g_unit", "g_lit"]),       # 最弱优先
        ("b", ["b_t1", "b_t2", "b_g1", "b_g2"]),    # 平局 0.5 按 kp_id 升序
        ("c", []),                                  # 池空诚实给空
        ("d", ["g_choice"]),
    ]
    profile = to_profile(trace(_seed_events(), bank, graph)[-1], "kt-1")
    kernel = recommend_for_profile(profile, bank, mcs)
    assert got == [(x.kp_id, x.item_ids) for x in kernel]  # 内核等价
    # 恰等阈值视为达标：threshold=0.5 剔除 b/c/d
    r5 = client.post("/recommend", json={"learner_id": "kt-1", "mastery_threshold": 0.5})
    assert [(x["kp_id"], x["item_ids"])
            for x in r5.json()["recommendations"]] == [
        ("a", ["g_half", "g_unit", "g_lit"])]


def test_recommend_errors(client):
    _seed_profile(client)
    assert client.post("/recommend", json={}).status_code == 400  # 皆空
    assert client.post("/recommend", json={"learner_id": "nobody"}).status_code == 404
    assert client.post("/recommend", json={"kp_id": "b", "limit": 0}).status_code == 400
    assert client.post("/recommend", json={"kp_id": "b", "limit": -1}).status_code == 400
    assert client.post("/recommend", json={"learner_id": "kt-1",
                                           "mastery_threshold": 1.5}).status_code == 400
    assert client.post("/recommend", json={"learner_id": "kt-1",
                                           "mastery_threshold": 0}).status_code == 400


def test_recommend_attach_mode_fills_steps(client, bank, graph, strategies, mcs):
    _seed_profile(client)
    r = client.post("/recommend", json={"learner_id": "kt-1", "attach": True})
    assert r.status_code == 200 and r.json()["mode"] == "plan"
    plan = r.json()["plan"]
    assert [(s["kp_id"], s["strategy_id"]) for s in plan["steps"]] == [
        ("a", "s_low"), ("b", "s_fallback"), ("c", "s_fallback"), ("d", "s_fallback")]
    recs = {s["kp_id"]: s["recommended_item_ids"] for s in plan["steps"]}
    assert recs["a"] == ["g_half", "g_unit", "g_lit"]
    assert recs["b"] == ["b_t1", "b_t2", "b_g1", "b_g2"]  # 误解标签 Tier1 在前
    assert recs["c"] == [] and recs["d"] == ["g_choice"]
    assert plan["learner_id"] == "kt-1" and plan["reviews"] == []
    # 内核等价（created_at 同日相等）
    profile = to_profile(trace(_seed_events(), bank, graph)[-1], "kt-1")
    kernel = attach_recommendations(
        build_plan(profile, bank, graph, strategies, date.today()), bank, mcs)
    assert [(s["kp_id"], s["strategy_id"], s["recommended_item_ids"])
            for s in plan["steps"]] == \
        [(s.kp_id, s.strategy_id, s.recommended_item_ids) for s in kernel.steps]
    # 既有 /plan 不受影响：步骤推荐仍为空列表（I8）
    legacy = client.get("/learners/kt-1/plan").json()
    assert all(s["recommended_item_ids"] == [] for s in legacy["steps"])


# ---------- /itembank/v2/validate ----------

def test_item_v2_valid_original(client):
    r = client.post("/itembank/v2/validate", json={"items": [
        {"id": "i1", "item_type": "fill", "stem": "s", "answer": "1",
         "kps": ["a"], "difficulty": 0.3, "source": "original"}]})
    assert r.status_code == 200
    out = r.json()
    assert out["valid"] is True and out["errors"] == []
    assert out["counts"] == {"original": 1, "adapted": 0, "llm_generated": 0}
    assert out["total"] == 1 and out["verified"] == 0  # original 允许无验证记录


def test_item_v2_error_catalogue(client):
    r = client.post("/itembank/v2/validate", json={"items": [
        {"id": "i2", "source": "llm_generated"},                       # 缺验证记录
        {"id": "i3", "source": "original",
         "verification": {"agents": ["x", "y"], "answers_agree": False}},  # 未通过
        {"id": "i4", "source": "original",
         "verification": {"agents": ["x"], "answers_agree": True}},     # 代理数不足
        {"id": "i5", "source": "original",
         "verification": {"agents": ["x", "x"], "answers_agree": True}},  # 代理重复
        {"id": "i6", "source": "adapted"},                              # 缺 source_ref
        "oops",                                                         # 非 dict
    ]})
    assert r.status_code == 200
    out = r.json()
    assert out["valid"] is False
    assert out["errors"] == [
        "i2: llm_generated requires verification",
        "i3: verification not passed",
        "i4: verification needs >=2 agents",
        "i5: duplicate verification agents",
        "i6: adapted requires non-empty source_ref",
        "item is not a dict",
    ]
    assert out["counts"] == {"original": 3, "adapted": 1, "llm_generated": 1}
    assert out["total"] == 6 and out["verified"] == 0


def test_item_v2_verified_count_and_determinism(client):
    body = {"items": [
        {"id": "ok1", "source": "original",
         "verification": {"agents": ["a1", "a2"], "answers_agree": True}},
        {"id": "ok2", "source": "original",
         "verification": {"agents": ["a1", "a2"], "answers_agree": False}}]}
    r1 = client.post("/itembank/v2/validate", json=body)
    r2 = client.post("/itembank/v2/validate", json=body)
    assert r1.json() == r2.json()  # 确定性（I3）
    out = r1.json()
    assert out["verified"] == 1  # 仅通过记录计数
    assert out["errors"] == ["ok2: verification not passed"]


# ---------- /coverage/standard ----------

def test_coverage_bidirectional_gaps(client, topics):
    kps = [{"id": "k1", "standard_ref": "2022课标：理解有理数的意义"},
           {"id": "k2", "standard_ref": "2022课标：一元一次方程的应用"},
           {"id": "k3", "standard_ref": "2022课标：某清单外内容"}]
    r1 = client.post("/coverage/standard", json={"kp_dicts": kps, "topics": topics})
    assert r1.status_code == 200
    out = r1.json()
    assert out["matches"] == [{"kp_id": "k1", "topic_ids": ["T1"]},
                              {"kp_id": "k2", "topic_ids": ["T2"]},
                              {"kp_id": "k3", "topic_ids": []}]
    assert out["uncovered_topic_ids"] == ["T3"]      # 覆盖缺口（清单原序）
    assert out["unmatched_kp_ids"] == ["k3"]         # 归属缺口（输入原序）
    assert out["covered_topic_ids"] == ["T1", "T2"]
    assert out["matched_kp_ids"] == ["k1", "k2"]
    assert out["coverage_rate"] == pytest.approx(2 / 3)
    assert out["is_complete"] is False
    # 内核等价
    kernel = check_coverage_dicts(kps, topics)
    assert out["uncovered_topic_ids"] == list(kernel.uncovered_topic_ids)
    assert out["coverage_rate"] == pytest.approx(kernel.coverage_rate)
    r2 = client.post("/coverage/standard", json={
        "kp_dicts": [{"id": "k1", "standard_ref": "理解有理数的意义"},
                     {"id": "k2", "standard_ref": "一元一次方程"},
                     {"id": "k3", "standard_ref": "函数"}],
        "topics": topics})
    assert r2.json()["is_complete"] is True
    assert r2.json()["coverage_rate"] == pytest.approx(1.0)


def test_coverage_errors_400(client, topics):
    dup_alias = {"domains": [{"domain": "d", "themes": [{"theme": "t", "topics": [
        {"id": "T1", "name": "n", "requirement": "r", "aliases": ["有理数"]},
        {"id": "T2", "name": "n", "requirement": "r", "aliases": ["有理数"]}]}]}]}
    assert client.post("/coverage/standard", json={
        "kp_dicts": [{"id": "k1"}], "topics": dup_alias}).status_code == 400
    assert client.post("/coverage/standard", json={
        "kp_dicts": [{"id": "k1"}],
        "topics": {"domains": []}}).status_code == 400
    assert client.post("/coverage/standard", json={
        "kp_dicts": [{"id": "k1"}, {"id": "k1"}], "topics": topics}).status_code == 400
    assert client.post("/coverage/standard", json={
        "kp_dicts": "not-a-list", "topics": topics}).status_code == 422


def test_coverage_readonly_and_deterministic(client, topics):
    body = {"kp_dicts": [{"id": "k1", "standard_ref": "有理数"}], "topics": topics}
    r1 = client.post("/coverage/standard", json=body)
    r2 = client.post("/coverage/standard", json=body)
    assert r1.content == r2.content  # 只读 + 逐字节确定（I3/I7）


# ---------- 全局：错误映射与既有端点兼容 ----------

def test_no_domain_error_becomes_500(client):
    # 抽查各端点的领域错误都映射为 4xx，绝不 500（I2）
    checks = [
        client.post("/trace", json={"events": [
            {"item_id": "g_half", "correct": True, "day": 3.0},
            {"item_id": "g_half", "correct": True, "day": 1.0}]}),
        client.post("/blueprint", json={"targets": ["ghost"], "budget": 1}),
        client.post("/grade", json={"item_id": "ghost", "learner_answer": "x"}),
        client.post("/recommend", json={"kp_id": "b", "limit": -1}),
        client.post("/coverage/standard", json={"kp_dicts": [],
                                                "topics": {"domains": []}}),
    ]
    assert all(400 <= r.status_code < 500 for r in checks)


def test_profile_404_before_any_trace(client):
    assert client.get("/learners/nobody/profile").status_code == 404  # 既有行为不变
