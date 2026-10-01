#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""runner.py — PPT 方法意图路由（ppt-method-router）确定性评测脚本

用法（建议在资产根目录 skillfactory/assets/ppt-method-router/ 下运行；
相对路径按当前工作目录解析，也可传绝对路径）：
  python eval/runner.py <被测输出目录> <参照输出目录>
  例：python eval/runner.py package/out oracle/out
  自校验：python eval/runner.py oracle/out oracle/out

两个目录下都必须存在 labels.json（JSON 数组，元素 schema 见 ../contract.md §2.3：
[{case, method, confidence, reasons}]）。

检查项（全部通过 -> exit 0；任一失败 -> exit 1，打印失败明细）：
  reference_labels_parseable  参照 labels.json 存在、可解析为 JSON 数组
  tested_labels_parseable     被测 labels.json 存在、可解析为 JSON 数组
  tested_labels_complete_20   被测恰含 case1..case20 各一条（无缺失/重复/多余/非法元素）
  tested_entry_schema         被测每条 method ∈ {editable_pptx, template_fill, visual_report}，
                              confidence 为 [0,1] 内数值
  tested_reasons_nonempty     被测每条 reasons 为非空数组，且每个元素为非空字符串
  method_agreement_ge_80      与参照按 case 对齐的 method 一致率 ≥ 80%
                              （参照为 oracle 判定，歧义/混合型已按优先级
                              template_fill > editable_pptx > visual_report 裁定）

stdout 打印一个 JSON 对象：{"checks": [{"name","pass","detail"}, ...], "summary": {...}}。
"""
import argparse
import json
import os
import sys

ALLOWED_METHODS = ("editable_pptx", "template_fill", "visual_report")
EXPECTED_CASES = ["case%d" % i for i in range(1, 21)]
AGREEMENT_THRESHOLD = 0.80
MAX_DETAIL_ITEMS = 5


def check(name, passed, detail):
    return {"name": name, "pass": bool(passed), "detail": detail}


def load_labels(directory):
    """读取 <directory>/labels.json；返回 (list 或 None, 错误说明或 None)。"""
    path = os.path.join(directory, "labels.json")
    if not os.path.isfile(path):
        return None, "labels.json 不存在：%s" % path
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        return None, "labels.json 读取/解析失败：%s（%s）" % (path, exc)
    if not isinstance(data, list):
        return None, "labels.json 顶层必须是 JSON 数组：%s" % path
    return data, None


def index_entries(entries):
    """按 case 建索引；返回 (索引 dict, 重复 case 列表, 非法元素描述列表)。"""
    idx, dups, invalid = {}, [], []
    for pos, entry in enumerate(entries):
        if not isinstance(entry, dict):
            invalid.append("第%d个元素不是对象" % (pos + 1))
            continue
        case = entry.get("case")
        if not isinstance(case, str):
            invalid.append("第%d个元素缺少字符串字段 case" % (pos + 1))
            continue
        if case in idx:
            dups.append(case)
        else:
            idx[case] = entry
    return idx, dups, invalid


def brief(items):
    items = [str(x) for x in items]
    tail = "（等共%d项）" % len(items) if len(items) > MAX_DETAIL_ITEMS else ""
    return "; ".join(items[:MAX_DETAIL_ITEMS]) + tail


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="ppt-method-router 确定性评测：比较被测与参照 labels.json")
    parser.add_argument("tested_dir", help="被测输出目录（含 labels.json，如 package/out）")
    parser.add_argument("reference_dir", help="参照输出目录（含 labels.json，如 oracle/out）")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    checks = []

    # ---- 前置：参照可解析 ----
    ref_entries, ref_err = load_labels(args.reference_dir)
    checks.append(check(
        "reference_labels_parseable", ref_err is None,
        ref_err if ref_err else
        "参照 %s/labels.json 可解析，共 %d 条" % (args.reference_dir, len(ref_entries))))

    # ---- 前置：被测可解析 ----
    tested_entries, tested_err = load_labels(args.tested_dir)
    checks.append(check(
        "tested_labels_parseable", tested_err is None,
        tested_err if tested_err else
        "被测 %s/labels.json 可解析，共 %d 条" % (args.tested_dir, len(tested_entries))))

    summary_agreement = None
    if tested_entries is None:
        for name in ("tested_labels_complete_20", "tested_entry_schema",
                     "tested_reasons_nonempty", "method_agreement_ge_80"):
            checks.append(check(name, False, "前置失败：%s" % tested_err))
    else:
        # ---- 被测 20 条齐全 ----
        tested_idx, dups, invalid = index_entries(tested_entries)
        expected_set = set(EXPECTED_CASES)
        missing = [c for c in EXPECTED_CASES if c not in tested_idx]
        extra = sorted(c for c in tested_idx if c not in expected_set)
        complete_ok = not missing and not dups and not invalid and not extra
        if complete_ok:
            complete_detail = "恰含 case1..case20 各一条，共 %d 条" % len(tested_entries)
        else:
            parts = ["共 %d 条" % len(tested_entries)]
            if missing:
                parts.append("缺失: %s" % ", ".join(missing))
            if dups:
                parts.append("重复: %s" % ", ".join(sorted(set(dups))))
            if extra:
                parts.append("多余: %s" % ", ".join(extra))
            if invalid:
                parts.append("非法元素: %s" % brief(invalid))
            complete_detail = "；".join(parts)
        checks.append(check("tested_labels_complete_20", complete_ok, complete_detail))

        # ---- 被测每条 schema ----
        bad_method, bad_conf = [], []
        for case in EXPECTED_CASES:
            entry = tested_idx.get(case)
            if entry is None:
                continue
            if entry.get("method") not in ALLOWED_METHODS:
                bad_method.append("%s=%r" % (case, entry.get("method")))
            conf = entry.get("confidence")
            if isinstance(conf, bool) or not isinstance(conf, (int, float)) \
                    or not (0.0 <= float(conf) <= 1.0):
                bad_conf.append("%s=%r" % (case, conf))
        schema_ok = not bad_method and not bad_conf
        if schema_ok:
            schema_detail = "20 条 method 均合法且 confidence ∈ [0,1]"
        else:
            schema_detail = ""
            if bad_method:
                schema_detail += "method 非法: %s；" % brief(bad_method)
            if bad_conf:
                schema_detail += "confidence 非法: %s" % brief(bad_conf)
        checks.append(check("tested_entry_schema", schema_ok, schema_detail))

        # ---- 被测每条 reasons 非空 ----
        bad_reasons = []
        for case in EXPECTED_CASES:
            entry = tested_idx.get(case)
            if entry is None:
                continue
            reasons = entry.get("reasons")
            ok = (isinstance(reasons, list) and len(reasons) >= 1
                  and all(isinstance(r, str) and r.strip() for r in reasons))
            if not ok:
                bad_reasons.append(case)
        checks.append(check(
            "tested_reasons_nonempty", not bad_reasons,
            "20 条 reasons 均非空" if not bad_reasons
            else "reasons 为空/非法: %s" % brief(bad_reasons)))

        # ---- 与参照 method 一致率 ≥ 80% ----
        if ref_entries is None:
            checks.append(check(
                "method_agreement_ge_80", False, "前置失败：%s" % ref_err))
        else:
            ref_idx, ref_dups, ref_invalid = index_entries(ref_entries)
            ref_missing = [c for c in EXPECTED_CASES if c not in ref_idx]
            if ref_missing or ref_dups or ref_invalid:
                checks.append(check(
                    "method_agreement_ge_80", False,
                    "参照不完整，无法评测：缺失 %s；重复 %s；非法 %s" % (
                        ", ".join(ref_missing) or "无",
                        ", ".join(sorted(set(ref_dups))) or "无",
                        brief(ref_invalid) or "无")))
            else:
                matched, mismatches = 0, []
                for case in EXPECTED_CASES:
                    got = tested_idx[case].get("method")
                    want = ref_idx[case].get("method")
                    if got == want:
                        matched += 1
                    else:
                        mismatches.append("%s 期望 %s 实得 %s" % (case, want, got))
                rate = float(matched) / len(EXPECTED_CASES)
                summary_agreement = rate
                agree_ok = rate >= AGREEMENT_THRESHOLD
                detail = "method 一致率 %d/%d = %.1f%%（阈值 %.0f%%）" % (
                    matched, len(EXPECTED_CASES), rate * 100.0,
                    AGREEMENT_THRESHOLD * 100.0)
                if mismatches:
                    detail += "；不一致: " + "; ".join(mismatches)
                checks.append(check("method_agreement_ge_80", agree_ok, detail))

    all_pass = all(c["pass"] for c in checks)
    result = {
        "checks": checks,
        "summary": {
            "tested_dir": args.tested_dir,
            "reference_dir": args.reference_dir,
            "expected_cases": len(EXPECTED_CASES),
            "agreement_rate": summary_agreement,
            "agreement_threshold": AGREEMENT_THRESHOLD,
            "all_pass": all_pass,
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
