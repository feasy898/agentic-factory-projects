# -*- coding: utf-8 -*-
"""按 spec §3.2.5 例1-7 与各【探针】值逐位核对 regen/round2/diagnosis.py（临时自检脚本）。"""
import importlib.util
import sys

sys.path.insert(0, "src")

from xuexing.itembank import ItemBank
from xuexing.kpgraph import KPGraph
from xuexing.types import Item, KnowledgePoint, Response

spec = importlib.util.spec_from_file_location("_regen_d", "regen/round2/diagnosis.py")
dx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dx)

fails = []


def check(name, got, want):
    if got != want:
        fails.append(f"{name}: got {got!r}, want {want!r}")


# small_bank / small_graph 按 tests/contract/conftest.py:37-68 自建
g = KPGraph()
g.add_kp(KnowledgePoint(id="a", name="甲", subject="math", grade=7, cluster="c1"))
g.add_kp(KnowledgePoint(id="b", name="乙", subject="math", grade=7, cluster="c1", prereqs=["a"]))
g.add_kp(KnowledgePoint(id="c", name="丙", subject="math", grade=7, cluster="c2", prereqs=["b"]))
g.add_kp(KnowledgePoint(id="d", name="丁", subject="math", grade=7, cluster="c2"))
for kp in g.kps():
    for p in kp.prereqs:
        g.add_edge(p, kp.id)

b = ItemBank()


def add(item_id, kp, difficulty, item_type="fill", options=None, answer="ans", guess=None, kps=None):
    b.add(Item(id=item_id, item_type=item_type, stem=f"stem-{item_id}", answer=answer,
               kps=kps or [kp], difficulty=difficulty, options=options or [], guess=guess))


add("a1", "a", 0.2)
add("a2", "a", 0.5)
add("a3", "a", 0.8)
add("b1", "b", 0.3)
add("b2", "b", 0.6)
add("c1", "c", 0.4)
add("d1", "d", 0.5, item_type="choice", options=["A. 1", "B. 2"], answer="B", guess=0.25)
add("d2", "d", 0.5)

# slip 探针（§3.1）
check("slip0.0", dx.slip_from_difficulty(0.0), 0.05)
check("slip0.1", dx.slip_from_difficulty(0.1), 0.07)
check("slip0.5", dx.slip_from_difficulty(0.5), 0.15000000000000002)
check("slip0.9", dx.slip_from_difficulty(0.9), 0.23000000000000004)
check("slip1.0", dx.slip_from_difficulty(1.0), 0.25)

# 例1 + 证据/置信度
p = dx.diagnose([Response("a1", True), Response("a2", False)], b, g)
check("ex1.mastery", p.mastery, {"a": 0.602649, "b": 0.5, "c": 0.5, "d": 0.5})
check("ex1.evidence", p.evidence, {"a": 2, "b": 0, "c": 0, "d": 0})
check("ex1.keys", list(p.mastery), ["a", "b", "c", "d"])

# 例2（C-a…C-e：先序补证 + 复利折价）
p = dx.diagnose([Response("b1", True), Response("b2", True)], b, g)
check("ex2.mastery", p.mastery, {"a": 0.591986, "b": 0.986644, "c": 0.5, "d": 0.5})
p2 = dx.diagnose([Response("a1", False), Response("a2", False), Response("b1", True), Response("b2", True)], b, g)
check("ex2.I8c.a", p2.mastery["a"], 0.016393)
check("ex2.I8c.b", p2.mastery["b"], 0.165722)  # C-e 复利两轮

# 例3 未知题忽略
p = dx.diagnose([Response("ghost", True)], b, g)
check("ex3.mastery", p.mastery, {"a": 0.5, "b": 0.5, "c": 0.5, "d": 0.5})
check("ex3.evidence", p.evidence, {"a": 0, "b": 0, "c": 0, "d": 0})

# 例4 方向性/单调/猜度感知
check("ex4.up", dx.diagnose([Response("a1", True), Response("a2", True), Response("a3", True)], b, g).mastery["a"], 0.998366)
check("ex4.down", dx.diagnose([Response("a1", False), Response("a2", False), Response("a3", False)], b, g).mastery["a"], 0.003874)
check("ex4.one", dx.diagnose([Response("a1", True)], b, g).mastery["a"], 0.90099)
check("ex4.d1", dx.diagnose([Response("d1", True)], b, g).mastery["d"], 0.772727)
check("ex4.d2", dx.diagnose([Response("d2", True)], b, g).mastery["d"], 0.894737)

# 例5 prior 非法
for bad in (0.0, -0.1, 1.0, 1.5):
    try:
        dx.diagnose([], b, g, prior=bad)
        fails.append(f"ex5.prior={bad}: no ValueError")
    except ValueError as e:
        check(f"ex5.msg{bad}", str(e), "prior must be in (0,1)")

# 例6 平滑直接性 C-f
p = dx.diagnose([Response("c1", True)], b, g)
check("ex6.mastery", p.mastery, {"a": 0.5, "b": 0.538144, "c": 0.896907, "d": 0.5})

# B2 护栏分支：guess=0.8, d=0.9 的 fill 题
g2 = KPGraph()
g2.add_kp(KnowledgePoint(id="a", name="a", subject="math", grade=7, cluster="k"))
b2 = ItemBank()
b2.add(Item(id="f", item_type="fill", stem="s", answer="x", kps=["a"], difficulty=0.9, guess=0.8))
check("guard.correct", dx.diagnose([Response("f", True)], b2, g2).mastery["a"], 0.506173)
check("guard.wrong", dx.diagnose([Response("f", False)], b2, g2).mastery["a"], 0.473684)

# D1 空作答先验一次性舍入
p = dx.diagnose([], b, g, prior=0.123456789)
check("D1.empty", p.mastery, {"a": 0.123457, "b": 0.123457, "c": 0.123457, "d": 0.123457})
check("D1.evidence", p.evidence, {"a": 0, "b": 0, "c": 0, "d": 0})

# B3 重复 kps：kps=["a","a"] 答对一次 → evidence 2, mastery 0.961213
g3 = KPGraph()
g3.add_kp(KnowledgePoint(id="a", name="a", subject="math", grade=7, cluster="k"))
b3 = ItemBank()
b3.add(Item(id="dup", item_type="fill", stem="s", answer="x", kps=["a", "a"], difficulty=0.5))
p = dx.diagnose([Response("dup", True)], b3, g3)
check("dup.evidence", p.evidence["a"], 2)
check("dup.mastery", p.mastery["a"], 0.961213)

# 例7 多前序/多后代合成（C-c/C-d）
g4 = KPGraph()
ids = {"x": [], "y": [], "z": ["x", "y"], "w": [], "u": ["w"], "v": ["w"]}
for kid, pr in ids.items():
    g4.add_kp(KnowledgePoint(id=kid, name=kid, subject="math", grade=7, cluster="k", prereqs=pr))
for kp in g4.kps():
    for pr in kp.prereqs:
        g4.add_edge(pr, kp.id)
b4 = ItemBank()
for iid, d in [("x1", 0.9), ("x2", 0.8), ("y1", 0.1), ("y2", 0.1), ("z1", 0.5), ("u1", 0.1), ("u2", 0.2), ("v1", 0.7)]:
    b4.add(Item(id=iid, item_type="fill", stem="s", answer="x", kps=[iid[0]], difficulty=d))
p = dx.diagnose([Response("x1", False), Response("x2", False), Response("y1", True), Response("y2", True),
                 Response("z1", True), Response("u1", True), Response("u2", True), Response("v1", True)], b4, g4)
check("ex7.mastery", p.mastery,
      {"u": 0.988322, "v": 0.89011, "w": 0.592993, "x": 0.056274, "y": 0.988570, "z": 0.168346})
check("ex7.keys", list(p.mastery), ["u", "v", "w", "x", "y", "z"])  # kps() 按 id 升序（spec §2）

# 渐近界：最易题（fill, d=0.1）连对/连错 30 次；闭式：odds 下限域不动点
#   连对：odds≈lr_c/1e-4=9.3e4 → 93000/93001=0.999989；连错：1e-4×lr_w=7.78e-6 → 8e-06
g5 = KPGraph()
g5.add_kp(KnowledgePoint(id="a", name="a", subject="math", grade=7, cluster="k"))
b5 = ItemBank()
b5.add(Item(id="e", item_type="fill", stem="s", answer="x", kps=["a"], difficulty=0.1))
m_up = dx.diagnose([Response("e", True)] * 30, b5, g5).mastery["a"]
m_dn = dx.diagnose([Response("e", False)] * 30, b5, g5).mastery["a"]
check("asym.up", m_up, 0.999989)
check("asym.down", m_dn, 8e-06)

# §3.3 聚合：逐值 + 键序 + 缺失按 0.0
p = dx.diagnose([Response("a1", True)], b, g)
cl = dx.aggregate_to_clusters(p, g)
check("agg.value", cl, {"c1": 0.700495, "c2": 0.5})
check("agg.keyorder", list(cl), ["c1", "c2"])

g6 = KPGraph()
g6.add_kp(KnowledgePoint(id="zz1", name="z", subject="math", grade=7, cluster="zz"))
g6.add_kp(KnowledgePoint(id="aa1", name="a", subject="math", grade=7, cluster="aa"))
cl = dx.aggregate_to_clusters(p, g6)  # p.mastery 无 zz1/aa1 → 全按 0.0
check("agg.order.zz-aa", list(cl), ["aa", "zz"])

from xuexing.types import Profile
prof = Profile(learner_id="x", mastery={"a": 0.9}, evidence={"a": 1})
cl = dx.aggregate_to_clusters(prof, g)  # a/b 同属 c1，b 缺失按 0.0 → 0.45
check("agg.missing", cl.get("c1"), 0.45)

if fails:
    print("FAIL", len(fails))
    for f in fails:
        print(" -", f)
    sys.exit(1)
print("ALL PROBES MATCH")
