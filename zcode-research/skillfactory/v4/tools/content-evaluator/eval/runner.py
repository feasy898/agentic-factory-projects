#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval/runner.py — content-evaluator 资产确定性评测器（机器可判，无随机/无网络）

用法：
    python eval/runner.py [<被测产物根> <参照产物根>]
  - 两参数：被测产物根在前，参照（oracle）产物根在后。
  - 零参数：两者均取内置缺省 <本文件>/../oracle/out（自校验：应全过 exit 0）。
  - 其它参数个数：用法错误，exit 2（信息走 stderr）。

产物根约定（与 spec.md §5 一致）：目录下含四个样本子目录
    good_dy/  good_xhs/  bad_xhs/  bad_wx/
每个子目录含 content-evaluator 产出的 report.json 与 REPORT.md。

固定 6 项检查，全部通过 exit 0 并打印 JSON；任一失败 exit 1：
  1) good_fixtures_all_pass     good_dy 与 good_xhs 的 report.json 结构合法且 9 项全 pass
  2) bad_xhs_expected_fails     bad_xhs 的 title_length/emoji_density/tag_count/
                                banned_words/structure_cta 五项均 FAIL
  3) bad_wx_expected_fails      bad_wx 的 paragraph_max/banned_words/structure_cta 均 FAIL，
                                且 emoji_density 为 pass=true + warning=true（软上限警告路径）
  4) score_recompute            四样本 checks 恰为冻结 9 项且顺序一致；score/summary 与逐项复算一致
                                （总分 = 通过项/应检项，ratio=round(p/a,4)，warn=pass 且 warning）
  5) report_md_consistency      四样本 REPORT.md 三个锚点（总分 p/a、汇总四元组、逐检查行
                                ✅/❌/⚠️ 标记）与 report.json 逐一一致
  6) oracle_agreement_90pct     与参照产物逐检查项（4 样本 × 9 检查名 = 36 对 pass 布尔）
                                一致率 ≥ 0.90；参照产物缺失/损坏直接判败

输出：stdout 打印 {"ok": bool, "summary": {total, pass, fail, tested_root, reference_root},
"checks": [{name, pass, detail}]}；无时间戳，同输入同输出（确定性）。
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.normpath(os.path.join(HERE, "..", "oracle", "out"))

SAMPLES = ("good_dy", "good_xhs", "bad_xhs", "bad_wx")
CHECK_NAMES = ("title_length", "emoji_density", "body_length", "paragraph_max",
               "tag_count", "banned_words", "structure_hook", "structure_cta",
               "structure_para")
BAD_XHS_FAILS = ("title_length", "emoji_density", "tag_count",
                 "banned_words", "structure_cta")
BAD_WX_FAILS = ("paragraph_max", "banned_words", "structure_cta")
BAD_WX_WARN = "emoji_density"
AGREEMENT_MIN = 0.90

SCORE_RE = re.compile(r"总分：(\d+/\d+)")
SUMMARY_RE = re.compile(r"应检 (\d+) 项，通过 (\d+) / 失败 (\d+) / 警告 (\d+)")
MARK_PASS, MARK_FAIL, MARK_WARN = "✅ PASS", "❌ FAIL", "⚠️ WARN"


def load_report(root, sample):
    """读 <root>/<sample>/report.json 并做结构校验。

    返回 (report | None, 错误说明 | None)。结构要求：顶层 JSON 对象；checks 为
    非空数组；元素含 name(str) / pass(bool) / detail(str)，warning 可缺省
    （出现时须为 bool，缺省按 false 计警告口径）。
    """
    path = os.path.join(root, sample, "report.json")
    if not os.path.isfile(path):
        return None, "缺少 %s" % path
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:  # noqa: BLE001
        return None, "report.json 无法解析: %s (%s)" % (path, exc)
    if not isinstance(data, dict):
        return None, "report.json 顶层不是 JSON 对象: %s" % path
    arr = data.get("checks")
    if not isinstance(arr, list) or not arr:
        return None, "report.json 缺非空 checks 数组: %s" % path
    for c in arr:
        if (not isinstance(c, dict)
                or not isinstance(c.get("name"), str)
                or not isinstance(c.get("pass"), bool)
                or not isinstance(c.get("detail"), str)):
            return None, "checks 元素须含 name(str)/pass(bool)/detail(str): %s" % path
        if "warning" in c and not isinstance(c["warning"], bool):
            return None, "checks 元素 warning 须为 bool: %s" % path
    return data, None


def check_pass(report, name):
    """按检查项名取 pass 布尔；该项不存在返回 None。"""
    for c in report["checks"]:
        if c["name"] == name:
            return c["pass"]
    return None


def check_warn(report, name):
    """按检查项名取 warning 布尔（缺省 false）；该项不存在返回 None。"""
    for c in report["checks"]:
        if c["name"] == name:
            return bool(c.get("warning", False))
    return None


def warn_count(report):
    """警告口径：pass=true 且 warning=true 的项数。"""
    return sum(1 for c in report["checks"] if c["pass"] and c.get("warning", False))


def add(checks, name, ok, detail):
    checks.append({"name": name, "pass": bool(ok), "detail": detail})


def main(argv):
    if len(argv) not in (0, 2):
        print("用法：python eval/runner.py [<被测产物根> <参照产物根>]"
              "（缺省两者均为 %s）" % DEFAULT_ROOT, file=sys.stderr)
        return 2
    tested, reference = (argv[0], argv[1]) if argv else (DEFAULT_ROOT, DEFAULT_ROOT)

    checks = []
    reports, errors = {}, {}
    for s in SAMPLES:
        reports[s], errors[s] = load_report(tested, s)

    # 1) 两个好样本全 PASS ----------------------------------------------------
    goods, bads = [], []
    for s in ("good_dy", "good_xhs"):
        rep = reports[s]
        if rep is None:
            bads.append("%s: %s" % (s, errors[s]))
            continue
        total = len(rep["checks"])
        n_ok = sum(1 for c in rep["checks"] if c["pass"])
        failed = [c["name"] for c in rep["checks"] if not c["pass"]]
        (goods if n_ok == total else bads).append(
            "%s %d/%d%s" % (s, n_ok, total,
                            "" if n_ok == total else "（失败: " + ", ".join(failed) + "）"))
    ok = not bads
    detail = ("两好样本均全 PASS: %s" % ", ".join(goods)) if ok else (
        "好样本未全 PASS: %s%s" % (", ".join(goods), ("；问题: " + "; ".join(bads)) if bads else ""))
    add(checks, "good_fixtures_all_pass", ok, detail)

    # 2) bad_xhs 命中基线违规集（5 项均 FAIL） ---------------------------------
    rep = reports["bad_xhs"]
    if rep is None:
        ok, detail = False, errors["bad_xhs"]
    else:
        hits = [n for n in BAD_XHS_FAILS if check_pass(rep, n) is False]
        misses = [n for n in BAD_XHS_FAILS if check_pass(rep, n) is not False]
        ok = len(hits) == len(BAD_XHS_FAILS)
        detail = ("基线违规 5 项均 FAIL: %s" % ", ".join(hits)) if ok else (
            "基线违规未全部命中 FAIL（要求 %s 均为 false）: 命中=[%s] 未命中=[%s]"
            % (", ".join(BAD_XHS_FAILS), ", ".join(hits) or "无", ", ".join(misses) or "无"))
    add(checks, "bad_xhs_expected_fails", ok, detail)

    # 3) bad_wx 命中基线违规集 + emoji 警告路径 ---------------------------------
    rep = reports["bad_wx"]
    if rep is None:
        ok, detail = False, errors["bad_wx"]
    else:
        probs = []
        hits = [n for n in BAD_WX_FAILS if check_pass(rep, n) is False]
        if len(hits) != len(BAD_WX_FAILS):
            probs.append("FAIL 项未全命中（要求 %s 均 false，命中=[%s]）"
                         % (", ".join(BAD_WX_FAILS), ", ".join(hits) or "无"))
        w_pass, w_warn = check_pass(rep, BAD_WX_WARN), check_warn(rep, BAD_WX_WARN)
        if w_pass is not True or w_warn is not True:
            probs.append("%s 应为 pass=true+warning=true，实测 pass=%r warning=%r"
                         % (BAD_WX_WARN, w_pass, w_warn))
        ok = not probs
        detail = ("3 项 FAIL（%s）且 %s 为 WARN（pass+warning，不计失败）"
                  % (", ".join(hits), BAD_WX_WARN)) if ok else "；".join(probs)
    add(checks, "bad_wx_expected_fails", ok, detail)

    # 4) 总分 = 通过项/应检项（程序复算一致） ------------------------------------
    mismatch = []
    for s in SAMPLES:
        rep = reports[s]
        if rep is None:
            mismatch.append("%s: %s" % (s, errors[s]))
            continue
        arr = rep["checks"]
        names = [c["name"] for c in arr]
        if names != list(CHECK_NAMES):
            mismatch.append("%s: checks 应恰为冻结 9 项且顺序一致，实测 %s"
                            % (s, names))
            continue
        passed = sum(1 for c in arr if c["pass"])
        applied = len(arr)
        warns = warn_count(rep)
        score = rep.get("score")
        summary = rep.get("summary")
        if not isinstance(score, dict) or not isinstance(summary, dict):
            mismatch.append("%s: 缺 score/summary 对象" % s)
            continue
        ratio = round(passed / applied, 4) if applied else 0.0
        probs = []
        if score.get("passed") != passed or score.get("applied") != applied:
            probs.append("score.passed/applied=%r/%r 应为 %d/%d"
                         % (score.get("passed"), score.get("applied"), passed, applied))
        if score.get("text") != "%d/%d" % (passed, applied):
            probs.append("score.text=%r 应为 %r" % (score.get("text"), "%d/%d" % (passed, applied)))
        got_ratio = score.get("ratio")
        if not isinstance(got_ratio, (int, float)) or abs(got_ratio - ratio) > 1e-9:
            probs.append("score.ratio=%r 应为 %r" % (got_ratio, ratio))
        if (summary.get("applied") != applied or summary.get("pass") != passed
                or summary.get("fail") != applied - passed or summary.get("warn") != warns):
            probs.append("summary=%r 应为 applied=%d pass=%d fail=%d warn=%d"
                         % (summary, applied, passed, applied - passed, warns))
        if probs:
            mismatch.append("%s: %s" % (s, "；".join(probs)))
    ok = not mismatch
    if ok:
        detail = "四样本总分复算一致（通过/应检）: " + ", ".join(
            "%s=%s" % (s, reports[s]["score"]["text"]) for s in SAMPLES)
    else:
        detail = "总分/汇总复算不一致: " + "; ".join(mismatch)
    add(checks, "score_recompute", ok, detail)

    # 5) REPORT.md 与 report.json 一致 ------------------------------------------
    mismatch = []
    for s in SAMPLES:
        rep = reports[s]
        if rep is None:
            mismatch.append("%s: %s" % (s, errors[s]))
            continue
        path = os.path.join(tested, s, "REPORT.md")
        if not os.path.isfile(path):
            mismatch.append("%s: 缺少 %s" % (s, path))
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as exc:  # noqa: BLE001
            mismatch.append("%s: REPORT.md 无法读取 (%s)" % (s, exc))
            continue
        probs = []
        m = SCORE_RE.search(text)
        if not m:
            probs.append("未找到「总分：p/a」锚点")
        elif m.group(1) != rep["score"]["text"]:
            probs.append("REPORT.md 总分=%s 与 json %s 不符" % (m.group(1), rep["score"]["text"]))
        m = SUMMARY_RE.search(text)
        sm = rep["summary"]
        if not m:
            probs.append("未找到「应检 N 项，通过 P / 失败 F / 警告 W」锚点")
        elif (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))) != (
                sm.get("applied"), sm.get("pass"), sm.get("fail"), sm.get("warn")):
            probs.append("REPORT.md 汇总=%s 与 json summary=%s 不符"
                         % (m.groups() if m else None, sm))
        for c in rep["checks"]:
            expect = MARK_FAIL if not c["pass"] else (
                MARK_WARN if c.get("warning", False) else MARK_PASS)
            row_re = re.compile(r"^\|\s*`%s`\s*\|\s*(✅ PASS|❌ FAIL|⚠️ WARN)\s*\|"
                                % re.escape(c["name"]), re.M)
            row = row_re.search(text)
            if not row:
                probs.append("检查表缺 %s 行" % c["name"])
            elif row.group(1) != expect:
                probs.append("%s 行标记=%s 与 json（pass=%s, warning=%s，应 %s）不符"
                             % (c["name"], row.group(1), c["pass"],
                                c.get("warning", False), expect))
        if probs:
            mismatch.append("%s: %s" % (s, "；".join(probs)))
    ok = not mismatch
    if ok:
        detail = "四样本 REPORT.md 锚点（总分/汇总/逐检查行标记）均与 report.json 一致"
    else:
        detail = "REPORT.md 与 json 不一致: " + "; ".join(mismatch)
    add(checks, "report_md_consistency", ok, detail)

    # 6) 与参照产物逐检查项一致率 ≥90% -------------------------------------------
    pairs, match, diff, ref_broken = 0, 0, [], []
    for s in SAMPLES:
        ref, err = load_report(reference, s)
        if ref is None:
            ref_broken.append("%s: %s" % (s, err))
            pairs += len(CHECK_NAMES)
            diff.extend("%s/%s" % (s, n) for n in CHECK_NAMES)
            continue
        tested_pass = ({c["name"]: c["pass"] for c in reports[s]["checks"]}
                       if reports[s] is not None else {})
        for name in CHECK_NAMES:
            pairs += 1
            tp = tested_pass.get(name)
            rp = check_pass(ref, name)
            if tp is not None and rp is not None and tp == rp:
                match += 1
            else:
                diff.append("%s/%s(被测=%s,参照=%s)" % (s, name, tp, rp))
    ratio = (match / pairs) if pairs else 0.0
    ok = pairs > 0 and ratio >= AGREEMENT_MIN and not ref_broken
    detail = "逐检查项一致 %d/%d（%.1f%%，阈值 %.0f%%）" % (
        match, pairs, ratio * 100, AGREEMENT_MIN * 100)
    if diff:
        detail += "，不一致: " + ", ".join(diff)
    if ref_broken:
        detail += "；参照产物缺失/损坏: " + "; ".join(ref_broken)
    add(checks, "oracle_agreement_90pct", ok, detail)

    n_ok = sum(1 for c in checks if c["pass"])
    result = {
        "ok": n_ok == len(checks),
        "summary": {
            "total": len(checks),
            "pass": n_ok,
            "fail": len(checks) - n_ok,
            "tested_root": os.path.abspath(tested),
            "reference_root": os.path.abspath(reference),
        },
        "checks": checks,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
