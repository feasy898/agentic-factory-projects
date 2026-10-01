# -*- coding: utf-8 -*-
"""step1: 运行被测（package/scripts/gen_doc.py）与参照（oracle/oracle.py）处理两份 case2，记录退出码/stdout/stderr/产物清单。"""
import subprocess, os, sys, json

ROOT = r"D:\workspace\zcode研究\skillfactory\v3\assets\office-templates"
WORK = os.path.join(ROOT, r"tests\ab\ab2-boundary-missing-required\arm-b\rep2\_work")

RUNS = [
    # (tag, script, template)
    ("PKG", r"package\scripts\gen_doc.py", "请示函"),
    ("PKG", r"package\scripts\gen_doc.py", "会议通知"),
    ("ORC", r"oracle\oracle.py", "请示函"),
    ("ORC", r"oracle\oracle.py", "会议通知"),
]
OUTDIR = {"PKG": r"package\out", "ORC": r"oracle\out"}

env = dict(os.environ, PYTHONIOENCODING="utf-8")
lines = []
for tag, script, tpl in RUNS:
    data = os.path.join("oracle", "inputs", tpl, "case2.json")
    outd = os.path.join(OUTDIR[tag], tpl, "case2")
    cmd = [sys.executable, script, "--template", tpl, "--data", data, "--outdir", outd]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, env=env)
    files = sorted(os.listdir(os.path.join(ROOT, outd))) if os.path.isdir(os.path.join(ROOT, outd)) else []
    rec = {
        "tag": tag, "template": tpl, "cmd": " ".join(cmd), "exit": p.returncode,
        "stdout": p.stdout.decode("utf-8", "replace").strip(),
        "stderr": p.stderr.decode("utf-8", "replace").strip(),
        "files": files,
    }
    lines.append(rec)
    print(f"=== {tag} {tpl} exit={p.returncode}")
    print(f"  cmd   : {rec['cmd']}")
    print(f"  stdout: {rec['stdout']}")
    if rec["stderr"]:
        print(f"  stderr: {rec['stderr']}")
    print(f"  files : {rec['files']}")

with open(os.path.join(WORK, "step1_runs.json"), "w", encoding="utf-8") as f:
    json.dump(lines, f, ensure_ascii=False, indent=2)
print("[DONE] 4 runs recorded → step1_runs.json")
