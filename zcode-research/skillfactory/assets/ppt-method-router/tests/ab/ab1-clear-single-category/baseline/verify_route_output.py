# -*- coding: utf-8 -*-
"""AB1（清晰型单信号 case9）baseline 校验脚本。

只读取本目录内由实际运行捕获的 route-stdout.txt / route-stderr.txt，
不读取 package/、oracle/ 下任何文件（公平性限制）。
参照判定取自任务说明原文：method=visual_report, confidence=0.8。

产出：verify-output.txt（逐项校验日志）、verdict.json（结构化判定）。
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
raw = (HERE / "route-stdout.txt").read_bytes()
stderr_raw = (HERE / "route-stderr.txt").read_bytes()

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

lines_out = []


def log(s=""):
    lines_out.append(s)


log(f"route-stdout.txt bytes = {len(raw)}")
log(f"route-stderr.txt bytes = {len(stderr_raw)}")

text = raw.decode("utf-8", errors="replace")
all_lines = text.splitlines()
nonempty = [l for l in all_lines if l.strip()]
log(f"stdout total lines = {len(all_lines)}; non-empty lines = {len(nonempty)}")
for i, l in enumerate(all_lines, 1):
    log(f"  line{i}: {l!r}")

check_single_line = len(nonempty) == 1
json_line = nonempty[0] if nonempty else ""
try:
    obj = json.loads(json_line)
    parse_ok = True
except Exception as e:
    obj, parse_ok = None, False
    log(f"JSON parse error: {e}")

checks = {}
checks["stdout_is_single_parseable_json_line"] = bool(check_single_line and parse_ok)

if parse_ok:
    keys = sorted(obj.keys())
    log(f"top-level keys = {keys}")
    checks["keys_are_method_confidence_reasons"] = keys == ["confidence", "method", "reasons"]

    method = obj.get("method")
    conf = obj.get("confidence")
    reasons = obj.get("reasons")

    checks["method_matches_reference_visual_report"] = method == "visual_report"
    log(f"method = {method!r}  (reference: 'visual_report')")

    is_num = isinstance(conf, (int, float)) and not isinstance(conf, bool)
    in_range = is_num and 0.0 <= float(conf) <= 1.0
    eq_ref = is_num and float(conf) == 0.8
    checks["confidence_is_numeric_in_0_1"] = in_range
    checks["confidence_equals_reference_0_8"] = eq_ref
    log(
        f"confidence = {conf!r} (type={type(conf).__name__}) "
        f"numeric_in_[0,1]={in_range} equals_ref_0.8={eq_ref}"
    )

    if isinstance(reasons, list):
        reasons_text = " ".join(str(x) for x in reasons)
        reasons_nonempty = len(reasons) > 0 and reasons_text.strip() != ""
        rtype = f"list(len={len(reasons)})"
    else:
        reasons_text = str(reasons) if reasons is not None else ""
        reasons_nonempty = bool(reasons_text.strip())
        rtype = type(reasons).__name__
    has_keyword = "海报" in reasons_text
    checks["reasons_nonempty"] = reasons_nonempty
    checks["reasons_mention_poster_keyword"] = has_keyword
    log(f"reasons type = {rtype}; joined text = {reasons_text!r}")
    log(f"reasons non-empty = {reasons_nonempty}; mentions 海报 = {has_keyword}")

checks["stderr_empty"] = len(stderr_raw) == 0
log(f"stderr empty = {len(stderr_raw) == 0}")

overall = all(checks.values())
log("")
log("== check verdicts ==")
for k, v in checks.items():
    log(f"  [{'PASS' if v else 'FAIL'}] {k}")
log(f"OVERALL: {'PASS' if overall else 'FAIL'}")

(HERE / "verify-output.txt").write_text("\n".join(lines_out) + "\n", encoding="utf-8")
(HERE / "verdict.json").write_text(
    json.dumps(
        {
            "case": "case9",
            "command": "python package/scripts/route.py --input oracle/inputs/case9.txt",
            "cwd": "skillfactory/assets/ppt-method-router",
            "stdout": text,
            "stderr": stderr_raw.decode("utf-8", errors="replace"),
            "reference_from_task_brief": {"method": "visual_report", "confidence": 0.8},
            "checks": checks,
            "overall": "PASS" if overall else "FAIL",
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)

print("\n".join(lines_out))
