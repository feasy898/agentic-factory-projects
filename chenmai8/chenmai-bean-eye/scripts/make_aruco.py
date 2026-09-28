#!/usr/bin/env python3
"""生成可打印的 ArUco 标定板图（M3 真硬件标定用，W0b 交付件之一）。

默认布局与 M3/标定契约一致：DICT_4X4_50，四角码 id=0..3，码边长 60mm，
300x300mm 盘面，码中心位于 (30,30)/(270,30)/(270,270)/(30,270) mm。
角点顺序：id0=左上, id1=右上, id2=右下, id3=左下（拍摄摆放任意，检测按 id 配对）。

产出：
  <out>.png        高分辨率打印图（白色静区 + 盘面外框参考线）
  <out>.json       布局真值（码中心 mm 坐标 / 码边长 / 盘面尺寸），供标定与自检比对

用法：
    ./.venv/Scripts/python.exe scripts/make_aruco.py                     # 默认 out/aruco_board
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


def build_board(
    board_mm: float,
    marker_mm: float,
    px_per_mm: int,
    margin_mm: float = 10.0,
) -> tuple["object", list[dict]]:  # (np.ndarray BGR, layout list)
    import cv2
    import numpy as np

    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    size_px = int(round((board_mm + 2 * margin_mm) * px_per_mm))
    canvas = np.full((size_px, size_px), 255, dtype=np.uint8)

    # 盘面外框参考线（帮助裁剪/摆放，检测不受影响）
    off = int(margin_mm * px_per_mm)
    cv2.rectangle(canvas, (off, off), (size_px - off - 1, size_px - off - 1), 180, max(1, px_per_mm // 4))

    centers_mm = {
        0: (marker_mm / 2, marker_mm / 2),                       # 左上
        1: (board_mm - marker_mm / 2, marker_mm / 2),            # 右上
        2: (board_mm - marker_mm / 2, board_mm - marker_mm / 2), # 右下
        3: (marker_mm / 2, board_mm - marker_mm / 2),            # 左下
    }
    side_px = int(round(marker_mm * px_per_mm))
    pad_px = max(2, side_px // 8)  # 静区：码外白边（≈码边 1/8）
    layout = []
    for mid, (cx_mm, cy_mm) in centers_mm.items():
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


def _imwrite_unicode(path: Path, img: "object") -> None:
    """cv2.imwrite 在非 ASCII 路径（本仓含中文目录）下会静默失败，改走编码字节流。"""
    import cv2
    import numpy as np

    ok, buf = cv2.imencode(path.suffix or ".png", img)
    if not ok:
        raise RuntimeError(f"图像编码失败: {path}")
    path.write_bytes(bytes(np.asarray(buf).tobytes()))


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 ArUco 标定板打印图")
    parser.add_argument("--out", default="out/aruco_board", help="输出路径前缀（不含扩展名）")
    parser.add_argument("--board-mm", type=float, default=300.0, help="盘面边长 mm（默认 300）")
    parser.add_argument("--marker-mm", type=float, default=60.0, help="码边长 mm（默认 60）")
    parser.add_argument("--px-per-mm", type=int, default=6, help="打印分辨率 px/mm（默认 6≈150dpi，A3 建议 8）")
    parser.add_argument("--single", type=int, default=None, metavar="ID", help="只生成单个码（0-49）")
    args = parser.parse_args()

    import cv2

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
        _imwrite_unicode(png_path, tile)
        print(f"[MAKE-ARUCO] 单码 id={args.single} -> {png_path} ({tile.shape[1]}x{tile.shape[0]}px)")
        return 0

    if args.marker_mm * 2 >= args.board_mm:
        print("[MAKE-ARUCO] 错误: 码边长过大，四角会重叠", file=sys.stderr)
        return 2

    canvas, layout = build_board(args.board_mm, args.marker_mm, args.px_per_mm)
    png_path = out_base.with_suffix(".png")
    json_path = out_base.with_suffix(".json")
    _imwrite_unicode(png_path, canvas)
    json_path.write_text(
        json.dumps(
            {
                "dictionary": "DICT_4X4_50",
                "board_mm": args.board_mm,
                "marker_mm": args.marker_mm,
                "px_per_mm": args.px_per_mm,
                "corner_order": "id0=LT, id1=RT, id2=RB, id3=LB",
                "markers": layout,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        f"[MAKE-ARUCO] 板图 {args.board_mm}mm/码 {args.marker_mm}mm @ {args.px_per_mm}px/mm "
        f"-> {png_path} ({canvas.shape[1]}x{canvas.shape[0]}px) + {json_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
