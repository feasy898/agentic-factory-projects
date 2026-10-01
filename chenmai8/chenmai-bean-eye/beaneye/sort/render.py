"""分拣线 · 可视化：把抓取计划 / 机械臂轨迹画到标注帧上，出前后对比图。

全部绘制用 OpenCV（ASCII 文本——cv2.putText 不支持中文，标注用英文标签）：

- :func:`draw_plan`：逐抓取步画「拾取点编号 + 指向分级盒的箭头 + 分级盒框」，
  被跳过的目标画叉并注 skip 标签；
- :func:`draw_trajectory`：臂轨迹（桌面 mm 采样序列）反投影到图上画折线；
- :func:`erase_targets`：把已抓走的豆从帧上抹除（以质心为圆心、面积等效
  半径填周边背景色）——「after」帧的可视化语义（渲染示意，非像素真值）；
- :func:`before_after_panel`：前后两帧拼接出对比图（BEFORE / AFTER 标签）。

缺陷配色按 taxonomy key 固定调色板（未登记类别灰色兜底）。
"""

from __future__ import annotations

from typing import Sequence

import cv2
import numpy as np

from beaneye.sort.frame import FrameToTable
from beaneye.sort.planner import SortPlan

__all__ = [
    "DEFECT_COLORS_BGR",
    "area_mm_to_r",
    "draw_plan",
    "draw_trajectory",
    "erase_targets",
    "before_after_panel",
]

# 缺陷类别 → BGR 配色（taxonomy key 固定；未登记类别灰色兜底）
DEFECT_COLORS_BGR: dict[str, tuple[int, int, int]] = {
    "black": (0, 0, 140),
    "mold": (160, 60, 160),
    "sour": (0, 90, 220),
    "dried": (60, 60, 200),
    "insect": (0, 160, 120),
    "broken": (200, 120, 0),
    "faded": (180, 180, 180),
    "brocade": (120, 200, 200),
    "immature": (0, 200, 200),
    "shell": (150, 150, 60),
    "elephant": (80, 160, 80),
    "peaberry": (255, 120, 120),
    "default": (128, 128, 128),
}

_THIN = 1
_MED = 2


def _color_for(name: str) -> tuple[int, int, int]:
    return DEFECT_COLORS_BGR.get(name, DEFECT_COLORS_BGR["default"])


def area_mm_to_r(area_mm2: float) -> float:
    """面积（mm²）→ 等效圆半径（mm）。"""
    return float(np.sqrt(max(float(area_mm2), 1e-6) / np.pi))


def draw_plan(
    img_bgr: np.ndarray,
    mapper: FrameToTable,
    plan: SortPlan,
    *,
    draw_skipped: bool = True,
    draw_bins: bool = True,
) -> np.ndarray:
    """把抓取计划画到帧上（返回新图，不改入参）。"""
    out = img_bgr.copy()
    if draw_bins:
        seen: set[str] = set()
        for s in plan.steps:
            if s.bin_name in seen:
                continue
            seen.add(s.bin_name)
            bx, by = (float(v) for v in mapper.table_to_px([[s.bin_x_mm, s.bin_y_mm]])[0])
            _draw_bin(out, int(round(bx)), int(round(by)), s.bin_name)
    for s in plan.steps:
        color = _color_for(s.target.defect)
        px = [float(v) for v in mapper.table_to_px([s.pick_x_mm, s.pick_y_mm])]
        bp = [float(v) for v in mapper.table_to_px([s.bin_x_mm, s.bin_y_mm])]
        p0 = (int(round(px[0])), int(round(px[1])))
        p1 = (int(round(bp[0])), int(round(bp[1])))
        cv2.arrowedLine(out, p0, p1, color, _THIN, tipLength=0.06)
        cv2.circle(out, p0, 6, color, -1, lineType=cv2.LINE_AA)
        cv2.putText(out, f"#{s.order} {s.target.defect}", (p0[0] + 8, p0[1] - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, _THIN, cv2.LINE_AA)
    if draw_skipped:
        gray = DEFECT_COLORS_BGR["default"]
        for sk in plan.skipped:
            t = sk.target
            xy = [float(v) for v in mapper.table_to_px([t.x_mm, t.y_mm])]
            p = (int(round(xy[0])), int(round(xy[1])))
            cv2.drawMarker(out, p, gray, cv2.MARKER_CROSS, 12, _MED)
            cv2.putText(out, f"{t.target_id} skip", (p[0] + 8, p[1] + 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, gray, _THIN, cv2.LINE_AA)
    return out


def draw_trajectory(
    img_bgr: np.ndarray,
    mapper: FrameToTable,
    trajectory: Sequence[dict],
) -> np.ndarray:
    """把臂轨迹采样（[{x_mm, y_mm, z_mm, ...}, ...]）反投影到图上画折线。"""
    out = img_bgr.copy()
    if not trajectory:
        return out
    pts_px = mapper.table_to_px([[p["x_mm"], p["y_mm"]] for p in trajectory])
    color = (255, 120, 40)
    for i in range(1, len(pts_px)):
        a = (int(round(float(pts_px[i - 1][0]))), int(round(float(pts_px[i - 1][1]))))
        b = (int(round(float(pts_px[i][0]))), int(round(float(pts_px[i][1]))))
        cv2.line(out, a, b, color, _THIN)
        cv2.circle(out, b, 3, color, -1)
    start = (int(round(float(pts_px[0][0]))), int(round(float(pts_px[0][1]))))
    cv2.drawMarker(out, start, color, cv2.MARKER_STAR, 14, _MED)
    return out


def erase_targets(
    img_bgr: np.ndarray,
    mapper: FrameToTable,
    targets_xy_mm: Sequence[Sequence[float]],
    areas_mm2: Sequence[float],
) -> np.ndarray:
    """把已抓走的豆抹掉（质心圆域填周边背景中值色）——after 帧可视化语义。

    ``targets_xy_mm``：桌面 mm 质心列表；``areas_mm2``：对应面积（等效半径）。
    """
    out = img_bgr.copy()
    h, w = out.shape[:2]
    origin_px = np.asarray(mapper.table_to_px([[0.0, 0.0], [1.0, 0.0]]), dtype=np.float64)
    px_per_mm_x = float(np.linalg.norm(origin_px[1] - origin_px[0]))  # 局部 x 向比例
    for xy, area in zip(targets_xy_mm, areas_mm2):
        p = np.asarray(mapper.table_to_px([xy[0], xy[1]]), dtype=np.float64)
        cx, cy = int(round(float(p[0]))), int(round(float(p[1])))
        r_px = max(2, int(round(area_mm_to_r(area) * px_per_mm_x)))
        x0, x1 = max(0, cx - r_px - 4), min(w, cx + r_px + 4)
        y0, y1 = max(0, cy - r_px - 4), min(h, cy + r_px + 4)
        patch = out[y0:y1, x0:x1]
        if patch.size == 0:
            continue
        bg = np.median(patch.reshape(-1, 3), axis=0)
        color = (int(bg[0]), int(bg[1]), int(bg[2]))
        cv2.circle(out, (cx, cy), r_px, color, -1, lineType=cv2.LINE_AA)
    return out


def before_after_panel(before_bgr: np.ndarray, after_bgr: np.ndarray) -> np.ndarray:
    """前后两帧等高拼接 + BEFORE/AFTER 标签（对比图）。"""
    h = min(before_bgr.shape[0], after_bgr.shape[0])

    def _fit(img: np.ndarray) -> np.ndarray:
        if img.shape[0] != h:
            scale = h / img.shape[0]
            img = cv2.resize(img, (max(1, int(round(img.shape[1] * scale))), h))
        return img

    b, a = _fit(before_bgr), _fit(after_bgr)
    sep = np.full((h, 6, 3), 255, dtype=np.uint8)
    panel = np.hstack([b, sep, a])
    cv2.putText(panel, "BEFORE", (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (30, 30, 30), _MED, cv2.LINE_AA)
    cv2.putText(panel, "AFTER", (b.shape[1] + 18, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (30, 30, 30), _MED, cv2.LINE_AA)
    return panel


# ---- 内部 --------------------------------------------------------------------


def _draw_bin(img: np.ndarray, cx: int, cy: int, name: str) -> None:
    """分级盒示意框（固定像素框，位置由桌面 mm 反投影给出）。"""
    half = 18
    p0, p1 = (cx - half, cy - half), (cx + half, cy + half)
    color = _color_for(name)
    cv2.rectangle(img, p0, p1, color, _MED)
    cv2.putText(img, name, (p0[0], p0[1] - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, _THIN, cv2.LINE_AA)
