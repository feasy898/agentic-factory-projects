#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""healthcheck.py — skill 包结构体检工具（依 spec.md §3 R1–R12 从零实现，仅标准库）

用法：
    python healthcheck.py --target <skill包目录> --out <报告目录>

行为（接口冻结，详见 contract.md / spec.md）：
    --target / --out 均必填（argparse 缺参 exit 2）；
    --target 不是目录 → stderr 报错，exit 2，不创建 --out、不写任何产物；
    其余一切情况（含全红）→ exit 0（体检工具只报告不设门），
    产物为 <out>/report.json 与 <out>/REPORT.md。

恰 5 项检查（名称与顺序冻结）：
    skill_md_exists → front_matter_fields → eval_present → eval_smoke → scripts_syntax
评级 = f(失败检查数；skip 不计失败)：0→A / 1→B / ≥2→C（规则写死）。
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime

TOOL_ID = "healthcheck.py 1.0.0"

# R2：检查项名称与顺序冻结（report.json 的 checks 数组顺序与此一致）
CHECK_NAMES = ("skill_md_exists", "front_matter_fields",
               "eval_present", "eval_smoke", "scripts_syntax")

# R4：front-matter 必须非空的五字段（顺序即「缺字段」detail 的罗列顺序）
REQUIRED_FIELDS = ("name", "version", "license", "description", "permissions")

# R6：eval_smoke 的 runner 查找优先级；都未命中时取 eval/ 顶层按文件名排序的首个 *.py
RUNNER_PRIORITY = ("runner.py", "run.py", "eval.py", "main.py")

SMOKE_TIMEOUT = 60   # R6：单次确定性调用，60s 超时
SUMMARY_LIMIT = 400  # R6：stdout/stderr 摘要空白压缩后截尾长度

FM_DELIM = re.compile(r"^---\s*$")                     # front-matter 起止行（允许行尾空白/\r）
FM_KEY = re.compile(r"^([^\s:][^:]*?)\s*:\s*(.*)$")    # 行级 key: value（非完整 YAML）


# ---------------------------------------------------------------- 工具函数 --

def compress(text):
    """空白压缩为单空格并截尾 400 字符（R6 摘要口径）。"""
    text = " ".join((text or "").split())
    if len(text) > SUMMARY_LIMIT:
        text = text[:SUMMARY_LIMIT] + "…"
    return text


def to_text(data):
    """subprocess 输出（bytes/str/None）转安全文本。"""
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data


def rel_to(path, base):
    """相对路径，统一用 / 分隔（R7 口径）。"""
    return os.path.relpath(path, base).replace(os.sep, "/")


def read_text_flex(path):
    """R4 编码口径：utf-8-sig 优先，解码失败回退 gbk，再失败返回 (None, 原因)。"""
    with open(path, "rb") as f:
        data = f.read()
    for enc in ("utf-8-sig", "gbk"):
        try:
            return data.decode(enc), None
        except UnicodeDecodeError as exc:
            last = exc
    return None, str(last)


def add(checks, name, ok, detail):
    checks.append({"name": name, "pass": bool(ok), "detail": detail})


def rate(num_fail):
    """R8 评级规则（写死）：A=0 失败 / B=1 / C=≥2。"""
    if num_fail == 0:
        return "A"
    if num_fail == 1:
        return "B"
    return "C"


# ------------------------------------------------------------------ 检查项 --

def check_skill_md_exists(target):
    """R3：<target>/SKILL.md 是普通文件 → pass（detail 含字节数）。"""
    path = os.path.join(target, "SKILL.md")
    if os.path.isfile(path):
        return True, "SKILL.md 存在（%d 字节）" % os.path.getsize(path)
    return False, "包根未找到 SKILL.md"


def parse_front_matter(text):
    """R4：行级解析 front-matter 块。返回 (fields|None, 失败原因|None)。

    块以首行 `---` 起始，至下一个 `---` 行闭合；块内逐行匹配 `key: value`
    （首个冒号切分；缩进行视为嵌套内容，不作为顶层键收集）。
    """
    lines = text.splitlines()
    if not lines or not FM_DELIM.match(lines[0]):
        return None, "front-matter 块缺失（首行不是 ---）"
    fields = {}
    for line in lines[1:]:
        if FM_DELIM.match(line):
            return fields, None
        m = FM_KEY.match(line)
        if m:
            fields[m.group(1)] = m.group(2).strip()
    return None, "front-matter 块未闭合（缺少结束 ---）"


def check_front_matter_fields(target):
    """R4：五字段 name/version/license/description/permissions 非空 → pass。"""
    path = os.path.join(target, "SKILL.md")
    if not os.path.isfile(path):
        return False, "SKILL.md 不存在，无法解析 front-matter"
    text, err = read_text_flex(path)
    if text is None:
        return False, "SKILL.md 解码失败（utf-8-sig 与 gbk 均失败）: %s" % compress(err)
    fields, reason = parse_front_matter(text)
    if fields is None:
        return False, reason
    missing = [k for k in REQUIRED_FIELDS if not fields.get(k)]
    present = [k for k in REQUIRED_FIELDS if fields.get(k)]
    if missing:
        return False, "front-matter 缺字段: %s（已有: %s）" % (
            ", ".join(missing), ", ".join(present))
    return True, "front-matter 五字段齐全（%s 均非空）" % "/".join(REQUIRED_FIELDS)


def check_eval_present(target):
    """R5：<target>/eval/ 是目录 → pass。"""
    if os.path.isdir(os.path.join(target, "eval")):
        return True, "eval/ 目录存在"
    return False, "缺少 eval/ 目录（无确定性评测）"


def find_eval_runner(target):
    """R6：runner 查找（优先级固定；最后回退 eval/ 顶层按文件名排序首个 *.py，仅文件）。"""
    eval_dir = os.path.join(target, "eval")
    for name in RUNNER_PRIORITY:
        path = os.path.join(eval_dir, name)
        if os.path.isfile(path):
            return path
    for name in sorted(os.listdir(eval_dir)):
        path = os.path.join(eval_dir, name)
        if name.endswith(".py") and os.path.isfile(path):
            return path
    return None


def check_eval_smoke(target, eval_dir_present):
    """R6：单次确定性 smoke 调用（不重试掩蔽）；无 runner → pass=true 且 detail 以 skip: 开头。"""
    if not eval_dir_present:
        return True, "skip: 缺 eval/ 目录，跳过 smoke"
    runner = find_eval_runner(target)
    if runner is None:
        return True, "skip: eval/ 目录存在但未找到 runner，跳过 smoke"

    ref = None
    for cand in (os.path.join(target, "reference", "out"),
                 os.path.join(target, "eval", "reference", "out")):
        if os.path.isdir(cand):
            ref = cand
            break
    args = [rel_to(runner, target)]
    if ref is not None:  # dist 系列自校验约定：<runner> <ref> <ref>
        args += [rel_to(ref, target), rel_to(ref, target)]
    else:
        args += ["--help"]
    cmd = "python " + " ".join(args)

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.run(
            ["python"] + args, cwd=target, env=env, timeout=SMOKE_TIMEOUT,
            capture_output=True, text=True, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired as exc:
        return False, ("smoke exit=timeout(%ds) | cmd: %s | stderr 摘要: %s | stdout 摘要: %s"
                       % (SMOKE_TIMEOUT, cmd, compress(to_text(exc.stderr)),
                          compress(to_text(exc.stdout))))
    except OSError as exc:
        return False, "smoke 无法启动 | cmd: %s | 错误: %s" % (cmd, compress(str(exc)))

    if proc.returncode == 0:
        return True, "smoke exit=0 | cmd: %s | stdout 摘要: %s" % (cmd, compress(proc.stdout))
    return False, ("smoke exit=%d | cmd: %s | stderr 摘要: %s | stdout 摘要: %s"
                   % (proc.returncode, cmd, compress(proc.stderr), compress(proc.stdout)))


def collect_scripts(target):
    """R7：递归收集 <target>/scripts/ 下的 *.py（跳过名为 __pycache__ 的子目录），按路径排序。"""
    scripts_dir = os.path.join(target, "scripts")
    if not os.path.isdir(scripts_dir):
        return None
    found = []
    for dirpath, dirnames, filenames in os.walk(scripts_dir):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for fn in sorted(filenames):
            if fn.endswith(".py"):
                found.append(os.path.join(dirpath, fn))
    return found


def check_scripts_syntax(target):
    """R7：逐个 *.py 以 utf-8-sig 读入后 compile()；任一失败即红，全过则绿。"""
    py_files = collect_scripts(target)
    if py_files is None:
        return False, "scripts/ 目录不存在"
    if not py_files:
        return False, "scripts/ 下没有 *.py 文件"

    failures, rels = [], []
    for path in py_files:
        relp = rel_to(path, target)
        rels.append(relp)
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                src = f.read()
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            failures.append("%s: 读取错误: %s" % (relp, compress(str(exc))))
            continue
        try:
            compile(src, relp, "exec")
        except SyntaxError as exc:
            lineno = exc.lineno if exc.lineno is not None else "?"
            failures.append("%s: 第%s行 SyntaxError: %s" % (relp, lineno, exc.msg or "invalid syntax"))
        except (ValueError, TypeError) as exc:  # 如含空字节等编译期错误
            failures.append("%s: 编译错误: %s" % (relp, compress(str(exc))))

    if failures:
        return False, "%d/%d 个脚本语法不过: %s" % (len(failures), len(py_files), "; ".join(failures))
    return True, "scripts/ 下 %d 个 *.py 全部语法可编译: %s" % (len(py_files), ", ".join(rels))


# ------------------------------------------------------------------ 产物 ----

def build_report(target, out_dir, checks):
    """R9/R10：组装并写出 report.json 与 REPORT.md，返回 (report dict, json 文本, md 文本)。"""
    total = len(checks)
    n_pass = sum(1 for c in checks if c["pass"])
    n_fail = total - n_pass
    rating = rate(n_fail)
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")

    report = {
        "tool": TOOL_ID,
        "target": os.path.abspath(target),
        "generated_at": generated_at,  # 唯一非确定性字段（R9/R12）
        "summary": {"total": total, "pass": n_pass, "fail": n_fail},
        "rating": rating,
        "checks": checks,
    }
    json_text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"

    lines = ["# Skill Healthcheck Report", ""]
    lines.append("- 目标包：`%s`" % report["target"])
    lines.append("- 生成时间：%s" % generated_at)
    lines.append("- 评级：**%s**（A=0 失败 / B=1 失败 / C=≥2 失败）" % rating)
    lines.append("- 汇总：%d 项检查，%d 通过 / %d 失败" % (total, n_pass, n_fail))
    lines.append("")
    lines.append("| 检查项 | 结果 | 说明 |")
    lines.append("| --- | --- | --- |")
    for c in checks:
        verdict = "✅ PASS" if c["pass"] else "❌ FAIL"
        lines.append("| %s | %s | %s |" % (c["name"], verdict, c["detail"].replace("|", "\\|")))
    lines.append("")
    lines.append("## 建议")
    lines.append("")
    if rating == "A":
        lines.append("评级 A：无失败项，包结构与确定性评测齐备，可进入分发流程。")
    elif rating == "B":
        lines.append("评级 B：仅 1 项失败，建议修复下述红项后重跑体检。")
    else:
        lines.append("评级 C：失败项 ≥2，分发前必须完成整改。")
    for c in checks:
        if not c["pass"]:
            lines.append("- %s：%s" % (c["name"], c["detail"]))
    lines.append("")
    md_text = "\n".join(lines)

    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write(json_text)
    with open(os.path.join(out_dir, "REPORT.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(md_text)
    return report, json_text, md_text


# ------------------------------------------------------------------ 主流程 --

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="healthcheck.py", description="skill 包结构体检工具（5 项检查，评级 A/B/C）")
    parser.add_argument("--target", required=True, help="skill 包目录")
    parser.add_argument("--out", required=True, help="报告输出目录（report.json + REPORT.md）")
    args = parser.parse_args(argv)  # 缺参 → argparse usage + exit 2

    target = args.target
    if not os.path.isdir(target):
        # R1/R11：exit 2，且不得创建 --out、不得写任何产物
        print("错误：--target 不是目录: %s" % target, file=sys.stderr)
        return 2

    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)

    checks = []
    ok_md, d_md = check_skill_md_exists(target)
    add(checks, "skill_md_exists", ok_md, d_md)
    ok_fm, d_fm = check_front_matter_fields(target)
    add(checks, "front_matter_fields", ok_fm, d_fm)
    ok_ev, d_ev = check_eval_present(target)
    add(checks, "eval_present", ok_ev, d_ev)
    ok_sm, d_sm = check_eval_smoke(target, ok_ev)
    add(checks, "eval_smoke", ok_sm, d_sm)
    ok_sc, d_sc = check_scripts_syntax(target)
    add(checks, "scripts_syntax", ok_sc, d_sc)

    assert [c["name"] for c in checks] == list(CHECK_NAMES), "检查项顺序被破坏（R2）"
    report, _, _ = build_report(target, out_dir, checks)
    print("体检完成：评级 %s（%d 项检查，%d 通过 / %d 失败）→ %s"
          % (report["rating"], report["summary"]["total"],
             report["summary"]["pass"], report["summary"]["fail"], out_dir))
    return 0  # R11：报告已写出即 0，无论红绿


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
