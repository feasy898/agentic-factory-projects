"""分拣线 · 像素 → 桌面毫米映射（相机系 → 臂基座系）。

链路（复用既有 ArUco 标定 + 叠加安装外参）::

    图像 px --(beaneye.calibration 的单应 H)--> 托盘 mm
            --(平面外参: yaw 旋转 + 平移偏移)--> 桌面 mm（臂基座系）

- 单应 H 来自 ``beaneye.calibration.calibrate``（ArUco 四角，含 mm/px 与
  平面旋转——ArUco 配对与检测顺序/摆放旋转无关，平面姿态已全部在 H 里）；
- 外参（「相机/托盘相对臂基座」的安装偏移 + 残余平面旋转）读
  configs/sort.yaml ``extrinsic`` 节（**默认全零，明日实测回填**）；
- :func:`solve_affine` 三点标定辅助：现场在桌面/托盘上取 3 个已知桌面
  坐标的标记点，读其像素坐标，直接解 2×3 仿射（跳过 H+外参的合成链，
  也可用来标定/校核 ``extrinsic`` 本身——把仿射分解回刚体部分）。

全部变换支持单点 (2,) 或批量 (N,2)，numpy 实现，无 cv2 依赖。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

import numpy as np

from beaneye.sort.config import ExtrinsicParams

if TYPE_CHECKING:  # 仅供类型标注，运行时不依赖 calibration 的重型链路
    from beaneye.calibration.core import SingleCalib
    from beaneye.schemas import CalibResult

__all__ = [
    "FrameMappingError",
    "Extrinsic2D",
    "FrameToTable",
    "Affine2D",
    "solve_affine",
    "fit_residual",
    "frame_to_table_from_calib",
]


class FrameMappingError(ValueError):
    """映射构造/求解失败（点数不足 / 退化 / 标定对象缺单应）。"""


# ---------------------------------------------------------------------------
# 平面外参（托盘系 → 臂系 2D 刚体）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Extrinsic2D:
    """托盘系 → 臂系平面刚体外参：先转 ``yaw_deg``，再加 ``offset_mm`` 平移。"""

    yaw_deg: float = 0.0
    offset_mm: tuple[float, float] = (0.0, 0.0)

    @classmethod
    def from_config(cls, ex: ExtrinsicParams) -> "Extrinsic2D":
        return cls(yaw_deg=ex.yaw_deg, offset_mm=ex.offset_mm)

    @property
    def _matrix(self) -> np.ndarray:
        """3×3 齐次（托盘 mm → 臂 mm）。"""
        t = math.radians(self.yaw_deg)
        c, s = math.cos(t), math.sin(t)
        return np.array(
            [[c, -s, self.offset_mm[0]], [s, c, self.offset_mm[1]], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        )

    def apply(self, pts_mm: np.ndarray | Sequence[Sequence[float]]) -> np.ndarray:
        """托盘 mm → 臂系桌面 mm（支持单点或批量）。"""
        return _happly(self._matrix, pts_mm)

    def inverse(self) -> "Extrinsic2D":
        """逆外参（臂系 → 托盘系；平面刚体的逆仍是平面刚体）。"""
        m_inv = np.linalg.inv(self._matrix)
        return Extrinsic2D(
            yaw_deg=-self.yaw_deg,
            offset_mm=(
                float(-(m_inv[0, 0] * self.offset_mm[0] + m_inv[0, 1] * self.offset_mm[1])),
                float(-(m_inv[1, 0] * self.offset_mm[0] + m_inv[1, 1] * self.offset_mm[1])),
            ),
        )


def _happly(m: np.ndarray, pts: np.ndarray | Sequence[Sequence[float]]) -> np.ndarray:
    """齐次矩阵作用于点（支持 (2,) 或 (N,2)，返回同形状 float64）。"""
    arr = np.asarray(pts, dtype=np.float64)
    single = arr.ndim == 1
    p = np.atleast_2d(arr)
    out = (m[:2, :2] @ p.T).T + m[:2, 2]
    return out[0] if single else out


# ---------------------------------------------------------------------------
# 像素 → 桌面毫米（H + 外参）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FrameToTable:
    """一帧图像的 px → 桌面 mm 映射（H 来自 ArUco 标定 + 安装外参）。

    ``H``：3×3 单应，图像 px → 托盘 mm（beaneye.calibration 产物，行主序）。
    """

    H: np.ndarray
    extrinsic: Extrinsic2D

    def __post_init__(self) -> None:
        h = np.asarray(self.H, dtype=np.float64)
        if h.shape != (3, 3) or not np.all(np.isfinite(h)):
            raise FrameMappingError(f"H 必须是 3×3 有限矩阵，得到 shape={np.shape(self.H)}")
        det = float(np.linalg.det(h))
        if abs(det) < 1e-12:
            raise FrameMappingError(f"H 奇异（det={det:.3e}），单应退化")
        object.__setattr__(self, "H", h)

    # -- 正向：px → 桌面 mm ---------------------------------------------------

    def px_to_tray_mm(self, pts_px: np.ndarray | Sequence[Sequence[float]]) -> np.ndarray:
        """图像 px → 托盘 mm（即 beaneye.calibration.px_to_mm 的本类内联）。"""
        return _perspective(self.H, pts_px)

    def tray_to_table_mm(self, pts_mm: np.ndarray | Sequence[Sequence[float]]) -> np.ndarray:
        """托盘 mm → 臂系桌面 mm（外参刚体）。"""
        return self.extrinsic.apply(pts_mm)

    def px_to_table_mm(self, pts_px: np.ndarray | Sequence[Sequence[float]]) -> np.ndarray:
        """图像 px → 臂系桌面 mm（全链路主入口）。"""
        return self.tray_to_table_mm(self.px_to_tray_mm(pts_px))

    # -- 反向：桌面 mm → px（把计划/轨迹画回图上用） ---------------------------

    def table_to_tray_mm(self, pts_mm: np.ndarray | Sequence[Sequence[float]]) -> np.ndarray:
        return self.extrinsic.inverse().apply(pts_mm)

    def tray_to_px(self, pts_mm: np.ndarray | Sequence[Sequence[float]]) -> np.ndarray:
        return _perspective(np.linalg.inv(self.H), pts_mm)

    def table_to_px(self, pts_mm: np.ndarray | Sequence[Sequence[float]]) -> np.ndarray:
        """臂系桌面 mm → 图像 px（render 反向投影）。"""
        return self.tray_to_px(self.table_to_tray_mm(pts_mm))


def _perspective(h: np.ndarray, pts: np.ndarray | Sequence[Sequence[float]]) -> np.ndarray:
    arr = np.atleast_2d(np.asarray(pts, dtype=np.float64))
    ph = np.c_[arr, np.ones(len(arr))] @ h.T
    w = ph[:, 2:3]
    if np.any(np.abs(w) < 1e-12):
        raise FrameMappingError("单应透视除法遇 w≈0（点落在退化区）")
    out = ph[:, :2] / w
    return out[0] if np.asarray(pts).ndim == 1 else out


# ---------------------------------------------------------------------------
# 三点标定辅助：直接解 px（或任意源系）→ 桌面 mm 的 2×3 仿射
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Affine2D:
    """2×3 仿射映射（源系 → 桌面 mm）：``dst = A·src + t``。"""

    matrix: np.ndarray  # 2×3

    def __post_init__(self) -> None:
        m = np.asarray(self.matrix, dtype=np.float64)
        if m.shape != (2, 3) or not np.all(np.isfinite(m)):
            raise FrameMappingError(f"仿射矩阵必须是 2×3 有限矩阵，得到 shape={np.shape(self.matrix)}")
        if abs(float(np.linalg.det(m[:, :2]))) < 1e-12:
            raise FrameMappingError(f"仿射线性部分退化（det={float(np.linalg.det(m[:, :2])):.3e}）")
        object.__setattr__(self, "matrix", m)

    def apply(self, pts: np.ndarray | Sequence[Sequence[float]]) -> np.ndarray:
        """源系点 → 桌面 mm（支持单点或批量）。"""
        arr = np.atleast_2d(np.asarray(pts, dtype=np.float64))
        out = arr @ self.matrix[:, :2].T + self.matrix[:, 2]
        return out[0] if np.asarray(pts).ndim == 1 else out

    def to_homogeneous(self) -> np.ndarray:
        """3×3 齐次形式（与 :class:`FrameToTable` 组合/互转用）。"""
        return np.vstack([self.matrix, [0.0, 0.0, 1.0]])


def solve_affine(
    src_pts: Sequence[Sequence[float]], dst_pts: Sequence[Sequence[float]]
) -> Affine2D:
    """三点（或更多点最小二乘）解仿射：``dst = A·src + t``。

    现场三点标定：桌面/托盘取 3 个已知桌面坐标的标记点（非共线），量出
    其像素坐标，即可直接得到 px → 桌面 mm 映射。点数 >3 时按最小二乘
    （可同时报拟合残差，供人工判断标定质量）。
    """
    src = np.atleast_2d(np.asarray(src_pts, dtype=np.float64))
    dst = np.atleast_2d(np.asarray(dst_pts, dtype=np.float64))
    if len(src) != len(dst) or len(src) < 3:
        raise FrameMappingError(
            f"三点标定至少需要 3 对等长点对，得到 src={len(src)}, dst={len(dst)}"
        )
    # 非共线校验（前三点叉积）
    (x0, y0), (x1, y1), (x2, y2) = src[0], src[1], src[2]
    if abs((x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0)) < 1e-9:
        raise FrameMappingError("标定源点三点共线，仿射无解（请重新选点）")
    a_t = np.hstack([src, np.ones((len(src), 1))])  # N×3
    sol, *_ = np.linalg.lstsq(a_t, dst, rcond=None)  # 3×2
    return Affine2D(matrix=sol.T)  # 2×3


def fit_residual(affine: Affine2D, src_pts: Sequence[Sequence[float]], dst_pts: Sequence[Sequence[float]]) -> float:
    """标定点的拟合残差 RMS（mm；>2mm 建议重标）。"""
    src = np.atleast_2d(np.asarray(src_pts, dtype=np.float64))
    dst = np.atleast_2d(np.asarray(dst_pts, dtype=np.float64))
    err = affine.apply(src) - dst
    return float(np.sqrt((err ** 2).sum(axis=1).mean()))


# ---------------------------------------------------------------------------
# 从既有标定产物装配
# ---------------------------------------------------------------------------


def frame_to_table_from_calib(
    calib: "SingleCalib | CalibResult",
    extrinsic: Extrinsic2D | ExtrinsicParams,
    *,
    side: str = "top",
) -> FrameToTable:
    """从 beaneye.calibration 的标定结果装配 FrameToTable。

    - ``SingleCalib``：直接取其 ``H``；
    - ``CalibResult``（冻结契约）：按 ``side`` 取 ``H_top`` / ``H_bottom``；
    - ``extrinsic`` 接受配置外参 (:class:`ExtrinsicParams`) 或
      :class:`Extrinsic2D`（前者自动包装）。
    """
    h_or_result = getattr(calib, "H", None)
    if h_or_result is not None:
        h = np.asarray(h_or_result, dtype=np.float64)
    else:
        key = f"H_{side}"
        h = getattr(calib, key, None)
        if h is None:
            raise FrameMappingError(
                f"标定对象 {type(calib).__name__} 缺少 H / {key} 字段"
                f"（side={side!r} 不受支持：契约面只有 top/bottom），无法装配映射"
            )
        h = np.asarray(h, dtype=np.float64)
    if isinstance(extrinsic, ExtrinsicParams):
        extrinsic = Extrinsic2D.from_config(extrinsic)
    return FrameToTable(H=h, extrinsic=extrinsic)
