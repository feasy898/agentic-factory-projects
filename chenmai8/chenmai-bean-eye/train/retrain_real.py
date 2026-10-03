#!/usr/bin/env python3
"""批5 真实数据重训分类腿：配方 A（纯真实）/ B（合成+真实过采样）对照（retrain_real）。

在批4 分类腿（``crop_classifier.py``，ResNet18 fp16，合成 20.8 万裁片，
test macro-F1 0.906766）基础上，回答「真实裁片能不能修好真实域表现」：

- **配方 A 纯真实**：只给 ``--real-roots``（多个真实裁片根，train/valid
  合并目录），不给 ``--synth-root``；真实 valid 合并为选型/汇报 holdout。
- **配方 B 混合**：加 ``--synth-root``（合成裁片根），真实项按
  ``--real-repeat`` 倍重复过采样混入训练集（重复因子如实计入 metrics，
  真实梯度占比 = n_real×repeat / (n_synth + n_real×repeat) 实测汇报）。
- ``--synth-eval-root``：配方 A 的合成评测通道（只评不训；合成 valid 逐
  epoch 跟踪、合成 test 终评，口径同批4）；给 ``--synth-root`` 时评测
  复用同一根，无需重复给。

真实裁片来源纪律：外部集以中性代号目录管理（如 ext-main/ext-scaa17/
ext-rgreen 训练池；eval_only 集不得传入 --real-roots，由调用方自律，
本脚本不认名字、只认传入目录）。

选型口径（两配方一致，与探针决胜对齐）
    每 epoch 评 真实 valid 合并集：**有 support 类的 macro-F1** 为 best
    依据（真实集若干类 0 训练样本，全类 macro 会被 0-support 类压住、
    失去区分度）；全 13 类 macro 同步记录。合成 valid macro 同 epoch
    跟踪（不参与选型）。holdout（合成 test、真实 valid）只在 best 权重
    上终评，任何 split 间无数据搬移。

类不平衡 / 超参
    与批4 完全同款：loss 权重 ``w_c = 1/log(1.02 + n_c)``（n_c = 有效
    训练计数 = 合成 + 真实×repeat；纯真实时即真实计数），AdamW lr 3e-4
    wd 0.05 + cosine，fp16 autocast+GradScaler（V100 无 bf16），8 epochs
    batch256，增强 RandomHorizontalFlip+ColorJitter（批4 JITTER 原值）。

预训练权重 / 导出 / 门禁
    IMAGENET1K_V1（下载失败回退随机初始化并记录）；ONNX opset17 静态
    batch1 交付 + batch64 测速件；对照门槛合成 test macro-F1 ≥0.85
    （批4=0.906766；--check-gates 未达 exit 1，默认只记录）。**本批决胜
    指标不在这里**：真实照片探针见 ``train/eval_real_probe.py``。

--dry-run：纯离线——扫描各根逐类计数、打印配方/有效梯度占比/权重表与
训练评测计划，结构性错误 exit 2。

期望运行时长（GPU 机 V100S 单卡卡0）
    A（真实 1.1 万裁片）≈3 min；B（合成 20.8 万 + 真实×4 ≈ 25.3 万）
    ≈30 min；加终评/导出/测速总墙钟 A ≈5 min、B ≈35 min。
"""

from __future__ import annotations

import argparse
import math
import sys
import time

import numpy as np  # 核心钉版依赖（非 NN 栈），dry-run 亦可承受

import _common
from _common import (
    EXIT_FAILED,
    EXIT_OK,
    EXIT_USAGE,
    PlanReporter,
    resolve_path,
    save_json,
)
import crop_classifier as cc  # 同目录批4实现：扫描/加载器/训练环/指标/导出全复用

# 对照门槛（批4 口径：合成 test macro-F1；批4 实测 0.906766）
GATE_SYNTH_MACRO_F1 = 0.85
BATCH4_TEST_MACRO_F1 = 0.906766  # 对照基线（beaneye-batch4/metrics.json 归档值）


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="批5 真实重训对照：A 纯真实 / B 合成+真实过采样（--dry-run 纯离线）",
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="不训练/不导出，只扫描计数并打印计划（离线，exit 0）")
    ap.add_argument("--real-roots", nargs="+", required=True,
                    help="真实裁片根列表（各含 train|valid/<classkey>/*.jpg；训练池合并）")
    ap.add_argument("--synth-root", default=None,
                    help="合成裁片根（给=配方 B 混入训练；缺=配方 A 纯真实）")
    ap.add_argument("--synth-eval-root", default=None,
                    help="合成评测根（配方 A 只评不训的合成 valid/test；--synth-root "
                         "给定时评测复用它，本参数忽略）")
    ap.add_argument("--real-repeat", type=int, default=1,
                    help="真实项过采样重复倍数（默认 1；配方 B 用 4，梯度占比见 metrics）")
    ap.add_argument("--out", default="train/runs/retrain_real",
                    help="输出目录（相对仓库根；默认 train/runs/retrain_real）")
    ap.add_argument("--epochs", type=int, default=8,
                    help="训练轮数（默认 8，同批4）")
    ap.add_argument("--batch", type=int, default=256,
                    help="batch size（默认 256，同批4）")
    ap.add_argument("--lr", type=float, default=3e-4,
                    help="AdamW 学习率（默认 3e-4；cosine，wd=0.05，同批4）")
    ap.add_argument("--size", type=int, default=224,
                    help="输入边长（默认 224）")
    ap.add_argument("--device", default="cuda:0",
                    help="训练设备（默认 cuda:0；本批承诺只用卡 0）")
    ap.add_argument("--workers", type=int, default=8,
                    help="DataLoader 进程数（默认 8，同批4）")
    ap.add_argument("--seed", type=int, default=0,
                    help="随机种子（默认 0）")
    ap.add_argument("--imbalance", default="loss-weight", choices=("loss-weight", "none"),
                    help="类不平衡方法（默认 loss-weight = 1/log(1.02+n_c)，n_c=有效计数）")
    ap.add_argument("--limit-per-class", type=int, default=0,
                    help="每根每 split 每类只取前 N 张（0 = 全量；链路自检用）")
    ap.add_argument("--check-gates", action="store_true",
                    help="对照门槛（合成 test macro-F1≥0.85）未达则 exit 1；默认只记录")
    return ap


# ---------------------------------------------------------------------------
# 多根扫描（真实集若干类可为空/缺目录，与合成严格扫描分开）
# ---------------------------------------------------------------------------


def scan_real_root(root, split: str, classes: list[str],
                   limit_per_class: int) -> dict[str, list]:
    """单个真实根的 split 扫描：缺类别目录/空类返回空表（合并后仍空才报错）。"""
    split_dir = root / split
    if not split_dir.is_dir():
        raise FileNotFoundError(f"真实根缺 split 目录: {split_dir}")
    out: dict[str, list] = {}
    for key in classes:
        cdir = split_dir / key
        files = sorted(p for p in cdir.iterdir() if p.suffix.lower() == ".jpg") \
            if cdir.is_dir() else []
        if limit_per_class > 0:
            files = files[:limit_per_class]
        out[key] = files
    return out


def merge_real(roots: list, split: str, classes: list[str],
               limit_per_class: int) -> dict[str, list]:
    """多根合并：{class: [相对来源标记的绝对路径,...]}（root→class 逐根拼接）。"""
    merged: dict[str, list] = {k: [] for k in classes}
    for root in roots:
        part = scan_real_root(root, split, classes, limit_per_class)
        for k in classes:
            merged[k].extend(part[k])
    return merged


def count_map(data: dict[str, list]) -> dict[str, int]:
    return {k: len(v) for k, v in data.items()}


# ---------------------------------------------------------------------------
# dry-run / run / main
# ---------------------------------------------------------------------------


def dry_run(args: argparse.Namespace, rep: PlanReporter) -> int:
    rep.header("retrain_real.py", "批5 真实数据重训对照（A 纯真实 / B 混合）")
    _, tax = _common.build_categories()
    classes = list(tax.severity_order)
    rep.section("输入")
    roots = [resolve_path(r) for r in args.real_roots]
    for r in roots:
        rep.check_dir(r, "真实根")
    synth_root = resolve_path(args.synth_root) if args.synth_root else None
    synth_eval_root = (resolve_path(args.synth_eval_root)
                       if args.synth_eval_root and not synth_root else None)
    if synth_root:
        rep.check_dir(synth_root, "合成根（配方 B，混入训练）")
    if synth_eval_root:
        rep.check_dir(synth_eval_root, "合成评测根（配方 A，只评不训）")
    recipe = "B-mixed" if synth_root else "A-pure-real"
    rep.plan(f"配方 = {recipe}；真实 repeat={args.real_repeat}")

    counts: dict = {}
    try:
        real_train = merge_real(roots, "train", classes, args.limit_per_class)
        real_valid = merge_real(roots, "valid", classes, args.limit_per_class)
        counts["real_train_merged"] = count_map(real_train)
        counts["real_valid_merged"] = count_map(real_valid)
        per_root = {}
        for r in roots:
            per_root[str(r)] = {
                "train": count_map(scan_real_root(r, "train", classes, args.limit_per_class)),
                "valid": count_map(scan_real_root(r, "valid", classes, args.limit_per_class)),
            }
        counts["real_by_root"] = per_root
    except (FileNotFoundError, ValueError) as exc:
        rep.error(str(exc))
        return rep.finish()
    n_real = sum(counts["real_train_merged"].values())
    n_real_valid = sum(counts["real_valid_merged"].values())
    rep.ok(f"真实 train 合并 {n_real} 张 / valid 合并 {n_real_valid} 张")
    zero_cls = [k for k, v in counts["real_train_merged"].items() if v == 0]
    if zero_cls:
        rep.missing(f"真实训练 0 样本类（如实记录，不阻塞）: {','.join(zero_cls)}")

    n_synth = 0
    if synth_root:
        try:
            synth = {s: cc.scan_split(synth_root, s, classes, args.limit_per_class)
                     for s in cc.SPLITS}
        except (FileNotFoundError, ValueError) as exc:
            rep.error(f"合成根: {exc}")
            return rep.finish()
        counts["synth"] = {s: count_map(synth[s]) for s in cc.SPLITS}
        n_synth = sum(counts["synth"]["train"].values())
        rep.ok(f"合成 train {n_synth} 张（valid/test 同批4 口径）")
    elif synth_eval_root:
        try:
            se = {s: cc.scan_split(synth_eval_root, s, classes, args.limit_per_class)
                  for s in ("valid", "test")}
        except (FileNotFoundError, ValueError) as exc:
            rep.error(f"合成评测根: {exc}")
            return rep.finish()
        counts["synth_eval_only"] = {s: count_map(se[s]) for s in ("valid", "test")}

    n_eff_real = n_real * args.real_repeat
    share = 100.0 * n_eff_real / (n_synth + n_eff_real) if (n_synth or n_eff_real) else 0.0
    rep.section("配方与梯度占比")
    rep.plan(f"有效训练样本 = " + (
        f"合成 {n_synth} + 真实 {n_real}×{args.real_repeat} = {n_synth + n_eff_real}"
        if synth_root else f"纯真实 {n_eff_real}（repeat={args.real_repeat}）"))
    if synth_root:
        rep.plan(f"真实梯度占比（重复因子计入）≈ {share:.1f}%")
    if args.imbalance == "loss-weight":
        eff = {k: (counts["synth"]["train"].get(k, 0) if synth_root else 0)
               + counts["real_train_merged"][k] * args.real_repeat for k in classes}
        rep.plan("loss 权重 w_c=1/log(1.02+n_c)（有效计数）: "
                 + ", ".join(f"{k}={1.0 / math.log(1.02 + n):.3f}" for k, n in eff.items()))
    rep.section("训练与评测计划")
    rep.plan(f"resnet18 IMAGENET1K_V1，epochs={args.epochs}，batch={args.batch}，"
             f"lr={args.lr}（AdamW wd=0.05+cosine），fp16 autocast（V100 无 bf16），"
             f"device={args.device}（承诺只用卡 0），workers={args.workers}，seed={args.seed}")
    rep.plan("选型：每 epoch 真实 valid 合并集 macro-F1（有 support 类）最高者存 best.pt；"
             "合成 valid 同步跟踪不选型；holdout 终评只跑 best")
    rep.plan("终评：真实 valid 全类 PRF+混淆；合成 valid/test（若给根）同批4 口径")
    rep.plan("导出：opset17 静态 batch1 交付 + batch64 测速件；CPU 延迟 batch1×100/batch64×20")
    rep.plan(f"对照门槛：合成 test macro-F1≥{GATE_SYNTH_MACRO_F1}"
             f"（批4={BATCH4_TEST_MACRO_F1}；决胜指标=真实照片探针，见 train/eval_real_probe.py）")
    rep.plan(f"输出 → {resolve_path(args.out)}/: best.pt、last.pt、crop_cls.onnx、metrics.json")
    return rep.finish()


def run(args: argparse.Namespace) -> int:
    import torch

    t_all = time.time()
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.backends.cudnn.benchmark = True
    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        print("[FAIL] --device 指定 cuda 但 torch.cuda.is_available()=False")
        return EXIT_FAILED
    use_amp = device.type == "cuda"

    _, tax = _common.build_categories()
    classes = list(tax.severity_order)
    roots = [resolve_path(r) for r in args.real_roots]
    synth_root = resolve_path(args.synth_root) if args.synth_root else None
    synth_eval_root = (resolve_path(args.synth_eval_root)
                       if args.synth_eval_root and not synth_root else None)

    # ---- 数据扫描：真实合并 +（可选）合成 ----
    real_train = merge_real(roots, "train", classes, args.limit_per_class)
    real_valid = merge_real(roots, "valid", classes, args.limit_per_class)
    counts: dict = {"real_train_merged": count_map(real_train),
                    "real_valid_merged": count_map(real_valid),
                    "real_by_root": {}}
    for r in roots:
        counts["real_by_root"][str(r)] = {
            "train": count_map(scan_real_root(r, "train", classes, args.limit_per_class)),
            "valid": count_map(scan_real_root(r, "valid", classes, args.limit_per_class))}
    n_real = sum(counts["real_train_merged"].values())
    if n_real == 0:
        print("[FAIL] 真实训练集合并后为空")
        return EXIT_USAGE
    zero_cls = [k for k, v in counts["real_train_merged"].items() if v == 0]
    if zero_cls:
        print(f"[警告] 真实训练 0 样本类: {','.join(zero_cls)}（如实记录）", flush=True)

    synth = None
    if synth_root:
        synth = {s: cc.scan_split(synth_root, s, classes, args.limit_per_class)
                 for s in cc.SPLITS}
        counts["synth"] = {s: count_map(synth[s]) for s in cc.SPLITS}
    elif synth_eval_root:
        synth_eval = {s: cc.scan_split(synth_eval_root, s, classes, args.limit_per_class)
                      for s in ("valid", "test")}
        counts["synth_eval_only"] = {s: count_map(synth_eval[s]) for s in ("valid", "test")}
    else:
        synth_eval = None
    if synth_root:
        synth_eval = synth  # 评测复用同一根

    n_eff_real = n_real * args.real_repeat
    n_synth = sum(counts["synth"]["train"].values()) if synth else 0
    real_share = round(100.0 * n_eff_real / (n_synth + n_eff_real), 2) if (n_synth + n_eff_real) else 0.0
    print(f"[数据] 真实根 {len(roots)} 个：train 合并 {n_real} 张"
          f"（有效 ×{args.real_repeat} = {n_eff_real}）/ valid 合并 "
          f"{sum(counts['real_valid_merged'].values())} 张", flush=True)
    if synth:
        print(f"[数据] 合成根 {synth_root}：train {n_synth} 张；"
              f"真实梯度占比 ≈ {real_share}%", flush=True)

    # ---- transform / loader（批4 同款增强与归一化）----
    from torchvision import transforms
    train_tf = transforms.Compose([
        transforms.Resize((args.size, args.size)),
        transforms.RandomHorizontalFlip(0.5),
        transforms.ColorJitter(**cc.JITTER),
        transforms.ToTensor(),
        transforms.Normalize(cc.IMAGENET_MEAN, cc.IMAGENET_STD),
    ])
    eval_tf = transforms.Compose([
        transforms.Resize((args.size, args.size)),
        transforms.ToTensor(),
        transforms.Normalize(cc.IMAGENET_MEAN, cc.IMAGENET_STD),
    ])
    items_real_train = cc.make_items(real_train) * args.real_repeat  # 过采样=列表重复
    items_synth_train = cc.make_items(synth["train"]) if synth else []
    items_train = items_synth_train + items_real_train  # 配方B=合成+真实×repeat；配方A=纯真实
    print(f"[训练集] 合成 {len(items_synth_train)} + 真实×{args.real_repeat} "
          f"{len(items_real_train)} = {len(items_train)} 项/epoch"
          f"（{len(items_train) // args.batch} iter）", flush=True)
    items_real_valid = cc.make_items(real_valid)
    loaders = {
        "train": cc.make_loader(items_train, train_tf, args.batch, True,
                                args.workers, args.seed, device),
        "real_valid": cc.make_loader(items_real_valid, eval_tf, args.batch, False,
                                     args.workers, args.seed + 1, device),
    }
    if synth:
        loaders["synth_valid"] = cc.make_loader(
            cc.make_items(synth["valid"]), eval_tf, args.batch, False,
            args.workers, args.seed + 1, device, persistent=False)
    elif synth_eval:
        # 配方 A：合成 valid 只作逐 epoch 域差跟踪（不参与选型）
        loaders["synth_valid"] = cc.make_loader(
            cc.make_items(synth_eval["valid"]), eval_tf, args.batch, False,
            args.workers, args.seed + 1, device, persistent=False)
    if synth_eval:
        loaders["synth_test"] = cc.make_loader(
            cc.make_items(synth_eval["test"]), eval_tf, args.batch, False,
            args.workers, args.seed + 1, device, persistent=False)

    # ---- 模型 / loss 权重（有效计数）/ 优化器（批4 超参）----
    out_dir = resolve_path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    model, weights_source = cc.build_model("resnet18", len(classes))
    model.to(device)
    print(f"[模型] resnet18 + {len(classes)} 类头，权重来源: {weights_source}", flush=True)

    class_weights: list[float] | None = None
    if args.imbalance == "loss-weight":
        eff = {k: (counts["synth"]["train"].get(k, 0) if synth else 0)
               + counts["real_train_merged"][k] * args.real_repeat for k in classes}
        class_weights = [1.0 / math.log(1.02 + eff[k]) for k in classes]
        criterion = torch.nn.CrossEntropyLoss(
            weight=torch.tensor(class_weights, device=device))
        print("[不平衡] loss 权重 w_c=1/log(1.02+n_eff_c)（有效计数）："
              + ", ".join(f"{k}={w:.3f}" for k, w in zip(classes, class_weights)),
              flush=True)
    else:
        criterion = torch.nn.CrossEntropyLoss()
        print("[不平衡] none（不加权，供对照）", flush=True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=5e-2)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)

    def eval_split(name: str):
        yt, yp = cc.predict(model, loaders[name], device, use_amp)
        return prf_full(yt, yp, classes)

    def prf_full(yt, yp, cls_):
        m = cc.prf_cm(yt, yp, cls_)  # 全类 macro（0-support 类 f1=0 计入）
        sup = [i for i, k in enumerate(cls_) if m["per_class"][k]["support"] > 0]
        f1s = [m["per_class"][cls_[i]]["f1"] for i in sup]
        m["macro_f1_supported"] = round(float(np.mean(f1s)), 6) if f1s else 0.0
        m["supported_classes"] = [cls_[i] for i in sup]
        return m

    # ---- 训练循环：best = 真实 valid 有 support 类 macro-F1 ----
    history: list[dict] = []
    best_key, best_epoch = -1.0, 0
    for ep in range(1, args.epochs + 1):
        lr_now = optimizer.param_groups[0]["lr"]
        loss, sec = cc.train_one_epoch(model, loaders["train"], criterion,
                                       optimizer, scaler, device, use_amp, ep, args.epochs)
        scheduler.step()
        rv = eval_split("real_valid")
        line = (f"[epoch {ep}/{args.epochs}] train_loss={loss:.4f} lr={lr_now:.2e} "
                f"real_valid_macro_sup={rv['macro_f1_supported']:.4f} "
                f"real_valid_macro_all13={rv['macro_f1']:.4f}（{sec:.0f}s）")
        sv = None
        if "synth_valid" in loaders:
            sv = eval_split("synth_valid")
            line += f" synth_valid_macro={sv['macro_f1']:.4f}"
        print(line, flush=True)
        print("  真实valid逐类F1: " + " ".join(
            f"{k}={v['f1']:.3f}" for k, v in rv["per_class"].items()
            if v["support"] > 0), flush=True)
        history.append({
            "epoch": ep, "train_loss": round(loss, 6), "lr": lr_now,
            "real_valid_macro_f1_supported": rv["macro_f1_supported"],
            "real_valid_macro_f1_all13": rv["macro_f1"],
            "synth_valid_macro_f1": sv["macro_f1"] if sv else None,
            "seconds": round(sec, 1),
        })
        ckpt = {"state_dict": model.state_dict(), "classes": classes, "arch": "resnet18",
                "epoch": ep, "real_valid_macro_f1_supported": rv["macro_f1_supported"],
                "args": vars(args), "weights_source": weights_source}
        torch.save(ckpt, out_dir / "last.pt")
        if rv["macro_f1_supported"] > best_key:
            best_key, best_epoch = rv["macro_f1_supported"], ep
            torch.save(ckpt, out_dir / "best.pt")
            print(f"[best] epoch {ep} 真实valid macro(sup) {best_key:.4f} → best.pt",
                  flush=True)

    if best_epoch == 0:
        print("[FAIL] 训练未产出任何 best（真实 valid 评测全失败？）")
        return EXIT_FAILED

    # ---- 终评：best 权重 → 真实 valid +（可选）合成 valid/test ----
    ck = torch.load(out_dir / "best.pt", map_location=device, weights_only=False)
    model.load_state_dict(ck["state_dict"])
    evals: dict[str, dict] = {"real_valid": eval_split("real_valid")}
    print(f"[终评 real_valid] macro(sup)={evals['real_valid']['macro_f1_supported']:.4f} "
          f"macro(all13)={evals['real_valid']['macro_f1']:.4f}", flush=True)
    for s in ("synth_valid", "synth_test"):
        if s in loaders:
            evals[s] = eval_split(s)
            print(f"[终评 {s}] macro-F1={evals[s]['macro_f1']:.4f} "
                  f"acc={evals[s]['accuracy']:.4f}", flush=True)
            print("  逐类P/R/F1: " + " ".join(
                f"{k}={v['precision']:.3f}/{v['recall']:.3f}/{v['f1']:.3f}"
                for k, v in evals[s]["per_class"].items()), flush=True)
    train_seconds = round(time.time() - t_all, 1)
    print(f"[训练+终评完成] best_epoch={best_epoch}，总耗时 {train_seconds}s", flush=True)

    # ---- ONNX 导出（批4 同款：batch1 交付 + batch64 测速）----
    export_info: dict = {}
    try:
        export_info = cc.export_onnx(model, out_dir / "crop_cls.onnx", args.size)
        print(f"[导出] crop_cls.onnx（opset 17 静态，{export_info['bytes']} bytes）",
              flush=True)
        b64 = cc.export_onnx(model, out_dir / "crop_cls_b64.onnx", args.size, batch=64)
        export_info["bench_batch64"] = {"onnx_path": b64["onnx_path"],
                                        "bytes": b64["bytes"], "sha256": b64["sha256"],
                                        "note": "仅 batch64 吞吐测速用，非交付件"}
    except Exception as exc:
        export_info = {"error": f"{type(exc).__name__}: {exc}"}
        print(f"[FAIL] ONNX 导出失败: {exc}", flush=True)
    latency: dict = {}
    try:
        latency = cc.cpu_latency(out_dir / "crop_cls.onnx",
                                 out_dir / "crop_cls_b64.onnx", args.size)
        print(f"[延迟] CPU batch1 mean={latency['batch1']['mean_ms']}ms", flush=True)
    except Exception as exc:
        latency = {"error": f"{type(exc).__name__}: {exc}"}
        print(f"[警告] CPU 延迟未测得: {exc}", flush=True)

    test_f1 = evals.get("synth_test", {}).get("macro_f1")
    gates = {
        "synth_test_macro_f1": {
            "basis": f"批5 对照门槛：合成 test macro-F1≥{GATE_SYNTH_MACRO_F1}"
                     f"（批4={BATCH4_TEST_MACRO_F1}；决胜=真实照片探针）",
            "threshold": GATE_SYNTH_MACRO_F1, "value": test_f1,
            "pass": bool(test_f1 is not None and test_f1 >= GATE_SYNTH_MACRO_F1),
            "not_evaluated": test_f1 is None,
        },
    }
    for name, g in gates.items():
        state = "PASS" if g["pass"] else ("NOT_EVALUATED" if g.get("not_evaluated") else "FAIL")
        print(f"[门槛] {name}: value={g['value']} threshold={g['threshold']} → {state}",
              flush=True)

    metrics = {
        "prepared_by": "train/retrain_real.py（beaneye 批5 真实重训对照线）",
        "recipe": "B-mixed" if synth_root else "A-pure-real",
        "gate_basis": f"决胜=真实照片探针 train/eval_real_probe.py；对照门槛="
                      f"合成 test macro-F1≥{GATE_SYNTH_MACRO_F1}（批4="
                      f"{BATCH4_TEST_MACRO_F1}）",
        "args": vars(args),
        "classes": classes,
        "weights_source": weights_source,
        "selection": {
            "metric": "real_valid_macro_f1_supported",
            "note": "真实 valid 合并集、有 support 类的 macro-F1（两配方一致；"
                    "全 13 类口径同记；0-support 类真实训练不存在样本）",
        },
        "imbalance": {
            "method": args.imbalance,
            "formula": "w_c = 1/log(1.02 + n_eff_c)，n_eff_c = 合成(若混入) + 真实×repeat",
            "class_weights": (dict(zip(classes, [round(w, 6) for w in class_weights]))
                              if class_weights else None),
        },
        "data": {
            "real_roots": [str(r) for r in roots],
            "synth_root": str(synth_root) if synth_root else None,
            "synth_eval_root": str(synth_eval_root) if (synth_eval_root and not synth_root) else None,
            "real_repeat": args.real_repeat,
            "real_train": n_real,
            "real_train_effective": n_eff_real,
            "synth_train": n_synth,
            "real_gradient_share_pct": real_share if synth_root else None,
            "zero_train_classes": zero_cls,
            "counts": counts,
        },
        "train_seconds": train_seconds,
        "best_epoch": best_epoch,
        "history": history,
        "eval": evals,
        "top_confusions": {s: cc.top_confusions(evals[s]["confusion_matrix"], classes)
                           for s in evals if "confusion_matrix" in evals[s]},
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
            print(f"[FAIL] 对照门槛未达: {','.join(failed)}（数值如实见 metrics.json）")
            return EXIT_FAILED
        print("[门槛] 全部 PASS（exit 0）")
    return EXIT_OK


def main() -> int:
    _common.setup_console()
    args = build_parser().parse_args()
    if args.epochs <= 0 or args.batch <= 0 or args.lr <= 0 or args.size <= 0 \
            or args.workers <= 0 or args.real_repeat <= 0:
        print("[错误] --epochs/--batch/--lr/--size/--workers/--real-repeat 须 >0")
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
        print(f"[FAIL] 输入结构性错误: {exc}")
        return EXIT_USAGE
    except RuntimeError as exc:
        print(f"[FAIL] {exc}")
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
