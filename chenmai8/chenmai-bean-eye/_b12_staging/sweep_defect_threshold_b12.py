# -*- coding: utf-8 -*-
"""缺陷决策阈值扫描（批10 收官·批9 ONNX 工作点选定）。

【批12 适配说明（2026-10-04）】本文件由 train/sweep_defect_threshold.py（批10 产物）
最小改而来：仅将 EXPECT_* 参考常量由批9 探针（probe_finetune_hn9.json，264/343 与
21/55）改钉批12 探针（/data/coffee-bean/batch12-results/probe_b12.json，279/343 与
12/55），用于批12 ONNX 的 τ 扫描端到端校验；其余逻辑逐字节同源。批12 探针坏堆
类别计数：broken=1, black=11, sour=0 → BBS=12/55=0.218182。

背景：批9 分类头 ONNX 的 argmax 口径探针（train/eval_real_probe.py，结果
``/data/coffee-bean/batch9-results/probe_finetune_hn9.json``）为
normal堆 normal 判对率 = 76.97%（264/343）、坏堆 {broken,black,sour} 检出
= 38.2%（21/55）。应用上漏检（坏豆进好堆）代价高于误报，故引入决策阈值 τ：

    预测 = defect  当  max(各缺陷类 softmax 概率) ≥ τ；否则 normal。
    判为 defect 时，缺陷类别 = 12 个缺陷类中的 argmax（top-defect）。

本脚本对 τ ∈ --tau-list 逐一计算：
  1) normal堆（大/中/小 按豆合并）判为 normal 的比例（normal 判对率）；
  2) 坏堆（坏）判为 defect 且 top-defect ∈ {broken,black,sour} 的比例（检出口径
     与批9 探针 summary 的 {broken,black,sour} 口径一致）；
  另附参考列：坏堆判为任意缺陷类的比例（decision=defect，不限类别）。

口径一致性（逐位）：分割与预处理**直接 import** train/eval_real_probe.py 的
``gray_world / seg_beans / classify_crop / imread_unicode / collect_photos``
与常量 CLASSES/MEAN/STD/SIZE/NORMAL_PILES/BAD_PILE，照片主流程与探针 run()
一致（读图 → gray_world 一次 → seg_beans → 逐粒分类）。本脚本另取全量
logits 算 softmax（预处理逐行复制 classify_crop），并对**每一粒**断言
``CLASSES[argmax(logits)] == classify_crop(...)``——任何一粒不一致即整体
FAIL，以此证明 τ 口径与探针 argmax 口径共享同一条前向链路。argmax 参考
行（τ 曲线之外）应逐位复现探针基线，作为端到端校验（EXPECT_* 常量批12
适配版引自 probe_b12.json）。

依赖仅 numpy + cv2 + onnxruntime（CPU 推理，与探针同 venv）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common
from _common import EXIT_FAILED, EXIT_OK, EXIT_USAGE, resolve_path, save_json, sha256_file
# 分割/预处理/聚合口径全部复用探针脚本本体（同目录，禁止复制漂移）
from eval_real_probe import (BAD_PILE, CLASSES, MEAN, NORMAL_PILES, SIZE, STD,
                             classify_crop, collect_photos, gray_world,
                             imread_unicode, seg_beans)

# 批12 探针已发布口径（/data/coffee-bean/batch12-results/probe_b12.json）：
# summary.normal_correct_rate = 0.813411（279/343）；
# 坏堆 {broken:1, black:11, sour:0} → 12/55 = 0.218182（21.8%）。
EXPECT_NORMAL_RATE = 279 / 343
EXPECT_BBS_RATE = 12 / 55
BBS = ("broken", "black", "sour")   # 检出口径子集（与批9 探针 38.2% 同口径）
DEFECT_IDX = list(range(1, len(CLASSES)))   # CLASSES[0]=normal，其余 12 为缺陷类


def full_logits(sess, inp_name, img, b):
    """单粒前向：预处理逐行复制 eval_real_probe.classify_crop，返回全量 logits。

    与 classify_crop 唯一差别：返回 out 向量而非 argmax（供 softmax/τ 判决）。
    逐位一致性由 run() 中对每粒的 argmax 断言保证。
    """
    import cv2
    x, y, w, h = b["x"], b["y"], b["w"], b["h"]
    pad = int(0.15 * max(w, h))
    x0, y0 = max(x - pad, 0), max(y - pad, 0)
    x1, y1 = min(x + w + pad, img.shape[1]), min(y + h + pad, img.shape[0])
    crop = img[y0:y1, x0:x1]
    # 掩码外置白底（与合成裁片一致的白背景先验）
    m = cv2.resize(b["mask"], (crop.shape[1], crop.shape[0]), interpolation=cv2.INTER_NEAREST)
    crop = np.where(m[:, :, None] == 1, crop, 255).astype(np.uint8)
    crop = cv2.resize(crop, (SIZE, SIZE), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    rgb = (rgb - MEAN) / STD
    t = rgb.transpose(2, 0, 1)[None].astype(np.float32)
    return sess.run(None, {inp_name: t})[0][0]


def softmax(z: np.ndarray) -> np.ndarray:
    e = np.exp(z - z.max())
    return e / e.sum()


def collect_beans(onnx_path: Path, photos_dir: Path) -> tuple[list[dict], dict, list[str]]:
    """一遍前向收齐每粒的 argmax（探针权威）+ softmax 概率。"""
    import cv2
    import onnxruntime

    so = onnxruntime.SessionOptions()
    sess = onnxruntime.InferenceSession(str(onnx_path), so,
                                        providers=["CPUExecutionProvider"])
    inp_name = sess.get_inputs()[0].name
    print(f"[模型] {onnx_path.name}（input={inp_name}，"
          f"ort {onnxruntime.__version__} / cv2 {cv2.__version__}）", flush=True)

    piles, unmatched = collect_photos(photos_dir)
    beans: list[dict] = []
    mismatch = 0
    for k in ("大", "中", "小", "坏"):
        for p in piles[k]:
            img = imread_unicode(p)
            if img is None:
                print(f"[警告] 读图失败，跳过: {p.name}", flush=True)
                continue
            img = gray_world(img)          # 与探针 run() 一致：seg 前先白平衡一次
            seg_beans_ = seg_beans(img)
            per_photo = 0
            for b in seg_beans_:
                cls_probe, _conf = classify_crop(sess, inp_name, img, b)   # 探针权威 argmax
                out = full_logits(sess, inp_name, img, b)                  # 全量 logits
                idx = int(np.argmax(out))
                if CLASSES[idx] != cls_probe:
                    mismatch += 1
                    print(f"[FAIL] argmax 断言不一致 {p.name}: "
                          f"{CLASSES[idx]} != {cls_probe}", flush=True)
                    continue
                probs = softmax(out)
                dsub = int(np.argmax(out[DEFECT_IDX])) + 1   # top-defect 类（logits 口径）
                beans.append({"pile": k, "file": p.name,
                              "argmax_cls": cls_probe,
                              "top_defect_cls": CLASSES[dsub],
                              "p_normal": round(float(probs[0]), 6),
                              "p_max_defect": round(float(probs[DEFECT_IDX].max()), 6)})
                per_photo += 1
            print(f"  [{k}] {p.name:<14s} 分割 {per_photo:3d} 粒", flush=True)
    if mismatch:
        print(f"[FAIL] {mismatch} 粒 argmax 断言不一致——τ 口径与探针前向不等价，拒绝出数",
              flush=True)
        sys.exit(EXIT_FAILED)
    meta = {k: {"photos": len(piles[k])} for k in ("大", "中", "小", "坏")}
    return beans, meta, unmatched


def metrics_at(beans: list[dict], tau: float | None) -> dict:
    """τ 处两指标。tau=None 表示 argmax 参考行（不做 τ 判决）。"""
    nrm = [b for b in beans if b["pile"] in NORMAL_PILES]
    bad = [b for b in beans if b["pile"] == BAD_PILE]
    if tau is None:   # argmax：normal 判对 = argmax==normal；检出 = argmax ∈ BBS
        n_ok = sum(1 for b in nrm if b["argmax_cls"] == "normal")
        bbs = sum(1 for b in bad if b["argmax_cls"] in BBS)
        d_any = sum(1 for b in bad if b["argmax_cls"] != "normal")
    else:             # τ 判决：defect ⟺ p_max_defect ≥ τ；类别 = top_defect_cls
        n_ok = sum(1 for b in nrm if b["p_max_defect"] < tau)
        bbs = sum(1 for b in bad if b["p_max_defect"] >= tau and b["top_defect_cls"] in BBS)
        d_any = sum(1 for b in bad if b["p_max_defect"] >= tau)
    return {"tau": tau,
            "normal_pile_n": len(nrm), "normal_pile_normal": n_ok,
            "normal_rate": round(n_ok / len(nrm), 6) if nrm else None,
            "bad_pile_n": len(bad),
            "bad_pile_bbs": bbs,
            "bbs_rate": round(bbs / len(bad), 6) if bad else None,
            "bad_pile_defect_any": d_any,
            "defect_any_rate": round(d_any / len(bad), 6) if bad else None}


def recommend(curve: list[dict]) -> dict:
    """推荐工作点：坏堆检出 ≥55% 且 normal ≥70%；多解取检出最高（漏检代价高），
    同检出取 normal 更高、再取 τ 更小。无解取相对缺口和最小者（如实说明）。"""
    G_BBS, G_NRM = 0.55, 0.70
    feas = [r for r in curve if r["bbs_rate"] >= G_BBS and r["normal_rate"] >= G_NRM]
    if feas:
        best = sorted(feas, key=lambda r: (-r["bbs_rate"], -r["normal_rate"], r["tau"]))[0]
        return {"feasible": True, **best,
                "rule": f"满足检出≥{G_BBS}且normal≥{G_NRM}；取检出最高者"}
    def gap(r):
        return (max(0.0, (G_BBS - r["bbs_rate"]) / G_BBS)
                + max(0.0, (G_NRM - r["normal_rate"]) / G_NRM))
    best = sorted(curve, key=lambda r: (gap(r), -r["bbs_rate"], r["tau"]))[0]
    return {"feasible": False, **best,
            "rule": "τ 网格上无同时满足检出≥55%与normal≥70%的点；"
                    "取相对缺口（检出缺口/55% + normal缺口/70%）最小者"}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="批12 ONNX 缺陷决策阈值 τ 扫描（复用 eval_real_probe 分割/预处理口径；批12 适配版）",
    )
    ap.add_argument("--onnx", required=True, help="分类 ONNX（批12 crop_cls.onnx）")
    ap.add_argument("--photos-dir", required=True,
                    help="实拍照片目录（.jpg，文件名首字 大/中/小/坏 定真值堆）")
    ap.add_argument("--tau-list", default="0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9",
                    help="逗号分隔 τ 网格（缺省 0,0.1,…,0.9）")
    ap.add_argument("--out", default=None, help="结果 JSON 路径（缺省只打印）")
    return ap


def main() -> int:
    _common.setup_console()
    args = build_parser().parse_args()
    onnx_path = resolve_path(args.onnx)
    photos_dir = resolve_path(args.photos_dir)
    if not onnx_path.is_file():
        print(f"[错误] ONNX 不存在: {onnx_path}")
        return EXIT_USAGE
    if not photos_dir.is_dir():
        print(f"[错误] 照片目录不存在: {photos_dir}")
        return EXIT_USAGE
    taus = [float(t) for t in args.tau_list.split(",") if t.strip() != ""]

    beans, pile_meta, unmatched = collect_beans(onnx_path, photos_dir)
    print(f"[beans] 共 {len(beans)} 粒（argmax 断言全部通过）", flush=True)

    # argmax 参考行应逐位复现批12 探针口径，作为端到端校验
    ref = metrics_at(beans, None)
    ref_ok = (abs(ref["normal_rate"] - EXPECT_NORMAL_RATE) < 5e-6
              and abs(ref["bbs_rate"] - EXPECT_BBS_RATE) < 5e-6)
    print(f"[argmax 参考] normal={ref['normal_rate']}（期望 {EXPECT_NORMAL_RATE:.6f}）；"
          f"{'+'.join(BBS)} 检出={ref['bbs_rate']}（期望 {EXPECT_BBS_RATE:.6f}）→ "
          f"{'VERIFIED' if ref_ok else 'MISMATCH'}", flush=True)
    if not ref_ok:
        print("[FAIL] argmax 参考行与批12 探针不一致——口径漂移，拒绝出数", flush=True)
        sys.exit(EXIT_FAILED)

    curve = [metrics_at(beans, t) for t in taus]
    print("\n[τ 曲线]  τ     normal堆normal%   坏堆BBS检出%   坏堆任意缺陷%")
    for r in curve:
        print(f"  {r['tau']:<5.2f}  {100*r['normal_rate']:>8.2f}      "
              f"{100*r['bbs_rate']:>8.2f}      {100*r['defect_any_rate']:>8.2f}", flush=True)

    rec = recommend(curve)
    print(f"\n[推荐] τ={rec['tau']}（feasible={rec['feasible']}）normal={rec['normal_rate']} "
          f"BBS检出={rec['bbs_rate']} — {rec['rule']}", flush=True)

    if args.out:
        payload = {
            "prepared_by": "train/sweep_defect_threshold_b12.py（批10 脚本批12 适配版：EXPECT_* "
                           "由批9 探针改钉批12 probe_b12.json=279/343 与 12/55，其余逐字节同源；"
                           "分割/预处理 import train/eval_real_probe.py，逐粒 argmax 断言）",
            "tau_rule": "预测=defect 当 max(12缺陷类 softmax 概率)≥τ，否则 normal；"
                        "判 defect 时类别=缺陷类 argmax；检出口径=top_defect ∈ {broken,black,sour}"
                        "（与批9 探针 38.2% 同口径）",
            "onnx": {"path": str(onnx_path), "bytes": onnx_path.stat().st_size,
                     "sha256": sha256_file(onnx_path)},
            "photos_dir": str(photos_dir),
            "n_photos_by_pile": pile_meta,
            "photos_unmatched": unmatched,
            "n_beans": len(beans),
            "argmax_reference": {**ref, "expect_normal_rate": EXPECT_NORMAL_RATE,
                                 "expect_bbs_rate": EXPECT_BBS_RATE,
                                 "match_probe_b12": ref_ok},
            "gates": {"bad_bbs_rate_min": 0.55, "normal_rate_min": 0.70},
            "curve": curve,
            "recommendation": rec,
            "beans": beans,
        }
        out_path = resolve_path(args.out)
        save_json(out_path, payload)
        print(f"[out] {out_path}", flush=True)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
