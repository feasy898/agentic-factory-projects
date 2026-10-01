#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval/runner.py — healthcheck 资产确定性评测器（机器可判，无随机/无网络）

用法：
    python eval/runner.py [<被测产物根> <参照产物根>]
  - 两参数：被测产物根在前，参照（oracle）产物根在后。
  - 零参数：两者均取内置缺省 <本文件>/../oracle/out（自校验：应全过 exit 0）。
  - 其它参数个数：用法错误，exit 2（信息走 stderr）。

产物根约定（与 spec.md §5 一致）：目录下含三个样本子目录
    meeting-minutes-skill/  broken-skill/  no-eval/
每个子目录含 healthcheck 产出的 report.json 与 REPORT.md。

固定 5 项检查，全部通过 exit 0 并打印 JSON；任一失败 exit 1：
  1) meeting_minutes_all_pass     好样本 report.json 结构合法且所有检查项 pass=true
  2) broken_skill_expected_fails  broken-skill 的 front_matter_fields 与 scripts_syntax 均 FAIL
  3) no_eval_eval_present_fail    no-eval 的 eval_present 为 FAIL
  4) rating_consistency           三样本 REPORT.md「评级：**X**」== 按失败数推导评级
                                  （A=0 失败 / B=1 / C=≥2，规则写死）== report.json rating 字段
  5) oracle_agreement_90pct       与参照产物逐检查项（3 样本 × 5 检查名 = 15 对 pass 布尔）
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

SAMPLES = ("meeting-minutes-skill", "broken-skill", "no-eval")
CHECK_NAMES = ("skill_md_exists", "front_matter_fields", "eval_present",
               "eval_smoke", "scripts_syntax")
AGREEMENT_MIN = 0.90
RATING_RE = re.compile(r"评级：\*\*([ABC])\*\*")


def rate(num_fail):
    """评级规则（与 oracle/healthcheck.py 的 rate() 一致，写死于此）：A=0 失败 / B=1 / C=≥2。"""
    if num_fail == 0:
        return "A"
    if num_fail == 1:
        return "B"
    return "C"


def load_report(root, sample):
    """读 <root>/<sample>/report.json 并做结构校验。

    返回 (report | None, 错误说明 | None)。结构要求：顶层 JSON 对象；checks 为
    非空数组；元素含 name(str) / pass(bool) / detail(str)。
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
    return data, None


def check_pass(report, name):
    """按检查项名取 pass 布尔；该项不存在返回 None。"""
    for c in report["checks"]:
        if c["name"] == name:
            return c["pass"]
    return None


def md_rating(root, sample):
    """从 <root>/<sample>/REPORT.md 解析「评级：**X**」；失败返回 (None, 原因)。"""
    path = os.path.join(root, sample, "REPORT.md")
    if not os.path.isfile(path):
        return None, "缺少 %s" % path
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception as exc:  # noqa: BLE001
        return None, "REPORT.md 无法读取: %s (%s)" % (path, exc)
    m = RATING_RE.search(text)
    if not m:
        return None, "REPORT.md 未找到「评级：**X**」锚点: %s" % path
    return m.group(1), None


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

    # 1) 好样本全 PASS --------------------------------------------------------
    rep = reports["meeting-minutes-skill"]
    if rep is None:
        ok, detail = False, errors["meeting-minutes-skill"]
    else:
        total = len(rep["checks"])
        n_ok = sum(1 for c in rep["checks"] if c["pass"])
        bad = [c["name"] for c in rep["checks"] if not c["pass"]]
        ok = n_ok == total
        detail = "report.json %d/%d 项 pass%s" % (
            n_ok, total, "（全 PASS）" if ok else "，失败项: " + ", ".join(bad))
    add(checks, "meeting_minutes_all_pass", ok, detail)

    # 2) broken-skill 至少 front-matter 与语法两项 FAIL ------------------------
    rep = reports["broken-skill"]
    if rep is None:
        ok, detail = False, errors["broken-skill"]
    else:
        hits, misses = [], []
        for name in ("front_matter_fields", "scripts_syntax"):
            v = check_pass(rep, name)
            (hits if v is False else misses).append(name)
        ok = len(hits) == 2
        detail = ("两项均 FAIL: %s" % ", ".join(hits)) if ok else (
            "未全部命中 FAIL（要求 front_matter_fields 与 scripts_syntax 均为 false）: "
            "命中=[%s] 未命中=[%s]" % (", ".join(hits) or "无", ", ".join(misses) or "无"))
    add(checks, "broken_skill_expected_fails", ok, detail)

    # 3) no-eval 命中 eval 缺失 ------------------------------------------------
    rep = reports["no-eval"]
    if rep is None:
        ok, detail = False, errors["no-eval"]
    else:
        v = check_pass(rep, "eval_present")
        ok = v is False
        detail = ("eval_present=false（命中 eval 缺失红项）" if ok
                  else "eval_present 应为 false，实测 %r" % (v,))
    add(checks, "no_eval_eval_present_fail", ok, detail)

    # 4) REPORT.md 评级与 report.json 一致 --------------------------------------
    mismatch = []
    for s in SAMPLES:
        rep = reports[s]
        if rep is None:
            mismatch.append("%s: %s" % (s, errors[s]))
            continue
        nf = sum(1 for c in rep["checks"] if not c["pass"])
        expect = rate(nf)
        got_md, err = md_rating(tested, s)
        if err:
            mismatch.append("%s: %s" % (s, err))
            continue
        got_json = rep.get("rating")
        if got_md != expect or got_json != expect:
            mismatch.append("%s: 失败数=%d 推导=%s，REPORT.md=%s，report.json.rating=%s"
                            % (s, nf, expect, got_md, got_json))
    ok = not mismatch
    if ok:
        detail = "三样本评级均一致（A=0 失败 / B=1 / C=≥2）: " + ", ".join(
            "%s=%s" % (s, rate(sum(1 for c in reports[s]["checks"] if not c["pass"])))
            for s in SAMPLES)
    else:
        detail = "评级不一致: " + "; ".join(mismatch)
    add(checks, "rating_consistency", ok, detail)

    # 5) 与参照产物逐检查项一致率 ≥90% -------------------------------------------
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
