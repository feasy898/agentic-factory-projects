# -*- coding: utf-8 -*-
"""规格条款级探针：逐条核对 specs/frozen/itembank.spec.md 冻结行为（契约测试未覆盖部分）。一次性脚本，可删。"""
import importlib.util, json, os, sys, tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
spec = importlib.util.spec_from_file_location("_regen_itembank_probe", os.path.join(ROOT, "regen", "round2", "itembank.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
from xuexing.types import Item

ItemBank, ItemBankError = mod.ItemBank, mod.ItemBankError
itembank_from_dict, load_itembank = mod.itembank_from_dict, mod.load_itembank

fails = []
def check(name, cond):
    if not cond:
        fails.append(name)

def item(iid, **kw):
    base = dict(id=iid, item_type="fill", stem="s-" + str(iid), answer="x", kps=["a"], difficulty=0.5)
    base.update(kw)
    return Item(**base)

# --- 3.1/3.3 异常类型与重复 id 消息 ---
b = ItemBank(); b.add(item("a1"))
check("mro", ItemBankError.__mro__[:3] == (ItemBankError, ValueError, Exception))
try:
    b.add(item("a1")); check("dup-raise", False)
except ItemBankError as e:
    check("dup-msg", str(e) == "duplicate item id: a1")

# --- 3.4/3.5 缺失安静 ---
check("missing-quiet", b.get("nope") is None and b.has("nope") is False)

# --- 3.6 items(): id 升序 / 新列表 / 存引用 / add 不校验 ---
b2 = ItemBank(); i_z, i_a, i_m = item("z3"), item("a1"), item("m2")
b2.add(i_z); b2.add(i_a); b2.add(i_m)
check("items-order", [i.id for i in b2.items()] == ["a1", "m2", "z3"])
check("items-newlist", b2.items() is not b2.items())
lst = b2.items(); lst.append(None)
check("items-isolated", len(b2.items()) == 3)
check("same-ref", b2.get("a1") is i_a)
b2.add(item("bad", difficulty=9.9)); check("add-no-validate", b2.has("bad"))

# --- 3.7 by_kp 语义（含空 kps、排序） ---
b4 = ItemBank()
b4.add(item("i1", kps=["a", "b"])); b4.add(item("i2", kps=["b"])); b4.add(item("e1", kps=[]))
check("primary", [i.id for i in b4.by_kp("a", primary_only=True)] == ["i1"])
check("member", {i.id for i in b4.by_kp("b")} == {"i1", "i2"})
check("empty-kps", all(i.id != "e1" for i in b4.by_kp("a")))
b4.add(item("j0", kps=["b"]))
check("bykp-order", [i.id for i in b4.by_kp("b")] == ["i1", "i2", "j0"])

# --- 3.8 R1 不短路：精确消息列表（规格探针记录） ---
got = ItemBank().validate_item(item("", item_type="essay", stem=" ", answer=" ", kps=[], difficulty=2.0))
check("r1-noshort", got == ['missing id', ": bad item_type 'essay'", ': empty stem', ': empty answer', ': no kp tags', ': difficulty out of [0,1]'])

# --- 3.8 多违规按目录顺序累加（R2..R8 共 7 条） ---
got = ItemBank().validate_item(item("v", item_type="essay", stem=" ", answer="  ", kps=[],
                                    difficulty=2.0, discrimination=-0.1, guess=1.5))
check("multi-order", got == ["v: bad item_type 'essay'", "v: empty stem", "v: empty answer",
                             "v: no kp tags", "v: difficulty out of [0,1]",
                             "v: discrimination out of [0,1]", "v: guess out of [0,1]"])

# --- 3.8 R9 组内结构 ---
vb = ItemBank()
check("r9a-skip-b", vb.validate_item(item("c", item_type="choice", options=["A"], answer="Z"))
      == ["c: choice needs >=2 options"])
check("r9b-then-r9c", vb.validate_item(item("c", item_type="choice", options=["A. 1", "A. 1"], answer="Z"))
      == ["c: answer not among options", "c: duplicate options"])
check("nonchoice-ignores-options", vb.validate_item(item("f", item_type="fill",
      options=["A", "A"], answer="x")) == [])
check("r9b-label", vb.validate_item(item("c", item_type="choice", options=["A. 1", "B. 2"], answer="B")) == [])
check("r9b-text", vb.validate_item(item("c", item_type="choice", options=["A. 1", "B. 2"], answer="B. 2")) == [])
check("r9b-strip", vb.validate_item(item("c", item_type="choice", options=[" A. 1 ", " B. 2 "], answer=" B ")) == [])
check("r9b-afterdot", vb.validate_item(item("c", item_type="choice", options=["A. 1", "B. 2"], answer="1"))
      == ["c: answer not among options"])
check("r9b-nodot", vb.validate_item(item("c", item_type="choice", options=["TRUE", "FALSE"], answer="TRUE")) == [])

# --- 3.8† NaN/±Inf 必报越域 ---
nan, inf = float("nan"), float("inf")
check("nan-diff", any("difficulty out of [0,1]" in e for e in vb.validate_item(item("n", difficulty=nan))))
check("nan-disc", any("discrimination out of [0,1]" in e for e in vb.validate_item(item("n", discrimination=nan))))
check("nan-guess", any("guess out of [0,1]" in e for e in vb.validate_item(item("n", guess=nan))))
check("inf-diff", any("difficulty out of [0,1]" in e for e in vb.validate_item(item("n", difficulty=inf))))
check("neginf-guess", any("guess out of [0,1]" in e for e in vb.validate_item(item("n", guess=-inf))))

# --- 3.9 validate_all 精确排序实例 + None 跳过 kp 检查 ---
b5 = ItemBank()
b5.add(item("i1", kps=["ghost"], difficulty=-1)); b5.add(item("i2", kps=["ghost"], difficulty=-1))
check("va-order", b5.validate_all(valid_kp_ids={"a"}) ==
      ['i1: difficulty out of [0,1]', 'i1: unknown kp ghost', 'i2: difficulty out of [0,1]', 'i2: unknown kp ghost'])
check("va-skip-kp", b5.validate_all() == ['i1: difficulty out of [0,1]', 'i2: difficulty out of [0,1]'])

# --- 3.10 load_itembank：NaN 入口 / 中文 roundtrip / OSError / JSONDecodeError ---
d = {"items": [{"id": "n1", "item_type": "fill", "stem": "题干", "answer": "答", "kps": ["a"], "difficulty": nan}]}
tmp = os.path.join(tempfile.mkdtemp(), "items.json")
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(d, f, ensure_ascii=False)
lb = load_itembank(tmp)
check("load-nan", lb.validate_all() == ["n1: difficulty out of [0,1]"])
check("load-chinese", lb.get("n1").stem == "题干" and lb.get("n1").answer == "答")
try:
    load_itembank(tmp + ".nope"); check("load-missing", False)
except OSError:
    check("load-missing", True)
with open(tmp, "w", encoding="utf-8") as f:
    f.write("{not json")
try:
    load_itembank(tmp); check("load-badjson", False)
except json.JSONDecodeError:
    check("load-badjson", True)

# --- 3.11 from_dict：强制表 / 未知键 / answer=null / guess 原样 / 缺省 / 重复 id / 强制失败传播 ---
data = {"items": [
    {"id": "d1", "item_type": "fill", "stem": "s", "answer": 1, "kps": ["a"], "difficulty": "0.5", "bogus": 1, "weight": 9},
    {"id": "d2", "item_type": "choice", "stem": "s", "answer": None, "kps": ["a"], "difficulty": 0.5, "options": ["A. 1", "B. 2"]},
]}
bd = itembank_from_dict(data); it1, it2 = bd.get("d1"), bd.get("d2")
check("fd-answer-str", it1.answer == "1")
check("fd-diff-coerce", it1.difficulty == 0.5 and isinstance(it1.difficulty, float))
check("fd-unknown-ignored", not hasattr(it1, "bogus") and not hasattr(it1, "weight"))
check("fd-defaults", it1.solution == "" and it1.options == [] and it1.discrimination == 0.6
      and it1.guess is None and it1.misconceptions == [])
check("fd-answer-none", it2.answer == "None")
# 规格探针语境：answer=null 的普通（fill）题 validate 通过；choice 题则按 R9b 报"not among options"
bf = itembank_from_dict({"items": [{"id": "fn", "item_type": "fill", "stem": "s", "answer": None,
                                    "kps": ["a"], "difficulty": 0.5}]})
check("fd-answer-none-fill-valid", bf.validate_all() == [])
check("fd-answer-none-choice-r9b", bd.validate_all() == ["d2: answer not among options"])
bg = itembank_from_dict({"items": [{"id": "g", "item_type": "fill", "stem": "s", "answer": "x",
                                    "kps": ["a"], "difficulty": 0.5, "guess": "0.3"}]})
check("fd-guess-raw", bg.get("g").guess == "0.3")
try:
    itembank_from_dict({"items": [
        {"id": "x", "item_type": "fill", "stem": "s", "answer": "a", "kps": ["a"], "difficulty": 0.5},
        {"id": "x", "item_type": "fill", "stem": "s", "answer": "a", "kps": ["a"], "difficulty": 0.5}]})
    check("fd-dup", False)
except ItemBankError:
    check("fd-dup", True)
for field, val, exc in [("difficulty", None, TypeError), ("difficulty", "abc", ValueError),
                        ("kps", None, TypeError), ("discrimination", None, TypeError)]:
    d2 = {"id": "y", "item_type": "fill", "stem": "s", "answer": "a", "kps": ["a"], "difficulty": 0.5}
    d2[field] = val
    try:
        itembank_from_dict({"items": [d2]})
        check("coerce-%s=%r" % (field, val), False)
    except exc:
        check("coerce-%s=%r" % (field, val), True)
    except Exception as e:
        check("coerce-%s=%r wrong-exc:%s" % (field, val, type(e).__name__), False)
try:
    itembank_from_dict({"items": [{"id": "z"}]}); check("fd-missing-field", False)
except KeyError:
    check("fd-missing-field", True)
try:
    itembank_from_dict({}); check("fd-missing-items", False)
except KeyError:
    check("fd-missing-items", True)

# --- 3.12 effective_guess（types 冻结方法，本模块契约断言面） ---
check("eg-choice", item("e", item_type="choice").effective_guess() == 0.25)
check("eg-fill", item("e", item_type="fill").effective_guess() == 0.10)
check("eg-solve", item("e", item_type="solve").effective_guess() == 0.02)
check("eg-override", item("e", guess=0.9).effective_guess() == 0.9)
check("eg-unknown-type", item("e", item_type="weird").effective_guess() == 0.1)

print("FAILURES:", fails if fails else "none")
