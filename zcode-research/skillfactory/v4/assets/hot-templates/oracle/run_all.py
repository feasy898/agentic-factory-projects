#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_all.py — 批量驱动：对 8 份样例逐个以子进程调用 gen.py（真实 CLI 路径）。

用法：python run_all.py
读取 inputs/<platform>/caseN.json 的 platform/topic/points 字段，
调用：python gen.py --platform P --topic T --points <case文件> --outdir out/<platform>/caseN
任一调用退出码非 0 即整体失败。
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.join(HERE, "gen.py")
PLATFORMS = ["dy", "xhs", "wx", "video"]


def main():
    results, failed = [], []
    for platform in PLATFORMS:
        case_dir = os.path.join(HERE, "inputs", platform)
        if not os.path.isdir(case_dir):
            print("[run_all] 错误：缺少样例目录 %s" % case_dir, file=sys.stderr)
            sys.exit(1)
        for name in sorted(os.listdir(case_dir)):
            if not name.endswith(".json"):
                continue
            case_path = os.path.join(case_dir, name)
            with open(case_path, "r", encoding="utf-8-sig") as f:
                case = json.load(f)
            case_id = os.path.splitext(name)[0]
            outdir = os.path.join(HERE, "out", platform, case_id)
            cmd = [sys.executable, GEN,
                   "--platform", case["platform"],
                   "--topic", case["topic"],
                   "--points", case_path,
                   "--outdir", outdir]
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
            status = "OK" if proc.returncode == 0 else "FAIL(%d)" % proc.returncode
            print("[run_all] %s/%s -> %s | %s" % (platform, case_id, status, proc.stdout.strip()))
            if proc.returncode != 0:
                failed.append((platform, case_id, proc.stderr.strip()))
            results.append((platform, case_id, proc.returncode))
    if failed:
        for platform, case_id, err in failed:
            print("[run_all] 失败 %s/%s：%s" % (platform, case_id, err), file=sys.stderr)
        sys.exit(1)
    print("[run_all] 全部 %d 份样例跑通" % len(results))


if __name__ == "__main__":
    main()
