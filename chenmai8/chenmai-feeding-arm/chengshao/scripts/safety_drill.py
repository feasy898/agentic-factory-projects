#!/usr/bin/env python3
"""安全演练入口（开发指令 §5.9 第 8 行；hw-toolchain spec §3 安全实测）。

用法（cwd=包根 chengshao/）::

    python scripts/safety_drill.py --cases head_turn,estop,face_intrude --trials 20
        # 真机：FeetechArm 骨架阶段 → HardwareUnavailable → exit 2
    python scripts/safety_drill.py --cases head_turn,estop,face_intrude --trials 20 --mock
        # MockArm 注入演练（cs_arm.SafetyEnvelope 硬闸链路）→ 报告 + exit 0

三组用例（每用例 --trials 次独立演练，每次全新 MockArm+SafetyEnvelope）：
  - head_turn：送达途中用户转头（head_yaw > 25°）→ 驱动层停止下发 + halt，
    断言冻结、TCP 不入禁入区、保持期零指令、解除后可续走（"停止"）；
  - estop：送达途中软件急停（空格键 latch 语义）→ 同步闩锁墙钟时延 ≤100ms、
    立即冻结、此后写指令拒绝（not_clear_to_move）、显式复位后可恢复；
  - face_intrude：送达走廊全程 TCP 禁入区 0 次侵入（逐 waypoint 审计）；
    面部移向静止臂 → 包络闩锁 face_in_zone + 冻结 + 拒写；解除后复位并
    后撤 ≥4.5cm（"后撤"，§5.6 的 5cm 后撤意图）。

通过线（§5.9）：20/20 停止或后撤；禁入区侵入 0 次；急停 ≤100ms。

exit：0 = 全部用例达标；1 = 有用例未达标；2 = fail-closed（硬件缺失 /
HardwareUnavailable / 用法错误）。**mock 结论不等于真机实测结论**（报告显式
标注）：真机演练在 D3+ 硬件到场后按同构检查链执行。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve()
_PKG_ROOT = _HERE.parents[1]
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from cs_arm._hw_common import (  # noqa: E402
    EXIT_CHECKS_FAILED,
    EXIT_HW_UNAVAILABLE,
    EXIT_OK,
    fail_closed,
    load_model_cached,
    resolve_path,
    write_report,
)
from cs_arm.clock import VirtualClock  # noqa: E402
from cs_arm.feetech import FeetechArm, FeetechArmConfig, HardwareUnavailable  # noqa: E402
from cs_arm.interface import ArmCommandRejected  # noqa: E402
from cs_arm.mock_arm import MockArm  # noqa: E402
from cs_arm.safety import SafetyEnvelope  # noqa: E402
from cs_arm.eval_mock import BOWL, cart_cmd  # noqa: E402
from cs_schema import ViolationKind  # noqa: E402
from cs_sim import EnvelopeValidator  # noqa: E402

#: §5.9 通过线
THRESHOLDS: dict = {
    "trials": 20,
    "stop_or_retreat_rate_min": 1.0,
    "estop_latency_ms_max": 100.0,
    "zone_intrusion_count_max": 0,
    "retreat_min_m": 0.045,   # 5cm 后撤意图的数值下界（跟踪误差容限）
    "hold_write_count_max": 0,  # 转头保持期不允许新指令
}

CASES = ("head_turn", "estop", "face_intrude")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="python scripts/safety_drill.py",
        description="安全演练：head_turn / estop / face_intrude（20/20 停止或后撤）",
    )
    ap.add_argument("--cases", default="head_turn,estop,face_intrude",
                    help="逗号分隔用例（缺省全部三组）")
    ap.add_argument("--trials", type=int, default=20, help="每用例演练次数（§5.9 为 20）")
    ap.add_argument("--mock", action="store_true",
                    help="MockArm 注入演练（无硬件；当前唯一可跑通道）")
    ap.add_argument("--port", default="", help="真机串口（骨架阶段 fail-closed）")
    ap.add_argument("--report", default=None,
                    help="报告 JSON（缺省 reports/safety_drill_eval.json）")
    return ap.parse_args(argv)


# ---- 演练辅助 --------------------------------------------------------------------

def _stream(env: SafetyEnvelope, clock: VirtualClock, point, speed: float = 0.05,
            step_m: float = 0.02, validator: EnvelopeValidator | None = None,
            audit: dict | None = None,
            journal: list | None = None) -> tuple[float, bool]:
    """流式送达 point（eval_mock.stream_to 同口径）+ 禁入区逐点审计。

    ``journal`` 非空时记录每个被接受途经点的实际 TCP（原路退回用：包络放行
    的段链按**逐段逆序**回放是可通行的，段间插值的"新"途经点会换 IK 支、
    不保证可通——见 cs_orchestra.RouteFollower 的 jtrack 逆序同口径）。
    """
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
        clock.advance_s(float(env.last_decision.get("duration_s") or 0.0) + 0.005)
        state = env.read()
        tcp = np.asarray(state.ee_pos, dtype=float)
        if journal is not None:
            journal.append(tcp.copy())
        if validator is not None and audit is not None:
            if validator.point_zone_violation(tcp) is not None:
                audit["zone_intrusions"] += 1  # 被放行的轨迹落进禁入区：记违规执行
        err = float(np.linalg.norm(tcp - wp))
    return err, ok


def _new_rig(model, validator: EnvelopeValidator):
    clock = VirtualClock()
    mock = MockArm(model, validator=validator, clock=clock)
    env = SafetyEnvelope(mock, model=model, validator=validator, clock=clock)
    env.enable()
    return clock, mock, env


# ---- 三组用例（单次演练） ---------------------------------------------------------

def drill_head_turn(model, validator: EnvelopeValidator, stop_point: np.ndarray) -> dict:
    """送达途中转头 → 停止：冻结 + 保持期零指令 + TCP 不入区 + 解除后续走。"""
    clock, mock, env = _new_rig(model, validator)
    _, ok_bowl = _stream(env, clock, BOWL, validator=validator)
    # 朝停点流式飞行，中段注入转头
    cur = np.asarray(env.read().ee_pos, dtype=float)
    mid = cur + (stop_point - cur) * 0.5
    _, ok_mid = _stream(env, clock, mid, validator=validator)
    q_at_turn = np.asarray(env.read().joint_pos, dtype=float)
    writes_before_hold = env.stats["written"]

    env.halt()  # 驱动层响应转头：不再下发新指令段 + 冻结
    clock.advance_s(0.5)  # 保持窗（1s 判定窗内前段）
    st_hold = env.read()
    frozen = (float(np.max(np.abs(np.asarray(st_hold.joint_pos, dtype=float)
                                  - q_at_turn))) == 0.0
              and all(v == 0.0 for v in st_hold.joint_vel)
              and not mock.in_motion)
    hold_writes = env.stats["written"] - writes_before_hold
    tcp_hold = np.asarray(st_hold.ee_pos, dtype=float)
    tcp_clear = validator.point_zone_violation(tcp_hold) is None
    ss = env.safety_state()
    no_violation = (ss.violation is ViolationKind.NONE and ss.clear_to_move)

    # 转头解除 → 原地续走到停点
    err_stop, ok_resume = _stream(env, clock, stop_point, validator=validator)
    return {
        "ok": bool(ok_bowl and ok_mid and frozen
                   and hold_writes <= THRESHOLDS["hold_write_count_max"]
                   and tcp_clear and no_violation and ok_resume
                   and err_stop <= 0.002),
        "frozen": frozen, "hold_writes": hold_writes,
        "tcp_clear_during_hold": tcp_clear,
        "violation": str(ss.violation),
        "resumed_and_arrived": bool(ok_resume and err_stop <= 0.002),
        "err_stop_m": round(err_stop, 6),
    }


def drill_estop(model, validator: EnvelopeValidator, stop_point: np.ndarray) -> dict:
    """送达途中软件急停：同步闩锁 ≤100ms + 冻结 + 拒写 + 复位恢复。"""
    clock, mock, env = _new_rig(model, validator)
    _, ok_bowl = _stream(env, clock, BOWL, validator=validator)
    cur = np.asarray(env.read().ee_pos, dtype=float)
    mid = cur + (stop_point - cur) * 0.5
    _, ok_mid = _stream(env, clock, mid, validator=validator)
    q_mid = np.asarray(env.read().joint_pos, dtype=float)

    t0 = time.perf_counter()
    env.estop()
    latency_ms = (time.perf_counter() - t0) * 1e3
    clock.advance_s(0.25)
    st_after = env.read()
    frozen = (float(np.max(np.abs(np.asarray(st_after.joint_pos, dtype=float)
                                  - q_mid))) == 0.0
              and all(v == 0.0 for v in st_after.joint_vel)
              and not mock.in_motion)
    post_reject_reason = None
    try:
        env.write(cart_cmd(stop_point))
    except ArmCommandRejected as exc:
        post_reject_reason = exc.reason
    ss = env.safety_state()
    latched = (ss.estop_latched and not ss.clear_to_move
               and ss.violation is ViolationKind.WATCHDOG)
    # 复位 → 恢复运动到停点
    env.reset()
    err_stop, ok_resume = _stream(env, clock, stop_point, validator=validator)
    return {
        "ok": bool(ok_bowl and ok_mid and frozen
                   and latency_ms <= THRESHOLDS["estop_latency_ms_max"]
                   and post_reject_reason == "not_clear_to_move"
                   and latched and ok_resume and err_stop <= 0.002),
        "latency_ms": round(latency_ms, 3),
        "frozen": frozen,
        "post_estop_write_rejected": post_reject_reason,
        "latched_state": {"estop_latched": bool(ss.estop_latched),
                          "clear_to_move": bool(ss.clear_to_move),
                          "violation": str(ss.violation)},
        "recovered": bool(ok_resume and err_stop <= 0.002),
        "err_stop_m": round(err_stop, 6),
    }


def drill_face_intrude(model, validator: EnvelopeValidator,
                       stop_point: np.ndarray) -> dict:
    """走廊零侵入 + 面部移向静止臂 → 闩锁/冻结/拒写 + 解除后复位并后撤。"""
    clock, mock, env = _new_rig(model, validator)
    audit = {"zone_intrusions": 0}
    journey: list = []  # 送达走廊的被接受途经点（原路退回用）
    err_bowl, ok_bowl = _stream(env, clock, BOWL, validator=validator, audit=audit)
    err_stop, ok_stop = _stream(env, clock, stop_point, validator=validator,
                                audit=audit, journal=journey)
    delivered = bool(ok_bowl and ok_stop and err_stop <= 0.002)

    # 面部移向静止臂（用户前倾）：以当前 TCP 为口部点重建包络
    tcp = np.asarray(env.read().ee_pos, dtype=float)
    cfg2 = {
        "mouth_point_m": [float(v) for v in tcp],
        "forbidden_zones": [
            {"type": "sphere", "name": "face", "center_m": [float(v) for v in tcp],
             "radius_m": 0.12},
            {"type": "capsule", "name": "torso", "p1_m": [0.48, 0.0, -0.10],
             "p2_m": [0.48, 0.0, 0.22], "radius_m": 0.15},
        ],
        "speed_limits_mps": {"approach": 0.15, "near_face": 0.10},
        "near_face_distance_m": 0.15,
    }
    validator2 = EnvelopeValidator(cfg2)
    env2 = SafetyEnvelope(mock, model=model, validator=validator2, clock=clock)
    env2.enable()
    ss2 = env2.poll()  # 巡检即闩锁（TCP 在重建的面部球内）
    latched = (ss2.violation is ViolationKind.FACE_IN_ZONE
               and ss2.human_zone_violation and not ss2.clear_to_move)
    mock_before = np.asarray(env2.read().joint_pos, dtype=float)
    post_reject_reason = None
    try:
        env2.write(cart_cmd([0.20, 0.0, 0.10]))
    except ArmCommandRejected as exc:
        post_reject_reason = exc.reason
    clock.advance_s(0.2)
    frozen = float(np.max(np.abs(np.asarray(env2.read().joint_pos, dtype=float)
                                 - mock_before))) == 0.0

    # 显式复位：侵入未解除（包络仍以"面部在 TCP 处"判定）→ 如实重新闩锁
    # （契约语义：clear_to_move 不会在侵入状态下变真）
    reset_state = env2.reset()
    reset_reannounces = reset_state.violation is ViolationKind.FACE_IN_ZONE

    # 面部退回（用户后仰）→ 恢复原包络（新闩锁态为干净）→ 后撤 ≥5cm。
    # 后撤路径 = 送达走廊**逐段逆序**回放（§5.6"复位后原路退回"；段间插值的
    # 新途经点会换 IK 支、连杆扫掠不保证可通——只有已被包络放行的段链本身
    # 是可通行证据）。累计位移 ≥5cm 即停（远离用户方向）。
    env3 = SafetyEnvelope(mock, model=model, validator=validator, clock=clock)
    env3.enable()
    clear_after_reset = bool(env3.poll().clear_to_move)
    retreat_m = 0.0
    ok_ret = True
    for p in reversed(journey[:-1]):
        try:
            env3.write(cart_cmd(p, speed=0.05))
        except ArmCommandRejected as exc:
            ok_ret = False
            break
        clock.advance_s(float(env3.last_decision.get("duration_s") or 0.0) + 0.005)
        tcp_ret = np.asarray(env3.read().ee_pos, dtype=float)
        retreat_m = float(np.linalg.norm(tcp_ret - tcp))
        if retreat_m >= 0.05:
            break
    err_ret = retreat_m
    return {
        "ok": bool(delivered and audit["zone_intrusions"] == 0 and latched
                   and post_reject_reason == "not_clear_to_move" and frozen
                   and reset_reannounces and clear_after_reset and ok_ret
                   and retreat_m >= THRESHOLDS["retreat_min_m"]),
        "zone_intrusions": audit["zone_intrusions"],
        "latched": latched,
        "write_blocked": post_reject_reason,
        "frozen": frozen,
        "reset_reannounces_while_intruded": reset_reannounces,
        "clear_after_face_retreats": clear_after_reset,
        "retreat_m": round(retreat_m, 4),
        "err_stop_m": round(err_stop, 6),
    }


# ---- 主流程 ----------------------------------------------------------------------

def _run_mock(cases: list[str], trials: int) -> tuple[dict, dict, list[str]]:
    model = load_model_cached()
    validator = EnvelopeValidator()
    stop_point = validator.delivery_stop_point()
    drillers = {"head_turn": drill_head_turn, "estop": drill_estop,
                "face_intrude": drill_face_intrude}
    metrics: dict = {"trials_per_case": trials, "cases": {}}
    checks: dict = {}
    for case in cases:
        results = [drillers[case](model, validator, stop_point)
                   for _ in range(trials)]
        n_ok = sum(1 for r in results if r["ok"])
        case_metrics: dict = {"trials": trials, "passed": n_ok,
                              "rate": round(n_ok / trials, 4)}
        if case == "estop":
            lat = [r["latency_ms"] for r in results]
            case_metrics["max_latency_ms"] = round(max(lat), 3)
            case_metrics["mean_latency_ms"] = round(float(np.mean(lat)), 3)
        if case == "face_intrude":
            case_metrics["zone_intrusions_total"] = sum(
                int(r["zone_intrusions"]) for r in results)
            case_metrics["min_retreat_m"] = min(r["retreat_m"] for r in results)
        metrics["cases"][case] = case_metrics
        if case == "estop":
            checks[f"drill:{case}"] = (
                n_ok == trials
                and case_metrics["max_latency_ms"] <= THRESHOLDS["estop_latency_ms_max"])
        elif case == "face_intrude":
            checks[f"drill:{case}"] = (
                n_ok == trials
                and case_metrics["zone_intrusions_total"]
                <= THRESHOLDS["zone_intrusion_count_max"])
        else:
            checks[f"drill:{case}"] = n_ok == trials
    total_intrusions = metrics["cases"].get("face_intrude", {}).get(
        "zone_intrusions_total", 0)
    checks["zone_intrusions_zero"] = total_intrusions <= THRESHOLDS[
        "zone_intrusion_count_max"]
    notes = [
        "mock 结论不等于真机实测结论：MockArm 为仿真内虚拟执行器，本演练证明的"
        "是包络硬闸与驱动响应链路；真机安全实测（D3+）按同构检查链执行",
        "estop=空格键软件急停 latch 语义（契约：急停复用 watchdog 违规类别，"
        "estop_latched 区分）；violation!=none → clear_to_move=False 直至显式 reset",
    ]
    return metrics, checks, notes


def _run_real(port: str, cases: list[str], trials: int) -> int:
    cfg = FeetechArmConfig(port=port)
    arm = FeetechArm(cfg)
    try:
        arm.connect()
    except HardwareUnavailable as exc:
        return fail_closed(exc, f"FeetechArm.connect(port={port!r}) "
                                f"(safety_drill real: cases={cases}, trials={trials})")
    raise HardwareUnavailable("真机安全实测随 T10 bring-up 实现")  # pragma: no cover


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    cases = [c.strip() for c in str(args.cases).split(",") if c.strip()]
    unknown = [c for c in cases if c not in CASES]
    if unknown or not cases:
        print(f"[safety_drill] 未知用例 {unknown}（可选：{list(CASES)}）",
              file=sys.stderr)
        return EXIT_HW_UNAVAILABLE
    if args.trials < 1:
        print("[safety_drill] --trials 须 ≥1", file=sys.stderr)
        return EXIT_HW_UNAVAILABLE

    if not args.mock:
        return _run_real(args.port, cases, args.trials)

    metrics, checks, notes = _run_mock(cases, args.trials)
    passed = all(checks.values())
    thresholds = dict(THRESHOLDS)
    thresholds["cases"] = list(cases)
    report_path = resolve_path(args.report) if args.report else \
        resolve_path("reports/safety_drill_eval.json")
    write_report(
        report_path,
        module="cs_arm.safety_drill",
        cmd=(f"python scripts/safety_drill.py --cases {args.cases} "
             f"--trials {args.trials} --mock  (cwd=包根 chengshao/)"),
        metrics=metrics,
        thresholds=thresholds,
        pass_=passed,
        checks=checks,
        notes=notes,
        evidence_kind="mock_dry_run",
        real_machine_measured=False,
        mock=True,
    )
    print(f"safety_drill(mock): pass={passed} cases={cases} trials={args.trials}")
    for case, m in metrics["cases"].items():
        extra = ""
        if "max_latency_ms" in m:
            extra = f" max_estop={m['max_latency_ms']}ms"
        if "zone_intrusions_total" in m:
            extra = f" intrusions={m['zone_intrusions_total']}" \
                    f" min_retreat={m['min_retreat_m']}m"
        print(f"  [{'PASS' if checks.get('drill:' + case) else 'FAIL'}] "
              f"{case}: {m['passed']}/{m['trials']}{extra}")
    print(f"report -> {report_path}")
    return EXIT_OK if passed else EXIT_CHECKS_FAILED


if __name__ == "__main__":
    sys.exit(main())
