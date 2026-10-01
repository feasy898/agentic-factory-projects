#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_tests.py -- office-guard-hooks package 自测（12 用例，spec R4.2）。

用法（cwd = package 根）：
    python run_tests.py    # 全过 exit 0；任一失败 exit 1
机器可读报告恒写出：out/tests.json。

用例构成：validate_output 7 + pii_guard 5，均以真实子进程方式调用两 hook，
断言 exit code（关键用例另断言 stderr 关键子串与 stdout 恒空）。
"""
import json
import subprocess
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent
FIXTURE_DIR = PKG_ROOT / "tests" / "fixtures"
REPORT_PATH = PKG_ROOT / "out" / "tests.json"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def payload(file_path, nested=False):
    """构造 hook payload：顶层 file_path（默认）或 tool_input.file_path（嵌套）。"""
    if nested:
        return {"tool_name": "Write", "tool_input": {"file_path": file_path}}
    return {"tool_name": "Write", "file_path": file_path}


# (suite, name, script, payload, expected exit, stderr 必含子串列表)
CASES = [
    # ---- validate_output.py：7 用例 ----
    ("validate_output", "good.txt 通过", "hooks/validate_output.py",
     payload("tests/fixtures/good.txt"), 0, ["OK"]),
    ("validate_output", "clean.docx 通过", "hooks/validate_output.py",
     payload("tests/fixtures/clean.docx"), 0, ["OK"]),
    ("validate_output", "bad_empty.txt 阻断(空文件)", "hooks/validate_output.py",
     payload("tests/fixtures/bad_empty.txt"), 2, ["empty"]),
    ("validate_output", "bad_encoding.txt 阻断(非UTF-8)", "hooks/validate_output.py",
     payload("tests/fixtures/bad_encoding.txt"), 2, ["not decodable as UTF-8"]),
    ("validate_output", "corrupt.docx 阻断(python-docx 打不开)", "hooks/validate_output.py",
     payload("tests/fixtures/corrupt.docx"), 2, ["python-docx"]),
    ("validate_output", "缺失文件阻断", "hooks/validate_output.py",
     payload("tests/fixtures/no_such_file.txt"), 2, ["does not exist"]),
    ("validate_output", "嵌套 tool_input.file_path schema", "hooks/validate_output.py",
     payload("tests/fixtures/good.txt", nested=True), 0, ["OK"]),
    # ---- pii_guard.py：5 用例 ----
    ("pii_guard", "pii.txt 阻断(脱敏命中，手机+身份证各一条)", "hooks/pii_guard.py",
     payload("tests/fixtures/pii.txt"), 2,
     ["pii.txt:2: [phone] 138****5678", "pii.txt:3: [cn-id] 1101**********4258"]),
    ("pii_guard", "good.txt 干净放行", "hooks/pii_guard.py",
     payload("tests/fixtures/good.txt"), 0, ["no PII"]),
    ("pii_guard", "bad_empty.txt 空文件 fail-open", "hooks/pii_guard.py",
     payload("tests/fixtures/bad_empty.txt"), 0, ["empty file"]),
    ("pii_guard", "bad_encoding.txt 非 UTF-8 不扫描放行", "hooks/pii_guard.py",
     payload("tests/fixtures/bad_encoding.txt"), 0, ["not scanned"]),
    ("pii_guard", "clean.docx 二进制跳过放行", "hooks/pii_guard.py",
     payload("tests/fixtures/clean.docx"), 0, ["skipped"]),
]

FIXTURE_NAMES = ["good.txt", "bad_empty.txt", "bad_encoding.txt",
                 "pii.txt", "clean.docx", "corrupt.docx"]


def ensure_fixtures():
    """fixtures 缺失时先跑 gen_fixtures.py（幂等）；失败返回错误信息。"""
    missing = [n for n in FIXTURE_NAMES if not (FIXTURE_DIR / n).is_file()]
    if not missing:
        return None
    proc = subprocess.run([sys.executable, "tests/gen_fixtures.py"],
                          cwd=str(PKG_ROOT), capture_output=True, timeout=120)
    if proc.returncode != 0:
        return "gen_fixtures.py exit=%d; stderr: %s" % (
            proc.returncode, (proc.stderr or b"").decode("utf-8", "replace")[:300])
    return None


def main():
    err = ensure_fixtures()
    if err:
        print("run_tests: FAIL: fixtures 不可用: %s" % err)
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(
            {"package": str(PKG_ROOT), "total": 0, "passed": 0, "failed": 0,
             "error": err}, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1

    results = []
    for suite, name, script, case_payload, expected_exit, must_contain in CASES:
        proc = subprocess.run(
            [sys.executable, script], cwd=str(PKG_ROOT),
            input=json.dumps(case_payload, ensure_ascii=False).encode("utf-8"),
            capture_output=True, timeout=120,
        )
        stderr_txt = (proc.stderr or b"").decode("utf-8", "replace")
        stdout_txt = (proc.stdout or b"").decode("utf-8", "replace")
        problems = []
        if proc.returncode != expected_exit:
            problems.append("exit=%d (期望 %d)" % (proc.returncode, expected_exit))
        for needle in must_contain:
            if needle not in stderr_txt:
                problems.append("stderr 缺少 %r" % needle)
        if stdout_txt != "":
            problems.append("stdout 应恒为空, 实际 %r" % stdout_txt[:100])
        ok = not problems
        results.append({
            "suite": suite, "name": name, "script": script,
            "expected_exit": expected_exit, "exit": proc.returncode,
            "ok": ok, "problems": problems,
        })
        print("[%s] %-16s %s" % ("PASS" if ok else "FAIL", suite, name))

    total = len(results)
    passed = sum(1 for r in results if r["ok"])
    failed = total - passed
    report = {
        "package": str(PKG_ROOT),
        "total": total, "passed": passed, "failed": failed,
        "cases": results,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print("run_tests: %d/%d PASS, 报告: %s" % (passed, total, REPORT_PATH))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
