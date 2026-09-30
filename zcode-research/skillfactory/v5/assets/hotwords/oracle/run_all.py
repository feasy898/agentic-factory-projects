#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_all.py — 批量驱动：按 fixtures/script.json 的操作序列，逐步以真实 CLI 子进程
调用 hotwords.py，全部跑完产出 out/（每步快照）。

用法：python run_all.py

机制：
  1. 清空并重建 out/；把 fixtures/base.json 复制为工作库 out/_work/store.json。
  2. 逐步执行 script.json 的 steps：命令形如
         python hotwords.py --store <工作库> <step.args...>
     子进程 cwd = out/<序号>_<id>/，故脚本内相对 --out 的导出产物直接落进该步快照目录。
  3. 每步快照（out/<序号>_<id>/）：cmd.txt（完整命令行）、exit_code.txt、stdout.txt、
     stderr.txt、store.json（该步执行后的库快照）、以及导出产物等 artifacts。
  4. 汇总写 out/manifest.json；任一步退出码与 expect（ok|fail）不符 → 整体退出码 1。
     expect=fail 的步骤要求退出码非 0（业务报错也是参照行为的一部分）。

确定性：无时间戳、无随机数——同输入连跑两次，out/ 逐字节一致。
"""

import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HOTWORDS = os.path.join(HERE, "hotwords.py")
FIX_BASE = os.path.join(HERE, "fixtures", "base.json")
FIX_SCRIPT = os.path.join(HERE, "fixtures", "script.json")
OUT = os.path.join(HERE, "out")
META_FILES = {"cmd.txt", "exit_code.txt", "stdout.txt", "stderr.txt", "store.json"}


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    for required in (HOTWORDS, FIX_BASE, FIX_SCRIPT):
        if not os.path.exists(required):
            print("[run_all] 错误：缺少必需文件 %s" % required, file=sys.stderr)
            sys.exit(1)
    with open(FIX_SCRIPT, "r", encoding="utf-8-sig") as f:
        script = json.load(f)
    steps = script["steps"]
    if not steps:
        print("[run_all] 错误：script.json 无步骤", file=sys.stderr)
        sys.exit(1)

    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    work_dir = os.path.join(OUT, "_work")
    os.makedirs(work_dir)
    work_store = os.path.join(work_dir, "store.json")
    shutil.copyfile(FIX_BASE, work_store)

    manifest, failed = [], False
    for i, step in enumerate(steps, 1):
        sid = "%02d_%s" % (i, step["id"])
        step_dir = os.path.join(OUT, sid)
        os.makedirs(step_dir)
        argv = [sys.executable, HOTWORDS, "--store", work_store] + step["args"]
        proc = subprocess.run(argv, cwd=step_dir, capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
        expect = step.get("expect", "ok")
        ok = (proc.returncode == 0) if expect == "ok" else (proc.returncode != 0)
        failed = failed or not ok

        write_text(os.path.join(step_dir, "cmd.txt"), subprocess.list2cmdline(argv) + "\n")
        write_text(os.path.join(step_dir, "exit_code.txt"), "%d\n" % proc.returncode)
        write_text(os.path.join(step_dir, "stdout.txt"), proc.stdout)
        write_text(os.path.join(step_dir, "stderr.txt"), proc.stderr)
        shutil.copyfile(work_store, os.path.join(step_dir, "store.json"))
        artifacts = sorted(fn for fn in os.listdir(step_dir) if fn not in META_FILES)

        first_line = proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else ""
        first_err = proc.stderr.strip().splitlines()[0] if proc.stderr.strip() else ""
        manifest.append({
            "step": sid,
            "desc": step.get("desc", ""),
            "expect": expect,
            "exit_code": proc.returncode,
            "pass": ok,
            "stdout_first_line": first_line,
            "stderr_first_line": first_err,
            "artifacts": artifacts,
        })
        print("[run_all] %-22s exit=%d expect=%-4s -> %s%s" % (
            sid, proc.returncode, expect, "OK" if ok else "FAIL",
            (" | " + (first_err if first_err else first_line))))

    summary = {
        "script": "fixtures/script.json",
        "base_store": "fixtures/base.json",
        "steps": manifest,
        "all_pass": not failed,
    }
    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
        f.write("\n")

    if failed:
        print("[run_all] 有步骤与 expect 不符，详见 out/manifest.json", file=sys.stderr)
        sys.exit(1)
    print("[run_all] 全部 %d 步按预期跑通，快照见 out/" % len(steps))


if __name__ == "__main__":
    main()
