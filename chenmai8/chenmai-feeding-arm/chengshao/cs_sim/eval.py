"""cs_sim 验收 eval（开发指令 §5.1；v3.1 审查修订）。

用法（在包根 ``chengshao/`` 目录下运行）::

    python -m cs_sim.eval --model auto --report reports/sim_eval.json

通过线（§5.1，全部满足才 exit 0）：
  1) 200 个随机可达目标 IK 成功率 >=98%，且位置误差 <=5mm、姿态误差 <=0.05rad、
     可操作度 sigma_min(Jp) >= 奇异保护线（低于阈值判失败，审查 A2）；
  2) 口前送达工作区专项目标批（停点邻域，FK 拒绝采样）：成功率、误差与
     灵巧可操作度单列达标（审查 A2）；
  3) 500 条随机违规轨迹被安全包络校验器 100% 拒绝；
  4) 对抗性独立 oracle 样本（关节空间，``cs_sim.adversarial`` 独立几何实现，
     不复用校验器距离代码）100% 被拒且预定违规类别命中（审查 A1/A3）；
  5) 名义送达：停点在面部球外、数值安全余量 >0、碗→停点整段走廊
     （笛卡尔 + 关节空间）不被拒且不依赖豁免（审查 A4/B3）；
  6) 生成 reports/reach_map.png。

附加自证（超出 §5.1 最低线，亦计入 pass）：
  - 装载校验（load_arm "加载并校验"）；
  - 跨层 FK 一致性：URDF(物理引擎) / 内置名义链 / URDF(ikpy 链) 对参考层
    MJCF 的 FK 最大位置/姿态偏差在阈值内（回退链保真证据）；
  - 良性轨迹（工作区慢速路径）不被误拒。

报告 JSON 字段遵循 §10.2：{module, date, cmd, metrics, thresholds, pass}。
模型路径在报告中只记中性元数据（层级 + 内容 SHA-256 前 16 位 + 关节表），
不落任何上游名（命名纪律）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

from .adversarial import build_adversarial_cases, run_adversarial
from .arm_model import ArmModel, load_arm
from .backends import IkpyChainBackend
from .ik_solver import solve_dls, solve_with_restarts
from .model_source import discover_model_file, file_sha256_prefix
from .safety_envelope import EnvelopeValidator

# ---- §5.1 通过线阈值（与报告 thresholds 字段一致） ---------------------------
THRESHOLDS: dict = {
    "ik_targets_min": 200,
    "ik_success_rate_min": 0.98,
    "ik_pos_err_max_m": 0.005,
    "ik_ori_err_max_rad": 0.05,
    "ik_manip_sigma_min": 0.005,  # 随机批奇异保护线：sigma_min(Jp) 低于即判失败
    "ik_mouth_front_targets_min": 60,
    "ik_mouth_front_success_rate_min": 0.95,
    "ik_mouth_front_manip_sigma_min": 0.02,  # 送达工作区灵巧底线（实测分布 p0=0.068）
    "violating_traj_min": 500,
    "violating_rejection_rate_min": 1.0,
    "adversarial_traj_min": 120,
    "adversarial_rejection_rate_min": 1.0,
    "adversarial_predicted_kind_hit_rate_min": 1.0,
    "delivery_margin_min_m": 0.005,
    "delivery_corridor_required": True,
    "reach_map_png": True,
    # 附加自证阈值
    "cross_tier_pos_err_max_m": 5e-4,
    "cross_tier_ori_err_max_rad": 5e-3,
    "benign_acceptance_rate_min": 1.0,
}

# 口前专项目标批：以送达停点为中心的目标盒半宽（米）与球外安全距
_MOUTH_FRONT_BOX_M = (0.025, 0.05, 0.05)
_MOUTH_FRONT_SPHERE_MARGIN_M = 0.005


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="python -m cs_sim.eval",
        description="cs_sim eval: model load fallback chain + FK/IK + reachability + safety envelope",
    )
    ap.add_argument("--model", default="auto",
                    help="模型文件路径；缺省 auto=回退链自动发现（MJCF→URDF→内置名义链）")
    ap.add_argument("--report", default="reports/sim_eval.json",
                    help="报告 JSON 输出路径（相对 cwd）")
    ap.add_argument("--seed", type=int, default=20260928, help="确定性随机种子")
    ap.add_argument("--ik-targets", type=int, default=200, help="IK 测试目标数（§5.1: 200）")
    ap.add_argument("--ik-mouth-front-targets", type=int, default=60,
                    help="口前送达工作区专项目标数（审查 A2）")
    ap.add_argument("--violating", type=int, default=500, help="违规轨迹数（§5.1: 500）")
    ap.add_argument("--adversarial-joint-speed", type=int, default=60,
                    help="对抗样本：关节角速度超限类数量")
    ap.add_argument("--adversarial-link-sweep", type=int, default=24,
                    help="对抗样本：连杆胶囊扫掠类数量")
    ap.add_argument("--adversarial-tcp-arc", type=int, default=40,
                    help="对抗样本：关节插值 TCP 入禁区类数量")
    ap.add_argument("--benign", type=int, default=100, help="良性对照轨迹数")
    ap.add_argument("--reach-res", type=float, default=0.03, help="可达空间体素步长 m")
    ap.add_argument("--cross-check-q", type=int, default=150, help="跨层 FK 一致性采样数")
    return ap.parse_args(argv)


# ---------------------------------------------------------------------------
# 各检查项
# ---------------------------------------------------------------------------


def _sigma_min(arm: ArmModel, q) -> float:
    """位置雅可比最小奇异值（可操作度判据，审查 A2）。"""
    jac_p, _ = arm.jac([float(v) for v in q])
    return float(np.linalg.svd(jac_p, compute_uv=False)[-1])


def _check_ik(arm: ArmModel, n_targets: int, seed: int) -> dict:
    """§5.1：随机可达目标（由随机构型 FK 生成）的 IK 成功率与误差分布。

    v3.1（审查 A2）：收敛解的可操作度 ``sigma_min(Jp)`` 低于
    ``ik_manip_sigma_min``（奇异保护线）时**判失败**，不再计入成功率。
    """
    rng = np.random.default_rng(seed)
    lower = np.asarray(arm.joint_lower)
    upper = np.asarray(arm.joint_upper)
    n_arm = arm.n_joints - 1  # 末关节为夹爪（不影响 TCP），不参与目标采样
    mid = 0.5 * (lower + upper)
    successes = 0
    pos_errs: list[float] = []
    ori_errs: list[float] = []
    restart_hist: list[int] = []
    sigmas: list[float] = []
    manip_rejects = 0
    unconverged = 0
    for k in range(n_targets):
        q_true = mid.copy()
        q_true[:n_arm] = rng.uniform(lower[:n_arm], upper[:n_arm])
        pose = arm.fk([float(v) for v in q_true])
        tpos, tquat = pose[0:3], pose[3:7]
        seed_q = mid + rng.uniform(-0.4, 0.4, size=len(mid))  # 有扰动的初值
        res = arm.ik_detailed(list(tpos), list(tquat), seed=[float(v) for v in seed_q])
        if res is None or not res.converged:
            unconverged += 1
            continue
        pose2 = arm.fk([float(v) for v in res.q])
        pos_err = float(np.linalg.norm(np.asarray(tpos) - np.asarray(pose2[0:3])))
        ori_err = _quat_angle(tquat, pose2[3:7])
        if pos_err > THRESHOLDS["ik_pos_err_max_m"] or ori_err > THRESHOLDS["ik_ori_err_max_rad"]:
            continue
        sigma = _sigma_min(arm, res.q)
        if sigma < THRESHOLDS["ik_manip_sigma_min"]:
            manip_rejects += 1  # 奇异邻域解：判失败（审查 A2）
            continue
        successes += 1
        pos_errs.append(pos_err)
        ori_errs.append(ori_err)
        restart_hist.append(res.restart)
        sigmas.append(sigma)
    rate = successes / n_targets if n_targets else 0.0
    return {
        "targets": n_targets,
        "successes": successes,
        "success_rate": rate,
        "unconverged": unconverged,
        "manip_rejects": manip_rejects,
        "manip_sigma_min_threshold": THRESHOLDS["ik_manip_sigma_min"],
        "manip_sigma_min": min(sigmas) if sigmas else None,
        "manip_sigma_p05": float(np.percentile(sigmas, 5)) if sigmas else None,
        "manip_sigma_median": float(np.median(sigmas)) if sigmas else None,
        "pos_err_max_m": max(pos_errs) if pos_errs else None,
        "pos_err_mean_m": float(np.mean(pos_errs)) if pos_errs else None,
        "pos_err_p95_m": float(np.percentile(pos_errs, 95)) if pos_errs else None,
        "ori_err_max_rad": max(ori_errs) if ori_errs else None,
        "ori_err_mean_rad": float(np.mean(ori_errs)) if ori_errs else None,
        "restarts_used_max": max(restart_hist) if restart_hist else 0,
        "restarts_used_mean": float(np.mean(restart_hist)) if restart_hist else 0.0,
    }


def _check_ik_mouth_front(arm: ArmModel, val: EnvelopeValidator, n_targets: int,
                          seed: int) -> dict:
    """口前送达工作区专项目标批（审查 A2）。

    目标 = 送达停点邻域盒内、面部球外（留 ``_MOUTH_FRONT_SPHERE_MARGIN_M``）、
    禁区外自由空间的位姿，由随机构型 FK 拒绝采样产生（与主批同方法学，保证
    按构造可达且姿态在 5 自由度可达流形上）。成功 = 收敛 + 位置/姿态达 §5.1
    线 + 可操作度 ``sigma_min >= ik_mouth_front_manip_sigma_min``（灵巧底线）。
    """
    rng = np.random.default_rng(seed + 3)
    lower = np.asarray(arm.joint_lower)
    upper = np.asarray(arm.joint_upper)
    n_arm = arm.n_joints - 1
    mid = 0.5 * (lower + upper)
    stop = val.delivery_stop_point()
    box = np.asarray(_MOUTH_FRONT_BOX_M, dtype=float)
    sphere_margin = _MOUTH_FRONT_SPHERE_MARGIN_M

    sig_min_threshold = THRESHOLDS["ik_mouth_front_manip_sigma_min"]
    successes = 0
    tried_targets = 0
    attempts = 0
    pos_errs: list[float] = []
    ori_errs: list[float] = []
    sigmas: list[float] = []
    manip_rejects = 0
    unconverged = 0
    face_zone = next(z for z in val.config.zones if z.name == "face")
    while tried_targets < n_targets and attempts < 500_000:
        attempts += 1
        q_true = mid.copy()
        q_true[:n_arm] = rng.uniform(lower[:n_arm], upper[:n_arm])
        pose = arm.fk([float(v) for v in q_true])
        p = np.asarray(pose[0:3])
        if np.any(np.abs(p - stop) > box):
            continue
        if float(face_zone.distance(p)) < sphere_margin:  # 球内或贴面者弃用
            continue
        if val.min_zone_clearance(p) < 0.0:
            continue
        tried_targets += 1
        seed_q = mid + rng.uniform(-0.4, 0.4, size=len(mid))
        res = arm.ik_detailed(list(p), list(pose[3:7]), seed=[float(v) for v in seed_q])
        if res is None or not res.converged:
            unconverged += 1
            continue
        pose2 = arm.fk([float(v) for v in res.q])
        pos_err = float(np.linalg.norm(p - np.asarray(pose2[0:3])))
        ori_err = _quat_angle(pose[3:7], pose2[3:7])
        if pos_err > THRESHOLDS["ik_pos_err_max_m"] or ori_err > THRESHOLDS["ik_ori_err_max_rad"]:
            continue
        sigma = _sigma_min(arm, res.q)
        if sigma < sig_min_threshold:
            manip_rejects += 1
            continue
        successes += 1
        pos_errs.append(pos_err)
        ori_errs.append(ori_err)
        sigmas.append(sigma)
    rate = successes / tried_targets if tried_targets else 0.0
    return {
        "region": "delivery stop-point neighbourhood (mouth-front workspace)",
        "box_half_width_m": [float(v) for v in box],
        "sphere_margin_m": sphere_margin,
        "targets": tried_targets,
        "successes": successes,
        "success_rate": rate,
        "unconverged": unconverged,
        "manip_rejects": manip_rejects,
        "manip_sigma_min_threshold": sig_min_threshold,
        "manip_sigma_min": min(sigmas) if sigmas else None,
        "manip_sigma_median": float(np.median(sigmas)) if sigmas else None,
        "pos_err_max_m": max(pos_errs) if pos_errs else None,
        "ori_err_max_rad": max(ori_errs) if ori_errs else None,
    }


def _quat_angle(q1, q2) -> float:
    q1 = np.asarray(q1, dtype=float)
    q2 = np.asarray(q2, dtype=float)
    q1 = q1 / np.linalg.norm(q1)
    q2 = q2 / np.linalg.norm(q2)
    return float(2.0 * np.arccos(min(1.0, abs(float(np.dot(q1, q2))))))


def _check_cross_tier(arm: ArmModel, n_q: int, seed: int) -> dict:
    """回退链保真：各回退层 FK 对参考层的最大位置/姿态偏差。"""
    if arm.tier != "mjcf":
        return {"skipped": True, "reason": f"reference tier is {arm.tier}, not mjcf"}
    rng = np.random.default_rng(seed + 1)
    lower = np.asarray(arm.joint_lower)
    upper = np.asarray(arm.joint_upper)
    n_arm = arm.n_joints - 1
    qs = []
    for _ in range(n_q):
        q = 0.5 * (lower + upper)
        q[:n_arm] = rng.uniform(lower[:n_arm], upper[:n_arm])
        qs.append(q)

    refs = [arm.fk_pose([float(v) for v in q]) for q in qs]
    out: dict = {"skipped": False, "n_q": n_q}

    # 层 2/3：URDF（物理引擎与 ikpy 链）与内置名义链——如本地存在则测
    resolution = discover_model_file()
    tiers_to_test: list[tuple[str, object]] = [("chain_builtin", IkpyChainBackend())]
    urdf_path = _sibling_urdf(resolution.path) if resolution.path is not None else None
    if urdf_path is not None:
        tiers_to_test.append(("chain_urdf_ikpy", IkpyChainBackend(urdf_path=urdf_path)))
        from .backends import MujocoBackend

        try:
            tiers_to_test.append(("urdf_mujoco", MujocoBackend(urdf_path)))
        except Exception as exc:  # noqa: BLE001
            out["urdf_mujoco_error"] = repr(exc)

    for name, backend in tiers_to_test:
        max_p = 0.0
        max_o = 0.0
        try:
            for q, (rp, rR) in zip(qs, refs):
                # 链式后端仅含臂关节（无夹爪列），取前 n 个分量
                qv = np.asarray(q, dtype=float)[: backend.n_joints]
                pos, R = backend.fk(qv)
                max_p = max(max_p, float(np.linalg.norm(pos - rp)))
                cos = float(np.clip((np.trace(rR.T @ R) - 1.0) / 2.0, -1.0, 1.0))
                max_o = max(max_o, float(np.arccos(cos)))
        except Exception as exc:  # noqa: BLE001
            out[name] = {"error": repr(exc)}
            continue
        out[name] = {"max_pos_err_m": max_p, "max_ori_err_rad": max_o}
    return out


def _sibling_urdf(mjcf_path):
    """同目录同名基底的 URDF 文件（存在才返回）。"""
    cand = mjcf_path.with_suffix(".urdf")
    return cand if cand.exists() else None


def _check_reachability(arm: ArmModel, res_m: float, report_dir: Path) -> dict:
    """§5.1：可达空间体素统计 + PNG。"""
    grid = {
        "x_m": [0.00, 0.50],
        "y_m": [-0.40, 0.40],
        "z_m": [-0.05, 0.50],
        "res_m": res_m,
    }
    result = arm.reachable_map(grid)
    png_path = report_dir / "reach_map.png"
    result["png"] = None
    try:
        result["png"] = arm.render_reach_map(result, png_path)
    except Exception as exc:  # noqa: BLE001
        result["png_error"] = repr(exc)
    result.pop("reachable_points_m", None)  # 报告瘦身：点阵只用于渲染
    return result


def _check_safety(n_violating: int, n_benign: int, seed: int) -> dict:
    """§5.1：500 条随机违规轨迹 100% 拒绝；良性对照不误拒。"""
    val = EnvelopeValidator()  # 缺省装载 config/workspace.json
    rng = np.random.default_rng(seed + 2)
    face = val.config.face_center
    torso_cfg = next(z for z in val.config.zones if z.name == "torso")
    by_type: dict[str, dict] = {}
    rejected_count = 0

    def _record(kind: str, report: dict) -> None:
        nonlocal rejected_count
        stats = by_type.setdefault(kind, {"n": 0, "rejected": 0})
        stats["n"] += 1
        if report["rejected"]:
            rejected_count += 1
            stats["rejected"] += 1
            kinds = {v["kind"] for v in report["violations"]}
            stats.setdefault("violation_kinds_seen", [])
            for k in sorted(kinds):
                if k not in stats["violation_kinds_seen"]:
                    stats["violation_kinds_seen"].append(k)

    def _linear_path(p0, p1, duration_s: float, n: int = 24):
        ts = np.linspace(0.0, duration_s, n)
        pts = np.linspace(np.asarray(p0), np.asarray(p1), n)
        return ts, pts

    # 1) 面部球域侵入（端点在球内或路径穿越球体）
    r = float(next(z for z in val.config.zones if z.name == "face").radius)
    for i in range(int(n_violating * 0.30)):
        q0 = _work_point(rng, val)
        depth = rng.uniform(0.02, 0.8 * r)
        direction = _rand_unit(rng)
        p_in = face + direction * depth
        ts, pts = _linear_path(q0, p_in, rng.uniform(1.0, 3.0))
        _record("face_zone_intrusion", val.check_trajectory(ts, pts, label=f"face_{i}"))

    # 2) 躯干胶囊侵入
    for i in range(int(n_violating * 0.20)):
        q0 = _work_point(rng, val)
        t = rng.uniform(0.15, 0.85)
        axis_pt = np.asarray(torso_cfg.p1) + t * (np.asarray(torso_cfg.p2) - np.asarray(torso_cfg.p1))
        d = _rand_unit(rng)
        p_in = axis_pt + d * (0.05 * float(torso_cfg.radius))
        ts, pts = _linear_path(q0, p_in, rng.uniform(1.0, 3.0))
        _record("torso_zone_intrusion", val.check_trajectory(ts, pts, label=f"torso_{i}"))

    # 3) 接近段超速（远离面部的工作区快速移动）
    for i in range(int(n_violating * 0.25)):
        p0 = _work_point(rng, val, min_face_dist=0.22)
        p1 = _work_point(rng, val, min_face_dist=0.22)
        length = float(np.linalg.norm(p1 - p0))
        if length < 1e-3:
            p1 = p0 + np.array([0.25, 0.05, 0.0])
            length = float(np.linalg.norm(p1 - p0))
        dur = length / rng.uniform(0.4, 0.9)  # 0.4~0.9 m/s >> 0.15
        ts, pts = _linear_path(p0, p1, dur)
        _record("speed_approach_violation", val.check_trajectory(ts, pts, label=f"fast_{i}"))

    # 4) 面部近旁超速（球外 0.12~0.15m 带内，速度介于两限之间）
    near = val.config.near_face_distance
    for i in range(n_violating - (int(n_violating * 0.30) + int(n_violating * 0.20)
                                  + int(n_violating * 0.25))):
        d_shell = rng.uniform(r + 0.006, near - 0.002)  # 球外、近旁带内
        d0 = _rand_unit(rng)
        # 与 d0 近垂直的方向，构造小弦长路径，保证不出带、不入球
        helper = _rand_unit(rng)
        tangent = np.cross(d0, helper)
        tangent /= max(np.linalg.norm(tangent), 1e-9)
        chord = rng.uniform(0.01, 0.03)
        p0 = face + d0 * d_shell
        p1 = face + (d0 + tangent * (chord / d_shell)) * d_shell
        dur = chord / rng.uniform(0.11, 0.14)  # 0.11~0.14 m/s > 0.10
        ts, pts = _linear_path(p0, p1, dur)
        _record("speed_near_face_violation", val.check_trajectory(ts, pts, label=f"near_{i}"))

    # 良性对照：工作区局部短程慢速路径（不应被拒）。
    # 构造保证：两端点与整段线段到面部球面 / 躯干胶囊面均留 >=2cm 裕量
    # （独立几何计算），速度 0.05 m/s 远低于两档限速。
    from .frames import segment_point_distance, segment_segment_distance

    face_zone = next(z for z in val.config.zones if z.name == "face")
    benign_accepted = 0
    benign_reports = []
    for i in range(n_benign):
        p0 = _work_point(rng, val, min_face_dist=0.24)
        p1 = None
        for _try in range(60):
            cand = p0 + _rand_unit(rng) * rng.uniform(0.02, 0.08)
            if cand[0] < 0.02 or abs(cand[1]) > 0.38 or not (-0.04 <= cand[2] <= 0.18):
                continue
            clear_face = segment_point_distance(p0, cand, np.asarray(face_zone.center)) - float(face_zone.radius)
            clear_torso = segment_segment_distance(
                p0, cand, np.asarray(torso_cfg.p1), np.asarray(torso_cfg.p2)
            ) - float(torso_cfg.radius)
            if min(clear_face, clear_torso) >= 0.02:
                p1 = cand
                break
        if p1 is None:
            continue
        length = float(np.linalg.norm(p1 - p0))
        dur = max(length / 0.05, 0.5)  # 0.05 m/s，远低于 0.10/0.15 两档限速
        ts, pts = _linear_path(p0, p1, dur)
        rep = val.check_trajectory(ts, pts, label=f"benign_{i}")
        benign_reports.append(rep)
        if not rep["rejected"]:
            benign_accepted += 1

    total = sum(s["n"] for s in by_type.values())
    return {
        "violating_total": total,
        "violating_rejected": rejected_count,
        "violating_rejection_rate": (rejected_count / total) if total else 0.0,
        "by_type": by_type,
        "benign_total": len(benign_reports),
        "benign_accepted": benign_accepted,
        "benign_acceptance_rate": (benign_accepted / len(benign_reports)) if benign_reports else 0.0,
        "config_source": "chengshao/config/workspace.json (defaults)",
    }


def _rand_unit(rng: np.random.Generator) -> np.ndarray:
    v = rng.normal(size=3)
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else np.array([1.0, 0.0, 0.0])


def _check_adversarial(arm: ArmModel, val: EnvelopeValidator, args) -> dict:
    """对抗性独立 oracle 样本（审查 A1/A3）。

    样本由 ``cs_sim.adversarial`` 生成：关节空间轨迹 + 独立几何实现 +
    生成前 oracle 核验 + 预定违规类别。通过线 = 100% 拒绝 **且** 预定
    违规类别逐条命中。
    """
    cases = build_adversarial_cases(
        arm, val,
        n_joint_speed=args.adversarial_joint_speed,
        n_link_sweep=args.adversarial_link_sweep,
        n_tcp_arc=args.adversarial_tcp_arc,
        seed=args.seed,
    )
    result = run_adversarial(val, arm, cases)
    result["predicted_kinds"] = {
        "joint_speed_over_limit": "joint_speed",
        "link_capsule_sweep": "link_sweep",
        "tcp_arc_zone_intrusion": "zone(face)",
    }
    return result


def _track_cartesian_line(arm: ArmModel, points: list[np.ndarray]) -> tuple[list[np.ndarray], int]:
    """位置-only IK 线跟踪：逐路点解 IK（优先续上一解，失败则多起点重启）。

    返回 (关节路点列表, 失败路点下标或 -1)。姿态不约束——走廊验收关注
    TCP 位置走廊与连杆扫掠，抓手姿态由行为层负责。
    """
    lower = np.asarray(arm.joint_lower)
    upper = np.asarray(arm.joint_upper)
    qs: list[np.ndarray] = []
    q_prev: np.ndarray | None = None
    for k, p in enumerate(points):
        p = np.asarray(p, dtype=float)
        if q_prev is not None:
            res = solve_dls(arm._backend, p, np.eye(3), q_prev, pos_only=True)
            if res.converged:
                q_prev = np.clip(res.q, lower, upper)
                qs.append(q_prev)
                continue
        best: tuple[float, np.ndarray] | None = None
        for sd in (0, 1, 2, 3):
            res = solve_with_restarts(arm._backend, p, np.eye(3),
                                      pos_only=True, restarts=48, rng_seed=sd)
            if res is not None and res.converged:
                qc = np.clip(res.q, lower, upper)
                d = 0.0 if q_prev is None else float(np.abs(qc - q_prev).max())
                if best is None or d < best[0]:
                    best = (d, qc)
        if best is None:
            return qs, k
        q_prev = best[1]
        qs.append(q_prev)
    return qs, -1


def _check_delivery(arm: ArmModel, val: EnvelopeValidator) -> dict:
    """名义送达验收（审查 A4/B3）：停点球外 + 数值余量 + 碗→停点整段走廊。

    - 停点 = ``delivery_stop_point()``：口部点 -X 退 (球半径 + 间隙)，必须
      严格在面部球外，**不登记任何送达豁免**；
    - 数值安全余量 = 停距 − 勺头伸出(保守常量) − 跟踪误差上界 − 感知误差
      上界，必须 ≥ ``delivery_margin_min_m``；
    - 走廊 = 碗位（config bowls_m[0]）→ 碗上提升点 → 中途过渡点 → 停点，
      按 0.05 m/s 时间刻度；笛卡尔线与位置-only IK 关节跟踪两条都要被
      校验器接受（含连杆扫掠与关节角速度检查）。
    """
    face = val.config.face_center
    stop = val.delivery_stop_point()
    stop_clearance = float(np.linalg.norm(stop - face)) - val.face_radius

    cfg_path = Path(__file__).resolve().parents[1] / "config" / "workspace.json"
    bowls: list[list[float]] = []
    if cfg_path.exists():
        try:
            bowls = [list(map(float, b)) for b in json.loads(
                cfg_path.read_text(encoding="utf-8")).get("bowls_m", [])]
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            bowls = []
    bowl = np.asarray(bowls[0] if bowls else [0.22, -0.18, 0.02], dtype=float)

    lift = bowl + np.array([0.0, 0.0, 0.10])
    transit = np.array([(bowl[0] + stop[0]) / 2.0 + 0.015, (bowl[1] + stop[1]) / 2.0, 0.20])
    corridor: list[np.ndarray] = [bowl.copy()]
    for a, b in [(bowl, lift), (lift, transit), (transit, stop)]:
        seg_len = float(np.linalg.norm(b - a))
        n = max(2, int(np.ceil(seg_len / 0.02)))
        for f in np.linspace(0.0, 1.0, n + 1)[1:]:
            corridor.append(a + f * (b - a))
    corridor_pts = np.asarray(corridor)
    durations = [float(np.linalg.norm(corridor_pts[i + 1] - corridor_pts[i])) / 0.05
                 for i in range(len(corridor_pts) - 1)]
    times = np.concatenate([[0.0], np.cumsum(durations)])

    cart_rep = val.check_trajectory(times, corridor_pts, label="delivery_corridor_cart")

    joint_qs, fail_at = _track_cartesian_line(arm, corridor)
    joint_rep: dict | None = None
    tcp_end_err = None
    tcp_start_err = None
    if fail_at < 0 and len(joint_qs) == len(corridor_pts):
        joint_rep = val.check_joint_trajectory(times, joint_qs, arm,
                                               label="delivery_corridor_joint")
        tcp_end_err = float(np.linalg.norm(
            np.asarray(arm.fk([float(v) for v in joint_qs[-1]])[:3]) - stop))
        tcp_start_err = float(np.linalg.norm(
            np.asarray(arm.fk([float(v) for v in joint_qs[0]])[:3]) - bowl))

    margin = val.delivery_margin()
    return {
        "stop_point_m": [round(float(v), 4) for v in stop],
        "stop_distance_m": round(float(np.linalg.norm(stop - face)), 4),
        "stop_clearance_m": round(stop_clearance, 4),
        "stop_outside_sphere": bool(stop_clearance >= val.config.delivery_stop_clearance - 1e-9),
        "exemptions_registered": len(val._delivery_targets),
        "spoon_reach_note": "spoon_tip_reach 为保守常量（未实测，偏大取值），D4 臂上件后实测覆盖",
        "margin": margin,
        "corridor": {
            "bowl_m": [round(float(v), 4) for v in bowl],
            "waypoints": int(len(corridor_pts)),
            "speed_mps": 0.05,
            "cart": {
                "rejected": bool(cart_rep["rejected"]),
                "min_zone_clearance_m": round(float(cart_rep["min_zone_clearance_m"]), 4),
                "max_speed_mps": round(float(cart_rep["max_speed_mps"]), 4),
            },
            "joint": {
                "tracked": bool(fail_at < 0 and joint_rep is not None),
                "fail_at": fail_at,
                "rejected": None if joint_rep is None else bool(joint_rep["rejected"]),
                "min_zone_clearance_m": None if joint_rep is None else round(
                    float(joint_rep["min_zone_clearance_m"]), 4),
                "min_link_clearance_m": None if joint_rep is None else round(
                    float(joint_rep["min_link_clearance_m"]), 4),
                "max_joint_speed_rad_s": None if joint_rep is None else round(
                    float(joint_rep["max_joint_speed_rad_s"]), 4),
                "tcp_start_err_m": None if tcp_start_err is None else round(tcp_start_err, 4),
                "tcp_end_err_m": None if tcp_end_err is None else round(tcp_end_err, 4),
            },
        },
    }


def _work_point(rng: np.random.Generator, val: EnvelopeValidator,
                min_face_dist: float = 0.20) -> np.ndarray:
    """工作区采样点：远离面部球域与躯干胶囊（有裕量），可作合法起止点。"""
    for _ in range(200):
        p = np.array([
            rng.uniform(0.05, 0.32),
            rng.uniform(-0.32, 0.32),
            rng.uniform(-0.03, 0.18),
        ])
        if float(np.linalg.norm(p - val.config.face_center)) < min_face_dist:
            continue
        if val.min_zone_clearance(p) < 0.02:
            continue
        return p
    return np.array([0.15, -0.25, 0.05])  # 理论上到不了的兜底点（远离两禁区）


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report_path = Path(args.report)
    report_dir = report_path.parent
    report_dir.mkdir(parents=True, exist_ok=True)
    t_wall0 = time.perf_counter()

    print(f"[cs_sim.eval] loading model: {args.model}")
    arm = load_arm(args.model)
    print(f"[cs_sim.eval] tier={arm.tier} n_joints={arm.n_joints} joints={arm.joint_names}")

    cmd = (f"python -m cs_sim.eval --model {args.model} --report {args.report}")
    metrics: dict = {
        "model": {
            "tier": arm.tier,
            "n_joints": arm.n_joints,
            "joint_names": arm.joint_names,
            "joint_lower_rad": [round(v, 6) for v in arm.joint_lower],
            "joint_upper_rad": [round(v, 6) for v in arm.joint_upper],
            **arm.info,
        },
        "validate": arm.validate(),
        "fk_zero_tcp_m": None,
    }

    pose0 = arm.fk([0.0] * arm.n_joints)
    metrics["fk_zero_tcp_m"] = [round(float(v), 6) for v in pose0[0:3]]
    print(f"[cs_sim.eval] fk(0) TCP = {np.round(pose0[0:3], 4).tolist()} m")

    print(f"[cs_sim.eval] IK benchmark: {args.ik_targets} targets ...")
    t0 = time.perf_counter()
    ik = _check_ik(arm, args.ik_targets, args.seed)
    ik["duration_s"] = round(time.perf_counter() - t0, 2)
    metrics["ik"] = ik
    print(f"[cs_sim.eval] IK success rate = {ik['success_rate']:.4f} "
          f"(pos_err_max={ik['pos_err_max_m']}, ori_err_max={ik['ori_err_max_rad']}, "
          f"manip_rejects={ik['manip_rejects']}, sigma_min={ik['manip_sigma_min']})")

    print(f"[cs_sim.eval] IK mouth-front batch: {args.ik_mouth_front_targets} targets ...")
    t0 = time.perf_counter()
    ik_mf = _check_ik_mouth_front(arm, EnvelopeValidator(), args.ik_mouth_front_targets, args.seed)
    ik_mf["duration_s"] = round(time.perf_counter() - t0, 2)
    metrics["ik_mouth_front"] = ik_mf
    print(f"[cs_sim.eval] IK mouth-front success rate = {ik_mf['success_rate']:.4f} "
          f"(targets={ik_mf['targets']}, sigma_min={ik_mf['manip_sigma_min']})")

    print("[cs_sim.eval] cross-tier FK consistency ...")
    t0 = time.perf_counter()
    cross = _check_cross_tier(arm, args.cross_check_q, args.seed)
    cross["duration_s"] = round(time.perf_counter() - t0, 2)
    metrics["cross_tier_fk"] = cross
    for k, v in cross.items():
        if isinstance(v, dict) and "max_pos_err_m" in v:
            print(f"[cs_sim.eval]   {k}: pos_err<={v['max_pos_err_m']:.2e} m, "
                  f"ori_err<={v['max_ori_err_rad']:.2e} rad")

    print(f"[cs_sim.eval] reachability map (res={args.reach_res} m) ...")
    t0 = time.perf_counter()
    reach = _check_reachability(arm, args.reach_res, report_dir)
    reach["duration_s"] = round(time.perf_counter() - t0, 2)
    metrics["reachability"] = reach
    print(f"[cs_sim.eval] reachable voxels = {reach['n_voxels_reachable']}/{reach['n_voxels_total']} "
          f"({reach['reachable_fraction'] * 100:.1f}%), png={reach.get('png')}")

    print(f"[cs_sim.eval] safety envelope: {args.violating} violating + {args.benign} benign ...")
    t0 = time.perf_counter()
    safety = _check_safety(args.violating, args.benign, args.seed)
    safety["duration_s"] = round(time.perf_counter() - t0, 2)
    metrics["safety_envelope"] = safety
    print(f"[cs_sim.eval] violating rejection rate = {safety['violating_rejection_rate']:.4f} "
          f"({safety['violating_rejected']}/{safety['violating_total']}), "
          f"benign acceptance = {safety['benign_accepted']}/{safety['benign_total']}")

    print("[cs_sim.eval] adversarial independent oracle (joint-space) ...")
    t0 = time.perf_counter()
    adv = _check_adversarial(arm, EnvelopeValidator(), args)
    adv["duration_s"] = round(time.perf_counter() - t0, 2)
    metrics["adversarial"] = adv
    print(f"[cs_sim.eval] adversarial rejection = {adv['rejection_rate']:.4f} "
          f"({adv['rejected']}/{adv['total']}), predicted-kind hits = "
          f"{adv['predicted_kind_hits']}/{adv['total']}")

    print("[cs_sim.eval] nominal delivery (stop point / margin / corridor) ...")
    t0 = time.perf_counter()
    delivery = _check_delivery(arm, EnvelopeValidator())
    delivery["duration_s"] = round(time.perf_counter() - t0, 2)
    metrics["delivery"] = delivery
    print(f"[cs_sim.eval] delivery stop_clearance={delivery['stop_clearance_m']} m, "
          f"margin={delivery['margin']['margin_m']} m, "
          f"corridor cart.rejected={delivery['corridor']['cart']['rejected']} "
          f"joint.rejected={delivery['corridor']['joint']['rejected']}")

    # ---- 通过判定 -------------------------------------------------------------
    corridor_joint = delivery["corridor"]["joint"]
    corridor_ok = (
        not delivery["corridor"]["cart"]["rejected"]
        and corridor_joint["tracked"] is True
        and corridor_joint["rejected"] is False
    )
    checks: dict[str, bool] = {
        "ik_targets_reached": ik["targets"] >= THRESHOLDS["ik_targets_min"],
        "ik_success_rate": ik["success_rate"] >= THRESHOLDS["ik_success_rate_min"],
        "ik_pos_err": ik["pos_err_max_m"] is not None
        and ik["pos_err_max_m"] <= THRESHOLDS["ik_pos_err_max_m"],
        "ik_ori_err": ik["ori_err_max_rad"] is not None
        and ik["ori_err_max_rad"] <= THRESHOLDS["ik_ori_err_max_rad"],
        "ik_manip_guard": (ik["manip_sigma_min"] is not None
                           and ik["manip_sigma_min"] >= THRESHOLDS["ik_manip_sigma_min"]),
        "ik_mouth_front_targets": ik_mf["targets"] >= THRESHOLDS["ik_mouth_front_targets_min"],
        "ik_mouth_front_success": ik_mf["success_rate"]
        >= THRESHOLDS["ik_mouth_front_success_rate_min"],
        "ik_mouth_front_manip": (ik_mf["manip_sigma_min"] is not None
                                 and ik_mf["manip_sigma_min"]
                                 >= THRESHOLDS["ik_mouth_front_manip_sigma_min"]),
        "violating_traj_reached": safety["violating_total"] >= THRESHOLDS["violating_traj_min"],
        "violating_rejection": safety["violating_rejection_rate"]
        >= THRESHOLDS["violating_rejection_rate_min"],
        "adversarial_traj_reached": adv["total"] >= THRESHOLDS["adversarial_traj_min"],
        "adversarial_rejection": adv["rejection_rate"]
        >= THRESHOLDS["adversarial_rejection_rate_min"],
        "adversarial_predicted_hits": adv["predicted_kind_hit_rate"]
        >= THRESHOLDS["adversarial_predicted_kind_hit_rate_min"],
        "delivery_stop_outside": delivery["stop_outside_sphere"] is True,
        "delivery_margin": delivery["margin"]["pass"] is True
        and delivery["margin"]["margin_m"] >= THRESHOLDS["delivery_margin_min_m"],
        "delivery_corridor": (corridor_ok if THRESHOLDS["delivery_corridor_required"] else True),
        "delivery_no_exemption": delivery["exemptions_registered"] == 0,
        "benign_acceptance": safety["benign_acceptance_rate"]
        >= THRESHOLDS["benign_acceptance_rate_min"],
        "reach_png_written": isinstance(reach.get("png"), str)
        if THRESHOLDS["reach_map_png"] else True,
    }
    # 附加自证：跨层一致性（凡实测了的层都要达标）
    for name, v in cross.items():
        if isinstance(v, dict) and "max_pos_err_m" in v:
            checks[f"cross_tier_{name}"] = (
                v["max_pos_err_m"] <= THRESHOLDS["cross_tier_pos_err_max_m"]
                and v["max_ori_err_rad"] <= THRESHOLDS["cross_tier_ori_err_max_rad"]
            )

    passed = all(checks.values())
    report = {
        "module": "cs_sim",
        "date": date.today().isoformat(),
        "cmd": cmd,
        "metrics": metrics,
        "thresholds": THRESHOLDS,
        "checks": checks,
        "pass": bool(passed),
        "wall_time_s": round(time.perf_counter() - t_wall0, 2),
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[cs_sim.eval] report -> {report_path}  pass={passed}")
    if not passed:
        failed = [k for k, ok in checks.items() if not ok]
        print(f"[cs_sim.eval] FAILED checks: {failed}", file=sys.stderr)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
