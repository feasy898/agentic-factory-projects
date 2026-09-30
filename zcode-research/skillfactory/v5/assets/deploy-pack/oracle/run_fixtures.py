#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_fixtures.py — deploy-pack oracle 全量 fixtures 实跑入口

fixtures（oracle/fixtures/，静态文件）:
    services-canonical.txt   asr,minutes,todo → 生成 + 校验全过（exit 0，C1-C7 除 C5 全 PASS）
    services-subset.txt      asr,todo         → 子集生成 + 校验全过（C5 SKIP，exit 0）
    services-invalid.txt     asr,wat          → 生成器拒绝（exit 2，且不建输出目录）
    red-bad-yaml/            compose YAML 破损           → 校验器 exit 1（C1 FAIL）
    red-missing-service/     合法 2 服务包（缺 todo）     → 校验器 exit 1（C2 FAIL）
    red-env-drift/           .env.example 缺 TODO_PORT    → 校验器 exit 1（C3 FAIL）
    red-hardcoded-secret/    compose 内嵌假密钥字面量      → 校验器 exit 1（C4 FAIL）

产物（oracle/out/）:
    pack-<tag>/  生成器三份产物；pack-<tag>-validate.json 校验报告；
    red/<name>-report.json 残缺包被判 FAIL 的报告；fixtures-run.json 本入口汇总
退出码: 0 = 全部 fixtures 符合预期；1 = 有不符
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures"
OUT = HERE / "out"
GEN = HERE / "gen_deploy.py"
VAL = HERE / "validate.py"
ASSET = "skillfactory/v5/assets/deploy-pack/oracle"


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def main() -> int:
    t0 = time.time()
    entries = []

    # ---- 正例：services-*.txt（invalid 为生成器拒绝用例）----
    for f in sorted(FIX.glob("services-*.txt")):
        tag = f.stem[len("services-"):]
        svc = f.read_text(encoding="utf-8").strip()
        pack_dir = OUT / ("pack-" + tag)
        if pack_dir.exists():
            shutil.rmtree(pack_dir)
        if tag == "invalid":
            r = run([sys.executable, str(GEN), "--services", svc, "--out", str(pack_dir)])
            ok = (r.returncode == 2) and (not pack_dir.exists())
            entries.append({
                "fixture": f.name, "kind": "gen-reject", "services": svc,
                "command": "gen_deploy.py --services %s --out %s" % (svc, pack_dir.name),
                "expected": "gen exit=2 且不建目录",
                "observed": "gen exit=%d; 目录存在=%s; stderr=%s"
                            % (r.returncode, pack_dir.exists(), r.stderr.strip()[:120]),
                "verdict": "OK" if ok else "MISMATCH",
            })
            print("[%s] %-24s %s" % ("OK" if ok else "XX", f.name, entries[-1]["observed"]))
        else:
            r1 = run([sys.executable, str(GEN), "--services", svc, "--out", str(pack_dir)])
            rep = OUT / ("pack-%s-validate.json" % tag)
            r2 = run([sys.executable, str(VAL), "--pack", str(pack_dir),
                      "--services", svc, "--out", str(rep)])
            verdict_json = ""
            if rep.is_file():
                try:
                    verdict_json = json.loads(rep.read_text(encoding="utf-8")).get("verdict", "")
                except Exception:
                    verdict_json = "<报告解析失败>"
            ok = (r1.returncode == 0) and (r2.returncode == 0)
            entries.append({
                "fixture": f.name, "kind": "positive", "services": svc,
                "command": "gen_deploy.py --services %s --out %s && validate.py --pack %s --services %s"
                           % (svc, pack_dir.name, pack_dir.name, svc),
                "expected": "gen exit=0; validate exit=0 (ALL GREEN)",
                "observed": "gen exit=%d; validate exit=%d; verdict=%s"
                            % (r1.returncode, r2.returncode, verdict_json),
                "verdict": "OK" if ok else "MISMATCH",
            })
            print("[%s] %-24s %s" % ("OK" if ok else "XX", f.name, entries[-1]["observed"]))

    # ---- 反例：red-* 残缺包，校验器必须判 FAIL（exit 1）----
    red_dir = OUT / "red"
    red_dir.mkdir(parents=True, exist_ok=True)
    for d in sorted(p for p in FIX.glob("red-*") if p.is_dir()):
        rep = red_dir / (d.name + "-report.json")
        r = run([sys.executable, str(VAL), "--pack", str(d), "--out", str(rep)])
        fails = []
        if rep.is_file():
            rep_data = json.loads(rep.read_text(encoding="utf-8"))
            fails = [c["name"] for c in rep_data.get("checks", []) if c["status"] == "FAIL"]
        ok = (r.returncode == 1) and rep.is_file()
        entries.append({
            "fixture": d.name + "/", "kind": "red-pack", "services": "默认三服务",
            "command": "validate.py --pack %s --out %s" % (d.name, rep.relative_to(HERE)),
            "expected": "validate exit=1（判为残缺包）",
            "observed": "validate exit=%d; FAIL 项=%s" % (r.returncode, fails),
            "verdict": "OK" if ok else "MISMATCH",
        })
        print("[%s] %-24s %s" % ("OK" if ok else "XX", d.name, entries[-1]["observed"]))

    n_ok = sum(1 for e in entries if e["verdict"] == "OK")
    summary = {
        "tool": "run_fixtures.py",
        "asset": ASSET,
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "duration_s": round(time.time() - t0, 2),
        "total": len(entries),
        "passed": n_ok,
        "failed": len(entries) - n_ok,
        "verdict": "ALL FIXTURES AS EXPECTED" if n_ok == len(entries) else "HAS MISMATCH",
        "entries": entries,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "fixtures-run.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    print("[SUM] fixtures %d/%d 符合预期 — %s; 汇总: %s"
          % (n_ok, len(entries), summary["verdict"], OUT / "fixtures-run.json"))
    return 0 if n_ok == len(entries) else 1


if __name__ == "__main__":
    sys.exit(main())
