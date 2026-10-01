#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""runner.py — hotwords（单位热词表管理器）确定性评测器（无随机/无网络/无时间戳）

用法：
    python skillfactory/v5/assets/hotwords/eval/runner.py <被测产物根> <参照产物根> [--out <path>]

    例：python eval/runner.py oracle/out oracle/out     # 自评（应 exit 0）
        python eval/runner.py package/out oracle/out    # 评被测实现

产物根 = run_all.py 产出的 out/ 目录（含 manifest.json 与 10 个步骤快照目录）；
给其父目录亦可（单层回退 <root>/out，resolved_via=parent-out 留痕）。

四项检查（名称冻结，恒 4 项齐全，见 contract.md §4 / spec.md §4.3）：
  1. script_sequence_consistent      操作序列每步快照与期望一致（10 步 id/expect/exit_code/快照文件齐备）
  2. duplicate_add_rejected          重复 add 报错（exit=2、stderr 中文、stdout 空、库不变；连带 remove 缺失词）
  3. funasr_export_format            export funasr 行格式正确（「词 权重」、缺省 20、stdout 导出一致、plain 每行一词）
  4. consistency_with_reference_100  与参照产物逐文件一致率 100%（cmd.txt 按冻结规则归一化后比对）

全过 → stdout 打印 JSON(ok=true) 且退出码 0；任一失败 → JSON(ok=false) 且退出码 1；
命令行用法错误由 argparse 退出码 2。输出不含时间戳；同参数重复运行 stdout 逐字节一致。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

try:  # Windows 控制台缺省 GBK，强制 UTF-8 输出
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ASSET = "skillfactory/v5/assets/hotwords/eval"

# ---------------------------------------------------------------- 冻结常量
# 与 spec.md 附录 A（增补条款 A-1）一致；修改须先改 spec.md/contract.md 并升版本号。
STORE_VERSION = 1
DEFAULT_WEIGHT = 20
NO_WEIGHT_WORD = "灵犀大模型"          # 步骤 02 未给 --weight，用于验证缺省权重 20
DEFAULT_WEIGHT_LINE = "灵犀大模型 20"

# 10 步操作序列（id 与 expect 冻结自 fixtures/script.json；快照目录名 = "%02d_%s" % (序号, id)）
STEPS = [
    {"id": "list_initial", "expect": "ok"},
    {"id": "add_ok", "expect": "ok"},
    {"id": "add_duplicate", "expect": "fail"},
    {"id": "add_with_weight", "expect": "ok"},
    {"id": "remove_ok", "expect": "ok"},
    {"id": "remove_missing", "expect": "fail"},
    {"id": "list_final", "expect": "ok"},
    {"id": "export_funasr", "expect": "ok"},
    {"id": "export_plain", "expect": "ok"},
    {"id": "export_stdout", "expect": "ok"},
]
EXPORT_ARTIFACTS = {
    "export_funasr": "hotwords_funasr.txt",
    "export_plain": "hotwords_plain.txt",
}
META_FILES = ("cmd.txt", "exit_code.txt", "stdout.txt", "stderr.txt", "store.json")
# expect=fail 步骤的业务报错判据（stderr 须命中全部关键词，中文报错契约）
FAIL_STDERR_KEYWORDS = {
    "add_duplicate": ("悟空客服", "已存在"),
    "remove_missing": ("不存在",),
}
FUNASR_LINE_RE = re.compile(r"^.+ \d+$")                # 每行「词 空格 权重」
STORE_FLAG_RE = re.compile(r'--store\s+(?:"[^"]*"|\S+)')  # cmd.txt 归一化用


# ---------------------------------------------------------------- 基础工具
def read_bytes(path):
    """读文件字节；失败返回 None。"""
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def decode(raw):
    """字节 → 文本（容忍 BOM）；失败返回 None。"""
    if raw is None:
        return None
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def resolve_out(root):
    """产物根解析：<root> 自身含 manifest.json → direct；否则单层回退 <root>/out。"""
    root = os.path.abspath(root)
    if os.path.isfile(os.path.join(root, "manifest.json")):
        return root, "direct"
    nested = os.path.join(root, "out")
    if os.path.isfile(os.path.join(nested, "manifest.json")):
        return nested, "parent-out(%s -> %s)" % (root, nested)
    return None, "none"


def step_path(out_root, index):
    """第 index 步（1 起）的快照目录路径。"""
    return os.path.join(out_root, "%02d_%s" % (index, STEPS[index - 1]["id"]))


def norm_cmd(raw):
    """cmd.txt 归一化：去掉 python 解释器与脚本绝对路径、--store 及其后工作库路径，
    仅保留其余参数串（strip）。机器相关路径不参与比对，操作序列本身参与。"""
    text = decode(raw)
    if text is None:
        return None
    m = STORE_FLAG_RE.search(text)
    tail = text[m.end():] if m else text
    return tail.strip()


def list_files(root):
    """递归列出 root 下全部文件 → {posix 相对路径: 绝对路径}。不做任何排除（严格一致）。"""
    files = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace("\\", "/")
            files[rel] = full
    return files


# ---------------------------------------------------------------- 检查 1
def check_sequence(cand_out):
    """操作序列每步快照与期望一致。返回 (passed, detail, audit)。"""
    problems = []
    manifest = None
    mraw = read_bytes(os.path.join(cand_out, "manifest.json"))
    if mraw is None:
        problems.append("manifest.json 不存在或不可读")
    else:
        try:
            manifest = json.loads(mraw.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError) as exc:
            problems.append("manifest.json JSON 解析失败: %s" % exc)
    steps_by_id = {}
    if manifest is not None:
        if manifest.get("all_pass") is not True:
            problems.append("manifest.all_pass=%r（须 true）" % (manifest.get("all_pass"),))
        steps = manifest.get("steps")
        if not isinstance(steps, list) or len(steps) != len(STEPS):
            problems.append("manifest.steps 共 %s 步（须 %d 步）"
                            % (len(steps) if isinstance(steps, list) else repr(steps), len(STEPS)))
        for s in steps if isinstance(steps, list) else []:
            if isinstance(s, dict) and isinstance(s.get("step"), str):
                steps_by_id[s["step"]] = s

    ok_steps = 0
    for i, spec in enumerate(STEPS, 1):
        dirname = "%02d_%s" % (i, spec["id"])
        d = os.path.join(cand_out, dirname)
        if not os.path.isdir(d):
            problems.append("%s: 步骤快照目录不存在" % dirname)
            continue
        step_bad = False
        for fn in META_FILES:
            if not os.path.isfile(os.path.join(d, fn)):
                problems.append("%s: 缺快照文件 %s" % (dirname, fn))
                step_bad = True
        exit_val = None
        exit_txt = decode(read_bytes(os.path.join(d, "exit_code.txt")))
        if exit_txt is None or not exit_txt.strip().isdigit():
            problems.append("%s: exit_code.txt 不可解析: %r" % (dirname, exit_txt))
            step_bad = True
        else:
            exit_val = int(exit_txt.strip())
            want = 0 if spec["expect"] == "ok" else 2
            if exit_val != want:
                problems.append("%s: expect=%s 但 exit=%d（契约要求 %d）"
                                % (dirname, spec["expect"], exit_val, want))
                step_bad = True
        mstep = steps_by_id.get(dirname)
        if mstep is None:
            problems.append("%s: manifest.json 未登记该步" % dirname)
            step_bad = True
        else:
            if mstep.get("expect") != spec["expect"]:
                problems.append("%s: manifest.expect=%r 与冻结序列 %r 不符"
                                % (dirname, mstep.get("expect"), spec["expect"]))
                step_bad = True
            if mstep.get("pass") is not True:
                problems.append("%s: manifest.pass=%r（须 true）" % (dirname, mstep.get("pass")))
                step_bad = True
            if exit_val is not None and mstep.get("exit_code") != exit_val:
                problems.append("%s: manifest.exit_code=%r 与 exit_code.txt（%d）不符"
                                % (dirname, mstep.get("exit_code"), exit_val))
                step_bad = True
        art = EXPORT_ARTIFACTS.get(spec["id"])
        if art:
            ab = read_bytes(os.path.join(d, art))
            if ab is None:
                problems.append("%s: 缺导出产物 %s" % (dirname, art))
                step_bad = True
            elif len(ab) == 0:
                problems.append("%s: 导出产物 %s 为空" % (dirname, art))
                step_bad = True
        if not step_bad:
            ok_steps += 1

    audit = {"steps_total": len(STEPS), "steps_ok": ok_steps}
    if problems:
        return False, "；".join(problems[:8]) + ("（共 %d 处）" % len(problems) if len(problems) > 8 else ""), audit
    return True, "10 步序列（%s）目录/快照文件/expect/exit_code/manifest 登记全部一致" % (
        "、".join(s["id"] for s in STEPS)), audit


# ---------------------------------------------------------------- 检查 2
def check_fail_steps(cand_out):
    """重复 add 报错且库不变（连带 remove 缺失词报错）。返回 (passed, detail, audit)。"""
    problems = []
    rows = []
    for i, spec in enumerate(STEPS, 1):
        if spec["expect"] != "fail":
            continue
        dirname = "%02d_%s" % (i, spec["id"])
        d = step_path(cand_out, i)
        prev_dir = step_path(cand_out, i - 1)
        row = {"step": dirname, "ok": True}
        if not os.path.isdir(d) or not os.path.isdir(prev_dir):
            problems.append("%s: 步骤快照目录缺失（无法核验）" % dirname)
            row["ok"] = False
            rows.append(row)
            continue

        exit_txt = decode(read_bytes(os.path.join(d, "exit_code.txt")))
        exit_val = int(exit_txt.strip()) if exit_txt and exit_txt.strip().isdigit() else None
        if exit_val != 2:
            problems.append("%s: 退出码 %r != 2（业务失败契约）" % (dirname, exit_val))
            row["ok"] = False

        stdout_raw = read_bytes(os.path.join(d, "stdout.txt"))
        stdout_txt = decode(stdout_raw)
        if stdout_txt is None or stdout_txt.strip() != "":
            problems.append("%s: stdout 应为空（业务报错走 stderr）" % dirname)
            row["ok"] = False

        stderr_txt = decode(read_bytes(os.path.join(d, "stderr.txt")))
        if stderr_txt is None or not stderr_txt.strip():
            problems.append("%s: stderr 应有中文报错，实际为空" % dirname)
            row["ok"] = False
        else:
            missing_kw = [kw for kw in FAIL_STDERR_KEYWORDS[spec["id"]] if kw not in stderr_txt]
            if missing_kw:
                problems.append("%s: stderr 未命中关键词 %s（实际: %s）"
                                % (dirname, "、".join(missing_kw), stderr_txt.strip()[:60]))
                row["ok"] = False

        cur_store = read_bytes(os.path.join(d, "store.json"))
        prev_store = read_bytes(os.path.join(prev_dir, "store.json"))
        if cur_store is None or prev_store is None:
            problems.append("%s: 库快照不可读（store.json 缺失）" % dirname)
            row["ok"] = False
        elif cur_store != prev_store:
            problems.append("%s: 失败操作后 store.json 发生变化（须与上一步逐字节一致，库不变）" % dirname)
            row["ok"] = False
        row["exit_code"] = exit_val
        rows.append(row)

    audit = {"fail_steps": rows}
    if problems:
        return False, "；".join(problems), audit
    detail = "；".join(
        "%s: exit=2、stderr 中文报错、stdout 空、store.json 与 %02d_%s 逐字节一致（库不变）"
        % ("%02d_%s" % (i, spec["id"]), i - 1, STEPS[i - 2]["id"])
        for i, spec in enumerate(STEPS, 1) if spec["expect"] == "fail")
    return True, detail, audit


# ---------------------------------------------------------------- 检查 3
def check_funasr(cand_out):
    """export funasr 行格式正确（词+空格+权重；缺省 20；stdout 导出一致；plain 每行一词）。"""
    problems = []
    d8 = step_path(cand_out, STEPS.index(next(s for s in STEPS if s["id"] == "export_funasr")) + 1)
    d9 = step_path(cand_out, STEPS.index(next(s for s in STEPS if s["id"] == "export_plain")) + 1)
    d10 = step_path(cand_out, STEPS.index(next(s for s in STEPS if s["id"] == "export_stdout")) + 1)

    store_raw = read_bytes(os.path.join(d8, "store.json"))
    words = None
    if store_raw is None:
        problems.append("08_export_funasr/store.json 不可读（无法推导期望产物）")
    else:
        try:
            store = json.loads(store_raw.decode("utf-8-sig"))
            words = store.get("words") if isinstance(store, dict) else None
        except (UnicodeDecodeError, ValueError) as exc:
            problems.append("08_export_funasr/store.json JSON 解析失败: %s" % exc)
    if words is not None:
        if not isinstance(words, list) or not words:
            problems.append("08_export_funasr/store.json words 为空或非数组")
            words = None
        else:
            for w in words:
                if (not isinstance(w, dict) or not isinstance(w.get("word"), str)
                        or isinstance(w.get("weight"), bool) or not isinstance(w.get("weight"), int)):
                    problems.append("store 词条形状非法: %r" % (w,))
                    words = None
                    break

    lines_ok = 0
    if words is not None:
        funasr_expected = ("\n".join("%s %d" % (w["word"], w["weight"]) for w in words)
                           + ("\n" if words else "")).encode("utf-8")
        plain_expected = ("\n".join(w["word"] for w in words)
                          + ("\n" if words else "")).encode("utf-8")

        funasr_raw = read_bytes(os.path.join(d8, EXPORT_ARTIFACTS["export_funasr"]))
        if funasr_raw is None:
            problems.append("08_export_funasr: 缺导出产物 hotwords_funasr.txt")
        else:
            if funasr_raw != funasr_expected:
                problems.append("hotwords_funasr.txt 与库快照推导的「词 权重」逐行期望不一致"
                                "（%d 字节 vs 期望 %d 字节）" % (len(funasr_raw), len(funasr_expected)))
            text = decode(funasr_raw) or ""
            lines = text.splitlines()
            bad_lines = [ln for ln in lines if not FUNASR_LINE_RE.match(ln)]
            if bad_lines:
                problems.append("funasr 行格式违规（须「词 空格 权重」）: %r" % bad_lines[:3])
            if len(lines) != len(words):
                problems.append("funasr 行数 %d != 库词条数 %d" % (len(lines), len(words)))
            if DEFAULT_WEIGHT_LINE not in text.splitlines():
                problems.append("缺省权重验证失败：未找到行「%s」（%s 未给 --weight，须缺省 %d）"
                                % (DEFAULT_WEIGHT_LINE, NO_WEIGHT_WORD, DEFAULT_WEIGHT))
            if not problems:
                lines_ok += 1

        plain_raw = read_bytes(os.path.join(d9, EXPORT_ARTIFACTS["export_plain"]))
        if plain_raw is None:
            problems.append("09_export_plain: 缺导出产物 hotwords_plain.txt")
        elif plain_raw != plain_expected:
            problems.append("hotwords_plain.txt 与库快照推导的「每行一词」期望不一致")

        stdout10_raw = read_bytes(os.path.join(d10, "stdout.txt"))
        if stdout10_raw is None:
            problems.append("10_export_stdout: stdout.txt 不可读")
        elif stdout10_raw != funasr_expected:
            problems.append("10_export_stdout: 省略 --out 时 stdout 应与 funasr 产物逐字节一致")

    audit = {"funasr_lines_ok": lines_ok == 1}
    if problems:
        return False, "；".join(problems[:6]) + ("（共 %d 处）" % len(problems) if len(problems) > 6 else ""), audit
    return True, ("funasr 产物 %d 行均为「词 空格 权重」且与库快照逐行一致；缺省权重行「%s」在列；"
                  "plain 产物每行一词；省略 --out 时 stdout 与 funasr 产物逐字节一致"
                  % (len(words), DEFAULT_WEIGHT_LINE)), audit


# ---------------------------------------------------------------- 检查 4
def check_consistency(cand_out, ref_out):
    """与参照产物逐文件一致率 100%。cmd.txt 归一化后比对，其余文件逐字节比对。"""
    cand_files = list_files(cand_out)
    ref_files = list_files(ref_out)
    universe = sorted(set(cand_files) | set(ref_files))
    matched, mismatched, missing, extra = [], [], [], []
    for rel in universe:
        cpath, rpath = cand_files.get(rel), ref_files.get(rel)
        if rpath is None:
            extra.append(rel)
            continue
        if cpath is None:
            missing.append(rel)
            continue
        cb, rb = read_bytes(cpath), read_bytes(rpath)
        if cb is None or rb is None:
            mismatched.append(rel)
            continue
        if rel.endswith("cmd.txt"):
            cval, rval = norm_cmd(cb), norm_cmd(rb)
            equal = cval is not None and rval is not None and cval == rval
        else:
            equal = cb == rb
        (matched if equal else mismatched).append(rel)

    total = len(universe)
    rate = (len(matched) / total) if total else 0.0
    audit = {
        "files_universe": total,
        "files_matched": len(matched),
        "files_mismatched": len(mismatched),
        "files_missing": len(missing),
        "files_extra": len(extra),
        "consistency_rate": round(rate, 4),
        "mismatched_files": mismatched,
        "missing_files": missing,
        "extra_files": extra,
    }
    if rate < 1.0:
        detail = ("一致率 %.1f%%（%d/%d 逐文件一致，阈值 100%%）；不一致: %s；缺失: %s；多出: %s"
                  % (rate * 100, len(matched), total,
                     "、".join(mismatched[:6]) or "无", "、".join(missing[:6]) or "无",
                     "、".join(extra[:6]) or "无"))
        return False, detail, audit
    return True, "与参照产物 %d 个文件逐文件一致（cmd.txt 归一化后比对），一致率 100%%" % total, audit


# ---------------------------------------------------------------- 主流程
def main(argv=None):
    ap = argparse.ArgumentParser(description="hotwords 资产确定性评测器")
    ap.add_argument("candidate", help="被测产物根（run_all.py 产出的 out/，或其父目录）")
    ap.add_argument("reference", help="参照产物根（oracle/out，或其父目录）")
    ap.add_argument("--out", default=None, help="评测报告输出路径（缺省仅打印 stdout）")
    args = ap.parse_args(argv)

    cand_out, cand_via = resolve_out(args.candidate)
    ref_out, ref_via = resolve_out(args.reference)
    results = []

    def record(name, passed, detail, **extra):
        entry = {"name": name, "passed": bool(passed), "detail": detail}
        entry.update(extra)
        results.append(entry)
        print("[%s] %s: %s" % ("PASS" if passed else "FAIL", name, detail))

    audit1 = {"steps_total": len(STEPS), "steps_ok": 0}
    audit2 = {"fail_steps": []}
    audit3 = {"funasr_lines_ok": False}
    audit4 = {"consistency_rate": None}

    if cand_out is None:
        pre = ("前置失败：被测产物根未解析出 out/manifest.json（已尝试 %s/manifest.json 与 %s/out/manifest.json）"
               % (args.candidate, args.candidate))
        record("script_sequence_consistent", False, pre, candidate_resolved_via=cand_via, **audit1)
        record("duplicate_add_rejected", False, "前置失败：被测产物根未解析（见第 1 项）", **audit2)
        record("funasr_export_format", False, "前置失败：被测产物根未解析（见第 1 项）", **audit3)
        if ref_out is None:
            record("consistency_with_reference_100", False,
                   "前置失败：被测与参照产物根均未解析出 manifest.json（参照已尝试 %s/out/manifest.json）"
                   % args.reference, **audit4)
        else:
            record("consistency_with_reference_100", False,
                   "前置失败：被测产物根未解析（见第 1 项）", **audit4)
    else:
        ok1, detail1, audit1 = check_sequence(cand_out)
        record("script_sequence_consistent", ok1, detail1,
               candidate_resolved=cand_out, candidate_resolved_via=cand_via, **audit1)

        ok2, detail2, audit2 = check_fail_steps(cand_out)
        record("duplicate_add_rejected", ok2, detail2, **audit2)

        ok3, detail3, audit3 = check_funasr(cand_out)
        record("funasr_export_format", ok3, detail3, **audit3)

        if ref_out is None:
            record("consistency_with_reference_100", False,
                   "前置失败：参照产物根未解析出 out/manifest.json（已尝试 %s/manifest.json 与 %s/out/manifest.json；"
                   "参照缺产物时先 cd oracle && python run_all.py 补跑）" % (args.reference, args.reference),
                   reference_resolved_via=ref_via, **audit4)
        else:
            ok4, detail4, audit4 = check_consistency(cand_out, ref_out)
            record("consistency_with_reference_100", ok4, detail4,
                   reference_resolved=ref_out, reference_resolved_via=ref_via, **audit4)

    all_ok = all(r["passed"] for r in results)
    passed_n = sum(1 for r in results if r["passed"])
    out = {
        "tool": "runner.py",
        "asset": ASSET,
        "candidate": args.candidate,
        "reference": args.reference,
        "candidate_resolved": cand_out,
        "candidate_resolved_via": cand_via,
        "reference_resolved": ref_out,
        "reference_resolved_via": ref_via,
        "self_eval": bool(cand_out and ref_out
                          and os.path.abspath(cand_out) == os.path.abspath(ref_out)),
        "ok": all_ok,
        "summary": {
            "checks": {"total": len(results), "passed": passed_n, "failed": len(results) - passed_n},
            "steps": {"total": audit1.get("steps_total"), "ok": audit1.get("steps_ok")},
            "files": {k: audit4.get(k) for k in ("files_universe", "files_matched",
                                                 "files_mismatched", "files_missing", "files_extra")},
            "consistency_rate": audit4.get("consistency_rate"),
        },
        "checks": results,
    }
    text = json.dumps(out, ensure_ascii=False, indent=2)
    print("-" * 60)
    print(text)
    print("结果: %s（%d/%d 项评测通过）" % ("ALL GREEN ✓" if all_ok else "FAILED ✗",
                                           passed_n, len(results)))
    if args.out:
        out_path = os.path.abspath(args.out)
        parent = os.path.dirname(out_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
        print("报告: %s" % out_path)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
