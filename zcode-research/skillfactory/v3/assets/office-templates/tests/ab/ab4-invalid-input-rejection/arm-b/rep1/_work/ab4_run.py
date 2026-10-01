#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AB4 非法输入拒绝 A/B 驱动 —— arm-b/rep1。

被测（A）：package/scripts/gen_doc.py（SKILL.md §4 / contract §2 冻结 CLI）
参照（B）：oracle/oracle.py（参照实现）
5 组输入 × 2 臂，逐组记录：退出码 / stdout / stderr / 产物残留（outdir 及父目录存在性、
沙箱树前后 diff、共享状态 package/out 与 oracle/out 校验和前后对照）。
结果写 _work/ab4_results.json，控制台打印人读表。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ASSET_ROOT = Path(__file__).resolve().parents[6]  # .../office-templates
WORK = Path(__file__).resolve().parent            # .../arm-b/rep1/_work

CMD_A = [sys.executable, "package/scripts/gen_doc.py"]
CMD_B = [sys.executable, "oracle/oracle.py"]

CASE1 = "oracle/inputs/周报/case1.json"           # 合法对照输入（任务书指定）


def sha_tree(root: Path) -> dict:
    out = {}
    if not root.exists():
        return out
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root)).replace("\\", "/")] = hashlib.sha256(
                p.read_bytes()).hexdigest()
    return out


def prepare_inputs() -> dict:
    """造三份非法/边界输入文件；返回说明 dict。"""
    ind = WORK / "inputs"
    ind.mkdir(parents=True, exist_ok=True)

    not_json = ind / "not-json.json"
    not_json.write_text("这不是一段合法的JSON文本！！", encoding="utf-8")  # 非JSON

    arr_top = ind / "array-top.json"
    arr_top.write_text('["数组", "非对象"]', encoding="utf-8")            # 顶层数组

    ghost = ind / "ghost_404.json"                                       # 不存在的文件
    if ghost.exists():
        ghost.unlink()

    return {
        "not_json": str(not_json.relative_to(ASSET_ROOT)).replace("\\", "/"),
        "arr_top": str(arr_top.relative_to(ASSET_ROOT)).replace("\\", "/"),
        "ghost": str(ghost.relative_to(ASSET_ROOT)).replace("\\", "/"),
    }


def snapshot(work_arm: Path) -> set:
    if not work_arm.exists():
        return set()
    return {str(p.relative_to(work_arm)).replace("\\", "/")
            for p in work_arm.rglob("*")}


def run_one(tag: str, cmd: list, template: str, data: str, outdir: Path,
            before_tree: set) -> dict:
    args = cmd + ["--template", template, "--data", data,
                  "--outdir", str(outdir.relative_to(ASSET_ROOT)).replace("\\", "/")]
    cp = subprocess.run(args, cwd=str(ASSET_ROOT), capture_output=True,
                        encoding="utf-8", errors="replace", timeout=120)
    after_tree = snapshot(WORK / ("a" if cmd is CMD_A else "b"))
    created = sorted(after_tree - before_tree)
    rec = {
        "group": tag,
        "arm": "A(被测 gen_doc.py)" if cmd is CMD_A else "B(参照 oracle.py)",
        "cmd": " ".join(args),
        "returncode": cp.returncode,
        "stdout": cp.stdout,
        "stderr": cp.stderr,
        "outdir_existed": outdir.exists(),
        "outdir_parent_existed": outdir.parent.exists(),
        "tree_created_paths": created,   # 运行前后沙箱树 diff（相对 _work/<arm>/）
        "has_traceback": "Traceback (most recent call last)" in (cp.stderr or ""),
    }
    return rec


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    inp = prepare_inputs()
    shared_before = {"package/out": sha_tree(ASSET_ROOT / "package/out"),
                     "oracle/out": sha_tree(ASSET_ROOT / "oracle/out")}

    groups = [
        # (组名, template, data, outdir 相对 WORK/<arm>/ 的子路径)
        ("G1-模板名非法", "证书", CASE1, "g1/out"),
        ("G2-data文件不存在", "周报", inp["ghost"], "g2/out"),
        ("G3-非JSON", "周报", inp["not_json"], "g3/out"),
        ("G4-顶层数组", "周报", inp["arr_top"], "g4/out"),
        ("G0-合法对照", "周报", CASE1, "control/周报/case1"),
    ]

    results = []
    for arm_name, cmd in (("a", CMD_A), ("b", CMD_B)):
        arm_root = WORK / arm_name
        before_tree = snapshot(arm_root)
        for tag, tpl, data, sub in groups:
            outdir = arm_root / sub
            rec = run_one(tag, cmd, tpl, data, outdir, before_tree)
            rec["arm_key"] = arm_name
            results.append(rec)
            before_tree = snapshot(arm_root)   # 更新基线，含对照组新增产物

    shared_after = {"package/out": sha_tree(ASSET_ROOT / "package/out"),
                    "oracle/out": sha_tree(ASSET_ROOT / "oracle/out")}
    shared_ok = {k: (shared_before[k] == shared_after[k]) for k in shared_before}

    ghost_ok = not (WORK / "inputs/ghost_404.json").exists()

    out = {
        "generated_inputs": inp,
        "ghost_still_absent": ghost_ok,
        "shared_state_unchanged": shared_ok,
        "runs": results,
    }
    (WORK / "ab4_results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 人读输出 ----
    for rec in results:
        print("=" * 78)
        print(f"[{rec['arm']}] {rec['group']}")
        print(f"  CMD : {rec['cmd']}")
        print(f"  RC  : {rec['returncode']}")
        print(f"  OUT : {rec['stdout'].strip() or '(空)'}")
        err = rec["stderr"].strip()
        print(f"  ERR : {err.splitlines()[0] if err else '(空)'}"
              + (f"  … 共{len(err.splitlines())}行" if len(err.splitlines()) > 1 else ""))
        print(f"  残留: outdir存在={rec['outdir_existed']} "
              f"父目录存在={rec['outdir_parent_existed']} "
              f"树新增={rec['tree_created_paths'] or '无'} "
              f"traceback={rec['has_traceback']}")
    print("=" * 78)
    print(f"ghost 文件仍未被创建: {ghost_ok}")
    print(f"共享状态零改动: {shared_ok}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
