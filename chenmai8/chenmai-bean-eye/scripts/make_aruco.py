#!/usr/bin/env python3
"""生成可打印的 ArUco 标定板图（M3 真硬件标定用，W0b 交付件之一）。

默认布局读 configs/tray.yaml（码位几何单一真源，W13 起）：DICT_4X4_50，
四角码 id=0..3，码边长/盘面边长/四码中心均取配置值（默认 60mm 码、
300x300mm 盘面，码中心 (30,30)/(270,30)/(270,270)/(30,270) mm）。
--board-mm/--marker-mm 显式覆盖时退回角位公式（m/2 内缩）。
角点顺序：id0=左上, id1=右上, id2=右下, id3=左下（拍摄摆放任意，检测按 id 配对）。

产出：
  <out>.png        高分辨率打印图（白色静区 + 盘面外框参考线）
  <out>.json       布局真值（码中心 mm 坐标 / 码边长 / 盘面尺寸），供标定与自检比对

用法：
    ./.venv/Scripts/python.exe scripts/make_aruco.py                     # 默认 out/aruco_board（布局=tray.yaml）
    ./.venv/Scripts/python.exe scripts/make_aruco.py --out out/board_a4 \
        --board-mm 280 --marker-mm 50 --px-per-mm 8                      # 适配 A4 打印
    ./.venv/Scripts/python.exe scripts/make_aruco.py --single 2 --marker-mm 60
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from beaneye.acquisition.base import imwrite_bgr  # noqa: E402
from beaneye.calibration.config import load_tray_config  # noqa: E402


def _formula_centers(board_mm: float, marker_mm: float) -> dict[int, tuple[float, float]]:
    """角位公式布局（显式覆盖 board/marker 时的退回路径）。"""
    m = marker_mm / 2.0
    return {0: (m, m), 1: (board_mm - m, m), 2: (board_mm - m, board_mm - m), 3: (m, board_mm - m)}


def build_board(
    board_mm: float,
    marker_mm: float,
    px_per_mm: int,
    margin_mm: float = 10.0,
    centers_mm: dict[int, tuple[float, float]] | None = None,
) -> tuple["object", list[dict]]:  # (np.ndarray BGR, layout list)
    import cv2
    import numpy as np

    centers = centers_mm if centers_mm is not None else _formula_centers(board_mm, marker_mm)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    size_px = int(round((board_mm + 2 * margin_mm) * px_per_mm))
    canvas = np.full((size_px, size_px), 255, dtype=np.uint8)

    # 盘面外框参考线（帮助裁剪/摆放，检测不受影响）
    off = int(margin_mm * px_per_mm)
    cv2.rectangle(canvas, (off, off), (size_px - off - 1, size_px - off - 1), 180, max(1, px_per_mm // 4))

    side_px = int(round(marker_mm * px_per_mm))
    pad_px = max(2, side_px // 8)  # 静区：码外白边（≈码边 1/8）
    layout = []
    for mid in sorted(centers):
        cx_mm, cy_mm = centers[mid]
        marker = cv2.aruco.generateImageMarker(dictionary, mid, side_px)
        tile = np.full((side_px + 2 * pad_px, side_px + 2 * pad_px), 255, dtype=np.uint8)
        tile[pad_px : pad_px + side_px, pad_px : pad_px + side_px] = marker
        cx_px = int(round((cx_mm + margin_mm) * px_per_mm))
        cy_px = int(round((cy_mm + margin_mm) * px_per_mm))
        x0, y0 = cx_px - tile.shape[1] // 2, cy_px - tile.shape[0] // 2
        canvas[y0 : y0 + tile.shape[0], x0 : x0 + tile.shape[1]] = tile
        layout.append(
            {
                "marker_id": mid,
                "center_mm": [cx_mm, cy_mm],
                "top_left_mm": [cx_mm - marker_mm / 2, cy_mm - marker_mm / 2],
                "size_mm": marker_mm,
            }
        )
    return canvas, layout


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 ArUco 标定板打印图（默认布局=configs/tray.yaml）")
    parser.add_argument("--out", default="out/aruco_board", help="输出路径前缀（不含扩展名）")
    parser.add_argument("--board-mm", type=float, default=None, help="盘面边长 mm（缺省读 configs/tray.yaml）")
    parser.add_argument("--marker-mm", type=float, default=None, help="码边长 mm（缺省读 configs/tray.yaml）")
    parser.add_argument("--px-per-mm", type=int, default=6, help="打印分辨率 px/mm（默认 6≈150dpi，A3 建议 8）")
    parser.add_argument("--single", type=int, default=None, metavar="ID", help="只生成单个码（0-49）")
    args = parser.parse_args()

    import cv2

    # 码位几何单一真源：缺省值一律取 configs/tray.yaml；显式覆盖 board/marker
    # 时退回角位公式布局（异形打印板）。
    cfg = load_tray_config()
    board_mm = args.board_mm if args.board_mm is not None else cfg.tray_mm
    marker_mm = args.marker_mm if args.marker_mm is not None else cfg.marker_mm
    explicit_override = args.board_mm is not None or args.marker_mm is not None
    centers_mm = None if explicit_override else dict(cfg.centers_mm)

    out_base = Path(args.out)
    if not out_base.is_absolute():
        out_base = ROOT / out_base
    out_base.parent.mkdir(parents=True, exist_ok=True)

    if args.single is not None:
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        side_px = int(round(args.marker_mm * args.px_per_mm))
        marker = cv2.aruco.generateImageMarker(dictionary, args.single, side_px)
        pad = max(2, side_px // 8)
        tile = cv2.copyMakeBorder(marker, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
        png_path = out_base.with_name(f"{out_base.name}_id{args.single}.png")
        imwrite_bgr(png_path, tile)
        print(f"[MAKE-ARUCO] 单码 id={args.single} -> {png_path} ({tile.shape[1]}x{tile.shape[0]}px)")
        return 0

    if marker_mm * 2 >= board_mm:
        print("[MAKE-ARUCO] 错误: 码边长过大，四角会重叠", file=sys.stderr)
        return 2

    canvas, layout = build_board(board_mm, marker_mm, args.px_per_mm, centers_mm=centers_mm)
    png_path = out_base.with_suffix(".png")
    json_path = out_base.with_suffix(".json")
    imwrite_bgr(png_path, canvas)
    json_path.write_text(
        json.dumps(
            {
                "dictionary": "DICT_4X4_50",
                "board_mm": board_mm,
                "marker_mm": marker_mm,
                "px_per_mm": args.px_per_mm,
                "layout_source": "explicit" if explicit_override else "configs/tray.yaml",
                "corner_order": "id0=LT, id1=RT, id2=RB, id3=LB",
                "markers": layout,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        f"[MAKE-ARUCO] 板图 {board_mm}mm/码 {marker_mm}mm @ {args.px_per_mm}px/mm "
        f"-> {png_path} ({canvas.shape[1]}x{canvas.shape[0]}px) + {json_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
