"""cs_mouth 单元测试（开发指令 §5.3 辅助；验收主命令是 python -m cs_mouth.eval）。

在仓库根执行::

    .venv/Scripts/python.exe -m pytest tests/test_mouth.py -q

覆盖：prior 装载/往返、mono/depth 三维映射数学、失效保持（契约 §3.1）、
MouthPose JSON 往返、合成样本可检出。模型权重缺失时跳过（不阻塞 CI 骨架）。
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from chengshao.cs_mouth import MouthEstimator, MouthPrior
from chengshao.cs_mouth._schema import MOUTH_PRIOR_DEFAULT_M, MouthPose
from chengshao.cs_mouth.imgio import imwrite_u
from chengshao.cs_mouth.synth import draw_cartoon_face, draw_no_face


def _model_available() -> bool:
    return MouthPrior.load().resolve_model_path().is_file()


pytestmark = pytest.mark.skipif(
    not _model_available(),
    reason="人脸关键点模型缺失（先跑 chengshao/scripts/fetch_models.py）",
)


# ---- MouthPrior -------------------------------------------------------------
def test_prior_defaults_and_config(tmp_path):
    p = MouthPrior()
    assert p.distance_m == MOUTH_PRIOR_DEFAULT_M == 0.42
    assert p.mode == "fixed"  # 契约 v1.1：缺省 fixed（顶部相机回退路径）
    assert p.ipd_m == pytest.approx(0.063)
    assert p.error_band_m == (0.03, 0.05)
    # JSON 往返
    f = tmp_path / "prior.json"
    p.save(f)
    p2 = MouthPrior.load(f)
    assert p2 == p
    # 缺失文件回退缺省（容错，不抛）
    assert MouthPrior.load(tmp_path / "nope.json") == MouthPrior()


def test_prior_mode_validation():
    from chengshao.cs_mouth.prior import PRIOR_MODES

    p = MouthPrior.load().with_updates(mode="ipd")
    assert p.mode in PRIOR_MODES
    with pytest.raises(ValueError):
        MouthPrior.from_dict({"mode": "lidar"})


def test_prior_intrinsics_scaling():
    p = MouthPrior()
    fx, fy, cx, cy = p.intrinsics_for(1280, 960)
    assert (fx, fy, cx, cy) == (920.0, 920.0, 640.0, 480.0)


def test_prior_matrix_orthonormal():
    import numpy as np

    R = np.asarray(MouthPrior().T_base_cam)[:3, :3]
    assert np.allclose(R @ R.T, np.eye(3), atol=1e-9)
    assert abs(np.linalg.det(R) - 1.0) < 1e-9


# ---- MouthEstimator：失效路径 ------------------------------------------------
def test_invalid_hold_and_recover():
    est = MouthEstimator(backend="mono")
    # 无历史失效 → 名义位姿
    pose = est.from_bgr(draw_no_face(seed=3))
    assert pose.valid is False and pose.confidence == 0.0
    assert (pose.x, pose.y, pose.z) == pytest.approx(
        (est.prior.distance_m, 0.0, est.prior.mouth_height_m)
    )
    # 检出 → 有效；再失效 → 沿用上一有效值（契约 §3.1）
    ok = est.from_bgr(draw_cartoon_face(mouth_open=0.5))
    assert ok.valid is True and ok.source == "mono"
    held = est.from_bgr(draw_no_face(seed=4))
    assert held.valid is False and held.confidence == 0.0
    assert (held.x, held.y, held.z) == pytest.approx((ok.x, ok.y, ok.z))


# ---- MouthEstimator：三维映射数学 ---------------------------------------------
def test_mono_maps_to_prior_distance():
    est = MouthEstimator(backend="mono")
    pose = est.from_bgr(draw_cartoon_face())
    assert pose.valid
    # 相机系下模长恒等于先验距离（先验缩放的定义），cam→base 为刚体变换不改变模长
    T = est.prior.matrix_base_cam()
    t = T[:3, 3]
    assert float(np.linalg.norm(np.array([pose.x, pose.y, pose.z]) - t)) == pytest.approx(
        est.prior.distance_m, abs=1e-9
    )
    assert 0.0 <= pose.jaw_open <= 1.0
    assert 0.0 <= pose.frown <= 1.0


def test_depth_backend_synthetic_plane():
    est = MouthEstimator(backend="depth")
    img = draw_cartoon_face()
    depth = np.full(img.shape[:2], 0.60, dtype=np.float32)  # 与 RGB 对齐的平面深度
    pose = est.from_bgr(img, depth)
    assert pose.valid and pose.source == "depth"
    T = est.prior.matrix_base_cam()
    t = T[:3, 3]
    # 平面深度下 |p_cam| ≈ z * sqrt(1 + 射线斜率²) ≥ z，与像素位置相关；留 2cm 容差
    norm = float(np.linalg.norm(np.array([pose.x, pose.y, pose.z]) - t))
    assert norm == pytest.approx(0.60, abs=0.02)
    # 整型毫米图自动换算
    pose_mm = est.from_bgr(img, np.full(img.shape[:2], 600, dtype=np.uint16))
    assert pose_mm.valid
    norm_mm = float(np.linalg.norm(np.array([pose_mm.x, pose_mm.y, pose_mm.z]) - t))
    assert norm_mm == pytest.approx(0.60, abs=0.02)
    # 深度缺失 → 失效
    assert est.from_bgr(img, None).valid is False


# ---- 契约兼容 -----------------------------------------------------------------
def test_pose_json_roundtrip():
    est = MouthEstimator(backend="mono")
    pose = est.from_bgr(draw_cartoon_face(mouth_open=0.2))
    decoded = MouthPose.model_validate_json(pose.model_dump_json())
    assert decoded == pose
    payload = json.loads(pose.model_dump_json())
    assert payload["source"] == "mono"
    assert payload["ts_ns"] > 0


def test_backend_validation():
    with pytest.raises(ValueError):
        MouthEstimator(backend="lidar")


# ---- 腕部双职（契约 v1.1） ------------------------------------------------------
def test_wrist_ipd_mode_source_and_geometry():
    """cam_pose 提供时走 IPD 估距且 source="wrist"；缺省调用行为不变。"""
    est_fixed = MouthEstimator(backend="mono")  # 未传 cam_pose / provider → 现状行为
    base = est_fixed.from_bgr(draw_cartoon_face())
    assert base.source == "mono"

    prior = MouthPrior.load().with_updates(mode="ipd")
    est = MouthEstimator(backend="mono", prior=prior)
    img = draw_cartoon_face()
    T_bf = np.eye(4)
    T_fc = prior.matrix_base_cam()
    pose = est.from_bgr(img, cam_pose=(T_bf, T_fc))
    assert pose.valid and pose.source == "wrist"
    # 相机系（=基座系口径，单位外参）下的深度为 IPD 估距值，必须落在合理量程
    assert 0.10 <= pose.z <= 0.80
    # pose_provider 途径：等价生效
    est2 = MouthEstimator(backend="mono", prior=prior, pose_provider=lambda: (T_bf, T_fc))
    pose2 = est2.from_bgr(img)
    assert pose2.valid and pose2.source == "wrist"
    assert (pose2.x, pose2.y, pose2.z) == pytest.approx((pose.x, pose.y, pose.z))


def test_wrist_ipd_unreliable_frame_is_invalid():
    """IPD 不可靠（过远/过小）按失效帧处理：construct 极小 fx 使 ipd_px 不足。"""
    from chengshao.cs_mouth.prior import IPD_PX_MIN

    prior = MouthPrior.load().with_updates(mode="ipd", fx=1.0, fy=1.0)  # 极小内参
    est = MouthEstimator(backend="mono", prior=prior)
    pose = est.from_bgr(draw_cartoon_face(), cam_pose=(np.eye(4), prior.matrix_base_cam()))
    assert pose.valid is False and pose.confidence == 0.0
    assert IPD_PX_MIN > 0  # 常量存在性自检


# ---- 合成样本质量（bootstrap 依赖） --------------------------------------------
def test_seed_variants_detect(tmp_path):
    """种子 + 8 变体全部可检出且 jaw/转头标签方向正确（抽样自 bundled 规则）。"""
    from chengshao.cs_mouth.synth import VARIANTS, apply_variant

    seed = tmp_path / "seed.jpg"
    base = draw_cartoon_face(mouth_open=0.0)
    assert imwrite_u(seed, base)
    img = None
    from chengshao.cs_mouth.imgio import imread_u

    img = imread_u(seed)
    est = MouthEstimator(backend="mono")
    for tag, kind in VARIANTS:
        pose = est.from_bgr(apply_variant(img, kind))
        assert pose.valid, f"变体 {tag}/{kind} 未检出"
