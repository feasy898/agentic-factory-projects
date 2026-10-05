#!/usr/bin/env python3
"""批13 缺陷过采样重训对照：批12 配方 + 单变量「非 normal 全部训练裁片 ×8」。

基于 train/retrain_real.py（批12 交付件 sha256 92527f6b…）复制改写，回答
「缺陷过采样能不能把坏堆检出救回来、normal 及格率要赔多少」：

- **唯一配方改动**：真实**训练**裁片中全部非 normal 类（12 类；web/ext 缺陷
  裁片都算）按 ``--defect-oversample``（批13=8）额外过采样；normal 保持批12
  原量（real_repeat=3）。即有效重复 = normal ×3、缺陷类 ×(3×8)=×24。
  任务给定类名单 black/broken/insect/sour/mold/shell/immature/faded/elephant/
  dried 后接「非 normal 全部」——按后者执行，peaberry（非 normal，有真实样本）
  一并过采样、brocade（真实训练 0 张）无操作，均如实记录。
- **其余逐项同批12**：合成回放（/data/coffee-bean/crops 全量）、real_repeat=3、
  epochs=8、batch=256、lr=3e-4（AdamW wd=0.05+cosine）、fp16 autocast、seed=0、
  只用卡0、增强同款；loss 权重公式不变 w_c=1/log(1.02+n_eff_c)，n_eff 按本批
  过采样后的真实有效计数重算（公式同源，输入计数如实反映过采样）。
- **起点纪律**：对照锚点 = 批12 best checkpoint（/data/coffee-bean/
  batch12-results/best.pt，best_epoch=7）。本脚本训练与批12 同从
  IMAGENET1K_V1 起步——保证两批唯一差异是过采样，而非起点权重。
- valid **永不过采样**（过采样只作用于训练裁片列表；选型与终评集合不动）。
- 选型/评测/导出/门禁口径与 retrain_real.py 逐项一致：real_valid macro(sup)
  选 best；合成 valid 逐 epoch 跟踪；终评 real_valid + synth valid/test；
  ONNX opset17 静态 batch1 + batch64 测速件；合成 test macro-F1≥0.85 门。
  holdout（real-photos 26 张）不在本脚本内，训练后由 eval_real_probe.py 单独评测。

--dry-run：纯离线——扫描各根逐类计数、打印过采样方案/逐类有效计数/权重表
与训练评测计划，结构性错误 exit 2。

运行时长预期（V100S 卡0）：约批12（1908s）的 1.5–1.8 倍，≈50–60 min。
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
from retrain_real import (  # 批12 交付件本体：扫描/合并/门槛常量零漂移复用
    BATCH4_TEST_MACRO_F1,
    GATE_SYNTH_MACRO_F1,
    count_map,
    merge_real,
    scan_real_root,
)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="批13 缺陷过采样重训：批12 配方 + 非 normal 训练裁片×8"
                    "（--dry-run 纯离线）",
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="不训练/不导出，只扫描计数并打印计划（离线，exit 0）")
    ap.add_argument("--real-roots", nargs="+", required=True,
                    help="真实裁片根列表（各含 train|valid/<classkey>/*.jpg；与批12 同 7 根）")
    ap.add_argument("--synth-root", default=None,
                    help="合成裁片根（批13 = /data/coffee-bean/crops 全量回放）")
    ap.add_argument("--synth-eval-root", default=None,
                    help="合成评测根（--synth-root 给定时忽略，同 retrain_real.py）")
    ap.add_argument("--real-repeat", type=int, default=3,
                    help="真实项基础重复倍数（默认 3，同批12；normal 最终即此倍数）")
    ap.add_argument("--defect-oversample", type=int, default=1,
                    help="非 normal 全部类的真实训练裁片额外过采样倍数（默认 1=关；"
                         "批13=8 → 缺陷类有效重复 = real_repeat×8）")
    ap.add_argument("--out", default="train/runs/retrain_b13_defos8",
                    help="输出目录（相对仓库根）")
    ap.add_argument("--epochs", type=int, default=8,
                    help="训练轮数（默认 8，同批12）")
    ap.add_argument("--batch", type=int, default=256,
                    help="batch size（默认 256，同批12）")
    ap.add_argument("--lr", type=float, default=3e-4,
                    help="AdamW 学习率（默认 3e-4；cosine，wd=0.05，同批12）")
    ap.add_argument("--size", type=int, default=224,
                    help="输入边长（默认 224）")
    ap.add_argument("--device", default="cuda:0",
                    help="训练设备（默认 cuda:0；承诺只用卡 0，卡1 是 vLLM）")
    ap.add_argument("--workers", type=int, default=8,
                    help="DataLoader 进程数（默认 8，同批12）")
    ap.add_argument("--seed", type=int, default=0,
                    help="随机种子（默认 0，同批12）")
    ap.add_argument("--imbalance", default="loss-weight", choices=("loss-weight", "none"),
                    help="类不平衡方法（默认 loss-weight = 1/log(1.02+n_eff_c)，"
                         "n_eff 按过采样后有效计数）")
    ap.add_argument("--limit-per-class", type=int, default=0,
                    help="每根每 split 每类只取前 N 张（0 = 全量；链路自检用）")
    ap.add_argument("--check-gates", action="store_true",
                    help="对照门槛（合成 test macro-F1≥0.85）未达则 exit 1；默认只记录")
    return ap


def repeat_by_class(classes: list[str], real_repeat: int,
                    defect_oversample: int) -> dict[str, int]:
    """逐类有效重复：normal=real_repeat；非 normal 全部=real_repeat×defect_oversample。"""
    return {k: (real_repeat * defect_oversample if k != "normal" and defect_oversample > 1
                else real_repeat) for k in classes}


# ---------------------------------------------------------------------------
# dry-run / run / main（除过采样三处外与 retrain_real.py 同构）
# ---------------------------------------------------------------------------


def dry_run(args: argparse.Namespace, rep: PlanReporter) -> int:
    rep.header("retrain_real_b13.py", "批13 缺陷过采样重训（批12 配方+缺陷×8）")
    _, tax = _common.build_categories()
    classes = list(tax.severity_order)
    rep_by = repeat_by_class(classes, args.real_repeat, args.defect_oversample)
    rep.section("输入")
    roots = [resolve_path(r) for r in args.real_roots]
    for r in roots:
        rep.check_dir(r, "真实根")
    synth_root = resolve_path(args.synth_root) if args.synth_root else None
    if synth_root:
        rep.check_dir(synth_root, "合成根（混入训练）")
    rep.plan(f"配方 = 批12 同款混合 + 缺陷过采样；real_repeat={args.real_repeat}，"
             f"defect_oversample={args.defect_oversample}")

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
    rep.ok(f"真实 train 合并 {n_real} 张 / valid 合并 {n_real_valid} 张"
           f"（valid 不过采样）")
    n_eff_by_class = {k: counts["real_train_merged"][k] * rep_by[k] for k in classes}
    n_eff_real = sum(n_eff_by_class.values())
    rep.section("过采样方案（唯一变量）")
    rep.plan("逐类有效重复: " + ", ".join(f"{k}×{rep_by[k]}" for k in classes))
    rep.plan("逐类真实有效计数: " + ", ".join(
        f"{k}={n_eff_by_class[k]}" for k in classes if counts["real_train_merged"][k] or rep_by[k] > args.real_repeat))
    zero_cls = [k for k, v in counts["real_train_merged"].items() if v == 0]
    if zero_cls:
        rep.missing(f"真实训练 0 样本类（过采样无操作，如实记录）: {','.join(zero_cls)}")

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
        rep.ok(f"合成 train {n_synth} 张（valid/test 同批4/批12 口径）")
    share = 100.0 * n_eff_real / (n_synth + n_eff_real) if (n_synth or n_eff_real) else 0.0
    defect_eff = sum(v for k, v in n_eff_by_class.items() if k != "normal")
    total_eff = n_synth + n_eff_real
    rep.section("配方与梯度占比")
    rep.plan(f"有效训练样本/epoch = 合成 {n_synth} + 真实原量 {n_real}"
             f"×（normal×{rep_by['normal']} / 缺陷×{args.real_repeat}×{args.defect_oversample}）"
             f" = {total_eff}")
    rep.plan(f"真实梯度占比 ≈ {share:.1f}%；其中缺陷类占比 ≈ "
             f"{100.0 * defect_eff / total_eff:.1f}%（对照批12 缺陷类 ≈ "
             f"{100.0 * (28741 - counts['real_train_merged']['normal']) * args.real_repeat / (208058 + 28741 * args.real_repeat):.1f}%）")
    if args.imbalance == "loss-weight":
        eff = {k: (counts["synth"]["train"].get(k, 0) if synth_root else 0)
               + n_eff_by_class[k] for k in classes}
        rep.plan("loss 权重 w_c=1/log(1.02+n_eff_c)（过采样后有效计数）: "
                 + ", ".join(f"{k}={1.0 / math.log(1.02 + n):.3f}" for k, n in eff.items()))
    rep.section("训练与评测计划")
    rep.plan(f"resnet18 IMAGENET1K_V1 起点（与批12 同起点，非批12 权重热启动），"
             f"epochs={args.epochs}，batch={args.batch}，lr={args.lr}"
             f"（AdamW wd=0.05+cosine），fp16 autocast，device={args.device}（只用卡0），"
             f"workers={args.workers}，seed={args.seed}")
    rep.plan("选型：每 epoch 真实 valid 合并集 macro-F1（有 support 类）最高者存 best.pt；"
             "valid 集不过采样；holdout（real-photos 26 张）训练后由 eval_real_probe.py 单评")
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
    rep_by = repeat_by_class(classes, args.real_repeat, args.defect_oversample)

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
        print(f"[警告] 真实训练 0 样本类: {','.join(zero_cls)}（过采样无操作，如实记录）",
              flush=True)

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

    # ---- 过采样（唯一变量）：逐类列表重复；normal 保持 real_repeat 原量 ----
    n_eff_by_class = {k: counts["real_train_merged"][k] * rep_by[k] for k in classes}
    n_eff_real = sum(n_eff_by_class.values())
    n_synth = sum(counts["synth"]["train"].values()) if synth else 0
    real_share = round(100.0 * n_eff_real / (n_synth + n_eff_real), 2) if (n_synth + n_eff_real) else 0.0
    defect_eff = sum(v for k, v in n_eff_by_class.items() if k != "normal")
    defect_share = round(100.0 * defect_eff / (n_synth + n_eff_real), 2) if (n_synth + n_eff_real) else 0.0
    print(f"[数据] 真实根 {len(roots)} 个：train 合并 {n_real} 张"
          f"（normal×{rep_by['normal']} / 非 normal×{rep_by['broken']}，"
          f"有效 {n_eff_real}）/ valid 合并 "
          f"{sum(counts['real_valid_merged'].values())} 张（不过采样）", flush=True)
    if synth:
        print(f"[数据] 合成根 {synth_root}：train {n_synth} 张；真实梯度占比 ≈ "
              f"{real_share}%（缺陷类 {defect_share}%）", flush=True)

    # ---- transform / loader（批4/批12 同款增强与归一化）----
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
    # 过采样=逐类列表重复（整字典一次 make_items，label 对齐 severity_order 位次）
    items_real_train = cc.make_items({k: real_train[k] * rep_by[k] for k in classes})
    items_synth_train = cc.make_items(synth["train"]) if synth else []
    items_train = items_synth_train + items_real_train
    print(f"[训练集] 合成 {len(items_synth_train)} + 真实过采样 "
          f"{len(items_real_train)}（normal×{rep_by['normal']}/缺陷"
          f"×{rep_by['black']}） = {len(items_train)} 项/epoch"
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
        loaders["synth_valid"] = cc.make_loader(
            cc.make_items(synth_eval["valid"]), eval_tf, args.batch, False,
            args.workers, args.seed + 1, device, persistent=False)
    if synth_eval:
        loaders["synth_test"] = cc.make_loader(
            cc.make_items(synth_eval["test"]), eval_tf, args.batch, False,
            args.workers, args.seed + 1, device, persistent=False)

    # ---- 模型 / loss 权重（过采样后有效计数）/ 优化器（批12 超参）----
    out_dir = resolve_path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    model, weights_source = cc.build_model("resnet18", len(classes))
    model.to(device)
    print(f"[模型] resnet18 + {len(classes)} 类头，权重来源: {weights_source}"
          f"（批12 同起点，非批12 权重热启动）", flush=True)

    class_weights: list[float] | None = None
    if args.imbalance == "loss-weight":
        eff = {k: (counts["synth"]["train"].get(k, 0) if synth else 0)
               + n_eff_by_class[k] for k in classes}
        class_weights = [1.0 / math.log(1.02 + eff[k]) for k in classes]
        criterion = torch.nn.CrossEntropyLoss(
            weight=torch.tensor(class_weights, device=device))
        print("[不平衡] loss 权重 w_c=1/log(1.02+n_eff_c)（过采样后有效计数）："
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

    # ---- ONNX 导出（批4/批12 同款：batch1 交付 + batch64 测速）----
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
            "basis": f"批12 同门槛：合成 test macro-F1≥{GATE_SYNTH_MACRO_F1}"
                     f"（批4={BATCH4_TEST_MACRO_F1}；批12 实测 0.884087；决胜=真实照片探针）",
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
        "prepared_by": "train/retrain_real_b13.py（批13 缺陷过采样重训线；"
                       "基于批12 retrain_real.py sha256 92527f6b… 复制改写）",
        "recipe": "b12-recipe + defect-oversample",
        "gate_basis": f"决胜=真实照片探针 train/eval_real_probe.py；对照门槛="
                      f"合成 test macro-F1≥{GATE_SYNTH_MACRO_F1}（批4="
                      f"{BATCH4_TEST_MACRO_F1}；批12=0.884087）",
        "args": vars(args),
        "classes": classes,
        "weights_source": weights_source,
        "selection": {
            "metric": "real_valid_macro_f1_supported",
            "note": "真实 valid 合并集、有 support 类的 macro-F1（与批12 一致；"
                    "valid 集不过采样）",
        },
        "oversample": {
            "defect_oversample": args.defect_oversample,
            "applies_to": "全部非 normal 类（任务口径「非 normal 全部」；web/ext 缺陷"
                          "裁片都算；brocade 真实训练 0 张=无操作）",
            "repeat_by_class": rep_by,
            "real_eff_by_class": n_eff_by_class,
            "normal_kept": "normal 保持批12 原量（real_repeat=3）",
        },
        "imbalance": {
            "method": args.imbalance,
            "formula": "w_c = 1/log(1.02 + n_eff_c)，n_eff_c = 合成(若混入) + "
                       "真实×该类有效重复（normal×3 / 缺陷×real_repeat×oversample）",
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
            "defect_gradient_share_pct": defect_share if synth_root else None,
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
            or args.workers <= 0 or args.real_repeat <= 0 or args.defect_oversample <= 0:
        print("[错误] --epochs/--batch/--lr/--size/--workers/--real-repeat/"
              "--defect-oversample 须 >0")
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
