#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""export_legacy.py — office-eval-suite package v1 黄金集兼容导出器

契约（contract.md §4，行为 = spec.md §4.3 X1–X4）:
    用法:   python export_legacy.py [--suite <path>] [--out <path>] [--report <path>]
                                    [--counts 域=整数,...] [--all]
    --suite   缺省 <脚本所在目录>/suite.json
    --out     缺省 <脚本所在目录>/out/golden-legacy.json（导出产物，v1 黄金集格式）
    --report  缺省 <脚本所在目录>/out/export-legacy.json
    --counts  域名=整数 逗号分隔，域名限 v1 六域，覆盖各域抽取数
    --all     宽松模式：导出全部 v1 六域题目（不做 25 题裁剪）

导出格式（v1 黄金集契约）:
    顶层 {version, description, items}，version = "1.0.0-legacy-export"；
    题目恰四键 {id, domain, instruction, checks}（严格此顺序，移除 difficulty）；
    v2 新增域（info-extraction / rewrite-polish）不导出。

缺省模式（严格）: 按 v1 六域下限 6/5/3/3/4/4（共 25 题）从 v2 套件按文件顺序取前 N 题；
    任一域可导出数不足 → 退出码 1。
退出码: 0 = 导出成功且达 v1 规格；1 = 任一域题目不足或失败。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

try:  # Windows 控制台缺省 GBK，强制 UTF-8 输出
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TOOL = "export_legacy.py"
LEGACY_VERSION = "1.0.0-legacy-export"
LEGACY_DESCRIPTION = ("v1 中文办公 Prompt 回归黄金集兼容子集"
                      "（由 office-eval-suite v2 套件按 contract.md §4 导出，移除 difficulty）")

V1_DOMAINS = {  # v1 六域：缺省严格模式的抽取下限
    "doc-writing": {"label": "文档写作", "min": 6},
    "table-data": {"label": "表格数据", "min": 5},
    "meeting-minutes": {"label": "会议纪要", "min": 3},
    "ppt-outline": {"label": "PPT要点", "min": 3},
    "email-comm": {"label": "邮件沟通", "min": 4},
    "process-spec": {"label": "流程规范", "min": 4},
}
V2_ONLY_DOMAINS = ["info-extraction", "rewrite-polish"]  # v2 新增域，不导出
DROPPED_FIELD = "difficulty"                              # v2 新增字段，导出时移除


def fail(problems: list[str], suite_path: Path, report_path: Path, n_source: int,
         mode: str, taken: dict[str, int]) -> int:
    for p in problems:
        print(f"[FAIL] {p}")
    report = {
        "tool": TOOL,
        "suite": str(suite_path),
        "generated_at": datetime.now().replace(microsecond=0).isoformat(),
        "ok": False,
        "mode": mode,
        "exported": 0,
        "total_items": n_source,
        "total_checks": 0,
        "per_domain_taken": taken,
        "dropped_v2_only_domains": list(V2_ONLY_DOMAINS),
        "dropped_field": DROPPED_FIELD,
        "problems": problems,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"报告: {report_path}")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="office-eval-suite v1 黄金集兼容导出器")
    script_dir = Path(__file__).resolve().parent
    ap.add_argument("--suite", default=None, help=f"v2 套件路径（缺省 {script_dir / 'suite.json'}）")
    ap.add_argument("--out", default=None, help="导出产物路径（缺省 <脚本目录>/out/golden-legacy.json）")
    ap.add_argument("--report", default=None, help="导出报告路径（缺省 <脚本目录>/out/export-legacy.json）")
    ap.add_argument("--counts", default=None, help="域名=整数 逗号分隔，覆盖各域抽取数（域名限 v1 六域）")
    ap.add_argument("--all", action="store_true", help="导出全部 v1 六域题目（宽松模式）")
    args = ap.parse_args()

    suite_path = Path(args.suite) if args.suite else script_dir / "suite.json"
    out_path = Path(args.out) if args.out else script_dir / "out" / "golden-legacy.json"
    report_path = Path(args.report) if args.report else script_dir / "out" / "export-legacy.json"

    mode = "all" if args.all else ("counts" if args.counts else "strict")
    problems: list[str] = []

    # ---- 加载套件
    try:
        data = json.loads(suite_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return fail([f"套件无法加载（{suite_path}）: {e}"], suite_path, report_path, 0, mode,
                    {d: 0 for d in V1_DOMAINS})
    items = data.get("items", []) if isinstance(data, dict) else []
    if not isinstance(items, list) or not items:
        return fail([f"套件无 items 或 items 非数组（{suite_path}）"], suite_path, report_path, 0, mode,
                    {d: 0 for d in V1_DOMAINS})
    n_source = len(items)

    # ---- 解析抽取数
    if args.all:
        targets: dict[str, int] = {d: -1 for d in V1_DOMAINS}  # -1 = 不限量
    else:
        targets = {d: cfg["min"] for d, cfg in V1_DOMAINS.items()}
        if args.counts:
            for pair in args.counts.split(","):
                pair = pair.strip()
                if not pair:
                    continue
                if "=" not in pair:
                    problems.append(f"--counts 片段非法（须 域名=整数）: {pair!r}")
                    continue
                dom, _, raw = pair.partition("=")
                dom = dom.strip()
                if dom not in V1_DOMAINS:
                    problems.append(f"--counts 域名不在 v1 六域内: {dom!r}")
                    continue
                try:
                    n = int(raw.strip())
                except ValueError:
                    problems.append(f"--counts 整数非法: {pair!r}")
                    continue
                if n < 0:
                    problems.append(f"--counts 数量须 ≥0: {pair!r}")
                    continue
                targets[dom] = n
        if problems:
            return fail(problems, suite_path, report_path, n_source, mode, {d: 0 for d in V1_DOMAINS})

    # ---- 按文件顺序抽取（严格模式取前 N 题；--all 全取）；v2 专属域不导出
    taken = {d: 0 for d in V1_DOMAINS}
    exported_items: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            problems.append(f"items 中存在非 object 项: {type(it).__name__}")
            continue
        dom = it.get("domain")
        if dom not in V1_DOMAINS:
            continue  # v2 专属域（及未知域）不导出
        limit = targets[dom]
        if limit >= 0 and taken[dom] >= limit:
            continue
        exported_items.append({  # 题目恰四键，严格此顺序，移除 difficulty
            "id": it.get("id"),
            "domain": dom,
            "instruction": it.get("instruction"),
            "checks": it.get("checks"),
        })
        taken[dom] += 1

    # ---- 严格模式：任一域不足 → 失败
    if not args.all:
        for d, cfg in V1_DOMAINS.items():
            if taken[d] < targets[d]:
                problems.append(f"{cfg['label']}({d}) 可导出 {taken[d]} 题 < 需 {targets[d]} 题")
        if problems:
            return fail(problems, suite_path, report_path, n_source, mode, taken)

    # ---- 写导出产物
    legacy = {
        "version": LEGACY_VERSION,
        "description": LEGACY_DESCRIPTION,
        "items": exported_items,
    }
    total_checks = sum(len(it["checks"]) for it in exported_items if isinstance(it.get("checks"), list))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(legacy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ---- 报告
    report = {
        "tool": TOOL,
        "suite": str(suite_path),
        "generated_at": datetime.now().replace(microsecond=0).isoformat(),
        "ok": True,
        "mode": mode,
        "exported": len(exported_items),
        "total_items": n_source,
        "total_checks": total_checks,
        "per_domain_taken": taken,
        "dropped_v2_only_domains": list(V2_ONLY_DOMAINS),
        "dropped_field": DROPPED_FIELD,
        "problems": [],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ---- stdout
    print(f"[PASS] 导出 {len(exported_items)} 题 / {total_checks} 条 check → {out_path}")
    print("六域配比: " + "、".join(
        f"{V1_DOMAINS[d]['label']}={taken[d]}" + ("" if targets[d] < 0 else f"/{targets[d]}") for d in V1_DOMAINS))
    print(f"移除字段: {DROPPED_FIELD}")
    print(f"未导出 v2 专属域: {'、'.join(V2_ONLY_DOMAINS)}")
    print(f"报告: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
