# -*- coding: utf-8 -*-
"""Verify route.py output for case11 against the rubric. Reads only the captured stdout.raw."""
import json, sys

OUT = "tests/ab/ab2-ambiguous-fallback/baseline"
raw = open(f"{OUT}/stdout.raw", "rb").read().decode("utf-8")
results = []
def check(name, ok, detail):
    results.append((name, ok, detail))

# 1. stdout is exactly one line of parseable JSON
lines = raw.splitlines()
check("stdout is exactly 1 line", len(lines) == 1, f"line count = {len(lines)}")
data = json.loads(raw)  # raises if not parseable
check("stdout parses as JSON", True, f"keys = {sorted(data.keys())}")

# 2. method matches reference verdict editable_pptx (fallback)
method = data.get("method")
check("method == editable_pptx", method == "editable_pptx", f"method = {method!r}")

# 3. confidence numeric in [0,1] and <= 0.6
conf = data.get("confidence")
conf_ok = isinstance(conf, (int, float)) and not isinstance(conf, bool) and 0.0 <= float(conf) <= 1.0
check("confidence is numeric in [0,1]", conf_ok, f"confidence = {conf!r} (type {type(conf).__name__})")
check("confidence <= 0.6 (low, below clear-signal cases)", conf_ok and float(conf) <= 0.6, f"confidence = {conf}")

# 4. reasons non-empty and state no-signal + fallback, no fabricated hits
reasons = data.get("reasons")
check("reasons non-empty list of non-empty strings",
      isinstance(reasons, list) and len(reasons) > 0 and all(isinstance(r, str) and r.strip() for r in reasons),
      f"{len(reasons) if isinstance(reasons, list) else 'n/a'} reason(s)")
text = " ".join(reasons) if isinstance(reasons, list) else ""
check("reasons state no keyword hit / no signal",
      ("未命中" in text and "无信号" in text), "contains 未命中 + 无信号")
check("reasons state fallback default verdict",
      ("兜底" in text and "editable_pptx" in text), "contains 兜底 + editable_pptx")

# 5. no fabricated keyword hits: no positive claim of a hit anywhere in output
blob = json.dumps(data, ensure_ascii=False)
fabricated = [kw for kw in ("命中了", "命中：", "命中:", "命中模板", "命中可编辑", "命中视觉") if kw in blob]
check("no positive keyword-hit claim (no fabricated hits)", not fabricated, f"suspects: {fabricated or 'none'}")
check("ordinary words 产品介绍/团队情况 not reported as category-keyword hits",
      not any(f"「{w}」" in text and "命中" in text.split(f"「{w}」")[1][:12] for w in ("产品介绍", "团队情况")),
      "产品介绍/团队情况 appear only as the input being described, never as a hit")
hits_field = [k for k in data.keys() if k.lower() in ("matched", "matches", "keywords", "signals", "hits")]
check("no matched/keywords field asserting hits", not hits_field, f"top-level keys = {sorted(data.keys())}")

all_ok = True
for name, ok, detail in results:
    all_ok &= ok
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  |  {detail}")
print("ALL_PASS" if all_ok else "SOME_FAIL")
sys.exit(0 if all_ok else 1)
