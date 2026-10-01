#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval/runner.py -- office-guard-hooks 确定性评测 runner.

契约（spec.md §5 / contract.md §5，写死）：
    python skillfactory/v3/assets/office-guard-hooks/eval/runner.py [<被测产物根>] [<参照产物根>]
默认：被测根 = <asset>/package，参照根 = <asset>/oracle
      （asset 根 = 本文件上级目录，即 skillfactory/v3/assets/office-guard-hooks）。

根解析规则（spec.md §5，写死）：
    传入根含全部必备文件           -> 原样评测（正常包根）
    传入根非空但缺必备文件         -> 向上 <=3 级解析最近含 run_tests.py + hooks.json
                                      的祖先作为实际评测根（resolved_* 字段透明记录）
    传入根为空目录 / 不存在        -> 不解析，直接判红（空目录必须判红）

输出：stdout 打印 {"runner","tested_root","reference_root","resolved_tested_root",
      "resolved_reference_root","ok","checks":[...]}；全过 exit 0，任一失败 exit 1。

checks（id 固定，全部确定性子进程，无网络）：
  1. root-resolution      被测/参照根按解析规则得到实际评测根
  2. reference-baseline   参照根必备文件齐全
  3. structure            被测根必备文件齐全
  4. fixtures-generated   python tests/gen_fixtures.py exit 0 且 6 fixture 就位
  5. self-suite           python run_tests.py（cwd=被测根）exit 0
  6. invalid-json-stdin   两脚本 × {截断 JSON, 非对象 JSON} 均 exit 2 且无 Traceback
  7. hooks-json-config    hooks.json 合法、事件名 ⊆ 文档白名单、形状合法
"""
import json
import subprocess
import sys
from pathlib import Path

ASSET_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TESTED = ASSET_ROOT / "package"
DEFAULT_REFERENCE = ASSET_ROOT / "oracle"

RUNNER_REL = "skillfactory/v3/assets/office-guard-hooks/eval/runner.py"

REQUIRED_BASE = [
    "run_tests.py",
    "hooks/validate_output.py",
    "hooks/pii_guard.py",
    "hooks.json",
    "tests/gen_fixtures.py",
]
# (fixture 文件名, 期望 0 字节?)
REQUIRED_FIXTURES = [
    ("good.txt", False),
    ("bad_empty.txt", True),
    ("bad_encoding.txt", False),
    ("pii.txt", False),
    ("clean.docx", False),
    ("corrupt.docx", False),
]

INVALID_JSON = '{"tool_name":"Write","file_path":'   # 截断 JSON
NONOBJECT_JSON = '[1,2,3]'                            # 合法但非对象

# Claude Code hooks 文档口径（code.claude.com/docs/en/hooks，2026-09-30 取证，
# 全集见 spec.md §5）；handler type 同源。
DOC_EVENTS = {
    "SessionStart", "Setup", "UserPromptSubmit", "UserPromptExpansion",
    "PreToolUse", "PermissionRequest", "PermissionDenied", "PostToolUse",
    "PostToolUseFailure", "PostToolBatch", "Notification", "MessageDisplay",
    "SubagentStart", "SubagentStop", "TaskCreated", "TaskCompleted", "Stop",
    "StopFailure", "TeammateIdle", "InstructionsLoaded", "ConfigChange",
    "CwdChanged", "DirectoryAdded", "FileChanged", "WorktreeCreate",
    "WorktreeRemove", "PreCompact", "PostCompact", "PreModelSwitch",
    "PostModelSwitch", "Elicitation", "ElicitationResult", "SessionEnd",
}
DOC_HANDLER_TYPES = {"command", "http", "mcp_tool", "prompt", "agent"}

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _is_package_root(p: Path) -> bool:
    return all((p / f).is_file() for f in REQUIRED_BASE)


def resolve_root(path: Path):
    """按 spec §5 根解析规则返回 (resolved|None, note)。"""
    if not path.is_dir():
        return None, "传入根不存在: %s" % path
    if _is_package_root(path):
        return path, "传入根即包根: %s" % path
    try:
        non_empty = any(path.iterdir())
    except Exception as e:
        return None, "传入根不可枚举 %s: %s: %s" % (path, type(e).__name__, e)
    if not non_empty:
        # 空目录必须判红：不向上解析
        return None, "传入根为空目录，按契约不向上解析（判红）: %s" % path
    cur, level = path, 0
    while level < 3:
        cur, level = cur.parent, level + 1
        if (cur / "run_tests.py").is_file() and (cur / "hooks.json").is_file():
            return cur, ("传入根 %s 缺必备文件，向上 %d 级解析到候选包根 %s"
                         % (path, level, cur))
    return None, "传入根缺必备文件且向上 3 级内无候选包根: %s" % path


def _run(cmd, cwd=None, input_bytes=None, timeout=180):
    """subprocess 包装：永不抛异常，返回 (completed|None, err_text)。"""
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd) if cwd else None,
            input=input_bytes, capture_output=True, timeout=timeout,
        )
        return proc, None
    except Exception as e:  # FileNotFoundError / TimeoutExpired / OSError
        return None, "%s: %s" % (type(e).__name__, e)


def _out(proc):
    return (proc.stdout or b"").decode("utf-8", "replace").strip()


def _err(proc):
    return (proc.stderr or b"").decode("utf-8", "replace").strip()


def check_reference_baseline(ref: Path):
    missing = [f for f in REQUIRED_BASE if not (ref / f).is_file()]
    if missing:
        return False, "参照根缺少必备文件: %s" % ", ".join(missing)
    return True, "参照根 %s 必备文件齐全" % ref


def check_structure(tested: Path):
    if not tested.is_dir():
        return False, "被测根不存在: %s" % tested
    missing = [f for f in REQUIRED_BASE if not (tested / f).is_file()]
    if missing:
        return False, "被测根缺少必备文件: %s" % ", ".join(missing)
    return True, "被测根 %s 必备文件齐全" % tested


def check_fixtures_generated(tested: Path):
    gen = tested / "tests" / "gen_fixtures.py"
    if not gen.is_file():
        return False, "tests/gen_fixtures.py 缺失，无法生成 fixtures"
    proc, err = _run([sys.executable, "tests/gen_fixtures.py"], cwd=tested, timeout=180)
    if proc is None:
        return False, "gen_fixtures.py 启动失败: %s" % err
    if proc.returncode != 0:
        return False, "gen_fixtures.py exit=%d (期望 0); stderr: %s" % (proc.returncode, _err(proc)[:400])
    problems = []
    for name, expect_empty in REQUIRED_FIXTURES:
        p = tested / "tests" / "fixtures" / name
        if not p.is_file():
            problems.append("%s 缺失" % name)
            continue
        size = p.stat().st_size
        if expect_empty and size != 0:
            problems.append("%s 应为 0 字节, 实际 %d" % (name, size))
        if not expect_empty and size == 0:
            problems.append("%s 不应为空" % name)
    if problems:
        return False, "; ".join(problems)
    return True, "6 个 fixtures 生成并就位 (%s)" % (tested / "tests" / "fixtures")


def check_self_suite(tested: Path):
    rt = tested / "run_tests.py"
    if not rt.is_file():
        return False, "run_tests.py 缺失"
    proc, err = _run([sys.executable, "run_tests.py"], cwd=tested, timeout=300)
    if proc is None:
        return False, "run_tests.py 启动失败: %s" % err
    if proc.returncode != 0:
        tail = (_out(proc) or _err(proc))[-500:]
        return False, "run_tests.py exit=%d (期望 0); 输出尾部: %s" % (proc.returncode, tail)
    return True, "run_tests.py exit=0（全部 fixtures 断言通过）"


def check_invalid_json_stdin(tested: Path):
    problems = []
    ran = 0
    for script in ("hooks/validate_output.py", "hooks/pii_guard.py"):
        full = tested / script
        if not full.is_file():
            problems.append("%s 缺失" % script)
            continue
        for label, payload in (("截断JSON", INVALID_JSON), ("非对象JSON", NONOBJECT_JSON)):
            ran += 1
            proc, err = _run([sys.executable, script], cwd=tested,
                             input_bytes=payload.encode("utf-8"), timeout=60)
            if proc is None:
                problems.append("%s/%s 启动失败: %s" % (script, label, err))
                continue
            stderr_txt = _err(proc)
            if proc.returncode != 2:
                problems.append("%s/%s exit=%d (期望 2)" % (script, label, proc.returncode))
            if "Traceback" in stderr_txt:
                problems.append("%s/%s stderr 出现 Traceback（崩溃而非优雅报错）" % (script, label))
    if problems:
        return False, "; ".join(problems)
    return True, "%d 次非法 stdin 子进程均 exit 2 且无 Traceback" % ran


def check_hooks_json_config(tested: Path):
    p = tested / "hooks.json"
    if not p.is_file():
        return False, "hooks.json 缺失"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return False, "hooks.json 不是合法 JSON: %s" % e
    if not isinstance(data, dict) or not isinstance(data.get("hooks"), dict):
        return False, '顶层必须是含 "hooks" 映射的对象'
    problems = []
    for event, groups in data["hooks"].items():
        if event not in DOC_EVENTS:
            problems.append("事件名不在 Claude Code 文档白名单: %r" % event)
            continue
        if not isinstance(groups, list) or not groups:
            problems.append("%s 的值必须是非空数组" % event)
            continue
        for i, group in enumerate(groups):
            tag = "%s[%d]" % (event, i)
            if not isinstance(group, dict):
                problems.append("%s 必须是对象" % tag)
                continue
            matcher = group.get("matcher")
            if matcher is not None and not isinstance(matcher, str):
                problems.append("%s.matcher 必须是 string" % tag)
            handlers = group.get("hooks")
            if not isinstance(handlers, list) or not handlers:
                problems.append("%s.hooks 必须是非空数组" % tag)
                continue
            for j, handler in enumerate(handlers):
                htag = "%s.hooks[%d]" % (tag, j)
                if not isinstance(handler, dict) or not isinstance(handler.get("type"), str) \
                        or handler["type"] not in DOC_HANDLER_TYPES:
                    problems.append("%s.type 非法 (%r)" % (htag, handler.get("type") if isinstance(handler, dict) else None))
                    continue
                if handler["type"] == "command" and not (
                        isinstance(handler.get("command"), str) and handler["command"].strip()):
                    problems.append("%s 为 command 类型但 command 非非空字符串" % htag)
    if problems:
        return False, "; ".join(problems[:10])
    return True, "hooks.json 合法; 事件=%s" % ",".join(sorted(data["hooks"]))


def main() -> int:
    argv = [a for a in sys.argv[1:] if a not in ("-h", "--help")]
    if len(argv) != len(sys.argv[1:]):
        print(__doc__)
        return 0
    tested_given = Path(argv[0]).resolve() if len(argv) > 0 else DEFAULT_TESTED
    reference_given = Path(argv[1]).resolve() if len(argv) > 1 else DEFAULT_REFERENCE

    tested, tested_note = resolve_root(tested_given)
    reference, reference_note = resolve_root(reference_given)
    resolution_ok = tested is not None and reference is not None
    resolution_detail = "被测: %s | 参照: %s" % (tested_note or "OK", reference_note or "OK")

    checks = [{
        "id": "root-resolution",
        "name": "被测/参照根按解析规则得到实际评测根",
        "passed": bool(resolution_ok),
        "detail": resolution_detail,
    }]
    print("[%s] %-20s %s" % ("PASS" if resolution_ok else "FAIL",
                             "root-resolution", resolution_detail), file=sys.stderr)

    for cid, name, fn, arg in [
        ("reference-baseline", "参照产物根必备文件齐全", check_reference_baseline, reference if reference else reference_given),
        ("structure", "被测产物根必备文件齐全", check_structure, tested if tested else tested_given),
        ("fixtures-generated", "gen_fixtures 生成 6 个 fixtures 且就位", check_fixtures_generated, tested if tested else tested_given),
        ("self-suite", "python run_tests.py 对全部 fixtures 断言通过 (exit 0)", check_self_suite, tested if tested else tested_given),
        ("invalid-json-stdin", "两脚本对非法 JSON stdin 返回 exit 2 而非崩溃", check_invalid_json_stdin, tested if tested else tested_given),
        ("hooks-json-config", "hooks.json 合法且事件名符合 Claude Code 文档口径", check_hooks_json_config, tested if tested else tested_given),
    ]:
        try:
            passed, detail = fn(arg)
        except Exception as e:  # 任何意外都判失败而不是让 runner 崩溃
            passed, detail = False, "runner 内部异常 %s: %s" % (type(e).__name__, e)
        checks.append({"id": cid, "name": name, "passed": bool(passed), "detail": detail})
        print("[%s] %-20s %s" % ("PASS" if passed else "FAIL", cid, detail), file=sys.stderr)

    ok = all(c["passed"] for c in checks)
    print(json.dumps({
        "runner": RUNNER_REL,
        "tested_root": str(tested_given),
        "reference_root": str(reference_given),
        "resolved_tested_root": str(tested) if tested else None,
        "resolved_reference_root": str(reference) if reference else None,
        "ok": ok,
        "checks": checks,
    }, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
