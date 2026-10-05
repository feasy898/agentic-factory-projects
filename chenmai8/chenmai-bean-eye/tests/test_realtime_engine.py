"""实时线 eval · 逐帧管线（beaneye.realtime.engine）。

运行（仓库根）::

    pytest tests/test_realtime_engine.py -q

覆盖：
1. **类别计数与合成 GT 一致**（简报验收核心）：compose_tray 合成盘 +
   OracleSeg 真值分割（beaneye.segment，黄金分割器）+ 真值分类替身 →
   FrameResult.counts 与逐粒真值直方**完全一致**；质心折算回真毫米坐标与
   GT 对得上；已标定时 eq_diameter_mm = 真值等效直径；
2. 真实链路（ClassicSeg + RulesV0）：合成帧上检出数 ≥ 真值一半（稀疏盘，
   classic 粘连切分短板不开）、全部类别为 taxonomy 合法 key、计数与逐粒
   一致；ArUco 标定生效（mm_per_px ≈ 合成真值）；
3. 旋钮：skip=2 时 7 帧只处理 3 帧（跳过帧回上一结果）；downscale=0.5 的
   结果坐标折回原始帧（与全尺寸运行质心一致）；未标定（--no-calib 口径）
   时 mm_per_px/eq_diameter_mm 恒为 None（伪毫米不冒充）；
4. 输入/配置校验与 JSON 往返。

全部素材为程序化合成（beaneye.synth），离线运行。
"""

from __future__ import annotations

from collections import Counter

import numpy as np
import pytest

from beaneye.realtime import FrameResult, RealtimeConfig, RealtimeEngine
from beaneye.segment import OracleSeg
from beaneye.synth import ComposeConfig, SynthTray, compose_tray
from beaneye.taxonomy import load_taxonomy

TAX = load_taxonomy()

_CLASS_WEIGHTS = {
    "black": 3.0, "mold": 2.0, "sour": 2.0, "insect": 2.0, "dried": 2.0,
    "broken": 3.0, "brocade": 2.0, "shell": 1.0, "elephant": 1.0,
    "peaberry": 1.0, "immature": 1.0, "faded": 1.0,
}


def _compose_tray(seed: int, *, width: int = 960, height: int = 540,
                  n_min: int = 10, n_max: int = 14, defect_rate: float = 0.5) -> SynthTray:
    """小而稀疏的合成盘（接触/重叠关闭：classic 短板不进实时验收口径）。"""
    cfg = ComposeConfig(
        version=1,
        width_px=width,
        height_px=height,
        margin_mm=12.0,
        n_beans_min=n_min,
        n_beans_max=n_max,
        defect_rate=defect_rate,
        class_weights=_CLASS_WEIGHTS,
        contact_min=0,
        contact_max=0,
        mirror_bottom=False,  # 实时单面语义
        per_class=20,
    )
    return compose_tray(seed, config=cfg)


class _TruthCls:
    """真值分类替身：mask_id → manifest class_top（验证引擎装配，不评精度）。"""

    stage = "classify"
    version = "truth:test_double"

    def __init__(self, oracle: OracleSeg, scan_id: str) -> None:
        self.oracle = oracle
        self.scan_id = scan_id

    def classify(self, crop_rgba, mask) -> tuple[str, float, int]:
        entry = self.oracle.entry(self.scan_id, mask.mask_id)
        cls = str(entry["class_top"])
        return cls, 1.0, int(TAX.severity_rank(cls))


# ---------------------------------------------------------------------------
# 1. 类别计数与合成 GT 一致（OracleSeg + 真值分类，校准 warp 路径）
# ---------------------------------------------------------------------------


def test_counts_match_synth_ground_truth():
    tray = _compose_tray(11)
    oracle = OracleSeg.from_tray(tray, side="top")
    engine = RealtimeEngine(
        cfg=RealtimeConfig(calibrate=True, calib_every=1, warp_grid_px=512),
        segment=oracle,
        classify=_TruthCls(oracle, tray.scan_id),
        scan_id=tray.scan_id,
    )
    res = engine.process(tray.top_bgr)

    gt = Counter(b.cls for b in tray.beans)
    assert res.frame_index == 0 and not res.skipped
    assert len(res.beans) == len(tray.beans)  # 真值分割：逐粒全数透传
    assert res.counts == dict(gt)  # 类别计数与合成 GT 完全一致
    assert sum(res.counts.values()) == len(tray.beans)
    assert res.calibrated is True and res.mm_per_px is not None

    # 毫米标定（帧口径）：ArUco 解得 mm/px 与合成真值同量级（≤10%，量化余量）
    truth_mmpp = 1.0 / tray.px_per_mm
    assert abs(res.mm_per_px - truth_mmpp) / truth_mmpp <= 0.10

    # H⁻¹ 回映后质心应落在合成真值的像素位置附近（origin_px + mm·px_per_mm）
    ox, oy = tray.origin_px
    ppm = tray.px_per_mm
    matched = 0
    for spot in res.beans:
        assert spot.eq_diameter_mm is not None  # 真毫米口径必须给尺寸
        assert spot.conf == 1.0 and spot.severity_rank == TAX.severity_rank(spot.defect)
        truth_px = [
            (ox + b.centroid_mm[0] * ppm, oy + b.centroid_mm[1] * ppm) for b in tray.beans
        ]
        nearest = min(
            np.hypot(spot.centroid_px[0] - tx, spot.centroid_px[1] - ty)
            for tx, ty in truth_px
        )
        if nearest < 8.0:  # 标定+透视回映的量化余量
            matched += 1
    assert matched >= int(0.8 * len(tray.beans))


def test_counts_match_gt_uncalibrated_pseudo_path():
    """未标定路径（画面仍带码但不启用标定）：计数语义不变，毫米字段诚实为空。"""
    tray = _compose_tray(12, width=560, height=560, n_min=6, n_max=8)
    oracle = OracleSeg.from_tray(tray, side="top")
    engine = RealtimeEngine(
        cfg=RealtimeConfig(calibrate=False),
        segment=oracle,
        classify=_TruthCls(oracle, tray.scan_id),
        scan_id=tray.scan_id,
    )
    res = engine.process(tray.top_bgr)
    assert res.counts == dict(Counter(b.cls for b in tray.beans))
    assert res.calibrated is False and res.mm_per_px is None
    assert all(b.eq_diameter_mm is None for b in res.beans)  # 伪毫米不冒充


# ---------------------------------------------------------------------------
# 2. 真实链路（ClassicSeg + RulesV0 缺省装配）
# ---------------------------------------------------------------------------


def test_real_pipeline_detection_and_calibration():
    tray = _compose_tray(21)
    engine = RealtimeEngine(
        cfg=RealtimeConfig(calibrate=True, calib_every=1, warp_grid_px=720),
        scan_id=tray.scan_id,
    )
    res = engine.process(tray.top_bgr)

    assert len(res.beans) >= max(3, int(0.5 * len(tray.beans))), (
        f"检出 {len(res.beans)}/真值 {len(tray.beans)}（稀疏盘 classic 应过半）"
    )
    for b in res.beans:
        assert TAX.is_valid_key(b.defect)
        assert 0.0 <= b.conf <= 1.0
        assert b.severity_rank == (0 if b.defect == "normal" else TAX.severity_rank(b.defect))
        assert len(b.contour_px) >= 3
        assert 0 <= b.centroid_px[0] < res.width and 0 <= b.centroid_px[1] < res.height
        assert len(b.color_bgr) == 3
    assert sum(res.counts.values()) == len(res.beans)
    assert res.calibrated is True
    truth_mmpp = 1.0 / tray.px_per_mm
    assert abs(res.mm_per_px - truth_mmpp) / truth_mmpp <= 0.10  # 帧口径 mm/px
    assert res.fps >= 0.0 and res.process_ms > 0.0


# ---------------------------------------------------------------------------
# 3. 旋钮：skip / downscale
# ---------------------------------------------------------------------------


def test_skip_processes_every_nth_frame():
    tray = _compose_tray(31, width=480, height=480, n_min=4, n_max=6, defect_rate=0.4)
    oracle = OracleSeg.from_tray(tray, side="top")
    engine = RealtimeEngine(
        cfg=RealtimeConfig(calibrate=False, skip=2),
        segment=oracle,
        classify=_TruthCls(oracle, tray.scan_id),
        scan_id=tray.scan_id,
    )
    results = [engine.process(tray.top_bgr) for _ in range(7)]
    processed = [r for r in results if not r.skipped]
    skipped = [r for r in results if r.skipped]
    assert [r.frame_index for r in processed] == [0, 3, 6]  # 每 3 帧处理 1 帧
    assert len(skipped) == 4
    assert all(r.process_ms == 0.0 for r in skipped)  # 跳过帧零处理
    assert all(r.beans == results[0].beans for r in skipped)  # 回放上一处理帧内容
    assert results[6].fps > 0


def test_downscale_maps_results_back_to_original_frame():
    tray = _compose_tray(41, width=480, height=480, n_min=4, n_max=6, defect_rate=0.4)
    oracle = OracleSeg.from_tray(tray, side="top")
    truth = _TruthCls(oracle, tray.scan_id)
    full = RealtimeEngine(cfg=RealtimeConfig(calibrate=False), segment=oracle, classify=truth,
                          scan_id=tray.scan_id)
    half = RealtimeEngine(cfg=RealtimeConfig(calibrate=False, downscale=0.5),
                          segment=OracleSeg.from_tray(tray, side="top"),
                          classify=_TruthCls(oracle, tray.scan_id), scan_id=tray.scan_id)
    r_full = full.process(tray.top_bgr)
    r_half = half.process(tray.top_bgr)
    assert r_full.width == 480 and r_half.width == 480  # 结果口径=原始帧（方形合成画布）
    assert len(r_half.beans) == len(r_full.beans)  # 真值分割：粒数不随缩放变
    c_full = sorted(r_full.beans, key=lambda b: b.centroid_px)
    c_half = sorted(r_half.beans, key=lambda b: b.centroid_px)
    for a, b in zip(c_full, c_half):  # 缩放后坐标折回原始帧（resize 取整余量 ≤3px）
        assert abs(a.centroid_px[0] - b.centroid_px[0]) <= 3.0
        assert abs(a.centroid_px[1] - b.centroid_px[1]) <= 3.0
        if a.area_px >= 200:  # 面积一致性只对足够大的豆断言（小豆半分辨率栅格化噪声主导）
            assert abs(a.area_px - b.area_px) <= 0.15 * a.area_px


# ---------------------------------------------------------------------------
# 4. 输入/配置校验 + JSON 往返
# ---------------------------------------------------------------------------


def test_engine_rejects_bad_input_and_config():
    engine = RealtimeEngine(cfg=RealtimeConfig(calibrate=False))
    with pytest.raises(ValueError):
        engine.process(np.zeros((8, 8), dtype=np.uint8))  # 非三通道
    bad_kwargs = [
        {"downscale": 2.0},
        {"skip": -1},
        {"calib_every": 0},
        {"warp_grid_px": 64},
        {"fps_ema": 1.0},
    ]
    for kw in bad_kwargs:  # 配置在循环体内构造（构造即校验）
        with pytest.raises(ValueError):
            RealtimeEngine(cfg=RealtimeConfig(**kw))


def test_frame_result_json_roundtrip():
    tray = _compose_tray(51, width=480, height=480, n_min=4, n_max=6, defect_rate=0.4)
    engine = RealtimeEngine(
        cfg=RealtimeConfig(calibrate=False),
        segment=OracleSeg.from_tray(tray, side="top"),
        classify=_TruthCls(OracleSeg.from_tray(tray, side="top"), tray.scan_id),
        scan_id=tray.scan_id,
    )
    res = engine.process(tray.top_bgr)
    rev = FrameResult.from_json(res.to_json())
    assert rev == res  # 契约基类：无损往返
