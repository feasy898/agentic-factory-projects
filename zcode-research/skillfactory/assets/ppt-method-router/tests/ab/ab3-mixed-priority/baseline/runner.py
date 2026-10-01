# -*- coding: utf-8 -*-
"""AB3 baseline runner: execute package/scripts/route.py on oracle/inputs/case15.txt
exactly as the ask specifies, capture stdout/stderr/exit code.
NOTE: this runner only EXECUTES the script; it never reads package/, oracle/, spec.md
source or contents (fairness restriction), except a labels-only programmatic comparison
done separately in compare_labels.py which prints booleans only.
"""
import json
import os
import subprocess
import sys

ROOT = r"D:\workspace\zcode研究\skillfactory\assets\ppt-method-router"
OUT_DIR = os.path.join(ROOT, "tests", "ab", "ab3-mixed-priority", "baseline")

env = dict(os.environ)
env["PYTHONIOENCODING"] = "utf-8"

cmd = [sys.executable, "package/scripts/route.py", "--input", "oracle/inputs/case15.txt"]
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

log = {
    "command": "python package/scripts/route.py --input oracle/inputs/case15.txt",
    "cwd": ROOT,
    "argv": cmd,
    "exit_code": p.returncode,
    "stdout_raw": stdout,
    "stderr_raw": stderr,
}
with open(os.path.join(OUT_DIR, "run-log.json"), "w", encoding="utf-8") as f:
    json.dump(log, f, ensure_ascii=False, indent=2)

stdout_stripped = stdout.rstrip("\r\n")
n_lines = len(stdout_stripped.split("\n")) if stdout_stripped.strip() else 0
print("EXIT_CODE:", p.returncode)
print("STDOUT_LINE_COUNT(non-empty):", n_lines)
print("--- STDOUT BEGIN ---")
print(stdout)
print("--- STDOUT END ---")
print("--- STDERR BEGIN ---")
print(stderr)
print("--- STDERR END ---")
