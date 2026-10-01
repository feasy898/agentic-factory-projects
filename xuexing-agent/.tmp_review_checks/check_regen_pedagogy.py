# 临时自检脚本：对照规格中"参考实现已运行验证"的行为逐条核查重生成实例。
# 只 import 重生成文件与 xuexing.types，不读参考实现源码。
import json
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "regen", "round1"))

import importlib.util

import xuexing  # noqa: F401  先完整加载参考包（与 tests/contract/conftest.py:12 一致），再做顶替

spec = importlib.util.spec_from_file_location("_regen_pedagogy_chk", os.path.join(ROOT, "regen", "round1", "pedagogy.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["xuexing.pedagogy"] = mod
spec.loader.exec_module(mod)

from xuexing.types import Strategy

StrategyError = mod.StrategyError
StrategyLibrary = mod.StrategyLibrary
load_strategies = mod.load_strategies

fails = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


def raises(fn, exc):
    try:
        fn()
        return False
    except exc:
        return True
    except Exception as e:  # noqa: BLE001
        print("   unexpected:", type(e).__name__, e)
        return False


# 3.1 异常子类
check("StrategyError is ValueError subclass", issubclass(StrategyError, ValueError) is True)

# 3.2 add/get/strategies/select
s = Strategy(id="x", name="X", description="", priority=5)
lib = StrategyLibrary()
lib.add(s)
check("get hits same object", lib.get("x") is s)
check("get miss returns None", lib.get("nope") is None)
try:
    lib.add(Strategy(id="x", name="Y", description=""))
    check("duplicate add raises", False)
except StrategyError:
    check("duplicate add raises", True)
check("duplicate add leaves library unchanged", [t.id for t in lib.strategies()] == ["x"])
check("select returns registered object", lib.select(0.5, 7) is s)

# I2 等值边界（单策略库，排除优先级干扰）
def solo(**kw):
    lb = StrategyLibrary()
    lb.add(Strategy(id="s", name="", description="", **kw))
    return lb


check("mastery == mastery_lt does NOT match (strict <)", raises(lambda: solo(mastery_lt=0.4).select(0.4, 0), StrategyError))
check("mastery just below mastery_lt matches", solo(mastery_lt=0.4).select(0.3999, 0).id == "s")
check("mastery == mastery_gte matches (inclusive >=)", solo(mastery_gte=0.4).select(0.4, 0).id == "s")
check("mastery just below mastery_gte no match", raises(lambda: solo(mastery_gte=0.4).select(0.3999, 0), StrategyError))
check("grade == grade_max matches (inclusive <=)", solo(grade_max=6).select(0.5, 6).id == "s")
check("grade above grade_max no match", raises(lambda: solo(grade_max=6).select(0.5, 7), StrategyError))
check("grade == grade_min matches (inclusive >=)", solo(grade_min=7).select(0.5, 7).id == "s")
check("grade below grade_min no match", raises(lambda: solo(grade_min=7).select(0.5, 6), StrategyError))
check("all-None conditions match anything", solo().select(-5.0, 99).id == "s")

# I4 同优先级 id 升序
c = StrategyLibrary()
for sid in ("b", "a", "c"):
    c.add(Strategy(id=sid, name="", description=""))
check("same priority sorted by id asc", [t.id for t in c.strategies()] == ["a", "b", "c"])
lst = c.strategies()
lst.append(Strategy(id="zz", name="", description=""))
check("strategies returns fresh list", len(c.strategies()) == 3)

# I3 空库/无匹配
try:
    StrategyLibrary().select(0.5, 7)
    check("empty select raises", False)
except StrategyError:
    check("empty select raises", True)

# 3.3 load_strategies：合法样例
lib2 = load_strategies(os.path.join(ROOT, "data", "pedagogy", "strategies.json"))
ids = [t.id for t in lib2.strategies()]
check("sample ids order", ids == ["s_gamified", "s_worked_example", "s_retrieval", "s_interleave", "s_guided_practice"])

tmp = tempfile.mkdtemp()


def wjson(obj, name="t.json"):
    p = os.path.join(tmp, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return p


check("top-level list -> TypeError", raises(lambda: load_strategies(wjson([1, 2, 3])), TypeError))
check("strategies=5 -> TypeError", raises(lambda: load_strategies(wjson({"strategies": 5})), TypeError))
check("strategies='abc' -> TypeError", raises(lambda: load_strategies(wjson({"strategies": "abc"})), TypeError))
check("entry str -> TypeError", raises(lambda: load_strategies(wjson({"strategies": ["a"]})), TypeError))
check("entry list -> TypeError", raises(lambda: load_strategies(wjson({"strategies": [[1, 2]]})), TypeError))
check("entry null -> TypeError", raises(lambda: load_strategies(wjson({"strategies": [None]})), TypeError))
check("missing name -> KeyError", raises(lambda: load_strategies(wjson({"strategies": [{"id": "x"}]})), KeyError))
check("missing strategies key -> KeyError", raises(lambda: load_strategies(wjson({"other": []})), KeyError))
check("dup id in file -> StrategyError", raises(lambda: load_strategies(wjson({"strategies": [{"id": "x", "name": "1"}, {"id": "x", "name": "2"}]})), StrategyError))
check("unknown key ignored", load_strategies(wjson({"strategies": [{"id": "x", "name": "n", "bogus": 123}]})).get("x") is not None)
check("missing file -> FileNotFoundError", raises(lambda: load_strategies(os.path.join(tmp, "nope.json")), FileNotFoundError))
p_bad = os.path.join(tmp, "bad.json")
with open(p_bad, "w", encoding="utf-8") as f:
    f.write("{not json")
check("invalid json -> JSONDecodeError", raises(lambda: load_strategies(p_bad), json.JSONDecodeError))
check("bad priority -> ValueError", raises(lambda: load_strategies(wjson({"strategies": [{"id": "x", "name": "n", "priority": "zap"}]})), ValueError))

# 5 确定性：select 重复调用同一对象
check("select deterministic identity", lib2.select(0.2, 4) is lib2.select(0.2, 4))

print("RESULT:", "ALL PASS" if not fails else f"{len(fails)} FAIL: {fails}")
sys.exit(1 if fails else 0)
