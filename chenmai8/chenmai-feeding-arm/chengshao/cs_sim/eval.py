"""cs_sim 验收 eval（开发指令 §5.1）。

用法（在包根 ``chengshao/`` 目录下运行）::

    python -m cs_sim.eval --model auto --report reports/sim_eval.json

通过线（§5.1，全部满足才 exit 0）：
  1) 200 个随机可达目标 IK 成功率 >=98%，且位置误差 <=5mm、姿态误差 <=0.05rad；
  2) 500 条随机违规轨迹被安全包络校验器 100% 拒绝；
  3) 生成 reports/reach_map.png。

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

from .arm_model import ArmModel, load_arm
from .backends import IkpyChainBackend
from .model_source import discover_model_file, file_sha256_prefix
from .safety_envelope import EnvelopeValidator

# ---- §5.1 通过线阈值（与报告 thresholds 字段一致） ---------------------------
THRESHOLDS: dict = {
    "ik_targets_min": 200,
    "ik_success_rate_min": 0.98,
    "ik_pos_err_max_m": 0.005,
    "ik_ori_err_max_rad": 0.05,
    "violating_traj_min": 500,
    "violating_rejection_rate_min": 1.0,
    "reach_map_png": True,
    # 附加自证阈值
    "cross_tier_pos_err_max_m": 5e-4,
    "cross_tier_ori_err_max_rad": 5e-3,
    "benign_acceptance_rate_min": 1.0,
}


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
    ap.add_argument("--violating", type=int, default=500, help="违规轨迹数（§5.1: 500）")
    ap.add_argument("--benign", type=int, default=100, help="良性对照轨迹数")
    ap.add_argument("--reach-res", type=float, default=0.03, help="可达空间体素步长 m")
    ap.add_argument("--cross-check-q", type=int, default=150, help="跨层 FK 一致性采样数")
    return ap.parse_args(argv)


# ---------------------------------------------------------------------------
# 各检查项
# ---------------------------------------------------------------------------


def _check_ik(arm: ArmModel, n_targets: int, seed: int) -> dict:
    """§5.1：随机可达目标（由随机构型 FK 生成）的 IK 成功率与误差分布。"""
    rng = np.random.default_rng(seed)
    lower = np.asarray(arm.joint_lower)
    upper = np.asarray(arm.joint_upper)
    n_arm = arm.n_joints - 1  # 末关节为夹爪（不影响 TCP），不参与目标采样
    mid = 0.5 * (lower + upper)
    successes = 0
    pos_errs: list[float] = []
    ori_errs: list[float] = []
    restart_hist: list[int] = []
    for k in range(n_targets):
        q_true = mid.copy()
        q_true[:n_arm] = rng.uniform(lower[:n_arm], upper[:n_arm])
        pose = arm.fk([float(v) for v in q_true])
        tpos, tquat = pose[0:3], pose[3:7]
        seed_q = mid + rng.uniform(-0.4, 0.4, size=len(mid))  # 有扰动的初值
        res = arm.ik_detailed(list(tpos), list(tquat), seed=[float(v) for v in seed_q])
        if res is None or not res.converged:
            continue
        pose2 = arm.fk([float(v) for v in res.q])
        pos_err = float(np.linalg.norm(np.asarray(tpos) - np.asarray(pose2[0:3])))
        ori_err = _quat_angle(tquat, pose2[3:7])
        if pos_err <= THRESHOLDS["ik_pos_err_max_m"] and ori_err <= THRESHOLDS["ik_ori_err_max_rad"]:
            successes += 1
            pos_errs.append(pos_err)
            ori_errs.append(ori_err)
            restart_hist.append(res.restart)
    rate = successes / n_targets if n_targets else 0.0
    return {
        "targets": n_targets,
        "successes": successes,
        "success_rate": rate,
        "pos_err_max_m": max(pos_errs) if pos_errs else None,
        "pos_err_mean_m": float(np.mean(pos_errs)) if pos_errs else None,
        "pos_err_p95_m": float(np.percentile(pos_errs, 95)) if pos_errs else None,
        "ori_err_max_rad": max(ori_errs) if ori_errs else None,
        "ori_err_mean_rad": float(np.mean(ori_errs)) if ori_errs else None,
        "restarts_used_max": max(restart_hist) if restart_hist else 0,
        "restarts_used_mean": float(np.mean(restart_hist)) if restart_hist else 0.0,
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
          f"(pos_err_max={ik['pos_err_max_m']}, ori_err_max={ik['ori_err_max_rad']})")

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

    # ---- 通过判定 -------------------------------------------------------------
    checks: dict[str, bool] = {
        "ik_targets_reached": ik["targets"] >= THRESHOLDS["ik_targets_min"],
        "ik_success_rate": ik["success_rate"] >= THRESHOLDS["ik_success_rate_min"],
        "ik_pos_err": ik["pos_err_max_m"] is not None
        and ik["pos_err_max_m"] <= THRESHOLDS["ik_pos_err_max_m"],
        "ik_ori_err": ik["ori_err_max_rad"] is not None
        and ik["ori_err_max_rad"] <= THRESHOLDS["ik_ori_err_max_rad"],
        "violating_traj_reached": safety["violating_total"] >= THRESHOLDS["violating_traj_min"],
        "violating_rejection": safety["violating_rejection_rate"]
        >= THRESHOLDS["violating_rejection_rate_min"],
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
