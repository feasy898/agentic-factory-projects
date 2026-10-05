#!/usr/bin/env python3
"""T1 验收评测（eval_seg；训练计划 T1 验收口径）。

对 prepare_coco 产出的评测集（holdout test / real_test）跑掩码 AP50 与
逐盘粒数 MAE，可选测速记录，按训练计划 T1 阈值裁决：

- 合成 holdout test 500 对：mask AP50 ≥ 0.90；粒数 MAE ≤3 粒/盘（≤300 粒盘）、
  ≤8 粒（>300 粒盘）；
- 真实盘（自采集 D4 实拍 20 张，人工核对粒数）：粒数误差 ≤10%；
- 推理速度：V100 单图 ≤400ms（1280 档）、ONNX Runtime CPU 2048² ≤8s（记录即可）。

指标口径（自实现，无 pycocotools 依赖）：mask AP50 为单 IoU 阈值 0.5 的
全点插值 AP（类内贪心匹配），见 ``train/_metrics.py`` 模块注释——与多 IoU
平均 mAP 非同一口径，报告时如实标注。

输入目录约定
    ``--data-dir``：COCO 评测目录（_annotations.coco.json + 图像，即
    ``<数据集根>/test`` 或 ``real_test``）。

输出（默认 ``train/runs/eval/``）
    ``eval_seg_<数据目录名>.json``（逐类 AP/粒数分桶/测速/门槛裁决）；
    确定性命名（不带时间戳），重复评测覆盖并在 json 里记录输入的 sha256。

期望运行时长
    GPU（V100S）：500 对 × 2 档 ≈ 10–20 min；CPU 小样本（--max-images）分钟级。

失败回退
    评测为只读操作；--check-gates 未达阈值 exit 1（验收口径），其余失败 exit 1
    并保留已有报告文件。

GPU 机执行顺序
    T0 → T1（det_finetune）→ **本脚本（T1 验收）** → T2/T3；
    数据/权重经 COS 中转（跨机不直传）。

--dry-run：纯离线——校验参数、打印指标定义与门槛、对存在的数据目录做
GT 结构离线统计（stdlib json，不触碰掩码），exit 0。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import _common
from _common import EXIT_USAGE, PlanReporter, resolve_path, save_json

# 训练计划 T1 验收阈值（口径出处：plan--咖啡豆质检/training-plan.md T1 节）
GATES_SYNTH = {"mask_ap50_min": 0.90, "mae_le_max": 3.0, "mae_gt_max": 8.0}
GATES_REAL = {"count_rel_err_max": 0.10}  # 真实盘粒数相对误差 ≤10%
BENCH_NOTES = "V100 单图 ≤400ms(1280)；ONNX CPU 2048² ≤8s——记录即可，不作门槛"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="T1 验收评测：掩码 AP50 + 粒数 MAE + 测速记录（--dry-run 纯离线）",
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="不推理/不写报告，只校验并打印评测计划（离线，exit 0）")
    ap.add_argument("--data-dir", default="train/runs/datasets/v1/test",
                    help="COCO 评测目录（_annotations.coco.json + 图像）")
    ap.add_argument("--checkpoint", default=None, help="T1 checkpoint（.pth；与 --onnx 二选一）")
    ap.add_argument("--onnx", default=None, help="ONNX 模型（部署形态评测）")
    ap.add_argument("--variant", choices=("small", "nano"), default="small",
                    help="checkpoint 路线的模型型号（须与训练一致）")
    ap.add_argument("--device", default="cuda:0", help="推理设备（CPU 小样本用 cpu）")
    ap.add_argument("--score-threshold", type=float, default=0.5, help="检测分数阈值")
    ap.add_argument("--resolutions", default="1024,1280",
                    help="评估分辨率档（逗号分隔；计划 T1：密集盘 1280 两档）")
    ap.add_argument("--count-bucket-split", type=int, default=300,
                    help="粒数 MAE 分桶界（真值粒数 ≤N / >N；计划 T1 = 300）")
    ap.add_argument("--max-images", type=int, default=0,
                    help="限制评测图像数（CPU 小样本；0=全量）")
    ap.add_argument("--gate-set", choices=("synth", "real"), default="synth",
                    help="验收门槛组：synth=AP50+分桶 MAE；real=粒数相对误差 ≤10%%")
    ap.add_argument("--class-id-offset", type=int, default=0,
                    help="预测 class_id + offset = COCO category_id（框架把 1..13 压成 0..12 时填 1）")
    ap.add_argument("--benchmark", action="store_true",
                    help="记录推理延迟（均值/分位；记录用，不作门槛）")
    ap.add_argument("--report", default=None,
                    help="报告 json 路径（默认 train/runs/eval/eval_seg_<目录名>.json）")
    ap.add_argument("--check-gates", action="store_true",
                    help="按训练计划 T1 阈值裁决；未达 → exit 1（验收口径）")
    return ap


# ---------------------------------------------------------------------------
# GT 装载与离线统计
# ---------------------------------------------------------------------------


def gt_stats_offline(data_dir: Path) -> dict:
    """仅结构统计（dry-run 用；不解码掩码）。"""
    json_path = data_dir / "_annotations.coco.json"
    if not json_path.is_file():
        raise FileNotFoundError(f"缺标注文件: {json_path}")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    images = data.get("images", [])
    counts: dict[int, int] = {}
    for ann in data.get("annotations", []):
        cid = int(ann.get("category_id", -1))
        counts[cid] = counts.get(cid, 0) + 1
    per_img = [0] * len(images)
    idx = {int(i["id"]): k for k, i in enumerate(images)}
    for ann in data.get("annotations", []):
        k = idx.get(int(ann["image_id"]))
        if k is not None:
            per_img[k] += 1
    return {
        "n_images": len(images),
        "n_annotations": len(data.get("annotations", [])),
        "gt_count_per_image_min": min(per_img) if per_img else 0,
        "gt_count_per_image_max": max(per_img) if per_img else 0,
        "annotations_by_category": dict(sorted(counts.items())),
        "missing_files": sum(
            1 for i in images if not (data_dir / str(i.get("file_name", ""))).is_file()
        ),
    }


# ---------------------------------------------------------------------------
# dry-run
# ---------------------------------------------------------------------------


def dry_run(args: argparse.Namespace, rep: PlanReporter) -> int:
    rep.header("eval_seg.py", "T1 验收评测（掩码 AP50 + 粒数 MAE）")
    if not args.checkpoint and not args.onnx:
        rep.missing("评测对象（--checkpoint 或 --onnx）：T1 产物，GPU 机提供")
    elif args.checkpoint and args.onnx:
        rep.error("--checkpoint 与 --onnx 只能二选一")

    rep.section("1. 评测对象")
    data_dir = resolve_path(args.data_dir)
    if data_dir.is_dir():
        rep.ok(f"评测集: {data_dir}")
        try:
            st = gt_stats_offline(data_dir)
            rep.ok(
                f"GT 统计：图像 {st['n_images']}，标注 {st['n_annotations']}，"
                f"每盘粒数 [{st['gt_count_per_image_min']}, {st['gt_count_per_image_max']}]，"
                f"磁盘缺图 {st['missing_files']}"
            )
            if st["missing_files"]:
                rep.error(f"{st['missing_files']} 个 file_name 在磁盘缺失")
            if args.max_images:
                rep.plan(f"--max-images={args.max_images}（CPU 小样本口径）")
        except (ValueError, FileNotFoundError) as exc:
            rep.error(str(exc))
    else:
        rep.missing(f"评测集: {data_dir}（prepare_coco 产物）")
    model_raw = args.checkpoint or args.onnx
    if model_raw:
        rep.check_file(resolve_path(model_raw), "模型")
    rep.plan(f"路线：{'checkpoint（' + args.variant + '）' if args.checkpoint else 'ONNX（onnxruntime）'}；"
             f"device={args.device}，score>={args.score_threshold}")
    rep.plan(f"分辨率档：{args.resolutions}（逐档分别评测并分别裁决）")
    rep.plan(f"class_id_offset={args.class_id_offset}（框架类别 id 压缩校正，README 核对节）")

    rep.section("2. 指标定义（自实现口径）")
    rep.plan("mask AP50：单 IoU 阈值 0.5 全点插值 AP，类内贪心匹配（train/_metrics.py）；"
             "≠ 多 IoU 平均 mAP，报告如实标注")
    rep.plan(f"粒数 MAE：逐盘 |预测−真值|，按真值粒数 ≤{args.count_bucket_split} / "
             f">{args.count_bucket_split} 分桶")
    rep.plan(f"测速：--benchmark 记录逐图延迟（{BENCH_NOTES}）")

    rep.section("3. 验收门槛（训练计划 T1）")
    if args.gate_set == "synth":
        rep.plan(f"mask AP50 ≥ {GATES_SYNTH['mask_ap50_min']}；"
                 f"MAE(≤{args.count_bucket_split} 粒盘) ≤ {GATES_SYNTH['mae_le_max']}；"
                 f"MAE(>{args.count_bucket_split} 粒盘) ≤ {GATES_SYNTH['mae_gt_max']}")
    else:
        rep.plan(f"真实盘粒数相对误差 ≤ {GATES_REAL['count_rel_err_max']:.0%}（人工核对粒数为基准）")
    rep.plan(f"--check-gates 未达 → exit 1；报告 → {args.report or 'train/runs/eval/eval_seg_<目录名>.json'}")
    rep.warn("评测顺序：T1 训练完成 → 本脚本验收 → T2/T3；数据/权重经 COS 中转")
    return rep.finish()


# ---------------------------------------------------------------------------
# 真实执行
# ---------------------------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    import cv2

    import _metrics
    import _predict

    data_dir = resolve_path(args.data_dir)
    images, gt_anns, stats = _gt_load(data_dir, args.max_images)
    if stats["missing_files"]:
        print(f"[警告] {stats['missing_files']} 个 file_name 缺失，对应图像跳过")

    resolutions = [int(r) for r in str(args.resolutions).split(",") if r.strip()]
    report: dict = {
        "script": "train/eval_seg.py",
        "data_dir": str(data_dir),
        "gate_set": args.gate_set,
        "input_sha256": _file_sha(data_dir / "_annotations.coco.json"),
        "gt_stats": stats,
        "score_threshold": args.score_threshold,
        "route": "checkpoint" if args.checkpoint else "onnx",
        "resolutions": {},
    }

    for res in resolutions:
        print(f"[eval_seg] 分辨率 {res}：加载模型…", flush=True)
        if args.checkpoint:
            predictor = _predict.CheckpointPredictor(
                args.checkpoint, device=args.device, resolution=res,
                variant=args.variant, score_thr=args.score_threshold,
            )
        else:
            predictor = _predict.OnnxPredictor(
                args.onnx, score_thr=args.score_threshold,
                class_id_offset=args.class_id_offset,
            )
        gts_by_img: list[list] = []
        preds_by_img: list[list] = []
        latencies: list[float] = []
        n_done = 0
        n_skipped_missing = 0
        for img_entry, anns in zip(images, gt_anns):
            f = data_dir / str(img_entry["file_name"])
            if not f.is_file():
                # 缺图盘**整体剔除**出指标样本（不追加空对）：空对会被
                # counting_mae 按误差 0 计入，缺图越多 MAE 越被乐观稀释（复核项）
                n_skipped_missing += 1
                continue
            bgr = cv2.imread(str(f))  # noqa: PTH stub（中文路径红线见下方 imdecode 版）
            if bgr is None:
                buf = np_fromfile(f)
                bgr = cv2.imdecode(buf, cv2.IMREAD_COLOR)
            if bgr is None:
                raise ValueError(f"图像解码失败: {f}")
            gts = [_metrics.ann_to_instance(a, bgr.shape[1], bgr.shape[0]) for a in anns]
            t0 = time.perf_counter()
            preds = predictor.predict(bgr)
            if args.benchmark:
                latencies.append(time.perf_counter() - t0)
            gts_by_img.append(gts)
            preds_by_img.append(preds)
            n_done += 1
            if n_done % 50 == 0:
                print(f"[eval_seg] {res}: {n_done}/{len(images)} 图完成", flush=True)
        if n_skipped_missing:
            print(f"[eval_seg] {res}: 缺图剔除 {n_skipped_missing} 盘（不计入指标）")

        ap = _metrics.evaluate_ap50(
            gts_by_img, preds_by_img, class_id_offset=args.class_id_offset
        )
        mae = _metrics.counting_mae(
            gts_by_img, preds_by_img, bucket_split=args.count_bucket_split
        )
        node: dict = {
            "ap50": ap,
            "counting_mae": mae,
            "n_images_evaluated": len(gts_by_img),
            "n_skipped_missing": n_skipped_missing,
        }
        if args.benchmark and latencies:
            lat = sorted(latencies)
            node["latency_s"] = {
                "n": len(lat),
                "mean": round(sum(lat) / len(lat), 4),
                "p50": round(lat[len(lat) // 2], 4),
                "p95": round(lat[int(len(lat) * 0.95)], 4),
                "max": round(lat[-1], 4),
            }
        if args.gate_set == "synth":
            mae_le = mae["le"]["mae"]
            mae_gt = mae["gt"]["mae"]
            gates = {
                "mask_ap50_min": GATES_SYNTH["mask_ap50_min"],
                "mae_le_max": GATES_SYNTH["mae_le_max"],
                "mae_gt_max": GATES_SYNTH["mae_gt_max"],
                "measured": {
                    "macro_ap50": ap["macro_ap50"],
                    "mae_le": mae_le,
                    "mae_gt": mae_gt,
                },
            }
        else:
            # 真实盘门槛：**逐盘**粒数相对误差（|pred−gt| / 该盘 gt 数）的均值
            # ≤10%（训练计划 T1「粒数误差 ≤10%」的盘级口径；不得用总体 MAE ÷
            # 标注总数——量纲错、会被低估 N_images 倍，复核项实测）
            gates = {
                "count_rel_err_max": GATES_REAL["count_rel_err_max"],
                "measured": {
                    "rel_err_mean": mae["rel_err_mean"],
                    "rel_err_max": mae["rel_err_max"],
                    "mae_overall": mae["mae_overall"],
                    "n_images_evaluated": len(gts_by_img),
                },
            }
        node["gates"] = gates
        node["gates_pass"] = _gates_pass(gates)
        report["resolutions"][str(res)] = node
        print(
            f"[eval_seg] {res}: macro AP50={ap['macro_ap50']} "
            f"MAE(≤{args.count_bucket_split})={mae['le']['mae']} "
            f"MAE(>{args.count_bucket_split})={mae['gt']['mae']} "
            f"gates_pass={node['gates_pass']}",
            flush=True,
        )

    out = resolve_path(args.report) if args.report else (
        resolve_path("train/runs/eval") / f"eval_seg_{data_dir.name}.json"
    )
    save_json(out, report)
    print(f"[eval_seg] 报告: {out}")
    if args.check_gates:
        worst = all(n["gates_pass"] for n in report["resolutions"].values())
        if not worst:
            print("[eval_seg] 未达训练计划 T1 验收阈值（--check-gates → exit 1）")
            return 1
        print("[eval_seg] 达到训练计划 T1 验收阈值")
    return 0


def _gt_load(data_dir: Path, max_images: int) -> tuple[list[dict], list[list], dict]:
    """真实分支 GT 装载（同 dry-run 统计口径，返回 ann dict 列表）。"""
    json_path = data_dir / "_annotations.coco.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    images = data.get("images", [])
    if max_images:
        images = images[:max_images]
    keep_ids = {int(i["id"]) for i in images}
    anns_by_img: dict[int, list[dict]] = {int(i["id"]): [] for i in images}
    for ann in data.get("annotations", []):
        iid = int(ann["image_id"])
        if iid in keep_ids:
            anns_by_img[iid].append(ann)
    gt_lists = [anns_by_img[int(i["id"])] for i in images]
    stats = {
        "n_images": len(images),
        "n_annotations": sum(len(a) for a in gt_lists),
        "missing_files": sum(
            1 for i in images if not (data_dir / str(i.get("file_name", ""))).is_file()
        ),
    }
    return images, gt_lists, stats


def _file_sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    return _common.sha256_file(path)


def _gates_pass(gates: dict) -> bool:
    m = gates["measured"]
    if gates.get("mask_ap50_min") is not None:
        return (
            m["macro_ap50"] is not None
            and m["macro_ap50"] >= gates["mask_ap50_min"]
            and m["mae_le"] is not None and m["mae_le"] <= gates["mae_le_max"]
            and m["mae_gt"] is not None and m["mae_gt"] <= gates["mae_gt_max"]
        )
    return (
        m["rel_err_mean"] is not None
        and m["rel_err_mean"] <= gates["count_rel_err_max"]
    )


def np_fromfile(path: Path) -> "object":
    """中文路径红线：cv2.imread 失败回退 imdecode（与本仓 acquisition 同思想）。"""
    import numpy as np

    return np.frombuffer(path.read_bytes(), dtype=np.uint8)


def main() -> int:
    _common.setup_console()
    args = build_parser().parse_args()
    if args.score_threshold <= 0 or args.score_threshold >= 1:
        print("[错误] --score-threshold 须在 (0,1)")
        return EXIT_USAGE
    if not args.dry_run and not (args.checkpoint or args.onnx):
        print("[错误] 真实模式必须提供 --checkpoint 或 --onnx 之一")
        return EXIT_USAGE
    if args.checkpoint and args.onnx:
        print("[错误] --checkpoint 与 --onnx 只能二选一")
        return EXIT_USAGE
    if args.max_images < 0 or args.count_bucket_split <= 0:
        print("[错误] --max-images 须 >=0；--count-bucket-split 须 >0")
        return EXIT_USAGE
    if args.dry_run:
        rep = PlanReporter(dry_run=True)
        return dry_run(args, rep)
    try:
        return run(args)
    except (RuntimeError, ValueError, FileNotFoundError, ImportError) as exc:
        print(f"[FAIL] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
