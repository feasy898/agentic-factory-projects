#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对 case15 路由输出做 rubric 逐项核验（baseline 自检）。

运行：python selftest/verify_case15.py
依赖产物：selftest/runs/{case15,clear-visual-report}.stdout.txt 与 case15.exit.txt
"""
import json
import sys

RUNS = "selftest/runs"


def load(name):
    with open("{}/{}.stdout.txt".format(RUNS, name), encoding="utf-8") as f:
        return f.read()


def main():
    checks = []

    def check(name, ok, detail):
        checks.append((name, ok, detail))

    # ---- 读取被测产物 ----
    with open("{}/case15.exit.txt".format(RUNS), encoding="utf-8") as f:
        exit_txt = f.read().strip()
    exit_code = int(exit_txt.split("=", 1)[1])
    stdout = load("case15")

    # 1. stdout 恰为一行可解析 JSON
    lines = stdout.splitlines()
    check("stdout 恰为一行", len(lines) == 1, "行数={}".format(len(lines)))
    try:
        obj = json.loads(stdout)
        check("stdout 可解析为 JSON", True, "keys={}".format(sorted(obj)))
    except Exception as exc:  # noqa: BLE001
        check("stdout 可解析为 JSON", False, repr(exc))
        return report(checks)

    # 2. 退出码 0
    check("退出码为 0", exit_code == 0, "EXIT_CODE={}".format(exit_code))

    # 3. method 与参照判定一致（参照：template_fill / 0.65）
    check("method == template_fill（与参照一致）",
          obj.get("method") == "template_fill",
          "method={!r}".format(obj.get("method")))

    # 4. confidence 为 0..1 数值，≤0.75，且低于清晰单类情形
    conf = obj.get("confidence")
    conf_ok = isinstance(conf, (int, float)) and not isinstance(conf, bool) and 0.0 <= conf <= 1.0
    check("confidence 为 0..1 数值", conf_ok, "confidence={!r}".format(conf))
    check("confidence ≤ 0.75（冲突压低）", conf_ok and conf <= 0.75,
          "confidence={!r}".format(conf))
    clear_obj = json.loads(load("clear-visual-report"))
    check("低于同类别无冲突清晰情形({})".format(clear_obj.get("confidence")),
          conf_ok and conf < clear_obj.get("confidence"),
          "conflict={!r} < clear={!r}".format(conf, clear_obj.get("confidence")))
    check("与参照置信度 0.65 一致", conf_ok and abs(conf - 0.65) < 1e-9,
          "confidence={!r}".format(conf))

    # 5. reasons 非空且完整披露两类命中
    reasons = obj.get("reasons")
    check("reasons 非空", isinstance(reasons, list) and len(reasons) > 0,
          "len={}".format(len(reasons) if isinstance(reasons, list) else "N/A"))
    joined = "\n".join(reasons) if isinstance(reasons, list) else str(reasons)
    check("披露 template_fill 命中「品牌」",
          "template_fill" in joined and "品牌" in joined, joined.splitlines()[:1])
    check("披露 visual_report 命中「海报」「一页」",
          "visual_report" in joined and "海报" in joined and "一页" in joined,
          [ln for ln in joined.splitlines() if "visual_report" in ln][:1])

    # 6. reasons 说明优先级裁定 + 冲突提示/人工复核建议
    check("说明优先级 template_fill > editable_pptx > visual_report",
          "template_fill > editable_pptx > visual_report" in joined,
          [ln for ln in joined.splitlines() if "优先级" in ln][:1])
    check("含冲突提示或人工复核建议",
          ("冲突" in joined) and ("人工复核" in joined or "复核" in joined),
          [ln for ln in joined.splitlines() if "冲突" in ln or "复核" in ln][:2])

    return report(checks)


def report(checks):
    failed = 0
    for name, ok, detail in checks:
        print("[{}] {} | {}".format("PASS" if ok else "FAIL", name, detail))
        if not ok:
            failed += 1
    print("TOTAL={} FAILED={}".format(len(checks), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
