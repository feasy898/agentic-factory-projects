# -*- coding: utf-8 -*-
"""Throwaway runtime verification of frozen spec clauses not covered by contract tests."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "regen", "round2"))

import pedagogy as P
from xuexing.types import Strategy

ok = []
def check(name, cond):
    ok.append((name, bool(cond)))

# 1. StrategyError is ValueError subclass
check("issubclass(StrategyError, ValueError)", issubclass(P.StrategyError, ValueError))

# 2. duplicate add: raises, library unchanged
lib = P.StrategyLibrary()
a = Strategy(id="x", name="X", description="", priority=5)
b = Strategy(id="x", name="X2", description="", priority=9)
lib.add(a)
try:
    lib.add(b)
    check("dup add raises", False)
except P.StrategyError:
    check("dup add raises", True)
check("dup add leaves library unchanged", len(lib.strategies()) == 1 and lib.strategies()[0] is a)

# 3. get identity
check("get hit same object", lib.get("x") is a)
check("get miss None", lib.get("nope") is None)

# 4. select returns registered object itself
lib2 = P.StrategyLibrary()
s = Strategy(id="all", name="A", description="", priority=1)
lib2.add(s)
check("select returns registered object (is)", lib2.select(0.5, 7) is s)

# 5. tie-break ordering (-priority, id)
lib3 = P.StrategyLibrary()
for sid in ("b", "a", "c"):
    lib3.add(Strategy(id=sid, name=sid, description="", priority=3))
check("same-priority tie-break by id asc", [x.id for x in lib3.strategies()] == ["a", "b", "c"])

# 6. equality boundaries (I2): strict < for mastery_lt; >= / <= / >= inclusive
lb = P.StrategyLibrary()
lb.add(Strategy(id="lt", name="", description="", priority=10, mastery_lt=0.5))
lb.add(Strategy(id="fallback", name="", description="", priority=1))
check("mastery == mastery_lt does NOT match lt", lb.select(0.5, 4).id == "fallback")
check("mastery < mastery_lt matches", lb.select(0.4999, 4).id == "lt")
lg = P.StrategyLibrary()
lg.add(Strategy(id="gte", name="", description="", priority=10, mastery_gte=0.65))
check("mastery == mastery_gte matches", lg.select(0.65, 4).id == "gte")
lg2 = P.StrategyLibrary()
lg2.add(Strategy(id="gmax", name="", description="", priority=10, grade_max=6))
check("grade == grade_max matches", lg2.select(0.5, 6).id == "gmax")
lg3 = P.StrategyLibrary()
lg3.add(Strategy(id="gmin", name="", description="", priority=10, grade_min=7))
check("grade == grade_min matches", lg3.select(0.5, 7).id == "gmin")

# 7. no domain validation / no clamp
lib_oos = P.StrategyLibrary()
lib_oos.add(Strategy(id="hi", name="", description="", priority=1, mastery_gte=2.0))
check("mastery beyond 1 can match", lib_oos.select(3.0, 4).id == "hi")

# 8. empty library select -> StrategyError
try:
    P.StrategyLibrary().select(0.5, 7)
    check("empty select raises", False)
except P.StrategyError:
    check("empty select raises", True)

# 9. strategies() returns new list each call; mutation safe; insertion order irrelevant
l1 = lib3.strategies(); l1.append("junk")
check("strategies() fresh list", len(lib3.strategies()) == 3)
li = P.StrategyLibrary()
for sid, pr in (("z", 1), ("y", 9), ("x", 1)):
    li.add(Strategy(id=sid, name="", description="", priority=pr))
check("order independent of insertion", [x.id for x in li.strategies()] == ["y", "x", "z"])

# 10. load_strategies on the legal sample fixture
full = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "pedagogy", "strategies.json")
loaded = P.load_strategies(full)
check("sample fixture ids order", [x.id for x in loaded.strategies()] ==
      ["s_gamified", "s_worked_example", "s_retrieval", "s_interleave", "s_guided_practice"])

# 11. load_strategies error table
def expect(name, exc, fn):
    try:
        fn()
        check(name, False)
    except exc:
        check(name, True)
    except Exception as e:
        check(name + f" (got {type(e).__name__}: {e})", False)

td = tempfile.mkdtemp()
def wf(obj, raw=None, name="t.json"):
    p = os.path.join(td, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(raw if raw is not None else json.dumps(obj))
    return p

expect("missing file -> FileNotFoundError", FileNotFoundError, lambda: P.load_strategies(os.path.join(td, "nope.json")))
expect("invalid JSON -> JSONDecodeError", json.JSONDecodeError, lambda: P.load_strategies(wf(None, raw="{not json")))
expect("top-level list -> TypeError", TypeError, lambda: P.load_strategies(wf([1, 2, 3])))
expect("strategies=5 -> TypeError", TypeError, lambda: P.load_strategies(wf({"strategies": 5})))
expect("strategies='abc' -> TypeError", TypeError, lambda: P.load_strategies(wf({"strategies": "abc"})))
expect("entry 'a' -> TypeError", TypeError, lambda: P.load_strategies(wf({"strategies": ["a"]})))
expect("entry [1,2] -> TypeError", TypeError, lambda: P.load_strategies(wf({"strategies": [[1, 2]]})))
expect("entry null -> TypeError", TypeError, lambda: P.load_strategies(wf({"strategies": [None]})))
expect("missing 'strategies' key -> KeyError", KeyError, lambda: P.load_strategies(wf({"other": []})))
expect("entry missing name -> KeyError", KeyError, lambda: P.load_strategies(wf({"strategies": [{"id": "x"}]})))
expect("entry missing id -> KeyError", KeyError, lambda: P.load_strategies(wf({"strategies": [{"name": "n"}]})))
expect("priority 'abc' -> ValueError from int()", ValueError,
       lambda: P.load_strategies(wf({"strategies": [{"id": "x", "name": "n", "priority": "abc"}]})))

# unknown keys ignored
p_uk = wf({"strategies": [{"id": "x", "name": "n", "bogus": 123}]})
l_uk = P.load_strategies(p_uk)
check("unknown key ignored", len(l_uk.strategies()) == 1 and l_uk.strategies()[0].id == "x")

# in-file duplicate id -> StrategyError
expect("in-file dup id -> StrategyError", P.StrategyError,
       lambda: P.load_strategies(wf({"strategies": [{"id": "x", "name": "n"}, {"id": "x", "name": "m"}]})))

# 12. spec examples from §3.4
mk = lambda: None
def ex1():
    L = P.StrategyLibrary()
    L.add(Strategy(id="low", name="", description="", priority=10, mastery_lt=0.4))
    L.add(Strategy(id="mid", name="", description="", priority=8, mastery_gte=0.4, mastery_lt=0.65))
    L.add(Strategy(id="high", name="", description="", priority=6, mastery_gte=0.65))
    L.add(Strategy(id="young", name="", description="", priority=12, mastery_lt=0.5, grade_max=6))
    L.add(Strategy(id="fallback", name="", description="", priority=1))
    return L
L1 = ex1()
check("ex1 select(0.2,4)=young", L1.select(0.2, 4).id == "young")
check("ex1 select(0.8,4)=high", L1.select(0.8, 4).id == "high")
check("ex1 select(0.2,9)=low", L1.select(0.2, 9).id == "low")
ids = [s.id for s in L1.strategies()]
check("ex1 full order", ids == ["young", "low", "mid", "high", "fallback"])
L2 = P.StrategyLibrary()
L2.add(Strategy(id="low", name="", description="", priority=10, mastery_lt=0.4))
L2.add(Strategy(id="high", name="", description="", priority=6, mastery_gte=0.65))
L2.add(Strategy(id="fallback", name="", description="", priority=1))
check("ex2 select(0.5,7)=fallback", L2.select(0.5, 7).id == "fallback")

# 13. allowed imports only (stdlib + xuexing.types)
import ast
src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "regen", "round2", "pedagogy.py")
with open(src_path, encoding="utf-8") as f:
    tree = ast.parse(f.read())
imports = []
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        imports += [a.name for a in node.names]
    elif isinstance(node, ast.ImportFrom):
        imports.append(node.module or "")
check("imports = json/__future__/xuexing.types", sorted(set(imports)) == ["__future__", "json", "xuexing.types"])

# 14. select first-hit scan stops (I1): lower-priority also-matching strategy not chosen
L4 = P.StrategyLibrary()
L4.add(Strategy(id="second", name="", description="", priority=5, mastery_lt=0.9))
L4.add(Strategy(id="first", name="", description="", priority=9, mastery_lt=0.9))
check("first hit wins", L4.select(0.1, 4).id == "first")

failed = [n for n, c in ok if not c]
print(f"TOTAL={len(ok)} PASSED={len(ok) - len(failed)} FAILED={len(failed)}")
for n in failed:
    print("FAIL:", n)
sys.exit(1 if failed else 0)
