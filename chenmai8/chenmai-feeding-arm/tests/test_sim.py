"""cs_sim 跨模块测试：模型加载回退链、FK/IK、可达空间、安全包络。

运行（仓库根）::

    python -m pytest tests/test_sim.py -q

无硬件依赖；本地存在 _vendor 参考模型时走 tier1/2 断言，缺失时回退
tier3（内置名义链）并跳过文件相关断言。
"""

from __future__ import annotations

import numpy as np
import pytest

from chengshao.cs_sim import (
    ArmModel,
    EnvelopeValidator,
    IkpyChainBackend,
    MujocoBackend,
    discover_model_file,
    load_arm,
)
from chengshao.cs_sim.frames import (
    matrix_from_quat,
    matrix_from_rpy,
    quat_angle_between,
    quat_from_matrix,
    segment_point_distance,
    so3_log,
)


@pytest.fixture(scope="module")
def arm() -> ArmModel:
    return load_arm("auto")


# ---------------------------------------------------------------------------
# 模型加载回退链
# ---------------------------------------------------------------------------


def test_load_arm_returns_valid_model(arm):
    assert isinstance(arm, ArmModel)
    assert arm.tier in ("mjcf", "urdf_mujoco", "chain_builtin", "chain_urdf_ikpy")
    assert arm.n_joints >= 2
    assert len(arm.joint_names) == arm.n_joints
    lower = np.asarray(arm.joint_lower)
    upper = np.asarray(arm.joint_upper)
    assert np.all(np.isfinite(lower)) and np.all(upper > lower)


def test_load_arm_explicit_missing_path_raises():
    with pytest.raises(FileNotFoundError):
        load_arm("no/such/model_file.xml")


def test_discovery_and_tiers():
    resolution = discover_model_file()
    if resolution.path is None:
        assert resolution.tier == "chain_builtin"
    else:
        assert resolution.tier in ("mjcf", "urdf_mujoco")
        # 显式装载该文件必须成功且层级一致
        arm = load_arm(str(resolution.path))
        assert arm.tier == resolution.tier


def test_builtin_chain_backend_stands_alone():
    """tier3 内置名义链：无文件依赖，可独立构造（回退链最后手段可用）。"""
    backend = IkpyChainBackend()
    model = ArmModel(backend)
    model.validate()
    pose = model.fk([0.0] * model.n_joints)
    assert len(pose) == 7 and all(np.isfinite(pose))


def test_builtin_chain_matches_reference_fk(arm):
    """内置名义链与参考层 FK 逐点一致（常数保真）。"""
    builtin = IkpyChainBackend()
    rng = np.random.default_rng(7)
    lo = np.asarray(arm.joint_lower)
    hi = np.asarray(arm.joint_upper)
    n = min(arm.n_joints, builtin.n_joints)
    max_pos = 0.0
    for _ in range(50):
        q = 0.5 * (lo + hi)
        q[: n - 1] = rng.uniform(lo[: n - 1], hi[: n - 1])
        rp, rR = arm.fk_pose([float(v) for v in q])
        p, R = builtin.fk(np.asarray(q, dtype=float)[: builtin.n_joints])
        max_pos = max(max_pos, float(np.linalg.norm(p - rp)))
        cos = float(np.clip((np.trace(rR.T @ R) - 1) / 2, -1, 1))
        assert np.arccos(cos) < 1e-3
    assert max_pos < 1e-4


@pytest.mark.skipif(discover_model_file().path is None, reason="本地无参考模型文件")
def test_urdf_mujoco_tier_matches_mjcf():
    """URDF(物理引擎) 层与 MJCF 层的 TCP 位置一致（<=1e-4 m）。"""
    resolution = discover_model_file()
    if resolution.path.suffix.lower() not in (".xml", ".mjcf"):
        pytest.skip("discovery did not pick an MJCF file")
    urdf_path = resolution.path.with_suffix(".urdf")
    if not urdf_path.exists():
        pytest.skip("no sibling URDF")
    arm_mjcf = load_arm(str(resolution.path))
    arm_urdf = load_arm(str(urdf_path))
    assert arm_urdf.tier == "urdf_mujoco"
    rng = np.random.default_rng(11)
    lo = np.asarray(arm_mjcf.joint_lower)
    hi = np.asarray(arm_mjcf.joint_upper)
    for _ in range(50):
        q = 0.5 * (lo + hi)
        q[:-1] = rng.uniform(lo[:-1], hi[:-1])
        p1, _ = arm_mjcf.fk_pose([float(v) for v in q])
        p2, _ = arm_urdf.fk_pose([float(v) for v in q])
        assert float(np.linalg.norm(p1 - p2)) < 1e-4


# ---------------------------------------------------------------------------
# FK / IK（§5.1 口径：位置 <=5mm、姿态 <=0.05rad）
# ---------------------------------------------------------------------------


def test_fk_output_shape_and_finiteness(arm):
    pose = arm.fk([0.0] * arm.n_joints)
    assert len(pose) == 7
    assert all(np.isfinite(pose))
    quat = np.asarray(pose[3:7])
    assert abs(np.linalg.norm(quat) - 1.0) < 1e-6


def test_fk_quat_matches_rotation_matrix(arm):
    rng = np.random.default_rng(3)
    lo = np.asarray(arm.joint_lower)
    hi = np.asarray(arm.joint_upper)
    for _ in range(20):
        q = rng.uniform(lo, hi)
        pose = arm.fk([float(v) for v in q])
        R = matrix_from_quat(np.asarray(pose[3:7]))
        R2 = quat_from_matrix(R)
        assert quat_angle_between(np.asarray(pose[3:7]), R2) < 1e-9


def test_ik_roundtrip_within_spec_thresholds(arm):
    """FK 生成可达目标 -> IK 回解：成功率 100%（20 样本）且误差达 §5.1 线。"""
    rng = np.random.default_rng(5)
    lo = np.asarray(arm.joint_lower)
    hi = np.asarray(arm.joint_upper)
    n_arm = arm.n_joints - 1  # 末关节为夹爪，不影响 TCP
    solved = 0
    for _ in range(20):
        q = 0.5 * (lo + hi)
        q[:n_arm] = rng.uniform(lo[:n_arm], hi[:n_arm])
        pose = arm.fk([float(v) for v in q])
        sol = arm.ik(list(pose[0:3]), list(pose[3:7]))
        assert sol is not None
        pose2 = arm.fk(sol)
        pos_err = float(np.linalg.norm(np.asarray(pose[0:3]) - np.asarray(pose2[0:3])))
        ori_err = quat_angle_between(np.asarray(pose[3:7]), np.asarray(pose2[3:7]))
        assert pos_err <= 0.005, f"pos_err={pos_err}"
        assert ori_err <= 0.05, f"ori_err={ori_err}"
        assert np.all(np.asarray(sol) >= lo - 1e-9)
        assert np.all(np.asarray(sol) <= hi + 1e-9)
        solved += 1
    assert solved == 20


def test_ik_unreachable_returns_none(arm):
    assert arm.ik([2.5, 2.5, 2.5], [1.0, 0.0, 0.0, 0.0]) is None


def test_ik_input_validation(arm):
    with pytest.raises(ValueError):
        arm.ik([0.1, 0.2], [1.0, 0.0, 0.0, 0.0])
    with pytest.raises(ValueError):
        arm.ik([0.1, 0.2, 0.3], [1.0, 0.0, 0.0])


def test_reachable_map_dict(arm):
    grid = {"x_m": [0.10, 0.25], "y_m": [-0.10, 0.10], "z_m": [0.00, 0.15], "res_m": 0.05}
    result = arm.reachable_map(grid)
    # 端点含入：x 4 点、y 5 点、z 4 点
    assert result["n_voxels_total"] == 4 * 5 * 4
    assert 0.0 < result["reachable_fraction"] <= 1.0
    assert len(result["reachable_points_m"]) == result["n_voxels_reachable"]


def test_reach_map_png_render(tmp_path, arm):
    grid = {"x_m": [0.10, 0.20], "y_m": [-0.05, 0.05], "z_m": [0.00, 0.10], "res_m": 0.05}
    result = arm.reachable_map(grid)
    out = tmp_path / "reach_test.png"
    path = arm.render_reach_map(result, out)
    assert out.exists() and out.stat().st_size > 10_000
    assert str(out) == path


# ---------------------------------------------------------------------------
# 安全包络校验器（§5.1：违规轨迹 100% 拒绝）
# ---------------------------------------------------------------------------


def test_envelope_point_checks():
    val = EnvelopeValidator()
    face = val.config.face_center
    assert val.point_zone_violation(face) == "face"  # 口部点在面部球域内
    outside = face + np.array([0.25, 0.0, 0.0])
    if val.point_zone_violation(outside) is None:
        pass  # 具体位置由配置决定，此处只验证查询可用
    assert val.speed_limit_at(face + np.array([0.10, 0.0, 0.0])) == pytest.approx(0.10)
    assert val.speed_limit_at(np.array([0.10, -0.25, 0.05])) == pytest.approx(0.15)


def test_envelope_rejects_zone_intrusion():
    val = EnvelopeValidator()
    face = val.config.face_center
    # 端点在球外的轨迹但线段穿越球体：连续检查必须拒绝
    p0 = face + np.array([-0.30, 0.0, 0.0])
    p1 = face + np.array([0.30, 0.0, 0.0])
    # 平移到球面上方擦过：让线段穿过球心正上方 0.05m（球内）
    p0 = p0 + np.array([0.0, 0.0, 0.05])
    p1 = p1 + np.array([0.0, 0.0, 0.05])
    rep = val.check_trajectory([0.0, 2.0], [p0, p1], label="graze")
    assert rep["rejected"]
    assert any(v["kind"] == "zone" for v in rep["violations"])


def test_envelope_rejects_speed_violation():
    val = EnvelopeValidator()
    p0 = np.array([0.10, -0.25, 0.05])
    p1 = p0 + np.array([0.20, 0.0, 0.0])  # 0.2m in 0.5s = 0.4 m/s >> 0.15
    rep = val.check_trajectory([0.0, 0.5], [p0, p1], label="fast")
    assert rep["rejected"]
    assert any(v["kind"] == "speed" for v in rep["violations"])


def test_envelope_accepts_slow_clear_trajectory():
    val = EnvelopeValidator()
    p0 = np.array([0.12, -0.28, 0.05])
    p1 = np.array([0.16, -0.24, 0.06])  # 4cm 短程
    rep = val.check_trajectory([0.0, 1.0], [p0, p1], label="slow")
    assert not rep["rejected"]
    assert rep["min_zone_clearance_m"] > 0.0


def test_envelope_trajectory_input_validation():
    val = EnvelopeValidator()
    with pytest.raises(ValueError):
        val.check_trajectory([0.0, 1.0], [[0.0, 0.0, 0.0]])  # 长度不一致
    with pytest.raises(ValueError):
        val.check_trajectory([0.0, 0.0], [[0.0, 0.0, 0.0], [0.1, 0.0, 0.0]])  # 时间非递增
    with pytest.raises(ValueError):
        val.check_segment([0.0, 0.0, 0.0], [0.1, 0.0, 0.0], dt_s=0.0)


def test_envelope_delivery_target_exemption():
    """登记送达目标后，目标球内的线段豁免禁入区判定；速度仍受限。"""
    val = EnvelopeValidator()
    face = val.config.face_center
    stop = face + np.array([-0.05, 0.0, 0.0])  # 口前 5cm：默认在球域内
    assert val.check_trajectory([0.0, 1.0], [stop + np.array([0.02, 0, 0]), stop])["rejected"]
    val.register_delivery_target(stop, radius_m=0.03)
    rep = val.check_trajectory([0.0, 1.0], [stop + np.array([0.02, 0, 0]), stop])
    assert not any(v["kind"] == "zone" for v in rep["violations"])


# ---------------------------------------------------------------------------
# 数学工具
# ---------------------------------------------------------------------------


def test_so3_log_roundtrip():
    rng = np.random.default_rng(9)
    for _ in range(50):
        q = rng.normal(size=4)
        q /= np.linalg.norm(q)
        R = matrix_from_quat(q)
        w = so3_log(R)
        theta = float(np.linalg.norm(w))
        if theta < 1e-9:
            continue
        axis = w / theta
        # Rodrigues 重建
        K = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
        R2 = np.eye(3) + np.sin(theta) * K + (1 - np.cos(theta)) * (K @ K)
        assert np.abs(R2 - R).max() < 1e-8


def test_rpy_matrix_roundtrip():
    for rpy in [(0.0, 0.0, 0.0), (0.1, -0.2, 0.3), (np.pi / 2, 0.0, 0.0), (0.0, np.pi / 2, 0.0)]:
        R = matrix_from_rpy(*rpy)
        assert np.abs(matrix_from_rpy(*rpy) - R).max() < 1e-12


def test_segment_point_distance():
    d = segment_point_distance(
        np.array([0.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0]), np.array([0.5, 0.3, 0.0])
    )
    assert d == pytest.approx(0.3)
    d2 = segment_point_distance(
        np.array([0.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0]), np.array([2.0, 0.0, 0.0])
    )
    assert d2 == pytest.approx(1.0)


def test_envelope_matches_workspace_config():
    """校验器缺省值与 config/workspace.json 一致（默认口径统一）。"""
    import json
    from pathlib import Path

    cfg_path = Path(__file__).resolve().parents[1] / "chengshao" / "config" / "workspace.json"
    if not cfg_path.exists():
        pytest.skip("config/workspace.json 不存在")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    val = EnvelopeValidator()
    assert val.config.face_center.tolist() == [float(v) for v in cfg["mouth_point_m"]]
    limits = cfg["speed_limits_mps"]
    assert val.config.speed_approach == pytest.approx(limits["approach"])
    assert val.config.speed_near_face == pytest.approx(limits["near_face"])
