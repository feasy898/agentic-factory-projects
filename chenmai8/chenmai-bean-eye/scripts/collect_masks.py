#!/usr/bin/env python3
"""HN-Robusta v0.1 采集辅助：单粒照批量出掩码 + 掩码/手勾多边形 IoU。

采集操作卡（docs/采集操作卡-v0.1.md）§6 自检的执行工具。只依赖仓库钉版
numpy/opencv（requirements.txt），零新增第三方依赖；图像 IO 走字节缓冲
（np.fromfile/cv2.imdecode），中文/非 ASCII 工程路径安全（W0b 实测坑，
与 beaneye.acquisition.base 同口径）。

三个子命令：

  extract  批量掩码提取（协议 §4.1 自动路线最小实现：灰度 Otsu（极性自检）
           → 形态学开闭 → 连通域；**只用于不带四角码的单粒照**（正面与
           反面 _b 都出掩码，自动跳过 *_pile 散铺照）——带码整盘照
           走 /demo 预标注管线（ClassicSeg 含码区抑制），本脚本会把码误当豆）。
           每张图在 <mask_dir> 写 8-bit {0,255} 二值掩码（与图同名 .png），
           逐图打印豆数；整批聚合打印面积中位数，并标记偏离中位数 ±40%
           的图（操作卡 §6.2 面积复核；单粒照一图一粒，「堆」= 本次命令
           处理的同一类目录）。

  iou      手工抽检（协议 §4.4）：手勾多边形（labelme 导出 JSON 的
           shapes[0].points，或 {"points": [[x,y], ...]} 简式）栅格化后与
           掩码 PNG 算 IoU，对照阈值（默认 0.95）打印 PASS/FAIL。

  poly2mask 掩码人工修正落盘（协议 §4.2）：手勾多边形 JSON 按原图尺寸
           栅格化为 8-bit {0,255} 掩码并写出——抽检 FAIL 的图在 labelme
           勾正确豆缘后，用本命令替换 masks/ 下不合格掩码。

用法（仓库根）::

    .venv/Scripts/python.exe scripts/collect_masks.py extract images/black masks/black
    .venv/Scripts/python.exe scripts/collect_masks.py extract images/black masks/black --min-area-px 500
    .venv/Scripts/python.exe scripts/collect_masks.py iou 手勾.json masks/black/black_20261003_001.png
    .venv/Scripts/python.exe scripts/collect_masks.py poly2mask 修正.json images/black/black_20261003_001.png masks/black/black_20261003_001.png

退出码：0 正常（extract 有 ±40% 标记时仍为 0，标记只打印不失败）；
2 参数/文件错误；3 extract 无有效前景（整批掩码全空）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import cv2
import numpy as np

__all__ = ["extract_mask", "polygon_iou", "rasterize_polygon", "load_polygon_points", "main"]

DEFAULT_MIN_AREA_PX = 500  # 面积小于该值的连通域按噪点丢弃（≥20px/mm 下 5mm 豆面积远超此值）
DEFAULT_IOU_THR = 0.95  # 协议 §4.4 抽检门槛
DEVIACTION_THR = 0.40  # 操作卡 §6.2 面积复核阈（±40%）


# ---------------------------------------------------------------------------
# 核心：单图掩码提取（协议 §4.1 自动路线最小版）
# ---------------------------------------------------------------------------


def _imread_any(path: Path) -> np.ndarray:
    """中文路径安全读图（BGR）。"""
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        raise ValueError(f"读图失败（空文件或路径不存在）: {path}")
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"解码失败（非图片或损坏）: {path}")
    return img


def _imwrite_gray(path: Path, mask: np.ndarray) -> None:
    """中文路径安全写 8-bit 灰度 PNG。"""
    ok, buf = cv2.imencode(".png", mask)
    if not ok:
        raise ValueError(f"PNG 编码失败: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    buf.tofile(str(path))


def extract_mask(
    img_bgr: np.ndarray,
    min_area_px: int = DEFAULT_MIN_AREA_PX,
    force_invert: bool = False,
) -> tuple[np.ndarray, int, list[int]]:
    """单张单粒照 → (二值掩码 uint8 {0,255}, 豆数, 各连通域面积列表)。

    极性自检与 beaneye/segment/classic.py 同口径：边框带前景占比 >50% 判
    极性反转（防深底浅豆误配）；``force_invert`` 手动反转（自检判反时用，
    命令行 --invert）。开闭运算清噪/补小洞；连通域按面积下限滤噪。
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    _, fg = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    # 极性：force_invert 手动反转并跳过自检；否则按边框带自检（各边 2%，最少 3px，
    # 前景占比 >50% → 反转，防深底浅豆误配）
    if force_invert:
        fg = 255 - fg
    else:
        h, w = fg.shape
        bx = max(3, w // 50)
        by = max(3, h // 50)
        border = np.concatenate(
            [fg[:by, :].ravel(), fg[-by:, :].ravel(), fg[:, :bx].ravel(), fg[:, -bx:].ravel()]
        )
        if float((border > 0).mean()) > 0.5:
            fg = 255 - fg
    # 开（去噪点）+ 闭（补豆内小洞）
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, kernel)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, kernel)
    # 连通域滤噪
    n, labels, stats, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
    keep = np.zeros_like(fg)
    areas: list[int] = []
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < min_area_px:
            continue
        keep[labels == i] = 255
        areas.append(area)
    return keep, len(areas), areas


# ---------------------------------------------------------------------------
# 核心：手勾多边形 vs 掩码 IoU（协议 §4.4）
# ---------------------------------------------------------------------------


def load_polygon_points(json_path: Path) -> list[list[float]]:
    """labelme JSON（shapes[0].points）或 {"points": [[x,y],...]} 简式 → 顶点表。"""
    obj = json.loads(json_path.read_text(encoding="utf-8"))
    if isinstance(obj, dict) and obj.get("shapes"):
        return obj["shapes"][0]["points"]
    if isinstance(obj, dict) and obj.get("points"):
        return obj["points"]
    raise ValueError(f"JSON 里既无 shapes[0].points 也无 points: {json_path}")


def polygon_iou(mask: np.ndarray, points: list[list[float]]) -> float:
    """手勾多边形栅格化 vs 掩码 PNG 的 IoU（两图尺寸必须一致）。"""
    if mask.ndim == 3:
        mask = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)
    h, w = mask.shape[:2]
    hand = rasterize_polygon(points, h, w)
    m = mask > 0
    hd = hand > 0
    inter = int(np.logical_and(m, hd).sum())
    union = int(np.logical_or(m, hd).sum())
    if union == 0:
        raise ValueError("掩码与手勾多边形均为空，IoU 无定义")
    return inter / union


def rasterize_polygon(points: list[list[float]], h: int, w: int) -> np.ndarray:
    """多边形顶点 → 8-bit {0,255} 掩码（协议入库格式；poly2mask/共同实现）。"""
    poly = np.asarray(points, dtype=np.float32)
    if poly.ndim != 2 or poly.shape[0] < 3 or poly.shape[1] != 2:
        raise ValueError(f"多边形顶点非法（需 ≥3 个 [x,y]）: shape={poly.shape}")
    hand = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(hand, [np.round(poly).astype(np.int32)], 255)
    return hand


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_extract(args: argparse.Namespace) -> int:
    img_dir = Path(args.image_dir)
    mask_dir = Path(args.mask_dir)
    if not img_dir.is_dir():
        print(f"[COLLECT-MASKS] 错误: 图片目录不存在 {img_dir}", file=sys.stderr)
        return 2
    exts = {".png", ".jpg", ".jpeg"}
    paths = sorted(p for p in img_dir.iterdir() if p.suffix.lower() in exts and not p.name.startswith("."))
    # 只排除散铺照（协议 §3.3：散铺照不入掩码流程）；正面/反面（_b）单粒照都出掩码
    paths = [p for p in paths if not p.stem.endswith("_pile")]
    if not paths:
        print(f"[COLLECT-MASKS] 错误: {img_dir} 下无单粒照（已自动跳过 *_pile 散铺照）", file=sys.stderr)
        return 2
    all_areas: list[int] = []
    per_image: list[tuple[str, int, list[int], Path]] = []
    for p in paths:
        img = _imread_any(p)
        mask, count, areas = extract_mask(
            img, min_area_px=args.min_area_px, force_invert=args.invert
        )
        out = mask_dir / f"{p.stem}.png"
        _imwrite_gray(out, mask)
        per_image.append((p.name, count, areas, out))
        all_areas.extend(areas)
        print(f"  {p.name}: 掩码 -> {out.name}，连通域 {count} 个")
    median = float(np.median(all_areas)) if all_areas else 0.0
    print(
        f"[EXTRACT] 共 {len(per_image)} 图 / {len(all_areas)} 个连通域；"
        f"面积中位数 {median:.0f}px²（min={min(all_areas) if all_areas else 0} "
        f"max={max(all_areas) if all_areas else 0}）"
    )
    flags = 0
    if len(all_areas) >= 3:  # 样本太少不做 ±40% 判定（中位数不稳）
        for name, count, areas, _out in per_image:
            for j, a in enumerate(areas):
                dev = abs(a - median) / median if median > 0 else 0.0
                if dev > DEVIACTION_THR:
                    flags += 1
                    print(
                        f"  [FLAG] {name}#{j + 1} 面积 {a}px² 偏离堆中位数 {median:.0f}px² "
                        f"{dev * 100:.0f}%（>±40%，标记复核：粘连/破碎/阴影？）"
                    )
    elif all_areas:
        print("[EXTRACT] 样本 <3 个，跳过 ±40% 面积复核（中位数不稳，人工逐张看）")
    print(f"[EXTRACT] 自检①数量：逐图核对上方连通域数 == 实拍豆数；自检②面积：标记 {flags} 个")
    if not all_areas:
        return 3
    return 0


def _cmd_iou(args: argparse.Namespace) -> int:
    mask_path = Path(args.mask_png)
    json_path = Path(args.polygon_json)
    for p in (mask_path, json_path):
        if not p.is_file():
            print(f"[COLLECT-MASKS] 错误: 文件不存在 {p}", file=sys.stderr)
            return 2
    mask = _imread_any(mask_path)
    points = load_polygon_points(json_path)
    iou = polygon_iou(mask, points)
    verdict = "PASS" if iou >= args.thr else "FAIL"
    print(f"[IOU] {mask_path.name} vs {json_path.name}: IoU={iou:.4f}（门槛 {args.thr}）-> {verdict}")
    return 0


def _cmd_poly2mask(args: argparse.Namespace) -> int:
    json_path = Path(args.polygon_json)
    img_path = Path(args.image)
    out_path = Path(args.out_png)
    for p in (json_path, img_path):
        if not p.is_file():
            print(f"[COLLECT-MASKS] 错误: 文件不存在 {p}", file=sys.stderr)
            return 2
    img = _imread_any(img_path)
    h, w = img.shape[:2]
    points = load_polygon_points(json_path)
    mask = rasterize_polygon(points, h, w)
    _imwrite_gray(out_path, mask)
    fg = int((mask > 0).sum())
    print(f"[POLY2MASK] {json_path.name} -> {out_path}（{w}x{h}，前景 {fg}px²）")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HN-Robusta 采集辅助：批量掩码提取 + 手勾 IoU 抽检")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ext = sub.add_parser("extract", help="批量单粒照 -> 8-bit 二值掩码（+数量/面积自检输出）")
    p_ext.add_argument("image_dir", help="单粒照目录，如 images/black（自动跳过 *_pile/*_b）")
    p_ext.add_argument("mask_dir", help="掩码输出目录，如 masks/black")
    p_ext.add_argument("--min-area-px", type=int, default=DEFAULT_MIN_AREA_PX, help="连通域面积下限（噪点），默认 500")
    p_ext.add_argument("--invert", action="store_true", help="极性手动反转（极性自检判反了时用）")
    p_ext.set_defaults(func=_cmd_extract)

    p_iou = sub.add_parser("iou", help="手勾多边形（labelme/简式 JSON）vs 掩码 PNG 的 IoU")
    p_iou.add_argument("polygon_json", help="labelme 导出 JSON 或 {\"points\": [[x,y],...]}")
    p_iou.add_argument("mask_png", help="掩码 PNG（extract 产物或人工修正后的入库掩码）")
    p_iou.add_argument("--thr", type=float, default=DEFAULT_IOU_THR, help="PASS 门槛，默认 0.95（协议 §4.4）")
    p_iou.set_defaults(func=_cmd_iou)

    p_p2m = sub.add_parser("poly2mask", help="手勾多边形 JSON → 8-bit {0,255} 掩码落盘（人工修正用）")
    p_p2m.add_argument("polygon_json", help="labelme 导出 JSON 或 {\"points\": [[x,y],...]}")
    p_p2m.add_argument("image", help="原图（提供输出掩码的尺寸）")
    p_p2m.add_argument("out_png", help="输出掩码路径（覆盖不合格掩码即完成修正）")
    p_p2m.set_defaults(func=_cmd_poly2mask)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
