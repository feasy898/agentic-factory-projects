#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
report.py — vpipe 汇报模块：汇 metadata → 报告
（vpipe SPEC.md 模块 4；汇总口径改造自今晚已验证的 overnight/数据/build_metadata.py
 ——该脚本产出的 metadata.json 是本模块的一等输入）。

契约: 输入=asset_manifest（contracts/asset_manifest.schema.json）+ 生成侧 metadata JSON
      （build_metadata.py 产出格式）+ qc_dir 下的 QCReport（contracts/qc_report.schema.json）；
      输出=Markdown 报告 + JSON 摘要。不 import 任何 vpipe 兄弟模块。

用法:
  python report.py --metadata ../数据/metadata.json --qc-dir out/qc_reports \
      [--manifest out/asset_manifest.json] --out out/report
产出: out/report.md + out/report.summary.json（退出码 0=正常，1=关键输入缺失）
"""
import argparse
import datetime
import json
import sys
from collections import Counter
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def log(msg):
    print(f"[report {datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def summarize_generation(meta):
    """生成矩阵概览（metadata.json = build_metadata.py 格式）。"""
    run = meta.get("run") or {}
    clips = meta.get("clips") or []
    cnt = Counter(c.get("status") for c in clips)
    cost = [c.get("credit_cost") for c in clips if isinstance(c.get("credit_cost"), int)]
    lines = [
        "## 1. 生成矩阵概览（来源：metadata.json）", "",
        f"- 通道：{run.get('channel', '?')}",
        f"- 终态记录：{len(clips)} 条 " + " ".join(f"{k}={v}" for k, v in sorted(cnt.items(), key=str)),
        f"- 含成片：{sum(1 for c in clips if c.get('clip_file'))} 条；缺成片：{meta.get('totals', {}).get('without_clip', '?')} 条",
        f"- 积分账目：baseline={run.get('credit_baseline')} → end={run.get('credit_end')}，"
        f"本次实扣 **{run.get('spent_this_test')}**（上限 {run.get('credit_cap', 40000)}）",
    ]
    if cost:
        lines.append(f"- 每条实扣：min={min(cost)} / max={max(cost)} / 合计={sum(cost)}（{len(cost)} 条有记录）")
    seed = run.get("seed_probe") or {}
    if seed:
        lines.append(f"- 种子控制实测：DTO 拒绝={seed.get('dto_rejected')}，决策={seed.get('decision', '?')}")
    st = meta.get("seed_test") or {}
    if st:
        lines.append(f"- 同种子双跑哈希结论：{json.dumps({k: st.get(k) for k in ('conclusion', 'identical_pairs') if k in st}, ensure_ascii=False)}")
    return lines, clips


def summarize_qc(qc_dir):
    """QC 报告概览（QCReport 契约）。"""
    reps = []
    for p in sorted(Path(qc_dir).glob("*.json")):
        try:
            reps.append(load_json(p))
        except Exception as e:
            log(f"[WARN] {p.name} 解析失败: {e}")
    decisions = Counter(r["verdict"]["decision"] for r in reps)
    detected = sum(1 for r in reps if r["verdict"]["defect_detected"])
    types = Counter(d["type"] for r in reps for d in r.get("defects", []))
    by = Counter(r["verdict"]["decided_by"] for r in reps)
    lines = [
        "## 2. QC 合议概览（来源：qc_reports/*.json）", "",
        f"- 报告数：{len(reps)}；检出 {detected}；decided_by={dict(by)}",
        f"- 处置分布：pass={decisions.get('pass', 0)} manual_review={decisions.get('manual_review', 0)} "
        f"auto_reject={decisions.get('auto_reject', 0)}",
        f"- 缺陷类型出现次数（defects 归并层，含信号）：",
    ]
    lines += [f"  - {t}: {n}" for t, n in types.most_common()]
    return lines, reps


def verify_manifest(manifest, clips):
    """manifest 完整性：metadata 的每条成片 sha256 是否能在 manifest 找到同 hash 条目。"""
    doc = load_json(manifest)
    have = {}
    for it in doc.get("items", []):
        have.setdefault(it.get("sha256"), it.get("asset_id"))
    hit = miss = 0
    for c in clips:
        if c.get("sha256") and c["sha256"] in have:
            hit += 1
        elif c.get("sha256"):
            miss += 1
    return doc, hit, miss


def main():
    ap = argparse.ArgumentParser(description="vpipe report：汇 metadata → 报告")
    ap.add_argument("--metadata", help="build_metadata.py 产出的 metadata.json")
    ap.add_argument("--qc-dir", default="out/qc_reports")
    ap.add_argument("--manifest", default="", help="asset_manifest.json（可选，做 hash 对账）")
    ap.add_argument("--out", default="out/report", help="输出基名（.md / .summary.json）")
    args = ap.parse_args()

    if not args.metadata and not Path(args.qc_dir).exists():
        log("[FATAL] --metadata 与 --qc-dir 至少给一个有效路径")
        return 1
    md, summary = [], {"generated_at": datetime.datetime.now().isoformat(timespec="seconds")}
    md.append(f"# vpipe 运行报告\n\n> 生成于 {summary['generated_at']}，由 report.py@vpipe1.0 汇总。\n")

    clips = []
    if args.metadata and Path(args.metadata).exists():
        meta = load_json(args.metadata)
        gen_lines, clips = summarize_generation(meta)
        md += gen_lines + [""]
        summary["generation"] = {"n_clips": len(clips)}
    elif args.metadata:
        log(f"[WARN] metadata 不存在: {args.metadata}")

    if Path(args.qc_dir).exists():
        qc_lines, reps = summarize_qc(args.qc_dir)
        md += qc_lines + ["", "### 2.1 逐 clip 处置表", "",
                          "| clip | detected | decision | confidence | decided_by |",
                          "|---|---|---|---|---|"]
        for r in reps:
            v = r["verdict"]
            md.append(f"| {r['clip_id']} | {v['defect_detected']} | {v['decision']} | "
                      f"{v['confidence']} | {v['decided_by']} |")
        summary["qc"] = {"n_reports": len(reps),
                         "detected": sum(1 for r in reps if r["verdict"]["defect_detected"])}
        md.append("")

    if args.manifest and Path(args.manifest).exists():
        doc, hit, miss = verify_manifest(args.manifest, clips)
        kinds = Counter(it.get("kind") for it in doc.get("items", []))
        note = ("（本 manifest 未登记 clip 类资产——clip 登记由 gen 模块产出时写入；"
                "此处对账只覆盖已登记部分）") if kinds.get("clip", 0) == 0 and clips else ""
        md += ["## 3. 资产登记对账（asset_manifest）", "",
               f"- manifest 条目：{len(doc.get('items', []))}（按 kind：{dict(kinds)}）",
               f"- metadata 成片 sha256 命中 {hit}、未登记 {miss} {note}",
               ""]
        summary["manifest"] = {"items": len(doc.get("items", [])), "kinds": dict(kinds),
                               "clip_hash_hit": hit, "clip_hash_missing": miss}

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".md").write_text("\n".join(md), encoding="utf-8")
    out.with_suffix(".summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"[done] {out.with_suffix('.md')} + {out.with_suffix('.summary.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
