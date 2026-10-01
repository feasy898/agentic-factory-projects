#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_stage_and_eval.py — 组装 runner 所需的 <case>/ 布局并调用技能自带验收 runner（ab-003 / case2）。

1) _staging/case2 = 本 treatment 产物原样复制（纪要.docx + summary.json）；
2) _staging/case1、case3、case4 用同一契约入口脚本生成（同一实现，仅供 runner 全量评测）；
3) 以子进程运行 eval/runner.py <staging> oracle/out，透传退出码；
4) 比对 _staging/case2 与 treatment 产物：summary.json 字节一致、docx 文本级一致。
"""
import filecmp
import os
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ASSET = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
TREAT = os.path.dirname(os.path.abspath(__file__))
STAGE = os.path.join(TREAT, "_staging")
SCRIPT = os.path.join(ASSET, "package", "scripts", "minutes.py")
RUNNER = os.path.join(ASSET, "eval", "runner.py")

os.makedirs(os.path.join(STAGE, "case2"), exist_ok=True)
for name in ("纪要.docx", "summary.json"):
    shutil.copy2(os.path.join(TREAT, name), os.path.join(STAGE, "case2", name))
for c in (1, 3, 4):
    r = subprocess.run(
        [sys.executable, SCRIPT,
         "--input", os.path.join(ASSET, "oracle", "inputs", "case%d.txt" % c),
         "--outdir", os.path.join(STAGE, "case%d" % c)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ASSET)
    print("case%d generate exit=%d %s" % (c, r.returncode, (r.stderr or "").strip()))

print("--- python eval/runner.py tests/ab/ab-003/treatment/_staging oracle/out ---")
r = subprocess.run([sys.executable, RUNNER, STAGE,
                    os.path.join(ASSET, "oracle", "out")],
                   capture_output=True, text=True, encoding="utf-8",
                   errors="replace", cwd=ASSET)
print(r.stdout)
if r.stderr.strip():
    print("stderr:", r.stderr)
print("runner_exit=%d" % r.returncode)

same_json = filecmp.cmp(os.path.join(TREAT, "summary.json"),
                        os.path.join(STAGE, "case2", "summary.json"), shallow=False)

from docx import Document  # noqa: E402


def docx_text(path):
    d = Document(path)
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts.extend(c.text for c in row.cells)
    return parts


same_docx = (docx_text(os.path.join(TREAT, "纪要.docx"))
             == docx_text(os.path.join(STAGE, "case2", "纪要.docx")))
print("determinism: summary.json byte-identical=%s; 纪要.docx text-identical=%s"
      % (same_json, same_docx))
sys.exit(0 if (r.returncode == 0 and same_json and same_docx) else 1)
