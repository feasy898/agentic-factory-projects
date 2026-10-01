# -*- coding: utf-8 -*-
"""AB3 baseline analysis:
(a) rubric checks against the route output captured in run-log.json;
(b) programmatic comparison with oracle/out/labels.json case15 -
    fairness restriction: oracle contents are NOT printed; only booleans are emitted.
All file paths are literal absolute paths confined to the baseline output dir
(+ read-only access to oracle/out/labels.json for the comparison the ask requires).
"""
import json

BASE = r"D:\workspace\zcode研究\skillfactory\assets\ppt-method-router\tests\ab\ab3-mixed-priority\baseline"
P_RUNLOG = BASE + r"\run-log.json"
P_LABELS = r"D:\workspace\zcode研究\skillfactory\assets\ppt-method-router\oracle\out\labels.json"
P_ANALYSIS = BASE + r"\analysis.json"
P_RAW = BASE + r"\route-output-raw.txt"

with open(P_RUNLOG, encoding="utf-8") as f:
    log = json.load(f)

stdout = log["stdout_raw"]
stdout_stripped = stdout.rstrip("\r\n")
lines = [ln for ln in stdout_stripped.split("\n") if ln.strip() != ""]

# ---- (a) rubric checks -------------------------------------------------
checks = {}
checks["exit_code_is_0"] = (log["exit_code"] == 0)
checks["stdout_single_line"] = (len(lines) == 1)

parsed = None
parse_err = None
try:
    parsed = json.loads(lines[0]) if len(lines) == 1 else None
except Exception as e:  # noqa: BLE001
    parse_err = repr(e)
checks["stdout_parses_as_json"] = (parsed is not None)

method = parsed.get("method") if isinstance(parsed, dict) else None
conf = parsed.get("confidence") if isinstance(parsed, dict) else None
reasons = parsed.get("reasons") if isinstance(parsed, dict) else None

checks["method_equals_reference_template_fill"] = (method == "template_fill")
checks["reasons_non_empty_list"] = isinstance(reasons, list) and len(reasons) > 0
reasons_text = "\n".join(reasons) if isinstance(reasons, list) else ""

# keyword disclosures
tf_brand = ("品牌" in reasons_text) and any("template_fill" in r for r in reasons)
vr_poster = ("海报" in reasons_text) and ("一页" in reasons_text) and any("visual_report" in r for r in reasons)
checks["reasons_disclose_template_fill_keyword_brand"] = tf_brand
checks["reasons_disclose_visual_report_keywords_poster_onepage"] = vr_poster

# priority statement + conflict notice / human review
checks["reasons_state_priority_chain"] = ("template_fill > editable_pptx > visual_report" in reasons_text)
checks["reasons_state_conflict_notice"] = ("冲突" in reasons_text)
checks["reasons_state_human_review_suggestion"] = ("人工复核" in reasons_text) or ("向用户确认" in reasons_text)

# confidence range & conflict-suppression bound
conf_ok_num = isinstance(conf, (int, float)) and not isinstance(conf, bool)
checks["confidence_is_number_in_0_1"] = conf_ok_num and (0.0 <= conf <= 1.0)
checks["confidence_le_0_75_conflict_suppressed"] = conf_ok_num and (conf <= 0.75)
checks["confidence_equals_reference_0_65"] = conf_ok_num and (abs(conf - 0.65) < 1e-9)

# ---- (b) programmatic compare with labels.json (booleans only) ---------
cmp_result = {"labels_file_found": False,
              "case15_entry_found": False,
              "ref_method_matches_output": None,
              "ref_confidence_matches_output": None,
              "matched_entry_key_name": None}

try:
    with open(P_LABELS, encoding="utf-8") as f:
        data = json.load(f)
    cmp_result["labels_file_found"] = True
    entry = None
    if isinstance(data, dict):
        if "case15" in data:
            entry = data["case15"]
            cmp_result["matched_entry_key_name"] = "case15"
        else:
            for k, v in data.items():
                if isinstance(v, dict) and str(v.get("id", v.get("case", ""))).lower() == "case15":
                    entry, cmp_result["matched_entry_key_name"] = v, k
                    break
    elif isinstance(data, list):
        for it in data:
            if isinstance(it, dict) and str(it.get("id", it.get("case", ""))).lower() == "case15":
                entry = it
                break
    if entry is not None:
        cmp_result["case15_entry_found"] = True
        if isinstance(entry, str):
            cmp_result["ref_method_matches_output"] = (entry.strip() == method)
        elif isinstance(entry, dict):
            ref_m = None
            for k in ("method", "expected_method", "expected", "label", "route", "answer"):
                if k in entry:
                    ref_m = entry[k]
                    break
            ref_c = None
            for k in ("confidence", "expected_confidence", "conf"):
                if k in entry:
                    ref_c = entry[k]
                    break
            cmp_result["ref_method_matches_output"] = (ref_m == method) if ref_m is not None else None
            cmp_result["ref_confidence_matches_output"] = (
                isinstance(ref_c, (int, float)) and isinstance(conf, (int, float))
                and abs(ref_c - conf) < 1e-9
            ) if ref_c is not None else None
except Exception as e:  # noqa: BLE001
    cmp_result["error"] = repr(e)

# ---- persist ------------------------------------------------------------
analysis = {
    "command": log["command"],
    "cwd": log["cwd"],
    "exit_code": log["exit_code"],
    "stdout": stdout,
    "stderr": log["stderr_raw"],
    "parsed_output": parsed,
    "checks": checks,
    "labels_compare": cmp_result,
    "stdout_parse_error": parse_err,
}
with open(P_ANALYSIS, "w", encoding="utf-8") as f:
    json.dump(analysis, f, ensure_ascii=False, indent=2)
with open(P_RAW, "w", encoding="utf-8", newline="") as f:
    f.write(stdout)

print(json.dumps({"checks": checks, "labels_compare": cmp_result, "parse_error": parse_err},
                 ensure_ascii=False, indent=2))
