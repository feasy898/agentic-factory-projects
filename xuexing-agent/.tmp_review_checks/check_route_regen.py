# -*- coding: utf-8 -*-
"""route 重生成实例的规格符合性复核（只针对规格冻结、契约测试未覆盖的行为）。"""
import importlib.util
import math
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from datetime import date

from xuexing import load_itembank, load_kpgraph, load_strategies
from xuexing.diagnosis import diagnose
from xuexing.kpgraph import KPGraph
from xuexing.types import KnowledgePoint, Response

spec = importlib.util.spec_from_file_location("_regen_route", os.path.join(ROOT, "regen", "round2", "route.py"))
route = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route)

TODAY = date(2026, 9, 28)
graph = load_kpgraph(os.path.join(ROOT, "data", "knowledge", "math_grade7.json"))
bank = load_itembank(os.path.join(ROOT, "data", "items", "math_grade7_items.json"))
strategies = load_strategies(os.path.join(ROOT, "data", "pedagogy", "strategies.json"))

fails = []


def check(name, cond):
    if not cond:
        fails.append(name)
    print(("PASS " if cond else "FAIL ") + name)


def profile_for(wrong_kp):
    rs = [Response(it.id, it.kps[0] != wrong_kp) for it in bank.items()]
    return diagnose(rs, bank, graph, learner_id="u")


# --- 例1：完整 steps 全序 / reviews（规格 §3.2 例 1）---
p1 = profile_for("kp_rational_add")
plan1 = route.build_plan(p1, bank, graph, strategies, TODAY)
expect_steps = [
    ("kp_rational_add", "s_worked_example"),
    ("kp_rational_mul", "s_worked_example"),
    ("kp_poly_ops", "s_worked_example"),
    ("kp_eq_concept", "s_retrieval"),
    ("kp_eq_solve", "s_retrieval"),
    ("kp_power", "s_retrieval"),
    ("kp_mixed_ops", "s_worked_example"),
]
check("ex1 steps sequence", [(s.kp_id, s.strategy_id) for s in plan1.steps] == expect_steps)
check("ex1 target_mastery == 0.65+0.2", all(s.target_mastery == 0.65 + 0.2 for s in plan1.steps))
check("ex1 len(reviews)==11", len(plan1.reviews) == 11)
check("ex1 reviews order", [r.kp_id for r in plan1.reviews] == [
    "kp_absvalue", "kp_algebraic", "kp_angles", "kp_eq_apply", "kp_geometry_basic",
    "kp_like_terms", "kp_lines_rays", "kp_monomial", "kp_numberline", "kp_opposite", "kp_posneg"])
check("ex1 review values", all(r.due == "2026-09-30" and r.interval_days == 2 and r.ease == 2.5 for r in plan1.reviews))
check("ex1 created_at/learner", plan1.created_at == "2026-09-28" and plan1.learner_id == "u")
check("ex1 rationale format", plan1.steps[0].rationale.startswith("mastery=0.00 < 0.65; "))
r1b = route.build_plan(p1, bank, graph, strategies, TODAY)
check("determinism whole-object", plan1 == r1b)

# --- 例2 ---
p2 = profile_for("kp_power")
plan2 = route.build_plan(p2, bank, graph, strategies, TODAY)
check("ex2 steps", [(s.kp_id, s.strategy_id) for s in plan2.steps] == [
    ("kp_power", "s_worked_example"), ("kp_mixed_ops", "s_worked_example")])
check("ex2 reviews 16", len(plan2.reviews) == 16 and all(r.kp_id != "kp_power" for r in plan2.reviews))

# --- 参数校验（§6）---
def expect_route_error(name, msg, *args, **kw):
    try:
        route.build_plan(*args, **kw)
        check(name + " [raised]", False)
    except route.RouteError as e:
        check(name, str(e) == msg)
    except Exception as e:
        check(name + " [type]", False)
        print("  got", type(e).__name__, e)

expect_route_error("t=1.5", "mastery_threshold out of (0,1)", p2, bank, graph, strategies, TODAY, mastery_threshold=1.5)
expect_route_error("t=0.0", "mastery_threshold out of (0,1)", p2, bank, graph, strategies, TODAY, mastery_threshold=0.0)
expect_route_error("t=1.0", "mastery_threshold out of (0,1)", p2, bank, graph, strategies, TODAY, mastery_threshold=1.0)
expect_route_error("t=-0.1", "mastery_threshold out of (0,1)", p2, bank, graph, strategies, TODAY, mastery_threshold=-0.1)
expect_route_error("t=NaN", "mastery_threshold out of (0,1)", p2, bank, graph, strategies, TODAY, mastery_threshold=float("nan"))
expect_route_error("session_size=0", "session_size must be >=1", p2, bank, graph, strategies, TODAY, session_size=0)
expect_route_error("session_size=-3", "session_size must be >=1", p2, bank, graph, strategies, TODAY, session_size=-3)
expect_route_error("both invalid -> threshold first", "mastery_threshold out of (0,1)", p2, bank, graph, strategies, TODAY, mastery_threshold=1.5, session_size=0)

try:
    route.build_plan(p2, bank, graph, strategies, TODAY, mastery_threshold="x")
    check("t=str -> TypeError", False)
except route.RouteError:
    check("t=str -> TypeError (wrapped!)", False)
except TypeError:
    check("t=str -> TypeError passthrough", True)

# --- 死锁：弱点声明成环、无先序边（I3/I5）---
g2 = KPGraph()
g2.add_kp(KnowledgePoint(id="a", name="a", subject="math", grade=7, cluster="c", prereqs=["b"]))
g2.add_kp(KnowledgePoint(id="b", name="b", subject="math", grade=7, cluster="c", prereqs=["a"]))
expect_route_error("weak cycle deadlock", "no pickable weak kp: prerequisite deadlock",
                   type("P", (), {"learner_id": "x", "mastery": {"a": 0.1, "b": 0.2}, "evidence": {}})(),
                   bank, g2, strategies, TODAY)

# --- 声明 prereq 无边仍阻塞；非弱 prereq 不阻塞（I3 复核）---
g3 = KPGraph()
g3.add_kp(KnowledgePoint(id="p", name="p", subject="math", grade=7, cluster="c"))
g3.add_kp(KnowledgePoint(id="q", name="q", subject="math", grade=7, cluster="c", prereqs=["p"]))
p3 = type("P", (), {"learner_id": "x", "mastery": {"p": 0.1, "q": 0.2}, "evidence": {}})()
# p、q 均弱且 p 声明为 q 的 prereq（无边）：q 被阻塞直到 p 排入，无环不死锁 → 输出 [p, q]
check("declared-no-edge order [p,q]",
      [s.kp_id for s in route.build_plan(p3, bank, g3, strategies, TODAY).steps] == ["p", "q"])

p3b = type("P", (), {"learner_id": "x", "mastery": {"p": 0.9, "q": 0.2}, "evidence": {}})()
check("non-weak prereq does not block",
      [s.kp_id for s in route.build_plan(p3b, bank, g3, strategies, TODAY).steps] == ["q"])

# --- 策略包装（I7 隐式链）/ RouteError 原样重抛 ---
class BoomLib:
    def select(self, m, grade):
        raise RuntimeError("boom")

class RouteBoomLib:
    def select(self, m, grade):
        raise route.RouteError("native")

try:
    route.build_plan(p3b, bank, g3, BoomLib(), TODAY)
    check("wrap select failure", False)
except route.RouteError as e:
    check("wrap select failure msg", str(e) == "strategy selection failed for q")
    check("implicit chain __cause__ None", e.__cause__ is None)
    check("implicit chain __context__", type(e.__context__) is RuntimeError)

try:
    route.build_plan(p3b, bank, g3, RouteBoomLib(), TODAY)
    check("RouteError re-raised", False)
except route.RouteError as e:
    check("RouteError re-raised as-is", str(e) == "native" and e.__context__ is None)

# --- I8 无截断：t=0.9 -> 1.1 ---
plan4 = route.build_plan(p3b, bank, g3, strategies, TODAY, mastery_threshold=0.9)
check("t=0.9 -> target 1.1 no clamp", all(s.target_mastery == max(0.85, 0.9 + 0.2) for s in plan4.steps))
check("t=0.9 -> reviews >= 0.9", [r.kp_id for r in plan4.reviews] == ["p"])

# --- 图外键过滤；图节点缺 mastery 键按 0.0（复习侧）---
g4 = KPGraph()
g4.add_kp(KnowledgePoint(id="a", name="a", subject="math", grade=7, cluster="c"))
g4.add_kp(KnowledgePoint(id="b", name="b", subject="math", grade=7, cluster="c"))
p4 = type("P", (), {"learner_id": "x", "mastery": {"a": 0.9, "zzz": 0.1}, "evidence": {}})()
plan5 = route.build_plan(p4, bank, g4, strategies, TODAY)
check("out-of-graph filtered", [s.kp_id for s in plan5.steps] == [] and [r.kp_id for r in plan5.reviews] == ["a"])
p5 = type("P", (), {"learner_id": "x", "mastery": {"a": 0.9}, "evidence": {}})()
plan6 = route.build_plan(p5, bank, g4, strategies, TODAY)
check("missing key -> 0.0 review side", [s.kp_id for s in plan6.steps] == [] and [r.kp_id for r in plan6.reviews] == ["a"])

# --- 全对画像：steps==[]、reviews==18（§3.1 输入容错）---
p_all = diagnose([Response(it.id, True) for it in bank.items()], bank, graph, learner_id="u")
plan7 = route.build_plan(p_all, bank, graph, strategies, TODAY)
check("all-pass steps empty", plan7.steps == [] and len(plan7.reviews) == 18)

# --- I11：上游 kps() 失序时输出仍升序 ---
class ReversedGraph:
    def __init__(self, g):
        self._g = g
    def has(self, k):
        return self._g.has(k)
    def prereqs(self, k):
        return self._g.prereqs(k)
    def descendants(self, k):
        return self._g.descendants(k)
    def get(self, k):
        return self._g.get(k)
    def kps(self):
        return list(reversed(self._g.kps()))

p8 = profile_for("kp_power")
plan8 = route.build_plan(p8, bank, ReversedGraph(graph), strategies, TODAY)
ids = [r.kp_id for r in plan8.reviews]
check("reviews ascending despite kps() order", ids == sorted(ids))
check("steps unaffected by kps() order", [(s.kp_id, s.strategy_id) for s in plan8.steps] == [
    ("kp_power", "s_worked_example"), ("kp_mixed_ops", "s_worked_example")])

# --- 恰等于阈值：不弱、且进复习 ---
p9 = type("P", (), {"learner_id": "x", "mastery": {"a": 0.65, "b": 0.6499999}, "evidence": {}})()
plan9 = route.build_plan(p9, bank, g4, strategies, TODAY)
check("m==threshold boundary", [s.kp_id for s in plan9.steps] == ["b"] and [r.kp_id for r in plan9.reviews] == ["a"])

# --- 不修改入参（I14）---
import copy
p10 = profile_for("kp_power")
snap = copy.deepcopy(p10.mastery)
route.build_plan(p10, bank, graph, strategies, TODAY)
check("profile not mutated", p10.mastery == snap)

print()
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
