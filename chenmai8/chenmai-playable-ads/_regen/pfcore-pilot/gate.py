#!/usr/bin/env python3
"""gate.py — pfcore-pilot 门禁（逐个跑评测项；工作流调用入口）。

用法（仓库根）：python gate.py        # 全 PASS → exit 0；任一 FAIL → exit 1

断言（冻结，SPEC.md §1；样本是规格的一部分，不许为过门禁改样本）：
  1. python -m pfcore validate specs-eval/golden-match3.json          → exit 0
  2. bad 6 件逐个 validate → 各 exit 1，issue 含 $. 字段路径
     （正则 \\$\\.[A-Za-z_][\\w.\\[\\]]*，spec-contract §4），且各自击中原检查项：
     01 schema-required@$.flow；02 I1-pullpin-order@$.game.params.orderSolution[0]；
     03 exit1+路径（schema-maximum 或 I4-duration-max——冻结校验次序下 schema 先行，
        SPEC.md §8.1 登记的契约内部张力，两种实现都算命中）；04 I5-i18n-coverage@$.i18n.strings.ja；
     05 schema-pattern@$.flow.endScreen.landingUrl；06 schema-enum@$.game.template
  3. validate "specs-eval/bad/*.json"（glob 内建展开）→ exit 1 且 6/6 判败
  4. 命令统一 make/validate：校验入口即 `python -m pfcore validate`（项 1–3 实测）；
     `run` 不可用（exit 2，无第三全流水线名）；`make` 占位 exit 2；无子命令 exit 2
  5. glob 无匹配计一条失败（防静默通过）→ exit 1
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYEXE = ROOT / "python" / ".venv" / "Scripts" / "python.exe"
BAD_DIR = ROOT / "specs-eval" / "bad"
PATH_RE = re.compile(r"\$\.[A-Za-z_][\w.\[\]]*")

# bad 样本 → (期望 code 集合, 期望路径前缀或 None)；路径/码依据 spec-contract §2.3/§3 + 冻结样本设计
BAD_EXPECT = {
    "01-missing-field.json": ({"schema-required"}, "$.flow"),
    "02-pullpin-unsolvable.json": ({"I1-pullpin-order"}, "$.game.params.orderSolution[0]"),
    # 03 双保险：schema 亦限 max≤30（先命中 schema-maximum），I4-duration-max 为不变式层同判
    "03-duration-over-budget.json": ({"schema-maximum", "I4-duration-max"}, "$.game.durationBudgetSec.max"),
    "04-missing-locale-strings.json": ({"I5-i18n-coverage"}, "$.i18n.strings.ja"),
    "05-bad-url.json": ({"schema-pattern"}, "$.flow.endScreen.landingUrl"),
    "06-unknown-template.json": ({"schema-enum"}, "$.game.template"),
}

_results: list[tuple[str, bool, str]] = []


def record(item: str, ok: bool, detail: str) -> None:
    _results.append((item, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {item}" + (f" — {detail}" if detail else ""))


def run_pfcore(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"  # REGENERATE §7 坑 9：GBK 控制台中文乱码
    return subprocess.run(
        [str(PYEXE), "-m", "pfcore", *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=180,
    )


def pf_lines(proc: subprocess.CompletedProcess) -> list[dict]:
    """解析 validate 的逐文件 JSON 行（跳过 summary 行与非 JSON 行）。"""
    out = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        obj = json.loads(line)
        if "summary" in obj:
            continue
        out.append(obj)
    return out


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    if not PYEXE.exists():
        print(f"gate: venv python missing: {PYEXE}", file=sys.stderr)
        return 1

    # ---- 项 1：golden → exit 0 -------------------------------------------------
    p = run_pfcore("validate", "specs-eval/golden-match3.json")
    record(
        "1 golden validate → exit 0",
        p.returncode == 0,
        f"exit={p.returncode} stdout={p.stdout.strip()[:120]!r}",
    )

    # ---- 项 2：bad 逐文件 → exit 1 + $. 路径 + 各自击中 -----------------------
    bad_files = sorted(BAD_DIR.glob("*.json")) if BAD_DIR.exists() else []
    if len(bad_files) != 6:
        record("2 bad 逐文件（6 件）", False, f"expected 6 frozen bad samples, found {len(bad_files)}")
    else:
        for bf in bad_files:
            p = run_pfcore("validate", f"specs-eval/bad/{bf.name}")
            reasons = []
            if p.returncode != 1:
                reasons.append(f"exit={p.returncode} (want 1)")
            m = PATH_RE.search(p.stdout)
            if not m:
                reasons.append("no $. field path in output")
            lines = pf_lines(p)
            code = lines[0]["issues"][0]["code"] if lines and lines[0].get("issues") else None
            path = lines[0]["issues"][0]["path"] if lines and lines[0].get("issues") else None
            want_codes, want_path = BAD_EXPECT.get(bf.name, (set(), None))
            if code not in want_codes:
                reasons.append(f"code={code!r} (want one of {sorted(want_codes)})")
            if want_path and (not path or not path.startswith(want_path)):
                reasons.append(f"path={path!r} (want prefix {want_path!r})")
            record(
                f"2 bad/{bf.name} → exit 1 + $.path + 击中 {sorted(want_codes)[0]}",
                not reasons,
                "; ".join(reasons) or f"code={code} path={path}",
            )

    # ---- 项 3：bad glob 一次跑 → exit 1 且 6/6 判败 ---------------------------
    p = run_pfcore("validate", "specs-eval/bad/*.json")
    lines = pf_lines(p)
    failed = sum(1 for ln in lines if not ln.get("ok"))
    ok = p.returncode == 1 and len(lines) == 6 and failed == 6
    record("3 bad glob → exit 1 且 6/6 判败", ok, f"exit={p.returncode} files={len(lines)} failed={failed}")

    # ---- 项 4：命令统一 make/validate；run 不可用；占位 exit 2 ----------------
    p_run = run_pfcore("run", "--spec", "specs-eval/golden-match3.json")
    record("4a 第三名 run 不可用 → exit 2", p_run.returncode == 2, f"exit={p_run.returncode}")
    p_make = run_pfcore("make", "--spec", "specs-eval/golden-match3.json")
    record("4b make 占位 → exit 2", p_make.returncode == 2, f"exit={p_make.returncode}")
    p_none = run_pfcore()
    record("4c 无子命令 → exit 2", p_none.returncode == 2, f"exit={p_none.returncode}")

    # ---- 项 5：glob 无匹配 → 计一条失败 → exit 1 ------------------------------
    p = run_pfcore("validate", "specs-eval/nomatch-*.json")
    record(
        "5 glob 无匹配计失败 → exit 1",
        p.returncode == 1 and "io-not-found" in p.stdout,
        f"exit={p.returncode}",
    )

    # ---- 汇总 -------------------------------------------------------------------
    total = len(_results)
    passed = sum(1 for _, ok, _ in _results if ok)
    verdict = "PASS" if passed == total else "FAIL"
    print(f"\nGATE PF-CORE-PILOT: {verdict} ({passed}/{total})")
    if passed != total:
        for item, ok, detail in _results:
            if not ok:
                print(f"  FAIL {item}: {detail}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
