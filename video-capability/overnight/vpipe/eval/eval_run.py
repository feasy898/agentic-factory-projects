#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
eval_run.py — vpipe 模块级评测器（SPEC.md 验收闸门）
对照: overnight/数据/score_golden_judges.py（今晚 judge 基准计分脚本，指标口径完全一致：
      正类=A 16 条注入缺陷，负类=C 12 条干净对照，检出=verdict.defect_detected，
      FPR=FP/12，B 类标签=expected_defect 推定 probable 单独计分）。

输入:
  --qc-dir     qc_orch.py 产出的 QCReport 目录（contracts/qc_report.schema.json）
  --golden     eval/golden_manifest.json（金标 manifest 拷贝）
  --thresholds eval/thresholds.yaml（准入线 eval_admission + 合议定义 ensemble）
  --schema     contracts/qc_report.schema.json（报告契约校验）
输出:
  --out        eval_results.json（全量指标 + 逐条对照 + PASS/FAIL）+ 控制台出分表
退出码: 0=全部准入线通过  1=有准入线未过（如实报差距，不许放水）  2=评测本身无效（输入缺失/契约损坏）

用法（验收全流程，两步）:
  python src/qc_orch.py --from-tonight --judges-root ../数据/judges \
      --golden ../eval/golden_manifest.json --thresholds ../eval/thresholds.yaml \
      --out-dir out/qc_reports --manifest out/asset_manifest.json
  python eval/eval_run.py --qc-dir out/qc_reports
"""
import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import yaml

HERE = Path(__file__).resolve().parent
TYPES8 = ["frame_freeze", "flicker", "color_shift", "face_blur",
          "garble_text", "temporal_swap", "pixelate", "ghosting"]
TYPE_ALIAS = {"text_error": "garble_text"}
# B 类意图标签 → 可接受类型集合（score_golden_judges.py:34-45 一致）
B_MAP_STRICT = {
    "hand_anatomy_distortion": {"hand_anomaly"},
    "text_render_garble": {"garble_text", "text_error"},
    "physics_temporal_violation": {"physics_error"},
    "count_error": {"count_error"},
}
B_MAP_LENIENT = {
    "hand_anatomy_distortion": {"hand_anomaly", "other"},
    "text_render_garble": {"garble_text", "text_error"},
    "physics_temporal_violation": {"physics_error", "temporal_swap", "other"},
    "count_error": {"count_error", "other"},
}


def norm_type(t):
    t = str(t).strip().lower()
    return TYPE_ALIAS.get(t, t)


def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def sha256_file(p):
    h = hashlib.sha256()
    h.update(Path(p).read_bytes())
    return h.hexdigest()


def f1_of(prec, rec):
    return (2 * prec * rec / (prec + rec)) if (prec is not None and prec + rec) else None


# ---------------------------------------------------------------- 评测
def evaluate(qc_dir, gold, admission):
    A = sorted(it["clip_id"] for it in gold["items"] if it["class"] == "A")
    B = sorted(it["clip_id"] for it in gold["items"] if it["class"] == "B")
    C = sorted(it["clip_id"] for it in gold["items"] if it["class"] == "C")
    gold_map = {it["clip_id"]: it for it in gold["items"]}

    problems = []
    if len(A) != admission["class_counts"]["A"] or len(B) != admission["class_counts"]["B"] \
            or len(C) != admission["class_counts"]["C"]:
        problems.append(f"金标类计数不符: A{len(A)}/B{len(B)}/C{len(C)} vs {admission['class_counts']}")
    if len(gold["items"]) < admission["min_clips_required"]:
        problems.append(f"金标条数 {len(gold['items'])} < min_clips_required={admission['min_clips_required']}")

    # 载入 QCReport + 契约校验
    verdicts, schema_bad = {}, []
    qc_dir = Path(qc_dir)
    for cid in A + B + C:
        p = qc_dir / f"{cid}.json"
        if not p.exists():
            problems.append(f"缺 QCReport: {p}")
            continue
        try:
            rep = load_json(p)
        except Exception as e:
            problems.append(f"QCReport 解析失败 {p}: {e}")
            continue
        v = rep.get("verdict") or {}
        if "defect_detected" not in v:
            problems.append(f"QCReport 无 verdict.defect_detected: {cid}")
            continue
        raw_types = [d.get("type") for d in (rep.get("defects") or [])]
        verdicts[cid] = {
            "detected": bool(v["defect_detected"]),
            "decision": v.get("decision"),
            "conf": v.get("confidence"),
            "decided_by": v.get("decided_by"),
            "types": [norm_type(t) for t in raw_types],
            "raw_types": raw_types,
            "thresholds_applied": (rep.get("scores") or {}).get("thresholds_applied") or {},
            "errors": rep.get("errors") or {},
        }
    if problems:
        return None, problems

    def metrics(det_ids):
        tp = sum(1 for c in A if det_ids(c))
        fp = sum(1 for c in C if det_ids(c))
        rec = tp / len(A)
        fpr = fp / len(C)
        prec = tp / (tp + fp) if tp + fp else None
        return {"tp": tp, "fn": len(A) - tp, "fp": fp, "tn": len(C) - fp,
                "recall": round(rec, 4), "fpr": round(fpr, 4),
                "precision": round(prec, 4) if prec is not None else None,
                "f1": round(f1_of(prec, rec), 4) if prec is not None else None}

    main_m = metrics(lambda c: verdicts[c]["detected"])

    per_type = {}
    for t in TYPES8:
        ids = [c for c in A if gold_map[c]["defect_type"] == t]
        per_type[t] = {
            "n": len(ids),
            "recall_clip": round(sum(1 for c in ids if verdicts[c]["detected"]) / len(ids), 4) if ids else None,
            "recall_type": round(sum(1 for c in ids if t in verdicts[c]["types"]) / len(ids), 4) if ids else None,
            "missed": [c for c in ids if not verdicts[c]["detected"]],
        }

    b_rows, b_flag, b_strict, b_lenient = [], 0, 0, 0
    for cid in B:
        exp = gold_map[cid]["expected_defect"]
        det = verdicts[cid]["detected"]
        tset = set(verdicts[cid]["types"])
        s = det and bool(tset & B_MAP_STRICT[exp])
        l = det and bool(tset & B_MAP_LENIENT[exp])
        b_flag += det
        b_strict += bool(s)
        b_lenient += bool(l)
        b_rows.append({"clip_id": cid, "expected": exp, "detected": det,
                       "types": verdicts[cid]["raw_types"], "strict_hit": bool(s),
                       "lenient_hit": bool(l)})
    b_m = {"n": len(B), "flag_rate": round(b_flag / len(B), 4),
           "intent_strict": round(b_strict / len(B), 4),
           "intent_lenient": round(b_lenient / len(B), 4), "rows": b_rows}

    fp_clips = [c for c in C if verdicts[c]["detected"]]
    fn_clips = [c for c in A if not verdicts[c]["detected"]]

    # 准入线判定
    checks = [
        ("recall_min", main_m["recall"] >= admission["recall_min"],
         f"recall {main_m['recall']} vs ≥{admission['recall_min']}"),
        ("fpr_max", main_m["fpr"] <= admission["fpr_max"],
         f"FPR {main_m['fpr']} vs ≤{admission['fpr_max']}"),
        ("f1_min", (main_m["f1"] or 0) >= admission["f1_min"],
         f"F1 {main_m['f1']} vs ≥{admission['f1_min']}"),
        ("b_flag_min", b_m["flag_rate"] >= admission["b_flag_min"],
         f"B_flag {b_m['flag_rate']} vs ≥{admission['b_flag_min']}"),
    ]
    return {"counts": {"A": len(A), "B": len(B), "C": len(C), "n_reports": len(verdicts)},
            "main": main_m, "per_type": per_type, "B": b_m,
            "fp_clips": fp_clips, "fn_clips": fn_clips,
            "decisions": {c: verdicts[c]["decision"] for c in A + C},
            "checks": [{"name": n, "passed": bool(p), "detail": d} for n, p, d in checks],
            "all_passed": all(c[1] for c in checks)}, problems


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="vpipe eval_run：模块级验收评测")
    ap.add_argument("--qc-dir", default=str(HERE.parent / "out" / "qc_reports"))
    ap.add_argument("--golden", default=str(HERE / "golden_manifest.json"))
    ap.add_argument("--thresholds", default=str(HERE / "thresholds.yaml"))
    ap.add_argument("--schema", default=str(HERE.parent / "contracts" / "qc_report.schema.json"))
    ap.add_argument("--out", default=str(HERE / "eval_results.json"))
    ap.add_argument("--skip-schema-check", action="store_true")
    args = ap.parse_args()

    gold = load_json(args.golden)
    thr_path = Path(args.thresholds)
    thr = yaml.safe_load(thr_path.read_text(encoding="utf-8"))
    admission = thr["eval_admission"]
    ens = thr["ensemble"]

    result = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "qc_dir": str(args.qc_dir),
        "golden": str(args.golden),
        "thresholds": str(args.thresholds),
        "thresholds_sha256": sha256_file(thr_path),
        "ensemble_recommended": ens["recommended"],
        "measured_baseline_报告E10": ens["measured_baseline"],
    }

    # 契约校验（全部报告过 schema）
    schema_problems = []
    if not args.skip_schema_check:
        try:
            import jsonschema
            schema = load_json(args.schema)
            validator = jsonschema.Draft7Validator(schema)
            for p in sorted(Path(args.qc_dir).glob("*.json")):
                errs = [f"{list(e.absolute_path)}: {e.message}" for e in validator.iter_errors(load_json(p))]
                if errs:
                    schema_problems.append({"file": p.name, "errors": errs[:5]})
        except ImportError:
            schema_problems.append({"file": "(all)", "errors": ["jsonschema 未安装，契约校验跳过"]})
        except Exception as e:
            schema_problems.append({"file": "(all)", "errors": [f"{type(e).__name__}: {e}"]})
    result["schema_check"] = {"skipped": bool(args.skip_schema_check),
                              "n_bad": len(schema_problems), "bad": schema_problems}

    metrics, problems = evaluate(args.qc_dir, gold, admission)
    if metrics is None:
        result["valid"] = False
        result["problems"] = problems
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        print("=== EVAL INVALID（评测本身无法进行） ===")
        for p in problems:
            print("  -", p)
        print("saved ->", args.out)
        return 2

    result["valid"] = True
    result["problems"] = problems
    result.update({k: metrics[k] for k in ("counts", "main", "per_type", "B",
                                           "fp_clips", "fn_clips", "decisions", "checks")})
    result["all_passed"] = metrics["all_passed"] and not schema_problems
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- 控制台出分表 ----
    m = metrics["main"]
    print("=== vpipe eval_run 出分（qc_orch 合议 vs 金标 A16正/C12负） ===")
    print(f"  检出口径: verdict.defect_detected  合议: {ens['recommended']}")
    print(f"  TP={m['tp']} FN={m['fn']} FP={m['fp']} TN={m['tn']}")
    print(f"  召回={m['recall']}  FPR={m['fpr']}  精确率={m['precision']}  F1={m['f1']}")
    b = metrics["B"]
    print(f"  B类: flag={b['flag_rate']} strict={b['intent_strict']} lenient={b['intent_lenient']} (n={b['n']})")
    print("  per-type（clip级/类型级）:")
    for t, pt in metrics["per_type"].items():
        print(f"    {t:14} {pt['recall_clip']}/{pt['recall_type']}  missed={pt['missed']}")
    base = ens["measured_baseline"]
    print(f"  对照 judge基准报告 E10 实测基线: R={base['recall']} FPR={base['fpr']} "
          f"F1={base['f1']} B_flag={base['b_flag_rate']}  "
          f"基线误报={base['fp_clips']}")
    print("  与基线偏差: "
          f"dR={round(m['recall'] - base['recall'], 4)} "
          f"dFPR={round(m['fpr'] - base['fpr'], 4)} "
          f"dF1={round((m['f1'] or 0) - base['f1'], 4)}")
    print("  本轮误报:", metrics["fp_clips"], " 漏检:", metrics["fn_clips"])
    print("  === 准入线（thresholds.yaml eval_admission） ===")
    for c in metrics["checks"]:
        print(f"    [{'PASS' if c['passed'] else 'FAIL'}] {c['name']}: {c['detail']}")
    print(f"    [{'PASS' if not schema_problems else 'FAIL'}] schema_check: "
          f"{len(schema_problems)} 份报告未过契约")
    verdict = "ACCEPT" if result["all_passed"] else "REJECT"
    print(f"  === 验收结论: {verdict} ===   (saved -> {args.out})")
    return 0 if result["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
