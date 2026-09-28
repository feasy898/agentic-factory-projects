"""临时自检脚本：核对 specs/frozen/route.spec.md 中契约测试未覆盖、但按参考冻结的行为。"""
import importlib.util
import os
import sys
from datetime import date

ROOT = r"D:\workspace\学情agent"
sys.path.insert(0, os.path.join(ROOT, "src"))
import xuexing  # noqa: F401

_spec = importlib.util.spec_from_file_location(
    "_regen_route", os.path.join(ROOT, "regen", "round3", "route.py")
)
route = importlib.util.module_from_spec(_spec)
sys.modules["xuexing.route"] = route
_spec.loader.exec_module(route)

from xuexing.kpgraph import KPGraph
from xuexing.types import KnowledgePoint, Profile

RouteError = route.RouteError
TODAY = date(2026, 9, 28)

assert issubclass(RouteError, ValueError), "3.0"

g = KPGraph()
g.add_kp(KnowledgePoint(id="a", name="甲", subject="math", grade=7, cluster="c1"))
g.add_kp(KnowledgePoint(id="b", name="乙", subject="math", grade=7, cluster="c1", prereqs=["a"]))
g.add_kp(KnowledgePoint(id="c", name="丙", subject="math", grade=7, cluster="c2", prereqs=["b"]))
g.add_kp(KnowledgePoint(id="d", name="丁", subject="math", grade=7, cluster="c2"))
for kp in g.kps():
    for p in kp.prereqs:
        g.add_edge(p, kp.id)


class FakeBank:
    pass


class FakeStrats:
    def __init__(self, behavior="ok"):
        self.behavior = behavior

    def select(self, mastery, grade):
        if self.behavior == "boom":
            raise ValueError("boom")
        if self.behavior == "route_err":
            raise RouteError("direct-route-error")
        s = type("S", (), {})()
        s.id, s.evidence = "strat", "EV"
        return s

    def get(self, sid):
        return type("S", (), {"id": sid})()


def plan_of(mastery, strats=None, graph=None, **kw):
    prof = Profile(learner_id="u", mastery=dict(mastery), evidence={}, updated_at="")
    return route.build_plan(prof, FakeBank(), graph or g, strats or FakeStrats(), TODAY, **kw)


fails = []


def check(name, fn):
    try:
        fn()
        print(f"PASS {name}")
    except AssertionError as e:
        fails.append(name)
        print(f"FAIL {name}: {e}")
    except Exception as e:  # noqa: BLE001
        fails.append(name)
        print(f"FAIL {name}: {type(e).__name__}: {e}")


def t_param():
    for bad in (0.0, 1.0, -0.1, float("nan"), 1.5):
        try:
            plan_of({"a": 0.5}, mastery_threshold=bad)
            raise AssertionError(f"threshold={bad} no raise")
        except RouteError as e:
            assert "mastery_threshold out of (0,1)" in str(e)
    for bad in (0, -3):
        try:
            plan_of({"a": 0.5}, session_size=bad)
            raise AssertionError(f"session_size={bad} no raise")
        except RouteError as e:
            assert "session_size must be >=1" in str(e)
    try:
        plan_of({"a": 0.5}, mastery_threshold=1.5, session_size=0)
        raise AssertionError("both invalid no raise")
    except RouteError as e:
        assert "mastery_threshold" in str(e), "threshold must be reported first"
    try:
        plan_of({"a": 0.5}, mastery_threshold="x")
        raise AssertionError("str threshold no raise")
    except RouteError:
        raise AssertionError("TypeError was wrapped into RouteError")
    except TypeError:
        pass


def t_order():
    p = plan_of({"a": 0.1, "b": 0.2, "c": 0.3, "d": 0.1})
    # round1 {a,d}: 2*0.55 vs 0 -> a; round2 {b,d}: 0.45 vs 0 -> b; round3 {c,d}: 0=0 tie -> c; d
    assert [s.kp_id for s in p.steps] == ["a", "b", "c", "d"], [s.kp_id for s in p.steps]


def t_deadlock():
    g2 = KPGraph()
    g2.add_kp(KnowledgePoint(id="p", name="P", subject="math", grade=7, cluster="c", prereqs=["q"]))
    g2.add_kp(KnowledgePoint(id="q", name="Q", subject="math", grade=7, cluster="c", prereqs=["p"]))
    # 声明 prereq 但未加边 —— 阻塞只看声明（I3）
    try:
        plan_of({"p": 0.1, "q": 0.2}, graph=g2)
        raise AssertionError("cycle not rejected")
    except RouteError as e:
        assert str(e) == "no pickable weak kp: prerequisite deadlock", str(e)


def t_chain():
    try:
        plan_of({"a": 0.1}, FakeStrats("boom"))
        raise AssertionError("no wrap")
    except RouteError as e:
        assert e.__cause__ is None, "__cause__ must stay None (bare raise)"
        assert type(e.__context__) is ValueError, type(e.__context__)
        assert str(e) == "strategy selection failed for a", str(e)
    try:
        plan_of({"a": 0.1}, FakeStrats("route_err"))
        raise AssertionError("RouteError not re-raised")
    except RouteError as e:
        assert str(e) == "direct-route-error", f"re-wrapped: {e}"


def t_out_of_graph():
    p = plan_of({"a": 0.1, "zz": 0.0})
    assert [s.kp_id for s in p.steps] == ["a"], [s.kp_id for s in p.steps]
    assert all(r.kp_id in {"a", "b", "c", "d"} for r in p.reviews)


def t_missing_key():
    # mastery 只含 a=0.9：b/c/d 缺键按 0.0 -> 不复习；弱点集只遍历 mastery 键 -> 无步骤
    p = plan_of({"a": 0.9})
    assert p.steps == []
    assert [r.kp_id for r in p.reviews] == ["a"], [r.kp_id for r in p.reviews]


def t_all_mastered():
    p = plan_of({k: 0.9 for k in "abcd"})
    assert p.steps == []
    assert [r.kp_id for r in p.reviews] == ["a", "b", "c", "d"]
    for r in p.reviews:
        assert r.due == "2026-09-30" and r.interval_days == 2 and r.ease == 2.5
    assert p.created_at == "2026-09-28" and p.learner_id == "u"


class ReversedKpsGraph:
    """kps() 故意失序的上游桩：I11 要求 route 输出仍按 kp_id 升序。"""

    def __init__(self, inner):
        self._inner = inner

    def has(self, k):
        return self._inner.has(k)

    def prereqs(self, k):
        return self._inner.prereqs(k)

    def descendants(self, k):
        return self._inner.descendants(k)

    def get(self, k):
        return self._inner.get(k)

    def kps(self):
        return list(reversed(self._inner.kps()))


def t_review_order():
    p = plan_of({k: 0.9 for k in "abcd"}, graph=ReversedKpsGraph(g))
    assert [r.kp_id for r in p.reviews] == ["a", "b", "c", "d"], [r.kp_id for r in p.reviews]


def t_target_no_cap():
    p = plan_of({"a": 0.1, "b": 0.9}, mastery_threshold=0.9)
    assert all(s.target_mastery == 1.1 for s in p.steps), [s.target_mastery for s in p.steps]
    assert [r.kp_id for r in p.reviews] == ["b"], "only mastered reviewed at t=0.9"


def t_rationale_and_fields():
    p = plan_of({"a": 0.1234})
    s = p.steps[0]
    assert s.rationale == "mastery=0.12 < 0.65; EV", s.rationale
    assert abs(s.target_mastery - 0.8500000000000001) < 1e-18, repr(s.target_mastery)
    assert s.strategy_id == "strat"


def t_pure_and_deterministic():
    mastery = {"a": 0.1, "b": 0.2, "c": 0.3, "d": 0.4}
    prof = Profile(learner_id="u", mastery=dict(mastery), evidence={}, updated_at="")
    snap = dict(prof.mastery)
    p1 = route.build_plan(prof, FakeBank(), g, FakeStrats(), TODAY)
    p2 = route.build_plan(prof, FakeBank(), g, FakeStrats(), TODAY)
    assert prof.mastery == snap, "profile mutated"
    assert [s.kp_id for s in p1.steps] == [s.kp_id for s in p2.steps]
    assert [(r.kp_id, r.due) for r in p1.reviews] == [(r.kp_id, r.due) for r in p2.reviews]


check("param_validation", t_param)
check("greedy_order", t_order)
check("declared_cycle_deadlock", t_deadlock)
check("wrap_implicit_chain", t_chain)
check("out_of_graph_filtered", t_out_of_graph)
check("missing_mastery_key", t_missing_key)
check("empty_weak_all_mastered", t_all_mastered)
check("review_sorted_upstream_shuffled", t_review_order)
check("target_mastery_no_cap", t_target_no_cap)
check("rationale_and_fields", t_rationale_and_fields)
check("purity_determinism", t_pure_and_deterministic)

print("RESULT:", "ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
