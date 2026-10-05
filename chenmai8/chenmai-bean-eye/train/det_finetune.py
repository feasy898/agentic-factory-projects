#!/usr/bin/env python3
"""T1 检测分割微调（det_finetune；训练计划 T1/T6 的 NN 微调脚本）。

单卡微调 13 类生豆缺陷分割模型（NN 包 seg 系型号，Apache-2.0 权重起步；
中性名纪律：上游件名不落本文件，钉版见 requirements-oss.txt）。超参按
训练计划 T1：lr 1e-4（余弦）、batch 4×累积 4、epochs 50、输入 1024×1024、
早停 val mAP50 3 epoch 无提升、checkpoint 每 5 epoch、导出 ONNX（opset 17，
静态 1024）。

输入目录约定
    ``--data-dir``：prepare_coco.py 产出的 COCO 目录（须含 ``train/`` 与
    ``valid/`` 子目录，各含 _annotations.coco.json + 图像）。

输出目录（默认 ``train/runs/t1``）
    checkpoint / 训练日志 / ``export/``（ONNX）；结果一律写 train/runs/。

期望运行时长
    计划 T5 口径：20k 图 × 50 epoch ≈ 6–8 h（V100S 单卡）；CPU 冒烟
    （--cpu-smoke）秒级；--smoke-train（1 epoch × 4 图）分钟级。

失败回退
    checkpoint 每 5 epoch 落盘（--checkpoint-every 可调）；中断后重跑同命令
    从输出目录恢复（NN 包按 output_dir 续训语义）；最坏情况以最近 checkpoint
    重启本脚本。

GPU 机执行顺序与数据中转
    T0（prepare_coco）→ **本脚本（T1，单卡 CUDA_VISIBLE_DEVICES=0）** →
    T2/T3 评测与消融（eval_ablation / domain_mix，第二卡并行）；
    数据集经 COS 中转（跨机不直传），到位后 sha256sum -c 校验。

--dry-run：纯离线校验（数据目录结构 / COCO json 离线统计 / 超参自检）并
打印训练计划，exit 0；不安装、不下载、不导入 NN 栈。
--cpu-smoke：真实模式冒烟（CPU 前向 1 图）；--smoke-train：1 epoch × ≤4 图
真训练小跑（计划 T6「1 batch 前向反传」的可执行等价——NN 包不暴露单步
训练接口，以前向冒烟 + 小跑反向共同覆盖）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import _common
from _common import (
    EXIT_USAGE,
    PlanReporter,
    resolve_path,
    save_json,
)

VALID_VARIANTS = ("small", "nano")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="T1 检测分割微调（--dry-run 纯离线打印训练计划）",
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="不训练/不下载/不导入 NN 栈，只校验并打印计划（离线，exit 0）")
    ap.add_argument("--data-dir", default="train/runs/datasets/v1",
                    help="COCO 数据集目录（prepare_coco 产物；含 train/ valid/）")
    ap.add_argument("--out", default="train/runs/t1",
                    help="输出根（checkpoint/日志/导出；相对仓库根）")
    ap.add_argument("--variant", choices=VALID_VARIANTS, default="small",
                    help="分割模型型号（small 默认；nano 为显存/速度备选）")
    ap.add_argument("--epochs", type=int, default=50, help="训练轮数（计划 T1 = 50）")
    ap.add_argument("--batch", type=int, default=4, help="批大小（V100S-32G 口径 = 4）")
    ap.add_argument("--accum", type=int, default=4, help="梯度累积步数（有效批 = 16）")
    ap.add_argument("--lr", type=float, default=1e-4, help="峰值学习率（余弦退火）")
    ap.add_argument("--resolution", type=int, default=1024,
                    help="训练输入边长（计划 T1 = 1024；评估另跑 1280 档）")
    ap.add_argument("--early-stop-patience", type=int, default=3,
                    help="早停耐心（val mAP50 连续 N epoch 无提升；计划 T1 = 3）")
    ap.add_argument("--checkpoint-every", type=int, default=5,
                    help="checkpoint 保存间隔 epoch（失败回退粒度）")
    ap.add_argument("--export-onnx", action="store_true", default=True,
                    help="训练后导出 ONNX（opset 17，静态 --resolution；默认开）")
    ap.add_argument("--no-export-onnx", dest="export_onnx", action="store_false",
                    help="关闭 ONNX 导出")
    ap.add_argument("--opset", type=int, default=17, help="ONNX opset（计划 T1 = 17）")
    ap.add_argument("--device", default="cuda:0",
                    help="训练设备（GPU 机单卡口径 cuda:0；第二卡留给 T2/T3）")
    ap.add_argument("--cpu-smoke", action="store_true",
                    help="真实模式冒烟：CPU 加载模型 + 1 张图前向（需已装 NN 栈）")
    ap.add_argument("--smoke-train", action="store_true",
                    help="真实模式小跑：复制 ≤4 张训练图到临时目录，1 epoch 真训练（反向覆盖）")
    return ap


# ---------------------------------------------------------------------------
# 离线校验（dry-run 与真实模式共用的数据目录检查）
# ---------------------------------------------------------------------------


def coco_split_stats(split_dir: Path) -> dict:
    """离线统计一个 COCO split（stdlib json；不触碰图像/掩码）。"""
    json_path = split_dir / "_annotations.coco.json"
    if not json_path.is_file():
        raise FileNotFoundError(f"缺 {json_path}")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "images" not in data or "annotations" not in data:
        raise ValueError(f"{json_path} 结构不完整（缺 images/annotations）")
    n_by_cat: dict[int, int] = {}
    missing_files = 0
    for img in data["images"]:
        if not (split_dir / str(img.get("file_name", ""))).is_file():
            missing_files += 1
    for ann in data["annotations"]:
        cid = int(ann.get("category_id", -1))
        n_by_cat[cid] = n_by_cat.get(cid, 0) + 1
    return {
        "images": len(data["images"]),
        "annotations": len(data["annotations"]),
        "missing_files": missing_files,
        "annotations_by_category": dict(sorted(n_by_cat.items())),
        "n_images_with_seg": sum(
            1 for a in data["annotations"] if a.get("segmentation")
        ),
    }


def check_data_dir(args: argparse.Namespace, rep: PlanReporter) -> dict:
    """校验数据目录两个 split；缺失不阻塞 dry-run，结构错误计 error。"""
    data_dir = resolve_path(args.data_dir)
    stats: dict[str, dict] = {}
    if not data_dir.is_dir():
        rep.missing(f"数据目录: {data_dir}（prepare_coco 产物；GPU 机经 COS 中转到位）")
        return stats
    rep.ok(f"数据目录: {data_dir}")
    for split in ("train", "valid"):
        sdir = data_dir / split
        if not sdir.is_dir():
            rep.missing(f"split 目录: {sdir}")
            continue
        try:
            st = coco_split_stats(sdir)
            stats[split] = st
            rep.ok(
                f"{split}: 图像 {st['images']}，标注 {st['annotations']}"
                f"（缺图像文件 {st['missing_files']}）"
            )
            if st["missing_files"]:
                rep.error(f"{split}: {st['missing_files']} 个 file_name 在磁盘缺失")
        except (ValueError, FileNotFoundError) as exc:
            rep.error(str(exc))
    return stats


# ---------------------------------------------------------------------------
# dry-run
# ---------------------------------------------------------------------------


def dry_run(args: argparse.Namespace, rep: PlanReporter) -> int:
    rep.header("det_finetune.py", "T1 检测分割微调")
    if args.cpu_smoke or args.smoke_train:
        rep.error("--cpu-smoke/--smoke-train 属真实模式，不能与 --dry-run 同用")

    rep.section("1. 数据")
    stats = check_data_dir(args, rep)

    rep.section("2. 训练计划（超参 = 训练计划 T1 口径）")
    rep.plan(f"模型：seg 系·{args.variant}（中性名 beaneye-det；钉版 requirements-oss.txt）")
    rep.plan(f"数据：{args.data_dir}（train {stats.get('train', {}).get('images', '?')} 图 / "
             f"valid {stats.get('valid', {}).get('images', '?')} 图）")
    rep.plan(f"超参：epochs={args.epochs} batch={args.batch}×累积{args.accum}（有效 {args.batch * args.accum}） "
             f"lr={args.lr:g}（余弦）resolution={args.resolution}")
    rep.plan(f"早停：val mAP50 连续 {args.early_stop_patience} epoch 无提升；"
             f"checkpoint 每 {args.checkpoint_every} epoch（失败回退粒度）")
    rep.plan(
        f"导出：ONNX opset={args.opset} 静态 {args.resolution}×{args.resolution}"
        if args.export_onnx else "导出：关闭（--no-export-onnx）"
    )
    rep.plan(f"设备：{args.device}（GPU 机单卡口径；第二卡留给 T2/T3 并行）")
    rep.plan(f"输出：{resolve_path(args.out)}（checkpoint/日志/export/）")
    rep.plan("估算时长：V100S 单卡 20k 图 × 50 epoch ≈ 6–8 h（计划 T5 口径）")

    rep.section("3. 执行顺序与数据中转")
    rep.plan("顺序：T0 prepare_coco → 本脚本 T1（单卡）→ T2/T3 评测消融（第二卡并行）")
    rep.warn("数据经 COS 中转（跨机不直传）；模型权重下载发生在 GPU 机（首次自动缓存，"
             "端点配置见 requirements-oss.txt 头部说明）")
    return rep.finish()


# ---------------------------------------------------------------------------
# 真实执行
# ---------------------------------------------------------------------------


def _smoke_data_dir(args: argparse.Namespace, work_dir: Path, limit: int = 4) -> Path:
    """从 train/valid 各抽 ≤limit 图 + 标注拷到临时 COCO 目录（小跑用）。"""
    import shutil

    src = resolve_path(args.data_dir)
    dst = work_dir / "smoke_data"
    for split in ("train", "valid"):
        data = json.loads(
            (src / split / "_annotations.coco.json").read_text(encoding="utf-8")
        )
        keep_imgs = data["images"][:limit]
        keep_ids = {int(i["id"]) for i in keep_imgs}
        keep_anns = [a for a in data["annotations"] if int(a["image_id"]) in keep_ids]
        out_split = dst / split
        out_split.mkdir(parents=True, exist_ok=True)
        for img in keep_imgs:
            f = src / split / str(img["file_name"])
            if f.is_file():
                shutil.copy2(f, out_split / img["file_name"])
        save_json(out_split / "_annotations.coco.json",
                  {"images": keep_imgs, "annotations": keep_anns,
                   "categories": data.get("categories", [])})
    return dst


def run(args: argparse.Namespace) -> int:
    nn_pkg, _torch = _common.import_nn_stack()
    model_cls = _common.nn_model_class(nn_pkg, args.variant)
    out = resolve_path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    device = args.device
    if args.cpu_smoke or args.smoke_train:
        device = "cpu"

    if args.cpu_smoke:
        import numpy as np

        kwargs: dict = {"device": device}
        try:
            model = model_cls(resolution=args.resolution, **kwargs)
        except TypeError:
            model = model_cls(**kwargs)
        img = (np.random.default_rng(0).integers(0, 255, (480, 640, 3), dtype=np.uint8))
        det = model.predict(img[:, :, ::-1], threshold=0.5)
        n = 0 if det is None else len(det)
        print(f"[cpu-smoke] 前向 OK：预测实例 {n} 个（随机噪声图，仅链路连通性）")
        print("[cpu-smoke] 反向覆盖：请再跑 --smoke-train（NN 包不暴露单步训练接口）")
        return 0

    data_dir = resolve_path(args.data_dir)
    if args.smoke_train:
        import tempfile

        with tempfile.TemporaryDirectory(prefix="det_smoke_") as td:
            smoke_dir = _smoke_data_dir(args, Path(td))
            model = model_cls(device=device)
            model.train(
                dataset_dir=str(smoke_dir),
                output_dir=str(out / "smoke_run"),
                epochs=1,
                batch_size=1,
                grad_accum_steps=1,
                lr=args.lr,
            )
        print(f"[smoke-train] 1 epoch × ≤4 图完成（前向+反向覆盖）：{out / 'smoke_run'}")
        return 0

    # ---- 正式训练（计划 T1 口径） ------------------------------------------
    stats = check_data_dir(args, PlanReporter(dry_run=False))
    if not stats.get("train") or not stats.get("valid"):
        print(f"[FAIL] 数据目录不完整: {data_dir}（先跑 prepare_coco.py）")
        return 1

    # 构造器参数名以 2026-10-03 pydantic 报错实测为准：合法参数为 resolution
    # （img_size 不存在）；非法参数抛 ValidationError（ValueError 子类）非 TypeError。
    # amp=fp16：V100（Volta，sm_70）无 bf16 硬件支持，包默认 bf16 存在风险；
    # 值不被接受时自动降级到仅 resolution 分支。
    model = None
    for ctor_kwargs in (
        {"device": device, "resolution": args.resolution, "amp": "fp16",
         "gradient_checkpointing": True},
        {"device": device, "resolution": args.resolution,
         "gradient_checkpointing": True},
        {"device": device, "resolution": args.resolution},
        {"device": device, "img_size": args.resolution},
        {"device": device},
    ):
        try:
            model = model_cls(**ctor_kwargs)
        except (TypeError, ValueError):
            continue
        if len(ctor_kwargs) > 1:
            used = ",".join(k for k in ctor_kwargs if k != "device")
            print(f"[构造] 已传入 {used}（resolution={args.resolution}）")
        else:
            print(f"[警告] 构造器不认 resolution/img_size，回退包默认分辨率训练"
                  f"（计划口径 {args.resolution} 未生效，见 README API 核对节）")
        break
    assert model is not None, "模型构造全部失败（不应到达）"
    train_kwargs: dict = {
        "dataset_dir": str(data_dir),
        "output_dir": str(out),
        "epochs": args.epochs,
        "batch_size": args.batch,
        "grad_accum_steps": args.accum,
        "lr": args.lr,
    }
    # 早停（计划 T1：val mAP50 连续 3 epoch 无提升）：NN 包若暴露早停组件则
    # 挂上（组件类名经 getattr 中性取用，不落上游件名）；未暴露/签名不符时
    # 如实回退——依赖 checkpoint 每 N epoch 保存 + 训练日志选 best。
    es_cls = getattr(nn_pkg, "CustomEarlyStopping", None)
    if es_cls is not None:
        try:
            train_kwargs["early_stopping"] = es_cls(
                patience=args.early_stop_patience, min_delta=1e-3, use_coco=True
            )
        except TypeError:
            print("[警告] 早停组件签名与预期不符，未挂载——依赖 checkpoint 每 "
                  f"{args.checkpoint_every} epoch 保存 + 训练日志选 best（见 README API 核对节）")
    else:
        print("[警告] NN 包未暴露早停组件——依赖 checkpoint 每 "
              f"{args.checkpoint_every} epoch 保存 + 训练日志选 best")
    save_json(out / "train_plan.json", {
        "script": "train/det_finetune.py",
        "args": {k: v for k, v in vars(args).items()},
        "data_stats": stats,
    })
    model.train(**train_kwargs)
    print(f"[train] 训练完成：{out}")

    if args.export_onnx:
        try:
            model.export(output_dir=str(out / "export"), opset_version=args.opset)
        except TypeError:
            print("[警告] export() 不接受 opset_version 参数，按钉版默认 opset 导出")
            model.export(output_dir=str(out / "export"))
        print(f"[export] ONNX（opset 目标 {args.opset}，静态 {args.resolution}）：{out / 'export'}")
    return 0


def main() -> int:
    _common.setup_console()
    args = build_parser().parse_args()
    if args.variant not in VALID_VARIANTS:
        print(f"[错误] --variant 须为 {VALID_VARIANTS}")
        return EXIT_USAGE
    if args.epochs <= 0 or args.batch <= 0 or args.accum <= 0:
        print("[错误] --epochs/--batch/--accum 须为正整数")
        return EXIT_USAGE
    if args.lr <= 0 or args.resolution <= 0:
        print("[错误] --lr/--resolution 须为正数")
        return EXIT_USAGE
    if args.dry_run:
        rep = PlanReporter(dry_run=True)
        return dry_run(args, rep)
    try:
        return run(args)
    except RuntimeError as exc:
        print(f"[FAIL] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
