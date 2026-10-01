"""契约：multitenant（机构多租户）—— org 维度数据隔离贯穿 store/attempt/api
（specs/drafts/multitenant.spec.md）。

分两层检验：内核层（OrgStore / AttemptCounter / resolve_org / org_key，纯数据
结构行为）与 HTTP 层（server.py 穿线 X-Org-Id + GET /orgs）。闭式值现算核实：
- /trace 夹具事件 [g_half 对@day0, 错@day7]（prior 0.5、半衰期 7）→ 首快照
  a=0.89899（odds 1→×8.9）、末快照 a=0.090741（= round(979/10789, 6)），
  evidence {"a": 2}，无证据 kp 保持 prior 0.5（与 test_server_contract 同源闭式）；
- /recommend、/profile 断言一律与内核直调结果逐字段对拍（org 不改领域值，I11）；
- next_item 选题确定性：同画像 + 空计数状态下跨 org 首选题相同，per_kp_cap=2
  在各 org 独立耗尽（kp a 恰 3 题入带：difficulty 0.3/0.4/0.5 ∈ [0.2, 0.8]）。

兼容红线：不带 X-Org-Id 的请求必须与单租户时代行为一致（本文件不改任何既有
测试；既有 test_server_contract / tests/unit/test_server.py 全绿即 I6 的另一半）。
"""
import pytest
from fastapi.testclient import TestClient

from xuexing.diagnosis import diagnose
from xuexing.itembank import ItemBank
from xuexing.kpgraph import KPGraph
from xuexing.kt import KTEvent, trace
from xuexing.multitenant import (
    DEFAULT_ORG_ID,
    AttemptCounter,
    OrgStore,
    org_key,
    resolve_org,
)
from xuexing.pedagogy import StrategyLibrary
from xuexing.server import create_app
from xuexing.types import Item, KnowledgePoint, Response, Strategy

ORG_A = "org-a"
ORG_B = "org-b"


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
            answer="ans", guess=None):
        b.add(Item(
            id=item_id, item_type=item_type, stem=f"stem-{item_id}", answer=answer,
            kps=[kp], difficulty=difficulty, options=options or [], guess=guess,
        ))

    add("g_half", "a", 0.3, answer="1/2")
    add("g_unit", "a", 0.4, answer="0.5米")
    add("g_lit", "a", 0.5, answer="x+1")
    add("g_choice", "d", 0.5, item_type="choice", options=["A. 1", "B. 2"],
        answer="B", guess=0.25)
    return b


@pytest.fixture
def strategies():
    lib = StrategyLibrary()
    lib.add(Strategy(id="s_low", name="低", description="d", priority=10,
                     evidence="E1", mastery_lt=0.4))
    lib.add(Strategy(id="s_fallback", name="兜底", description="d", priority=0,
                     evidence="E2"))  # 无条件兜底（/plan 需要）
    return lib


@pytest.fixture
def client(bank, graph, strategies):
    return TestClient(create_app(bank, graph, strategies))


def _trace_events():
    """闭式事件：g_half 对@0 错@7 → a: 0.89899 → 0.090741，evidence a=2。"""
    return [{"item_id": "g_half", "correct": True, "day": 0.0},
            {"item_id": "g_half", "correct": False, "day": 7.0}]


def _kernel_events(bank, graph):
    return [KTEvent(e["item_id"], e["correct"], e["day"]) for e in _trace_events()]


def _seed_trace(client, org, learner_id="kt"):
    r = client.post("/trace", json={"learner_id": learner_id, "events": _trace_events()},
                    headers={"X-Org-Id": org})
    assert r.status_code == 200 and r.json()["profile_saved"] is True
    return r.json()


# ---------- 内核：resolve_org（I2） ----------

def test_resolve_org_merges_defaults():
    assert resolve_org(None) == DEFAULT_ORG_ID == "default"
    assert resolve_org("") == DEFAULT_ORG_ID
    assert resolve_org("   ") == DEFAULT_ORG_ID
    assert resolve_org(" default ") == DEFAULT_ORG_ID  # 去空白后恰为缺省值
    assert resolve_org(DEFAULT_ORG_ID) == DEFAULT_ORG_ID


def test_resolve_org_verbatim_and_case_sensitive():
    assert resolve_org(" a ") == "a"
    assert resolve_org("A") == "A" != "a"
    assert resolve_org("a:b") == "a:b"      # 标点原样保留
    assert resolve_org("机构-01") == "机构-01"  # 非 ASCII 原样保留


@pytest.mark.parametrize("bad", [123, ["a"], b"org", object()])
def test_resolve_org_rejects_non_str(bad):
    with pytest.raises(TypeError):
        resolve_org(bad)


# ---------- 内核：org_key（I1） ----------

def test_org_key_injective_and_deterministic():
    pairs = [("a", "bc"), ("ab", "c"), ("", "abc"), ("abc", ""),
             ("a:x", "y"), ("a", "x:y"), ("A", "a"), ("a", "A")]
    keys = [org_key(o, l) for o, l in pairs]
    assert len(keys) == len(set(keys))          # 两两不同（单射）
    assert org_key("a:x", "y") != org_key("a", "x:y")  # 分隔符歧义对不碰撞
    assert org_key("a:x", "y") == org_key("a:x", "y")  # 同输入同输出


@pytest.mark.parametrize("pair", [(None, "a"), ("a", None), (1, "a"), ("a", 2.5)])
def test_org_key_rejects_non_str(pair):
    with pytest.raises(TypeError):
        org_key(*pair)


# ---------- 内核：OrgStore（I3/I4） ----------

def test_orgstore_isolates_same_learner_across_orgs():
    s = OrgStore()
    ea = s.entry(ORG_A, "L")
    eb = s.entry(ORG_B, "L")
    assert ea is not eb
    assert ea == {"responses": [], "history": []}  # 新档起步形状
    ea["responses"].append("r1")
    ea["history"].append(2)
    ea["profile"] = "P"
    assert eb == {"responses": [], "history": []}  # 另一 org 完全不可见
    assert s.get(ORG_A, "L") is ea
    assert s.get(ORG_B, "L") is eb
    assert s.get("org-c", "L") is None              # 未建档 org：None 且不建域


def test_orgstore_same_pair_returns_same_entry():
    s = OrgStore()
    e1 = s.entry("o", "L")
    e1["responses"].append("r1")
    assert s.entry("o", "L") is e1                  # 状态延续（同一 dict）
    assert s.get("o", "L") is e1


def test_orgstore_profile_helpers():
    s = OrgStore()
    assert s.has_profile("o", "L") is False         # 未建档
    s.entry("o", "M")                               # 建档但无画像
    assert s.has_profile("o", "M") is False
    s.set_profile("o", "L", {"m": 0.5})
    assert s.has_profile("o", "L") is True
    assert s.get("o", "L")["profile"] == {"m": 0.5}
    assert s.has_profile("other", "L") is False     # 画像不跨 org
    with pytest.raises(TypeError):
        s.set_profile(1, "L", {"m": 0.5})


def test_orgstore_merges_default_and_whitespace():
    s = OrgStore()
    assert s.entry(None, "L") is s.entry(DEFAULT_ORG_ID, "L")
    assert s.entry("", "L") is s.entry(DEFAULT_ORG_ID, "L")
    assert s.entry(" o ", "L") is s.entry("o", "L")  # 容器内强制归并
    # 归并后无空串/空白 org：只有缺省域与 "o"
    assert s.org_ids() == [DEFAULT_ORG_ID, "o"]


def test_orgstore_case_sensitive_orgs_are_distinct_domains():
    s = OrgStore()
    e_upper = s.entry("ORG", "L")
    e_lower = s.entry("org", "L")
    assert e_upper is not e_lower
    e_upper["responses"].append("r1")
    assert e_lower["responses"] == []
    assert s.learner_ids("ORG") == ["L"] and s.learner_ids("org") == ["L"]


def test_orgstore_enumeration_sorted_and_total():
    s = OrgStore()
    assert s.org_ids() == [] and s.learner_ids("ghost") == []
    s.entry("o2", "z")
    s.entry("o2", "a")
    s.entry("o1", "b")
    s.entry("o2", "m")                               # 插入顺序打乱
    assert s.learner_ids("o2") == ["a", "m", "z"]    # 恒升序
    assert s.learner_ids("o1") == ["b"]
    assert s.org_ids() == ["o1", "o2"]
    with pytest.raises(TypeError):
        s.get(1, "L")
    with pytest.raises(TypeError):
        s.entry("o", None)
    with pytest.raises(TypeError):
        s.learner_ids(3)


# ---------- 内核：AttemptCounter（I5） ----------

def test_attempt_counter_isolates_domains():
    c = AttemptCounter()
    assert c.bump("a", "L", "kp") == 1
    assert c.bump("a", "L", "kp") == 2               # 同键累加
    assert c.bump(ORG_B, "L", "kp") == 1             # 同 learner 异 org 独立
    assert c.bump("a", "M", "kp") == 1               # 同 org 异 learner 独立
    assert c.bump("a", "L", "kp2") == 1              # 同对异 kp 独立
    assert c.get("a", "L", "kp") == 2
    assert c.get("a", "L", "ghost") == 0             # 未计过为 0
    assert c.counts("a", "L") == {"kp": 2, "kp2": 1}
    assert c.counts(ORG_B, "L") == {"kp": 1}


def test_attempt_counter_merges_default_and_whitespace():
    c = AttemptCounter()
    assert c.counts(None, "L") is c.counts(DEFAULT_ORG_ID, "L")
    assert c.counts(" c ", "L") is c.counts("c", "L")
    c.bump(None, "L", "kp")
    assert c.get(DEFAULT_ORG_ID, "L", "kp") == 1


@pytest.mark.parametrize("call", [
    lambda c: c.counts(1, "a"),
    lambda c: c.counts("a", None),
    lambda c: c.bump("a", "L", 7),
    lambda c: c.get("a", "L", None),
])
def test_attempt_counter_rejects_non_str(call):
    with pytest.raises(TypeError):
        call(AttemptCounter())


# ---------- HTTP：缺省等价（I6）与无状态端点免疫（I10） ----------

def test_default_org_equivalence(client, bank, graph):
    body = {"responses": [{"item_id": "g_half", "correct": True}]}
    assert client.post("/learners/L1/responses", json=body).status_code == 200
    kernel = diagnose([Response(item_id="g_half", correct=True)],
                      bank, graph, learner_id="L1")  # org 不改领域值（I11）
    for org in (None, "", "default"):
        headers = {} if org is None else {"X-Org-Id": org}
        r = client.get("/learners/L1/profile", headers=headers)
        assert r.status_code == 200
        assert r.json()["mastery"] == kernel.mastery   # 无头 ≡ "" ≡ "default"
    assert client.get("/learners/L1/profile",
                      headers={"X-Org-Id": ORG_A}).status_code == 404


def test_stateless_endpoints_ignore_org_header(client):
    ok = {"X-Org-Id": "a:b"}
    assert client.post("/grade", json={"item_id": "g_half", "learner_answer": "0.5"},
                       headers=ok).status_code == 200
    assert client.post("/papers/diagnostic", json={"blueprint": {"a": 1}, "seed": 7},
                       headers=ok).status_code == 200
    # 既有错误映射不因 org 头改变
    assert client.post("/learners/x/reviews", json={"rating": 9},
                       headers=ok).status_code == 400
    assert client.post("/trace", json={"events": [], "learner_id": "x"},
                       headers=ok).status_code == 400


# ---------- HTTP：org 隔离（I7） ----------

def test_cross_org_profile_and_plan_isolation(client, bank, graph):
    correct = {"responses": [{"item_id": "g_half", "correct": True}]}
    wrong = {"responses": [{"item_id": "g_half", "correct": False}]}
    ha, hb = {"X-Org-Id": ORG_A}, {"X-Org-Id": ORG_B}

    assert client.post("/learners/dup/responses", json=correct, headers=ha).status_code == 200
    prof_a = client.get("/learners/dup/profile", headers=ha)
    assert prof_a.status_code == 200
    kernel = diagnose([Response(item_id="g_half", correct=True)],
                      bank, graph, learner_id="dup")
    assert prof_a.json()["mastery"] == kernel.mastery     # 内核等价（I11）

    assert client.get("/learners/dup/profile", headers=hb).status_code == 404
    assert client.get("/learners/dup/profile").status_code == 404  # 无头 = default 域
    assert client.get("/learners/dup/plan", headers=hb).status_code == 404

    # 同 learner_id 在 org-b 建立独立画像：不同作答 → 不同 mastery
    assert client.post("/learners/dup/responses", json=wrong, headers=hb).status_code == 200
    prof_b = client.get("/learners/dup/profile", headers=hb)
    assert prof_b.status_code == 200
    assert prof_b.json()["mastery"] != prof_a.json()["mastery"]
    assert prof_b.json()["evidence"] == prof_a.json()["evidence"]  # 各自 1 条证据

    # 事后互不漂移
    assert client.get("/learners/dup/profile", headers=ha).json()["mastery"] \
        == prof_a.json()["mastery"]

    # plan 按 org 分域：有画像的 org 200，其余 404
    plan_a = client.get("/learners/dup/plan", headers=ha)
    assert plan_a.status_code == 200 and len(plan_a.json()["steps"]) > 0
    assert client.get("/learners/dup/plan").status_code == 404


def test_trace_and_recommend_are_org_scoped(client, bank, graph):
    ha, hb = {"X-Org-Id": ORG_A}, {"X-Org-Id": ORG_B}
    kernel = trace(_kernel_events(bank, graph), bank, graph)

    out = _seed_trace(client, ORG_A)
    snaps = out["snapshots"]
    assert snaps[0]["mastery"]["a"] == 0.89899            # 闭式（见文件头）
    assert snaps[-1]["mastery"]["a"] == 0.090741
    assert snaps == [{"day": s.day, "item_id": s.item_id, "correct": s.correct,
                      "mastery": s.mastery, "evidence": s.evidence} for s in kernel]

    prof_a = client.get("/learners/kt/profile", headers=ha)
    assert prof_a.status_code == 200
    assert prof_a.json()["mastery"] == snaps[-1]["mastery"]
    assert prof_a.json()["evidence"] == {"a": 2, "b": 0, "c": 0, "d": 0}
    assert client.get("/learners/kt/profile", headers=hb).status_code == 404
    assert client.get("/learners/kt/profile").status_code == 404

    # recommend 学习者模式按 org 取画像
    rec_a = client.post("/recommend", json={"learner_id": "kt"}, headers=ha)
    assert rec_a.status_code == 200 and rec_a.json()["mode"] == "profile"
    assert client.post("/recommend", json={"learner_id": "kt"},
                       headers=hb).status_code == 404
    assert client.post("/recommend", json={"learner_id": "kt"}).status_code == 404

    # org-b 存自己的画像（不同事件：对@0 → 0.89899, evidence a=1），不串 org-a
    r = client.post("/trace", json={"learner_id": "kt",
                                    "events": [{"item_id": "g_half", "correct": True,
                                                "day": 0.0}]}, headers=hb)
    assert r.status_code == 200
    prof_b = client.get("/learners/kt/profile", headers=hb)
    assert prof_b.json()["mastery"]["a"] == 0.89899
    assert prof_b.json()["evidence"]["a"] == 1
    assert client.get("/learners/kt/profile", headers=ha).json()["mastery"] \
        == snaps[-1]["mastery"]                            # org-a 不漂移

    # /trace 确定性：同 (org, body) 重复请求逐字节相等
    t1 = client.post("/trace", json={"learner_id": "kt", "events": _trace_events()},
                     headers=ha)
    t2 = client.post("/trace", json={"learner_id": "kt", "events": _trace_events()},
                     headers=ha)
    assert t1.status_code == 200 and t1.content == t2.content


def test_http_org_case_sensitive_isolation(client):
    body = {"responses": [{"item_id": "g_half", "correct": True}]}
    assert client.post("/learners/cs/responses", json=body,
                       headers={"X-Org-Id": "ORG-A"}).status_code == 200
    assert client.get("/learners/cs/profile",
                      headers={"X-Org-Id": "ORG-A"}).status_code == 200
    assert client.get("/learners/cs/profile",
                      headers={"X-Org-Id": "org-a"}).status_code == 404


# ---------- HTTP：attempt 隔离（I8） ----------

def test_next_item_attempt_counts_isolated_per_org(client):
    ha, hb = {"X-Org-Id": ORG_A}, {"X-Org-Id": ORG_B}
    # 双 org 各自种同一画像（同事件 → 同 mastery）
    _seed_trace(client, ORG_A, "cat")
    _seed_trace(client, ORG_B, "cat")

    def nxt(org_headers):
        return client.get("/learners/cat/next_item",
                          params={"scope": "a", "per_kp_cap": 2},
                          headers=org_headers).json()

    a1 = nxt(ha)["item_id"]
    a2 = nxt(ha)["item_id"]
    assert a1 and a2 and a1 != a2
    assert nxt(ha) == {"item_id": None, "reason": "exhausted"}  # org-a 计满 cap=2

    # org-b 从满额开始：同画像 + 空计数 → 与 org-a 首选题逐位相同（选题确定性）
    assert nxt(hb)["item_id"] == a1
    assert nxt(hb)["item_id"] == a2
    assert nxt(hb) == {"item_id": None, "reason": "exhausted"}  # 独立耗尽

    # org-a 再查仍耗尽，不被 org-b 的消耗"复活"，也不互额外扣减
    assert nxt(ha) == {"item_id": None, "reason": "exhausted"}


# ---------- HTTP：/orgs 枚举（I9） ----------

def test_orgs_endpoint_sorted_readonly_byte_stable(client):
    assert client.get("/orgs").json() == {"orgs": []}          # 初始为空

    assert client.post("/learners/L1/responses",
                       json={"responses": [{"item_id": "g_half", "correct": True}]}
                       ).status_code == 200                     # default 域
    assert client.post("/learners/dup/responses",
                       json={"responses": [{"item_id": "g_half", "correct": True}]},
                       headers={"X-Org-Id": ORG_A}).status_code == 200
    assert client.post("/learners/dup/responses",
                       json={"responses": [{"item_id": "g_half", "correct": False}]},
                       headers={"X-Org-Id": ORG_B}).status_code == 200
    assert client.post("/learners/ghost/reviews", json={"rating": 2},
                       headers={"X-Org-Id": ORG_A}).status_code == 200  # 无画像也建档

    expected = {"orgs": [
        {"org_id": DEFAULT_ORG_ID, "learner_ids": ["L1"]},
        {"org_id": ORG_A, "learner_ids": ["dup", "ghost"]},
        {"org_id": ORG_B, "learner_ids": ["dup"]},
    ]}
    r1 = client.get("/orgs")
    assert r1.status_code == 200 and r1.json() == expected      # org/learner 恒升序
    assert client.get("/orgs").content == r1.content            # 只读 + 逐字节稳定


# ---------- HTTP：org 头全容忍（I10） ----------

def test_org_header_tolerates_arbitrary_values(client):
    weird = {"X-Org-Id": "a:b"}
    body = {"responses": [{"item_id": "g_half", "correct": True}]}
    assert client.post("/learners/w/responses", json=body, headers=weird).status_code == 200
    assert client.get("/learners/w/profile", headers=weird).status_code == 200
    assert client.get("/learners/w/profile").status_code == 404  # 自成命名空间
