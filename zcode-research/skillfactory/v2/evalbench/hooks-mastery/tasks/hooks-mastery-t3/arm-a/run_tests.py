#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_tests.py — 用子进程实测 env_guard.py：喂入 stdin JSON，报告退出码/stderr。"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
SCRIPT = HERE / "env_guard.py"


def case(desc, tool_name, tool_input):
    payload = {
        "session_id": "test-session",
        "transcript_path": "/tmp/t.jsonl",
        "cwd": "D:/workspace/demo",
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input,
    }
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(HERE),
    )
    verdict = "BLOCKED(退出码2)" if proc.returncode == 2 else (
        "ALLOWED(退出码0)" if proc.returncode == 0 else f"OTHER(退出码{proc.returncode})"
    )
    print(f"[{verdict}] {desc}")
    if proc.stderr.strip():
        print(f"    stderr: {proc.stderr.strip()}")
    return proc.returncode


def main():
    print(f"被测脚本: {SCRIPT}")
    print("=" * 72)
    rc1 = case(
        "测试1(应拦): Edit .env.local",
        "Edit",
        {"file_path": "D:/workspace/demo/.env.local", "old_string": "A=1", "new_string": "A=2"},
    )
    rc2 = case(
        "测试2(应放): Edit src/app.py",
        "Edit",
        {"file_path": "D:/workspace/demo/src/app.py", "old_string": "pass", "new_string": "x = 1"},
    )
    print("-" * 72)
    print("附加边界用例:")
    case("附加: Write 相对路径 .env", "Write", {"file_path": ".env", "content": "K=v"})
    case("附加: Write src/.env.production", "Write", {"file_path": "D:/workspace/demo/src/.env.production", "content": "K=v"})
    case("附加: Write Windows反斜杠 .ENV(大小写)", "Write", {"file_path": "D:\\workspace\\demo\\.ENV", "content": "K=v"})
    case("附加(应放): Write foo.env(前缀不符,非变体)", "Write", {"file_path": "D:/workspace/demo/config/foo.env", "content": "x=1"})
    case("附加(应放): Read .env(读工具不受限)", "Read", {"file_path": "D:/workspace/demo/.env"})
    ok = (rc1 == 2) and (rc2 == 0)
    print("=" * 72)
    print("结论: 测试1 阻断(2) / 测试2 放行(0) ->", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
