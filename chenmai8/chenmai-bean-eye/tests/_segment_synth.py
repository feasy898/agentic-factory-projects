"""简化程序化豆盘合成器（tests 基建 · W4b）。

**背景**：M12 合成数据引擎（``beaneye.synth``）尚未提交，W4b 分割 eval 依赖
「合成图 + 逐豆真值」。本模块按任务说明提供**简化程序化夹具**：椭圆豆模型 +
四角定位码 + 逐豆像素级真值标签，直接在托盘正射网格坐标系（configs/tray.yaml：
grid_px=2048 覆盖 tray_mm=300）上渲染，可充当「标定 warp 后的托盘图」
（恒等单应的特例）；也可经 ``tests/_calib_views.render_view`` 走真实
透视→标定→warp 全路径（见 tests/test_segment.py）。

独立于被测模块构造真值（被测代码看不到本文件的绘制公式）；
M12 就绪后本夹具由真合成器替换，指标口径不变。

真值约定：``label[i,j]==k``（k≥1）表示像素属于第 k 粒豆（``beans[k-1]``）；
两豆重叠像素归后画的一粒（分割 eval 只在稀疏盘上用逐豆 IoU 达标线，
粘连盘只考核「分离召回」，重叠归属误差不影响该口径）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

# 与 configs/tray.yaml 一致的正射网格几何（不 import 配置模块，保持测试基建独立）
GRID_PX = 2048
TRAY_MM = 300.0
PPM = GRID_PX / TRAY_MM  # px per mm ≈ 6.827
MARKER_MM = 60.0
MARKER_CENTERS_MM = {0: (30.0, 30.0), 1: (270.0, 30.0), 2: (270.0, 270.0), 3: (30.0, 270.0)}
BG_LEVEL = 205  # 浅色亚克力盘面灰度（近 configs/tray.yaml warp.border_value 235 的同族浅色）


@dataclass(frozen=True)
class Bean:
    """一枚椭圆豆：盘面 mm 中心、长短半轴、旋转角。"""

    cx: float
    cy: float
    semi_a: float  # 长半轴 mm（罗布斯塔生豆整粒 ~2.7-4.1）
    semi_b: float  # 短半轴 mm
    angle_deg: float


@dataclass(frozen=True)
class Scene:
    """一份合成豆盘：RGB 画布（=恒等 warp 的托盘正射图）+ 逐豆真值标签。"""

    canvas: np.ndarray  # uint8 RGB (GRID_PX, GRID_PX, 3)
    label: np.ndarray  # int32 (GRID_PX, GRID_PX)，0=背景，k=第 k 粒豆
    beans: tuple[Bean, ...]


def ellipse_mask(bean: Bean, grid_px: int = GRID_PX) -> np.ndarray:
    """单豆像素级真值掩码（画布坐标系；越界部分自然裁剪）。"""
    ppm = grid_px / TRAY_MM
    r = bean.semi_a * ppm + 2
    x0 = max(0, int(bean.cx * ppm - r))
    x1 = min(grid_px, int(bean.cx * ppm + r) + 2)
    y0 = max(0, int(bean.cy * ppm - r))
    y1 = min(grid_px, int(bean.cy * ppm + r) + 2)
    m = np.zeros((grid_px, grid_px), dtype=bool)
    if x1 <= x0 or y1 <= y0:
        return m
    xs = (np.arange(x0, x1) + 0.5) / ppm
    ys = (np.arange(y0, y1) + 0.5) / ppm
    dx = xs[None, :] - bean.cx
    dy = ys[:, None] - bean.cy
    ca = math.cos(math.radians(bean.angle_deg))
    sa = math.sin(math.radians(bean.angle_deg))
    xr = ca * dx + sa * dy
    yr = -sa * dx + ca * dy
    m[y0:y1, x0:x1] = (xr * xr) / (bean.semi_a**2) + (yr * yr) / (bean.semi_b**2) <= 1.0
    return m


def _paste_marker(canvas_bgr: np.ndarray, mid: int, cx_mm: float, cy_mm: float) -> None:
    """按 scripts/make_aruco.py 同款布局贴一枚定位码（含白色静区）。"""
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    side = int(round(MARKER_MM * PPM))
    marker = cv2.aruco.generateImageMarker(dictionary, mid, side)
    pad = max(2, side // 8)
    tile = np.full((side + 2 * pad, side + 2 * pad), 255, dtype=np.uint8)
    tile[pad : pad + side, pad : pad + side] = marker
    tile_bgr = cv2.cvtColor(tile, cv2.COLOR_GRAY2BGR)
    th, tw = tile_bgr.shape[:2]
    cx = int(round(cx_mm * PPM))
    cy = int(round(cy_mm * PPM))
    x0, y0 = cx - tw // 2, cy - th // 2
    h, w = canvas_bgr.shape[:2]
    sx0, sy0 = max(0, -x0), max(0, -y0)
    dx0, dy0 = max(0, x0), max(0, y0)
    dx1, dy1 = min(w, x0 + tw), min(h, y0 + th)
    if dx1 > dx0 and dy1 > dy0:
        canvas_bgr[dy0:dy1, dx0:dx1] = tile_bgr[sy0 : sy0 + dy1 - dy0, sx0 : sx0 + dx1 - dx0]


def make_scene(
    beans,
    *,
    markers: bool = True,
    seed: int = 7,
    bean_gray=(70, 150),
    bean_noise_sigma: float = 5.0,
    bg_noise_sigma: float = 3.0,
) -> Scene:
    """渲染一份豆盘：浅色背景 + 四角定位码 + 逐粒椭圆豆（灰度有随机深浅）。"""
    rng = np.random.default_rng(seed)
    bgr = np.full((GRID_PX, GRID_PX, 3), BG_LEVEL, dtype=np.uint8)
    if bg_noise_sigma > 0:
        noise = rng.normal(0.0, bg_noise_sigma, (GRID_PX, GRID_PX, 1))
        bgr = np.clip(bgr.astype(np.float64) + noise, 0, 255).astype(np.uint8)
    label = np.zeros((GRID_PX, GRID_PX), dtype=np.int32)
    if markers:
        for mid, (cx_mm, cy_mm) in MARKER_CENTERS_MM.items():
            _paste_marker(bgr, mid, cx_mm, cy_mm)
    beans = tuple(beans)
    for i, bean in enumerate(beans, start=1):
        level = int(rng.integers(bean_gray[0], bean_gray[1] + 1))
        m = ellipse_mask(bean)
        if not m.any():
            continue
        region = bgr[:, :, 0].astype(np.float64)
        vals = np.full(int(m.sum()), float(level))
        if bean_noise_sigma > 0:
            vals += rng.normal(0.0, bean_noise_sigma, vals.shape)
        region[m] = np.clip(vals, 0, 255)
        bgr[:, :, 0] = region.astype(np.uint8)
        bgr[:, :, 1] = bgr[:, :, 0]
        bgr[:, :, 2] = bgr[:, :, 0]
        label[m] = i
    canvas = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)  # 管线把 RGB 交给 predict
    return Scene(canvas=canvas, label=label, beans=beans)


# ---------------------------------------------------------------------------
# 布局生成
# ---------------------------------------------------------------------------


def random_bean(rng: np.random.Generator, cx: float, cy: float) -> Bean:
    """随机椭圆豆：长轴 2.7-4.1mm、短/长比 0.68-1.0、任意朝向。"""
    a = float(rng.uniform(2.7, 4.1))
    b = a * float(rng.uniform(0.68, 1.0))
    return Bean(cx=cx, cy=cy, semi_a=a, semi_b=b, angle_deg=float(rng.uniform(0.0, 180.0)))


def place_sparse(
    n: int, *, region=(75.0, 225.0), min_gap: float = 9.5, seed: int = 11
) -> list[Bean]:
    """拒绝采样铺 n 粒互不接触的豆（中心距 ≥ min_gap mm，避开四角码区）。"""
    rng = np.random.default_rng(seed)
    lo, hi = region
    beans: list[Bean] = []
    tries = 0
    while len(beans) < n:
        tries += 1
        if tries > 20000:
            raise RuntimeError(f"稀疏布局放不下 {n} 粒（region={region}, min_gap={min_gap}）")
        cx = float(rng.uniform(lo, hi))
        cy = float(rng.uniform(lo, hi))
        cand = random_bean(rng, cx, cy)
        if all(math.hypot(cx - b.cx, cy - b.cy) >= min_gap for b in beans):
            beans.append(cand)
    return beans


def touching_pair(
    rng: np.random.Generator, cx: float, cy: float, *, overlap: float
) -> tuple[Bean, Bean]:
    """在 (cx,cy) 附近造一对粘连豆：中心距 = (r1+r2)·(1−overlap)，随机朝向。

    ``overlap`` 是占两粒半径和的比例（0.22-0.38 → 实打实接触、可分水岭切开）。
    """
    b1 = random_bean(rng, cx, cy)
    ang = float(rng.uniform(0.0, 360.0))
    b2 = random_bean(rng, cx, cy)
    gap = (b1.semi_a + b2.semi_a) * (1.0 - overlap)
    b2 = Bean(
        cx=cx + gap * math.cos(math.radians(ang)),
        cy=cy + gap * math.sin(math.radians(ang)),
        semi_a=b2.semi_a,
        semi_b=b2.semi_b,
        angle_deg=b2.angle_deg,
    )
    return b1, b2


def place_touching_scene(
    n_pairs: int, n_singles: int, *, region=(70.0, 230.0), cluster_gap: float = 17.0, seed: int = 23
) -> tuple[list[Bean], list[tuple[int, int]]]:
    """铺「粘连对 + 单粒」混合盘，返回 (beans, pairs)（pairs 元素=两粒在 beans 的下标）。"""
    rng = np.random.default_rng(seed)
    lo, hi = region
    centers: list[tuple[float, float, float]] = []  # (x, y, 占用半径)
    beans: list[Bean] = []
    pairs: list[tuple[int, int]] = []

    def _far_enough(x: float, y: float, r: float) -> bool:
        return all(math.hypot(x - ox, y - oy) >= r + orr for ox, oy, orr in centers)

    tries = 0
    while len(pairs) < n_pairs:
        tries += 1
        if tries > 20000:
            raise RuntimeError("粘连场景布局失败：区域太小/间隙太大")
        cx = float(rng.uniform(lo + 6, hi - 6))
        cy = float(rng.uniform(lo + 6, hi - 6))
        ov = float(rng.uniform(0.22, 0.38))
        b1, b2 = touching_pair(rng, cx, cy, overlap=ov)
        r = max(b1.semi_a, b2.semi_a) + max(
            math.hypot(b2.cx - b1.cx, b2.cy - b1.cy), 0.0
        )
        if not _far_enough(cx, cy, r):
            continue
        i1 = len(beans)
        beans.extend([b1, b2])
        pairs.append((i1, i1 + 1))
        centers.append((cx, cy, r))
    tries = 0
    while len(beans) < 2 * n_pairs + n_singles:
        tries += 1
        if tries > 20000:
            raise RuntimeError("粘连场景单粒布局失败")
        cx = float(rng.uniform(lo, hi))
        cy = float(rng.uniform(lo, hi))
        cand = random_bean(rng, cx, cy)
        if not _far_enough(cx, cy, cand.semi_a + 1.5):
            continue
        beans.append(cand)
        centers.append((cx, cy, cand.semi_a))
    return beans, pairs
