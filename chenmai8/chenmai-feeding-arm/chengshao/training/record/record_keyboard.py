"""键盘遥操录制入口（training/record；无主臂方案的采数入口之二）。

单从臂、无主臂遥操作（training-plan v2）：拖动示教（record_demo，方案 B）
之外的第二条人工示教通路——**键盘增量遥操**：操作者按键给出关节增量目标，
经 SafetyEnvelope 限步下发，30–50Hz 记录 obs（6 关节回读）/ action（6 维
关节目标）/ image（双路相机帧）。适合精细调整类示教与纠错条目
（"没舀到→抬升→再舀"）的补采。

键位表（固定，dry-run 打印；两态共用同一增量管线）::

    q/a=关节1±  w/s=关节2±  e/d=关节3±  r/f=关节4±  t/g=关节5±
    y/h=关节6(夹爪)±  space=标记 scoop_done  enter=结束本回合  esc=中止采集

模式（互斥三态，占位即契约）：
- 缺省：**plan-only dry-run**——校验参数、打印键位表与采样计划，不写文件
  不碰硬件、不启动键盘监听；
- ``--mock``：**合成数据 dry-run**——确定性合成按键序列走同一增量管线，
  MockArm 虚拟执行 + 合成帧，产出小样本数据集并跑通格式校验（零硬件）；
- ``--execute``：**真实采集**——需 ``CS_HW_SESSION=1`` + 真机通道
  （cs_arm.FeetechArm，未接入即 HardwareUnavailable → exit 2）+ 双路相机
  + pynput 键盘监听；任一缺失一律显式失败（exit 2），不假装成功。

数据格式：机器人学习运行栈数据集布局（中性名；详见 record/session.py）。

退出码：0=成功（含 dry-run/mock）；2=参数/硬件纪律拒绝。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

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

_MODULE = "training.record.record_keyboard"
GRIP_JOINT = N_ARM_JOINTS - 1  # 契约 v1.1：下标 5 = 夹爪（增量放大）

# 键位表：增量键 → (关节下标, 方向)；事件键单列（中性自记录键位，与本仓无涉）
KEYMAP: dict[str, tuple[int, int]] = {
    "q": (0, +1), "a": (0, -1),
    "w": (1, +1), "s": (1, -1),
    "e": (2, +1), "d": (2, -1),
    "r": (3, +1), "f": (3, -1),
    "t": (4, +1), "g": (4, -1),
    "y": (5, +1), "h": (5, -1),
}
EVENT_KEYS = {"space": "scoop_done", "enter": "__episode_end__", "esc": "__abort__"}
GRIP_DELTA_FACTOR = 5.0  # 夹爪行程短，增量按倍数放大
# 合成按键脚本（mock dry-run；确定性：逼近碗位→合爪→标记→收尾，每回合同表）
MOCK_KEY_SCRIPT = ["w*12", "a*8", "d*6", "e*4", "y*3", "space", "enter"]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m chengshao.training.record.record_keyboard",
        description="键盘遥操录制（缺省 plan-only dry-run；--mock 合成数据；"
                    "--execute 需硬件 + CS_HW_SESSION=1）")
    parser.add_argument("--episodes", type=int, default=1, help="采集回合数")
    parser.add_argument("--out", type=Path, default=None,
                        help="数据集根目录（仓库相对；缺省 data/recordings/keyboard_teleop）")
    parser.add_argument("--fps", type=float, default=30.0,
                        help="采样频率 Hz（录制协议 30–50）")
    parser.add_argument("--cams", default="scene,wrist",
                        help="相机列表（逗号分隔，子集于 scene,wrist）")
    parser.add_argument("--delta", type=float, default=0.05,
                        help="关节增量（rad/键；夹爪按 5 倍）")
    parser.add_argument("--task", default="键盘遥操舀取示教", help="任务描述")
    parser.add_argument("--mock", action="store_true",
                        help="合成数据 dry-run：确定性按键序列 + MockArm 虚拟执行")
    parser.add_argument("--execute", action="store_true",
                        help="真实采集（需 CS_HW_SESSION=1 + 真机通道 + 相机 + pynput）")
    parser.add_argument("--port", default="",
                        help="真机串口号（--execute 必填）")
    parser.add_argument("--cam-dev", default="scene=0,wrist=1",
                        help="相机设备号映射（--execute 用；如 scene=0,wrist=1）")
    parser.add_argument("--report", type=Path, default=None,
                        help="§10.2 证据报告输出路径（配合 --mock/--execute）")
    return parser.parse_args(argv)


def validate_args(args: argparse.Namespace) -> list[str]:
    if not (10.0 <= float(args.fps) <= 50.0):
        fail(f"--fps 必须在 30–50 协议带内（录制协议 §1.2）：{args.fps}")
    if args.episodes < 1 or args.episodes > 500:
        fail(f"--episodes 必须在 1–500：{args.episodes}")
    if not (0.005 <= float(args.delta) <= 0.5):
        fail(f"--delta 必须在 0.005–0.5 rad：{args.delta}")
    cams = [c.strip() for c in args.cams.split(",") if c.strip()]
    if not cams or not set(cams) <= set(VALID_CAMS):
        fail(f"--cams 必须为 {VALID_CAMS} 的非空子集：{cams}")
    if args.mock and args.execute:
        fail("--mock 与 --execute 互斥（合成 dry-run 与真实采集不混跑）")
    return cams


def keymap_lines() -> list[str]:
    lines = ["KEYMAP:"]
    for key, (idx, direction) in KEYMAP.items():
        lines.append(f"  {key}: joint_{idx + 1} {'+' if direction > 0 else '-'}")
    lines.append("  space: 标记 scoop_done；enter: 结束本回合；esc: 中止采集")
    return lines


def plan(args: argparse.Namespace, cams: list[str], out_dir: Path) -> dict:
    return {
        "mode": "execute" if args.execute else ("mock" if args.mock else "plan-only"),
        "episodes": args.episodes,
        "fps": float(args.fps),
        "delta_rad": float(args.delta),
        "grip_delta_factor": GRIP_DELTA_FACTOR,
        "cams": cams,
        "resolution": list(RESOLUTION),
        "state_dim": N_ARM_JOINTS,
        "action_dim": N_ARM_JOINTS,
        "out_dir": str(out_dir),
        "task": args.task,
        "format": "robot-learning-runtime-dataset v2.1（meta/+parquet/mp4，中性名）",
        "note": "键盘增量遥操：目标=关节增量累积（经包络限步），动作=6 维关节目标",
    }


# ---------------------------------------------------------------------------
# 增量管线（mock 合成按键与真实监听共用）
# ---------------------------------------------------------------------------

def expand_key_script(script: list[str]) -> list[str]:
    """把 "w*12" 形式的合成按键脚本展开为单键 token 序列。"""
    tokens: list[str] = []
    for item in script:
        key, _, rep = item.partition("*")
        if key not in KEYMAP and key not in EVENT_KEYS:
            raise ConfigError(f"合成按键脚本含未知键：{item!r}")
        n = int(rep) if rep else 1
        if n < 1 or n > 200:
            raise ConfigError(f"合成按键重复次数非法（1–200）：{item!r}")
        tokens.extend([key] * n)
    return tokens


def apply_token(q_target: np.ndarray, token: str,
                delta: float) -> tuple[np.ndarray, str]:
    """按键 → 关节增量目标或事件；返回 (新目标, 事件名或空串)。"""
    if token in EVENT_KEYS:
        return q_target, EVENT_KEYS[token]
    if token not in KEYMAP:
        raise ConfigError(f"未知键 token：{token!r}")
    idx, direction = KEYMAP[token]
    step = float(delta) * (GRIP_DELTA_FACTOR if idx == GRIP_JOINT else 1.0)
    q_next = q_target.copy()
    q_next[idx] += direction * step
    return q_next, ""


def clip_to_limits(model, q_target: np.ndarray) -> np.ndarray:
    lo = np.asarray(model.joint_lower, dtype=float)
    hi = np.asarray(model.joint_upper, dtype=float)
    return np.clip(q_target, lo, hi)


def record_tick(env, q_target: np.ndarray, session, *, cam_frame,
                t_start: float) -> int:
    """下发一步关节目标并记录（obs=回读, action=目标, images）。"""
    from chengshao.cs_arm import ArmCommandRejected
    from chengshao.cs_schema import ArmCommand

    cmd = ArmCommand(mode="joints", target=[float(v) for v in q_target],
                     max_speed=1.5, timeout_s=60.0)
    try:
        env.write(cmd)
    except ArmCommandRejected as exc:
        raise ConfigError(f"包络拒绝（{exc.reason}）——增量目标超限请先回调") from exc
    clock = getattr(env, "_clock", None)
    if clock is not None and hasattr(clock, "advance_s"):
        clock.advance_s(float(env.last_decision.get("duration_s", 0.0)) + 0.005)
    state = env.read()
    if clock is not None and hasattr(clock, "now_ns"):
        t_s = clock.now_ns() / 1e9
    else:
        t_s = time.monotonic() - t_start
    return _add_step(session, state.joint_pos, q_target, t_s, cam_frame)


def _add_step(session, joint_pos, q_target, t_s, cam_frame) -> int:
    fi = session["buffer"].add_step([float(v) for v in joint_pos],
                                    [float(v) for v in q_target], t_s,
                                    cam_frame(session["step"], t_s))
    session["step"] += 1
    return fi


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
    return root, validate_dataset(root)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cams = validate_args(args)
    out_dir = resolve_out_dir(str(args.out) if args.out else "data/recordings/keyboard_teleop",
                              default="", field_name="--out")
    print("PLAN:", plan(args, cams, out_dir))
    for line in keymap_lines():
        print(line)

    if args.execute:
        return run_real(args, cams, out_dir)
    if args.mock:
        return run_mock(args, cams, out_dir)
    print("NOTE: plan-only dry-run @ 未写文件未碰硬件未启动键盘监听；"
          "--mock 生成合成小样本；--execute 真实采集（需 CS_HW_SESSION=1）。")
    return 0


# ---------------------------------------------------------------------------
# 模式实现
# ---------------------------------------------------------------------------

def run_mock(args: argparse.Namespace, cams: list[str], out_dir: Path) -> int:
    """合成数据 dry-run：确定性按键序列走增量管线，MockArm 虚拟执行。"""
    tokens = expand_key_script(MOCK_KEY_SCRIPT)
    env, _clock, model = build_mock_env(seed=1000)
    writer = DatasetWriter(out_dir, task=args.task, cams=cams, fps=args.fps,
                           joint_names=list(env.model.joint_names))
    cam_frame = make_cam_frame_mock(cams)
    session: dict = {"buffer": None, "step": 0}
    events_summary: dict[str, list[int]] = {}
    try:
        env.enable()
        for ei in range(args.episodes):
            session["buffer"] = writer.start_episode(ei)
            session["step"] = 0
            q_now = np.asarray(env.read().joint_pos, dtype=float)
            q_target = q_now.copy()
            try:
                for token in tokens:
                    q_target, event = apply_token(q_target, token, float(args.delta))
                    q_target = clip_to_limits(model, q_target)
                    if event == "__episode_end__":
                        break
                    if event == "__abort__":
                        fail("合成按键脚本不应包含中止键")
                    fi = record_tick(env, q_target, session,
                                     cam_frame=cam_frame, t_start=0.0)
                    if event == "scoop_done":
                        session["buffer"].mark("scoop_done", fi)
                        events_summary.setdefault(str(ei), []).append(fi)
            except ConfigError as exc:
                return fail(f"mock 采集第 {ei} 回合失败：{exc}")
            writer.finish_episode()
    finally:
        env.disable()
    root, v_report = finish_and_validate(writer)
    print(f"WROTE: {root}")
    print("VALIDATE:", v_report)
    if args.report is not None:
        emit_report(args.report, module=_MODULE,
                    cmd="python -m chengshao.training.record.record_keyboard --mock",
                    metrics={"episodes": args.episodes,
                             "frames": int(v_report.get("frames") or 0),
                             "dataset_root": str(root), "validation": v_report,
                             "events": events_summary},
                    thresholds={"format_validation_ok": True,
                                "state_dim": N_ARM_JOINTS,
                                "fps_band": "30-50"},
                    passed=bool(v_report["ok"]))
        print(f"REPORT: {args.report}")
    return 0 if v_report["ok"] else 1


def run_real(args: argparse.Namespace, cams: list[str], out_dir: Path) -> int:
    """真实采集：CS_HW_SESSION=1 + FeetechArm + 相机 + pynput；缺失 exit 2。"""
    from chengshao.cs_arm import HardwareUnavailable, FeetechArm, FeetechArmConfig, SafetyEnvelope

    require_hw_session("record_keyboard")
    if not args.port.strip():
        print("[training] 错误：--execute 需要 --port（真机串口号）；"
              "未配置即拒绝（fail-closed）。", file=sys.stderr)
        return 2
    try:
        import pynput  # noqa: F401
        from pynput import keyboard
    except ImportError as exc:
        print(f"[training] 错误：键盘监听依赖 pynput 不可用（{exc}）——拒绝真实采集。",
              file=sys.stderr)
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

    def key_token(key) -> str | None:
        import pynput

        if isinstance(getattr(key, "char", None), str) and key.char:
            return key.char.lower()
        if key is pynput.keyboard.Key.space:
            return "space"
        if key is pynput.keyboard.Key.enter:
            return "enter"
        if key is pynput.keyboard.Key.esc:
            return "esc"
        return None

    def on_press(key) -> None:
        token = key_token(key)
        if token is not None:
            keys.append(token)

    keys: list[str] = []
    listener = keyboard.Listener(on_press=on_press)
    listener.start()

    caps: dict = {}
    try:
        arm = FeetechArm(FeetechArmConfig(port=args.port.strip()))
        env = SafetyEnvelope(arm)
        model = env.model
        for cam in cams:
            cap = open_camera(cam_devs.get(cam, 0))
            if cap is None:
                print(f"[training] 错误：相机 {cam}（dev={cam_devs.get(cam, 0)}）"
                      "无法打开——设备缺失即拒绝（fail-closed）。", file=sys.stderr)
                return 2
            caps[cam] = cap
        writer = DatasetWriter(out_dir, task=args.task, cams=cams, fps=args.fps,
                               joint_names=list(model.joint_names))
        q_target = clip_to_limits(model, np.asarray(env.read().joint_pos, dtype=float))
        period = 1.0 / float(args.fps)
        finished = 0
        env.enable()
        print("RECORDING: esc=中止 enter=结束本回合；"
              f"目标 {args.episodes} 回合 @ {args.fps}Hz")
        aborted = False
        while not aborted and finished < args.episodes:
            session = {"buffer": writer.start_episode(finished), "step": 0}
            cam_frame = make_cam_frame_real(caps)
            episode_done = False
            while not episode_done:
                drained = keys[:]  # 快照后原地清空（清空窗口内的新按键下一拍消费）
                keys.clear()
                pending_event = ""
                for token in drained:
                    q_target, event = apply_token(q_target, token, float(args.delta))
                    q_target = clip_to_limits(model, q_target)
                    if event == "__abort__":
                        listener.stop()
                        print("ABORT: 操作者中止；已完成回合保留，"
                              "当前未完成回合丢弃。", file=sys.stderr)
                        writer.discard_episode()
                        aborted = True
                        break
                    if event == "__episode_end__":
                        episode_done = True
                        break
                    if event == "scoop_done":
                        pending_event = "scoop_done"
                if aborted:
                    break
                # 无按键也记录：控制节拍 = 帧节拍（30–50Hz 连续记录）
                fi = record_tick(env, q_target, session, cam_frame=cam_frame,
                                 t_start=time.monotonic())
                if pending_event:
                    session["buffer"].mark("scoop_done", fi)
                time.sleep(period)
            if aborted:
                break
            writer.finish_episode()
            finished += 1
            print(f"EPISODE {finished}/{args.episodes} 完成（enter 后 1s 缓冲）")
            time.sleep(1.0)
        if aborted:
            listener.stop()
            for cap in caps.values():
                cap.release()
            if finished == 0:
                return 2
            root, v_report = finish_and_validate(writer)
            print(f"WROTE(部分): {root}")
            print("VALIDATE:", v_report)
            return 0 if v_report["ok"] else 1
        env.disable()
        listener.stop()
        for cap in caps.values():
            cap.release()
        root, v_report = finish_and_validate(writer)
        print(f"WROTE: {root}")
        print("VALIDATE:", v_report)
        if args.report is not None:
            emit_report(args.report, module=_MODULE,
                        cmd="python -m chengshao.training.record.record_keyboard --execute",
                        metrics={"episodes": finished, "validation": v_report},
                        thresholds={"format_validation_ok": True},
                        passed=bool(v_report["ok"]))
        return 0 if v_report["ok"] else 1
    except HardwareUnavailable as exc:
        print(f"[training] 错误：真机通道不可用（{exc}）——骨架阶段显式失败。",
              file=sys.stderr)
        return 2
    finally:
        listener.stop()
        for cap in caps.values():
            try:
                cap.release()
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    raise SystemExit(main())
