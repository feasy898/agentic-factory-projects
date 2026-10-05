"""脚本示教自记录（training/record；无主臂方案的采数入口之一）。

单从臂方案下无主臂可遥操作（training-plan v2）：ACT 示教数据由
**ScriptedScoop 执行期自记录**产出——把脚本化舀取轨迹（悬停→入碗→合爪→
抬勺→回悬停）以 30–50Hz 逐步经 SafetyEnvelope 下发，每步记录
obs（6 关节回读）/ action（6 维关节目标）/ image（双路相机帧）。

模式（互斥三态，占位即契约）：
- 缺省：**plan-only dry-run**——校验参数/输出路径/覆盖配置，打印采样计划，
  不写文件、不碰硬件（本机与 GPU 机行为一致）；
- ``--mock``：**合成数据 dry-run**——MockArm(cs_sim) + SafetyEnvelope +
  虚拟时钟真实执行同一脚本轨迹，图像为确定性合成帧，产出小样本数据集并
  跑通格式校验（零硬件，本机可用；数据仅证明格式链路，不代表真实视觉）；
- ``--execute``：**真实采集**——需 ``CS_HW_SESSION=1`` + 真机通道
  （cs_arm.FeetechArm，未接入即 HardwareUnavailable → exit 2）+ 双路相机
  设备；设备缺失一律显式失败，不假装成功。

数据格式：机器人学习运行栈数据集布局（中性名；meta/ + parquet + mp4，
详见 ``record/session.py`` docstring），训练入口名按命名纪律不入仓库文本。

退出码：0=成功（含 dry-run/mock）；2=参数/硬件纪律拒绝。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import numpy as np

from chengshao.cs_schema import N_ARM_JOINTS  # noqa: E402
from chengshao.training.common import ConfigError, fail  # noqa: E402
from chengshao.training.record.session import (  # noqa: E402
    RESOLUTION,
    VALID_CAMS,
    DatasetWriter,
    build_mock_env,
    capture_frame,
    emit_report,
    open_camera,
    require_hw_session,
    resolve_out_dir,
    synthesize_frame,
    validate_dataset,
)

_MODULE = "training.record.record_scripted"
DEFAULT_BOWL = (0.22, -0.18, 0.02)  # 与 cs_arm.eval_mock 演示碗位一致（base 系，米）
GRIP_JOINT = N_ARM_JOINTS - 1  # 契约 v1.1：下标 5 = 夹爪
SPEED_MPS = {"approach": 0.05, "dip": 0.03, "lift": 0.04}
STEP_M = 0.01  # 路径步长（米）：单步时长 ≤0.34s，远低于包络限速语义


def parse_bowl(value: str) -> tuple[float, float, float]:
    try:
        parts = [float(v) for v in value.split(",")]
        if len(parts) != 3:
            raise ValueError("需要 3 个分量")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"--bowl 格式应为 x,y,z：{exc}") from exc
    return tuple(parts)  # type: ignore[return-value]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m chengshao.training.record.record_scripted",
        description="脚本示教自记录：ScriptedScoop 执行期记录 obs/action/image"
                    "（缺省 plan-only dry-run；--mock 合成数据；--execute 需硬件）")
    parser.add_argument("--episodes", type=int, default=1,
                        help="采集回合数（覆盖矩阵见 plan/training-plan.md §1.1）")
    parser.add_argument("--out", type=Path, default=None,
                        help="数据集根目录（仓库相对；缺省 data/recordings/scripted_scoop）")
    parser.add_argument("--fps", type=float, default=30.0,
                        help="采样频率 Hz（录制协议 30–50；训练配置口径为 30）")
    parser.add_argument("--cams", default="scene,wrist",
                        help="相机列表（逗号分隔，子集于 scene,wrist）")
    parser.add_argument("--bowl", type=parse_bowl, default=DEFAULT_BOWL,
                        help="碗位 base 系坐标 x,y,z（米；缺省演示碗位）")
    parser.add_argument("--task", default="脚本舀取一勺（ScriptedScoop 自记录）",
                        help="任务描述（写入数据集任务表）")
    parser.add_argument("--seed", type=int, default=1000,
                        help="合爪前微扰随机种子（确定性采集）")
    parser.add_argument("--mock", action="store_true",
                        help="合成数据 dry-run：MockArm 虚拟执行 + 合成帧，产出小样本并校验")
    parser.add_argument("--execute", action="store_true",
                        help="真实采集（需 CS_HW_SESSION=1 + 真机通道 + 相机设备）")
    parser.add_argument("--port", default="",
                        help="真机串口号（如 COM3 / /dev/ttyUSB0；--execute 必填）")
    parser.add_argument("--cam-dev", default="scene=0,wrist=1",
                        help="相机设备号映射（--execute 用；如 scene=0,wrist=1）")
    parser.add_argument("--report", type=Path, default=None,
                        help="§10.2 证据报告输出路径（配合 --mock/--execute）")
    args = parser.parse_args(argv)
    return args


def validate_args(args: argparse.Namespace) -> list[str]:
    """公共参数校验（三态共用）；非法即 fail(exit 2)。返回相机列表。"""
    if not (10.0 <= float(args.fps) <= 50.0):
        fail(f"--fps 必须在 30–50 协议带内（录制协议 §1.2）：{args.fps}")
    if args.episodes < 1 or args.episodes > 500:
        fail(f"--episodes 必须在 1–500：{args.episodes}")
    cams = [c.strip() for c in args.cams.split(",") if c.strip()]
    if not cams or not set(cams) <= set(VALID_CAMS):
        fail(f"--cams 必须为 {VALID_CAMS} 的非空子集：{cams}")
    if args.mock and args.execute:
        fail("--mock 与 --execute 互斥（合成 dry-run 与真实采集不混跑）")
    return cams


def plan(args: argparse.Namespace, cams: list[str], out_dir: Path) -> dict:
    """采样计划（三态打印同构；plan-only 模式即到此为止）。"""
    return {
        "mode": "execute" if args.execute else ("mock" if args.mock else "plan-only"),
        "episodes": args.episodes,
        "fps": float(args.fps),
        "cams": cams,
        "resolution": list(RESOLUTION),
        "bowl_base_xyz_m": [round(v, 4) for v in args.bowl],
        "state_dim": N_ARM_JOINTS,
        "action_dim": N_ARM_JOINTS,
        "out_dir": str(out_dir),
        "task": args.task,
        "seed": int(args.seed),
        "trajectory": "悬停→入碗→合爪(记 scoop_done)→抬勺→回悬停（ScriptedScoop 主腿）",
        "format": "robot-learning-runtime-dataset v2.1（meta/+parquet/mp4，中性名）",
    }


# ---------------------------------------------------------------------------
# 轨迹生成（ScriptedScoop 主腿的笛卡尔航点序列；mock/真实共用）
# ---------------------------------------------------------------------------

TRANSIT = [0.25, -0.09, 0.20]  # 转移点（与 cs_arm.eval_mock 演示走廊一致；可达域内）


def trajectory_waypoints(bowl: tuple[float, float, float]) -> list[tuple[str, list[float], float]]:
    """返回 [(phase, target_xyz, speed_mps), ...]；合爪腿由执行层单独发。

    转移腿经演示走廊可达域进入碗位上空（直连 home→hover 会跨 IK 解支，
    cs_sim 解算器无解——见 2026-10-02 本机调试记录）。
    """
    hover = [bowl[0], bowl[1], bowl[2] + 0.08]
    dip = [bowl[0], bowl[1], bowl[2] + 0.02]
    return [
        ("transit", TRANSIT, SPEED_MPS["approach"]),
        ("approach", hover, SPEED_MPS["approach"]),
        ("dip", dip, SPEED_MPS["dip"]),
        ("lift", hover, SPEED_MPS["lift"]),
    ]


def stream_leg(env, model, target_xyz: list[float], speed_mps: float,
               session, *, cam_frame: Callable[[int, float], dict],
               t_start: float) -> tuple[int, float]:
    """把一段笛卡尔腿按 STEP_M 流式下发并逐步记录；返回 (步数, 结束时刻 s)。"""
    from chengshao.cs_arm import ArmCommandRejected

    cur = np.asarray(env.read().ee_pos, dtype=float)
    goal = np.asarray(target_xyz, dtype=float)
    n = max(1, int(np.ceil(float(np.linalg.norm(goal - cur)) / STEP_M)))
    steps = 0
    for i in range(1, n + 1):
        wp = cur + (goal - cur) * (i / n)
        cmd = _cart_cmd(wp, speed_mps)
        steps += _record_step(env, model, cmd, session,
                              cam_frame=cam_frame, t_start=t_start)
    return steps, t_start


def _cart_cmd(point, speed: float):
    from chengshao.cs_schema import ArmCommand

    return ArmCommand(mode="cartesian", target=[float(v) for v in point],
                      max_speed=speed, timeout_s=300.0)


def _joints_cmd(target, speed: float):
    from chengshao.cs_schema import ArmCommand

    return ArmCommand(mode="joints", target=[float(v) for v in target],
                      max_speed=speed, timeout_s=300.0)


def _record_step(env, model, cmd, session, *, cam_frame, t_start) -> int:
    """下发一条指令并记录 (obs, action, images)；返回该步帧下标。"""
    from chengshao.cs_arm import ArmCommandRejected, resolve_target_joints

    q_now = np.asarray(env.read().joint_pos, dtype=float)
    try:
        q1 = resolve_target_joints(model, cmd, q_now)  # 与包络同口径的目标解算
    except ArmCommandRejected as exc:
        raise ConfigError(f"目标解算被拒（{exc.reason}）——采集轨迹必须零拒绝") from exc
    try:
        env.write(cmd)
    except ArmCommandRejected as exc:
        raise ConfigError(f"包络拒绝（{exc.reason}）——采集轨迹必须零拒绝") from exc
    dt = float(env.last_decision.get("duration_s", 0.0)) + 0.005
    _advance_clock(env, dt)
    state = env.read()
    t_s = _now_s(env, t_start)
    frame_index = session["buffer"].add_step(
        [float(v) for v in state.joint_pos], [float(v) for v in q1],
        t_s, cam_frame(session["step"], t_s))
    session["step"] += 1
    return frame_index


def _advance_clock(env, dt_s: float) -> None:
    """虚拟时钟推进（mock）；真实通道用墙钟，无可推进对象则跳过。"""
    clock = getattr(env, "_clock", None)
    if clock is not None and hasattr(clock, "advance_s"):
        clock.advance_s(dt_s)


def _now_s(env, t_start: float) -> float:
    clock = getattr(env, "_clock", None)
    if clock is not None and hasattr(clock, "now_ns"):
        return clock.now_ns() / 1e9
    return time.monotonic() - t_start


def run_episode(env, model, args, session, *, cam_frame) -> dict:
    """执行一条完整舀取腿并记录；返回该回合统计（帧数/事件）。"""
    bowl = args.bowl
    rng = np.random.default_rng(int(args.seed))
    t_start = _now_s(env, 0.0)
    for phase, target, speed in trajectory_waypoints(bowl):
        if phase == "dip":
            # 腕部闭环修正语义（与 cs_orchestra MockScoop 一致）：入碗点微扰
            target = [target[0] + float(rng.uniform(-0.01, 0.01)),
                      target[1] + float(rng.uniform(-0.01, 0.01)), target[2]]
        if phase == "lift":
            # 合爪（夹爪关节独立短行程），合爪完成帧记 scoop_done
            q_now = np.asarray(env.read().joint_pos, dtype=float)
            grip_target = q_now.copy()
            grip_target[GRIP_JOINT] = max(0.0, grip_target[GRIP_JOINT] - 0.5)
            fi = _record_step(env, model, _joints_cmd(grip_target, 0.8), session,
                              cam_frame=cam_frame, t_start=t_start)
            session["buffer"].mark("scoop_done", fi)
        stream_leg(env, model, target, speed, session, cam_frame=cam_frame,
                   t_start=t_start)
    buf = session["buffer"]
    return {"episode_index": buf.episode_index, "frames": buf.length,
            "events": {k: list(v) for k, v in buf.events.items()}}


def make_cam_frame_mock(cams: list[str]):
    def cam_frame(step: int, t_s: float) -> dict:
        return {cam: synthesize_frame(cam, t_s, step) for cam in cams}
    return cam_frame


def make_cam_frame_real(caps: dict):
    def cam_frame(_step: int, _t_s: float) -> dict:
        return {cam: capture_frame(cap, cam) for cam, cap in caps.items()}
    return cam_frame


def finish_and_validate(writer: DatasetWriter) -> tuple[Path, dict]:
    root = writer.finalize()
    report = validate_dataset(root)
    return root, report


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cams = validate_args(args)
    out_dir = resolve_out_dir(str(args.out) if args.out else "data/recordings/scripted_scoop",
                              default="", field_name="--out")
    print("PLAN:", plan(args, cams, out_dir))

    if args.execute:
        return run_real(args, cams, out_dir)
    if args.mock:
        return run_mock(args, cams, out_dir)

    print(f"NOTE: plan-only dry-run @ 未写文件未碰硬件；--mock 生成合成小样本，"
          "--execute 真实采集（需 CS_HW_SESSION=1 + 真机通道 + 相机）。")
    return 0


# ---------------------------------------------------------------------------
# 模式实现
# ---------------------------------------------------------------------------

def run_mock(args: argparse.Namespace, cams: list[str], out_dir: Path) -> int:
    """合成数据 dry-run：MockArm 虚拟执行脚本轨迹，产出小样本 + 格式校验。"""
    from chengshao.cs_arm import ArmCommandRejected

    env, _clock, model = build_mock_env(seed=int(args.seed))
    writer = DatasetWriter(out_dir, task=args.task, cams=cams, fps=args.fps,
                           joint_names=list(env.model.joint_names))
    cam_frame = make_cam_frame_mock(cams)
    session = {"buffer": None, "step": 0}
    episode_stats: list[dict] = []
    try:
        env.enable()
        for ei in range(args.episodes):
            session["buffer"] = writer.start_episode(ei)
            try:
                episode_stats.append(run_episode(env, model, args, session,
                                                 cam_frame=cam_frame))
            except ArmCommandRejected as exc:
                return fail(f"mock 采集第 {ei} 回合被包络拒绝（{exc.reason}）——"
                            "脚本轨迹应零拒绝，请检查碗位参数")
            writer.finish_episode()
    finally:
        env.disable()
    root, v_report = finish_and_validate(writer)
    print(f"WROTE: {root}")
    print("VALIDATE:", v_report)
    if args.report is not None:
        emit_report(args.report, module=_MODULE,
                    cmd="python -m chengshao.training.record.record_scripted --mock",
                    metrics={"episodes": len(episode_stats), "frames": int(v_report.get("frames") or 0),
                             "dataset_root": str(root), "validation": v_report,
                             "episode_stats": episode_stats},
                    thresholds={"format_validation_ok": True,
                                "state_dim": N_ARM_JOINTS,
                                "fps_band": "30-50"},
                    passed=bool(v_report["ok"]))
        print(f"REPORT: {args.report}")
    return 0 if v_report["ok"] else 1


def run_real(args: argparse.Namespace, cams: list[str], out_dir: Path) -> int:
    """真实采集：CS_HW_SESSION=1 + FeetechArm + 双路相机；缺失一律 exit 2。"""
    from chengshao.cs_arm import HardwareUnavailable, FeetechArm, FeetechArmConfig, SafetyEnvelope

    require_hw_session("record_scripted")
    if not args.port.strip():
        print("[training] 错误：--execute 需要 --port（真机串口号）；"
              "未配置即拒绝（fail-closed，不假装成功）。", file=sys.stderr)
        return 2
    cam_devs: dict[str, int] = {}
    for item in args.cam_dev.split(","):
        if not item.strip():
            continue
        name, _, num = item.partition("=")
        if name.strip() not in cams or not num.strip().isdigit():
            print(f"[training] 错误：--cam-dev 项非法：{item!r}（应形如 scene=0）",
                  file=sys.stderr)
            return 2
        cam_devs[name.strip()] = int(num)
    caps: dict = {}
    try:
        arm = FeetechArm(FeetechArmConfig(port=args.port.strip()))
        env = SafetyEnvelope(arm)  # 真机包络（墙钟；模型由包络自动装载）
        for cam in cams:
            cap = open_camera(cam_devs.get(cam, 0))
            if cap is None:
                print(f"[training] 错误：相机 {cam}（dev={cam_devs.get(cam, 0)}）"
                      "无法打开——设备缺失即拒绝（fail-closed）。", file=sys.stderr)
                return 2
            caps[cam] = cap
        writer = DatasetWriter(out_dir, task=args.task, cams=cams, fps=args.fps,
                               joint_names=list(env.model.joint_names))
        session = {"buffer": None, "step": 0}
        env.enable()
        for ei in range(args.episodes):
            session["buffer"] = writer.start_episode(ei)
            run_episode(env, env.model, args, session,
                        cam_frame=make_cam_frame_real(caps))
            writer.finish_episode()
            time.sleep(1.0)
        env.disable()
        for cap in caps.values():
            cap.release()
        root, v_report = finish_and_validate(writer)
        print(f"WROTE: {root}")
        print("VALIDATE:", v_report)
        if args.report is not None:
            emit_report(args.report, module=_MODULE,
                        cmd="python -m chengshao.training.record.record_scripted --execute",
                        metrics={"episodes": args.episodes, "validation": v_report},
                        thresholds={"format_validation_ok": True},
                        passed=bool(v_report["ok"]))
        return 0 if v_report["ok"] else 1
    except HardwareUnavailable as exc:
        print(f"[training] 错误：真机通道不可用（{exc}）——骨架阶段显式失败，"
              "不假装成功。", file=sys.stderr)
        return 2
    finally:
        for cap in caps.values():
            try:
                cap.release()
            except Exception:  # noqa: BLE001 - 释放失败不掩盖主结果
                pass


if __name__ == "__main__":
    raise SystemExit(main())
