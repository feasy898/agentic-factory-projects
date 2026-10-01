"""自验证：规格 §3.3/§3.5-§3.8 的探针实例与 [仅参考] 行为（自建 duck-typed bank，不读参考实现）。"""
import sys

sys.path.insert(0, "src")
sys.path.insert(0, "regen/round1")

import agent_shell as m  # noqa: E402
from xuexing.types import Item, Misconception  # noqa: E402

failures = []


def check(name, got, want):
    if got != want:
        failures.append(f"{name}: got {got!r}, want {want!r}")
    else:
        print(f"ok  {name}")


# --- §3.3 MockLLM 冻结探针 ---
llm = m.MockLLM("item_drafter")
out1 = llm.complete("sys", "kp=a difficulty=0.30")
check("drafter same-line", out1,
      '{"id": "draft-a-30", "item_type": "fill", "stem": "计算：6 + 5 = ?", "answer": "11", '
      '"kps": ["a"], "difficulty": 0.3, "solution": "6 + 5 = 11"}')
check("drafter calls recorded", llm.calls, [("sys", "kp=a difficulty=0.30")])
out2 = m.MockLLM("item_drafter").complete("sys", "kp=a\ndifficulty=0.30")
import json as _json  # noqa: E402
d2 = _json.loads(out2)
check("drafter split-line kps", d2["kps"], ["kp_unknown"])
check("drafter split-line diff/id", (d2["difficulty"], d2["id"]), (0.5, "draft-kp_unknown-50"))
check("explainer hit", m.MockLLM("explainer").complete("sys", "教学提示: 提示X"),
      "【讲解】提示X 我们一步步来看这道题……")
check("explainer fullwidth-colon miss", m.MockLLM("explainer").complete("sys", "教学提示：提示X"),
      "【讲解】回顾基础概念 我们一步步来看这道题……")
check("default", m.MockLLM().complete("sys", "u"), "OK")

# --- §3.5 attribute_error 探针 ---
mcs = [
    Misconception(id="mc_x", kp_id="a", description="误解X", hint="提示X", signature=["9"]),
    Misconception(id="mc_y", kp_id="a", description="误解Y", hint="提示Y", signature=["7"]),
]
item = Item(id="i1", item_type="fill", stem="s-i1", answer="5", kps=["a"], difficulty=0.4)


class Scripted:
    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def complete(self, system, user):
        self.calls += 1
        return self.reply


check("sig strip both sides", m.attribute_error(item, " 7 ", mcs, Scripted("anything")), "mc_y")
l1 = Scripted("我认为是 mc_y")
check("llm fallback", m.attribute_error(item, "weird", mcs, l1), "mc_y")
check("llm exactly once", l1.calls, 1)
check("none reply", m.attribute_error(item, "weird", mcs, Scripted("NONE")), None)
check("empty answer no llm", m.attribute_error(item, "  ", mcs, Scripted("mc_x")), None)

# --- §3.6 explain_error 冻结耦合自验谓词 ---
import re as _re  # noqa: E402


class Capture:
    def __init__(self):
        self.user = None

    def complete(self, system, user):
        self.user = user
        return "  "  # 全空白 → 回退路径


cap = Capture()
out = m.explain_error(item, "9", "提示X", cap)
mm = _re.search(r"教学提示:\s*(.+)$", cap.user, _re.M)
check("explain predicate hit", bool(mm), True)
check("explain predicate group==hint", mm.group(1).strip(), "提示X")
check("explain blank-reply fallback", out, "【讲解】提示X")

# --- §3.7 draft_item 冻结耦合自验谓词 ---


class CaptureJson:
    def __init__(self):
        self.user = None

    def complete(self, system, user):
        self.user = user
        return '前言 {"id": "d1", "stem": "x"} 后记'  # 带噪声，检验 find/rfind 截取


cap2 = CaptureJson()
draft = m.draft_item(cap2, "a", 0.3)
mm2 = _re.search(r"kp=(\S+).*?difficulty=([\d.]+)", cap2.user)
check("draft predicate hit", bool(mm2), True)
check("draft predicate kp", mm2.group(1), "a")
check("draft predicate diff", float(mm2.group(2)), 0.3)
check("draft kps", draft["kps"], ["a"])
check("draft non-brace reply", _json.loads(m.MockLLM("item_drafter").complete("s", "kp=z difficulty=1.00")),
      {"id": "draft-z-100", "item_type": "fill", "stem": "计算：13 + 5 = ?", "answer": "18",
       "kps": ["z"], "difficulty": 1.0, "solution": "13 + 5 = 18"})
try:
    m.draft_item(Scripted("no braces here"), "a", 0.3)
    failures.append("no-brace: LLMError not raised")
except m.LLMError as e:
    check("no-brace LLMError msg", str(e), "draft is not JSON")
try:
    m.draft_item(Scripted("{not json}"), "a", 0.3)
    failures.append("bad-json: JSONDecodeError not bubbled")
except _json.JSONDecodeError:
    print("ok  bad-json bubbles JSONDecodeError")
check("LLMError is RuntimeError", issubclass(m.LLMError, RuntimeError), True)

# --- §3.8 try_accept_draft：duck-typed bank ---


class MyBank:
    def __init__(self):
        self._items = []

    def validate_item(self, it):
        errs = []
        if not it.answer:
            errs.append(f"{it.id}: empty answer")
        if not (0.0 <= it.difficulty <= 1.0):
            errs.append(f"{it.id}: difficulty out of [0,1]")
        return errs

    def items(self):
        return sorted(self._items, key=lambda i: i.id)

    def add(self, it):
        self._items.append(it)

    def has(self, iid):
        return any(i.id == iid for i in self._items)


bk = MyBank()
bk.add(Item(id="a1", item_type="fill", stem="stem-a1", answer="ans", kps=["a"], difficulty=0.2))
draft_ml = m.draft_item(m.MockLLM("item_drafter"), "a", 0.3)
g = m.try_accept_draft(draft_ml, bk, {"a"})
check("gate accept", g, (True, []))
check("gate stored with solution", bk.has("draft-a-30"), True)
stored = [i for i in bk.items() if i.id == "draft-a-30"][0]
check("gate solution field kept", stored.solution, "6 + 5 = 11")
g2 = m.try_accept_draft(dict(draft_ml, id="draft-a-30-2"), bk, {"a"})
check("gate duplicate", (g2[0], any("duplicate" in e for e in g2[1]), len(g2[1])), (False, True, 1))
co = {"id": "q1", "item_type": "fill", "stem": "stem-a1", "answer": "", "kps": ["ghost"], "difficulty": 0.5}
check("gate co-existing errs", m.try_accept_draft(co, bk, {"a"}),
      (False, ["q1: empty answer", "q1: unknown kp ghost", "q1: duplicate stem with a1"]))
check("gate malformed kps=None", m.try_accept_draft({"kps": None}, bk, {"a"})[0], False)
check("gate malformed msg prefix", m.try_accept_draft({"kps": None}, bk, {"a"})[1][0].startswith("malformed draft:"), True)
n_before = len(bk.items())
m.try_accept_draft({"id": "bad3", "item_type": "fill", "stem": "zz", "answer": "", "kps": ["a"], "difficulty": 2.0}, bk, {"a"})
check("gate reject no mutation", len(bk.items()), n_before)
try:
    m.try_accept_draft("not-a-dict", bk, {"a"})
    failures.append("non-dict: AttributeError not bubbled")
except AttributeError:
    print("ok  non-dict bubbles AttributeError")

print()
if failures:
    print("FAILURES:")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("all probes passed")
