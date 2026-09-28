# -*- coding: utf-8 -*-
"""agent_shell 重生成实例的规格条款探针（对照 spec 全部可自验点，含 [仅参考] 条款）。

装载方式与 tests/contract/conftest.py 一致：先加载参考包，再以独立文件 exec 注入
重生成实例；bank 用参考 ItemBank（仅按结构使用，spec §3.8）。
"""
import ast
import importlib.util
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

import xuexing  # noqa: F401  先完整加载参考包
from xuexing.itembank import ItemBank
from xuexing.types import Item, Misconception

_spec = importlib.util.spec_from_file_location(
    "_regen_agent_shell", os.path.join(ROOT, "regen", "round3", "agent_shell.py")
)
m = importlib.util.module_from_spec(_spec)
sys.modules["xuexing.agent_shell"] = m
_spec.loader.exec_module(m)

FAILS = []


def check(name, cond):
    if cond:
        print(f"PASS {name}")
    else:
        print(f"FAIL {name}")
        FAILS.append(name)


class RecorderLLM:
    """固定回复 + 记录 (system, user)。"""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []
        self.systems = []

    def complete(self, system, user):
        self.calls.append(user)
        self.systems.append(system)
        return self.reply


def _mcs():
    return [
        Misconception(id="mc_x", kp_id="a", description="误解X", hint="提示X", signature=["9"]),
        Misconception(id="mc_y", kp_id="a", description="误解Y", hint="提示Y", signature=["7"]),
    ]


def _item(item_id="i1", kp="a"):
    return Item(id=item_id, item_type="fill", stem=f"s-{item_id}", answer="5", kps=[kp], difficulty=0.4)


def _bank():
    b = ItemBank()
    b.add(Item(id="a1", item_type="fill", stem="stem-a1", answer="ans", kps=["a"], difficulty=0.2))
    b.add(Item(id="b1", item_type="fill", stem="stem-b1", answer="ans", kps=["b"], difficulty=0.3))
    return b


# ---- §6/§3.1 LLMError 是 RuntimeError 子类 ----
check("LLMError is RuntimeError subclass", issubclass(m.LLMError, RuntimeError))

# ---- §3.3 MockLLM 探针实例（5 条） ----
out = m.MockLLM("item_drafter").complete("sys", "kp=a difficulty=0.30")
check("MockLLM drafter hit", json.loads(out) == {
    "id": "draft-a-30", "item_type": "fill", "stem": "计算：6 + 5 = ?", "answer": "11",
    "kps": ["a"], "difficulty": 0.3, "solution": "6 + 5 = 11"})
out = json.loads(m.MockLLM("item_drafter").complete("sys", "kp=a\ndifficulty=0.30"))
check("MockLLM drafter miss (newline)", out["kps"] == ["kp_unknown"] and out["difficulty"] == 0.5
      and out["id"] == "draft-kp_unknown-50")
out = m.MockLLM("explainer").complete("sys", "教学提示: 提示X")
check("MockLLM explainer hit", out == "【讲解】提示X 我们一步步来看这道题……")
out = m.MockLLM("explainer").complete("sys", "教学提示：提示X")
check("MockLLM explainer fullwidth-colon miss", out == "【讲解】回顾基础概念 我们一步步来看这道题……")
check("MockLLM default OK", m.MockLLM().complete("sys", "u") == "OK")
llm = m.MockLLM("default")
llm.complete("s1", "u1")
llm.complete("s2", "u2")
check("MockLLM.calls order", llm.calls == [("s1", "u1"), ("s2", "u2")])

# ---- §3.5 attribute_error ----
llm = RecorderLLM("anything")
check("sig hit strip both sides", m.attribute_error(_item(), " 7 ", _mcs(), llm) == "mc_y" and llm.calls == [])
llm = RecorderLLM("mc_x")
check("empty answer -> None, no LLM", m.attribute_error(_item(), "  \t", _mcs(), llm) is None and llm.calls == [])
llm = RecorderLLM("我认为是 mc_y")
check("llm fallback first-id-substring", m.attribute_error(_item(), "weird", _mcs(), llm) == "mc_y"
      and len(llm.calls) == 1)
check("llm fallback NONE -> None", m.attribute_error(_item(), "weird", _mcs(), RecorderLLM("NONE")) is None)
llm = RecorderLLM("我觉得是 mc_y 或 mc_x")
# 规格按 misconceptions 列表顺序取第一个 id 作为子串出现的误解：mc_x 也在回复中且列表更靠前
check("first by list order", m.attribute_error(_item(), "weird", _mcs(), llm) == "mc_x")
# 空签名条目被跳过，不误命中
mcs_empty_sig = [Misconception(id="mc_e", kp_id="a", description="E", hint="H", signature=["", "  "]),
                 Misconception(id="mc_z", kp_id="a", description="Z", hint="H", signature=["z"])]
llm = RecorderLLM("NONE")
check("empty signature entries skipped", m.attribute_error(_item(), "", mcs_empty_sig, llm) is None)
check("sig match vs empty-str answer", m.attribute_error(_item(), " ", mcs_empty_sig, RecorderLLM("mc_z")) is None)
check("nonempty sig matches stripped", m.attribute_error(_item(), " z ", mcs_empty_sig, RecorderLLM("NONE")) == "mc_z")
mcs_before = [list(mc.signature) for mc in _mcs()]
m.attribute_error(_item(), "weird", _mcs(), RecorderLLM("NONE"))
check("misconceptions not mutated", [list(mc.signature) for mc in _mcs()] == mcs_before)

# ---- §3.6 explain_error：冻结耦合自验谓词 + 回退 + 恒走 LLM ----
rec = RecorderLLM("好的")
out = m.explain_error(_item(), "9", "提示X", rec)
mm = re.search(r"教学提示:\s*(.+)$", rec.calls[0], re.M)
check("explain frozen line predicate", mm is not None and mm.group(1).strip() == "提示X")
check("explain raw reply passthrough", out == "好的")
rec = RecorderLLM("   \n\t ")
check("explain blank-reply fallback", m.explain_error(_item(), "9", "提示X", rec) == "【讲解】提示X")
rec = RecorderLLM("x")
m.explain_error(_item(), "", "提示X", rec)
check("explain no empty-answer special case", len(rec.calls) == 1)
check("explain exactly one call", len(m.explain_error(_item(), "9", "提示X", RecorderLLM("y")).strip()) > 0)

# ---- §3.7 draft_item：冻结耦合自验谓词 + 解析 + 缺省 ----
for kp, diff in [("a", 0.3), ("kp_x", 0.5), ("a", 0.0), ("a", 1.0), ("a", 0.875)]:
    rec = RecorderLLM("{}")
    m.draft_item(rec, kp, diff)
    mm = re.search(r"kp=(\S+).*?difficulty=([\d.]+)", rec.calls[0])
    # :.2f 冻结格式；>2 位小数按两位舍入（0.875 -> 0.88，谓词等式仅在 <=2 位小数时成立）
    check(f"draft frozen line predicate kp={kp} diff={diff}",
          mm is not None and mm.group(1) == kp and float(mm.group(2)) == float(f"{diff:.2f}")
          and f"difficulty={diff:.2f}" in rec.calls[0])
rec = RecorderLLM('前缀文字 {"id": "d1", "stem": "s"} 后缀文字')
d = m.draft_item(rec, "a", 0.3)
check("draft brace-extraction + kps default", d == {"id": "d1", "stem": "s", "kps": ["a"]})
rec = RecorderLLM('{"kps": []}')
check("draft existing empty kps kept", m.draft_item(rec, "a", 0.3)["kps"] == [])
try:
    m.draft_item(RecorderLLM("没有任何大括号"), "a", 0.3)
    check("draft no-braces -> LLMError", False)
except m.LLMError as e:
    check("draft no-braces -> LLMError", str(e) == "draft is not JSON")
try:
    m.draft_item(RecorderLLM("{bad json}"), "a", 0.3)
    check("draft invalid JSON bubbles JSONDecodeError", False)
except json.JSONDecodeError:
    check("draft invalid JSON bubbles JSONDecodeError", True)
except m.LLMError:
    check("draft invalid JSON bubbles JSONDecodeError", False)

# ---- §3.8 try_accept_draft ----
# 成功路径 + solution 入库 + 恰新增一题
b = _bank()
size0 = len(b.items())
draft = m.draft_item(m.MockLLM("item_drafter"), "a", 0.3)
ok, errs = m.try_accept_draft(draft, b, {"a"})
check("gate success", ok and errs == [] and len(b.items()) == size0 + 1 and b.has("draft-a-30"))
check("gate stores solution", next(i for i in b.items() if i.id == "draft-a-30").solution == "6 + 5 = 11")
# 同题干（仅差首尾空白）拒绝：先试一个会被接受的无害草稿占位，再验 strip 查重
b = _bank()
size0 = len(b.items())
draft = m.draft_item(m.MockLLM("item_drafter"), "a", 0.3)
ok, errs = m.try_accept_draft(draft, b, {"a"})
check("gate success", ok and errs == [] and len(b.items()) == size0 + 1 and b.has("draft-a-30"))
check("gate stores solution", next(i for i in b.items() if i.id == "draft-a-30").solution == "6 + 5 = 11")
ok2, errs2 = m.try_accept_draft(dict(draft, id="draft-a-30-2", stem=f"  {draft['stem']}  "), b, {"a"})
check("duplicate stem (strip compare)", (not ok2) and len(errs2) == 1
      and errs2[0] == "draft-a-30-2: duplicate stem with draft-a-30"
      and len(b.items()) == size0 + 1)
ok3, errs3 = m.try_accept_draft(dict(draft, id="draft-a-30-3"), b, {"a"})
check("duplicate stem exact", (not ok3) and len(errs3) == 1
      and errs3[0] == "draft-a-30-3: duplicate stem with draft-a-30"
      and len(b.items()) == size0 + 1)
# 未知 kp / 难度越界 / bank 不变
b2 = _bank()
s2 = len(b2.items())
ok4, errs4 = m.try_accept_draft({"id": "bad1", "item_type": "fill", "stem": "x", "answer": "1",
                                 "kps": ["ghost"], "difficulty": 0.5}, b2, {"a"})
check("unknown kp rejected, bank intact", (not ok4) and any("unknown kp" in e for e in errs4)
      and len(b2.items()) == s2)
ok5, errs5 = m.try_accept_draft({"id": "bad2", "item_type": "fill", "stem": "y", "answer": "1",
                                 "kps": ["a"], "difficulty": 2.0}, b2, {"a"})
check("difficulty out of range rejected", (not ok5) and any("difficulty" in e for e in errs5))
ok6, errs6 = m.try_accept_draft({"id": "bad3", "item_type": "fill", "stem": "z", "answer": "1",
                                 "kps": ["a"]}, b2, {"a"})
check("missing difficulty -> -1.0 rejected", (not ok6) and any("difficulty" in e for e in errs6))
# 多类错误并存（[仅参考] 探针实例，逐字对照）
ok7, errs7 = m.try_accept_draft({"id": "q1", "item_type": "fill", "stem": "stem-a1", "answer": "",
                                 "kps": ["ghost"], "difficulty": 0.5}, _bank(), {"a"})
check("coexisting errors accumulate verbatim",
      (not ok7) and errs7 == ["q1: empty answer", "q1: unknown kp ghost", "q1: duplicate stem with a1"])
# malformed 草稿：唯一短路出口，bank 不变
b3 = _bank()
s3 = len(b3.items())
ok8, errs8 = m.try_accept_draft({"id": "m1", "item_type": "fill", "stem": "m", "answer": "1",
                                 "kps": None, "difficulty": 0.5}, b3, {"a"})
check("kps=None -> malformed, bank intact", (not ok8) and len(errs8) == 1
      and errs8[0].startswith("malformed draft: ") and len(b3.items()) == s3)
ok9, errs9 = m.try_accept_draft({"id": "m2", "item_type": "fill", "stem": "m", "answer": "1",
                                 "kps": ["a"], "difficulty": "abc"}, b3, {"a"})
check("difficulty=abc -> malformed", (not ok9) and len(errs9) == 1 and errs9[0].startswith("malformed draft: "))
# id 撞库（题干不同）-> ValueError 冒泡（[仅参考]）
b4 = _bank()
try:
    m.try_accept_draft(dict(draft, id="a1"), b4, {"a"})
    check("id collision bubbles ValueError", False)
except ValueError:
    check("id collision bubbles ValueError", True)
# 入参不被修改
d0 = dict(draft)
kpset = {"a"}
m.try_accept_draft(draft, _bank(), kpset)
check("draft/valid_kp_ids not mutated", draft == d0 and kpset == {"a"})
# 空白题干查重：与空白既有题干相等的 strip 命中
b5 = ItemBank()
b5.add(Item(id="e1", item_type="fill", stem="  ", answer="ans", kps=["a"], difficulty=0.5))
ok10, errs10 = m.try_accept_draft({"id": "n1", "item_type": "fill", "stem": " ", "answer": "1",
                                   "kps": ["a"], "difficulty": 0.5}, b5, {"a"})
check("strip-only-whitespace stem duplicate", (not ok10)
      and any("duplicate stem with e1" in e for e in errs10))

# ---- 静态合规：import 白名单 + 无 itembank 引用 + 无 random/time ----
src = open(os.path.join(ROOT, "regen", "round3", "agent_shell.py"), encoding="utf-8").read()
tree = ast.parse(src)
imps = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        imps.update(a.name for a in node.names)
    elif isinstance(node, ast.ImportFrom):
        imps.add(node.module or "")
allowed = {"json", "os", "re", "typing", "xuexing.types", "__future__",
           "httpx"}  # httpx 为 §2 唯一豁免：仅 OpenAICompatClient.complete 内延迟 import
check("imports within whitelist", imps <= allowed and "xuexing.types" in imps)
check("no itembank reference in source", "itembank" not in src)
check("no random/time modules", "import random" not in src and "import time" not in src)
check("public API present", all(hasattr(m, n) for n in
      ["LLMError", "LLMClient", "MockLLM", "OpenAICompatClient",
       "attribute_error", "explain_error", "draft_item", "try_accept_draft"]))
import inspect
check("OpenAICompatClient signature",
      list(inspect.signature(m.OpenAICompatClient.__init__).parameters) == ["self", "base_url", "model", "api_key_env"]
      and inspect.signature(m.OpenAICompatClient.__init__).parameters["api_key_env"].default == "XX_LLM_API_KEY"
      and m.OpenAICompatClient("http://h//", "gpt").base_url == "http://h")

print()
print("ALL PASS" if not FAILS else f"FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
