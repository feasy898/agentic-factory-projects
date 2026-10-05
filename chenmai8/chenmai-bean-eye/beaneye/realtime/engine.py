"""实时线 · 逐帧管线（beaneye.realtime.engine）。

RealtimeEngine 把实时画面接入既有识别链（全部复用，不重写）：

    帧(BGR) → 可选降采样 → ClassicSeg 逐粒分割（beaneye.segment.classic）
           → 逐粒 crop RGBA + RulesV0 规则分类（beaneye.classify）
           → FrameResult（逐粒 BeanSpot + 整帧各类计数 + FPS）

实时模式**单面拍摄**：不做双面配对、不做计量定级——那是整盘批处理链
（beaneye.app.pipeline）的职责；本引擎只产逐帧着色标注所需的轻量结果。

毫米口径（重要，诚实边界）：

- ClassicSeg 按「输入图 = 托盘正射网格」假设把 mm/px 记为 ``tray_mm/图宽``。
  实时画面不是正射网格，因此**未标定时掩码 mm 是伪毫米**（只有像素几何
  可信）：BeanSpot.eq_diameter_mm 此时恒为 None，HUD 显示「未标定」；
- 画面里出现四角 ArUco（合成盘帧自带；真机摆托盘拍摄即有）时，引擎按
  ``calib_every`` 周期重解单应（复用 :func:`beaneye.calibration.calibrate`），
  并把帧 warp 到 ``warp_grid_px`` 正射网格再分割——此时 mm 是**真毫米**，
  BeanSpot.eq_diameter_mm 给出豆粒等效直径，HUD 显示毫米尺寸（简报加分项）。

工程约定：

- 分割/分类实现满足冻结 Protocol（``beaneye.schemas.SegModel`` / ``ClsModel``），
  构造参数可注入替身（测试用 OracleSeg + 真值分类器做「类别计数与合成 GT
  一致」的端到端）；每帧构造的最小 TrayScan 只作协议载荷（scan_id 可配）；
- 旋钮：``downscale``（工作图缩放，0.1-1.0）与 ``skip``（每 skip+1 帧处理
  一次；跳过帧返回上一处理帧结果的轻量拷贝，叠加层保持稳定）；
- 帧坐标系：BeanSpot 的 centroid_px / contour_px 一律折算回**原始帧像素**
  坐标（与 downscale 无关），叠加层直接画在原始帧上。
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, replace as dc_replace
from datetime import datetime, timezone
from typing import Any

import cv2
import numpy as np
from pydantic import Field

from beaneye.calibration import CalibrationError, calibrate, load_tray_config, warp_to_tray
from beaneye.classify import DEFAULT_TAU, NnOnnxClassifier, RulesV0
from beaneye.segment import ClassicSeg
from beaneye.schemas import BeanEyeBaseModel, BeanMask, TrayScan
from beaneye.taxonomy import Taxonomy, load_taxonomy

__all__ = [
    "RealtimeConfig",
    "BeanSpot",
    "FrameResult",
    "RealtimeEngine",
    "crop_mask_rgba",
    "CLASSIFIER_CHOICES",
    "ClassifierUsageError",
    "build_classifier",
]

CLASSIFIER_CHOICES = ("rules", "nn")


class ClassifierUsageError(ValueError):
    """分类器开关用法错误（未知选项 / nn 未给 onnx 路径）。"""


def build_classifier(
    choice: str = "rules",
    nn_onnx: str | None = None,
    *,
    tau: float = DEFAULT_TAU,
) -> RulesV0 | NnOnnxClassifier:
    """分类器开关装配（批10）：``rules`` → RulesV0（缺省，产品现状）；
    ``nn`` → NnOnnxClassifier(onnx, τ)（批9 海南域 ONNX 头，τ=批10 扫描
    推荐工作点 0.13）。两实现满足同一冻结分类协议，引擎无差别调用。
    """
    if choice == "rules":
        return RulesV0()
    if choice == "nn":
        if not nn_onnx:
            raise ClassifierUsageError("classifier=nn 需要提供 nn_onnx 路径（如 train/runs/crop_cls/b9.onnx）")
        return NnOnnxClassifier(nn_onnx, tau=tau)
    raise ClassifierUsageError(f"未知分类器选项 {choice!r}（可选 {CLASSIFIER_CHOICES}）")


# ---------------------------------------------------------------------------
# 配置与输出 schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RealtimeConfig:
    """实时管线旋钮（_immutable_；字段语义见模块 docstring）。"""

    downscale: float = 1.0        # 工作图缩放系数（相对原始帧；1.0=原尺寸）
    skip: int = 0                 # 每 skip+1 帧处理一次（0=每帧都处理）
    calibrate: bool = True        # 加分项：画面有四角 ArUco 时刷新毫米标定
    calib_every: int = 10         # 每处理多少帧重解一次单应（1=每处理帧都解）
    warp_grid_px: int = 720       # 标定后正射网格边长（越小越快；真毫米口径）
    fps_ema: float = 0.85         # FPS 指数滑动平均系数（越大越平滑）

    def __post_init__(self) -> None:
        if not 0.1 <= float(self.downscale) <= 1.0:
            raise ValueError(f"downscale 必须在 [0.1, 1.0]，得到 {self.downscale}")
        if int(self.skip) < 0:
            raise ValueError(f"skip 必须 >= 0，得到 {self.skip}")
        if int(self.calib_every) < 1:
            raise ValueError(f"calib_every 必须 >= 1，得到 {self.calib_every}")
        if not 256 <= int(self.warp_grid_px) <= 2048:
            raise ValueError(f"warp_grid_px 必须在 [256, 2048]，得到 {self.warp_grid_px}")
        if not 0.0 < float(self.fps_ema) < 1.0:
            raise ValueError(f"fps_ema 必须在 (0,1)，得到 {self.fps_ema}")


class BeanSpot(BeanEyeBaseModel):
    """一粒豆的实时检测结果（像素坐标，与 downscale 无关）。"""

    defect: str                                  # taxonomy key
    conf: float = Field(default=0.0, ge=0.0, le=1.0)
    severity_rank: int = Field(default=0, ge=0)
    centroid_px: tuple[float, float]
    area_px: float = Field(default=0.0, ge=0.0)  # 掩码像素数（伪毫米=原始帧口径；标定=网格口径）
    color_bgr: tuple[int, int, int] = (0, 0, 0)  # 掩码内均值 BGR（实测豆色）
    contour_px: list[list[float]] = Field(default_factory=list)  # 原始帧像素坐标外轮廓
    eq_diameter_mm: float | None = None          # 仅真毫米口径（已标定）时给出
    mask_id: str = ""


class FrameResult(BeanEyeBaseModel):
    """一帧的实时标注结果（skipped 帧复用上一处理帧的内容）。"""

    frame_index: int
    skipped: bool = False
    width: int = 0            # 原始帧宽（px）
    height: int = 0           # 原始帧高（px）
    beans: list[BeanSpot] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)  # taxonomy key → 粒数（含 normal；严重度序）
    fps: float = 0.0              # 处理帧吞吐（EMA；不含被 skip 的帧）
    mm_per_px: float | None = None  # 原始帧口径标定值（1/帧中心 px_per_mm）；未标定=None
    calibrated: bool = False
    process_ms: float = 0.0       # 本次处理耗时（ms；跳过帧 = 0）


# ---------------------------------------------------------------------------
# 逐帧管线
# ---------------------------------------------------------------------------


def crop_mask_rgba(img_bgr: np.ndarray, mask: BeanMask, mm_per_px: float) -> np.ndarray:
    """按掩码 mm 多边形从 BGR 图裁出 RGBA（RGB+alpha）证据 crop。

    与 ``beaneye.app.pipeline.extract_mask_crop_rgba`` 同语义（正射/伪正射图
    上 mm → px 线性换算 + fillPoly 掩模）；本地实现以避免实时线反向依赖
    应用层（app 包导入即拉起 report/agent 全栈）。
    """
    h, w = img_bgr.shape[:2]
    x0, y0, x1, y1 = mask.bbox_mm
    px0 = max(0, int(np.floor(x0 / mm_per_px)) - 2)
    py0 = max(0, int(np.floor(y0 / mm_per_px)) - 2)
    px1 = min(w, int(np.ceil(x1 / mm_per_px)) + 2)
    py1 = min(h, int(np.ceil(y1 / mm_per_px)) + 2)
    # mm 口径与图不符（如真值掩码 + 伪毫米、异形画布）时窗口可能越界/翻转——
    # 实时循环绝不因单粒 crop 崩溃：钳回合法窗口，退化 crop 由调用方按空处理
    px0, py0 = min(px0, w - 1), min(py0, h - 1)
    px1, py1 = max(px1, px0 + 1), max(py1, py0 + 1)
    if px1 - px0 < 2 or py1 - py0 < 2:
        px1, py1 = min(w, px0 + 4), min(h, py0 + 4)
    patch = img_bgr[py0:py1, px0:px1]
    poly = np.asarray(mask.polygon, dtype=np.float32) / float(mm_per_px)
    poly[:, 0] -= float(px0)
    poly[:, 1] -= float(py0)
    alpha = np.zeros(patch.shape[:2], dtype=np.uint8)
    cv2.fillPoly(alpha, [np.round(poly).astype(np.int32)], 255)
    rgb = cv2.cvtColor(patch, cv2.COLOR_BGR2RGB)
    return np.dstack([rgb, alpha])


class RealtimeEngine:
    """逐帧实时管线：分割 → 分类 → 结构化结果（叠加绘制见 overlay 模块）。"""

    stage = "realtime"
    version = "realtime:v1 (classic+rules_v0)"

    def __init__(
        self,
        *,
        cfg: RealtimeConfig | None = None,
        segment: Any | None = None,
        classify: Any | None = None,
        taxonomy: Taxonomy | None = None,
        scan_id: str = "live",
    ) -> None:
        self.cfg = cfg if cfg is not None else RealtimeConfig()
        self.segment = segment if segment is not None else ClassicSeg()
        self.classify = classify if classify is not None else RulesV0()
        self.tax = taxonomy if taxonomy is not None else load_taxonomy()
        self.scan_id = str(scan_id)
        self._frame_no = -1          # 已读入帧序（含跳过）
        self._processed = 0          # 实际处理帧序
        self._fps = 0.0
        self._last_t: float | None = None
        self._last: FrameResult | None = None
        self._H: np.ndarray | None = None      # 工作图 px → 盘面 mm（ArUco 标定）
        self._mm_per_px: float | None = None   # 原始帧口径 mm/px（1/帧中心 px_per_mm；HUD 用）
        self._tray = load_tray_config()
        self._scan = TrayScan(
            scan_id=self.scan_id,
            sample_id="live",
            tray_id="live",
            top_image="live_top.png",
            bottom_image="live_bottom.png",
            calibration=None,
            captured_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            source="usb",  # 实时=真实相机语义（契约三值取 usb）
        )

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------

    @property
    def frame_index(self) -> int:
        """已读入帧序（从 0 起；含被跳过的帧）。"""
        return self._frame_no

    @property
    def processed_frames(self) -> int:
        """已完整处理的帧数（不含跳过帧）。"""
        return self._processed

    @property
    def calibrated(self) -> bool:
        """当前是否处于真毫米口径（ArUco 标定有效）。"""
        return self._H is not None

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def process(self, frame_bgr: np.ndarray) -> FrameResult:
        """处理一帧 → :class:`FrameResult`（跳过帧返回上一结果轻量拷贝）。"""
        self._frame_no += 1
        idx = self._frame_no
        step = int(self.cfg.skip) + 1
        if self._last is not None and idx % step != 0:
            return self._last.model_copy(
                update={"frame_index": idx, "skipped": True, "process_ms": 0.0}
            )

        t0 = time.perf_counter()
        frame = np.asarray(frame_bgr)
        if frame.ndim != 3 or frame.shape[2] < 3:
            raise ValueError(f"实时帧形状不支持: {frame.shape}（期望 HxWx3 BGR）")
        h, w = frame.shape[:2]

        # ---- 1) 可选降采样（工作图；结果坐标折回原始帧） -------------------
        scale = float(self.cfg.downscale)
        if scale < 1.0 - 1e-9:
            work = cv2.resize(
                frame, (max(2, int(round(w * scale))), max(2, int(round(h * scale)))),
                interpolation=cv2.INTER_AREA,
            )
        else:
            work = frame
        wh, ww = work.shape[:2]
        inv_scale = 1.0 / scale

        # ---- 2) 毫米标定（加分项）：周期重解单应；成功则 warp 正射网格 -----
        self._maybe_calibrate(work)
        if self._H is not None:
            grid_cfg = dc_replace(self._tray, grid_px=int(self.cfg.warp_grid_px))
            img_bgr = warp_to_tray(work, self._H, grid_cfg)
            mm_per_px = self._tray.tray_mm / float(self.cfg.warp_grid_px)  # 真毫米
            calibrated = True
        else:
            img_bgr = work
            mm_per_px = self._tray.tray_mm / float(ww)  # 伪毫米（ClassicSeg 假设口径）
            calibrated = False

        # ---- 3) 分割（复用冻结 SegModel 协议） → 逐粒分类 ------------------
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        seg = self.segment.predict(img_rgb, self._scan)
        # mm → 原始帧 px 的几何回映：
        #   伪毫米路径 = 线性（ClassicSeg 的 tray_mm/图宽 口径）；
        #   标定路径   = H⁻¹ 透视（warp 网格 mm → 原图 px），叠加层才画得准
        hinv = np.linalg.inv(self._H) if calibrated and self._H is not None else None

        def mm_to_frame_px(pts_mm: np.ndarray) -> np.ndarray:
            if hinv is not None:
                px = cv2.perspectiveTransform(
                    np.asarray(pts_mm, dtype=np.float64).reshape(-1, 1, 2), hinv
                ).reshape(-1, 2)
                return px * inv_scale  # H 在工作图上解得 → 折回原始帧
            return np.asarray(pts_mm, dtype=np.float64) / float(mm_per_px) * inv_scale

        beans: list[BeanSpot] = []
        for m in seg.masks:
            crop = crop_mask_rgba(img_bgr, m, mm_per_px)
            defect, conf, rank = self.classify.classify(crop, m)
            beans.append(
                self._to_spot(
                    m, crop, defect, float(conf), int(rank),
                    mm_to_frame_px=mm_to_frame_px, calibrated=calibrated,
                )
            )

        # ---- 4) 整帧计数（严重度序） + FPS（EMA） ---------------------------
        hist = Counter(b.defect for b in beans)
        counts: dict[str, int] = {}
        for key in self.tax.severity_order:
            n = int(hist.get(key, 0))
            if n > 0:
                counts[key] = n
        for key, n in sorted(hist.items()):  # 盘外键不丢（诚实透出）
            if key not in counts:
                counts[key] = int(n)

        now = time.perf_counter()
        if self._last_t is not None:
            dt = now - self._last_t
            inst = 1.0 / dt if dt > 1e-6 else 0.0
            self._fps = (
                inst if self._processed == 0
                else float(self.cfg.fps_ema) * self._fps + (1.0 - float(self.cfg.fps_ema)) * inst
            )
        self._last_t = now
        self._processed += 1

        res = FrameResult(
            frame_index=idx,
            skipped=False,
            width=int(w),
            height=int(h),
            beans=beans,
            counts=counts,
            fps=round(self._fps, 2),
            # 帧口径 mm/px（HUD「标定 x.xxx mm/px」即此值）；内部 crop 用网格口径
            mm_per_px=(round(float(self._mm_per_px), 6) if calibrated else None),
            calibrated=calibrated,
            process_ms=round((time.perf_counter() - t0) * 1000.0, 2),
        )
        self._last = res
        return res

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _maybe_calibrate(self, work: np.ndarray) -> None:
        """按 calib_every 周期尝试 ArUco 标定（失败=退回伪毫米，不抛错）。"""
        if not self.cfg.calibrate:
            self._H = None
            self._mm_per_px = None
            return
        if self._processed % int(self.cfg.calib_every) != 0:
            return  # 周期之间沿用上次单应
        try:
            cal = calibrate(work, self._tray)
            self._H = np.asarray(cal.H, dtype=np.float64)
            self._mm_per_px = 1.0 / float(cal.px_per_mm)  # 帧中心局部尺度的倒数
        except CalibrationError:
            self._H = None  # 码不全/画面无托盘：诚实退回伪毫米口径
            self._mm_per_px = None

    def _to_spot(
        self,
        m: BeanMask,
        crop: np.ndarray,
        defect: str,
        conf: float,
        rank: int,
        *,
        mm_to_frame_px,
        calibrated: bool,
    ) -> BeanSpot:
        """契约 BeanMask + 分类输出 → 原始帧像素坐标的 BeanSpot。

        ``area_px`` 口径随路径注明：伪毫米路径 = 原始帧像素；标定路径 =
        正射网格像素（透视下逐点尺度不同，不做假折算）。
        """
        poly_mm = np.asarray(m.polygon, dtype=np.float64)
        poly = mm_to_frame_px(poly_mm)
        cx, cy = m.centroid_mm
        c = mm_to_frame_px(np.array([[float(cx), float(cy)]], dtype=np.float64))[0]
        centroid = (float(c[0]), float(c[1]))

        sel = crop[..., 3] > 127
        if sel.any():
            mean_rgb = crop[..., :3][sel].mean(axis=0)
            color = (int(round(mean_rgb[2])), int(round(mean_rgb[1])), int(round(mean_rgb[0])))
        else:
            color = (0, 0, 0)
        area_px = float(sel.sum())  # 工作图口径（伪毫米=原始帧 px；标定=网格 px）
        eq_mm: float | None = None
        if calibrated and m.area_mm2 > 0:
            eq_mm = round(2.0 * float(np.sqrt(m.area_mm2 / np.pi)), 3)
        return BeanSpot(
            defect=defect,
            conf=round(float(conf), 4),
            severity_rank=int(rank),
            centroid_px=(round(centroid[0], 2), round(centroid[1], 2)),
            area_px=round(area_px, 2),
            color_bgr=color,
            contour_px=[[round(float(x), 1), round(float(y), 1)] for x, y in poly],
            eq_diameter_mm=eq_mm,
            mask_id=m.mask_id,
        )
