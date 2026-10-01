"""cs_arm eval：Mock 执行层验收（开发指令 §5.2；T6 自验收入口）。

用法（包根 chengshao/ 下）::

    python -m cs_arm.eval_mock --report reports/arm_mock_eval.json
    # 仓库根亦可用：python -m chengshao.cs_arm.eval_mock

通过线（§5.2 + T6 硬闸语义，全部满足才 exit 0）：
  1) 注入 ≥1000 条混合指令（良性 / 禁区目标 / 超硬限速 / 不可达 / 对抗性
     关节轨迹）：**0 条违规执行**——必须拒的类别 100% 拒绝且零运动，
     放行的逐条经 cs_sim 包络校验器独立复核通过；
  2) 软件急停：同步闩锁墙钟时延 ≤100ms，注入后立即冻结（位形/速度）
     且不再下发命令；显式复位后恢复运动；
  3) 限速被遵守：执行段实测 TCP 速度 ≤ 接近段限速（0.15 m/s）、关节
     角速度 ≤ 1.5 rad/s；近脸 0.10 m/s 软限速场在规划层拉长时长生效；
  4) 送达走廊：碗→停点整段经包络零拒绝执行，到位误差 ≤2mm，停点在
     面部球面之外，数值安全余量 ≥5mm（复用 cs_sim 校验器口径）；
  5) 看门狗：500ms 静默即跳闸并主动 disable（0.4s 内不误跳）；复位恢复；
  6) 禁入区监控：TCP 落入禁区（面部移向静止臂）即闩锁 face_in_zone +
     冻结 + 拒写；侵入未解除时复位不恢复 clear_to_move。

报告 JSON 字段遵循 §10.2：{module, date, cmd, metrics, thresholds, pass}。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

from .clock import VirtualClock
from .kinematics import plan_motion
from .mock_arm import MockArm
from .safety import SafetyEnvelope
from .interface import ArmCommandRejected

_HERE = Path(__file__).resolve()
_PKG_ROOT = _HERE.parents[1]  # .../chengshao

from cs_schema import ArmCommand, N_ARM_JOINTS, ViolationKind  # noqa: E402
from cs_sim import ArmModel, EnvelopeValidator, load_arm  # noqa: E402
from cs_sim.ik_solver import solve_with_restarts  # noqa: E402

# ---- §5.2 通过线阈值（与报告 thresholds 字段一致） ---------------------------
THRESHOLDS: dict = {
    "injected_min": 1000,
    "must_reject_rate_min": 1.0,
    "violating_executed_max": 0,
    "estop_latency_ms_max": 100.0,
    "estop_freeze_required": True,
    "post_estop_write_rejected": True,
    "tracking_err_max_m": 0.002,
    "measured_tcp_speed_max_mps": 0.15,
    "measured_joint_speed_max_rad_s": 1.5,
    "delivery_margin_min_m": 0.005,
    "stop_outside_face_sphere": True,
    "corridor_all_accepted": True,
    "benign_categories_accepted_min": 1,
    "watchdog_timeout_s": 0.5,
    "watchdog_trips_required": True,
    "watchdog_quiet_required": True,
    "zone_latch_required": True,
}

STOP_CLEARANCE_EPS_M = 1e-9
SPEED_EPS = 1e-6

BOWL = np.array([0.22, -0.18, 0.02])
TRANSIT = np.array([0.25, -0.09, 0.20])


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="python -m cs_arm.eval_mock",
        description="cs_arm eval: MockArm virtual execution + SafetyEnvelope hard gate",
    )
    ap.add_argument("--report", default=str(_PKG_ROOT / "reports" / "arm_mock_eval.json"),
                    help="报告 JSON 输出路径（缺省包根 reports/arm_mock_eval.json）")
    ap.add_argument("--inject", type=int, default=1000,
                    help="注入指令总数下限（§5.2 为 1000）")
    return ap.parse_args(argv)


# ---- 小工具 ------------------------------------------------------------------


def cart_cmd(point, speed: float = 0.05, timeout: float = 300.0) -> ArmCommand:
    return ArmCommand(mode="cartesian", target=[float(v) for v in point],
                      max_speed=speed, timeout_s=timeout)


def joints_cmd(target, speed: float = 0.5, timeout: float = 300.0) -> ArmCommand:
    return ArmCommand(mode="joints", target=[float(v) for v in target],
                      max_speed=speed, timeout_s=timeout)


def stream_to(env: SafetyEnvelope, clock: VirtualClock, point, speed: float = 0.05,
              step_m: float = 0.02) -> tuple[float, bool]:
    """流式送达 point；返回 (末端跟踪误差 m, 是否全程零拒绝)。"""
    target = np.asarray(point, dtype=float)
    cur = np.asarray(env.read().ee_pos, dtype=float)
    n = max(1, int(np.ceil(float(np.linalg.norm(target - cur)) / step_m)))
    err = float("inf")
    ok = True
    for i in range(1, n + 1):
        wp = cur + (target - cur) * (i / n)
        try:
            env.write(cart_cmd(wp, speed=speed))
        except ArmCommandRejected:
            ok = False
            break
        clock.advance_s(env.last_decision["duration_s"] + 0.005)
        err = float(np.linalg.norm(np.asarray(env.read().ee_pos) - wp))
    return err, ok


def measure_motion_speeds(env: SafetyEnvelope, clock: VirtualClock, samples: int = 10,
                          acc: dict | None = None) -> dict:
    """对当前在途运动按仿真时间采样，累计实测最大 TCP/关节速度。"""
    acc = acc if acc is not None else {"max_tcp_mps": 0.0, "max_joint_rad_s": 0.0}
    T = env.last_decision.get("duration_s", 0.0)
    if T <= 0.0:
        return acc
    prev = np.asarray(env.read().ee_pos, dtype=float)
    prev_t = clock.now_ns() / 1e9
    for _ in range(samples):
        clock.advance_s(T / samples)
        st = env.read()
        t = st.ts_ns / 1e9
        d = float(np.linalg.norm(np.asarray(st.ee_pos, dtype=float) - prev))
        if t > prev_t:
            acc["max_tcp_mps"] = max(acc["max_tcp_mps"], d / (t - prev_t))
        acc["max_joint_rad_s"] = max(acc["max_joint_rad_s"],
                                     float(np.max(np.abs(st.joint_vel))))
        prev = np.asarray(st.ee_pos, dtype=float)
        prev_t = t
    return acc


# ---- 注入批（§5.2：1000 条命令注入 0 条违规执行） ----------------------------


def run_injection(env: SafetyEnvelope, clock: VirtualClock, mock: MockArm,
                  model: ArmModel, validator: EnvelopeValidator,
                  n_min: int, rng: np.random.Generator) -> dict:
    counts: dict[str, dict] = {}
    violating_executed = 0
    speed_acc = {"max_tcp_mps": 0.0, "max_joint_rad_s": 0.0}

    def record(cat: str, rejected: bool) -> None:
        c = counts.setdefault(cat, {"n": 0, "rejected": 0})
        c["n"] += 1
        if rejected:
            c["rejected"] += 1

    def try_write(cmd: ArmCommand, cat: str) -> None:
        nonlocal violating_executed
        q_pre = np.asarray(env.read().joint_pos, dtype=float)
        try:
            env.write(cmd)
        except ArmCommandRejected:
            record(cat, True)
            clock.advance_s(0.005)
            drift = float(np.max(np.abs(np.asarray(env.read().joint_pos) - q_pre)))
            if drift != 0.0:  # 拒绝后零运动（硬闸语义）
                violating_executed += 1
            return
        record(cat, False)
        if env.last_decision.get("noop"):
            return
        d = env.last_decision
        if d["eff_joint_speed_rad_s"] > 1.5 + SPEED_EPS or \
                d["eff_linear_speed_mps"] > d["linear_bound_mps"] + SPEED_EPS:
            violating_executed += 1  # 放行指令的决策速度超界
        T = d["duration_s"]
        clock.advance_s(T + 0.005)
        st = env.read()
        q_post = np.asarray(st.joint_pos, dtype=float)
        rep = validator.check_joint_trajectory(
            [0.0, max(T, 1e-3)], [q_pre.tolist(), q_post.tolist()], model,
            label="injection_audit")
        if rep["rejected"] or validator.point_zone_violation(
                np.asarray(st.ee_pos, dtype=float)) is not None:
            violating_executed += 1  # 放行指令的独立复核未过
        speed_acc["max_joint_rad_s"] = max(speed_acc["max_joint_rad_s"],
                                           float(np.max(np.abs(st.joint_vel))))

    face = np.asarray(validator.config.face_center, dtype=float)
    torso = next(z for z in validator.config.zones if z.name == "torso")

    # 目标计数：总量达到 n_min 后按比例收尾（见本函数末尾的补齐循环）
    plan = [
        ("benign_cartesian", 340), ("benign_joints", 200),
        ("face_sphere_target", 120), ("torso_target", 80),
        ("joints_zone_target", 100), ("unreachable", 8),
        ("joint_speed_over_hard", 60), ("cart_speed_over_hard", 40),
    ]
    for cat, n in plan:
        for _ in range(n):
            if cat == "benign_cartesian":
                cur = np.asarray(env.read().ee_pos, dtype=float)
                cand = None
                for _ in range(20):
                    delta = np.array([rng.uniform(-0.05, 0.02),
                                      rng.uniform(-0.05, 0.05),
                                      rng.uniform(-0.04, 0.04)])  # x 向 -X 偏置（离脸）
                    c = cur + delta
                    if (validator.point_zone_violation(c) is None
                            and validator.min_zone_clearance(c) > 0.02
                            and 0.05 <= c[0] <= 0.32 and 0.03 <= c[2] <= 0.38):
                        cand = c
                        break
                if cand is None:
                    continue
                try_write(cart_cmd(cand, speed=0.05), cat)
            elif cat == "benign_joints":
                q0 = np.asarray(env.read().joint_pos, dtype=float)
                cand = np.clip(q0 + rng.uniform(-0.08, 0.08, size=N_ARM_JOINTS),
                               model.joint_lower, model.joint_upper)
                cand[5] = rng.uniform(-0.10, 1.70)  # 夹爪行程
                try_write(joints_cmd(cand, speed=0.4), cat)
            elif cat == "face_sphere_target":
                direction = rng.normal(size=3)
                direction /= np.linalg.norm(direction)
                p = face + direction * rng.uniform(0.0, 0.10)
                try_write(cart_cmd(p, speed=0.05), cat)
            elif cat == "torso_target":
                p = (np.asarray(torso.p1) + rng.uniform(0.2, 0.8)
                     * (np.asarray(torso.p2) - np.asarray(torso.p1)))
                try_write(cart_cmd(p, speed=0.05), cat)
            elif cat == "joints_zone_target":
                # 关节目标：TCP 端点在面部球内（pos-only 解 10 个球内点轮换）
                direction = rng.normal(size=3)
                direction /= np.linalg.norm(direction)
                p = face + direction * rng.uniform(0.0, 0.08)
                res = solve_with_restarts(model._backend, p, np.eye(3),
                                          seed=mock.current_q(), pos_only=True)
                if res is None or not res.converged:
                    continue
                qz = np.clip(res.q, model.joint_lower, model.joint_upper)
                qz[5] = mock.current_q()[5]
                try_write(joints_cmd(qz, speed=0.1), cat)
            elif cat == "unreachable":
                try_write(cart_cmd([2.5, 2.5, 2.5], speed=0.1), cat)
            elif cat == "joint_speed_over_hard":
                q0 = np.asarray(env.read().joint_pos, dtype=float)
                cand = np.clip(q0 + rng.uniform(-0.2, 0.2, size=N_ARM_JOINTS),
                               model.joint_lower, model.joint_upper)
                try_write(joints_cmd(cand, speed=float(rng.uniform(2.0, 8.0))), cat)
            elif cat == "cart_speed_over_hard":
                cur = np.asarray(env.read().ee_pos, dtype=float)
                try_write(cart_cmd(cur + np.array([-0.02, 0.0, 0.0]),
                                   speed=float(rng.uniform(0.2, 1.0))), cat)

    # 对抗性关节轨迹（cs_sim 独立 oracle 样本；teleport 到样本起点复现轨迹）
    from cs_sim.adversarial import build_adversarial_cases

    cases = build_adversarial_cases(model, validator, n_joint_speed=6,
                                    n_link_sweep=4, n_tcp_arc=6, seed=20260928)
    for case in cases:
        qa = np.asarray(case.q_list[0], dtype=float)
        mock.teleport(qa)
        q1 = np.asarray(case.q_list[-1], dtype=float)
        dq = float(np.max(np.abs(q1 - qa)))
        dur = float(case.times_s[-1] - case.times_s[0])
        try_write(joints_cmd(q1, speed=max(dq / dur, 1e-4), timeout=3600.0),
                  "adversarial")

    # 补齐到 n_min（补良性关节小步——短平快的确定性注入）
    total = sum(c["n"] for c in counts.values())
    while total < n_min:
        q0 = np.asarray(env.read().joint_pos, dtype=float)
        cand = np.clip(q0 + rng.uniform(-0.03, 0.03, size=N_ARM_JOINTS),
                       model.joint_lower, model.joint_upper)
        try_write(joints_cmd(cand, speed=0.4), "benign_joints")
        total += 1

    by_cat = {k: {**v, "rate": v["rejected"] / v["n"] if v["n"] else 0.0}
              for k, v in counts.items()}
    must_reject = ("face_sphere_target", "torso_target", "joints_zone_target",
                   "unreachable", "joint_speed_over_hard", "cart_speed_over_hard",
                   "adversarial")
    rates = [by_cat[c]["rate"] for c in must_reject if by_cat.get(c, {}).get("n")]
    return {
        "injected_total": total,
        "by_category": by_cat,
        "must_reject_rate_min_observed": min(rates) if rates else 0.0,
        "violating_executed": violating_executed,
        "speeds": speed_acc,
    }


# ---- 主流程 ------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    t_start = time.perf_counter()
    metrics: dict = {}
    checks: dict[str, bool] = {}

    model = load_arm("auto")
    validator = EnvelopeValidator()
    clock = VirtualClock()
    mock = MockArm(model, validator=validator, clock=clock)
    env = SafetyEnvelope(mock, model=model, validator=validator, clock=clock)
    env.enable()
    metrics["model_tier"] = model.tier
    metrics["n_joints"] = model.n_joints

    # ---- 1) 送达停点与数值安全余量 -------------------------------------------
    margin = validator.delivery_margin()
    stop = validator.delivery_stop_point()
    metrics["delivery"] = {**margin,
                           "stop_point_m": [round(float(v), 4) for v in stop]}
    checks["delivery_margin"] = margin["pass"] and margin["margin_m"] >= THRESHOLDS[
        "delivery_margin_min_m"]
    checks["stop_outside_face_sphere"] = (
        float(np.linalg.norm(stop - validator.config.face_center))
        >= validator.face_radius - STOP_CLEARANCE_EPS_M
        and validator.point_zone_violation(stop) is None
    )

    # ---- 2) 送达走廊（碗→停点，整段经包络） + 软急停注入 + 恢复 --------------
    speeds = {"max_tcp_mps": 0.0, "max_joint_rad_s": 0.0}
    err_bowl, ok1 = stream_to(env, clock, BOWL)
    speeds = measure_motion_speeds(env, clock, acc=speeds)
    lifts = [BOWL + np.array([0.0, 0.0, 0.10])]
    for a, b in ((BOWL, BOWL + np.array([0.0, 0.0, 0.10])),):
        n = max(1, int(np.ceil(float(np.linalg.norm(b - a)) / 0.02)))
        lifts = [a + (b - a) * (i / n) for i in range(1, n + 1)]
    ok_all = ok1
    for wp in lifts:  # 抬勺
        env.write(cart_cmd(wp))
        ok_all = ok_all and env.last_decision["accepted"]
        clock.advance_s(env.last_decision["duration_s"] + 0.005)
        env.read()

    # 软急停：抬勺后向转运点飞行中段注入
    cur = np.asarray(env.read().ee_pos, dtype=float)
    wp_mid = cur + (TRANSIT - cur) * 0.4
    env.write(cart_cmd(wp_mid))
    clock.advance_s(env.last_decision["duration_s"] * 0.5)
    st_mid = env.read()
    q_mid = np.asarray(st_mid.joint_pos, dtype=float)
    t0 = time.perf_counter()
    env.estop()
    estop_ms = (time.perf_counter() - t0) * 1e3
    clock.advance_s(0.2)
    st_after = env.read()
    frozen = (float(np.max(np.abs(np.asarray(st_after.joint_pos) - q_mid))) == 0.0
              and all(v == 0.0 for v in st_after.joint_vel)
              and not mock.in_motion)
    ss_estop = env.safety_state()
    post_reject = False
    try:
        env.write(cart_cmd(TRANSIT))
    except ArmCommandRejected as exc:
        post_reject = exc.reason == "not_clear_to_move"
    env.reset()
    err_stop, ok2 = stream_to(env, clock, TRANSIT)
    err_stop, ok2 = stream_to(env, clock, stop)
    speeds = measure_motion_speeds(env, clock, acc=speeds)
    final_err = float(np.linalg.norm(np.asarray(env.read().ee_pos) - stop))

    metrics["estop"] = {
        "latency_ms": round(estop_ms, 3),
        "frozen": frozen,
        "post_estop_write_rejected": post_reject,
        "violation_after": str(ss_estop.violation),
        "clear_to_move_after": ss_estop.clear_to_move,
        "recovered": ok2,
    }
    checks["estop"] = (estop_ms <= THRESHOLDS["estop_latency_ms_max"]
                       and frozen and post_reject
                       and ss_estop.violation is ViolationKind.WATCHDOG
                       and ss_estop.clear_to_move is False
                       and ok2)
    metrics["corridor"] = {
        "waypoints_all_accepted": bool(ok_all and ok2),
        "err_bowl_m": round(err_bowl, 6),
        "err_stop_m": round(final_err, 6),
        "measured_max_tcp_mps": round(speeds["max_tcp_mps"], 4),
        "measured_max_joint_rad_s": round(speeds["max_joint_rad_s"], 4),
        "cartesian_rewrites": env.stats["cartesian_rewritten_to_joints"],
    }
    checks["corridor"] = (ok_all and ok2
                          and err_bowl <= THRESHOLDS["tracking_err_max_m"]
                          and final_err <= THRESHOLDS["tracking_err_max_m"])
    checks["measured_speeds"] = (
        speeds["max_tcp_mps"] <= THRESHOLDS["measured_tcp_speed_max_mps"] + SPEED_EPS
        and speeds["max_joint_rad_s"] <= THRESHOLDS["measured_joint_speed_max_rad_s"]
        + SPEED_EPS)
    checks["cartesian_rewrite_works"] = env.stats["cartesian_rewritten_to_joints"] > 0

    # ---- 3) 注入批（≥1000 条，0 违规执行） -----------------------------------
    rng = np.random.default_rng(20260928)
    inj = run_injection(env, clock, mock, model, validator, max(1000, args.inject), rng)
    metrics["injection"] = {
        "injected_total": inj["injected_total"],
        "violating_executed": inj["violating_executed"],
        "must_reject_rate_min_observed": inj["must_reject_rate_min_observed"],
        "by_category": inj["by_category"],
    }
    checks["injection_no_violation_executed"] = (
        inj["injected_total"] >= THRESHOLDS["injected_min"]
        and inj["violating_executed"] == 0
        and inj["must_reject_rate_min_observed"] >= THRESHOLDS["must_reject_rate_min"])
    benign_ok = all(inj["by_category"].get(c, {}).get("rejected", 0) >= 1
                    for c in ())  # 占位：良性类别在下方单独判
    benign_accepted = sum(inj["by_category"].get(c, {}).get("n", 0)
                          - inj["by_category"].get(c, {}).get("rejected", 0)
                          for c in ("benign_cartesian", "benign_joints"))
    checks["benign_accepted"] = benign_accepted >= THRESHOLDS["benign_categories_accepted_min"]
    del benign_ok

    # ---- 4) 近脸软限速场（规划层证明；缺省几何下该壳层被连杆封锁） -----------
    from cs_sim.ik_solver import solve_with_restarts

    mouth2 = [0.26, -0.04, 0.16]
    cfg2 = {
        "mouth_point_m": mouth2,
        "forbidden_zones": [
            {"type": "sphere", "name": "face", "center_m": mouth2, "radius_m": 0.12},
            {"type": "capsule", "name": "torso", "p1_m": [0.48, 0.0, -0.10],
             "p2_m": [0.48, 0.0, 0.22], "radius_m": 0.15},
        ],
        "speed_limits_mps": {"approach": 0.15, "near_face": 0.10},
        "near_face_distance_m": 0.15,
    }
    val2 = EnvelopeValidator(cfg2)
    A = np.array([0.19, -0.06, 0.05])
    B = np.array([0.21, -0.06, 0.05])
    res_a = solve_with_restarts(model._backend, A, np.eye(3), seed=None,
                                pos_only=True, restarts=32)
    res_b = solve_with_restarts(model._backend, B, np.eye(3),
                                seed=None if res_a is None else res_a.q,
                                pos_only=True, restarts=32)
    soft_ok = bool(res_a is not None and res_a.converged and res_b is not None
                   and res_b.converged
                   and 0.12 < float(np.linalg.norm(A - np.asarray(mouth2))) < 0.15
                   and 0.12 < float(np.linalg.norm(B - np.asarray(mouth2))) < 0.15)
    if soft_ok:
        qa = np.clip(res_a.q, model.joint_lower, model.joint_upper)
        qb = np.clip(res_b.q, model.joint_lower, model.joint_upper)
        info = plan_motion(model, val2, qa, qb,
                           cart_cmd(B, speed=0.15), 1.5)
        soft_ok = (info["linear_bound_mps"] == 0.10
                   and info["eff_linear_speed_mps"] <= 0.10 + SPEED_EPS)
        metrics["near_face_soft_limit"] = {
            "segment_in_band_m": [round(float(np.linalg.norm(A - np.asarray(mouth2))), 3),
                                  round(float(np.linalg.norm(B - np.asarray(mouth2))), 3)],
            "requested_mps": 0.15,
            "effective_mps": round(info["eff_linear_speed_mps"], 4),
        }
    checks["near_face_soft_limit"] = soft_ok

    # ---- 5) 看门狗（500ms 静默跳闸 + 主动 disable；0.4s 不误跳） -------------
    clock2 = VirtualClock()
    mock2 = MockArm(model, validator=validator, clock=clock2)
    env2 = SafetyEnvelope(mock2, model=model, validator=validator, clock=clock2)
    env2.enable()
    clock2.advance_s(0.4)
    quiet_ok = env2.poll().violation is ViolationKind.NONE
    clock2.advance_s(0.2)  # 累计 0.6s 静默
    ss_wd = env2.poll()
    wd_ok = (ss_wd.violation is ViolationKind.WATCHDOG
             and ss_wd.clear_to_move is False and mock2.enabled is False)
    env2.reset()
    env2.enable()
    q0 = np.asarray(env2.read().joint_pos, dtype=float)
    rec = q0.copy()
    rec[0] = float(np.clip(rec[0] + 0.05, model.joint_lower[0], model.joint_upper[0]))
    wd_recovered = True
    try:
        env2.write(joints_cmd(rec, speed=0.4))
        clock2.advance_s(env2.last_decision["duration_s"] + 0.01)
        wd_recovered = float(abs(env2.read().joint_pos[0] - rec[0])) < 1e-9
    except ArmCommandRejected:
        wd_recovered = False
    metrics["watchdog"] = {"timeout_s": 0.5, "quiet_0p4s_no_trip": quiet_ok,
                           "trips_at_0p6s": wd_ok, "recovered": wd_recovered}
    checks["watchdog"] = quiet_ok and wd_ok and wd_recovered

    # ---- 6) 禁入区监控（面部移到静止臂位 → 闩锁 + 冻结 + 拒写） --------------
    clock3 = VirtualClock()
    mock3 = MockArm(model, validator=validator, clock=clock3)
    mock3.enable()
    env3 = SafetyEnvelope(mock3, model=model, validator=validator, clock=clock3)
    env3.enable()
    err_s, ok_s = stream_to(env3, clock3, stop)
    cfg3 = dict(cfg2)
    cfg3["mouth_point_m"] = [float(v) for v in stop]
    cfg3["forbidden_zones"] = [
        {"type": "sphere", "name": "face", "center_m": [float(v) for v in stop],
         "radius_m": 0.12},
        {"type": "capsule", "name": "torso", "p1_m": [0.48, 0.0, -0.10],
         "p2_m": [0.48, 0.0, 0.22], "radius_m": 0.15},
    ]
    val3 = EnvelopeValidator(cfg3)
    env3b = SafetyEnvelope(mock3, model=model, validator=val3, clock=clock3)
    env3b.enable()
    ss_zone = env3b.poll()
    zone_write_blocked = False
    try:
        env3b.write(cart_cmd([0.20, 0.0, 0.10]))
    except ArmCommandRejected as exc:
        zone_write_blocked = exc.reason == "not_clear_to_move"
    relatched = env3b.reset().violation is ViolationKind.FACE_IN_ZONE
    metrics["zone_monitor"] = {
        "arm_stopped_at_stop_point": bool(ok_s and err_s <= THRESHOLDS["tracking_err_max_m"]),
        "latched": ss_zone.violation is ViolationKind.FACE_IN_ZONE,
        "human_zone_violation": ss_zone.human_zone_violation,
        "clear_to_move": ss_zone.clear_to_move,
        "write_blocked": zone_write_blocked,
        "reset_reannounces_while_intruded": relatched,
    }
    checks["zone_monitor"] = (
        ok_s and ss_zone.violation is ViolationKind.FACE_IN_ZONE
        and ss_zone.human_zone_violation and not ss_zone.clear_to_move
        and zone_write_blocked and relatched)

    # ---- 汇总 -----------------------------------------------------------------
    elapsed = time.perf_counter() - t_start
    metrics["stats"] = {"envelope": env.stats, "mock": mock.stats}
    metrics["elapsed_s"] = round(elapsed, 2)
    passed = all(checks.values())
    report = {
        "module": "cs_arm",
        "date": date.today().isoformat(),
        "cmd": "python -m cs_arm.eval_mock --report reports/arm_mock_eval.json  (cwd=包根 chengshao/)",
        "metrics": metrics,
        "thresholds": THRESHOLDS,
        "checks": {k: bool(v) for k, v in checks.items()},
        "pass": bool(passed),
        "notes": (
            "近脸 0.10 m/s 软限速场在规划层证明（缺省几何下 0.12-0.15m 壳层被 "
            "30mm 连杆胶囊封锁：TCP 名义停点 0.17m + 勺尖前伸 0.08m 覆盖该壳层，"
            "执行层限速证据由走廊实测与硬限拒绝覆盖）。violation 状态仅保留给"
            "真实安全事件（急停/看门狗/禁入区），指令拒绝不计入——拒绝是包络在"
            "正确工作。"
        ),
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"cs_arm.eval_mock: pass={passed} elapsed={elapsed:.1f}s")
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"report -> {report_path}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
