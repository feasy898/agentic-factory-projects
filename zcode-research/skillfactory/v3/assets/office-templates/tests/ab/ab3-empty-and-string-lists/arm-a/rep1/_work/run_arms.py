#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_arms.py — ab3 列表字段边界：双臂实跑驱动器（arm-a/rep1）。

对两个 case2 输入（周报 / 工作总结）各跑：
  Arm A（被测）: <asset>/package/scripts/gen_doc.py   （SKILL.md §4 命令行）
  Arm B（参照）: <asset>/oracle/oracle.py             （oracle/README.md 运行节）
每臂每模板连跑 2 遍（run1 交付目录 + run2 确定性复跑目录，spec D1）。

记录每次调用的退出码 / stdout / stderr 到 logs/，并检查产物目录恰含
文书.docx + fields.json 两个文件。打印 JSON 摘要。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WORK = Path(__file__).resolve().parent          # .../arm-a/rep1/_work
ASSET = WORK.parents[5]                          # .../office-templates
TEMPLATES = ("周报", "工作总结")
ARMS = {
    "A": (ASSET / "package" / "scripts" / "gen_doc.py"),
    "B": (ASSET / "oracle" / "oracle.py"),
}
RUNS = ("run1", "run2")                          # run2 = 确定性复跑（全新目录）


def run_one(arm: str, script: Path, template: str, run: str) -> dict:
    outdir = WORK / arm / run / template / "case2"
    data = ASSET / "oracle" / "inputs" / template / "case2.json"
    cmd = [sys.executable, str(script), "--template", template,
           "--data", str(data), "--outdir", str(outdir)]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    log = WORK / "logs" / f"{arm}_{template}_{run}.log"
    log.write_text(
        "$ " + " ".join(cmd) + "\n"
        f"--- exit={proc.returncode} ---\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}",
        encoding="utf-8")
    files = sorted(p.name for p in outdir.iterdir()) if outdir.is_dir() else []
    return {
        "arm": arm, "template": template, "run": run,
        "exit": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "outdir_exists": outdir.is_dir(),
        "files": files,
        "files_exact_two": files == ["fields.json", "文书.docx"],
        "log": str(log.relative_to(WORK)),
    }


def main() -> int:
    results = []
    for template in TEMPLATES:
        for arm, script in ARMS.items():
            for run in RUNS:
                results.append(run_one(arm, script, template, run))
    print(json.dumps(results, ensure_ascii=False, indent=1))
    ok = all(r["exit"] == 0 and r["files_exact_two"] for r in results)
    print(f"\nSUMMARY: {len(results)} runs, all exit=0 & exactly-2-files: {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
