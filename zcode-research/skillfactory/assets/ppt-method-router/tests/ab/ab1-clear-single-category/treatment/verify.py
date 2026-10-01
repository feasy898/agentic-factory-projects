#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""verify.py — ab1-clear-single-category/treatment 的逐项核验（只读，不写任何文件）。

对照 ask 与 rubric，逐项检查：
  C1 stdout 恰为一行可解析 JSON（无多余日志混入，UTF-8 可解码，无 BOM）；
  C2 JSON 恰含 method / confidence / reasons 三个字段，无缺失无多余；
  C3 method 与 oracle/out/labels.json 中 case9 的判定一致（参照 visual_report）；
  C4 confidence 为 0..1 之间的数值（int/float，非 bool）；
  C5 reasons 非空（非空字符串数组），且明确提到命中关键词「海报」或等价裁定依据。
  EX stderr 为空。

核验结论以 JSON 打到 stdout，由调用方落盘为 verify_result.json。
"""
import json
import sys

RAW_PATH = "D:/workspace/zcode研究/skillfactory/assets/ppt-method-router/tests/ab/ab1-clear-single-category/treatment/stdout.raw"
ERR_PATH = "D:/workspace/zcode研究/skillfactory/assets/ppt-method-router/tests/ab/ab1-clear-single-category/treatment/stderr.txt"
ORACLE_PATH = "D:/workspace/zcode研究/skillfactory/assets/ppt-method-router/oracle/out/labels.json"

checks = []


def record(cid, desc, passed, detail):
    checks.append({"id": cid, "desc": desc, "passed": bool(passed), "detail": detail})


# ---- C1: raw stdout: UTF-8 decodable, no BOM, exactly one line ----
with open(RAW_PATH, "rb") as f:
    raw = f.read()

bom = raw.startswith(b"\xef\xbb\xbf")
try:
    text = raw.decode("utf-8")
    decode_ok = True
except UnicodeDecodeError as exc:
    text = ""
    decode_ok = False
    record("C1", "stdout UTF-8 可解码", False, str(exc))

line_count = text.count("\n")  # 1 = exactly one line ending with a single newline
ends_with_single_nl = text.endswith("\n") and not text.endswith("\n\n")
one_line = decode_ok and line_count == 1 and ends_with_single_nl
record(
    "C1", "stdout 恰一行可解析 JSON、无多余日志",
    one_line and not bom,
    "bytes=%d, utf8_ok=%s, bom=%s, newline_count=%d, ends_single_newline=%s, content=%r"
    % (len(raw), decode_ok, bom, line_count, ends_with_single_nl, text),
)

# ---- C2: parse JSON, exactly the three required fields ----
stripped = text.strip()
parse_ok, obj, parse_err = False, None, None
try:
    obj = json.loads(stripped)
    parse_ok = True
except Exception as exc:  # noqa: BLE001
    parse_err = str(exc)
keys = sorted(obj.keys()) if isinstance(obj, dict) else None
fields_ok = keys == ["confidence", "method", "reasons"]
record(
    "C2", "JSON 可解析且恰含 method/confidence/reasons 三字段",
    parse_ok and fields_ok,
    "parse_ok=%s, parse_err=%s, keys=%s" % (parse_ok, parse_err, keys),
)

# ---- C3: method matches oracle case9 ----
with open(ORACLE_PATH, "r", encoding="utf-8") as f:
    oracle = json.load(f)
case9 = next((e for e in oracle if e.get("case") == "case9"), None)
out_method = obj.get("method") if isinstance(obj, dict) else None
method_match = (
    case9 is not None
    and out_method == case9.get("method")
    and out_method in ("editable_pptx", "template_fill", "visual_report")
)
record(
    "C3", "method 与 oracle case9 参照判定一致",
    method_match,
    "package_method=%r, oracle_case9_method=%r (期望 visual_report), oracle_case9_confidence=%r"
    % (out_method, case9.get("method") if case9 else None,
       case9.get("confidence") if case9 else None),
)

# ---- C4: confidence numeric in [0,1] ----
conf = obj.get("confidence") if isinstance(obj, dict) else None
conf_is_num = isinstance(conf, (int, float)) and not isinstance(conf, bool)
conf_in_range = conf_is_num and 0.0 <= float(conf) <= 1.0
record(
    "C4", "confidence 为 [0,1] 内数值",
    conf_in_range,
    "confidence=%r, type=%s, is_number=%s, in_range=%s"
    % (conf, type(conf).__name__, conf_is_num, conf_in_range),
)

# ---- C5: reasons non-empty and cites 海报 ----
reasons = obj.get("reasons") if isinstance(obj, dict) else None
reasons_nonempty = (
    isinstance(reasons, list)
    and len(reasons) > 0
    and all(isinstance(r, str) and r.strip() for r in reasons)
)
mentions_poster = reasons_nonempty and any("海报" in r for r in reasons)
record(
    "C5", "reasons 非空且明确提到命中关键词「海报」",
    reasons_nonempty and mentions_poster,
    "reasons_count=%s, all_nonempty_str=%s, mentions_haibao=%s, reasons=%r"
    % (len(reasons) if isinstance(reasons, list) else None,
       reasons_nonempty, mentions_poster, reasons),
)

# ---- EX: stderr must be empty (no log contamination) ----
with open(ERR_PATH, "rb") as f:
    err_raw = f.read()
record("EX", "stderr 为空（无日志泄漏迹象）", len(err_raw) == 0,
       "stderr_bytes=%d" % len(err_raw))

summary = {"all_passed": all(c["passed"] for c in checks), "checks": checks}

sys.stdout.reconfigure(encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2))
