# -*- coding: utf-8 -*-
"""ab5 arm-a rep1 — 参照实现（oracle）确定性对照组。

协议与被测完全镜像：同一输入（oracle/inputs/会议通知/case1.json），
同一 outdir（_work/oracle-run1）连续跑两遍（第二遍覆盖复写第一遍产物），
每遍跑完立即快照两个产物文件的 md5/size。
两遍中间产物分别留存在 _work/oracle-run2/{fields_run1,docx_run1}.{json,docx} 与
_work/oracle-run2/{fields_run2,docx_run2}.{json,docx}（不触碰 oracle/out 预置基线）。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]      # .../office-templates
W = Path(__file__).resolve().parent
RUN_DIR = W / "oracle-run1"                     # 同一 outdir，两遍覆盖复写
KEEP = W / "oracle-run2"                        # 两遍快照留存
INPUT = ROOT / "oracle/inputs/会议通知/case1.json"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def snap(tag: str) -> dict:
    return {p.name: {"size": p.stat().st_size, "md5": md5(p),
                     "mtime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(p.stat().st_mtime))}
            for p in sorted(RUN_DIR.iterdir())}


def main() -> int:
    KEEP.mkdir(exist_ok=True)
    RUN_DIR.mkdir(exist_ok=True)
    for p in RUN_DIR.iterdir():                 # 保证第一遍是全新写入
        p.unlink()
    results = {}
    for run in (1, 2):
        cmd = [sys.executable, str(ROOT / "oracle/oracle.py"),
               "--template", "会议通知", "--data", str(INPUT), "--outdir", str(RUN_DIR)]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=ROOT)
        if r.returncode != 0 or not (RUN_DIR / "fields.json").is_file():
            print(json.dumps({"run": run, "exit": r.returncode, "stdout": r.stdout,
                              "stderr": r.stderr, "cmd": cmd}, ensure_ascii=False, indent=1))
            raise SystemExit(f"oracle run{run} failed")
        keep = "_run1" if run == 1 else "_run2"
        shutil.copy(RUN_DIR / "fields.json", KEEP / f"fields{keep}.json")
        shutil.copy(RUN_DIR / "文书.docx", KEEP / f"docx{keep}.docx")
        results[f"run{run}"] = {
            "cmd": " ".join(cmd),
            "exit": r.returncode,
            "stdout_tail": r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "",
            "dir_listing": sorted(p.name for p in RUN_DIR.iterdir()),
            "snapshot": snap(f"run{run}"),
        }
    out = W / "step3_oracle_control.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
