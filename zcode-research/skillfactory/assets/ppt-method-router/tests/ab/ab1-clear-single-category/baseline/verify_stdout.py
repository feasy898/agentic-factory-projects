# -*- coding: utf-8 -*-
"""ab1-clear-single-category / baseline：对 route.py stdout 做机检。

对照基准说明：任务材料（ask）给出的 case9 参照判定 = method=visual_report, confidence=0.8。
oracle/out/labels.json 本体因公平性约束（不得读取 oracle/）未直接打开，
逐字段对照以任务材料给出的参照值为准。
"""
import json
import sys

BASE = r"D:\workspace\zcode研究\skillfactory\assets\ppt-method-router\tests\ab\ab1-clear-single-category\baseline"
REF_METHOD = "visual_report"   # 来自任务材料：labels.json 中 case9 参照判定
REF_CONF = 0.8                 # 来自任务材料：同上

checks = []

def check(name, passed, detail):
    checks.append({"check": name, "pass": bool(passed), "detail": detail})

with open(BASE + r"\stdout.txt", "rb") as f:
    raw = f.read()

try:
    text = raw.decode("utf-8")
    decode_note = "utf-8"
except UnicodeDecodeError:
    text = raw.decode("gbk")
    decode_note = "gbk"

lines = text.splitlines()
nonempty = [ln for ln in lines if ln.strip()]
check("stdout_恰为单行", len(nonempty) == 1, "非空行数=%d, 总行数=%d" % (len(nonempty), len(lines)))

parsed = None
parse_err = ""
try:
    parsed = json.loads(nonempty[0]) if nonempty else None
    parse_ok = parsed is not None
except Exception as e:
    parse_ok = False
    parse_err = repr(e)
check("stdout_为可解析JSON", parse_ok, parse_err or "json.loads 成功, 顶层类型=%s" % type(parsed).__name__)

has_keys = isinstance(parsed, dict) and all(k in parsed for k in ("method", "confidence", "reasons"))
extra = sorted(set(parsed) - {"method", "confidence", "reasons"}) if isinstance(parsed, dict) else []
check("JSON含method/confidence/reasons三字段", bool(has_keys),
      "含三字段=%s, 多余键=%s" % (bool(has_keys), extra if extra else "无"))

method = parsed.get("method") if isinstance(parsed, dict) else None
check("method与参照一致(visual_report)", method == REF_METHOD,
      "实际=%r, 参照=%r" % (method, REF_METHOD))

conf = parsed.get("confidence") if isinstance(parsed, dict) else None
is_num = isinstance(conf, (int, float)) and not isinstance(conf, bool)
in_range = is_num and 0.0 <= float(conf) <= 1.0
check("confidence为[0,1]数值", in_range,
      "实际=%r(类型=%s), 是否数值=%s, 是否在[0,1]=%s" % (conf, type(conf).__name__, is_num, in_range))

reasons = parsed.get("reasons") if isinstance(parsed, dict) else None
reasons_nonempty = isinstance(reasons, list) and len(reasons) > 0 and all(
    isinstance(r, str) and r.strip() for r in reasons)
joined = " ".join(reasons) if isinstance(reasons, list) and all(isinstance(r, str) for r in reasons) else ""
mentions = ("海报" in joined)
check("reasons非空且提到命中词「海报」", reasons_nonempty and mentions,
      "reasons条数=%s, 全部非空字符串=%s, 含「海报」=%s" % (
          len(reasons) if isinstance(reasons, list) else type(reasons).__name__,
          reasons_nonempty, mentions))

verdict = {
    "stdout_encoding": decode_note,
    "stdout_raw_single_line": nonempty[0] if len(nonempty) == 1 else None,
    "stderr_bytes": __import__("os").path.getsize(BASE + r"\stderr.txt"),
    "parsed": parsed,
    "reference_from_ask": {"method": REF_METHOD, "confidence": REF_CONF},
    "field_by_field": {
        "method": {"stdout": method, "reference": REF_METHOD, "match": method == REF_METHOD},
        "confidence": {"stdout": conf, "reference": REF_CONF,
                       "in_[0,1]": in_range, "equals_reference": (conf == REF_CONF) if is_num else None},
        "reasons": {"stdout": reasons, "non_empty": reasons_nonempty,
                    "mentions_keyword_海报": mentions},
    },
    "checks": checks,
    "all_pass": all(c["pass"] for c in checks),
}

with open(BASE + r"\verify_result.json", "w", encoding="utf-8") as f:
    json.dump(verdict, f, ensure_ascii=False, indent=2)

print(json.dumps(verdict, ensure_ascii=False, indent=2))
sys.exit(0 if verdict["all_pass"] else 1)
