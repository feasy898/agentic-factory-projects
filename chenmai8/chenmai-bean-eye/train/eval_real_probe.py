# -*- coding: utf-8 -*-
"""真实照片探针（eval_real_probe；批5 分类腿决胜指标）。

对一批按堆分组的实拍照片跑「分割 → ONNX 裁片分类 → 按堆聚合」，产出
分类腿在真实域的及格口径。与 ``scripts/eval_real_v0.py``（一次性首测）
同分割/分类逻辑（证件屏蔽 + HSV 阴影排除 + 灰世界白平衡，已调通不改），
本脚本将其参数化并落 JSON：``--photos-dir``（照片目录）、``--onnx``
（分类模型）、``--out``（结果 JSON 路径）。

真值口径（按文件名首字分堆）：大/中/小 = 正常豆（按尺寸分档）；
坏 = 缺陷豆。评估三件：
  1) 正常堆（大中小）预测为 normal 的比例（决胜第一优先，越高越好）；
  2) 坏豆堆预测为非 normal（某缺陷类）的比例 + 缺陷类别分布（第二优先）；
  3) 三档尺寸排序 大>中>小（等效直径中位数，像素口径，同机拍摄可比）。

已知限制：光影/阴影会造成分割噪声；elephant/immature 是已知易误报类。
依赖仅 cv2 + numpy + onnxruntime（CPU 推理即可，无需 GPU）。

--dry-run：纯离线——校验照片目录与 ONNX 存在性、按堆计数匹配照片、
打印计划；不导入 cv2/onnxruntime、不做推理。结构性错误 exit 2。

输出 JSON（--out，UTF-8 ensure_ascii=False）：按堆与按照片的类别分布、
normal%/缺陷%、直径中位、summary 决胜三件；并记录 ONNX sha256 便于
追溯评测用的是哪个权重件。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np  # 核心钉版依赖（非 NN 栈），dry-run 亦可承受

import _common
from _common import EXIT_FAILED, EXIT_OK, EXIT_USAGE, PlanReporter, save_json, sha256_file

# 类别表（severity_order 位次序，与 ONNX 输出 logits 序一致）
CLASSES = ["normal", "broken", "faded", "brocade", "immature", "peaberry", "shell",
           "elephant", "insect", "dried", "sour", "mold", "black"]
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
SIZE = 224
NORMAL_PILES = ("大", "中", "小")   # 真值 = 正常豆
BAD_PILE = "坏"                     # 真值 = 缺陷豆
PILE_RE = re.compile(r"([大中小坏])")


def card_mask(img):
    """证件区域掩码（v2）：证件冷色调（B>R）在暖光纸面上显著；膨胀留边后整体排除。"""
    import cv2
    b, g, r = img[:, :, 0].astype(np.int16), img[:, :, 1].astype(np.int16), img[:, :, 2].astype(np.int16)
    diff = b - r
    m = (diff > 4).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((51, 51), np.uint8))
    m = cv2.dilate(m, np.ones((31, 31), np.uint8))
    return m


def gray_world(img):
    """灰世界白平衡（v2）：对齐合成数据的中性光源，消除室内暖色偏。"""
    res = img.astype(np.float32)
    means = res.reshape(-1, 3).mean(axis=0)
    gray = means.mean()
    gains = gray / np.maximum(means, 1e-3)
    return np.clip(res * gains[None, None, :], 0, 255).astype(np.uint8)


def seg_beans(img):
    """白底豆粒分割（v3）：屏蔽证件；HSV 饱和度逻辑（有彩度=豆，极暗=黑豆，
    低饱和灰斑=阴影出局）。与 scripts/eval_real_v0.py 逐参数一致（已调通）。"""
    import cv2
    work = gray_world(img)
    cmask = card_mask(work)
    cmask_inv = cv2.bitwise_not(cmask)
    hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)
    S = hsv[:, :, 1].astype(np.float32)
    V = hsv[:, :, 2].astype(np.float32)
    fg = (((S > 50) & (V > 55)) | (V < 42)).astype(np.uint8) * 255
    fg = cv2.bitwise_and(fg, cmask_inv)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    n, labcc, stats, cent = cv2.connectedComponentsWithStats(fg)
    area_img = img.shape[0] * img.shape[1]
    beans = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not (3e-5 * area_img < area < 4e-3 * area_img):
            continue
        mask = (labcc[y:y + h, x:x + w] == i).astype(np.uint8)
        # 实心度/圆度过滤（排除阴影软斑与纸面污渍）
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            continue
        c = max(cnts, key=cv2.contourArea)
        solidity = area / max(cv2.contourArea(cv2.convexHull(c)), 1)
        (cx, cy), (rw, rh), ang = cv2.minAreaRect(c)
        aspect = max(rw, rh) / max(min(rw, rh), 1)
        eq_d = 2 * np.sqrt(area / np.pi)
        if solidity < 0.80 or aspect > 2.6:
            continue
        beans.append({"cx": cent[i][0], "cy": cent[i][1], "eq_d": eq_d,
                      "x": x, "y": y, "w": w, "h": h, "mask": mask})
    return beans


def classify_crop(sess, inp_name, img, b):
    """单粒分类：掩码外置白底裁片 → 224² → ImageNet 归一化 → ONNX argmax。"""
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
    out = sess.run(None, {inp_name: t})[0][0]
    idx = int(np.argmax(out))
    return CLASSES[idx], float(out[idx])


def imread_unicode(path: Path):
    """非 ASCII 路径安全读图（cv2.imread 在部分平台不吃 unicode 路径）。"""
    import cv2
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)


def collect_photos(photos_dir: Path) -> dict[str, list[Path]]:
    """按堆分组枚举照片：文件名首字 ∈ {大,中,小,坏}；未匹配的记录并跳过。"""
    piles: dict[str, list[Path]] = {k: [] for k in ("大", "中", "小", "坏")}
    unmatched: list[str] = []
    for p in sorted(photos_dir.iterdir()):
        if p.suffix.lower() != ".jpg" or not p.is_file():
            continue
        m = PILE_RE.match(p.name)
        if m:
            piles[m.group(1)].append(p)
        else:
            unmatched.append(p.name)
    return piles, unmatched


def dry_run(args: argparse.Namespace, rep: PlanReporter) -> int:
    """纯离线：目录/ONNX 存在性 + 按堆照片计数 + 推理计划（exit 0/2）。"""
    rep.header("eval_real_probe.py", "真实照片探针（批5 分类腿决胜指标）")
    rep.section("输入")
    photos_dir = _common.resolve_path(args.photos_dir)
    rep.check_dir(photos_dir, "照片目录 --photos-dir")
    onnx_path = _common.resolve_path(args.onnx)
    if onnx_path.is_file():
        rep.ok(f"ONNX: {onnx_path}（{onnx_path.stat().st_size} bytes）")
    else:
        rep.missing(f"ONNX: {onnx_path}")
    if photos_dir.is_dir():
        piles, unmatched = collect_photos(photos_dir)
        for k, files in piles.items():
            role = "正常堆" if k in NORMAL_PILES else "缺陷堆"
            (rep.ok if files else rep.missing)(f"{k}堆（{role}）: {len(files)} 张")
        if unmatched:
            rep.missing(f"文件名首字未匹配分堆（跳过）: {','.join(unmatched[:5])}"
                        + ("…" if len(unmatched) > 5 else ""))
        total = sum(len(v) for v in piles.values())
        rep.plan(f"共 {total} 张照片参与探针")
    rep.section("推理计划")
    rep.plan("分割（证件屏蔽+HSV 阴影排除+灰世界白平衡，同 eval_real_v0 已调通版）"
             " → 逐粒 ONNX CPU 分类 → 按堆聚合")
    rep.plan(f"决胜三件：大中小堆 normal 判对率；坏堆缺陷检出率（非 normal%）+ "
             f"缺陷类别分布；尺寸排序 大>中>小")
    if args.out:
        rep.plan(f"结果 JSON → {_common.resolve_path(args.out)}")
    else:
        rep.plan("--out 未给：只打印，不落 JSON")
    return rep.finish()


def run(args: argparse.Namespace) -> int:
    """真实模式：逐照片分割+分类 → 按堆聚合 → summary →（可选）落 JSON。"""
    import cv2
    import onnxruntime

    photos_dir = _common.resolve_path(args.photos_dir)
    onnx_path = _common.resolve_path(args.onnx)
    if not photos_dir.is_dir():
        print(f"[错误] 照片目录不存在: {photos_dir}")
        return EXIT_USAGE
    if not onnx_path.is_file():
        print(f"[错误] ONNX 不存在: {onnx_path}")
        return EXIT_USAGE
    piles, unmatched = collect_photos(photos_dir)
    total_photos = sum(len(v) for v in piles.values())
    if total_photos == 0:
        print("[错误] 照片目录中没有文件名首字可匹配 大/中/小/坏 的 .jpg")
        return EXIT_USAGE
    if unmatched:
        print(f"[警告] {len(unmatched)} 张未匹配分堆，跳过（如 {unmatched[0]}）", flush=True)

    so = onnxruntime.SessionOptions()
    sess = onnxruntime.InferenceSession(str(onnx_path), so,
                                        providers=["CPUExecutionProvider"])
    inp_name = sess.get_inputs()[0].name
    print(f"[模型] {onnx_path.name}（input={inp_name}，"
          f"ort {onnxruntime.__version__} / cv2 {cv2.__version__}）", flush=True)

    piles_stat: dict[str, dict] = {}
    photos_log: list[dict] = []
    for k in ("大", "中", "小", "坏"):
        cls_total: Counter = Counter()
        eq_ds: list[float] = []
        for p in piles[k]:
            img = imread_unicode(p)
            if img is None:
                print(f"[警告] 读图失败，跳过: {p.name}", flush=True)
                continue
            img = gray_world(img)
            beans = seg_beans(img)
            per_photo: Counter = Counter()
            for b in beans:
                cls, _conf = classify_crop(sess, inp_name, img, b)
                cls_total[cls] += 1
                per_photo[cls] += 1
                eq_ds.append(b["eq_d"])
            photos_log.append({"file": p.name, "pile": k, "beans": len(beans),
                               "class_counts": dict(per_photo)})
            print(f"  {p.name:<14s} 分割 {len(beans):3d} 粒 → "
                  f"{dict(per_photo)}", flush=True)
        tot = sum(cls_total.values())
        normal = int(cls_total.get("normal", 0))
        med = float(np.median(eq_ds)) if eq_ds else None
        st = {"photos": len(piles[k]), "beans": tot,
              "normal": normal,
              "normal_pct": round(100.0 * normal / tot, 2) if tot else None,
              "defect_pct": round(100.0 * (tot - normal) / tot, 2) if tot else None,
              "class_counts": {c: int(cls_total.get(c, 0)) for c in CLASSES},
              "defect_class_counts": {c: int(cls_total.get(c, 0)) for c in CLASSES
                                      if c != "normal" and cls_total.get(c, 0) > 0},
              "eq_d_median_px": round(med, 1) if med is not None else None,
              }
        if k == BAD_PILE:
            st["top_defects"] = sorted(st["defect_class_counts"].items(),
                                       key=lambda t: t[1], reverse=True)[:4]
        piles_stat[k] = st
        print(f"[{k}堆] 照片 {st['photos']} 张，豆 {tot} 粒，normal={st['normal_pct']}%，"
              f"缺陷={st['defect_pct']}%"
              + (f"，直径中位={st['eq_d_median_px']:.0f}px" if med is not None else "")
              + (f"，主要缺陷预测={st.get('top_defects')}" if k == BAD_PILE else ""),
              flush=True)

    # summary：决胜三件
    n_beans = sum(piles_stat[k]["beans"] for k in NORMAL_PILES)
    n_normal = sum(piles_stat[k]["normal"] for k in NORMAL_PILES)
    bad = piles_stat[BAD_PILE]
    meds = {k: piles_stat[k]["eq_d_median_px"] for k in NORMAL_PILES}
    order_ok = (meds["大"] is not None and meds["中"] is not None and meds["小"] is not None
                and meds["大"] > meds["中"] > meds["小"])
    summary = {
        "normal_piles_beans": n_beans,
        "normal_piles_normal": n_normal,
        "normal_correct_rate": round(n_normal / n_beans, 6) if n_beans else None,
        "normal_correct_rate_by_pile": {k: piles_stat[k]["normal_pct"] for k in NORMAL_PILES},
        "bad_pile_beans": bad["beans"],
        "bad_pile_defect": bad["beans"] - bad["normal"],
        "defect_detection_rate": (round((bad["beans"] - bad["normal"]) / bad["beans"], 6)
                                  if bad["beans"] else None),
        "bad_pile_defect_distribution_pct": (
            {c: round(100.0 * n / (bad["beans"] - bad["normal"]), 2)
             for c, n in sorted(bad["defect_class_counts"].items(),
                                key=lambda t: t[1], reverse=True)}
            if bad["beans"] - bad["normal"] > 0 else {}),
        "eq_d_median_px": meds,
        "size_order_ok": bool(order_ok),
    }
    print("[summary] 正常堆 normal 判对率="
          f"{summary['normal_correct_rate']}（大/中/小 = "
          f"{summary['normal_correct_rate_by_pile']}）；坏堆缺陷检出率="
          f"{summary['defect_detection_rate']}；缺陷分布="
          f"{summary['bad_pile_defect_distribution_pct']}；尺寸排序大>中>小={order_ok}",
          flush=True)

    if args.out:
        out_path = _common.resolve_path(args.out)
        payload = {
            "prepared_by": "train/eval_real_probe.py（scripts/eval_real_v0.py 参数化版，分割口径一致）",
            "photos_dir": str(photos_dir),
            "n_photos": total_photos,
            "n_photos_by_pile": {k: len(piles[k]) for k in piles_stat},
            "photos_unmatched": unmatched,
            "onnx": {"path": str(onnx_path), "bytes": onnx_path.stat().st_size,
                     "sha256": sha256_file(onnx_path)},
            "runtime": {"onnxruntime": onnxruntime.__version__, "cv2": cv2.__version__,
                        "providers": ["CPUExecutionProvider"]},
            "piles": piles_stat,
            "summary": summary,
            "photos": photos_log,
        }
        save_json(out_path, payload)
        print(f"[out] {out_path}", flush=True)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="真实照片探针：分割→ONNX 分类→按堆聚合（--dry-run 纯离线打印计划）",
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="只校验照片目录/ONNX 并打印计划（离线，exit 0）")
    ap.add_argument("--photos-dir", required=True,
                    help="实拍照片目录（.jpg，文件名首字 大/中/小/坏 定真值堆）")
    ap.add_argument("--onnx", required=True,
                    help="分类 ONNX（opset17 静态 1×3×224²，input=logits 同批4 导出口径）")
    ap.add_argument("--out", default=None,
                    help="结果 JSON 路径（缺省只打印不落盘）")
    return ap


def main() -> int:
    _common.setup_console()
    args = build_parser().parse_args()
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
