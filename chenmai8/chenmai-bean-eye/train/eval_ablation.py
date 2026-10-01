#!/usr/bin/env python3
"""T2 单面/双面消融评测（eval_ablation；训练计划 T2 实验矩阵）。

同一 T1 模型 + 同一 test 集（成对 top/bottom、带 bean_id 的合成 holdout）上
跑三配置，产出论文级「双面刚需」证据链：

| 配置 | 输入 | 配对 | 计数/类别规则 |
|---|---|---|---|
| A 单面-top | 仅 top | 无 | 每粒计 top 标签 |
| B 单面-bottom | 仅 bottom | 无 | 每粒计 bottom 标签 |
| C 双面（ours） | top+bottom | 匈牙利 | 每粒取最严重面（severity_order） |

报告（--out，默认 train/runs/eval/ablation.json；训练计划 T2 提到 out/ablation.json，
可用 --out out/ablation.json 对齐旧口径）：三配置逐豆 macro-F1 表 + per-class
F1 + 配对贡献分解（配对成功/未配对粒子集的 F1）+ 单面可见缺陷漏检统计；
门槛：C 相对 A 的 macro-F1 提升 ≥0.05 才算「可写进 PPT」，不足时如实输出
``below_threshold=true``（exit 仍 0——如实报告也是验收口径的一部分）。

口径注记：合成集按 M12 成对语义上下**同类**（class_top == class_bottom），
「仅单面可见缺陷」在该数据上恒为 0——该指标为真实双面真值数据预留，
本脚本自动计算、数据不含此类粒时如实标注 n_applicable=0。

输入目录约定
    ``--data-dir``：成对 COCO 评测目录（_annotations.coco.json + 图像；
    标注须带 bean_id/side/class_top/class_bottom 扩展字段——prepare_coco 产物）。

期望运行时长
    V100S：500 对 × 2 面推理 ≈ 8–15 min；CPU 小样本（--max-pairs）分钟级。

失败回退
    只读评测；预测可 --cache-predictions 落盘复用（A/B/C 共享一次推理）。

GPU 机执行顺序
    T0 → T1（det_finetune）→ T1 验收（eval_seg）→ **本脚本（T2）**；
    第二卡可并行跑 T3 混入档训练；数据/权重经 COS 中转（跨机不直传）。

--dry-run：纯离线——校验参数、打印实验矩阵与门槛、对数据目录做成对结构
离线统计（stdlib json），exit 0。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import _common
from _common import EXIT_USAGE, PlanReporter, resolve_path, save_json

MIN_GAIN_DEFAULT = 0.05  # 计划 T2：C−A 平均单类 F1 提升 ≥0.05 才写进 PPT


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="T2 单面/双面消融：A/B/C 三配置逐豆 F1（--dry-run 纯离线）",
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="不推理/不写报告，只校验并打印实验计划（离线，exit 0）")
    ap.add_argument("--data-dir", default="train/runs/datasets/v1/test",
                    help="成对 COCO 评测目录（prepare_coco 的 holdout test）")
    ap.add_argument("--checkpoint", default=None, help="T1 checkpoint（与 --onnx 二选一）")
    ap.add_argument("--onnx", default=None, help="ONNX 模型")
    ap.add_argument("--variant", choices=("small", "nano"), default="small",
                    help="checkpoint 路线模型型号（须与训练一致）")
    ap.add_argument("--device", default="cuda:0", help="推理设备")
    ap.add_argument("--score-threshold", type=float, default=0.5, help="检测分数阈值")
    ap.add_argument("--resolution", type=int, default=1024, help="推理分辨率")
    ap.add_argument("--pair-iou", type=float, default=0.3,
                    help="双面配对 IoU 可行阈值（匈牙利）")
    ap.add_argument("--pair-max-dist-px", type=float, default=80.0,
                    help="双面配对质心距上限 px（翻面横移容差）")
    ap.add_argument("--match-iou", type=float, default=0.5, help="预测↔真值匹配 IoU")
    ap.add_argument("--class-id-offset", type=int, default=0,
                    help="预测 class_id + offset = COCO category_id（与 eval_seg 同口径）")
    ap.add_argument("--max-pairs", type=int, default=0, help="限制评测盘对数（CPU 小样本；0=全量）")
    ap.add_argument("--min-gain", type=float, default=MIN_GAIN_DEFAULT,
                    help=f"C−A macro-F1 提升门槛（计划 T2 = {MIN_GAIN_DEFAULT}）")
    ap.add_argument("--out", default="train/runs/eval/ablation.json",
                    help="报告 json（相对仓库根）")
    return ap


# ---------------------------------------------------------------------------
# 成对数据装载
# ---------------------------------------------------------------------------


def load_pairs(data_dir: Path, max_pairs: int = 0) -> tuple[list[dict], dict]:
    """把 COCO 目录组织成盘对：[(pair_key, top_img, bottom_img)], 逐对 GT。

    side 优先取 image 条目的 ``side`` 字段，缺失时按文件名前缀 top_/bottom_
    判定；GT ann 按 (pair_key, bean_id) 归组（合成 holdout 每粒上下共享
    bean_id——prepare_coco 扩展字段）。
    """
    json_path = data_dir / "_annotations.coco.json"
    if not json_path.is_file():
        raise FileNotFoundError(f"缺标注文件: {json_path}")
    data = json.loads(json_path.read_text(encoding="utf-8"))

    def _side_of(img: dict) -> str | None:
        side = img.get("side")
        if side in ("top", "bottom"):
            return str(side)
        name = str(img.get("file_name", ""))
        if name.startswith("top_"):
            return "top"
        if name.startswith("bottom_"):
            return "bottom"
        return None

    tops: dict[str, dict] = {}
    bottoms: dict[str, dict] = {}
    for img in data.get("images", []):
        side = _side_of(img)
        key = Path(str(img.get("file_name", ""))).stem
        for prefix in ("top_", "bottom_"):
            if key.startswith(prefix):
                key = key[len(prefix):]
                break
        if side == "top":
            tops[key] = img
        elif side == "bottom":
            bottoms[key] = img
    pair_keys = sorted(set(tops) & set(bottoms))
    only_one_side = (set(tops) ^ set(bottoms)) - set(pair_keys)
    if not pair_keys:
        raise ValueError(
            f"目录中未找到成对图像（top/bottom 同 stem 配对）: {data_dir}"
        )
    if max_pairs:
        pair_keys = pair_keys[:max_pairs]

    anns_by_img: dict[int, list[dict]] = {int(i["id"]): [] for i in data.get("images", [])}
    for ann in data.get("annotations", []):
        iid = int(ann["image_id"])
        if iid in anns_by_img:
            anns_by_img[iid].append(ann)

    pairs: list[dict] = []
    for key in pair_keys:
        ti, bi = tops[key], bottoms[key]
        gt_by_bean: dict[str, dict] = {}
        for side, img in (("top", ti), ("bottom", bi)):
            for ann in anns_by_img.get(int(img["id"]), []):
                bean_id = ann.get("bean_id")
                if bean_id is None:
                    raise ValueError(
                        "消融要求标注带 bean_id 扩展字段（prepare_coco 产物）；"
                        f"缺字段：{data_dir} image_id={img['id']}"
                    )
                node = gt_by_bean.setdefault(str(bean_id), {})
                node[f"class_{side}"] = ann.get(f"class_{side}") or ann.get("category_id")
                node.setdefault("anns", {})[side] = ann
        pairs.append({
            "key": key,
            "top": ti,
            "bottom": bi,
            "gt_beans": gt_by_bean,
        })
    stats = {
        "n_images": len(data.get("images", [])),
        "n_pairs": len(pair_keys),
        "only_one_side": len(only_one_side),
        "n_annotations": len(data.get("annotations", [])),
    }
    return pairs, stats


def offline_pair_stats(pairs: list[dict]) -> dict:
    """离线统计：GT 类别直方 / 上下异类粒数（单面可见缺陷的承载指标）。"""
    cls_top: Counter = Counter()
    diffs = 0
    n_beans = 0
    for p in pairs:
        for bean in p["gt_beans"].values():
            n_beans += 1
            ct = bean.get("class_top")
            cb = bean.get("class_bottom")
            if isinstance(ct, int) or isinstance(cb, int):
                continue  # 无扩展类别字段（外部数据）不计
            cls_top[ct] += 1
            if ct != cb:
                diffs += 1
    return {
        "n_beans": n_beans,
        "class_top_hist": dict(sorted(cls_top.items())),
        "n_top_bottom_class_diff": diffs,
    }


# ---------------------------------------------------------------------------
# dry-run
# ---------------------------------------------------------------------------


def dry_run(args: argparse.Namespace, rep: PlanReporter) -> int:
    rep.header("eval_ablation.py", "T2 单面/双面消融（A/B/C）")
    if not args.checkpoint and not args.onnx:
        rep.missing("评测对象（--checkpoint 或 --onnx）：T1 产物，GPU 机提供")

    rep.section("1. 数据（成对 test 集）")
    data_dir = resolve_path(args.data_dir)
    if data_dir.is_dir():
        try:
            pairs, stats = load_pairs(data_dir, args.max_pairs)
            rep.ok(
                f"成对评测集: {data_dir}（盘对 {stats['n_pairs']}，单面落单 "
                f"{stats['only_one_side']}，标注 {stats['n_annotations']}）"
            )
            st = offline_pair_stats(pairs)
            rep.plan(f"GT 逐豆统计：{st['n_beans']} 粒；上下异类 {st['n_top_bottom_class_diff']} 粒"
                     "（=「仅单面可见缺陷」承载指标；合成集按 M12 同类语义通常为 0）")
        except (ValueError, FileNotFoundError) as exc:
            rep.error(str(exc))
    else:
        rep.missing(f"成对评测集: {data_dir}（prepare_coco holdout test）")
    model_raw = args.checkpoint or args.onnx
    if model_raw:
        rep.check_file(resolve_path(model_raw), "模型")

    rep.section("2. 实验矩阵（同一模型、同一 test 集）")
    rep.plan("A 单面-top：仅 top 推理，逐豆计 top 标签；真值 = class_top")
    rep.plan("B 单面-bottom：仅 bottom 推理，逐豆计 bottom 标签；真值 = class_bottom")
    rep.plan("C 双面（ours）：top+bottom 推理 → 匈牙利配对（IoU≥"
             f"{args.pair_iou} 或质心距≤{args.pair_max_dist_px:.0f}px）→ 逐豆取最严重面"
             "（taxonomy severity_order）；真值 = max(class_top, class_bottom)")
    rep.plan(f"匹配：逐豆 IoU≥{args.match_iou} 类内贪心；指标：per-class F1 + macro-F1（自实现口径）")
    rep.plan(f"推理：{args.resolution} 分辨率，score>={args.score_threshold}，"
             f"device={args.device}，max_pairs={args.max_pairs or '全量'}")

    rep.section("3. 报告与门槛（训练计划 T2）")
    out = resolve_path(args.out)
    rep.plan(f"报告: {out}（三配置 F1 表 + 配对贡献分解 + 单面可见缺陷统计）")
    rep.plan(
        f"门槛：C − A macro-F1 ≥ {args.min_gain} → 「可写进 PPT」；不足 → "
        "below_threshold=true 如实报告（exit 0）"
    )
    rep.warn("执行顺序：T1 训练 → T1 验收（eval_seg）→ 本脚本；第二卡可并行 T3")
    return rep.finish()


# ---------------------------------------------------------------------------
# 真实执行
# ---------------------------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    import cv2

    import _metrics
    import _predict

    data_dir = resolve_path(args.data_dir)
    pairs, stats = load_pairs(data_dir, args.max_pairs)
    cats, tax = _common.build_categories()
    id2name = {int(c["id"]): c["name"] for c in cats}
    name2id = _common.categories_by_name(cats)
    offset = args.class_id_offset

    def _sev_max(cls_a: str | None, cls_b: str | None) -> str | None:
        """两面类别取更严重者（taxonomy severity_order；None 取另一面）。"""
        if cls_a is None:
            return cls_b
        if cls_b is None:
            return cls_a
        return cls_a if tax.severity_rank(cls_a) >= tax.severity_rank(cls_b) else cls_b

    print(f"[ablation] 盘对 {len(pairs)}，模型加载…", flush=True)
    if args.checkpoint:
        predictor = _predict.CheckpointPredictor(
            args.checkpoint, device=args.device, resolution=args.resolution,
            variant=args.variant, score_thr=args.score_threshold,
        )
    else:
        predictor = _predict.OnnxPredictor(
            args.onnx, score_thr=args.score_threshold,
            class_id_offset=args.class_id_offset,
        )

    # ---- 每面推理一次（A/B/C 共享） ----------------------------------------
    def _read(path: Path):
        img = cv2.imdecode(np_frombytes(path), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"图像解码失败: {path}")
        return img

    def _pred(img_entry: dict) -> list:
        f = data_dir / str(img_entry["file_name"])
        return predictor.predict(_read(f))

    buckets = {"A": ([], []), "B": ([], []), "C": ([], [])}  # 配置 → (gts, preds)
    c_unpaired_pred: list = []  # 配对贡献分解：C 中未配对预测粒
    c_paired_pred: list = []
    single_side_total = single_side_applicable = 0
    n_done = 0

    for p in pairs:
        pred_top = _pred(p["top"])
        pred_bot = _pred(p["bottom"])
        w = int(p["top"].get("width", 0)) or 2048
        h = int(p["top"].get("height", 0)) or 2048

        # GT 实例（逐面解码一次）
        gt_top: dict[str, object] = {}
        gt_bot: dict[str, object] = {}
        for bean_id, node in p["gt_beans"].items():
            for side, store in (("top", gt_top), ("bottom", gt_bot)):
                ann = node.get("anns", {}).get(side)
                if ann is not None:
                    inst = _metrics.ann_to_instance(ann, w, h)
                    store[bean_id] = inst

        # A / B：单面逐豆
        buckets["A"][0].extend(gt_top.values())
        buckets["A"][1].extend(_relabel_list(pred_top, offset, id2name, name2id))
        buckets["B"][0].extend(gt_bot.values())
        buckets["B"][1].extend(_relabel_list(pred_bot, offset, id2name, name2id))

        # C：匈牙利配对 → 最严重面
        paired, un_t, un_b = _metrics.pair_top_bottom(
            pred_top, pred_bot,
            iou_thr=args.pair_iou, max_dist_px=args.pair_max_dist_px,
        )
        gt_c: list = []
        pred_c: list = []
        for bean_id, node in p["gt_beans"].items():
            truth = _sev_max(
                _as_name(node.get("class_top"), id2name),
                _as_name(node.get("class_bottom"), id2name),
            )
            inst = gt_top.get(bean_id) or gt_bot.get(bean_id)
            if inst is None:
                continue
            gt_c.append(_with_class(inst, name2id[truth]))  # type: ignore[index]
            ct = _as_name(node.get("class_top"), id2name)
            cb = _as_name(node.get("class_bottom"), id2name)
            single_side_total += 1
            if ct != cb and _is_defect_diff(ct, cb, tax):
                single_side_applicable += 1
        for i, j in paired:
            name_t = id2name.get(pred_top[i].category_id + offset)
            name_b = id2name.get(pred_bot[j].category_id + offset)
            bean = _with_class(pred_top[i], name2id[_sev_max(name_t, name_b)])  # type: ignore[index]
            pred_c.append(bean)
            c_paired_pred.append(bean)
        for i in un_t:
            name_t = id2name.get(pred_top[i].category_id + offset)
            bean = _with_class(pred_top[i], name2id[name_t])  # type: ignore[index]
            pred_c.append(bean)
            c_unpaired_pred.append(bean)
        for j in un_b:
            name_b = id2name.get(pred_bot[j].category_id + offset)
            bean = _with_class(pred_bot[j], name2id[name_b])  # type: ignore[index]
            pred_c.append(bean)
            c_unpaired_pred.append(bean)
        buckets["C"][0].extend(gt_c)
        buckets["C"][1].extend(pred_c)

        n_done += 1
        if n_done % 25 == 0:
            print(f"[ablation] {n_done}/{len(pairs)} 盘对完成", flush=True)

    report: dict = {
        "script": "train/eval_ablation.py",
        "data_dir": str(data_dir),
        "n_pairs": len(pairs),
        "pair_stats": stats,
        "match_iou": args.match_iou,
        "pairing": {"iou_thr": args.pair_iou, "max_dist_px": args.pair_max_dist_px},
        "configs": {},
    }
    for cfg_name, (gts, preds) in buckets.items():
        prf = _metrics.prf_from_matches(
            gts, preds, iou_thr=args.match_iou, class_id_offset=0
        )
        report["configs"][cfg_name] = prf
        print(
            f"[ablation] {cfg_name}: macro-F1={prf['macro_f1']} "
            f"P={prf['precision']} R={prf['recall']}",
            flush=True,
        )

    # 配对贡献分解（C 内部：配对 vs 未配对预测粒对同一 GT 全集）
    report["pairing_contribution"] = {
        "n_pred_beans_paired": len(c_paired_pred),
        "n_pred_beans_unpaired": len(c_unpaired_pred),
        "f1_paired_subset": _metrics.prf_from_matches(
            buckets["C"][0], c_paired_pred, iou_thr=args.match_iou
        )["f1"] if c_paired_pred else None,
        "f1_unpaired_subset": _metrics.prf_from_matches(
            buckets["C"][0], c_unpaired_pred, iou_thr=args.match_iou
        )["f1"] if c_unpaired_pred else None,
    }
    report["single_side_defect"] = {
        "n_beans_total": single_side_total,
        "n_single_side_visible": single_side_applicable,
        "rate": (
            round(single_side_applicable / single_side_total, 6)
            if single_side_total else None
        ),
        "note": "合成集按 M12 成对语义上下同类，此指标通常为 0；真实双面真值数据接入后自动生效",
    }

    macro_a = report["configs"]["A"]["macro_f1"]
    macro_c = report["configs"]["C"]["macro_f1"]
    gain = None if (macro_a is None or macro_c is None) else round(macro_c - macro_a, 6)
    report["gate"] = {
        "min_gain": args.min_gain,
        "macro_f1_A": macro_a,
        "macro_f1_C": macro_c,
        "c_minus_a": gain,
        "pass": gain is not None and gain >= args.min_gain,
        "note": "C 相对 A 提升 ≥ 门槛才写进 PPT；不足时如实报告（计划 T2 口径）",
    }
    out = resolve_path(args.out)
    save_json(out, report)
    print(f"[ablation] 报告: {out}")
    print(f"[ablation] C−A macro-F1 = {gain}（门槛 {args.min_gain}，pass={report['gate']['pass']}）")
    return 0


# ---------------------------------------------------------------------------
# 小工具（类别换算与实例复制）
# ---------------------------------------------------------------------------


def _relabel_list(preds: list, offset: int, id2name: dict, name2id: dict) -> list:
    """预测实例 category_id 重贴（+offset→名字→规范 id）；未知类别丢弃。"""
    out = []
    for inst in preds:
        name = id2name.get(inst.category_id + offset)
        new_id = name2id.get(name) if name else None
        if new_id is None:
            continue
        out.append(
            _metrics.Instance(
                category_id=new_id, score=inst.score, crop=inst.crop, offset=inst.offset
            )
        )
    return out


def _with_class(inst, category_id: int):
    """复制实例并替换类别（掩码/偏移共享引用，只读使用）。"""
    return _metrics.Instance(
        category_id=category_id, score=inst.score, crop=inst.crop, offset=inst.offset
    )


def _as_name(value, id2name: dict) -> str | None:
    """GT 扩展字段可能是类别名或 category id → 统一成名字。"""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return id2name.get(int(value))


def _is_defect_diff(cls_a: str | None, cls_b: str | None, tax) -> bool:
    """上下异类且恰有一面计缺陷（单面可见缺陷的定义）。"""
    if cls_a is None or cls_b is None or cls_a == cls_b:
        return False
    return tax.get(cls_a).counts_as_defect != tax.get(cls_b).counts_as_defect


def np_frombytes(path: Path):
    """中文路径红线：字节缓冲解码（与本仓 acquisition.imread_bgr 同思想）。"""
    import numpy as np

    return np.frombuffer(path.read_bytes(), dtype=np.uint8)


def main() -> int:
    _common.setup_console()
    args = build_parser().parse_args()
    if not 0 < args.score_threshold < 1:
        print("[错误] --score-threshold 须在 (0,1)")
        return EXIT_USAGE
    if not args.dry_run and not (args.checkpoint or args.onnx):
        print("[错误] 真实模式必须提供 --checkpoint 或 --onnx 之一")
        return EXIT_USAGE
    if args.max_pairs < 0:
        print("[错误] --max-pairs 须 >=0")
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
