#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_tests.py -- oracle self-test for office-guard-hooks.

Runs hooks/validate_output.py and hooks/pii_guard.py as real subprocesses
against every fixture, asserting the Claude Code hook exit code for each
combination, then writes a machine-readable report to out/tests.json.

Exit codes of this script itself:
  0 = every case matched its expectation
  1 = at least one case failed (details in out/tests.json / stderr)

Usage:
    python run_tests.py
"""
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tests"))
import gen_fixtures  # noqa: E402

HOOKS = ROOT / "hooks"
OUT = ROOT / "out"
FIX = gen_fixtures.FIX

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def run_hook(script_name: str, payload: dict):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(HOOKS / script_name)],
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        capture_output=True, timeout=120, env=env,
    )
    return {
        "exit": proc.returncode,
        "stdout": proc.stdout.decode("utf-8", "replace"),
        "stderr": proc.stderr.decode("utf-8", "replace"),
    }


def payload_for(fixture_name, nested=False):
    if fixture_name is None:
        fp = str(FIX / "does-not-exist.txt")
    else:
        fp = str(FIX / fixture_name)
    p = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Write",
        "session_id": "oracle-selftest",
        "cwd": str(ROOT),
    }
    if nested:
        p["tool_input"] = {"file_path": fp}
    else:
        p["file_path"] = fp
    return p


def build_cases():
    """(suite, case_name, fixture, nested_path, expect_exit, stderr_must_contain)"""
    return [
        # ---- validate_output.py ----
        ("validate_output", "good.txt passes", "good.txt", False, 0, ["OK"]),
        ("validate_output", "clean.docx passes (python-docx opens, nested path schema)",
         "clean.docx", True, 0, ["OK"]),
        ("validate_output", "pii.txt passes structure (PII is pii_guard's job)",
         "pii.txt", False, 0, ["OK"]),
        ("validate_output", "bad_empty.txt blocked (0 bytes)",
         "bad_empty.txt", False, 2, ["FAIL", "empty"]),
        ("validate_output", "bad_encoding.txt blocked (not UTF-8)",
         "bad_encoding.txt", False, 2, ["FAIL", "UTF-8"]),
        ("validate_output", "corrupt.docx blocked (python-docx cannot open)",
         "corrupt.docx", False, 2, ["FAIL", "python-docx"]),
        ("validate_output", "missing file blocked", None, False, 2,
         ["FAIL", "does not exist"]),
        # ---- pii_guard.py ----
        ("pii_guard", "pii.txt blocked with line numbers 2 and 3",
         "pii.txt", False, 2, [":2:", ":3:", "[phone]", "[cn-id]"]),
        ("pii_guard", "good.txt clean", "good.txt", False, 0, ["OK", "no PII"]),
        ("pii_guard", "clean.docx skipped (binary)", "clean.docx", False, 0,
         ["skipped"]),
        ("pii_guard", "bad_encoding.txt not scanned -> non-blocking exit 0",
         "bad_encoding.txt", False, 0, ["WARNING", "not scanned"]),
        ("pii_guard", "bad_empty.txt nothing to scan", "bad_empty.txt", False, 0,
         ["empty file"]),
    ]


def main():
    fixtures = gen_fixtures.ensure_fixtures()
    print("fixtures: %s" % ", ".join(fixtures))

    results = []
    for suite, name, fixture, nested, expect, must_contain in build_cases():
        payload = payload_for(fixture, nested=nested)
        r = run_hook(suite + ".py", payload)
        errs = [s for s in must_contain if s not in r["stderr"]]
        ok = (r["exit"] == expect) and not errs
        results.append({
            "suite": suite,
            "case": name,
            "fixture": fixture,
            "expect_exit": expect,
            "actual_exit": r["exit"],
            "exit_ok": r["exit"] == expect,
            "stderr_fragments_expected": must_contain,
            "stderr_fragments_missing": errs,
            "stderr": r["stderr"].strip(),
            "pass": ok,
        })
        mark = "PASS" if ok else "FAIL"
        print("[%s] %-8s %-55s expect=%d actual=%d" % (mark, suite, name, expect, r["exit"]))
        if not ok:
            print("       stderr: %r" % r["stderr"].strip())

    passed = sum(1 for x in results if x["pass"])
    report = {
        "oracle": "office-guard-hooks",
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "fixtures": fixtures,
        "cases": results,
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "ok": passed == len(results),
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    report_path = OUT / "tests.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print("report written: %s" % report_path)
    print("summary: %d/%d passed" % (passed, len(results)))
    sys.exit(0 if report["summary"]["ok"] else 1)


if __name__ == "__main__":
    main()
