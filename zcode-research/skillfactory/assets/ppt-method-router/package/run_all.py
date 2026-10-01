#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""run_all.py — 批量路由 package/inputs/case1.txt … case20.txt → package/out/labels.json

契约（contract.md §2.2）：
  命令    python run_all.py（无参数，在 package/ 目录下或任意目录均可）
  行为    逐条以 subprocess 调用 scripts/route.py（走命令行契约，而非进程内 import）
  产物    out/labels.json：JSON 数组恰 20 条，顺序 case1 → case20，
          每条 {"case", "method", "confidence", "reasons"}（schema 见 contract.md §2.3）
  退出码  0 成功；1 任一条路由失败（stderr 给出明细）
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROUTE_SCRIPT = os.path.join(HERE, "scripts", "route.py")
INPUT_DIR = os.path.join(HERE, "inputs")
OUTPUT_DIR = os.path.join(HERE, "out")
NUM_CASES = 20


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    entries = []
    for i in range(1, NUM_CASES + 1):
        case = "case%d" % i
        path = os.path.join(INPUT_DIR, case + ".txt")
        proc = subprocess.run(
            [sys.executable, ROUTE_SCRIPT, "--input", path],
            capture_output=True, text=True, encoding="utf-8")
        if proc.returncode != 0:
            print("[%s] route.py 退出码 %d，stderr: %s"
                  % (case, proc.returncode, proc.stderr.strip()), file=sys.stderr)
            return 1
        try:
            obj = json.loads(proc.stdout)
            entry = {
                "case": case,
                "method": obj["method"],
                "confidence": obj["confidence"],
                "reasons": obj["reasons"],
            }
        except (ValueError, KeyError, TypeError) as exc:
            print("[%s] route.py stdout 不是合法结果 JSON（%s）: %r"
                  % (case, exc, proc.stdout[:200]), file=sys.stderr)
            return 1
        entries.append(entry)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, "labels.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("wrote %s (%d entries)" % (out_path, len(entries)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
