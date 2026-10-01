#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""verify.py — ab3 混合型·两类冲突样例（case15）单条路由校验

从资产根目录运行：python tests/ab/ab3-mixed-priority/treatment/verify.py
重跑 `python package/scripts/route.py --input oracle/inputs/case15.txt` 捕获退出码与输出，
并对照 oracle/out/labels.json 中 case15 的参照判定（template_fill / 0.65）逐项断言。

重点核查（对应任务 rubric）：
  1. method 与参照一致：template_fill（「品牌」所在类优先级高于「海报/一页」所在类）；
  2. reasons 非空且同时披露两类命中：template_fill 的「品牌」与 visual_report 的「海报、一页」；
  3. reasons 明确写出优先级链 template_fill > editable_pptx > visual_report，并给冲突提示/人工复核建议；
  4. confidence ∈ [0,1] 且 ≤0.75（冲突压低置信度，低于单类清晰情形的下限 0.80）；
  5. stdout 恰一行可解析 JSON、退出码 0。
"""
import json
import subprocess
import sys

ROOT = "."
CMD = [sys.executable, "package/scripts/route.py", "--input", "oracle/inputs/case15.txt"]
OUT_RAW = "tests/ab/ab3-mixed-priority/treatment/stdout.raw"

checks = []


def check(name, ok, detail):
    checks.append({"check": name, "passed": bool(ok), "detail": detail})


# 1. 重跑命令，捕获退出码 / stdout / stderr
proc = subprocess.run(CMD, capture_output=True)
stdout_bytes = proc.stdout
stdout_text = stdout_bytes.decode("utf-8")
check("exit_code_0", proc.returncode == 0, "returncode=%d" % proc.returncode)

# 2. stdout 恰一行可解析 JSON（含尾部换行、UTF-8 无 BOM、非 ASCII 原样输出）
lines = stdout_text.splitlines()
check("stdout_one_line", len(lines) == 1 and stdout_text.endswith("\n"),
      "non-blank lines=%d, ends with newline=%s" % (len(lines), stdout_text.endswith("\n")))
check("stdout_no_bom", not stdout_bytes.startswith(b"\xef\xbb\xbf"),
      "first bytes=%r" % stdout_bytes[:3])
check("stdout_utf8_raw_nonascii", "品牌".encode("utf-8") in stdout_bytes and b"\\u" not in stdout_bytes,
      "「品牌」以 UTF-8 原样出现且无 \\u 转义（ensure_ascii=False）")
try:
    payload = json.loads(stdout_text)
    check("stdout_parseable_json", True, "json.loads ok；顶层字段=%r" % sorted(payload.keys()))
except Exception as exc:
    payload = None
    check("stdout_parseable_json", False, repr(exc))
check("stderr_empty", proc.stderr == b"", "stderr bytes=%d" % len(proc.stderr))

# 3. 复现性：重跑一次与本次 stdout 及落盘产物 stdout.raw 逐字节一致
proc2 = subprocess.run(CMD, capture_output=True)
saved = open(OUT_RAW, "rb").read()
check("reproducible_rerun", proc2.stdout == stdout_bytes,
      "两次运行 stdout 均为 %d 字节，逐字节一致=%s" % (len(stdout_bytes), proc2.stdout == stdout_bytes))
check("artifact_matches_rerun", saved == stdout_bytes,
      "stdout.raw（%d 字节）与重跑输出逐字节一致=%s" % (len(saved), saved == stdout_bytes))

if payload is not None:
    # 4. method 与参照判定一致：template_fill（「品牌」类优先级最高）
    check("method_is_template_fill", payload.get("method") == "template_fill",
          "method=%r（参照 oracle case15 = template_fill）" % payload.get("method"))
    check("method_in_contract_enum", payload.get("method") in
          ("editable_pptx", "template_fill", "visual_report"),
          "method 在契约三值枚举内")

    # 5. confidence：数值 ∈ [0,1]，≤0.75（冲突压低），且低于单类清晰情形下限 0.80，
    #    并等于确定性公式 min(0.75, 0.60+0.05×(总命中词数−2))
    conf = payload.get("confidence")
    conf_ok = isinstance(conf, (int, float)) and not isinstance(conf, bool) and 0 <= conf <= 1
    check("confidence_in_0_1", conf_ok, "confidence=%r（%s）" % (conf, type(conf).__name__))
    check("confidence_le_0.75", conf_ok and conf <= 0.75, "confidence=%r <= 0.75（冲突上限）" % conf)
    check("confidence_below_clear_single_category_floor", conf_ok and conf < 0.80,
          "0.65 < 0.80 = SKILL.md §4 R3 单类清晰情形公式下限（0.80+0.05×0）")
    expected_conf = round(min(0.75, 0.60 + 0.05 * (3 - 2)), 2)  # 总命中词数=3（见 §7 独立复算）
    check("confidence_matches_priority_formula", conf == expected_conf,
          "confidence=%r == min(0.75, 0.60+0.05×(3−2)) = %r" % (conf, expected_conf))

    # 6. reasons 非空，且同时披露两类命中关键词
    reasons = payload.get("reasons")
    reasons_ok = (isinstance(reasons, list) and len(reasons) > 0
                  and all(isinstance(r, str) and r.strip() for r in reasons))
    check("reasons_non_empty_strings", reasons_ok,
          "reasons=%d 条，均非空字符串" % (len(reasons) if isinstance(reasons, list) else -1))
    joined = "".join(reasons) if reasons_ok else ""
    tf_hit_lines = [r for r in (reasons or []) if r.startswith("命中[template_fill")]
    vr_hit_lines = [r for r in (reasons or []) if r.startswith("命中[visual_report")]
    check("reasons_disclose_template_fill_hit_brand",
          len(tf_hit_lines) == 1 and "品牌" in tf_hit_lines[0],
          "template_fill 命中行=%r（含「品牌」=%s）"
          % (tf_hit_lines[0] if tf_hit_lines else None,
             bool(tf_hit_lines) and "品牌" in tf_hit_lines[0]))
    check("reasons_disclose_visual_report_hits",
          len(vr_hit_lines) == 1 and "海报" in vr_hit_lines[0] and "一页" in vr_hit_lines[0],
          "visual_report 命中行=%r（含「海报」「一页」=%s）"
          % (vr_hit_lines[0] if vr_hit_lines else None,
             bool(vr_hit_lines) and "海报" in vr_hit_lines[0] and "一页" in vr_hit_lines[0]))

    # 7. reasons 明确优先级链 + 冲突提示/人工复核建议
    check("reasons_state_priority_chain", "template_fill > editable_pptx > visual_report" in joined,
          "reasons 含完整优先级链「template_fill > editable_pptx > visual_report」")
    check("reasons_state_conflict", ("多类信号" in joined or "冲突" in joined),
          "reasons 含冲突说明表述")
    check("reasons_give_review_advice", ("人工复核" in joined or "确认主用途" in joined),
          "reasons 含人工复核/向用户确认建议")

    # 8. 独立复算关键词匹配（不依赖 route.py 逻辑）：
    #    case15 文本 lower() 后应命中 template_fill{品牌} 与 visual_report{海报,一页}，editable_pptx 零命中
    RULES = [
        ("template_fill", ["模板", "公司vi", "套用", "品牌"]),
        ("editable_pptx", ["数据", "表格", "台账", "月报", "图表", "汇报"]),
        ("visual_report", ["海报", "一页", "信息图", "视觉", "朋友圈", "转发"]),
    ]
    text = open("oracle/inputs/case15.txt", encoding="utf-8-sig").read().strip().lower()
    recomputed = {m: [kw for kw in kws if kw in text] for m, kws in RULES}
    check("independent_recompute_hits",
          recomputed["template_fill"] == ["品牌"]
          and recomputed["visual_report"] == ["海报", "一页"]
          and recomputed["editable_pptx"] == [],
          "独立复算 16 词子串匹配=%r" % recomputed)
    check("reasons_no_fabricated_editable_hits",
          not any(r.startswith("命中[editable_pptx") for r in (reasons or []))
          and "editable_pptx" not in (vr_hit_lines[0] if vr_hit_lines else "")
          and "editable_pptx" not in (tf_hit_lines[0] if tf_hit_lines else ""),
          "case15 无 editable_pptx 关键词命中，reasons 命中行未虚构 editable_pptx 命中"
          "（editable_pptx 仅作为优先级链一环出现，属如实披露）")

# 9. 与 oracle 参照判定对照（oracle/out/labels.json 的 case15：template_fill / 0.65）
oracle = json.load(open("oracle/out/labels.json", encoding="utf-8"))
oracle_c15 = next(e for e in oracle if e["case"] == "case15")
check("oracle_case15_reference_values", oracle_c15["method"] == "template_fill"
      and oracle_c15["confidence"] == 0.65,
      "oracle case15 = %s / %r" % (oracle_c15["method"], oracle_c15["confidence"]))
if payload is not None:
    check("oracle_method_match", payload["method"] == oracle_c15["method"],
          "package=%r oracle=%r" % (payload["method"], oracle_c15["method"]))
    check("oracle_confidence_match", payload["confidence"] == oracle_c15["confidence"],
          "package=%r oracle=%r" % (payload["confidence"], oracle_c15["confidence"]))
    o_joined = "".join(oracle_c15["reasons"])
    check("oracle_reasons_disclose_both_categories",
          "品牌" in o_joined and "海报" in o_joined and "一页" in o_joined,
          "oracle case15 reasons 同样同时披露「品牌」与「海报、一页」两类命中")
    check("oracle_reasons_disclose_priority_and_review",
          "template_fill > editable_pptx > visual_report" in o_joined and "人工复核" in o_joined,
          "oracle case15 reasons 同样写明优先级链与人工复核建议")

# 10. 与 package 自身批量产物 package/out/labels.json 的 case15 一致性
pkg_batch = json.load(open("package/out/labels.json", encoding="utf-8"))
pkg_c15 = next(e for e in pkg_batch if e["case"] == "case15")
if payload is not None:
    check("package_batch_consistent",
          payload["method"] == pkg_c15["method"] and payload["confidence"] == pkg_c15["confidence"],
          "单条路由与 package 批量产物 case15 均为 %s / %r" % (pkg_c15["method"], pkg_c15["confidence"]))

result = {"command": " ".join(CMD), "cwd": "skillfactory/assets/ppt-method-router/",
          "stdout": json.loads(stdout_text) if payload is not None else stdout_text,
          "oracle_case15": oracle_c15, "checks": checks,
          "all_passed": all(c["passed"] for c in checks)}
with open("tests/ab/ab3-mixed-priority/treatment/verify_result.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print(json.dumps(result, ensure_ascii=False, indent=2))
sys.exit(0 if result["all_passed"] else 1)
