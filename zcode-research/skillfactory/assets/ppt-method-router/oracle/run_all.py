#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""run_all.py — 对 inputs/ 全部样例逐条运行 oracle.py（走命令行契约），
汇总结果到 out/labels.json（数组：[{case, method, confidence, reasons}]）。

用法：python run_all.py
"""

import json
import os
import subprocess
import sys

ALLOWED = {"editable_pptx", "template_fill", "visual_report"}


def case_no(name):
    return int(name.replace("case", "").replace(".txt", ""))


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    inputs_dir = os.path.join(here, "inputs")
    oracle = os.path.join(here, "oracle.py")
    out_dir = os.path.join(here, "out")
    os.makedirs(out_dir, exist_ok=True)

    files = sorted(
        (f for f in os.listdir(inputs_dir)
         if f.startswith("case") and f.endswith(".txt")),
        key=case_no)
    if not files:
        print("inputs/ 下没有样例，请先运行 gen_inputs.py", file=sys.stderr)
        return 2

    labels = []
    for name in files:
        path = os.path.join(inputs_dir, name)
        proc = subprocess.run(
            [sys.executable, oracle, "--input", path],
            capture_output=True, encoding="utf-8")
        if proc.returncode != 0:
            print("oracle.py 运行失败(%s): %s" % (name, proc.stderr),
                  file=sys.stderr)
            return 1
        obj = json.loads(proc.stdout)
        if obj["method"] not in ALLOWED:
            print("非法 method(%s): %s" % (name, obj["method"]), file=sys.stderr)
            return 1
        labels.append({
            "case": name.replace(".txt", ""),
            "method": obj["method"],
            "confidence": obj["confidence"],
            "reasons": obj["reasons"],
        })

    out_path = os.path.join(out_dir, "labels.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(labels, f, ensure_ascii=False, indent=2)
    print("wrote %s (%d entries)" % (out_path, len(labels)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
