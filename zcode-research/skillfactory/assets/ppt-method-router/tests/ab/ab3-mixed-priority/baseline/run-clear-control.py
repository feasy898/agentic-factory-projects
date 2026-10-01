# -*- coding: utf-8 -*-
"""AB3 baseline control run: execute the REAL package router on a self-written
(non-oracle) clear single-category input, to evidence the rubric dimension
"conflict lowers confidence below the same-category clear case".
All paths are literal; this script never reads package/oracle/spec contents.
"""
import json
import subprocess
import sys

BASE = r"D:\workspace\zcode研究\skillfactory\assets\ppt-method-router\tests\ab\ab3-mixed-priority\baseline"
ROOT = r"D:\workspace\zcode研究\skillfactory\assets\ppt-method-router"
P_CONTROL_IN = BASE + r"\control-clear-template-fill.txt"
P_LOG = BASE + r"\control-clear-run.json"

env = dict()
env["PYTHONIOENCODING"] = "utf-8"
cmd = [sys.executable, "package/scripts/route.py", "--input", "tests/ab/ab3-mixed-priority/baseline/control-clear-template-fill.txt"]
p = subprocess.run(cmd, cwd=ROOT, capture_output=True, env=env)


def decode(b):
    for enc in ("utf-8", "gbk"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", errors="replace")


stdout = decode(p.stdout)
stderr = decode(p.stderr)
log = {"command": "python package/scripts/route.py --input tests/ab/ab3-mixed-priority/baseline/control-clear-template-fill.txt",
       "cwd": ROOT, "exit_code": p.returncode, "stdout": stdout, "stderr": stderr,
       "input_text": "请套用公司品牌模板填充这份红头通知 (self-written clear single-category control, not from oracle)"}
with open(P_LOG, "w", encoding="utf-8") as f:
    json.dump(log, f, ensure_ascii=False, indent=2)
print("EXIT_CODE:", p.returncode)
print("STDOUT:", stdout)
print("STDERR:", stderr)
