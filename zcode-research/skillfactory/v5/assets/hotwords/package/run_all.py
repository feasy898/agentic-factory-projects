#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_all.py — 按 fixtures/script.json 以真实 CLI 子进程逐步执行 hotwords.py，产出 out/ 快照

驱动契约（冻结，见 ../contract.md §2.2 / ../spec.md §4.2 A1-A5 与附录 A.8）：

- 清空重建 out/；fixtures/base.json 复制为 out/_work/store.json，跨步延续。
- 逐步以真实 CLI 子进程执行 10 步：argv = [python, hotwords.py, --store <工作库>] + step.args，
  子进程 cwd = 该步快照目录（相对 --out 产物直接落入快照）。
- 每步快照 out/<NN>_<id>/：cmd.txt（subprocess.list2cmdline 全命令行）、exit_code.txt（"%d\\n"）、
  stdout.txt、stderr.txt、store.json（工作库复制）+ 导出产物。
- 汇总 out/manifest.json（键结构见 spec 附录 A.8，indent=2 + ensure_ascii=False + 末尾换行）。
- 整体退出码：任一步与 expect 不符 → 1，否则 0。
- 确定性：无时间戳、无随机数、无网络，同输入连跑两次 out/ 全树逐字节一致。

自包含：仅依赖 Python 标准库。
"""

import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "out")
FIXTURES_DIR = os.path.join(HERE, "fixtures")
HOTWORDS_PY = os.path.join(HERE, "hotwords.py")
MANIFEST_SCRIPT = "fixtures/script.json"   # spec 附录 A.8 冻结取值
MANIFEST_BASE = "fixtures/base.json"
META_FILES = ("cmd.txt", "exit_code.txt", "stdout.txt", "stderr.txt", "store.json")


def force_utf8_stdio():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", newline="\n")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", newline="\n")
    except Exception:
        pass


def write_bytes(path, data):
    with open(path, "wb") as f:
        f.write(data)


def first_line(raw):
    """stdout/stderr 首行（UTF-8 解码；空输出为空串）。"""
    lines = raw.decode("utf-8", "replace").splitlines()
    return lines[0] if lines else ""


def main():
    force_utf8_stdio()
    script_path = os.path.join(FIXTURES_DIR, "script.json")
    base_path = os.path.join(FIXTURES_DIR, "base.json")
    with open(script_path, "rb") as f:
        script = json.loads(f.read().decode("utf-8-sig"))
    steps = script.get("steps")
    if not isinstance(steps, list) or not steps:
        print("script.json 缺少 steps 数组，退出")
        return 2

    # A1：清空重建 out/，工作库自 base.json 复制，跨步延续
    if os.path.isdir(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    work_dir = os.path.join(OUT_DIR, "_work")
    os.makedirs(work_dir)
    work_store = os.path.join(work_dir, "store.json")
    shutil.copyfile(base_path, work_store)

    rows = []
    all_pass = True
    for index, step in enumerate(steps, 1):
        step_id = step.get("id", "step%d" % index)
        dirname = "%02d_%s" % (index, step_id)
        snap_dir = os.path.join(OUT_DIR, dirname)
        os.makedirs(snap_dir)

        # A2：真实 CLI 子进程；--store 注入工作库绝对路径，cwd = 快照目录
        argv = [sys.executable, HOTWORDS_PY, "--store", work_store] + list(step.get("args", []))
        proc = subprocess.run(argv, cwd=snap_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # A3：快照文件（字节写入，杜绝平台换行翻译）
        write_bytes(os.path.join(snap_dir, "cmd.txt"),
                    (subprocess.list2cmdline(argv) + "\n").encode("utf-8"))
        write_bytes(os.path.join(snap_dir, "exit_code.txt"),
                    ("%d\n" % proc.returncode).encode("ascii"))
        write_bytes(os.path.join(snap_dir, "stdout.txt"), proc.stdout)
        write_bytes(os.path.join(snap_dir, "stderr.txt"), proc.stderr)
        shutil.copyfile(work_store, os.path.join(snap_dir, "store.json"))
        artifacts = sorted(fn for fn in os.listdir(snap_dir) if fn not in META_FILES)

        # A5：expect=ok 要求退出码 0；expect=fail 要求非 0
        expect = step.get("expect", "ok")
        passed = (proc.returncode == 0) if expect == "ok" else (proc.returncode != 0)
        all_pass = all_pass and passed
        rows.append({
            "step": dirname,
            "desc": step.get("desc", ""),
            "expect": expect,
            "exit_code": proc.returncode,
            "pass": passed,
            "stdout_first_line": first_line(proc.stdout),
            "stderr_first_line": first_line(proc.stderr),
            "artifacts": artifacts,
        })
        print("[%s] %s exit=%d %s" % ("OK" if passed else "FAIL", dirname,
                                      proc.returncode, step.get("desc", "")))

    # A4：manifest（A.8 键序；indent=2 + ensure_ascii=False + 末尾换行，UTF-8 无 BOM）
    manifest = {"script": MANIFEST_SCRIPT, "base_store": MANIFEST_BASE,
                "steps": rows, "all_pass": all_pass}
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    write_bytes(os.path.join(OUT_DIR, "manifest.json"), text.encode("utf-8"))

    ok_count = sum(1 for r in rows if r["pass"])
    print("%d/%d 步 OK；产物目录：%s" % (ok_count, len(rows), OUT_DIR))
    print("EXIT=%d" % (0 if all_pass else 1))
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
