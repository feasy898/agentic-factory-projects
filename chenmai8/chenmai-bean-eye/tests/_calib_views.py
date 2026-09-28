"""M3 标定测试的合成视图生成器（测试基建，独立于被测模块构造真值）。

用针孔相机模型把「盘面平面图（mm 已知）」投影成整盘照片：
  盘面 mm --(R 旋转 + 平移 t)--> 相机坐标 --(K 内参)--> 输出 px
平面场景下该映射恰为单应 H_mm_px = K·[r1 r2 t]，真值解析可得，
被测模块全程看不到 R/K（杜绝用生成器公式自证）。

另提供 ``build_board_custom``：按任意 id→中心布局铺 ArUco（scripts/make_aruco.py
固定四角公式布局，异形/置换布局用这里生成）。
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class ViewSpec:
    """一次合成拍摄的几何与光度参数。"""

    rx_deg: float = 0.0            # 绕 x 轴俯仰（透视前后景深）
    ry_deg: float = 0.0            # 绕 y 轴俯仰
    rz_deg: float = 0.0            # 盘面内旋转
    out_w: int = 1600
    out_h: int = 1200
    fill: float = 0.86             # 盘面投影占输出画幅的比例
    gain: float = 1.0              # 亮度增益（乘）
    bias: float = 0.0              # 亮度偏置（加）
    noise_sigma: float = 0.0       # 高斯噪点 σ
    seed: int = 7
    border: tuple[int, int, int] = (60, 60, 60)  # 盘外填充（深灰）


def rotation_matrix(rx_deg: float, ry_deg: float, rz_deg: float) -> np.ndarray:
    """R = Rz·Ry·Rx（盘面先俯仰后自转），3x3 float64。"""
    ax, ay, az = np.deg2rad([rx_deg, ry_deg, rz_deg])
    cx, sx = np.cos(ax), np.sin(ax)
    cy, sy = np.cos(ay), np.sin(ay)
    cz, sz = np.cos(az), np.sin(az)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], dtype=np.float64)
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=np.float64)
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], dtype=np.float64)
    return Rz @ Ry @ Rx


def apply_h(H: np.ndarray, pts: np.ndarray | list) -> np.ndarray:
    """单应逐点变换 (N,2)/(2,) → 同形状 float64。"""
    arr = np.asarray(pts, dtype=np.float64)
    single = arr.ndim == 1
    p = arr.reshape(-1, 1, 2).astype(np.float32)
    out = cv2.perspectiveTransform(p, np.asarray(H, dtype=np.float64).reshape(3, 3))
    out = out.reshape(-1, 2).astype(np.float64)
    return out[0] if single else out


def render_view(
    canvas_bgr: np.ndarray,
    tray_mm: float,
    margin_mm: float,
    px_per_mm: float,
    spec: ViewSpec,
) -> tuple[np.ndarray, np.ndarray]:
    """把盘面平面图渲染成一张合成照片，返回 (view, H_mm_px 真值)。

    canvas 坐标约定与 scripts/make_aruco.py 一致：px = (mm + margin_mm) · px_per_mm。
    单位：盘面先归一到边长 1、盘心置于原点，相机距离 d=5（保证任意 ±30° 姿态下
    全盘 Z>0，透视良态）；H_mm_px 已把归一化链路换算回 mm。
    """
    R = rotation_matrix(spec.rx_deg, spec.ry_deg, spec.rz_deg)
    d = 5.0
    M_pose = np.hstack([R[:, :2], np.array([[0.0], [0.0], [d]])])  # 作用于归一化盘面坐标
    # mm → (mm−盘心)/tray_mm：先移盘心到原点再缩放到单位边长
    M_norm = np.array(
        [[1.0 / tray_mm, 0.0, -0.5], [0.0, 1.0 / tray_mm, -0.5], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    M = M_pose @ M_norm  # 盘面 mm → 相机归一化平面（齐次 3x3）

    corners_mm = np.array(
        [[0, 0], [tray_mm, 0], [tray_mm, tray_mm], [0, tray_mm]], dtype=np.float64
    )
    P = M @ np.hstack([corners_mm, np.ones((4, 1))]).T  # 3x4 齐次
    n = (P[:2] / P[2]).T  # 归一化像坐标
    bw = n[:, 0].max() - n[:, 0].min()
    bh = n[:, 1].max() - n[:, 1].min()
    f = min(spec.out_w * spec.fill / bw, spec.out_h * spec.fill / bh)
    cx = spec.out_w / 2.0 - f * (n[:, 0].max() + n[:, 0].min()) / 2.0
    cy = spec.out_h / 2.0 - f * (n[:, 1].max() + n[:, 1].min()) / 2.0
    K = np.array([[f, 0, cx], [0, f, cy], [0, 0, 1]], dtype=np.float64)
    H_mm_px = K @ M  # 盘面 mm → 输出 px（真值）
    A_px_to_mm = np.array(
        [
            [1.0 / px_per_mm, 0.0, -margin_mm],
            [0.0, 1.0 / px_per_mm, -margin_mm],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    H_canvas = H_mm_px @ A_px_to_mm  # 素材板 px → 输出 px

    view = cv2.warpPerspective(
        canvas_bgr, H_canvas, (spec.out_w, spec.out_h), flags=cv2.INTER_LINEAR,
        borderValue=spec.border,
    )
    if spec.gain != 1.0 or spec.bias != 0.0 or spec.noise_sigma > 0:
        rng = np.random.default_rng(spec.seed)
        v = view.astype(np.float64) * spec.gain + spec.bias
        if spec.noise_sigma > 0:
            v += rng.normal(0.0, spec.noise_sigma, v.shape)
        view = np.clip(v, 0, 255).astype(np.uint8)
    return view, H_mm_px


def gt_scale_at(H_mm_px: np.ndarray, pt_mm: tuple[float, float], eps: float = 0.05) -> float:
    """真值映射 mm→px 在 pt_mm 处的局部尺度 sqrt(|det J|)（px/mm）。"""
    pt = np.asarray(pt_mm, dtype=np.float64)
    ex = (apply_h(H_mm_px, pt + [eps, 0]) - apply_h(H_mm_px, pt - [eps, 0])) / (2 * eps)
    ey = (apply_h(H_mm_px, pt + [0, eps]) - apply_h(H_mm_px, pt - [0, eps])) / (2 * eps)
    det = ex[0] * ey[1] - ey[0] * ex[1]
    return float(np.sqrt(abs(det)))


def build_board_custom(
    centers_mm: dict[int, tuple[float, float]],
    marker_mm: float,
    tray_mm: float,
    px_per_mm: float,
    margin_mm: float = 10.0,
    dictionary_name: str = "DICT_4X4_50",
) -> np.ndarray:
    """按任意 id→中心布局铺 ArUco 的盘面平面图（BGR）。布局逻辑同 scripts/make_aruco.py。"""
    dict_id = getattr(cv2.aruco, dictionary_name)
    dictionary = cv2.aruco.getPredefinedDictionary(dict_id)
    size_px = int(round((tray_mm + 2 * margin_mm) * px_per_mm))
    canvas = np.full((size_px, size_px), 255, dtype=np.uint8)
    off = int(margin_mm * px_per_mm)
    cv2.rectangle(canvas, (off, off), (size_px - off - 1, size_px - off - 1), 180, max(1, int(px_per_mm) // 4))
    side_px = int(round(marker_mm * px_per_mm))
    pad_px = max(2, side_px // 8)
    for mid, (cx_mm, cy_mm) in centers_mm.items():
        marker = cv2.aruco.generateImageMarker(dictionary, mid, side_px)
        tile = np.full((side_px + 2 * pad_px, side_px + 2 * pad_px), 255, dtype=np.uint8)
        tile[pad_px : pad_px + side_px, pad_px : pad_px + side_px] = marker
        cx = int(round((cx_mm + margin_mm) * px_per_mm))
        cy = int(round((cy_mm + margin_mm) * px_per_mm))
        x0, y0 = cx - tile.shape[1] // 2, cy - tile.shape[0] // 2
        canvas[y0 : y0 + tile.shape[0], x0 : x0 + tile.shape[1]] = tile
    return cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)


def detect_centers(img_bgr: np.ndarray, dictionary_name: str = "DICT_4X4_50") -> dict[int, tuple[float, float]]:
    """独立于被测模块的 ArUco 检测（测试复核用），返回 id → 码中心 px。"""
    dict_id = getattr(cv2.aruco, dictionary_name)
    detector = cv2.aruco.ArucoDetector(
        cv2.aruco.getPredefinedDictionary(dict_id), cv2.aruco.DetectorParameters()
    )
    gray = img_bgr if img_bgr.ndim == 2 else cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = detector.detectMarkers(gray)
    out: dict[int, tuple[float, float]] = {}
    if ids is None:
        return out
    for quad, mid in zip(corners, ids):
        c = quad[0].mean(axis=0)
        out[int(mid[0])] = (float(c[0]), float(c[1]))
    return out
