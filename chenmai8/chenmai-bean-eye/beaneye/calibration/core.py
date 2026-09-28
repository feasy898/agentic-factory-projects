"""M3 标定与坐标变换核心（plan/开发指令.md §4 M3）。

职责：
  1. 整盘图上检测 4 角 ArUco（字典/码边长/布局出自 ``configs/tray.yaml``）；
  2. 由「检测角点 px ↔ 布局 mm」对应求 **原图 px → 盘面 mm 的平面单应 H**——
     平面场景下单应即托盘相对相机的完整平面姿态表达（规格走 findHomography 路线，
     不需要相机内参）；
  3. 提供 :func:`warp_to_tray`（原图 → 盘面 2048² 正射网格）与 :func:`px_to_mm` /
     :func:`mm_to_px` 逐点变换。

与冻结契约（beaneye/schemas.py ``CalibResult``）的关系：契约对象同时携带两面
（top/bottom）单应，因此——

  - :func:`calibrate` 单面求解，返回富结果 :class:`SingleCalib`
    （H / px_per_mm / reproj_err_px / 检测细节）。这是 §4 M3 spec 的单图入口；
  - :func:`calibrate_pair` 两面各解一次，组装契约 ``CalibResult``
    （``px_per_mm`` 取两面均值；``reproj_err_px`` 取两面最大值，按最保守读数），
    由 M2 采集写入 ``TrayScan.calibration``。

求解策略（两级）：
  a) 四码 **中心**（4 角点均值）→ ``findHomography`` 精确解。中心配对只依赖
     marker id，与检测顺序、托盘摆放旋转完全无关（任意角度均正确）；
  b) 用 a) 的 H 把布局角点反投影到 px，与检测角点做循环移位匹配（4 选 1，
     对任意盘面内旋转稳健），得 16 对角点 → 最小二乘精化 H，同时得到有意义的
     ``reproj_err_px``。若精化在角点上的 RMS 反而变差则回退 a)，保证不劣化。

失败语义：检出角码 <4 或 id 不全 → :class:`CalibrationError`（v1 不做单码姿态
兜底，现场摆正重拍即可）。

``px_per_mm`` 语义：H 逆（mm→px）在盘面中心的局部尺度 sqrt(|det J|)，即盘面
中心处的像素密度；透视下它是逐点变化的，此值是全局快速换算用的中心估计。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import cv2
import numpy as np

from beaneye.schemas import CalibResult
from beaneye.calibration.config import TrayConfig, TrayConfigError, load_tray_config

__all__ = [
    "CalibrationError",
    "SingleCalib",
    "calibrate",
    "calibrate_pair",
    "warp_to_tray",
    "px_to_mm",
    "mm_to_px",
]

_INTERP_FLAGS = {
    "linear": cv2.INTER_LINEAR,
    "cubic": cv2.INTER_CUBIC,
    "nearest": cv2.INTER_NEAREST,
}


class CalibrationError(RuntimeError):
    """标定失败：角码缺失 / 单应退化 / 结果明显不自洽。"""


@dataclass(frozen=True)
class SingleCalib:
    """单面（一张整盘图）标定的富结果。

    H: 3x3，原图 px → 盘面 mm（齐次；透视除法后为 mm 坐标）。
    centers_px: 检测到的码中心（px）。corners_px: 检测角点 4x2（px，检测器原始序）。
    """

    H: np.ndarray
    px_per_mm: float
    reproj_err_px: float
    marker_ids: list[int]
    centers_px: dict[int, tuple[float, float]]
    corners_px: dict[int, np.ndarray]
    img_size: tuple[int, int]  # (w, h)


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _resolve_cfg(cfg: TrayConfig | str | Path | None) -> TrayConfig:
    if isinstance(cfg, TrayConfig):
        return cfg
    try:
        return load_tray_config(cfg)  # None → 仓库默认 configs/tray.yaml
    except TrayConfigError as exc:
        raise CalibrationError(f"托盘配置不可用: {exc}") from exc


def _as_gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img
    if img.ndim == 3 and img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
    if img.ndim == 3 and img.shape[2] == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    raise CalibrationError(f"不支持的图像形状 {img.shape}（期望 1/3/4 通道）")


def _perspective(pts: np.ndarray | Sequence[Sequence[float]], H: np.ndarray) -> np.ndarray:
    """逐点透视变换，输入 (N,2) 或 (2,)，输出同形状 float64。"""
    arr = np.asarray(pts, dtype=np.float64)
    single = arr.ndim == 1
    p = arr.reshape(-1, 1, 2).astype(np.float32)
    out = cv2.perspectiveTransform(p, np.asarray(H, dtype=np.float64).reshape(3, 3))
    out = out.reshape(-1, 2).astype(np.float64)
    return out[0] if single else out


def _local_scale_px_per_mm(H: np.ndarray, pt_mm: Sequence[float], eps: float = 0.05) -> float:
    """H 逆映射（mm→px）在 pt_mm 处的局部尺度 sqrt(|det J|)，即该点 px/mm。"""
    hinv = np.linalg.inv(np.asarray(H, dtype=np.float64))
    pt = np.asarray(pt_mm, dtype=np.float64)
    col = lambda d: (_perspective(pt + d, hinv) - _perspective(pt - d, hinv)) / (2.0 * eps)  # noqa: E731
    ex, ey = col(np.array([eps, 0.0])), col(np.array([0.0, eps]))
    det = ex[0] * ey[1] - ey[0] * ex[1]
    return math.sqrt(abs(det))


def _detect_markers(img: np.ndarray, cfg: TrayConfig) -> dict[int, np.ndarray]:
    """检测 ArUco 并按 id 索引；缺失任一期望角码即抛 CalibrationError。"""
    dict_id = getattr(cv2.aruco, cfg.dictionary, None)
    if not isinstance(dict_id, int):
        raise CalibrationError(f"未知 ArUco 字典常量 cv2.aruco.{cfg.dictionary}")
    dictionary = cv2.aruco.getPredefinedDictionary(dict_id)
    detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())
    corners, ids, _ = detector.detectMarkers(_as_gray(img))
    if ids is None or len(ids) == 0:
        raise CalibrationError(f"未检测到任何 ArUco 码（字典 {cfg.dictionary}）")
    found: dict[int, np.ndarray] = {}
    for quad, mid in zip(corners, ids):
        found[int(mid[0])] = np.asarray(quad, dtype=np.float64).reshape(4, 2)
    expected = set(cfg.centers_mm)
    got = expected & set(found)
    missing = sorted(expected - set(found))
    if missing:
        extra = sorted(set(found) - expected)
        raise CalibrationError(
            f"角码不全：期望 {sorted(expected)}，检测到 {len(got)}/4，缺失 id={missing}"
            + (f"，另有盘外误检 id={extra}" if extra else "")
            + "；v1 不做单码姿态兜底，请摆正托盘后重拍"
        )
    return {i: found[i] for i in expected}  # 只保留四角期望码，弃盘外误检


def _solve_view(found: dict[int, np.ndarray], cfg: TrayConfig, img_size: tuple[int, int]) -> SingleCalib:
    ids_sorted = sorted(found)
    centers_px = {i: tuple(found[i].mean(axis=0)) for i in ids_sorted}

    # --- a) 中心配对精确解（与摆放旋转/检测顺序无关） ---
    src = np.float32([centers_px[i] for i in ids_sorted])
    dst = np.float32([list(cfg.centers_mm[i]) for i in ids_sorted])
    H0, _ = cv2.findHomography(src, dst, 0)
    if H0 is None or not np.all(np.isfinite(H0)):
        raise CalibrationError("四码中心单应求解失败（findHomography 返回空/非有限值）")
    try:
        h0_inv = np.linalg.inv(np.asarray(H0, dtype=np.float64))
    except np.linalg.LinAlgError as exc:
        raise CalibrationError(f"中心单应矩阵不可逆: {exc}") from exc

    # --- b) 角点级精化：16 对（4 码 × 4 角），循环移位匹配 + 最小二乘 ---
    half = cfg.marker_mm / 2.0
    quads_mm: list[np.ndarray] = []
    quads_px: list[np.ndarray] = []
    for i in ids_sorted:
        cx, cy = cfg.centers_mm[i]
        quad_mm = np.array(
            [
                [cx - half, cy - half],  # 布局 TL（俯视坐标，顺时针序）
                [cx + half, cy - half],  # TR
                [cx + half, cy + half],  # BR
                [cx - half, cy + half],  # BL
            ],
            dtype=np.float64,
        )
        proj_px = _perspective(quad_mm, h0_inv)  # 布局角点反投影到原图 px
        rolls = [np.roll(found[i], k, axis=0) for k in range(4)]
        costs = [float(np.linalg.norm(proj_px - r, axis=1).sum()) for r in rolls]
        best = int(np.argmin(costs))
        quads_mm.append(quad_mm)
        quads_px.append(rolls[best])
    mm_all = np.vstack(quads_mm)
    px_all = np.vstack(quads_px)
    H1, _ = cv2.findHomography(
        px_all.reshape(-1, 1, 2).astype(np.float32), mm_all.reshape(-1, 1, 2).astype(np.float32), 0
    )

    def _rms_px(H: np.ndarray) -> float:
        """16 角点的像素重投影 RMS（布局 mm 经 H⁻¹ 投回 px 与检测比对）。"""
        try:
            hinv = np.linalg.inv(np.asarray(H, dtype=np.float64))
        except np.linalg.LinAlgError:
            return float("inf")
        proj = _perspective(mm_all, hinv)
        return float(np.sqrt(((proj - px_all) ** 2).sum(axis=1).mean()))

    rms0 = _rms_px(H0)
    if H1 is not None and np.all(np.isfinite(H1)):
        rms1 = _rms_px(H1)
        H, reproj = (H1, rms1) if rms1 <= rms0 else (H0, rms0)
    else:
        H, reproj = H0, rms0

    # --- 端到端自洽门：检测中心经 H 反投影须落在布局中心 ≤2mm ---
    px_per_mm = _local_scale_px_per_mm(H, cfg.center_mm)
    est_mm = _perspective(src, np.asarray(H, dtype=np.float64))
    center_err_mm = float(np.linalg.norm(est_mm - dst, axis=1).max())
    if center_err_mm > 2.0:
        raise CalibrationError(
            f"角码配对异常：中心反投影最大偏差 {center_err_mm:.2f}mm（阈值 2mm），"
            "请核对 configs/tray.yaml 布局与实际托盘是否一致"
        )

    return SingleCalib(
        H=np.asarray(H, dtype=np.float64),
        px_per_mm=px_per_mm,
        reproj_err_px=reproj,
        marker_ids=ids_sorted,
        centers_px=centers_px,
        corners_px=found,
        img_size=img_size,
    )


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def calibrate(img_bgr: np.ndarray, cfg: TrayConfig | str | Path | None = None) -> SingleCalib:
    """单面整盘图标定：检测 4 角 ArUco → 原图 px → 盘面 mm 单应。

    ``cfg`` 可传 TrayConfig / 配置路径 / None（用仓库默认 configs/tray.yaml）。
    检出 <4 码或 id 不全抛 :class:`CalibrationError`（v1 无单码兜底）。
    """
    cfg = _resolve_cfg(cfg)
    img = np.asarray(img_bgr)
    found = _detect_markers(img, cfg)
    return _solve_view(found, cfg, (int(img.shape[1]), int(img.shape[0])))


def calibrate_pair(
    img_top: np.ndarray,
    img_bottom: np.ndarray,
    cfg: TrayConfig | str | Path | None = None,
) -> CalibResult:
    """双面各标定一次，组装冻结契约 ``CalibResult``（M2 写入 TrayScan.calibration）。

    px_per_mm 取两面中心尺度均值；reproj_err_px 取两面最大（保守读数）。
    """
    cfg = _resolve_cfg(cfg)
    st = calibrate(img_top, cfg)
    sb = calibrate(img_bottom, cfg)
    return CalibResult(
        px_per_mm=(st.px_per_mm + sb.px_per_mm) / 2.0,
        H_top=[[float(v) for v in row] for row in st.H],
        H_bottom=[[float(v) for v in row] for row in sb.H],
        marker_ids=sorted(set(st.marker_ids) | set(sb.marker_ids)),
        reproj_err_px=max(st.reproj_err_px, sb.reproj_err_px),
    )


def px_to_mm(pts: np.ndarray | Sequence[Sequence[float]], H: np.ndarray) -> np.ndarray:
    """原图像素坐标 → 盘面 mm（用 calibrate 的 H；输入 (N,2) 或 (2,)）。"""
    return _perspective(pts, H)


def mm_to_px(pts: np.ndarray | Sequence[Sequence[float]], H: np.ndarray) -> np.ndarray:
    """盘面 mm → 原图像素坐标（H 的逆映射）。"""
    hinv = np.linalg.inv(np.asarray(H, dtype=np.float64).reshape(3, 3))
    return _perspective(pts, hinv)


def warp_to_tray(
    img_bgr: np.ndarray, H: np.ndarray, cfg: TrayConfig | str | Path | None = None
) -> np.ndarray:
    """原图 → 盘面正射网格（默认 2048² 覆盖 300×300mm，≈0.147mm/px）。

    变换矩阵 M = S(grid_px/tray_mm) · H；盘外区域填 cfg.border_value。
    """
    cfg = _resolve_cfg(cfg)
    s = cfg.grid_px / cfg.tray_mm
    M = np.array([[s, 0.0, 0.0], [0.0, s, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64) @ np.asarray(
        H, dtype=np.float64
    ).reshape(3, 3)
    img = np.asarray(img_bgr)
    if img.ndim == 3:
        border: int | tuple[int, int, int] = (cfg.border_value,) * img.shape[2]
    else:
        border = cfg.border_value
    return cv2.warpPerspective(
        img,
        M,
        (cfg.grid_px, cfg.grid_px),
        flags=_INTERP_FLAGS[cfg.interp],
        borderValue=border,
    )


def corners_px_of(calib: SingleCalib) -> dict[int, np.ndarray]:
    """透出检测角点（调试/画标注用）。"""
    return dict(calib.corners_px)
