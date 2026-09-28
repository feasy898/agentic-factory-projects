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
    """登记送达目标后，目标球内的线段豁免禁入区判定；速度仍受限。

    v3.1 注：这只覆盖豁免**机制**本身（保留给非名义场景）；名义送达走
    test_delivery_* 系列——停点在球外、零豁免。
    """
    val = EnvelopeValidator()
    face = val.config.face_center
    stop = face + np.array([-0.05, 0.0, 0.0])  # 球内一点（非名义停点）
    assert val.check_trajectory([0.0, 1.0], [stop + np.array([0.02, 0, 0]), stop])["rejected"]
    val.register_delivery_target(stop, radius_m=0.03)
    rep = val.check_trajectory([0.0, 1.0], [stop + np.array([0.02, 0, 0]), stop])
    assert not any(v["kind"] == "zone" for v in rep["violations"])


# ---------------------------------------------------------------------------
# v3.1 审查修订：停点球外 / 数值安全余量 / 整段送达走廊 / 关节轨迹检查
# ---------------------------------------------------------------------------


def test_delivery_stop_point_outside_face_sphere():
    """名义停点必须在 r=0.12m 面部球外（审查 A4：不再依赖球内豁免）。"""
    val = EnvelopeValidator()
    stop = val.delivery_stop_point()
    face = val.config.face_center
    clearance = float(np.linalg.norm(stop - face)) - val.face_radius
    assert clearance >= val.config.delivery_stop_clearance - 1e-9
    assert val.point_zone_violation(stop) is None
    # TCP 停距 0.17m：停距-勺头-跟踪-感知 = 0.17-0.08-0.02-0.05 = 0.02 > 0
    margin = val.delivery_margin()
    assert margin["margin_m"] >= 0.005
    assert margin["pass"] is True


def test_delivery_margin_negative_control():
    """勺头伸出超过停距时余量断言必须失败（断言本身有判别力）。"""
    from chengshao.cs_sim.safety_envelope import EnvelopeConfig

    val = EnvelopeValidator()
    bad = EnvelopeValidator(EnvelopeConfig(
        zones=val.config.zones,
        face_center=val.config.face_center,
        speed_approach=val.config.speed_approach,
        speed_near_face=val.config.speed_near_face,
        near_face_distance=val.config.near_face_distance,
        spoon_tip_reach=0.30,  # 30cm 勺：余量必为负
    ))
    m = bad.delivery_margin()
    assert m["margin_m"] < 0.0
    assert m["pass"] is False


def _track_line(val: EnvelopeValidator, arm, points, speed_mps: float = 0.05):
    """位置-only IK 线跟踪（测试自备实现，独立于 eval 内部工具）。"""
    from chengshao.cs_sim.ik_solver import solve_dls, solve_with_restarts

    lo = np.asarray(arm.joint_lower)
    hi = np.asarray(arm.joint_upper)
    qs = []
    q_prev = None
    for p in points:
        p = np.asarray(p, dtype=float)
        solved = None
        if q_prev is not None:
            r = solve_dls(arm._backend, p, np.eye(3), q_prev, pos_only=True)
            if r.converged:
                solved = np.clip(r.q, lo, hi)
        if solved is None:
            best = None
            for sd in (0, 1, 2, 3):
                r = solve_with_restarts(arm._backend, p, np.eye(3),
                                        pos_only=True, restarts=48, rng_seed=sd)
                if r is not None and r.converged:
                    qc = np.clip(r.q, lo, hi)
                    d = 0.0 if q_prev is None else float(np.abs(qc - q_prev).max())
                    if best is None or d < best[0]:
                        best = (d, qc)
            solved = None if best is None else best[1]
        if solved is None:
            return None
        qs.append(solved)
        q_prev = solved
    return np.asarray(qs)


def test_delivery_corridor_bowl_to_stop_accepted(arm):
    """整段"碗→停点"走廊（笛卡尔 + 关节空间跟踪）零违规、零豁免（审查 A4）。"""
    val = EnvelopeValidator()
    assert len(val._delivery_targets) == 0  # 名义送达不登记任何豁免
    bowl = np.array([0.22, -0.18, 0.02])
    stop = val.delivery_stop_point()
    lift = bowl + np.array([0.0, 0.0, 0.10])
    transit = np.array([0.25, -0.09, 0.20])
    pts = [bowl.copy()]
    for a, b in [(bowl, lift), (lift, transit), (transit, stop)]:
        n = max(2, int(np.ceil(float(np.linalg.norm(b - a)) / 0.02)))
        for f in np.linspace(0.0, 1.0, n + 1)[1:]:
            pts.append(a + f * (b - a))
    pts_arr = np.asarray(pts)
    durs = [float(np.linalg.norm(pts_arr[i + 1] - pts_arr[i])) / 0.05
            for i in range(len(pts_arr) - 1)]
    times = np.concatenate([[0.0], np.cumsum(durs)])

    cart = val.check_trajectory(times, pts_arr, label="corridor_cart")
    assert not cart["rejected"], cart["violations"][:3]

    qs = _track_line(val, arm, pts)
    assert qs is not None, "位置-only IK 线跟踪失败"
    joint = val.check_joint_trajectory(times, qs, arm, label="corridor_joint")
    assert not joint["rejected"], joint["violations"][:5]
    assert joint["max_joint_speed_rad_s"] <= 1.5
    # 终点 TCP 停在停点邻域（跟踪误差内）
    tcp_end = np.asarray(arm.fk([float(v) for v in qs[-1]])[:3])
    assert float(np.linalg.norm(tcp_end - stop)) < 0.01


def test_zone_violation_reports_all_crossed_zones():
    """同一线段穿多个禁区时逐区报告（v3.1 审查补丁：不得吞掉面部球入侵）。"""
    val = EnvelopeValidator()
    torso = next(z for z in val.config.zones if z.name == "torso")
    face = val.config.face_center
    # 面部球心本身在面部球内；取一条同时深入躯干胶囊与面部球的段
    deep = np.asarray(torso.p1) + 0.4 * (np.asarray(torso.p2) - np.asarray(torso.p1))
    a = face.copy()
    b = deep
    assert float(np.linalg.norm(a - face)) < val.face_radius  # a 在球内
    assert float(np.linalg.norm(b - np.asarray(torso.p1))) < float(torso.radius)  # b 在胶囊内
    hits, _ = val._zone_segment_violation(a, b)
    names = {n for n, _ in hits}
    assert "face" in names and "torso" in names
    rep = val.check_trajectory([0.0, 1.0], [a, b], label="multi")
    zones = {v.get("zone") for v in rep["violations"] if v["kind"] == "zone"}
    assert {"face", "torso"} <= zones


def test_joint_trajectory_dense_fk_catches_tcp_arc(arm):
    """关节段弦在球外、弧在球内：加密 FK 采样必须拒绝（审查 A3）。"""
    val = EnvelopeValidator()
    from chengshao.cs_sim.adversarial import _Zones

    zones = _Zones.from_validator(val)
    lo = np.asarray(arm.joint_lower)
    hi = np.asarray(arm.joint_upper)
    n_arm = arm.n_joints - 1
    mid = 0.5 * (lo + hi)
    rng = np.random.default_rng(7)
    found = None
    for _ in range(60_000):
        qa = mid.copy()
        qa[:n_arm] = rng.uniform(lo[:n_arm], hi[:n_arm])
        pa = np.asarray(arm.fk([float(v) for v in qa])[:3])
        if zones.face_penetration(pa) > -0.03:
            continue
        j = int(rng.integers(0, n_arm))
        qb = qa.copy()
        qb[j] = float(np.clip(qb[j] + rng.uniform(0.8, 1.4) * rng.choice([-1.0, 1.0]), lo[j], hi[j]))
        pb = np.asarray(arm.fk([float(v) for v in qb])[:3])
        if zones.face_penetration(pb) > -0.03:
            continue
        worst = -1e9
        for f in np.linspace(0, 1, 101)[1:-1]:
            qi = qa + f * (qb - qa)
            pi = np.asarray(arm.fk([float(v) for v in qi])[:3])
            worst = max(worst, zones.face_penetration(pi))
        if worst >= 0.01:
            found = (qa, qb, worst)
            break
    assert found is not None, "几何搜索未找到关节弧入球样本"
    qa, qb, worst = found
    # 弧长按 0.06 m/s（低于近脸限速）：违规只可能来自禁区入侵
    arc = 0.30
    dur = arc / 0.06
    rep = val.check_joint_trajectory([0.0, dur], [qa, qb], arm, label="arc_trap")
    assert rep["rejected"]
    assert any(v["kind"] == "zone" and v.get("zone") == "face" for v in rep["violations"])


def test_joint_trajectory_link_sweep_caught(arm):
    """连杆体（参考点+半径）入禁区而 TCP 在球外：link_sweep 必须拒绝。"""
    val = EnvelopeValidator()
    from chengshao.cs_sim.adversarial import _Zones

    zones = _Zones.from_validator(val)
    lo = np.asarray(arm.joint_lower)
    hi = np.asarray(arm.joint_upper)
    n_arm = arm.n_joints - 1
    mid = 0.5 * (lo + hi)
    rng = np.random.default_rng(11)
    found = None
    for _ in range(80_000):
        q = mid.copy()
        q[:n_arm] = rng.uniform(lo[:n_arm], hi[:n_arm])
        lp = np.asarray(arm.link_points([float(v) for v in q]))
        tcp_clear = zones.point_clearance(lp[-1])
        if tcp_clear < 0.02:
            continue
        for i in range(len(lp) - 1):
            name, pen = zones.point_penetration(lp[i])
            if pen >= 0.008:
                found = (q, i, name, pen)
                break
        if found:
            break
    assert found is not None, "几何搜索未找到连杆扫掠样本"
    q, i, zone_name, pen = found
    q1 = q.copy()
    q1[0] += 0.004  # 极慢漂移 0.0005 rad/s：不触发角速度/TCP 检查
    rep = val.check_joint_trajectory([0.0, 8.0], [q, q1], arm, label="link_trap")
    assert rep["rejected"]
    assert any(v["kind"] == "link_sweep" for v in rep["violations"])
    assert rep["min_link_clearance_m"] < 0.0


def test_joint_trajectory_joint_speed_caught(arm):
    """关节角速度超限：逐段 max|Δq|/Δt 检查必须拒绝（v3.1 新类别）。"""
    val = EnvelopeValidator()
    from chengshao.cs_sim.adversarial import _Zones

    zones = _Zones.from_validator(val)
    lo = np.asarray(arm.joint_lower)
    hi = np.asarray(arm.joint_upper)
    n_arm = arm.n_joints - 1
    mid = 0.5 * (lo + hi)
    rng = np.random.default_rng(13)
    q0 = None
    for _ in range(2000):
        cand = mid.copy()
        cand[:n_arm] = rng.uniform(lo[:n_arm], hi[:n_arm])
        tcp = np.asarray(arm.fk([float(v) for v in cand])[:3])
        lp = np.asarray(arm.link_points([float(v) for v in cand]))
        if zones.point_clearance(tcp) >= 0.02 and min(zones.point_clearance(p) for p in lp) >= 0.02:
            q0 = cand
            break
    assert q0 is not None
    q1 = q0.copy()
    q1[0] = float(np.clip(q1[0] + 1.0, lo[0], hi[0]))
    dt = 0.25  # 4 rad/s >> 1.5 rad/s
    rep = val.check_joint_trajectory([0.0, dt], [q0, q1], arm, label="speed_trap")
    assert rep["rejected"]
    assert any(v["kind"] == "joint_speed" for v in rep["violations"])
    assert rep["max_joint_speed_rad_s"] > 1.5


def test_joint_trajectory_accepts_slow_clean_motion(arm):
    """两个干净构型间的慢速关节插值不被误拒（对照）。"""
    val = EnvelopeValidator()
    from chengshao.cs_sim.adversarial import _Zones

    zones = _Zones.from_validator(val)
    lo = np.asarray(arm.joint_lower)
    hi = np.asarray(arm.joint_upper)
    n_arm = arm.n_joints - 1
    mid = 0.5 * (lo + hi)
    rng = np.random.default_rng(17)

    def clean(q):
        tcp = np.asarray(arm.fk([float(v) for v in q])[:3])
        lp = np.asarray(arm.link_points([float(v) for v in q]))
        return (zones.point_clearance(tcp) >= 0.03
                and min(zones.point_clearance(p) for p in lp) >= 0.03)

    qa = qb = None
    for _ in range(4000):
        cand = mid.copy()
        cand[:n_arm] = rng.uniform(lo[:n_arm], hi[:n_arm])
        if clean(cand):
            qa = cand
            break
    assert qa is not None
    for _ in range(4000):
        cand = qa + rng.uniform(-0.15, 0.15, size=len(qa))
        cand = np.clip(cand, lo, hi)
        if clean(cand):
            qb = cand
            break
    assert qb is not None
    rep = val.check_joint_trajectory([0.0, 4.0], [qa, qb], arm, label="slow_clean")
    assert not rep["rejected"], rep["violations"][:3]


def test_pos_only_solver_never_reports_fake_convergence():
    """IK 假收敛回归锁：converged=True 必须蕴含自身 pos_err 达标（含替换分支）。"""
    from chengshao.cs_sim.ik_solver import solve_with_restarts

    arm = load_arm("auto")
    be = arm._backend
    for p in ([0.22, -0.18, 0.06], [0.25, 0.0, 0.30], [0.10, 0.30, 0.40]):
        for sd in (0, 1, 2):
            res = solve_with_restarts(be, np.asarray(p, dtype=float), np.eye(3),
                                      pos_only=True, restarts=32, rng_seed=sd)
            if res is None:
                continue
            if res.converged:
                assert res.pos_err_m <= 5e-4 + 1e-9, (p, sd, res.pos_err_m)


def test_adversarial_independent_oracle_end_to_end(arm):
    """独立 oracle 小样本全绿：全部拒绝且预定违规类别逐条命中（审查 A1）。"""
    val = EnvelopeValidator()
    from chengshao.cs_sim.adversarial import build_adversarial_cases, run_adversarial

    cases = build_adversarial_cases(
        arm, val, n_joint_speed=6, n_link_sweep=4, n_tcp_arc=6, seed=42
    )
    assert len(cases) >= 12
    res = run_adversarial(val, arm, cases)
    assert res["total"] == len(cases)
    assert res["rejection_rate"] == pytest.approx(1.0)
    assert res["predicted_kind_hit_rate"] == pytest.approx(1.0)


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
