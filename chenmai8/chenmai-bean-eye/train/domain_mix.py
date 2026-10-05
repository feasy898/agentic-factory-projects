#!/usr/bin/env python3
"""T3 合成→真实域差配比数据构建（domain_mix；训练计划 T3 混入比扫描）。

把自采集真实标注图按 {0%, 5%, 10%, 20%} 四档混入合成训练集（其余合成），
产出四份可训练 COCO 目录（mix_r00 … mix_r20），供 T1 同超参重训扫描
「真实测试集 F1–混入比」曲线——回答「要多少本地数据才够」（答辩关键问题）。

红线（docs/collect_protocol.md §6）：自采集 v0.1 全量只用于评测/阈值回填，
**任何训练集划分在未来版本另行声明**。因此产出含真实数据档（ratio>0）必须
显式传 ``--redline-ack future-split-declared``（即声明 T3 划分已按未来版本
流程获准）；dry-run 不产数据、只提示。

配比口径
    真实图占比 = n_real / (n_real + n_synth) = r% → n_real = round(r·N_synth/(1−r))。
    真实图不足时**有放回重采样**（重复因子记入 manifest；>20× 时 WARN——
    该档结论可信度受限，须如实报告）。

输入目录约定
    - ``--synth-json``：prepare_coco 产出的 train/_annotations.coco.json；
      ``--synth-image-root`` 取其所在目录（默认同目录）；
    - ``--real-json`` + ``--real-image-root``：自采集真实盘 COCO
      （类别 = 内部 taxonomy key；collect_protocol §5 格式）。

输出（默认 ``train/runs/domain_mix``）
    ``mix_r{NN}/train/``（_annotations.coco.json + 图像，硬链接优先、跨卷回退
    复制）+ ``mix_plan.json``（四档配方/重复因子/种子/红线确认状态）。

期望运行时长
    主要是图像链接/复制：分钟级（20k 图 × 4 档，同卷硬链接时秒级）。

失败回退
    逐档落盘，中断重跑幂等（已存在的 mix 目录跳过或 --force 重建）。

GPU 机执行顺序
    T0 → T1（基准模型）→ **本脚本（T3 配方）** → 四档 det_finetune 重训 →
    eval_seg 逐档真实集评测 → 曲线入答辩材料；数据经 COS 中转（跨机不直传）。

--dry-run：纯离线——读 json（若存在）算四档配方并打印计划，exit 0。
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from pathlib import Path

import _common
from _common import EXIT_USAGE, PlanReporter, load_json, resolve_path, save_json

REDLINE_ACK_VALUE = "future-split-declared"  # 与 collect_protocol §6 表述对应的确认串
DEFAULT_RATIOS = "0,5,10,20"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="T3 域差配比：真实标注图 {0,5,10,20}% 混入合成训练集（--dry-run 纯离线）",
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="不写数据集，只校验并打印四档配方（离线，exit 0）")
    ap.add_argument("--synth-json", default="train/runs/datasets/v1/train/_annotations.coco.json",
                    help="合成训练集 COCO json（prepare_coco 产物）")
    ap.add_argument("--synth-image-root", default=None,
                    help="合成图像根（默认取 --synth-json 所在目录）")
    ap.add_argument("--real-json", default=None,
                    help="自采集真实标注 COCO json（taxonomy key；T3 混入源）")
    ap.add_argument("--real-image-root", default=None,
                    help="真实图像根目录")
    ap.add_argument("--ratios", default=DEFAULT_RATIOS,
                    help=f"混入比档位（%%，逗号分隔；默认 {DEFAULT_RATIOS}）")
    ap.add_argument("--seed", type=int, default=20261002,
                    help="真实图重采样种子（每档 = seed + ratio 派生，可复现）")
    ap.add_argument("--out", default="train/runs/domain_mix",
                    help="输出根（相对仓库根）")
    ap.add_argument("--redline-ack", default=None,
                    help=f"红线确认：产出含真实档必须等于 {REDLINE_ACK_VALUE!r}"
                         "（collect_protocol §6：训练集划分在未来版本另行声明）")
    ap.add_argument("--force", action="store_true",
                    help="已存在的 mix 目录也重建（默认跳过）")
    return ap


# ---------------------------------------------------------------------------
# 配方计算（dry-run 与真实模式共用；纯 stdlib）
# ---------------------------------------------------------------------------


def load_coco_brief(path: Path) -> dict:
    """读 COCO json 概要（图像数/类别名集/每图标注数），结构校验。"""
    data = load_json(path)
    if not isinstance(data, dict) or "images" not in data or "annotations" not in data:
        raise ValueError(f"COCO json 结构不完整: {path}")
    cat_names = sorted(
        {str(c.get("name", c.get("id"))) for c in data.get("categories", [])}
    )
    n_by_img: dict[int, int] = {}
    for ann in data.get("annotations", []):
        iid = int(ann["image_id"])
        n_by_img[iid] = n_by_img.get(iid, 0) + 1
    missing = sum(
        1 for i in data["images"] if not isinstance(i.get("file_name"), str)
    )
    return {
        "n_images": len(data["images"]),
        "n_annotations": len(data.get("annotations", [])),
        "category_names": cat_names,
        "anns_per_image": n_by_img,
        "images_missing_filename": missing,
        "data": data,
    }


def plan_ratio(ratio_pct: float, n_synth: int, n_real_avail: int) -> dict:
    """单档配方：目标真实图数 / 重复因子 / 混合总量。"""
    if ratio_pct <= 0:
        return {"ratio_pct": 0.0, "n_real_used": 0, "repeat_factor": 0.0,
                "n_mixed": n_synth, "n_synth": n_synth}
    share = ratio_pct / 100.0
    n_target = int(round(share * n_synth / max(1.0 - share, 1e-9)))
    repeat = n_target / n_real_avail if n_real_avail else float("inf")
    return {
        "ratio_pct": ratio_pct,
        "n_real_target": n_target,
        "n_real_avail": n_real_avail,
        "repeat_factor": round(repeat, 2) if n_real_avail else None,
        "n_mixed": n_synth + n_target,
        "n_synth": n_synth,
    }


def ratio_table(ratios: list[float], synth: dict | None, real: dict | None) -> list[dict]:
    n_synth = synth["n_images"] if synth else 0
    n_real = real["n_images"] if real else 0
    return [plan_ratio(r, n_synth, n_real) for r in ratios]


# ---------------------------------------------------------------------------
# dry-run
# ---------------------------------------------------------------------------


def dry_run(args: argparse.Namespace, rep: PlanReporter) -> int:
    rep.header("domain_mix.py", "T3 域差配比（真实标注混入合成集）")
    ratios = _parse_ratios(args.ratios, rep)
    if ratios is None:
        return rep.finish()

    rep.section("1. 输入")
    synth = real = None
    synth_json = resolve_path(args.synth_json)
    if synth_json.is_file():
        try:
            synth = load_coco_brief(synth_json)
            rep.ok(f"合成训练集: {synth_json}（图像 {synth['n_images']}，标注 "
                   f"{synth['n_annotations']}，类别 {synth['category_names']}）")
        except ValueError as exc:
            rep.error(str(exc))
    else:
        rep.missing(f"合成训练集: {synth_json}（prepare_coco 产物）")
    if args.real_json:
        real_json = resolve_path(args.real_json)
        if real_json.is_file():
            try:
                real = load_coco_brief(real_json)
                rep.ok(f"真实标注集: {real_json}（图像 {real['n_images']}，标注 "
                       f"{real['n_annotations']}，类别 {real['category_names']}）")
                if synth and real:
                    unknown = set(real["category_names"]) - set(synth["category_names"])
                    if unknown:
                        rep.error(f"真实集类别超出 taxonomy 13 类: {sorted(unknown)}")
            except ValueError as exc:
                rep.error(str(exc))
        else:
            rep.missing(f"真实标注集: {real_json}")
        if not args.real_image_root:
            rep.error("--real-json 提供时必须同时提供 --real-image-root")
    else:
        rep.missing("真实标注集（--real-json 未提供；T3 扫描需要）")

    rep.section("2. 四档配方")
    for row in ratio_table(ratios, synth, real):
        if row["ratio_pct"] <= 0:
            rep.plan(
                f"r{row['ratio_pct']:02.0f}%：纯合成 {row['n_mixed']} 图（0% 基准档）"
            )
            continue
        warn = ""
        if row["repeat_factor"] is not None and row["repeat_factor"] > 20:
            warn = " ←⚠ 重复因子>20，该档结论可信度受限（如实报告）"
        rep.plan(
            f"r{row['ratio_pct']:02.0f}%：真实 {row.get('n_real_target', 0)} 图"
            f"（可用 {row.get('n_real_avail', 0)}，重复因子 {row.get('repeat_factor')}）"
            f" + 合成 {row['n_synth']} = {row['n_mixed']} 图{warn}"
        )

    rep.section("3. 红线与输出")
    positive = [r for r in ratios if r > 0]
    if positive and args.redline_ack != REDLINE_ACK_VALUE:
        rep.warn(
            f"含真实档（{positive}%）须 --redline-ack {REDLINE_ACK_VALUE!r}"
            "（v0.1 只评测；训练划分未来版本另行声明）——dry-run 仅提示"
        )
    elif positive:
        rep.ok(f"红线确认串已提供（{args.redline_ack!r}）")
    out = resolve_path(args.out)
    rep.plan(f"输出: {out}/mix_r{{NN}}/train/ + mix_plan.json（硬链接优先，跨卷回退复制）")
    rep.warn("顺序：本脚本配方 → 四档 det_finetune 同超参重训 → eval_seg 真实集逐档评测")
    rep.warn("验收：曲线单调性合理；10% 档相对 0% 档真实集 F1 提升 ≥0.05（计划 T3 口径）")
    return rep.finish()


def _parse_ratios(raw: str, rep: PlanReporter) -> list[float] | None:
    vals: list[float] = []
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            v = float(tok)
        except ValueError:
            rep.error(f"--ratios 含非数值项: {tok!r}")
            return None
        if not 0 <= v < 100:
            rep.error(f"--ratios 档位须在 [0,100): {v}")
            return None
        vals.append(v)
    if not vals:
        rep.error("--ratios 为空")
        return None
    return sorted(set(vals))


# ---------------------------------------------------------------------------
# 真实执行
# ---------------------------------------------------------------------------


def _link_or_copy(src: Path, dst: Path) -> str:
    """硬链接优先（同卷零拷贝），跨卷/失败回退复制。返回 'link'|'copy'。"""
    if dst.exists():
        return "link"
    try:
        import os

        os.link(src, dst)
        return "link"
    except OSError:
        shutil.copy2(src, dst)
        return "copy"


def build_mix(
    ratio: float,
    synth: dict,
    real: dict | None,
    args: argparse.Namespace,
    out_root: Path,
) -> dict:
    """构建单档混合目录（幂等：--force 才重建）。"""
    tag = f"r{int(round(ratio)):02d}"
    mix_dir = out_root / f"mix_{tag}" / "train"
    if mix_dir.exists() and not args.force:
        return {"dir": str(mix_dir), "skipped": True}
    if mix_dir.exists() and args.force:
        shutil.rmtree(mix_dir.parent)
    mix_dir.mkdir(parents=True, exist_ok=True)

    synth_data = synth["data"]
    synth_root = (
        resolve_path(args.synth_image_root)
        if args.synth_image_root
        else resolve_path(args.synth_json).parent
    )
    real_root = resolve_path(args.real_image_root) if args.real_image_root else None

    images_out: list[dict] = []
    anns_out: list[dict] = []
    modes = {"link": 0, "copy": 0}

    # 合成图（每档都全量）
    for img in synth_data["images"]:
        fname = str(img["file_name"])
        src = synth_root / fname
        if not src.is_file():
            raise FileNotFoundError(f"合成图像缺失: {src}")
        modes[_link_or_copy(src, mix_dir / fname)] += 1
        images_out.append(dict(img))
    for ann in synth_data["annotations"]:
        node = dict(ann)
        node["source"] = "synth"
        anns_out.append(node)

    # 真实图（有放回重采样至目标数；标注按图像预分组，避免 O(n_target×n_anns)）
    n_real_used = 0
    if ratio > 0 and real is not None:
        real_data = real["data"]
        real_imgs = list(real_data["images"])
        if not real_imgs:
            raise ValueError("真实标注集无图像，无法混入")
        anns_by_img: dict[int, list[dict]] = {}
        for ann in real_data.get("annotations", []):
            anns_by_img.setdefault(int(ann["image_id"]), []).append(ann)
        rng = random.Random(args.seed + int(round(ratio)))
        n_target = plan_ratio(ratio, synth["n_images"], len(real_imgs))["n_real_target"]
        for k in range(n_target):
            src_img = real_imgs[rng.randrange(len(real_imgs))]
            fname = str(src_img["file_name"])
            src = real_root / fname if real_root else None
            if src is None or not src.is_file():
                continue
            dst_name = f"real_{k:05d}_{Path(fname).name}"
            modes[_link_or_copy(src, mix_dir / dst_name)] += 1
            img_id = len(images_out) + 1
            images_out.append({
                "id": img_id,
                "file_name": dst_name,
                "width": int(src_img.get("width", 0)),
                "height": int(src_img.get("height", 0)),
            })
            for ann in anns_by_img.get(int(src_img["id"]), []):
                node = dict(ann)
                node["id"] = len(anns_out) + 1
                node["image_id"] = img_id
                node["source"] = "real_self_collected"
                anns_out.append(node)
            n_real_used += 1

    save_json(
        mix_dir / "_annotations.coco.json",
        {
            "images": images_out,
            "annotations": anns_out,
            "categories": synth_data.get("categories", []),
        },
    )
    return {
        "dir": str(mix_dir),
        "ratio_pct": ratio,
        "n_images": len(images_out),
        "n_annotations": len(anns_out),
        "n_real_used": n_real_used,
        "io_modes": modes,
    }


def run(args: argparse.Namespace) -> int:
    ratios = _parse_ratios(args.ratios, PlanReporter(dry_run=True))
    if ratios is None:
        return EXIT_USAGE
    positive = [r for r in ratios if r > 0]
    if positive and args.redline_ack != REDLINE_ACK_VALUE:
        print(
            f"[FAIL] 产出含真实档（{positive}%）须 --redline-ack {REDLINE_ACK_VALUE!r}"
            "（collect_protocol §6：v0.1 只评测，训练划分未来版本另行声明）"
        )
        return EXIT_USAGE
    if positive and not args.real_json:
        print("[FAIL] 含真实档需要 --real-json")
        return EXIT_USAGE

    synth_json = resolve_path(args.synth_json)
    synth = load_coco_brief(synth_json)
    real = load_coco_brief(resolve_path(args.real_json)) if args.real_json else None
    if real is not None:
        unknown = set(real["category_names"]) - set(synth["category_names"])
        if unknown:
            print(f"[FAIL] 真实集类别超出合成集类别表: {sorted(unknown)}")
            return EXIT_USAGE

    out_root = resolve_path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    plan_rows = []
    for ratio in ratios:
        print(f"[domain_mix] 构建 mix_r{int(round(ratio)):02d} …", flush=True)
        row = build_mix(ratio, synth, real if ratio > 0 else None, args, out_root)
        plan_rows.append(row)
        print(f"[domain_mix]   {row}", flush=True)

    manifest = {
        "script": "train/domain_mix.py",
        "ratios": ratios,
        "seed": args.seed,
        "redline_ack": args.redline_ack,
        "redline_note": "含真实档表示 T3 训练划分已按 collect_protocol §6 未来版本流程获准",
        "synth": {k: synth[k] for k in ("n_images", "n_annotations", "category_names")},
        "real": (
            {k: real[k] for k in ("n_images", "n_annotations", "category_names")}
            if real else None
        ),
        "plans": ratio_table(ratios, synth, real),
        "built": plan_rows,
    }
    save_json(out_root / "mix_plan.json", manifest)
    print(f"[domain_mix] 配方清单: {out_root / 'mix_plan.json'}")
    print("[domain_mix] 下一步：四档 det_finetune 同超参重训 → eval_seg 真实集逐档评测")
    return 0


def main() -> int:
    _common.setup_console()
    args = build_parser().parse_args()
    rep = PlanReporter(dry_run=args.dry_run)
    if args.dry_run:
        return dry_run(args, rep)
    try:
        return run(args)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"[FAIL] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
