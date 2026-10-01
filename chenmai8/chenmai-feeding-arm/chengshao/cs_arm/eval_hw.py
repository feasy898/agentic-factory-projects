"""cs_arm.eval_hw：单臂冒烟 eval（开发指令 §5.9 第 1 行；hw-toolchain spec §2 第 2 步）。

用法（cwd=包根 chengshao/）::

    python -m cs_arm.eval_hw                      # 真机：无硬件 → HardwareUnavailable → exit 2
    python -m cs_arm.eval_hw --port COM3          # 真机（骨架阶段同样 exit 2——T10 实现）
    python -m cs_arm.eval_hw --mock               # MockArm 等价语义 dry-run → 报告 + exit 0

通过线（§5.9：6/6 舵机连通、回读一致、限位/温度正常、TPU 夹爪开合）：

  1) 连通：6/6 关节在位（契约 v1.1：6 关节 = 5 臂关节 + 1 夹爪），状态可读且全有限；
  2) 回读一致：经 SafetyEnvelope 下发的关节目标，执行完成后回读误差 ≤ 1e-3 rad；
  3) 限位：限位外目标 100% 拒绝（零运动）；已执行目标全部在关节限位内；
  4) 温度：真机读舵机温度寄存器（上限 55°C）；mock 等价语义 = 无热模型，以
     "看门狗通道健康 + 全程零 violation + 零堵转/超速事件"作为等价判定
     （报告显式标注 mock_equivalent，**不等于**真机温度实测）；
  5) 夹爪：TPU 夹爪开→合→开循环经包络执行并回读一致（真机为夹爪舵机行程）。

纪律：一切指令经 SafetyEnvelope 下发（契约 §3.1）；真机分支占位即契约——
FeetechArm 骨架 connect()/read()/write() 抛 HardwareUnavailable，本入口如实
映射为 exit 2，不产出任何 pass=true 的报告。
"""

from __future__ import annotations

import argparse
import sys
import time

import numpy as np

try:  # 包根直跑形态 / 仓库根集成形态双兼容
    from cs_arm._hw_common import (
        EXIT_CHECKS_FAILED,
        EXIT_HW_UNAVAILABLE,
        EXIT_OK,
        fail_closed,
        load_model_cached,
        resolve_path,
        write_report,
    )
    from cs_arm.clock import VirtualClock
    from cs_arm.feetech import FeetechArm, FeetechArmConfig, HardwareUnavailable
    from cs_arm.interface import ArmCommandRejected
    from cs_arm.mock_arm import MockArm
    from cs_arm.safety import SafetyEnvelope
    from cs_schema import ArmCommand, CommandMode, N_ARM_JOINTS, ViolationKind
    from cs_sim import EnvelopeValidator
except ImportError:  # pragma: no cover - 仓库根形态
    from chengshao.cs_arm._hw_common import (
        EXIT_CHECKS_FAILED,
        EXIT_HW_UNAVAILABLE,
        EXIT_OK,
        fail_closed,
        load_model_cached,
        resolve_path,
        write_report,
    )
    from chengshao.cs_arm.clock import VirtualClock
    from chengshao.cs_arm.feetech import FeetechArm, FeetechArmConfig, HardwareUnavailable
    from chengshao.cs_arm.interface import ArmCommandRejected
    from chengshao.cs_arm.mock_arm import MockArm
    from chengshao.cs_arm.safety import SafetyEnvelope
    from chengshao.cs_schema import ArmCommand, CommandMode, N_ARM_JOINTS, ViolationKind
    from chengshao.cs_sim import EnvelopeValidator

#: §5.9 通过线（与报告 thresholds 字段一致）
THRESHOLDS: dict = {
    "servos_online_required": N_ARM_JOINTS,       # 6/6
    "readback_err_rad_max": 1e-3,                 # 回读一致（仿真内确定性执行）
    "limit_violations_executed_max": 0,           # 限位外执行次数
    "over_limit_targets_must_reject": True,
    "temperature_max_c": 55.0,                    # 真机口径（mock 为等价语义）
    "temperature_mock_equivalent": True,          # mock：看门狗健康+零事件替代温度读数
    "gripper_cycles_min": 2,                      # 开→合→开（≥2 次换向）
    "gripper_readback_err_rad_max": 1e-3,
}

GRIPPER_OPEN = 0.6    # 与 cs_orchestra.params.gripper_open 一致（TPU 夹爪全开）
GRIPPER_CLOSE = 0.2   # 与 cs_orchestra.params.gripper_close 一致（合爪取食位）
JOINT_SPEED = 0.5     # 冒烟速度（rad/s，< 硬限 1.5）


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="python -m cs_arm.eval_hw",
        description="单臂冒烟：6/6 连通 / 回读一致 / 限位与温度 / 夹爪开合（§5.9）",
    )
    ap.add_argument("--mock", action="store_true",
                    help="无硬件 dry-run：MockArm 等价语义 + 合成判定（exit 0 可达）")
    ap.add_argument("--port", default="",
                    help="真机串口（如 COM3 / /dev/ttyUSB0）；缺省空 = 未配置（fail-closed）")
    ap.add_argument("--baudrate", type=int, default=1_000_000)
    ap.add_argument("--report", default=None,
                    help="报告 JSON（缺省 reports/hw_smoke_eval.json；真机失败路径不写报告）")
    return ap.parse_args(argv)


# ---- mock 冒烟检查 ---------------------------------------------------------------

def _run_mock() -> tuple[dict, dict, list[str]]:
    """MockArm 等价语义冒烟：返回 (metrics, checks, notes)。"""
    model = load_model_cached()
    validator = EnvelopeValidator()
    clock = VirtualClock()
    mock = MockArm(model, validator=validator, clock=clock)
    env = SafetyEnvelope(mock, model=model, validator=validator, clock=clock)
    metrics: dict = {"backend": "MockArm+SafetyEnvelope+VirtualClock",
                     "mock_equivalent": True, "model_tier": model.tier}
    checks: dict = {}
    lo = np.asarray(model.joint_lower, dtype=float)
    hi = np.asarray(model.joint_upper, dtype=float)

    def move(target: np.ndarray, speed: float = JOINT_SPEED) -> None:
        env.write(ArmCommand(mode=CommandMode.JOINTS,
                             target=[float(v) for v in target],
                             max_speed=speed, timeout_s=30.0))
        clock.advance_s(float(env.last_decision.get("duration_s") or 0.0) + 0.005)
        env.read()

    # 1) 连通：6/6 关节在位、可读、有限
    env.enable()
    st = env.read()
    q = np.asarray(st.joint_pos, dtype=float)
    n_online = int(np.isfinite(q).sum())
    metrics["servos_online"] = n_online
    metrics["servos_expected"] = N_ARM_JOINTS
    checks["connectivity_6_of_6"] = (n_online == N_ARM_JOINTS == len(q)
                                     and model.n_joints == N_ARM_JOINTS)

    # 2) 回读一致：三个确定性良性目标
    q0 = q.copy()
    targets = [q0.copy(), q0.copy(), q0.copy()]
    targets[1][0] = float(np.clip(q0[0] + 0.15, lo[0], hi[0]))
    targets[1][2] = float(np.clip(q0[2] - 0.10, lo[2], hi[2]))
    targets[2][1] = float(np.clip(q0[1] + 0.12, lo[1], hi[1]))
    targets[2][3] = float(np.clip(q0[3] + 0.08, lo[3], hi[3]))
    max_err = 0.0
    rejected_readback = 0
    for t in targets:
        try:
            move(t)
            max_err = max(max_err, float(np.max(np.abs(
                np.asarray(env.read().joint_pos, dtype=float) - t))))
        except ArmCommandRejected:
            rejected_readback += 1
    metrics["readback_max_err_rad"] = round(max_err, 9)
    metrics["readback_targets_rejected"] = rejected_readback
    checks["readback_consistent"] = (max_err <= THRESHOLDS["readback_err_rad_max"]
                                     and rejected_readback == 0)

    # 3) 限位：限位外目标必须拒绝且零运动
    over = q0.copy()
    over[0] = float(hi[0] + 0.5)  # 关节 1 超上限
    q_pre = np.asarray(env.read().joint_pos, dtype=float)
    over_rejected = False
    try:
        move(over)
    except ArmCommandRejected as exc:
        over_rejected = exc.reason == "target_beyond_joint_limits"
    drift = float(np.max(np.abs(np.asarray(env.read().joint_pos, dtype=float) - q_pre)))
    limits_violated = int(drift > 0.0)  # 拒绝后零运动语义
    # 已执行目标全部在限位内
    in_limits = bool(np.all(q >= lo - 1e-9) and np.all(q <= hi + 1e-9))
    metrics["over_limit_target_rejected"] = over_rejected
    metrics["motion_after_reject_rad"] = round(drift, 9)
    metrics["limit_violations_executed"] = limits_violated
    metrics["executed_targets_in_limits"] = in_limits
    checks["limits_ok"] = (over_rejected and drift == 0.0
                           and limits_violated <= THRESHOLDS["limit_violations_executed_max"]
                           and in_limits)

    # 4) 温度（mock 等价语义）：无热模型 → 看门狗通道健康 + 全程零 violation
    quiet_ok = env.poll().violation is ViolationKind.NONE
    clock.advance_s(0.6)  # 累计静默 > 0.5s：看门狗应跳闸（保护通道在线）
    wd = env.poll()
    wd_trips = wd.violation is ViolationKind.WATCHDOG and not mock.enabled
    env.reset()
    env.enable()
    recovered = env.poll().violation is ViolationKind.NONE
    final_violation_free = env.safety_state().violation is ViolationKind.NONE
    metrics["temperature"] = {
        "mode": "mock_equivalent",
        "watchdog_quiet_ok": bool(quiet_ok),
        "watchdog_trips_on_silence": bool(wd_trips),
        "watchdog_recovers_after_reset": bool(recovered),
        "violations_total": 0 if final_violation_free else 1,
        "note": "MockArm 无热模型：以看门狗通道健康 + 零 violation 等价替代温度读数，"
                "不等于真机温度实测（真机读舵机温度寄存器，上限 55°C）",
    }
    checks["temperature_ok_mock_equivalent"] = (quiet_ok and wd_trips and recovered
                                                and final_violation_free)

    # 5) TPU 夹爪：开→合→开循环（仅夹爪分量变化，经包络）
    q_cur = np.asarray(env.read().joint_pos, dtype=float)
    cycle = [GRIPPER_OPEN, GRIPPER_CLOSE, GRIPPER_OPEN]
    grip_err = 0.0
    grip_cycles = 0
    grip_rejected = 0
    for g in cycle:
        t = q_cur.copy()
        t[-1] = float(g)
        try:
            move(t, speed=0.8)
            grip_err = max(grip_err, float(abs(np.asarray(
                env.read().joint_pos, dtype=float)[-1] - g)))
            grip_cycles += 1
        except ArmCommandRejected:
            grip_rejected += 1
    metrics["gripper"] = {"cycles_completed": grip_cycles, "rejected": grip_rejected,
                          "max_readback_err_rad": round(grip_err, 9),
                          "open_rad": GRIPPER_OPEN, "close_rad": GRIPPER_CLOSE}
    checks["gripper_open_close"] = (grip_cycles >= THRESHOLDS["gripper_cycles_min"]
                                    and grip_rejected == 0
                                    and grip_err <= THRESHOLDS["gripper_readback_err_rad_max"])

    metrics["envelope_stats"] = {k: v for k, v in env.stats.items()
                                 if k != "rejected_by_reason"}
    notes = [
        "mock 结论不等于真机结论：MockArm 为仿真内虚拟执行器（无串口/舵机/热模型），"
        "本报告证明的是冒烟检查链与包络语义，不是 §5.9 真机冒烟达标",
        "真机分支：FeetechArm.connect() 校验 6/6 在线后逐项执行同构检查（T10 实现）",
    ]
    return metrics, checks, notes


def _run_real(port: str, baudrate: int) -> int:
    """真机冒烟：FeetechArm 骨架阶段必然 HardwareUnavailable → exit 2（fail-closed）。"""
    cfg = FeetechArmConfig(port=port, baudrate=baudrate)
    arm = FeetechArm(cfg)
    try:
        arm.connect()  # 骨架：显式抛 HardwareUnavailable（T10 实现串口通道）
    except HardwareUnavailable as exc:
        return fail_closed(exc, f"FeetechArm.connect(port={port!r})")
    # T10 实现后接续的检查链（连通/回读/限位/温度寄存器/夹爪行程）在此展开；
    # 骨架阶段不可达（connect 已失败关闭）。
    raise HardwareUnavailable("单臂冒烟真机检查链随 T10 bring-up 实现")  # pragma: no cover


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    t0 = time.perf_counter()
    if not args.mock:
        return _run_real(args.port, args.baudrate)

    metrics, checks, notes = _run_mock()
    metrics["elapsed_s"] = round(time.perf_counter() - t0, 2)
    passed = all(checks.values())
    report_path = resolve_path(args.report) if args.report else \
        resolve_path("reports/hw_smoke_eval.json")
    write_report(
        report_path,
        module="cs_arm.eval_hw",
        cmd="python -m cs_arm.eval_hw --mock  (cwd=包根 chengshao/)",
        metrics=metrics,
        thresholds=THRESHOLDS,
        pass_=passed,
        checks={k: bool(v) for k, v in checks.items()},
        notes=notes,
        evidence_kind="mock_dry_run",
        real_machine_measured=False,
    )
    print(f"cs_arm.eval_hw(mock): pass={passed}")
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"report -> {report_path}")
    return EXIT_OK if passed else EXIT_CHECKS_FAILED


if __name__ == "__main__":
    sys.exit(main())
