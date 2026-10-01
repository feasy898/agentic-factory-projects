#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""export_legacy.py — office-eval-suite v2 套件 → v1 黄金集兼容格式导出器（oracle 参照软件）

v1 兼容格式 = skillfactory/v3/assets/prompt-regression/package/golden.json 的结构契约
（contract.md §2）:
    顶层: {version, description, items}
    题目: {id, domain, instruction, checks}   ← 无 difficulty（v1 无此字段，导出时移除）
    check: {name, desc, type∈{contains,regex,semantic}, value}
    六域枚举: doc-writing/table-data/meeting-minutes/ppt-outline/email-comm/process-spec
    v1 黄金集规格: 25 题，六域配比 6/5/3/3/4/4

用法:
    python export_legacy.py [--suite <suite.json>] [--out <导出路径>]
                            [--counts doc-writing=6,table-data=5,...] [--all] [--report <json>]
    缺省: --suite <脚本目录>/suite.json；--out <脚本目录>/out/golden-legacy.json；
          --report <脚本目录>/out/export-legacy.json
    模式: 缺省按 v1 六域下限（6/5/3/3/4/4，共 25 题）从 v2 套件抽取子集（各域按文件顺序取前 N 题），
          产物可直接通过 v1 校验器（prompt-regression validate.py）；
          --all 导出全部六域旧域题目（不做 25 题裁剪，仅保证域合法）；
          --counts 覆盖各域抽取数。
    退出码: 0 = 导出成功且达 v1 规格；1 = 任一域题目不足或失败
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TOOL = "export_legacy.py"

# ---- v1 契约常量（来源: skillfactory/v3/assets/prompt-regression/contract.md §2 与 package/golden.json）----
V1_VERSION = "1.0.0-legacy-export"
V1_TOTAL = 25
V1_LEGACY_DOMAINS = {  # v1 六域: 标签 → v1 下限（即精确配比）
    "doc-writing": {"label": "文档写作", "min": 6},
    "table-data": {"label": "表格数据", "min": 5},
    "meeting-minutes": {"label": "会议纪要", "min": 3},
    "ppt-outline": {"label": "PPT要点", "min": 3},
    "email-comm": {"label": "邮件沟通", "min": 4},
    "process-spec": {"label": "流程规范", "min": 4},
}
V2_ONLY_DOMAINS = {  # v2 新增域：v1 枚举之外，默认不导出
    "info-extraction": "信息抽取",
    "rewrite-polish": "改写润色",
}
V1_ITEM_KEYS = ["id", "domain", "instruction", "checks"]  # 严格顺序、无 difficulty


def load_suite(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise SystemExit(f"[FAIL] {path}: 顶层须为 object 且含 items 数组")
    return data


def parse_counts(spec: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pair in spec.split(","):
        k, _, v = pair.partition("=")
        k, v = k.strip(), v.strip()
        if k not in V1_LEGACY_DOMAINS or not v.isdigit():
            raise SystemExit(f"[FAIL] --counts 非法片段: {pair!r}（须为 域名=整数，域名限 v1 六域）")
        counts[k] = int(v)
    return counts


def export_legacy(suite: dict, per_domain: dict[str, int], out_path: Path, report_path: Path,
                  strict: bool) -> int:
    items = [it for it in suite["items"] if isinstance(it, dict)]
    by_domain: dict[str, list[dict]] = {d: [] for d in V1_LEGACY_DOMAINS}
    dropped_new: dict[str, int] = {d: 0 for d in V2_ONLY_DOMAINS}
    for it in items:  # 保持原文件顺序
        dom = it.get("domain")
        if dom in by_domain:
            by_domain[dom].append(it)
        elif dom in dropped_new:
            dropped_new[dom] += 1

    picked: list[dict] = []
    per_domain_taken: dict[str, int] = {}
    problems: list[str] = []
    for dom, cfg in V1_LEGACY_DOMAINS.items():
        want = per_domain[dom]
        avail = by_domain[dom]
        take = avail[:want]
        per_domain_taken[dom] = len(take)
        picked.extend(take)
        if len(take) < want:
            problems.append(f"{cfg['label']}({dom}) 仅 {len(take)} 题可导出 < 目标 {want}")

    exported_items = [
        {k: copy.deepcopy(it[k]) for k in V1_ITEM_KEYS}
        for it in picked
        if all(k in it for k in V1_ITEM_KEYS)
    ]
    total = len(exported_items)

    export = {
        "version": V1_VERSION,
        "description": (f"office-eval-suite v2 子集的 v1 黄金集兼容导出：{total} 题，六域配比 "
                        "/".join(str(per_domain_taken[d]) for d in V1_LEGACY_DOMAINS)
                        + "；源套件 suite.json（v2），导出时移除 v1 不支持的 difficulty 字段，"
                          "v2 新增域（信息抽取/改写润色）不在 v1 枚举内故不导出。"),
        "items": exported_items,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(export, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    checks_total = sum(len(it["checks"]) for it in exported_items)
    ok = (not problems) if strict else total > 0
    if strict and total != V1_TOTAL:
        problems.append(f"总题数 {total} != v1 期望 {V1_TOTAL}")

    summary = {
        "tool": TOOL,
        "suite": None,  # 由调用方填
        "generated_at": datetime.now().replace(microsecond=0).isoformat(),
        "ok": ok,
        "mode": "strict-v1" if strict else "loose",
        "exported": str(out_path),
        "total_items": total,
        "total_checks": checks_total,
        "per_domain_taken": {V1_LEGACY_DOMAINS[d]["label"]: per_domain_taken[d] for d in V1_LEGACY_DOMAINS},
        "dropped_v2_only_domains": {V2_ONLY_DOMAINS[d]: n for d, n in dropped_new.items()},
        "dropped_field": "difficulty（v1 题目键集无此字段）",
        "problems": problems,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    summary["suite"] = str(suite.get("_suite_path", "?"))
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[PASS] 导出 {total} 题 / {checks_total} 条 check → {out_path}")
    print(f"       六域配比: " + "、".join(
        f"{V1_LEGACY_DOMAINS[d]['label']}={per_domain_taken[d]}" for d in V1_LEGACY_DOMAINS))
    print(f"       移除字段: difficulty；未导出 v2 新增域: "
          + "、".join(f"{V2_ONLY_DOMAINS[d]}({n}题)" for d, n in dropped_new.items()))
    print(f"报告: {report_path}")
    if problems:
        for p in problems:
            print(f"[FAIL] {p}")
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="office-eval-suite v2 → v1 黄金集兼容导出器")
    ap.add_argument("--suite", default=None, help="suite.json 路径（缺省 <脚本目录>/suite.json）")
    ap.add_argument("--out", default=None, help="导出路径（缺省 <脚本目录>/out/golden-legacy.json）")
    ap.add_argument("--report", default=None, help="导出报告路径（缺省 <脚本目录>/out/export-legacy.json）")
    ap.add_argument("--counts", default=None, help="覆盖各域抽取数，如 doc-writing=6,table-data=5,...")
    ap.add_argument("--all", action="store_true", help="导出全部 v1 六域题目（不做 25 题裁剪，宽松模式）")
    args = ap.parse_args()

    base = Path(__file__).resolve().parent
    suite_path = Path(args.suite) if args.suite else base / "suite.json"
    out_path = Path(args.out) if args.out else base / "out" / "golden-legacy.json"
    report_path = Path(args.report) if args.report else base / "out" / "export-legacy.json"

    suite = load_suite(suite_path)
    suite["_suite_path"] = str(suite_path)  # 仅供报告留痕

    per_domain = {d: cfg["min"] for d, cfg in V1_LEGACY_DOMAINS.items()}
    if args.counts:
        per_domain.update(parse_counts(args.counts))
    strict = not args.all
    if args.all:
        per_domain = {d: 10**6 for d in V1_LEGACY_DOMAINS}

    return export_legacy(suite, per_domain, out_path, report_path, strict=strict)


if __name__ == "__main__":
    sys.exit(main())
