#!/usr/bin/env python3
"""单粒豆裁片分类：ResNet18 训练 + 评测 + ONNX 导出（crop_classifier；训练计划 T4 备胎线）。

把 prepare_crops.py 产出的单粒裁片（默认 ``/data/coffee-bean/crops``，
``<split>/<classkey>/<hash>.jpg``，13 类 = taxonomy severity_order）训练
ResNet18 分类器，评测 valid/test 两 split，导出 ONNX（opset 17 静态
1×3×--size²）并测 onnxruntime CPU 延迟，全部结果写 ``metrics.json``。

对应训练计划 T4（备用路线）：「RFDETRSeg 掩码 crop → MobileNetV3-small/
ResNet18 分类头（torchvision，BSD/Apache 权重）」，验收口径**单粒集
macro-F1 ≥0.85、CPU ONNX ≤15ms/粒**；按 T4 备胎线执行，输入裁片即
prepare_crops 产物（top/bottom 两面裁片混合训练，不区分面别）。

类不平衡处理（方法）
    交叉熵 loss 权重 ``w_c = 1/log(1.02 + n_c)``，n_c = train split 类 c
    的裁片实测数（与 crops manifest per_class.kept 同源）。prepare_crops
    已对 normal/broken/dried/black 做 per-class-cap=20000 封顶，剩余不平
    衡约 2:1（immature 9.6k vs 20k）；1/log 缓冲让最终权重比 ≈1.08，只
    轻微抬低频类——比 inverse-frequency 温和，避免小类梯度主导。
    （--imbalance none 可关闭，供对照；权重表如实写进 metrics.json。）

预训练权重
    ``torchvision.models.resnet18(weights=IMAGENET1K_V1)``（BSD 许可，
    download.pytorch.org）。下载失败自动回退 ``weights=None`` 随机初始化
    并从头训练，metrics.json 的 ``weights_source`` 如实记录（不静默）。

精度
    fp16 混合精度（``torch.amp.autocast`` + ``torch.amp.GradScaler``）：
    V100（Volta）有 fp16 tensor core、**无 bf16**（Ampere+ 特性），故
    dtype 固定 float16、禁用 bf16；CPU device 时两者都不启用。

数据纪律
    holdout 语义保持：valid 只用于逐 epoch 选 best（macro-F1 最高），
    test 只在训练结束后用 best 权重终评一次；任何 split 间无数据搬移
    （与 prepare_crops 的 redline 一致）。

输入目录约定
    ``--crops-dir``：裁片根（默认 /data/coffee-bean/crops），下含
    ``{train,valid,test}/<classkey>/*.jpg``；manifest.json 只读用于交叉
    核对计数（缺失/不一致不阻塞，以磁盘实测为准并打印警告）。

输出（--out，默认 train/runs/crop_cls）
    ``best.pt``（best macro-F1 权重 + 类别表 + 元数据）、``last.pt``
    （末 epoch，崩溃诊断用）、``crop_cls.onnx``（opset 17 静态）、
    ``metrics.json``（参数/数据计数/权重来源/每 epoch 历史/valid+test
    逐类 P·R·F1 与混淆矩阵/导出与 CPU 延迟实测/门禁对照）。

期望运行时长（GPU 机 V100S-32GB 单卡、16 核 CPU）
    train 20.8 万裁片 fp16 batch256 约 2.5–4 min/epoch × 8 epochs，加
    valid 终评、ONNX 导出与 CPU 测速，总墙钟约 30–60 min。

失败回退
    每个 epoch 落 last.pt、刷新 best 落 best.pt（中断后可改 --epochs 续
    评，但本脚本不做断点续训——重跑成本低）；权重下载失败回退随机初始
    化（记录）；onnxruntime 缺失时训练/评测/导出照常，延迟项记 error、
    门禁标 not_evaluated（train/README.md 依赖节口径：GPU 机需自行
    pip install onnxruntime）；``--check-gates`` 时任一门禁未达 → exit 1
    （默认只记录不失败，如实打印）。

GPU 机执行顺序（详见 train/README.md；数据经 COS 中转到位）
    prepare_crops.py（裁片落 /data）→ **本脚本**（CUDA_VISIBLE_DEVICES=0，
    单卡口径）→ crop_cls.onnx + metrics.json 经 COS 回传（前缀
    beaneye-batch4/，跨机不直传）。

--dry-run：纯离线——校验 crops 目录结构与类别表一致性、打印训练/导出/
测速计划与每 split 计数（os.scandir 计数，不读图像、不导入 torch 等
NN 栈），结构性错误 exit 2，否则 exit 0。
"""

from __future__ import annotations

import argparse
import math
import os
import random
import sys
import time
from pathlib import Path

import numpy as np  # 核心钉版依赖（非 NN 栈），dry-run 亦可承受

import _common
from _common import (
    EXIT_FAILED,
    EXIT_OK,
    EXIT_USAGE,
    PlanReporter,
    build_categories,
    load_json,
    resolve_path,
    save_json,
    sha256_file,
)

SPLITS = ("train", "valid", "test")
# ImageNet 归一化（与 export_onnx_quant.py / _predict.OnnxPredictor 同口径）
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)
# 轻度 ColorJitter（合成→真实的颜色域差缓冲；hue 只动 0.02 防色相类间混淆）
JITTER = dict(brightness=0.2, contrast=0.2, saturation=0.1, hue=0.02)
# 验收口径（training-plan.md T4 备胎线）
GATE_MACRO_F1 = 0.85    # 单粒集 macro-F1（test split 口径）
GATE_CPU_MS = 15.0      # CPU ONNX 单粒延迟（batch1 mean，ms）


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="单粒裁片分类训练+评测+ONNX 导出（--dry-run 纯离线打印计划）",
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="不训练/不导出/不导入 NN 栈，只校验并打印计划（离线，exit 0）")
    ap.add_argument("--crops-dir", default="/data/coffee-bean/crops",
                    help="裁片根（prepare_crops 产物；默认 /data/coffee-bean/crops）")
    ap.add_argument("--out", default="train/runs/crop_cls",
                    help="输出目录（相对仓库根；默认 train/runs/crop_cls）")
    ap.add_argument("--arch", default="resnet18", choices=("resnet18",),
                    help="骨干（训练计划 T4 口径：resnet18；默认且仅 resnet18）")
    ap.add_argument("--epochs", type=int, default=8,
                    help="训练轮数（默认 8）")
    ap.add_argument("--batch", type=int, default=256,
                    help="batch size（默认 256）")
    ap.add_argument("--lr", type=float, default=3e-4,
                    help="AdamW 学习率（默认 3e-4；cosine 退火，wd=0.05）")
    ap.add_argument("--size", type=int, default=224,
                    help="输入边长（默认 224；crops 本身即 224²，此为一致性保险）")
    ap.add_argument("--device", default="cuda:0",
                    help="训练设备（默认 cuda:0；T4/T5 单卡口径卡 0）")
    ap.add_argument("--workers", type=int, default=8,
                    help="DataLoader 进程数（默认 8；16 核机给训练留核）")
    ap.add_argument("--seed", type=int, default=0,
                    help="随机种子（默认 0；影响初始化/洗牌）")
    ap.add_argument("--imbalance", default="loss-weight", choices=("loss-weight", "none"),
                    help="类不平衡方法（默认 loss-weight = 交叉熵权重 1/log(1.02+n_c)）")
    ap.add_argument("--limit-per-class", type=int, default=0,
                    help="每 split 每类只取前 N 张（0 = 全量；链路自检用）")
    ap.add_argument("--check-gates", action="store_true",
                    help="对照 T4 门禁（macro-F1≥0.85、CPU≤15ms/粒），未达则 exit 1")
    return ap


# ---------------------------------------------------------------------------
# 数据扫描与指标（numpy 自实现，零新增依赖）
# ---------------------------------------------------------------------------


def scan_split(crops_root: Path, split: str, classes: list[str],
               limit_per_class: int) -> dict[str, list[Path]]:
    """枚举一个 split 的裁片：{classkey: [Path,...]}；目录缺失/空类即抛错。

    类别顺序 = taxonomy severity_order（与 prepare_crops/coco categories
    id 序一致，跨脚本确定性）。``--limit-per-class`` 截前 N 个文件（排序
    确定性 → 冒烟可复现）。
    """
    split_dir = crops_root / split
    if not split_dir.is_dir():
        raise FileNotFoundError(f"缺 split 目录: {split_dir}")
    out: dict[str, list[Path]] = {}
    for key in classes:
        cdir = split_dir / key
        if not cdir.is_dir():
            raise FileNotFoundError(
                f"缺类别目录: {cdir}（crops 结构须为 <split>/<classkey>/*.jpg）")
        files = sorted(p for p in cdir.iterdir() if p.suffix.lower() == ".jpg")
        if not files:
            raise ValueError(f"类别目录为空: {cdir}")
        if limit_per_class > 0:
            files = files[:limit_per_class]
        out[key] = files
    return out


def prf_cm(y_true: np.ndarray, y_pred: np.ndarray, classes: list[str]) -> dict:
    """逐类 P/R/F1 + macro-F1 + 混淆矩阵（行=真值、列=预测，序 = classes）。"""
    n = len(classes)
    cm = np.zeros((n, n), dtype=np.int64)
    np.add.at(cm, (y_true, y_pred), 1)
    per_class: dict[str, dict] = {}
    f1s: list[float] = []
    for i, key in enumerate(classes):
        tp = int(cm[i, i])
        fp = int(cm[:, i].sum()) - tp
        fn = int(cm[i, :].sum()) - tp
        p = tp / (tp + fp) if (tp + fp) else 0.0
        r = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) else 0.0
        per_class[key] = {"precision": round(p, 6), "recall": round(r, 6),
                          "f1": round(f1, 6), "support": tp + fn}
        f1s.append(f1)
    total = int(cm.sum())
    acc = float(np.trace(cm)) / total if total else 0.0
    return {
        "macro_f1": round(float(np.mean(f1s)), 6),
        "accuracy": round(acc, 6),
        "per_class": per_class,
        "confusion_matrix": cm.tolist(),
        "confusion_note": "行=真值、列=预测，顺序与 classes 一致",
    }


def top_confusions(cm: list[list[int]], classes: list[str], k: int = 5) -> list[dict]:
    """混淆矩阵 → 离对角质量最高的前 k 个（真值, 误判为）对（误差分析用）。"""
    arr = np.asarray(cm)
    pairs = [
        (int(arr[i, j]), classes[i], classes[j])
        for i in range(len(classes)) for j in range(len(classes))
        if i != j and arr[i, j] > 0
    ]
    pairs.sort(key=lambda t: t[0], reverse=True)
    return [{"count": c, "true": a, "pred": b} for c, a, b in pairs[:k]]


# ---------------------------------------------------------------------------
# 真实模式：数据集 / 模型 / 训练·评测循环（NN 栈只在真实分支导入）
# ---------------------------------------------------------------------------


def make_items(data: dict[str, list[Path]]) -> list[tuple[str, int]]:
    """{classkey: files} → [(path, label_idx), ...]（label = severity_order 位次）。"""
    classes = list(data.keys())
    return [(str(p), i) for i, key in enumerate(classes) for p in data[key]]


def make_loader(items: list[tuple[str, int]], transform, batch: int, shuffle: bool,
                workers: int, seed: int, device, persistent: bool = True):
    """DataLoader 装配（PIL 解码在 worker 进程；shuffle 仅 train，drop_last 同步）。"""
    import torch
    from torch.utils.data import DataLoader, Dataset

    class _CropDataset(Dataset):
        """(path,label) 列表 → PIL RGB + transform 的最小数据集。"""

        def __init__(self, its: list[tuple[str, int]], tf) -> None:
            self.its = its
            self.tf = tf

        def __len__(self) -> int:
            return len(self.its)

        def __getitem__(self, idx: int):
            from PIL import Image
            path, label = self.its[idx]
            with Image.open(path) as im:
                im = im.convert("RGB")
                return self.tf(im), label

    ds = _CropDataset(items, transform)
    g = torch.Generator()
    g.manual_seed(seed)
    return DataLoader(ds, batch_size=batch, shuffle=shuffle,
                      num_workers=workers, pin_memory=(device.type == "cuda"),
                      generator=g, drop_last=shuffle,
                      persistent_workers=(workers > 0 and persistent))


def build_model(arch: str, n_classes: int) -> tuple[object, str]:
    """resnet18 + 13 类头；IMAGENET1K_V1 下载失败回退随机初始化（如实记录）。"""
    import torch
    import torchvision

    if arch != "resnet18":
        raise ValueError(f"未知骨干 {arch!r}（T4 口径仅 resnet18）")
    try:
        weights = torchvision.models.ResNet18_Weights.IMAGENET1K_V1
        model = torchvision.models.resnet18(weights=weights)
        source = "IMAGENET1K_V1（torchvision 预训练，BSD）"
    except Exception as exc:  # 断网/权重源不可达 → 从头训，记录不静默
        print(f"[警告] 预训练权重下载失败（{exc}），回退 weights=None 随机初始化从头训",
              flush=True)
        model = torchvision.models.resnet18(weights=None)
        source = f"random_init（IMAGENET1K_V1 下载失败: {type(exc).__name__}: {exc}）"
    model.fc = torch.nn.Linear(model.fc.in_features, n_classes)
    return model, source


def train_one_epoch(model, loader, criterion, optimizer, scaler, device,
                    use_amp: bool, epoch: int, epochs: int) -> tuple[float, float]:
    """一个 epoch 训练；返回 (平均loss, 秒)。fp16 autocast（V100 无 bf16）。"""
    import torch  # 真实分支专用惰性导入（dry-run 不出现 NN 栈）
    model.train()
    t0 = time.time()
    loss_sum, seen, iters = 0.0, 0, len(loader)
    for it, (imgs, y) in enumerate(loader, start=1):
        imgs = imgs.to(device, non_blocking=True)
        y = y.to(device, non_blocking=True)
        optimizer.zero_grad(set_to_none=True)
        if use_amp:
            with torch.amp.autocast(device_type="cuda", dtype=torch.float16):
                loss = criterion(model(imgs), y)
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
        else:
            loss = criterion(model(imgs), y)
            loss.backward()
            optimizer.step()
        loss_sum += float(loss.detach()) * y.size(0)  # detach：标量化不挂计算图
        seen += y.size(0)
        if it % 100 == 0 or it == iters:
            rate = seen / max(time.time() - t0, 1e-6)
            eta = (iters - it) * (time.time() - t0) / it
            print(f"  [e{epoch}/{epochs}] {it}/{iters} iter，"
                  f"loss={loss_sum / max(seen, 1):.4f}，{rate:.0f} img/s，"
                  f"ETA {eta:.0f}s", flush=True)
    return loss_sum / max(seen, 1), time.time() - t0


def predict(model, loader, device, use_amp: bool) -> tuple[np.ndarray, np.ndarray]:
    """整个 loader 的 (真值, 预测) numpy 数组（eval 模式，无 TTA）。"""
    import torch  # 真实分支专用惰性导入（dry-run 不出现 NN 栈）
    ys, ps = [], []
    model.eval()
    with torch.no_grad():
        for imgs, y in loader:
            imgs = imgs.to(device, non_blocking=True)
            if use_amp:
                with torch.amp.autocast(device_type="cuda", dtype=torch.float16):
                    logits = model(imgs)
            else:
                logits = model(imgs)
            ps.append(logits.float().argmax(dim=1).cpu())
            ys.append(y)
    return torch.cat(ys).numpy(), torch.cat(ps).numpy()


def export_onnx(model, onnx_path: Path, size: int, batch: int = 1) -> dict:
    """best 模型 → opset 17 静态 batch×3×size² ONNX（CPU 权重导出，便携优先）。

    交付件固定 batch=1（1×3×224×224，计划口径）；batch=64 只用于吞吐测速
    的基准件（静态导出不接受变 batch，实测踩坑：ort 报 Got:64 Expected:1）。
    """
    import torch

    model = model.to("cpu").eval()
    dummy = torch.randn(batch, 3, size, size)
    t0 = time.time()
    exporter = ""
    try:  # 首选 TorchScript 导出器（dynamo=False；不引入 onnxscript 依赖）
        torch.onnx.export(model, dummy, str(onnx_path), opset_version=17,
                          input_names=["input"], output_names=["logits"],
                          dynamo=False)
        exporter = "torchscript(dynamo=False)"
    except TypeError:  # 版本不含 dynamo 形参 → 按默认导出并记录
        torch.onnx.export(model, dummy, str(onnx_path), opset_version=17,
                          input_names=["input"], output_names=["logits"])
        exporter = "default(该版本无 dynamo 形参)"
    info = {
        "onnx_path": str(onnx_path),
        "opset": 17,
        "static_input": [batch, 3, size, size],
        "exporter": exporter,
        "seconds": round(time.time() - t0, 1),
        "bytes": onnx_path.stat().st_size,
        "sha256": sha256_file(onnx_path),
    }
    # 数值一致性抽查：torch vs onnxruntime 同一 dummy 的 logits 最大绝对差
    try:
        import onnxruntime as ort
        sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
        with torch.no_grad():
            ref = model(dummy).numpy()
        got = sess.run(None, {"input": dummy.numpy()})[0]
        info["parity_max_abs_diff"] = float(np.abs(ref - got).max())
    except Exception as exc:  # ort 缺失等 → 记录，不阻塞导出本身
        info["parity_error"] = f"{type(exc).__name__}: {exc}"
    return info


def cpu_latency(onnx_path: Path, onnx_path_b64: Path, size: int,
                n_single: int = 100, n_b64: int = 20) -> dict:
    """onnxruntime CPU 延迟：batch1 单粒（均值/p50/p95）+ batch64 吞吐。

    batch1 用交付件（静态 1×3×size²）；batch64 用静态 64×3×size² 基准件
    （``export_onnx`` 同权重另导，静态导出不接受变 batch）。测的是本机
    （GPU 机 16 核 Xeon）CPU，非部署目标机——口径如实写进返回值；
    batch1 mean 对照 T4 门禁 ≤15ms/粒。
    """
    import onnxruntime as ort

    so = ort.SessionOptions()  # 线程数默认（0 = 用满物理核），如实记录
    sess = ort.InferenceSession(str(onnx_path), so,
                                providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0].name
    x1 = np.random.randn(1, 3, size, size).astype(np.float32)
    for _ in range(10):  # 预热不计入
        sess.run(None, {inp: x1})
    ts = []
    for _ in range(n_single):
        t0 = time.perf_counter()
        sess.run(None, {inp: x1})
        ts.append((time.perf_counter() - t0) * 1000.0)
    sess64 = ort.InferenceSession(str(onnx_path_b64), so,
                                  providers=["CPUExecutionProvider"])
    inp64 = sess64.get_inputs()[0].name
    x64 = np.random.randn(64, 3, size, size).astype(np.float32)
    for _ in range(3):
        sess64.run(None, {inp64: x64})
    ts64 = []
    for _ in range(n_b64):
        t0 = time.perf_counter()
        sess64.run(None, {inp64: x64})
        ts64.append(time.perf_counter() - t0)
    b64_ms = float(np.mean(ts64)) * 1000.0
    return {
        "device": f"CPU（本机 os.cpu_count={os.cpu_count()}；GPU 机 16 核，"
                  "非部署目标机，口径如实记录）",
        "onnxruntime": ort.__version__,
        "session": {"providers": ["CPUExecutionProvider"],
                    "intra_op_num_threads": so.intra_op_num_threads,
                    "intra_op_note": "0 = 默认用满物理核"},
        "batch1": {
            "runs": n_single,
            "mean_ms": round(float(np.mean(ts)), 3),
            "p50_ms": round(float(np.percentile(ts, 50)), 3),
            "p95_ms": round(float(np.percentile(ts, 95)), 3),
        },
        "batch64": {
            "runs": n_b64,
            "mean_ms_per_batch": round(b64_ms, 1),
            "mean_ms_per_image": round(b64_ms / 64.0, 3),
            "throughput_imgs_per_s": round(64.0 / (b64_ms / 1000.0), 1),
        },
    }


# ---------------------------------------------------------------------------
# dry-run / run / main
# ---------------------------------------------------------------------------


def dry_run(args: argparse.Namespace, rep: PlanReporter) -> int:
    """纯离线计划打印：crops 结构校验 + 每类计数（scandir）+ 训练/导出计划。"""
    rep.header("crop_classifier.py", "单粒裁片分类训练（T4 备胎线）")
    rep.section("输入")
    crops_root = resolve_path(args.crops_dir)
    rep.check_dir(crops_root, "裁片根 --crops-dir")
    try:
        _, tax = build_categories()
        classes = list(tax.severity_order)
        rep.ok(f"taxonomy 类别 {len(classes)} 类: {','.join(classes)}")
    except Exception as exc:  # taxonomy 加载失败属结构性错误
        rep.error(f"taxonomy 加载失败: {exc}")
        return rep.finish()

    counts: dict[str, dict[str, int]] = {}
    for split in SPLITS:
        split_dir = crops_root / split
        if not split_dir.is_dir():
            rep.missing(f"{split} 目录: {split_dir}")
            continue
        cnt: dict[str, int] = {}
        for key in classes:
            cdir = split_dir / key
            if not cdir.is_dir():
                rep.error(f"缺类别目录: {cdir}")
                break
            cnt[key] = sum(1 for p in cdir.iterdir() if p.suffix.lower() == ".jpg")
        if len(cnt) == len(classes):
            total = sum(cnt.values())
            rep.ok(f"{split}: {total} 张（每类 min {min(cnt.values())} / "
                   f"max {max(cnt.values())}；normal 封顶后比 ≈2:1）")
            counts[split] = cnt

    rep.section("训练计划")
    rep.plan(f"arch={args.arch}（IMAGENET1K_V1 预训练，下载失败回退随机初始化并记录）")
    rep.plan(f"epochs={args.epochs}，batch={args.batch}，lr={args.lr}（AdamW wd=0.05 "
             f"+ cosine），size={args.size}²，device={args.device}，workers={args.workers}，"
             f"seed={args.seed}")
    rep.plan(f"训练增强: RandomHorizontalFlip(0.5) + ColorJitter{JITTER} + "
             f"Normalize(ImageNet)；评测仅 Resize + Normalize")
    rep.plan(f"类不平衡: {args.imbalance}"
             + ("（交叉熵权重 w_c=1/log(1.02+n_c)，n_c=train 每类实测数）"
                if args.imbalance == "loss-weight" else "（不加权，供对照）"))
    rep.plan("fp16 autocast+GradScaler（V100 支持 fp16；bf16 为 Ampere+ 特性，禁用）")
    rep.plan("每 epoch valid 逐类 F1/macro-F1，best 按 macro-F1 存 best.pt；"
             "holdout test 仅用 best 权重终评（永不入训练）")

    rep.section("输出计划")
    out_dir = resolve_path(args.out)
    rep.plan(f"{out_dir}/ 下: best.pt、last.pt、crop_cls.onnx、metrics.json")
    rep.plan(f"ONNX: opset 17 静态 1×3×{args.size}×{args.size}（TorchScript 导出器，"
             "不引入 onnxscript）")
    rep.plan(f"onnxruntime CPU 延迟: batch1 ×100（mean/p50/p95）+ batch64 ×20（吞吐）；"
             f"缺 onnxruntime 则延迟项记 error（需自行 pip install onnxruntime）")
    rep.plan(f"门禁: test macro-F1≥{GATE_MACRO_F1}、CPU batch1≤{GATE_CPU_MS}ms/粒"
             f"（--check-gates 时未达 → exit 1；默认只记录）")
    if args.limit_per_class:
        rep.plan(f"小样本自检模式：每 split 每类限 {args.limit_per_class} 张")
    return rep.finish()


def run(args: argparse.Namespace) -> int:
    """真实模式：扫描数据 → 训练 → best 终评 valid/test → 导出 → 测速 → metrics。"""
    import torch

    t_all = time.time()
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.backends.cudnn.benchmark = True  # 定长输入，选最快卷积实现
    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        print("[FAIL] --device 指定 cuda 但 torch.cuda.is_available()=False")
        return EXIT_FAILED
    use_amp = device.type == "cuda"  # V100：fp16 yes，bf16 no（Ampere+ 特性）

    # 数据扫描（结构性错误 → EXIT_USAGE，由 main 统一接）
    _, tax = build_categories()
    classes = list(tax.severity_order)
    crops_root = resolve_path(args.crops_dir)
    data = {s: scan_split(crops_root, s, classes, args.limit_per_class) for s in SPLITS}
    counts = {s: {k: len(v) for k, v in data[s].items()} for s in SPLITS}
    print(f"[数据] {crops_root}", flush=True)
    for s in SPLITS:
        print(f"  {s}: {sum(counts[s].values())} 张 "
              f"（min {min(counts[s].values())} / max {max(counts[s].values())}）", flush=True)

    # manifest 交叉核对（只读；不一致以磁盘实测为准并警告，不静默）。
    # --limit-per-class 是小样本自检通道，计数必然对不上 manifest → 跳过。
    manifest_note: str | None = None
    man_path = crops_root / "manifest.json"
    if man_path.is_file() and args.limit_per_class == 0:
        try:
            msplits = (load_json(man_path) or {}).get("splits", {})
            for s in SPLITS:
                for k in classes:
                    kept = msplits.get(s, {}).get("per_class", {}).get(k, {}).get("kept")
                    if kept is not None and int(kept) != counts[s][k]:
                        manifest_note = (f"{s}/{k} 磁盘实测 {counts[s][k]} != "
                                         f"manifest kept {kept}（以磁盘为准）")
                        print(f"[警告] {manifest_note}", flush=True)
        except (ValueError, FileNotFoundError) as exc:
            print(f"[警告] crops manifest 读取失败（不阻塞）: {exc}", flush=True)

    # transform / loader
    from torchvision import transforms
    train_tf = transforms.Compose([
        transforms.Resize((args.size, args.size)),
        transforms.RandomHorizontalFlip(0.5),
        transforms.ColorJitter(**JITTER),
        transforms.ToTensor(),
        transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
    ])
    eval_tf = transforms.Compose([
        transforms.Resize((args.size, args.size)),
        transforms.ToTensor(),
        transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
    ])
    items = {s: make_items(data[s]) for s in SPLITS}
    loaders = {
        "train": make_loader(items["train"], train_tf, args.batch, True,
                             args.workers, args.seed, device),
        "valid": make_loader(items["valid"], eval_tf, args.batch, False,
                             args.workers, args.seed + 1, device),
        "test": make_loader(items["test"], eval_tf, args.batch, False,
                            args.workers, args.seed + 1, device, persistent=False),
    }

    # 模型 / 类不平衡 loss 权重 / 优化器
    out_dir = resolve_path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    model, weights_source = build_model(args.arch, len(classes))
    model.to(device)
    print(f"[模型] resnet18 + {len(classes)} 类头，权重来源: {weights_source}", flush=True)

    class_weights: list[float] | None = None
    if args.imbalance == "loss-weight":
        class_weights = [1.0 / math.log(1.02 + counts["train"][k]) for k in classes]
        criterion = torch.nn.CrossEntropyLoss(
            weight=torch.tensor(class_weights, device=device))
        print("[不平衡] loss 权重 w_c=1/log(1.02+n_c)："
              + ", ".join(f"{k}={w:.3f}" for k, w in zip(classes, class_weights)),
              flush=True)
    else:
        criterion = torch.nn.CrossEntropyLoss()
        print("[不平衡] none（不加权，供对照）", flush=True)

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=5e-2)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)

    # 训练循环：每 epoch valid 评 macro-F1，best 存 best.pt，末轮存 last.pt
    history: list[dict] = []
    best_f1, best_epoch = -1.0, 0
    for ep in range(1, args.epochs + 1):
        lr_now = optimizer.param_groups[0]["lr"]
        loss, sec = train_one_epoch(model, loaders["train"], criterion, optimizer,
                                    scaler, device, use_amp, ep, args.epochs)
        scheduler.step()
        yt, yp = predict(model, loaders["valid"], device, use_amp)
        m = prf_cm(yt, yp, classes)
        print(f"[epoch {ep}/{args.epochs}] train_loss={loss:.4f} lr={lr_now:.2e} "
              f"valid_macro_f1={m['macro_f1']:.4f} acc={m['accuracy']:.4f}"
              f"（{sec:.0f}s）", flush=True)
        print("  逐类F1: " + " ".join(f"{k}={v['f1']:.3f}"
                                      for k, v in m["per_class"].items()), flush=True)
        history.append({
            "epoch": ep, "train_loss": round(loss, 6), "lr": lr_now,
            "valid_macro_f1": m["macro_f1"], "valid_accuracy": m["accuracy"],
            "valid_per_class_f1": {k: v["f1"] for k, v in m["per_class"].items()},
            "seconds": round(sec, 1),
        })
        ckpt = {"state_dict": model.state_dict(), "classes": classes, "arch": args.arch,
                "epoch": ep, "val_macro_f1": m["macro_f1"], "args": vars(args),
                "weights_source": weights_source}
        torch.save(ckpt, out_dir / "last.pt")
        if m["macro_f1"] > best_f1:
            best_f1, best_epoch = m["macro_f1"], ep
            torch.save(ckpt, out_dir / "best.pt")
            print(f"[best] epoch {ep} valid macro-F1 {best_f1:.4f} → best.pt", flush=True)

    if best_epoch == 0:
        print("[FAIL] 训练未产出任何 best（valid 评测全失败？）")
        return EXIT_FAILED

    # 终评：best 权重 → valid + test（holdout 只评一次，永不入训练）
    ck = torch.load(out_dir / "best.pt", map_location=device, weights_only=False)
    model.load_state_dict(ck["state_dict"])
    evals: dict[str, dict] = {}
    for s in ("valid", "test"):
        yt, yp = predict(model, loaders[s], device, use_amp)
        evals[s] = prf_cm(yt, yp, classes)
        print(f"[终评 {s}] macro-F1={evals[s]['macro_f1']:.4f} "
              f"acc={evals[s]['accuracy']:.4f}", flush=True)
        print("  逐类P/R/F1: " + " ".join(
            f"{k}={v['precision']:.3f}/{v['recall']:.3f}/{v['f1']:.3f}"
            for k, v in evals[s]["per_class"].items()), flush=True)
    train_seconds = round(time.time() - t_all, 1)
    print(f"[训练+终评完成] best_epoch={best_epoch}，总耗时 {train_seconds}s", flush=True)

    # ONNX 导出（best 模型）：交付件静态 batch1 + 测速基准件 batch64（不回传）
    export_info: dict = {}
    try:
        export_info = export_onnx(model, out_dir / "crop_cls.onnx", args.size)
        print(f"[导出] {export_info['onnx_path']}（opset 17 静态，"
              f"{export_info['bytes']} bytes，{export_info['exporter']}"
              + (f"，parity max|Δ|={export_info['parity_max_abs_diff']:.2e}"
                 if "parity_max_abs_diff" in export_info else "") + "）", flush=True)
        b64_info = export_onnx(model, out_dir / "crop_cls_b64.onnx", args.size, batch=64)
        export_info["bench_batch64"] = {"onnx_path": b64_info["onnx_path"],
                                        "bytes": b64_info["bytes"],
                                        "sha256": b64_info["sha256"],
                                        "note": "仅 batch64 吞吐测速用，非交付件"}
    except Exception as exc:
        export_info = {"error": f"{type(exc).__name__}: {exc}"}
        print(f"[FAIL] ONNX 导出失败: {exc}", flush=True)

    # onnxruntime CPU 延迟（batch1 单粒用交付件 + batch64 吞吐用基准件）
    latency: dict = {}
    try:
        latency = cpu_latency(out_dir / "crop_cls.onnx",
                              out_dir / "crop_cls_b64.onnx", args.size)
        print(f"[延迟] CPU batch1 mean={latency['batch1']['mean_ms']}ms "
              f"p95={latency['batch1']['p95_ms']}ms；batch64 "
              f"{latency['batch64']['mean_ms_per_image']}ms/图"
              f"（{latency['batch64']['throughput_imgs_per_s']} img/s）", flush=True)
    except Exception as exc:
        latency = {"error": f"{type(exc).__name__}: {exc}（README 依赖节：GPU 机需 "
                            "自行 pip install onnxruntime）"}
        print(f"[警告] CPU 延迟未测得: {exc}", flush=True)

    # 门禁对照（training-plan.md T4 备胎线）
    test_f1 = evals["test"]["macro_f1"]
    b1_mean = latency.get("batch1", {}).get("mean_ms") if isinstance(latency, dict) else None
    gates = {
        "macro_f1": {"basis": "training-plan T4：test split macro-F1",
                     "threshold": GATE_MACRO_F1, "value": test_f1,
                     "pass": bool(test_f1 >= GATE_MACRO_F1)},
        "cpu_ms_per_crop": {"basis": "training-plan T4：onnxruntime CPU batch1 mean",
                            "threshold": GATE_CPU_MS, "value": b1_mean,
                            "pass": (bool(b1_mean is not None and b1_mean <= GATE_CPU_MS))
                            if b1_mean is not None else False,
                            "not_evaluated": b1_mean is None},
    }
    for name, g in gates.items():
        state = "PASS" if g["pass"] else ("NOT_EVALUATED" if g.get("not_evaluated") else "FAIL")
        print(f"[门禁] {name}: value={g['value']} threshold={g['threshold']} → {state}",
              flush=True)

    metrics = {
        "prepared_by": "train/crop_classifier.py (beaneye 训练线 T4 备胎线)",
        "gate_basis": f"training-plan.md T4：单粒集 macro-F1≥{GATE_MACRO_F1}、"
                      f"CPU ONNX ≤{GATE_CPU_MS}ms/粒",
        "args": vars(args),
        "classes": classes,
        "weights_source": weights_source,
        "imbalance": {
            "method": args.imbalance,
            "formula": "w_c = 1/log(1.02 + n_c)，n_c = train split 类 c 实测裁片数",
            "class_weights": (dict(zip(classes, [round(w, 6) for w in class_weights]))
                              if class_weights else None),
        },
        "data": {
            "crops_dir": str(crops_root),
            "counts": counts,
            "manifest_crosscheck": manifest_note or "一致（或 manifest 缺省未核对）",
        },
        "train_seconds": train_seconds,
        "best_epoch": best_epoch,
        "history": history,
        "eval": evals,
        "top_confusions": {s: top_confusions(evals[s]["confusion_matrix"], classes)
                           for s in ("valid", "test")},
        "export": export_info,
        "latency": latency,
        "gates": gates,
        "total_seconds": round(time.time() - t_all, 1),
    }
    mpath = save_json(out_dir / "metrics.json", metrics)
    print(f"[metrics] {mpath}", flush=True)

    if args.check_gates:
        failed = [k for k, g in gates.items() if not g["pass"]]
        if failed:
            print(f"[FAIL] T4 门禁未达: {','.join(failed)}"
                  "（数值如实见 metrics.json，误差分析见 top_confusions）")
            return EXIT_FAILED
        print("[门禁] 全部 PASS（exit 0）")
    return EXIT_OK


def main() -> int:
    _common.setup_console()
    args = build_parser().parse_args()
    if args.epochs <= 0 or args.batch <= 0 or args.lr <= 0 or args.size <= 0 \
            or args.workers <= 0:
        print("[错误] --epochs/--batch/--lr/--size/--workers 须 >0")
        return EXIT_USAGE
    if args.limit_per_class < 0:
        print("[错误] --limit-per-class 须 >=0（0 = 全量）")
        return EXIT_USAGE
    rep = PlanReporter(dry_run=args.dry_run)
    try:
        if args.dry_run:
            return dry_run(args, rep)
        return run(args)
    except (ValueError, FileNotFoundError) as exc:
        print(f"[FAIL] 输入结构性错误: {exc}")  # crops 结构/类别表问题 → 2
        return EXIT_USAGE
    except RuntimeError as exc:
        print(f"[FAIL] {exc}")  # 执行期失败（CUDA OOM 等）→ 1
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
