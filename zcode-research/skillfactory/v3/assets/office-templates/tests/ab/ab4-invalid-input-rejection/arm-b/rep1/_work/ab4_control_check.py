#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AB4 对照组产物核验 —— A/B 各自合法对照产物 vs 基线 oracle/out/周报/case1。

1) outdir 恰含 文书.docx + fields.json 两个文件；
2) fields.json 深度 diff（忽略 $.outputs.* 自引用路径）：A_replay vs B_replay vs 基线；
3) docx 段落文本序列逐段对比（语义层；zip 时间戳允许不同）；
4) oracle/verify.py 版式不变量校验（对照根 _work/{a,b}/control）；
5) 全部产物 sha256 清单（留档 OUT.md）。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

from docx import Document

ASSET_ROOT = Path(__file__).resolve().parents[6]
WORK = Path(__file__).resolve().parent
BASELINE = ASSET_ROOT / "oracle/out/周报/case1"
A_CTRL = WORK / "a/control/周报/case1"
B_CTRL = WORK / "b/control/周报/case1"


def strip_outputs(node, path="$"):
    """深度复制并剔除 $.outputs.*（自引用路径，允许不同写法）。"""
    if isinstance(node, dict):
        return {k: (strip_outputs(v, f"{path}.{k}") if not path.endswith(".outputs")
                    else "<ignored>") for k, v in node.items()}
    if isinstance(node, list):
        return [strip_outputs(v, f"{path}[{i}]") for i, v in enumerate(node)]
    return node


def deep_diff(a, b, path="$", out=None):
    if out is None:
        out = []
    if type(a) is not type(b):
        out.append(f"{path}: 类型 {type(a).__name__} vs {type(b).__name__}")
        return out
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append(f"{path}.{k}: 仅B有={b[k]!r}")
            elif k not in b:
                out.append(f"{path}.{k}: 仅A有={a[k]!r}")
            else:
                deep_diff(a[k], b[k], f"{path}.{k}", out)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append(f"{path}: 长度 {len(a)} vs {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            deep_diff(x, y, f"{path}[{i}]", out)
    elif a != b:
        out.append(f"{path}: {a!r} vs {b!r}")
    return out


def docx_paras(p: Path):
    return [q.text for q in Document(str(p)).paragraphs]


def load_fields(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def sha16(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    report = {}

    # 1) 文件清单
    for tag, d in (("A", A_CTRL), ("B", B_CTRL), ("基线", BASELINE)):
        files = sorted(x.name for x in d.iterdir())
        ok = files == ["fields.json", "文书.docx"]
        report[f"files_{tag}"] = {"files": files, "exactly_two": ok}
        print(f"[{tag}] outdir 清单: {files}  恰2文件={ok}")

    # 2) fields.json 三方深度 diff
    fa, fb, fb0 = load_fields(A_CTRL / "fields.json"), load_fields(
        B_CTRL / "fields.json"), load_fields(BASELINE / "fields.json")
    d_ab = deep_diff(strip_outputs(fa), strip_outputs(fb))
    d_ab0 = deep_diff(strip_outputs(fa), strip_outputs(fb0))
    d_bb0 = deep_diff(strip_outputs(fb), strip_outputs(fb0))
    report["fields_diff_A_vs_B"] = d_ab
    report["fields_diff_A_vs_baseline"] = d_ab0
    report["fields_diff_B_vs_baseline"] = d_bb0
    print(f"fields A vs B（忽略outputs）   : {'一致(0差异)' if not d_ab else d_ab}")
    print(f"fields A vs 基线（忽略outputs）: {'一致(0差异)' if not d_ab0 else d_ab0}")
    print(f"fields B vs 基线（忽略outputs）: {'一致(0差异)' if not d_bb0 else d_bb0}")

    # 3) docx 段落文本序列对比
    pa, pb, pb0 = docx_paras(A_CTRL / "文书.docx"), docx_paras(
        B_CTRL / "文书.docx"), docx_paras(BASELINE / "文书.docx")
    report["docx_paras_A_vs_B"] = None if pa == pb else {"A": pa, "B": pb}
    report["docx_paras_A_vs_baseline"] = None if pa == pb0 else {"A": pa, "B": pb0}
    print(f"docx 段落文本 A vs B    : {'逐段一致（%d段）' % len(pa) if pa == pb else '不一致'}")
    print(f"docx 段落文本 A vs 基线 : {'逐段一致（%d段）' % len(pa) if pa == pb0 else '不一致'}")
    if pa != pb:
        print("  --- A 段落序列 ---")
        for i, t in enumerate(pa):
            print(f"   {i}: {t!r}")
        print("  --- B 段落序列 ---")
        for i, t in enumerate(pb):
            print(f"   {i}: {t!r}")

    # 4) verify.py（oracle 自设版式不变量门槛）
    for tag, root in (("A", WORK / "a/control"), ("B", WORK / "b/control")):
        cp = subprocess.run([sys.executable, "oracle/verify.py",
                             str(root.relative_to(ASSET_ROOT))],
                            cwd=str(ASSET_ROOT), capture_output=True,
                            encoding="utf-8", errors="replace")
        report[f"verify_{tag}"] = {"rc": cp.returncode, "out": cp.stdout.strip()}
        print(f"verify.py [{tag}]: rc={cp.returncode}\n{cp.stdout.strip()}")

    # 5) sha256 清单
    report["sha256_16"] = {
        f"{tag}/{name}": sha16(p)
        for tag, p in (("A", A_CTRL / "文书.docx"), ("A", A_CTRL / "fields.json"),
                       ("B", B_CTRL / "文书.docx"), ("B", B_CTRL / "fields.json"),
                       ("基线", BASELINE / "文书.docx"), ("基线", BASELINE / "fields.json"))
        for name in ([p.name])}
    for k, v in report["sha256_16"].items():
        print(f"sha256[{k}] = {v}")

    # fields.json 顶层键与 summary 键集合（S1 自洽口径，contract §3）
    for tag, f in (("A", fa), ("B", fb)):
        report[f"keys_{tag}"] = {"top": sorted(f), "summary": sorted(f["summary"]),
                                 "outputs_ignored_paths": sorted(f.get("outputs", {}))}
        print(f"[{tag}] fields 顶层键={sorted(f)} summary键={sorted(f['summary'])}")

    (WORK / "ab4_control_check.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
