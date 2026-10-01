#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""verify.py — ab2 无信号兜底样例（case11）单条路由校验（treatment 臂，2026-09-29 重跑）

从资产根目录运行：python tests/ab/ab2-ambiguous-fallback/treatment/verify.py
重跑 `python package/scripts/route.py --input oracle/inputs/case11.txt` 共 4 次，
捕获退出码与原始字节输出，逐项断言 rubric：
  1) method 与参照判定一致：editable_pptx（兜底裁定）；
  2) reasons 非空，明确说明「未命中任何类别关键词/无信号」与兜底默认，未编造命中词；
  3) confidence ∈ [0,1] 且 ≤0.6（明显低于有明确信号命中的情形）；
  4) 未把「产品介绍」「团队情况」等普通词误报为任何类别关键词的命中；
  5) stdout 恰一行可解析 JSON，退出码 0。

产物（全部写入本 treatment 目录）：
  stdout.raw / stderr.txt           第 1 次运行的原始字节
  runs/run{1..4}.stdout/stderr.txt  4 次运行的原始字节
  verify_result.json                逐项检查结果
  verify-output.txt                 本脚本人读输出

所有路径一律由本文件位置向上推导资产根目录后做绝对路径拼接（os.path.normpath），
不出现相对跳转片段；写入仅限本 treatment 目录。
"""
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# treatment → ab2-ambiguous-fallback → ab → tests → ppt-method-router（资产根）
ASSET_ROOT = os.path.normpath(os.path.join(
    HERE, os.pardir, os.pardir, os.pardir, os.pardir))
RUNS_DIR = os.path.join(HERE, "runs")
ROUTE = os.path.join(ASSET_ROOT, "package", "scripts", "route.py")
INPUT = os.path.join(ASSET_ROOT, "oracle", "inputs", "case11.txt")
ORACLE_LABELS = os.path.join(ASSET_ROOT, "oracle", "out", "labels.json")
PKG_LABELS = os.path.join(ASSET_ROOT, "package", "out", "labels.json")
CMD = [sys.executable, ROUTE, "--input", INPUT]
RUN_KWARGS = {"cwd": ASSET_ROOT, "capture_output": True}

checks = []


def check(name, ok, detail):
    checks.append({"check": name, "passed": bool(ok), "detail": detail})


def read_labels(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------- 1. 重跑 4 次，捕获退出码 / stdout / stderr 原始字节 ----------
os.makedirs(RUNS_DIR, exist_ok=True)
procs = []
for i in range(1, 5):
    p = subprocess.run(CMD, **RUN_KWARGS)
    procs.append(p)
    with open(os.path.join(RUNS_DIR, "run%d.stdout.txt" % i), "wb") as f:
        f.write(p.stdout)
    with open(os.path.join(RUNS_DIR, "run%d.stderr.txt" % i), "wb") as f:
        f.write(p.stderr)

proc = procs[0]
with open(os.path.join(HERE, "stdout.raw"), "wb") as f:
    f.write(proc.stdout)
with open(os.path.join(HERE, "stderr.txt"), "wb") as f:
    f.write(proc.stderr)

stdout_text = proc.stdout.decode("utf-8")
check("exit_code_0", proc.returncode == 0 and all(p.returncode == 0 for p in procs),
      "run1 returncode=%d（run2-4 亦全为 0）" % proc.returncode)

# ---------- 2. stdout 恰一行可解析 JSON ----------
lines = stdout_text.splitlines()
check("stdout_one_line", len(lines) == 1 and proc.stdout.endswith(b"\n"),
      "行数=%d，以恰一个 LF 结尾=%s，stdout 字节数=%d"
      % (len(lines), proc.stdout.endswith(b"\n"), len(proc.stdout)))
try:
    payload = json.loads(stdout_text)
    check("stdout_parseable_json", True, "json.loads ok")
except Exception as exc:
    payload = None
    check("stdout_parseable_json", False, repr(exc))

# 逐字节重建：stdout 应恰为单行 JSON + 恰一个行终止符（Windows 管道下 print 行尾为 os.linesep="\r\n"，
# 亦接受 "\n"），正文须与 json.dumps(payload, ensure_ascii=False) 逐字节一致，无任何隐藏额外输出
if payload is not None:
    body = proc.stdout.rstrip(b"\r\n")
    term = proc.stdout[len(body):]
    rebuilt_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    exact = (body == rebuilt_body and term in (b"\n", b"\r\n")
             and proc.stdout.count(b"\n") == 1)
    check("stdout_is_exactly_one_json_line", exact,
          "正文与单行 JSON 逐字节一致=%s，行终止符=%r（Windows os.linesep），"
          "恰 1 个行终止符=%s" % (body == rebuilt_body, term, proc.stdout.count(b"\n") == 1))
check("stderr_empty", proc.stderr == b"", "run1 stderr 字节数=%d" % len(proc.stderr))

# ---------- 3. 兜底稳定性：4 次运行 stdout 逐字节一致（SKILL.md §4：同一输入重复运行逐字节一致） ----------
digests = [hashlib.sha256(p.stdout).hexdigest() for p in procs]
stable = len(set(digests)) == 1 and all(p.returncode == 0 for p in procs)
check("fallback_stable_across_reruns", stable,
      "4 次运行 stdout sha256 全部一致: %s" % digests[0])

if payload is not None:
    # ---------- 4. method 与参照判定一致：editable_pptx（兜底裁定） ----------
    check("method_is_editable_pptx", payload.get("method") == "editable_pptx",
          "method=%r" % payload.get("method"))
    check("method_in_enum",
          payload.get("method") in ("editable_pptx", "template_fill", "visual_report"),
          "method 属于三值枚举")

    # ---------- 5. confidence ∈ [0,1] 且 ≤0.6；且恰为 R5 兜底值 0.4 ----------
    conf = payload.get("confidence")
    conf_ok = isinstance(conf, (int, float)) and not isinstance(conf, bool) and 0 <= conf <= 1
    check("confidence_in_0_1", conf_ok, "confidence=%r（数值型，在 [0,1] 内）" % conf)
    check("confidence_le_0.6", conf_ok and conf <= 0.6,
          "confidence=%r <= 0.6（rubric 低置信线）" % conf)
    # 对照：route.py R3 单类命中公式下限 = 0.80+0.05×(1−1) = 0.80（route.py:81）→ 兜底 0.4 明显更低
    check("confidence_below_single_hit_floor", conf_ok and conf < 0.80,
          "0.4 < R3 单类命中下限 0.80（package/scripts/route.py:81）")
    check("confidence_equals_r5_fallback", conf_ok and conf == 0.4,
          "confidence 恰为 R5 无信号兜底固定值 0.4（SKILL.md §4 规则3 / route.py:38）")

    # ---------- 6. reasons 非空，如实说明无信号 + 兜底默认，未编造命中词 ----------
    reasons = payload.get("reasons")
    reasons_nonempty = (isinstance(reasons, list) and len(reasons) > 0
                        and all(isinstance(r, str) and r.strip() for r in reasons))
    check("reasons_non_empty_strings", reasons_nonempty,
          "reasons=%d 条且均为非空字符串"
          % (len(reasons) if isinstance(reasons, list) else -1))
    joined = "".join(reasons) if reasons_nonempty else ""
    check("reasons_state_no_signal", ("未命中" in joined and "无信号" in joined),
          "reasons 含「未命中任何类别关键词」「无信号」表述")
    check("reasons_state_fallback", ("兜底" in joined and "editable_pptx" in joined),
          "reasons 含「兜底默认裁定 editable_pptx」表述")
    # 未编造命中：不存在「命中[类别(标签)]关键词：…」样式的命中行（该格式仅在有命中时出现，route.py:75）
    fab_lines = [r for r in (reasons or []) if re.search(r"命中\[.+?\].*关键词[：:]", r)]
    check("reasons_no_fabricated_hit_lines", fab_lines == [],
          "reasons 中不存在「命中[类别]关键词：…」行（route.py:75 格式）")

    # ---------- 7. 独立复算：case11 文本对 16 个信号词均无子串命中 ----------
    # 硬编码表与 route.py 实现表（RULES，route.py:28-35）交叉核对，保证复算用的是同一张表
    sys.path.insert(0, os.path.join(ASSET_ROOT, "package", "scripts"))
    import route as route_mod  # noqa: E402
    RULES = {
        "template_fill": ["模板", "公司vi", "套用", "品牌"],
        "editable_pptx": ["数据", "表格", "台账", "月报", "图表", "汇报"],
        "visual_report": ["海报", "一页", "信息图", "视觉", "朋友圈", "转发"],
    }
    impl_rules = {m: kws for m, _, kws in route_mod.RULES}
    table_identical = impl_rules == RULES
    check("keyword_table_matches_implementation", table_identical,
          "独立复算所用 16 词表与 route.py:28-35 的 RULES 完全一致=%s" % table_identical)

    with open(INPUT, encoding="utf-8-sig") as f:
        text = f.read().strip().lower()
    actual_hits = [(m, kw) for m, kws in RULES.items() for kw in kws if kw in text]
    check("independent_recompute_zero_hits", actual_hits == [],
          "对 case11 文本独立复算 16 个信号词子串匹配，命中=%r" % actual_hits)

    # ---------- 8. 普通词（产品介绍/团队情况等）不是关键词，也未在 reasons 中被报为命中 ----------
    plain_words = ["产品介绍", "团队情况", "产品", "团队", "介绍", "情况", "看着办", "内容"]
    all_keywords = [kw for kws in RULES.values() for kw in kws]
    leaked = [w for w in plain_words if w in all_keywords]
    claimed = [w for w in plain_words
               if any(re.search(r"命中\[.+?\].*关键词[：:].*%s" % re.escape(w), r)
                      for r in (reasons or []))]
    check("plain_words_not_keywords", leaked == [],
          "「产品介绍/团队情况」等普通词均不在 route.py 关键词表内（route.py:30-34），误入=%r" % leaked)
    check("plain_words_not_claimed_as_hits", claimed == [],
          "reasons 未把普通词报为任何类别关键词的命中，误报=%r" % claimed)

# ---------- 9. 与 oracle 参照判定对照（oracle/out/labels.json 的 case11） ----------
oracle_c11 = next(e for e in read_labels(ORACLE_LABELS) if e["case"] == "case11")
if payload is not None:
    check("oracle_method_match", payload["method"] == oracle_c11["method"],
          "package=%r oracle=%r（oracle/out/labels.json case11）"
          % (payload["method"], oracle_c11["method"]))
    check("oracle_confidence_match", payload["confidence"] == oracle_c11["confidence"],
          "package=%r oracle=%r" % (payload["confidence"], oracle_c11["confidence"]))
    check("oracle_reasons_semantics",
          ("未命中" in "".join(oracle_c11["reasons"]) and "兜底" in "".join(oracle_c11["reasons"])),
          "oracle case11 reasons 同样写明无信号与兜底")

# ---------- 10. 与 package 自身批量产物 package/out/labels.json 的 case11 一致性 ----------
pkg_c11 = next(e for e in read_labels(PKG_LABELS) if e["case"] == "case11")
if payload is not None:
    check("package_batch_consistent",
          payload["method"] == pkg_c11["method"] and payload["confidence"] == pkg_c11["confidence"],
          "单条路由与 package 批量产物 case11 均为 %s / %r"
          % (pkg_c11["method"], pkg_c11["confidence"]))

# ---------- 汇总落盘 ----------
result = {"command": "%s %s --input %s" % (os.path.basename(sys.executable),
                                           os.path.relpath(ROUTE, ASSET_ROOT),
                                           os.path.relpath(INPUT, ASSET_ROOT)),
          "cwd": "skillfactory/assets/ppt-method-router/",
          "runs": 4,
          "stdout": json.loads(stdout_text) if payload is not None else stdout_text,
          "oracle_case11": oracle_c11, "checks": checks,
          "all_passed": all(c["passed"] for c in checks)}
with open(os.path.join(HERE, "verify_result.json"), "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

report_lines = ["command: %s --input %s（cwd=资产根）"
                % (os.path.relpath(ROUTE, ASSET_ROOT), os.path.relpath(INPUT, ASSET_ROOT)),
                "stdout(1 行): %s" % stdout_text.strip(),
                "exit=%d stderr_bytes=%d" % (proc.returncode, len(proc.stderr)),
                "checks: %d/%d passed" % (sum(c["passed"] for c in checks), len(checks)), ""]
for c in checks:
    report_lines.append("[%s] %s — %s" % ("PASS" if c["passed"] else "FAIL",
                                          c["check"], c["detail"]))
report_lines += ["", "all_passed: %s" % result["all_passed"]]
with open(os.path.join(HERE, "verify-output.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(report_lines) + "\n")

print("\n".join(report_lines))
sys.exit(0 if result["all_passed"] else 1)
