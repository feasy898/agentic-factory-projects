# -*- coding: utf-8 -*-
"""AB2（歧义型·无信号 case11）baseline 程序化校验。

只做三件事，均不读取 package/、oracle/、spec.md 的文件内容（公平性限制）：
1. 读取本目录首次运行落盘的 route-stdout.txt / route-stderr.txt（原始字节）；
2. 以相同命令复跑一次 route.py（subprocess，cwd=ppt-method-router），做字节级复现比对；
3. 按本条 rubric 逐项判定，写出 verdict.json 并打印报告。
"""
import json
import os
import re
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROUTER_DIR = os.path.abspath(os.path.join(BASE, "..", "..", "..", ".."))
CMD = [sys.executable, "package/scripts/route.py", "--input", "oracle/inputs/case11.txt"]
COMMAND_STR = "python package/scripts/route.py --input oracle/inputs/case11.txt"

# 参照判定：取自任务材料原文（「参照判定 editable_pptx / 0.4 兜底」）。
# oracle/out/labels.json 属禁读目录，本脚本与报告均未读取它。
REFERENCE = {"method": "editable_pptx", "confidence": 0.4}


def decode(b):
    for enc in ("utf-8", "gbk"):
        try:
            return b.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", errors="replace"), "utf-8(replace)"


def main():
    checks = {}
    detail = {}

    # ---- 1) 首次运行的落盘捕获 ----
    raw_out = open(os.path.join(BASE, "route-stdout.txt"), "rb").read()
    raw_err = open(os.path.join(BASE, "route-stderr.txt"), "rb").read()
    out_text, out_enc = decode(raw_out)
    err_text, err_enc = decode(raw_err)

    # ---- 2) 复跑一次做复现性比对 ----
    p = subprocess.run(CMD, cwd=ROUTER_DIR, capture_output=True)
    rerun_text, rerun_enc = decode(p.stdout)
    checks["rerun_exit_code_0"] = p.returncode == 0
    checks["rerun_bytes_identical_to_first_run"] = p.stdout == raw_out
    detail["rerun"] = {
        "cmd": COMMAND_STR,
        "exit_code": p.returncode,
        "stdout_bytes": len(p.stdout),
        "encoding": rerun_enc,
        "bytes_identical": p.stdout == raw_out,
    }

    # ---- 3) stdout 恰一行可解析 JSON ----
    stripped = out_text.strip()
    lines = stripped.split("\n")
    checks["stdout_single_line"] = len(lines) == 1
    checks["stdout_ends_with_single_trailing_newline"] = out_text in (
        stripped + "\n", stripped + "\r\n")
    obj = None
    try:
        obj = json.loads(stripped)
        checks["stdout_parses_as_json"] = isinstance(obj, dict)
    except Exception as e:
        checks["stdout_parses_as_json"] = False
        detail["json_parse_error"] = repr(e)
    checks["keys_exactly_method_confidence_reasons"] = (
        isinstance(obj, dict) and sorted(obj.keys()) == ["confidence", "method", "reasons"])
    checks["stderr_empty"] = len(raw_err) == 0

    method = obj.get("method") if isinstance(obj, dict) else None
    conf = obj.get("confidence") if isinstance(obj, dict) else None
    reasons = obj.get("reasons") if isinstance(obj, dict) else None

    # ---- 4) method 与参照判定一致（兜底裁定 editable_pptx）----
    checks["method_matches_reference_editable_pptx"] = method == REFERENCE["method"]
    checks["method_in_contract_enum"] = method in {
        "editable_pptx", "template_fill", "visual_report"}

    # ---- 5) confidence 数值、[0,1]、明显低于有信号情形（<=0.6）、等于参照 0.4 ----
    conf_is_num = isinstance(conf, (int, float)) and not isinstance(conf, bool)
    checks["confidence_numeric_not_bool"] = conf_is_num
    checks["confidence_in_0_1"] = conf_is_num and 0.0 <= float(conf) <= 1.0
    checks["confidence_low_le_0_6"] = conf_is_num and float(conf) <= 0.6
    checks["confidence_equals_reference_0_4"] = conf == REFERENCE["confidence"]

    # ---- 6) reasons 非空且元素均非空字符串 ----
    checks["reasons_nonempty_array"] = (
        isinstance(reasons, list) and len(reasons) >= 1
        and all(isinstance(r, str) and r.strip() for r in reasons))
    joined = " | ".join(reasons) if isinstance(reasons, list) else ""

    # ---- 7) reasons 如实说明「未命中/无信号」与「兜底默认」----
    checks["reasons_state_no_keyword_hit_or_no_signal"] = any(
        k in joined for k in ["未命中", "无命中", "没有命中", "无信号", "未出现", "未匹配", "无任何"])
    checks["reasons_state_fallback_default"] = any(
        k in joined for k in ["兜底", "默认", "fallback", "缺省"])

    # ---- 8) 未编造命中：无「未」以外的「命中」表述；未把普通词报成命中 ----
    positive_hits = re.findall(r"(?<!未)命中", joined)
    checks["reasons_no_fabricated_hit_claim"] = len(positive_hits) == 0
    detail["positive_hit_occurrences"] = positive_hits
    detail["mentions_input_plain_words"] = {
        "产品介绍": "产品介绍" in joined,
        "团队情况": "团队情况" in joined,
        "产品": "产品" in joined,
        "团队": "团队" in joined,
    }
    # rubric 要求「未把产品介绍/团队情况等普通词误报为任何类别关键词的命中」：
    # reasons 完全未出现这些词，且唯一的「命中」出现在否定句「未命中」中 → 不存在误报。

    detail["case"] = "case11"
    detail["command"] = COMMAND_STR
    detail["cwd"] = "skillfactory/assets/ppt-method-router"
    detail["stdout_raw"] = out_text
    detail["stdout_bytes"] = len(raw_out)
    detail["stdout_encoding"] = out_enc
    detail["stderr_text"] = err_text
    detail["exit_code_first_run"] = 0
    detail["parsed"] = obj
    detail["reference_from_task_brief"] = REFERENCE

    overall = "PASS" if all(bool(v) for v in checks.values()) else "FAIL"

    verdict = {
        "case": "case11",
        "command": COMMAND_STR,
        "cwd": "skillfactory/assets/ppt-method-router",
        "stdout": out_text,
        "stderr": err_text,
        "exit_code": 0,
        "reference_from_task_brief": REFERENCE,
        "checks": checks,
        "detail": detail,
        "overall": overall,
    }
    with open(os.path.join(BASE, "verdict.json"), "w", encoding="utf-8") as f:
        json.dump(verdict, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("== AB2 case11 baseline verification ==")
    print("command:", COMMAND_STR)
    print("exit_code(first run / rerun): 0 /", p.returncode)
    print("stdout bytes:", len(raw_out), "encoding:", out_enc)
    print("rerun bytes identical:", checks["rerun_bytes_identical_to_first_run"])
    print("parsed:", json.dumps(obj, ensure_ascii=False))
    print("checks:")
    for k, v in checks.items():
        print("  [%s] %s" % ("PASS" if v else "FAIL", k))
    print("OVERALL:", overall)
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
