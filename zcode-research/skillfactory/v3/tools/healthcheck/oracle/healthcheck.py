#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""healthcheck.py — Skill 包体检 CLI（oracle 参照实现）

用法：
    python healthcheck.py --target <skill包目录> --out <报告目录>

检查项（report.json 的 checks 数组，元素为 {name, pass, detail}）：
  1. skill_md_exists      包根存在 SKILL.md
  2. front_matter_fields  SKILL.md front-matter 含 name/version/license/description/permissions
  3. eval_present         包根存在 eval/ 目录
  4. eval_smoke           eval/ 内有 runner 则实跑 smoke：超时 60s，记录 exit code，
                          任何情况不中断整体；无 runner 则跳过（pass=true，detail 注明 skip）
  5. scripts_syntax       scripts/ 下所有 *.py 用 compile() 验语法（跳过 __pycache__）；
                          目录缺失或无 py 文件记失败

smoke 调用策略（单次执行、确定性，不做多策略重试掩蔽）：
  - runner 查找顺序：eval/runner.py > eval/run.py > eval/eval.py > eval/main.py
    > eval/ 下第一个 *.py（跳过 __pycache__）
  - 存在 <target>/reference/out 或 <target>/eval/reference/out 时（dist 系列技能
    的自校验约定）：python <runner> <ref> <ref>
  - 否则：python <runner> --help

评级（REPORT.md，按失败项数）：A = 0 失败；B = 1 失败；C = ≥2 失败

退出码：0 = 报告已写出（无论红绿，体检工具只报告不设门）；2 = 参数或目标目录无效
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

TOOL_NAME = "healthcheck.py"
TOOL_VERSION = "1.0.0"
SMOKE_TIMEOUT_SEC = 60
FRONT_FIELDS = ("name", "version", "license", "description", "permissions")
FRONT_MATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(\r?\n|$)", re.S)
FRONT_KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):(.*)$")
RUNNER_CANDIDATES = ("runner.py", "run.py", "eval.py", "main.py")
DETAIL_MAX = 400

ADVICE = {
    "skill_md_exists": "在包根补写 SKILL.md：front-matter（name/version/license/description/permissions）+ 正文（何时使用、输入输出、规则）。",
    "front_matter_fields": "在 SKILL.md 头部 front-matter 中补齐缺失字段（缺哪些见 checks 明细）。",
    "eval_present": "建立 eval/ 目录，放置确定性评测 runner（如 runner.py）与 golden 用例清单，保证机器可判、无网络依赖。",
    "eval_smoke": "修复 eval runner 使其可独立运行；dist 系列技能可用自校验入口：python eval/runner.py reference/out reference/out（应 exit 0）。",
    "scripts_syntax": "按 checks 明细修复 scripts/ 下语法错误，本地复验：python -m py_compile <file>。",
}
RATING_ADVICE = {
    "A": "全绿：可作为分发参照包。",
    "B": "单项不达标：按下方对应建议修复后重跑本工具复检。",
    "C": "多项不达标：结构性问题，建议对照 A 级样本（如 skillfactory/dist/meeting-minutes-skill）重做包骨架。",
}


def clip(text, limit=DETAIL_MAX):
    """压缩空白并截尾，保证报告 detail 单行可读。"""
    flat = re.sub(r"\s+", " ", (text or "")).strip()
    if len(flat) > limit:
        flat = flat[: limit - 3] + "..."
    return flat


# ---------------------------------------------------------------- 检查项 ----

def check_skill_md(target):
    path = os.path.join(target, "SKILL.md")
    if os.path.isfile(path):
        return True, "SKILL.md 存在（%d 字节）" % os.path.getsize(path), None
    return False, "包根未找到 SKILL.md", None


def parse_front_matter(text):
    m = FRONT_MATTER_RE.match(text)
    if not m:
        return None, "文件未以 '---' 行起始的 front-matter 块开头"
    fm = {}
    for line in m.group(1).splitlines():
        km = FRONT_KEY_RE.match(line)
        if km:
            fm[km.group(1)] = km.group(2).strip()
    return fm, None


def check_front_matter(target):
    path = os.path.join(target, "SKILL.md")
    if not os.path.isfile(path):
        return False, "SKILL.md 不存在，无法检查 front-matter", None
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            text = f.read()
    except UnicodeDecodeError:
        try:
            with open(path, "r", encoding="gbk") as f:
                text = f.read()
        except Exception as exc:  # noqa: BLE001
            return False, "SKILL.md 无法读取: %s" % exc, None
    fm, err = parse_front_matter(text)
    if fm is None:
        return False, err, {"missing": list(FRONT_FIELDS)}
    missing = [k for k in FRONT_FIELDS if not fm.get(k)]
    if missing:
        return False, "front-matter 缺字段: %s（已有: %s）" % (
            ", ".join(missing), ", ".join(k for k in FRONT_FIELDS if k in fm) or "无"), None
    return True, "front-matter 五字段齐全: %s" % ", ".join(FRONT_FIELDS), None


def find_runner(target):
    """返回 eval/ 下 runner 的绝对路径；找不到返回 None。"""
    eval_dir = os.path.join(target, "eval")
    if not os.path.isdir(eval_dir):
        return None
    for name in RUNNER_CANDIDATES:
        p = os.path.join(eval_dir, name)
        if os.path.isfile(p):
            return p
    for fn in sorted(os.listdir(eval_dir)):
        p = os.path.join(eval_dir, fn)
        if fn.endswith(".py") and os.path.isfile(p):
            return p
    return None


def build_smoke_command(target, runner):
    """单次确定性的 smoke 命令：有自校验参照目录则用之，否则 --help。"""
    ref = None
    for cand in (os.path.join(target, "reference", "out"),
                 os.path.join(target, "eval", "reference", "out")):
        if os.path.isdir(cand):
            ref = cand
            break
    if ref:
        return [sys.executable, runner, ref, ref]
    return [sys.executable, runner, "--help"]


def check_eval_present(target):
    eval_dir = os.path.join(target, "eval")
    if os.path.isdir(eval_dir):
        return True, "eval/ 目录存在", None
    return False, "缺少 eval/ 目录（无确定性评测）", None


def check_eval_smoke(target):
    """runner 可执行则实跑 smoke；超时/非零都只记录，不抛出不中断。"""
    runner = find_runner(target)
    if runner is None:
        if not os.path.isdir(os.path.join(target, "eval")):
            return True, "skip: 缺 eval/ 目录，跳过 smoke", None
        return True, "skip: eval/ 存在但无可执行 runner，跳过 smoke", None
    cmd = build_smoke_command(target, runner)
    disp = " ".join(os.path.basename(c) if i == 0 else c for i, c in enumerate(cmd))
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.run(
            cmd, cwd=target, env=env, timeout=SMOKE_TIMEOUT_SEC,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.TimeoutExpired:
        return False, "smoke 超时（>%ds）被终止: %s" % (SMOKE_TIMEOUT_SEC, disp), {
            "cmd": disp, "exit_code": None, "timed_out": True}
    except OSError as exc:
        return False, "smoke 无法启动: %s (%s)" % (disp, exc), {
            "cmd": disp, "exit_code": None, "error": str(exc)}
    out = clip(proc.stdout.decode("utf-8", errors="replace"))
    err = clip(proc.stderr.decode("utf-8", errors="replace"))
    if proc.returncode == 0:
        detail = "smoke exit=0（%s）stdout: %s" % (disp, out or "<空>")
        return True, detail, {"cmd": disp, "exit_code": 0}
    detail = "smoke exit=%d 非 0（%s）stderr: %s stdout: %s" % (
        proc.returncode, disp, err or "<空>", out or "<空>")
    return False, detail, {"cmd": disp, "exit_code": proc.returncode,
                           "stderr": err, "stdout": out}


def check_scripts_syntax(target):
    scripts_dir = os.path.join(target, "scripts")
    if not os.path.isdir(scripts_dir):
        return False, "scripts/ 目录不存在", None
    py_files = []
    for root, dirs, files in os.walk(scripts_dir):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fn in sorted(files):
            if fn.endswith(".py"):
                py_files.append(os.path.join(root, fn))
    if not py_files:
        return False, "scripts/ 下没有 *.py 文件", None
    bad = []
    for p in py_files:
        rel = os.path.relpath(p, target).replace("\\", "/")
        try:
            with open(p, "r", encoding="utf-8-sig") as f:
                src = f.read()
            compile(src, p, "exec")
        except SyntaxError as exc:
            bad.append("%s: 第%s行 SyntaxError: %s" % (rel, exc.lineno, exc.msg))
        except Exception as exc:  # noqa: BLE001 — 编码/读取错误同样是编译失败
            bad.append("%s: %s" % (rel, exc))
    if bad:
        return False, "%d/%d 个脚本语法不过: %s" % (
            len(bad), len(py_files), "; ".join(bad)), {"bad": bad}
    return True, "scripts/ 下 %d 个 *.py 全部语法可编译: %s" % (
        len(py_files), ", ".join(
            os.path.relpath(p, target).replace("\\", "/") for p in py_files)), None


# ---------------------------------------------------------------- 报告 ----

def rate(num_fail):
    if num_fail == 0:
        return "A"
    if num_fail == 1:
        return "B"
    return "C"


def build_report(target, checks):
    fails = [c for c in checks if not c["pass_"]]
    rating = rate(len(fails))
    return {
        "tool": "%s %s" % (TOOL_NAME, TOOL_VERSION),
        "target": os.path.abspath(target),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "summary": {"total": len(checks),
                    "pass": len(checks) - len(fails),
                    "fail": len(fails)},
        "rating": rating,
        "checks": [{"name": c["name"], "pass": c["pass_"], "detail": c["detail"]}
                   for c in checks],
    }


def write_report_md(report, out_dir):
    lines = ["# Skill Healthcheck Report", ""]
    lines.append("- 目标包：`%s`" % report["target"])
    lines.append("- 生成时间：%s（%s）" % (report["generated_at"], report["tool"]))
    lines.append("- 评级：**%s**（A=0 失败 / B=1 失败 / C=≥2 失败）" % report["rating"])
    s = report["summary"]
    lines.append("- 汇总：%d 项检查，%d 通过 / %d 失败"
                 % (s["total"], s["pass"], s["fail"]))
    lines.append("")
    lines.append("| 检查项 | 结果 | 说明 |")
    lines.append("|---|---|---|")
    for c in report["checks"]:
        mark = "✅ PASS" if c["pass"] else "❌ FAIL"
        lines.append("| `%s` | %s | %s |" % (c["name"], mark, c["detail"].replace("|", "\\|")))
    lines.append("")
    lines.append("## 建议")
    lines.append("")
    lines.append("- %s" % RATING_ADVICE[report["rating"]])
    for c in report["checks"]:
        if not c["pass"] and c["name"] in ADVICE:
            lines.append("- **%s**：%s" % (c["name"], ADVICE[c["name"]]))
    lines.append("")
    path = os.path.join(out_dir, "REPORT.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    return path


def main(argv):
    ap = argparse.ArgumentParser(
        prog=TOOL_NAME, description="Skill 包体检：SKILL.md / eval / scripts 语法")
    ap.add_argument("--target", required=True, help="skill 包目录")
    ap.add_argument("--out", required=True, help="报告输出目录")
    args = ap.parse_args(argv)

    target = args.target
    if not os.path.isdir(target):
        print("错误：--target 不是目录: %s" % target, file=sys.stderr)
        return 2
    os.makedirs(args.out, exist_ok=True)

    checks = []
    ok, detail, extra = check_skill_md(target)
    checks.append(dict(name="skill_md_exists", pass_=ok, detail=detail, extra=extra))
    ok, detail, extra = check_front_matter(target)
    checks.append(dict(name="front_matter_fields", pass_=ok, detail=detail, extra=extra))
    ok, detail, extra = check_eval_present(target)
    checks.append(dict(name="eval_present", pass_=ok, detail=detail, extra=extra))
    ok, detail, extra = check_eval_smoke(target)
    checks.append(dict(name="eval_smoke", pass_=ok, detail=detail, extra=extra))
    ok, detail, extra = check_scripts_syntax(target)
    checks.append(dict(name="scripts_syntax", pass_=ok, detail=detail, extra=extra))

    report = build_report(target, checks)
    json_path = os.path.join(args.out, "report.json")
    with open(json_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")
    md_path = write_report_md(report, args.out)

    print("评级 %s（%d/%d 通过）-> %s" % (
        report["rating"], report["summary"]["pass"], report["summary"]["total"], json_path))
    print("人读报告 -> %s" % md_path)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
