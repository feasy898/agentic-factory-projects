# -*- coding: utf-8 -*-
"""ab1-clear-single-category / baseline 对照脚本。

对照对象：
  - raw_stdout.txt : `python package/scripts/route.py --input oracle/inputs/case9.txt` 的 stdout 原样捕获
  - oracle/out/labels.json 中 case9 的判定（公平性要求：只输出比对结果布尔值，不打印 oracle 侧原始内容）
参照判定（来自任务说明，非来自读取 oracle）：method=visual_report, confidence=0.8
"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(BASE))))
# ROOT = .../ppt-method-router（baseline 上溯 4 级：baseline→ab1→ab→tests→ppt-method-router）
STDOUT_PATH = os.path.join(BASE, "raw_stdout.txt")
STDERR_PATH = os.path.join(BASE, "raw_stderr.txt")
LABELS_PATH = os.path.join(ROOT, "oracle", "out", "labels.json")
REFERENCE = {"method": "visual_report", "confidence": 0.8}

result = {}

# ---------- 1. stdout 原始字节检查 ----------
raw = open(STDOUT_PATH, "rb").read()
result["stdout_bytes"] = len(raw)
result["stdout_newline_count"] = raw.count(b"\n")
lines = raw.decode("utf-8").splitlines()
result["stdout_nonempty_line_count"] = len([l for l in lines if l.strip()])
result["stdout_single_line"] = result["stdout_nonempty_line_count"] == 1

# ---------- 2. JSON 可解析性与字段 ----------
try:
    obj = json.loads(raw.decode("utf-8"))
    result["json_parseable"] = True
except Exception as e:
    obj = None
    result["json_parseable"] = False
    result["json_parse_error"] = str(e)

if obj is not None:
    result["stdout_top_level_type"] = type(obj).__name__
    keys = sorted(obj.keys()) if isinstance(obj, dict) else None
    result["stdout_keys"] = keys
    result["has_exactly_three_fields"] = keys == ["confidence", "method", "reasons"]

    # method
    result["my_method"] = obj.get("method")
    result["method_is_str"] = isinstance(obj.get("method"), str)

    # confidence：数值且在 [0,1]
    c = obj.get("confidence")
    result["my_confidence"] = c
    result["confidence_is_number"] = isinstance(c, (int, float)) and not isinstance(c, bool)
    result["confidence_in_0_1"] = (
        result["confidence_is_number"] and 0.0 <= float(c) <= 1.0
    )

    # reasons：非空且提到「海报」或等价裁定依据
    r = obj.get("reasons")
    result["my_reasons"] = r
    result["reasons_nonempty"] = bool(r)
    if isinstance(r, list):
        joined = " ".join(str(x) for x in r)
    else:
        joined = str(r) if r is not None else ""
    result["reasons_mention_haibao"] = "海报" in joined
    result["reasons_total_len"] = len(joined)

# ---------- 3. 与 oracle/out/labels.json case9 逐字段对照 ----------
labels = json.load(open(LABELS_PATH, encoding="utf-8"))
entry = None
key_used = None
if isinstance(labels, dict):
    for k in ("case9", "9", 9):
        if k in labels:
            entry, key_used = labels[k], k
            break
    if entry is None:  # 兜底：遍历键名找 case9
        for k, v in labels.items():
            if str(k).lower() == "case9":
                entry, key_used = v, k
                break
elif isinstance(labels, list) and len(labels) >= 9:
    entry, key_used = labels[8], "list_index_8"

result["labels_entry_found"] = entry is not None
result["labels_key_used"] = str(key_used) if key_used is not None else None

if entry is not None and obj is not None:
    result["oracle_entry_fields"] = sorted(entry.keys()) if isinstance(entry, dict) else None
    # 参照判定一致性（参照值来自任务说明）：确认 oracle 文件与任务给出的参照相符
    result["oracle_method_equals_reference_visual_report"] = entry.get("method") == REFERENCE["method"]
    result["oracle_confidence_equals_reference_0_8"] = entry.get("confidence") == REFERENCE["confidence"]
    # 逐字段比对（只输出布尔，不输出 oracle 原文）
    result["match_method"] = entry.get("method") == obj.get("method")
    result["match_confidence"] = entry.get("confidence") == obj.get("confidence")
    if "reasons" in entry:
        result["match_reasons"] = entry.get("reasons") == obj.get("reasons")
    else:
        result["match_reasons"] = None  # oracle 无 reasons 字段，无从比对
    result["all_three_match"] = (
        result["match_method"]
        and result["match_confidence"]
        and result["match_reasons"] is not False
    )

print(json.dumps(result, ensure_ascii=False, indent=2))
