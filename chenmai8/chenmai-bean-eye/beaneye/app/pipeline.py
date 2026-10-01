"""M13 应用壳 · 全链路管线（整盘图 → 标定 → 分割 → 分类 → 证据 → 配对 →
计量 → 定级 → 溯因 → 护照）。

装配顺序对齐 plan/开发指令.md §2 数据流；所有跨阶段数据走冻结契约
（beaneye.schemas）。降级语义：

- 分割/分类缺位（``NullSegModel``/``NullClsModel``）→ 0 检出继续走完全链路
  （配对/计量/定级/护照全部真实执行），降级阶段与原因由调用方写入响应；
- 标定失败（图上无四角码）→ :class:`PipelineStageError`（阶段=calibration），
  作业置 failed——v1 不做单码兜底（M3 spec 约定现场摆正重拍）；
- 护照生成失败不吞结果：作业仍 done，护照阶段记入降级清单。

**校验和一致性约定**：护照 QR 内嵌 ``sha256(BatchResult)``，因此 BatchResult
必须在护照生成前定型——``timings_s`` 覆盖到 agent 为止，护照耗时单列在
``PipelineOutcome.passport_runtime_s``（写回会把 QR 校验和与结果脱钩）。

图像 IO 一律走字节缓冲封装（``beaneye.acquisition.base`` 的
``imread_bgr/imwrite_bgr``，内部 cv2.imencode/imdecode + 字节流写读；
工程路径含中文，cv2 直传路径会静默失败——W0b 实测坑，gate 第⑤项红线）。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from beaneye.acquisition.base import AcquisitionError, imread_bgr, imwrite_bgr
from beaneye.agent import RootCauseAgent, make_agent
from beaneye.app.components import Components, normalize_seg_result
from beaneye.calibration import CalibrationError, calibrate_pair, load_tray_config, warp_to_tray
from beaneye.metrology import measure
from beaneye.pairing import pair_observations
from beaneye.report import build_passport, build_qr_payload, canonical_sha256
from beaneye.schemas import (
    AgentReport,
    BatchResult,
    BeanMask,
    BeanObservation,
    PassportReport,
    PairedBean,
    SegResult,
    TrayScan,
)
from beaneye.standards import DEFAULT_STANDARDS_DIR, StandardEngineV1, load_engine
from beaneye.taxonomy import Taxonomy, load_taxonomy

__all__ = [
    "PipelineStageError",
    "PipelineRequest",
    "PipelineOutcome",
    "STAGE_ORDER",
    "run_pipeline",
    "make_offline_agent",
    "extract_mask_crop_rgba",
]

# 作业阶段名（演示页进度与响应 timings 键一致；passport 耗时单列，见模块 docstring）
STAGE_ORDER = (
    "ingest",
    "calibration",
    "segment",
    "classify",
    "pairing",
    "metrology",
    "grading",
    "agent",
    "passport",
)


class PipelineStageError(RuntimeError):
    """管线某阶段失败：``stage`` 供作业状态与 API 错误信息使用。"""

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(f"[{stage}] {message}")
        self.stage = stage
        self.message = message


@dataclass
class PipelineRequest:
    """一次整盘作业的输入（双面图已落盘，路径为绝对路径）。

    ``ingest_degraded``：入库阶段即已发生的降级（如合成请求回退内置模拟源），
    键为阶段名、值为原因；随结果信封一起透出。
    """

    scan: TrayScan
    top_path: Path
    bottom_path: Path
    standard_id: str
    langs: list[str]
    data_root: Path
    ingest_degraded: dict[str, str] = field(default_factory=dict)


@dataclass
class PipelineOutcome:
    """管线产物：契约结果 + 护照 + 降级元数据 + 已写入标定的 scan。"""

    result: BatchResult
    passport: PassportReport | None
    scan: TrayScan
    degraded_stages: list[str] = field(default_factory=list)
    degraded_reasons: dict[str, str] = field(default_factory=dict)
    pairing_summary: dict[str, int] = field(default_factory=dict)
    passport_runtime_s: float = 0.0


def make_offline_agent() -> RootCauseAgent:
    """离线溯因智能体（模板保底；应用评测不依赖网络/环境变量）。"""
    return make_agent(backend="template")


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def run_pipeline(
    req: PipelineRequest,
    components: Components,
    *,
    agent: RootCauseAgent | None = None,
) -> PipelineOutcome:
    """按阶段执行全链路；任何硬失败抛 :class:`PipelineStageError`。"""
    ag = agent if agent is not None else make_offline_agent()
    timings: dict[str, float] = {}

    # ---- ingest：读回双面图（中文路径安全封装） ---------------------------
    t0 = time.perf_counter()
    try:
        top_bgr = imread_bgr(req.top_path)
        bottom_bgr = imread_bgr(req.bottom_path)
    except AcquisitionError as exc:
        raise PipelineStageError("ingest", str(exc)) from exc
    timings["ingest"] = time.perf_counter() - t0

    # ---- calibration：ArUco 四角 → 单应（失败=作业失败，不降级继续） ------
    t0 = time.perf_counter()
    try:
        calib = calibrate_pair(top_bgr, bottom_bgr)
    except CalibrationError as exc:
        raise PipelineStageError(
            "calibration",
            f"整盘图未检出四角定位码（{exc}）——请上传带四角定位码的整盘照片",
        ) from exc
    scan = req.scan.model_copy(update={"calibration": calib})
    timings["calibration"] = time.perf_counter() - t0

    # ---- 正射盘面网格（mm 坐标系；分割/分类/证据裁剪统一在此坐标系） ------
    tray_cfg = load_tray_config()
    mm_per_px = tray_cfg.tray_mm / tray_cfg.grid_px
    warped = {
        "top": warp_to_tray(top_bgr, np.asarray(calib.H_top, dtype=np.float64), tray_cfg),
        "bottom": warp_to_tray(bottom_bgr, np.asarray(calib.H_bottom, dtype=np.float64), tray_cfg),
    }

    # ---- segment：每面各调一次（协议不携带 side，装配器规范化） ----------
    t0 = time.perf_counter()
    seg_results: dict[str, SegResult] = {}
    for side in ("top", "bottom"):
        img_rgb = cv2.cvtColor(warped[side], cv2.COLOR_BGR2RGB)
        raw = components.segment.impl.predict(img_rgb, scan)
        if not isinstance(raw, SegResult):
            raise PipelineStageError(
                "segment", f"分割实现返回 {type(raw).__name__}，契约要求 SegResult"
            )
        seg_results[side] = normalize_seg_result(raw, side=side, scan_id=scan.scan_id)
    timings["segment"] = time.perf_counter() - t0

    # ---- classify + 证据裁剪：逐掩码 crop RGBA + LAB 均值 + 等效直径 -----
    t0 = time.perf_counter()
    crops_dir = req.data_root / "crops" / scan.scan_id
    tax = load_taxonomy()
    observations: dict[str, list[BeanObservation]] = {"top": [], "bottom": []}
    for side in ("top", "bottom"):
        for m in seg_results[side].masks:
            crop_rgba = extract_mask_crop_rgba(warped[side], m, mm_per_px)
            crop_rel = f"crops/{scan.scan_id}/{m.mask_id}.png"
            imwrite_bgr(crops_dir / f"{m.mask_id}.png", crop_rgba)
            defect, conf, rank = components.classify.impl.classify(crop_rgba, m)
            _validate_cls_output(defect, conf, rank, tax, m.mask_id)
            observations[side].append(
                BeanObservation(
                    obs_id=m.mask_id,
                    side=side,
                    defect=defect,
                    defect_conf=float(conf),
                    severity_rank=int(rank),
                    crop_path=crop_rel,
                    mask=m,
                    color_lab=_masked_lab8(warped[side], m, mm_per_px),
                    eq_diameter_mm=_eq_diameter_mm(m.area_mm2),
                )
            )
    timings["classify"] = time.perf_counter() - t0

    # ---- pairing --------------------------------------------------------
    t0 = time.perf_counter()
    beans: list[PairedBean] = pair_observations(observations["top"], observations["bottom"])
    timings["pairing"] = time.perf_counter() - t0
    pairing_summary = {
        "paired": sum(1 for b in beans if b.top is not None and b.bottom is not None),
        "top_only": sum(1 for b in beans if b.bottom is None and b.top is not None),
        "bottom_only": sum(1 for b in beans if b.top is None and b.bottom is not None),
    }

    # ---- metrology ------------------------------------------------------
    t0 = time.perf_counter()
    std_path = Path(DEFAULT_STANDARDS_DIR) / f"{req.standard_id}.yaml"
    measurements = measure(beans, calib, str(std_path))
    timings["metrology"] = time.perf_counter() - t0

    # ---- grading --------------------------------------------------------
    t0 = time.perf_counter()
    engine: StandardEngineV1 = load_engine(req.standard_id)
    grading = engine.evaluate(beans, measurements)
    timings["grading"] = time.perf_counter() - t0

    # ---- 组结果 → 溯因 → 定型（护照生成前 BatchResult 不得再变） ---------
    t0 = time.perf_counter()
    pre_versions = _pipeline_versions(components, req.standard_id)
    result = BatchResult(
        result_id=str(uuid.uuid4()),
        sample_id=scan.sample_id,
        scan_ids=[scan.scan_id],
        beans=beans,
        measurements=measurements,
        grading=grading,
        agent_report=None,
        timings_s={k: round(v, 4) for k, v in timings.items()},
        pipeline_versions=pre_versions,
    )
    report: AgentReport = ag.explain(result, "zh")
    timings["agent"] = time.perf_counter() - t0
    result = result.model_copy(
        update={
            "agent_report": report,
            "timings_s": {k: round(v, 4) for k, v in timings.items()},
            "pipeline_versions": {**pre_versions, "agent": report.backend},
        }
    )

    # ---- passport（失败不吞结果：作业仍 done，护照阶段记入降级清单） -----
    t0 = time.perf_counter()
    passport: PassportReport | None = None
    passport_err = ""
    try:
        passport = build_passport(
            result,
            req.data_root / "reports" / result.result_id,
            langs=req.langs,
            crop_root=req.data_root,
        )
    except Exception as exc:  # 护照失败不阻塞结果查询
        passport_err = f"护照生成失败（{exc.__class__.__name__}: {exc}）"
    passport_s = time.perf_counter() - t0

    outcome = PipelineOutcome(
        result=result,
        passport=passport,
        scan=scan,
        degraded_stages=[*req.ingest_degraded.keys(), *components.degraded_stages()],
        degraded_reasons={**req.ingest_degraded, **components.degraded_reasons()},
        pairing_summary=pairing_summary,
        passport_runtime_s=passport_s,
    )
    if passport_err:
        outcome.degraded_reasons["passport"] = passport_err
        outcome.degraded_stages.append("passport")
    return outcome


# ---------------------------------------------------------------------------
# 证据裁剪 / 颜色 / 几何
# ---------------------------------------------------------------------------


def extract_mask_crop_rgba(
    warped_bgr: np.ndarray, mask: BeanMask, mm_per_px: float
) -> np.ndarray:
    """从正射盘面网格按掩码多边形裁出 RGBA（RGB 通道序 + alpha）证据图。

    正射网格是线性 mm 坐标系（``mm_per_px = tray_mm / grid_px``），掩码
    mm 多边形直接除以 ``mm_per_px`` 得网格像素坐标。
    """
    h, w = warped_bgr.shape[:2]
    x0, y0, x1, y1 = mask.bbox_mm
    px0 = max(0, int(np.floor(x0 / mm_per_px)) - 2)
    py0 = max(0, int(np.floor(y0 / mm_per_px)) - 2)
    px1 = min(w, int(np.ceil(x1 / mm_per_px)) + 2)
    py1 = min(h, int(np.ceil(y1 / mm_per_px)) + 2)
    if px1 - px0 < 2 or py1 - py0 < 2:
        px0, py0 = max(0, px0), max(0, py0)
        px1, py1 = min(w, px0 + 4), min(h, py0 + 4)
    patch = warped_bgr[py0:py1, px0:px1]
    poly = np.asarray(mask.polygon, dtype=np.float32) / float(mm_per_px)
    poly[:, 0] -= float(px0)
    poly[:, 1] -= float(py0)
    alpha = np.zeros(patch.shape[:2], dtype=np.uint8)
    cv2.fillPoly(alpha, [np.round(poly).astype(np.int32)], 255)
    rgb = cv2.cvtColor(patch, cv2.COLOR_BGR2RGB)
    return np.dstack([rgb, alpha])


def _masked_lab8(
    warped_bgr: np.ndarray, mask: BeanMask, mm_per_px: float
) -> tuple[float, float, float]:
    """掩码内均值 L*a*b*（lab8 标度：三通道 0-255，契约单一标度）。"""
    h, w = warped_bgr.shape[:2]
    x0, y0, x1, y1 = mask.bbox_mm
    px0 = max(0, int(np.floor(x0 / mm_per_px)))
    py0 = max(0, int(np.floor(y0 / mm_per_px)))
    px1 = min(w, int(np.ceil(x1 / mm_per_px)))
    py1 = min(h, int(np.ceil(y1 / mm_per_px)))
    patch = warped_bgr[py0:py1, px0:px1]
    if patch.size == 0:
        return (0.0, 128.0, 128.0)
    lab = cv2.cvtColor(patch, cv2.COLOR_BGR2Lab)
    poly = np.asarray(mask.polygon, dtype=np.float32) / float(mm_per_px)
    poly[:, 0] -= float(px0)
    poly[:, 1] -= float(py0)
    m = np.zeros(patch.shape[:2], dtype=np.uint8)
    cv2.fillPoly(m, [np.round(poly).astype(np.int32)], 1)
    if int(m.sum()) == 0:
        return (0.0, 128.0, 128.0)
    vals = lab[m > 0].astype(np.float64).mean(axis=0)
    return (float(vals[0]), float(vals[1]), float(vals[2]))


def _eq_diameter_mm(area_mm2: float) -> float:
    """面积等效直径（mm）；契约要求 >0，零面积给最小正下界。"""
    d = 2.0 * float(np.sqrt(max(float(area_mm2), 1e-9) / np.pi))
    return d if d > 0 else 1e-3


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _validate_cls_output(defect: str, conf: float, rank: int, tax: Taxonomy, mask_id: str) -> None:
    if not tax.is_valid_key(defect):
        raise PipelineStageError(
            "classify",
            f"分类实现输出未知类别 {defect!r}（mask={mask_id}）；合法类别: {tax.keys()}",
        )
    if not 0.0 <= float(conf) <= 1.0:
        raise PipelineStageError("classify", f"置信度越界 {conf}（mask={mask_id}）")
    if defect == "normal" and int(rank) != 0:
        raise PipelineStageError("classify", f"normal 的 severity_rank 必须=0（mask={mask_id}）")
    if defect != "normal" and int(rank) <= 0:
        raise PipelineStageError(
            "classify", f"缺陷类 {defect} 的 severity_rank 必须>0（mask={mask_id}）"
        )


def _pipeline_versions(components: Components, standard_id: str) -> dict[str, str]:
    return {
        "calibration": "aruco4:v1",
        "segment": components.segment.resolved_version("segment:v?"),
        "classify": components.classify.resolved_version("classify:v?"),
        "pairing": "hungarian:v1",
        "metrology": "measure:v1",
        "standard": standard_id,
        "report": "passport:v1",
    }
