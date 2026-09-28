"""编排核心：运行参数 / 追踪 / 相机角色台账 / 单口状态机 / 臂服务 / 路线跟随器。

本模块承载行为树的全部共享状态与机械件；行为节点见 :mod:`.nodes`，
mock 依赖注入实现见 :mod:`.mock`，生产接线见 :mod:`.runtime`。

单口状态机（冻结，开发指令 §5.6；tests/test_orchestra.py 按本表断言）::

    每口主序列（无中断时严格按序）：
      SELECT_BOWL -> SCOOP -> SPOON_CHECK -> DELIVER -> WAIT_OPEN
                  -> WAIT_BITE -> SPOON_EMPTY -> RETRACT -> RECORD -> 下一口
    - SCOOP：脚本参数化轨迹 + 腕部检查闭环，空勺重舀（重试 <=2）；
      重试耗尽仍空 => 本口 outcome=retry，跳过 DELIVER/WAIT 直接 RETRACT
      （该口 camera_role 全程 scene，0 次切换——从未进入送达）。
    - SPOON_CHECK 通过 => 进入 DELIVER 的转换沿：
      camera_role: scene -> wrist_mouth（原因 delivery_entry），
      此后曝光稳定窗（默认 0.5s）内的口部帧一律不采信（valid=False）。
    - WAIT_OPEN：勺停口前（包络送达停点），等待张嘴（jaw_open>0.35）；
      WAIT_BITE：张嘴后等待咬合（jaw 回落）；SPOON_EMPTY：勺空确认。
    - RETRACT 完成转换沿：camera_role: wrist_mouth -> scene（原因
      retract_complete），随后 RECORD 写 BiteRecord。

    打断分支（每 tick 最高优先级，响应动作冻结）：
      软件急停（estop 闩锁）  -> 立即停 + camera_role->scene(estop_abort)
                                + 本口 outcome=aborted + 等复位+resume/next
      禁入区违规（闩锁）      -> 立即停 + camera_role->scene(zone_abort)
                                + 本口 outcome=aborted + 复位后原路退回+回家
                                （覆盖"后撤 5cm"的安全意图；TCP 仍在区内时
                                复位会如实重新闩锁，闸保持 RUNNING 等待外部
                                解除；mock 用 teleport 装配）
      转头/人脸丢失 >1s       -> 保持（不再下发新指令段）+ 播报一次，
                                恢复后原地继续当前阶段
      intent=pause            -> 悬停 + 播报，intent=resume 解除
      intent=done（吃饱了）   -> 本口 outcome=rejected + 撤回（撤回完成时
                                camera_role->scene, done_retract）+ 会话结束
      intent=next（等待咬合中）-> 跳过等待，本口 outcome=rejected，撤回
      intent=select（我想吃X） -> 记录点菜偏好（菜序->碗序），下一口选碗生效
      frown>0.5               -> 暂停 + 询问播报，frown 回落或 resume 解除

    camera_role 计账（v3.1 契约，eval/tests 逐口断言）：
      每个进入送达的口恰好 2 次切换：
        scene -> wrist_mouth（delivery_entry，进送达运动之前）
        wrist_mouth -> scene（retract_complete / estop_abort / zone_abort /
        done_retract 四者中先发生者），无其他切换。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import numpy as np

try:  # 仓库根运行（pytest / python -m chengshao.*）与包根运行（-m cs_orchestra.*）双形态
    from chengshao.cs_arm import ArmCommandRejected, SafetyEnvelope, VirtualClock
    from chengshao.cs_schema import (
        ArmCommand,
        BiteOutcome,
        BiteRecord,
        CameraRole,
        CommandMode,
        MealSession,
        SafetyState,
        SpoonCheck,
    )
    from chengshao.cs_sim import EnvelopeValidator
except ImportError:  # pragma: no cover - 包根直跑形态
    from cs_arm import ArmCommandRejected, SafetyEnvelope, VirtualClock  # type: ignore[no-redef]
    from cs_schema import (  # type: ignore[no-redef]
        ArmCommand,
        BiteOutcome,
        BiteRecord,
        CameraRole,
        CommandMode,
        MealSession,
        SafetyState,
        SpoonCheck,
    )
    from cs_sim import EnvelopeValidator  # type: ignore[no-redef]

PKG_ROOT = Path(__file__).resolve().parents[1]  # .../chengshao
DEFAULT_CONFIG_PATH = PKG_ROOT / "config" / "orchestra.json"
DEFAULT_WORKSPACE_PATH = PKG_ROOT / "config" / "workspace.json"
DEFAULT_HANDEYE_WRIST = PKG_ROOT / "config" / "calib" / "handeye_wrist.npz"

# 腕部手眼外参名义值（eye-in-hand 标定前的缺省；标定后由 handeye_wrist.npz 覆盖）。
# 约定：flange 系 X 前向朝用户；相机系 OpenCV（Z 前向）：cam_z 沿 flange +X，
# cam_x 沿 flange -Y，cam_y 沿 flange -Z；相机光心在 flange 前方 2cm、上方 5cm。
NOMINAL_T_FLANGE_CAM: list[list[float]] = [
    [0.0, 0.0, 1.0, 0.02],
    [0.0, 1.0, 0.0, 0.0],
    [-1.0, 0.0, 0.0, 0.05],
    [0.0, 0.0, 0.0, 1.0],
]


def load_t_flange_cam(path: str | Path | None = None) -> np.ndarray:
    """腕部手眼外参：handeye_wrist.npz（key=T_flange_cam）优先，否则名义值。"""
    p = Path(path) if path is not None else DEFAULT_HANDEYE_WRIST
    if p.is_file():
        try:
            with np.load(p) as data:
                if "T_flange_cam" in data:
                    m = np.asarray(data["T_flange_cam"], dtype=float)
                    if m.shape == (4, 4):
                        return m
        except (OSError, ValueError):
            pass
    return np.asarray(NOMINAL_T_FLANGE_CAM, dtype=float)


def quat_to_mat(quat: list[float] | np.ndarray) -> np.ndarray:
    """单位四元数 [w, x, y, z] -> 3×3 旋转矩阵（ArmState.ee_quat -> 4×4 用）。"""
    w, x, y, z = (float(v) for v in quat)
    n = w * w + x * x + y * y + z * z
    s = 0.0 if n < 1e-15 else 2.0 / n
    xx, yy, zz = s * x * x, s * y * y, s * z * z
    xy, xz, yz = s * x * y, s * x * z, s * y * z
    wx, wy, wz = s * w * x, s * w * y, s * w * z
    return np.array([
        [1.0 - (yy + zz), xy - wz, xz + wy],
        [xy + wz, 1.0 - (xx + zz), yz - wx],
        [xz - wy, yz + wx, 1.0 - (xx + yy)],
    ])


def flange_pose_mat(ee_pos: list[float], ee_quat: list[float]) -> np.ndarray:
    """ArmState 的 ee_pos/ee_quat -> T_base_flange（4×4 齐次，base 系）。"""
    m = np.eye(4)
    m[:3, :3] = quat_to_mat(ee_quat)
    m[:3, 3] = np.asarray(ee_pos, dtype=float)
    return m


# ---- 单口阶段 -----------------------------------------------------------------


class BitePhase(Enum):
    """单口阶段（顺序即状态转移表；数值只增不改）。"""

    IDLE = 0
    SELECT_BOWL = 1
    SCOOP = 2
    SPOON_CHECK = 3
    DELIVER = 4
    WAIT_OPEN = 5
    WAIT_BITE = 6
    SPOON_EMPTY = 7
    RETRACT = 8
    RECORD = 9


# 进入送达之后的阶段：camera_role 应处于 wrist_mouth（撤回完成才切回）。
WRIST_PHASES: frozenset[BitePhase] = frozenset({
    BitePhase.DELIVER,
    BitePhase.WAIT_OPEN,
    BitePhase.WAIT_BITE,
    BitePhase.SPOON_EMPTY,
})

STATE_TRANSITION_TABLE = __doc__ or ""  # docstring 即冻结状态转移表（tests 断言存在）


# ---- 运行参数 -----------------------------------------------------------------


@dataclass
class OrchestraParams:
    """编排运行参数（config/orchestra.json 可覆盖；缺省值与文件一致）。"""

    tick_s: float = 0.02  # 行为树 tick 周期（50Hz，§5.6）
    cruise_speed_mps: float = 0.14  # 转运巡航（< 接近段硬限 0.15，留包络余量）
    approach_speed_mps: float = 0.08  # 末段逼近送达停点
    scoop_descend_speed_mps: float = 0.06  # 入碗慢降
    route_step_m: float = 0.03  # 转运段流式步长（细步防关节大步密的峰速超限）
    final_step_m: float = 0.02  # 末段流式步长
    exposure_settle_s: float = 0.5  # 相机角色切换后曝光稳定窗（契约 v3.1）
    turn_sustain_s: float = 1.0  # 转头/人脸丢失保持判定的持续阈值（§5.6）
    wait_bite_timeout_s: float = 25.0  # 等待咬合超时（超时按 rejected 撤回）
    scoop_retries_max: int = 2  # 空勺重舀上限（含首次共 <=3 次行程）
    spoon_empty_rechecks: int = 3  # 勺空确认复检次数
    spoon_recheck_interval_s: float = 0.5
    retreat_distance_m: float = 0.05  # 禁入区后撤距离（§5.6）
    arrive_tolerance_m: float = 0.01  # 送达到位判定半径
    cmd_timeout_s: float = 30.0  # 单条 ArmCommand 超时（仿真秒）
    max_meal_sim_s: float = 900.0  # 单餐仿真时长上限（防挂死）
    home_point_m: list[float] = field(default_factory=lambda: [0.24, -0.08, 0.16])
    # 送达途经点（碗上悬停 -> 途经 -> 预停点 -> 停点；仿真逐碗调参，见 §5.6/M5）
    delivery_via_points_m: list[list[float]] = field(default_factory=lambda: [
        [0.22, -0.09, 0.18], [0.20, -0.05, 0.26]])
    # 逐碗覆盖（按碗序；空表 = 全部用共享途经点）。仿真走廊搜索实测选优。
    delivery_via_points_by_bowl: list = field(default_factory=lambda: [
        [[0.21, -0.07, 0.16], [0.20, -0.05, 0.26]],
        [[0.22, -0.10, 0.20], [0.20, -0.05, 0.26]],
        [[0.22, -0.09, 0.18], [0.19, -0.04, 0.22]],
    ])
    stop_approach_offset_m: float = 0.08  # 送达停点 -X 方向的预停点偏移
    # 关节轨迹回放速度上限（rad/s；逐写按 TCP 增益再收严，见 RouteFollower）
    jtrack_replay_speed_rad_s: float = 1.2
    bowl_hover_offset_m: float = 0.08  # 碗上方悬停高度
    bowl_dip_offset_m: float = 0.015  # 入碗深度（碗口向上偏移量）
    gripper_open: float = 0.6
    gripper_close: float = 0.2
    # mock 用户反应参数（生产无此组；仅 mock 仿真用）
    user_reaction_delay_s: float = 0.4
    user_open_dwell_s: float = 0.4
    user_bite_close_s: float = 0.3
    user_reach_tolerance_m: float = 0.012

    @classmethod
    def load(cls, path: str | Path | None = None) -> "OrchestraParams":
        """装载 config/orchestra.json；缺失/损坏回退缺省（工程容错）。"""
        p = Path(path) if path is not None else DEFAULT_CONFIG_PATH
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f for f in cls.__dataclass_fields__}  # noqa: C416
        clean = {}
        for k, v in d.items():
            if k not in known or isinstance(v, dict):
                continue
            clean[k] = v
        return cls(**clean)

    def delivery_vias_for(self, bowl_index: int | None) -> list[np.ndarray]:
        """该碗的送达途经点（逐碗表优先，回退共享表）。"""
        if (bowl_index is not None and self.delivery_via_points_by_bowl
                and 0 <= int(bowl_index) < len(self.delivery_via_points_by_bowl)):
            rows = self.delivery_via_points_by_bowl[int(bowl_index)]
            if rows:
                return [np.asarray(v, dtype=float) for v in rows]
        return [np.asarray(v, dtype=float) for v in self.delivery_via_points_m]

    def bowls_m(self) -> list[np.ndarray]:
        """碗位（base 系）：config/workspace.json 的 bowls_m，缺失用缺省三点。"""
        try:
            d = json.loads(DEFAULT_WORKSPACE_PATH.read_text(encoding="utf-8"))
            bowls = [np.asarray(b, dtype=float) for b in d.get("bowls_m", [])]
            if bowls:
                return bowls
        except (OSError, ValueError):
            pass
        return [np.array([0.22, -0.18, 0.02]), np.array([0.22, 0.0, 0.02]),
                np.array([0.22, 0.18, 0.02])]


# ---- 追踪（trace，审计用 JSONL 事件流） ---------------------------------------


class Trace:
    """事件追踪：内存累积 + 每回合落盘（reports/orchestra_trace.jsonl，供审计）。"""

    def __init__(self, episode: int, path: Path | None = None) -> None:
        self.episode = int(episode)
        self.path = path
        self.events: list[dict] = []

    def add(self, kind: str, *, ts_ns: int, bite: int | None = None,
            phase: str | None = None, **fields) -> dict:
        ev = {"ts_ns": int(ts_ns), "ep": self.episode, "kind": kind,
              "bite": bite, "phase": phase, **fields}
        self.events.append(ev)
        return ev

    def dump(self) -> int:
        """追加写入本轮事件到 path（存在则续写），返回写入行数。"""
        if self.path is None or not self.events:
            return 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            for ev in self.events:
                f.write(json.dumps(ev, ensure_ascii=False, separators=(",", ":")) + "\n")
        return len(self.events)


# ---- 相机角色台账（v3.1 切换审计：每口恰好 2 次） ------------------------------


class CameraRoleLedger:
    """camera_role 切换台账：每次切换记 (ts, bite, from, to, reason)。

    断言口径（eval 与 tests 共用，见 :meth:`per_bite_report`）：
    进入送达的口恰好 2 次：scene->wrist_mouth(delivery_entry) 与
    wrist_mouth->scene(retract_complete/estop_abort/zone_abort/done_retract)；
    重舀耗尽未进送达的口 0 次。
    """

    def __init__(self) -> None:
        self.switches: list[dict] = []

    def switch(self, ctx: "TickContext", to_role: CameraRole, reason: str) -> dict:
        frm = ctx.camera_role
        if frm is to_role:
            raise ValueError(f"camera_role 重复切换到 {to_role}（reason={reason}）")
        rec = {
            "ts_ns": int(ctx.clock.now_ns()),
            "bite": ctx.bite.idx if ctx.bite else None,
            "from": str(frm),
            "to": str(to_role),
            "reason": reason,
        }
        self.switches.append(rec)
        ctx.camera_role = to_role
        ctx.bb_set("camera_role", to_role)
        ctx.trace.add("role_switch", ts_ns=rec["ts_ns"], bite=rec["bite"],
                      frm=str(frm), to=str(to_role), reason=reason)
        if ctx.deps is not None and ctx.deps.mouth is not None:
            ctx.deps.mouth.set_role(to_role, rec["ts_ns"])
        return rec

    def for_bite(self, bite_idx: int) -> list[dict]:
        return [s for s in self.switches if s["bite"] == bite_idx]

    def per_bite_report(self, bite_idx: int, delivered: bool) -> dict:
        """单口切换判定：delivered 口应恰好 2 次且原因/次序正确；否则 0 次。"""
        sw = self.for_bite(bite_idx)
        if not delivered:
            return {"switches": len(sw), "ok": len(sw) == 0, "detail": sw}
        ok = (
            len(sw) == 2
            and sw[0]["from"] == str(CameraRole.SCENE)
            and sw[0]["to"] == str(CameraRole.WRIST_MOUTH)
            and sw[0]["reason"] == "delivery_entry"
            and sw[1]["from"] == str(CameraRole.WRIST_MOUTH)
            and sw[1]["to"] == str(CameraRole.SCENE)
            and sw[1]["reason"] in ("retract_complete", "estop_abort",
                                    "zone_abort", "done_retract")
            and sw[1]["ts_ns"] >= sw[0]["ts_ns"]
        )
        return {"switches": len(sw), "ok": bool(ok), "detail": sw}


# ---- 臂服务（行为树触达执行层的唯一通道） --------------------------------------


class ArmService:
    """对 SafetyEnvelope 的薄封装：发指令、查在途、读状态，拒绝即落 trace。

    纪律（契约 §3.1）：一切指令经包络下发，本类不提供任何旁路；
    ArmCommandRejected 原样上抛（由调用方决定本口处置）。
    """

    def __init__(self, ctx: "TickContext") -> None:
        self.ctx = ctx

    def cart(self, point, speed: float, timeout_s: float | None = None) -> dict:
        """下发一个 base 系绝对途经点（cartesian，姿态保持）。"""
        cmd = ArmCommand(
            mode=CommandMode.CARTESIAN,
            target=[float(point[0]), float(point[1]), float(point[2])],
            max_speed=float(speed),
            timeout_s=float(timeout_s if timeout_s is not None
                            else self.ctx.params.cmd_timeout_s),
        )
        self.ctx.env.write(cmd)
        return self.ctx.env.last_decision

    def joints(self, q, speed: float) -> dict:
        """下发 6 关节目标（jtrack 回放用）。"""
        cmd = ArmCommand(
            mode=CommandMode.JOINTS,
            target=[float(v) for v in q],
            max_speed=float(speed),
            timeout_s=float(self.ctx.params.cmd_timeout_s),
        )
        self.ctx.env.write(cmd)
        return self.ctx.env.last_decision

    def grip(self, value: float, speed: float = 0.5) -> dict:
        """夹爪开合（joints 指令，臂关节分量保持当前值）。"""
        state = self.ctx.arm_state()
        target = [float(v) for v in state.joint_pos]
        target[-1] = float(value)
        cmd = ArmCommand(mode=CommandMode.JOINTS, target=target,
                         max_speed=float(speed),
                         timeout_s=float(self.ctx.params.cmd_timeout_s))
        self.ctx.env.write(cmd)
        return self.ctx.env.last_decision

    def busy(self) -> bool:
        return bool(getattr(self.ctx.env.inner, "in_motion", False))


# ---- 单口状态 -----------------------------------------------------------------


@dataclass
class BiteState:
    """进行中单口的状态（打开于 SELECT_BOWL，关闭于 RECORD/中止记录）。"""

    idx: int = 0  # 1 起始
    ts_start_ns: int = 0
    phase: BitePhase = BitePhase.IDLE
    outcome: BiteOutcome | None = None
    bowl_index: int | None = None
    bowl_pos_m: np.ndarray | None = None
    scoop_round: int = 0  # 已发起的舀取行程轮次（1 起）
    spoon_checks: int = 0
    delivered: bool = False  # 是否进入过送达（camera_role 断言分叉）
    delivery_entered: bool = False
    aim_offset_m: float | None = None  # 到达时实测口部与名义面中心的横向偏差
    skip_wait: bool = False  # "下一口"跳过等待
    route: "RouteFollower | None" = None  # 当前阶段路线
    empty_rechecks: int = 0
    last_empty_check_ns: int = 0
    open_seen: bool = False  # WAIT_OPEN 期间见过张嘴（进入 WAIT_BITE 的凭据）
    delivered_ns: int = 0  # 到达停点时刻（mock 用户反应计时基准）
    settle_until_ns: int = 0  # 曝光稳定窗截止（delivery_entry 起算）
    last_route_journal: list | None = None  # 上一条完成路线的关节目标序列（回撤用）


# ---- 路线跟随器 ----------------------------------------------------------------

# 路线项：("cart", 点位, 速度, 步长) | ("grip", 开度, 速度) |
#         ("joints", q, 速度) | ("jtrack_reverse", 速度上限) |
#         ("jtrack_seq", 关节轨迹, 速度上限)
RouteItem = tuple


class RouteFollower:
    """把一段路线（cart/grip 项）在逐 tick 中流式下发（经安全包络）。

    - cart 项在起段时从当前 TCP 展开为 <=step 的绝对途经点序列，逐点下发；
    - grip 项下发关节指令（仅夹爪分量变化，臂关节保持）；
    - joints 项逐个下发关节目标；jtrack_reverse 项在执行到时把本路线此前
      记录的关节目标序列**逆序**回放（脚本舀取的抬勺段复用入碗段关节路径，
      避免腕部滚转关节在重构区被点式 IK 换支——路径反转与下行段同样可通行）；
    - journal 只记录**前向探索**写（cart/grip，cart 项按包络同口径预解析
      关节目标）；joints 回放写不计入——保证 jtrack_seq 逆序回放得到的是
      纯去程路径（带嵌入式回放的去程逆序会先重新下碗）；
    - 被打断（急停冻结/闸保持）后原地继续：绝对途经点仍然成立；
    - 任何 ArmCommandRejected 记为 failed（正常调度下不应发生，触发即
      本口按 aborted 处理并落 trace）。
    """

    def __init__(self, ctx: "TickContext", items: list[RouteItem], label: str) -> None:
        self.ctx = ctx
        self.items = list(items)
        self.label = label
        self.i = 0
        self.subpoints: list[np.ndarray] = []
        self.sub_i = 0
        self.journal: list[np.ndarray] = []  # 前向探索写的目标关节角（jtrack_reverse 用）
        self.failed: str | None = None
        self.done = False

    # -- 展开与下发 ------------------------------------------------------------
    def _expand_cart(self, target: np.ndarray, step: float) -> None:
        cur = np.asarray(self.ctx.arm_state().ee_pos, dtype=float)
        n = max(1, int(np.ceil(float(np.linalg.norm(target - cur)) / max(step, 1e-4))))
        self.subpoints = [cur + (target - cur) * (k / n) for k in range(1, n + 1)]
        self.sub_i = 0

    def _replay_speed(self, q_prev: np.ndarray, q_next: np.ndarray) -> float:
        """回放写的逐写速度：按 TCP 增益（chord/dq）对该段限速收严。

        TCP 速度 ≈ chord × speed / dq_max，须 <= 该段限速（近脸 0.10/接近
        0.15）；干净段自动放慢到与原速相当，翻转段（G 小）放到全局上限。
        """
        model = self.ctx.env.model
        p0 = np.asarray(model.fk([float(v) for v in q_prev])[0:3], dtype=float)
        p1 = np.asarray(model.fk([float(v) for v in q_next])[0:3], dtype=float)
        chord = float(np.linalg.norm(p1 - p0))
        dq = float(np.max(np.abs(np.asarray(q_next, dtype=float) - q_prev)))
        if dq < 1e-9:
            return 0.5
        gain = chord / dq
        limit = float(self.ctx.validator.speed_limit_at((p0 + p1) / 2.0))
        return float(min(self.ctx.params.jtrack_replay_speed_rad_s,
                         0.8 * limit / max(gain, 1e-6)))

    def _jtrack_items(self, track: list[np.ndarray]) -> list[RouteItem]:
        """把关节轨迹物化为逐写 joints 项（首写从当前位形起算速度）。"""
        out: list[RouteItem] = []
        q_prev = np.asarray(self.ctx.arm_state().joint_pos, dtype=float)
        for q in track:
            q = np.asarray(q, dtype=float)
            out.append(("joints", q, self._replay_speed(q_prev, q)))
            q_prev = q
        return out

    def _resolve_cart_q(self, target: np.ndarray, speed: float) -> np.ndarray:
        """笛卡尔途经点的关节目标（与安全包络同口径预解析，journal 用）。"""
        try:
            from chengshao.cs_arm.kinematics import resolve_target_joints
        except ImportError:  # pragma: no cover
            from cs_arm.kinematics import resolve_target_joints  # type: ignore[no-redef]

        cmd = ArmCommand(
            mode=CommandMode.CARTESIAN,
            target=[float(target[0]), float(target[1]), float(target[2])],
            max_speed=float(speed),
            timeout_s=float(self.ctx.params.cmd_timeout_s),
        )
        q0 = np.asarray(self.ctx.arm_state().joint_pos, dtype=float)
        return np.asarray(resolve_target_joints(self.ctx.env.model, cmd, q0),
                          dtype=float).copy()

    def tick(self) -> bool:
        """推进一段；返回 True=完成（或失败），False=仍在执行。"""
        if self.done or self.failed is not None:
            return True
        if self.i >= len(self.items):
            if self.ctx.arm.busy():
                return False  # 末段在途
            self.done = True
            return True
        if self.ctx.arm.busy():
            return False  # 当前段在途
        item = self.items[self.i]
        kind = item[0]
        try:
            if kind == "cart":
                _, point, speed, step = item
                if self.sub_i >= len(self.subpoints):
                    self._expand_cart(np.asarray(point, dtype=float), step)
                target = self.subpoints[self.sub_i]
                q1 = self._resolve_cart_q(target, speed)
                self.ctx.arm.cart(
                    target, speed=speed, timeout_s=self.ctx.params.cmd_timeout_s)
                self.journal.append(q1)
                self.sub_i += 1
                if self.sub_i >= len(self.subpoints):
                    self.i += 1
                    self.subpoints, self.sub_i = [], 0
            elif kind == "grip":
                _, value, speed = item
                q_grip = np.asarray(self.ctx.arm_state().joint_pos, dtype=float).copy()
                q_grip[-1] = float(value)
                self.ctx.arm.grip(value, speed=speed)
                self.journal.append(q_grip)
                self.i += 1
            elif kind == "joints":
                _, q, speed = item
                self.ctx.arm.joints(q, speed=speed)
                self.i += 1  # 回放写不计入 journal（journal 只记前向探索路径）
            elif kind == "jtrack_reverse":
                _, speed = item
                track = [q.copy() for q in reversed(self.journal)]
                self.items[self.i : self.i + 1] = self._jtrack_items(track)
                if not track:  # 空轨迹：直接跳过（不报错）
                    self.i += 1
            elif kind == "jtrack_seq":
                _, track, speed = item
                self.items[self.i : self.i + 1] = self._jtrack_items(
                    [np.asarray(q, dtype=float) for q in track])
                if not track:  # 空轨迹：直接跳过（不报错）
                    self.i += 1
            else:
                raise ValueError(f"未知路线项 {kind!r}")
        except ArmCommandRejected as exc:
            self.failed = exc.reason
            self.ctx.trace.add(
                "route_rejected", ts_ns=self.ctx.now_ns(),
                bite=self.ctx.bite.idx if self.ctx.bite else None,
                route=self.label, item=self.i, reason=exc.reason)
            self.done = True
            return True
        return False


def retract_route_items(b: "BiteState | None", params: "OrchestraParams",
                        stop_point: np.ndarray) -> list[RouteItem]:
    """撤回/收尾路线：进过送达的口沿送达走廊**笛卡尔返向**回家
    （停点 -> 预停点 -> 途经点逆序 -> 家；返向已被包络逐口实测可通行，
    且快于关节回放——去程 IK 支在返向种子下保持不变）；未进送达的口
    （碗上悬停）直接回家。开爪项由调用方追加。"""
    if b is None or not b.delivered:
        return [("cart", np.asarray(params.home_point_m, dtype=float),
                 params.cruise_speed_mps, params.route_step_m)]
    stop = np.asarray(stop_point, dtype=float)
    pre = stop + np.array([-float(params.stop_approach_offset_m), 0.0, 0.0])
    items: list[RouteItem] = [("cart", pre, params.approach_speed_mps,
                               params.final_step_m)]
    for v in reversed(params.delivery_vias_for(
            b.bowl_index if b is not None else None)):
        items.append(("cart", np.asarray(v, dtype=float),
                      params.cruise_speed_mps, params.route_step_m))
    items.append(("cart", np.asarray(params.home_point_m, dtype=float),
                  params.cruise_speed_mps, params.route_step_m))
    return items


# ---- 依赖注入容器 -------------------------------------------------------------


@dataclass
class Deps:
    """注入式依赖（各实现消费对应模块的冻结契约接口）。

    - mouth：口部通道（set_role/sample，wrist 角色下经 cam_pose=FK×手眼 出
      基座系坐标，scene 角色下无面部职责、返回失效帧）；
      生产实现消费 cs_mouth.MouthEstimator（cam_pose 契约 v1.1）；
    - scene：场景扫描（select_bowl）；生产实现消费 cs_food.BowlSelector；
    - spoon：勺上检查源（check）；生产实现消费 cs_food.SpoonClassifier 协议；
    - voice：语音总线（poll/say）；生产实现消费 cs_voice.VoiceLink 冻结接口；
    - sink：进餐记录池（start_session/post_bite/end_session）；
      生产实现消费 cs_dashboard HTTP 契约；
    - scoop：舀取策略（MockScoop；ScriptedScoop/学习型策略对齐同一交互）。
    """

    mouth: object | None = None
    scene: object | None = None
    spoon: object | None = None
    voice: object | None = None
    sink: object | None = None
    scoop: object | None = None


# ---- tick 上下文 ---------------------------------------------------------------


class TickContext:
    """行为树全部节点共享的逐 tick 上下文（黑板冻结键的写入方）。"""

    def __init__(
        self,
        *,
        env: SafetyEnvelope,
        clock: VirtualClock | None,
        params: OrchestraParams | None,
        deps: Deps,
        validator: EnvelopeValidator,
        episode: int = 1,
        user_id: str = "user-mock",
        trace_path: Path | None = None,
    ) -> None:
        from py_trees.blackboard import Blackboard

        self.env = env
        self.clock = clock if clock is not None else _WallClock()
        self.params = params if params is not None else OrchestraParams.load()
        self.deps = deps
        self.validator = validator
        self.episode = int(episode)
        self.trace = Trace(self.episode, trace_path)
        self.ledger = CameraRoleLedger()
        self.bb = Blackboard()

        self.arm = ArmService(self)

        self.camera_role: CameraRole = CameraRole.SCENE
        self.user_id = user_id
        self.session: MealSession | None = None
        self.bite: BiteState | None = None
        self.bites_done: list[BiteRecord] = []
        self.max_bites: int = 15
        self.meal_finished: bool = False

        # 交互状态
        self.pending_intents: list[object] = []
        self.last_intent: object | None = None
        self.estop_entered: bool = False
        self.zone_entered: bool = False
        self.pause_active: bool = False
        self.pause_announced: bool = False
        self.turn_hold: bool = False
        self.turn_announced: bool = False
        self.turn_since_ns: int | None = None
        self.frown_hold: bool = False
        self.frown_announced: bool = False
        self.frown_since_ns: int | None = None
        self.done_shutdown: bool = False
        self.announce_counts: dict[str, int] = {}
        self.requested_dish: str | None = None
        self.unexpected_failures: list[str] = []
        self.zone_retreat: RouteFollower | None = None
        self.shutdown_route: RouteFollower | None = None
        self.aborted_journal: list | None = None  # 被中止路线的前向关节路径（安全恢复回家用）
        # 口部采样审计：每 tick 记录 (ts, role, valid, T_base_flange)
        self.mouth_samples: list[tuple[int, str, bool, np.ndarray]] = []

    # -- 黑板（冻结键） ---------------------------------------------------------
    def bb_set(self, key: str, value) -> None:
        self.bb.set(key, value)

    # -- 时间/臂助手 ------------------------------------------------------------
    def now_ns(self) -> int:
        return int(self.clock.now_ns())

    def arm_state(self):
        return self.env.read()

    def arm_busy(self) -> bool:
        return self.arm.busy()

    def say(self, text: str, key: str) -> None:
        """播报（语音总线）+ trace；key 用于一次性播报去重与统计。"""
        if self.deps.voice is not None:
            self.deps.voice.say(text)
        self.announce_counts[key] = self.announce_counts.get(key, 0) + 1
        self.trace.add("announce", ts_ns=self.now_ns(),
                       bite=self.bite.idx if self.bite else None, key=key, text=text)

    # -- 意图消费（闸节点专用；FIFO 逐条取用） ----------------------------------
    def take_intent(self, *kinds: str):
        """取走最早一条 intent 命中 kinds 的挂起意图；无则 None。"""
        want = {str(k).split(".")[-1] for k in kinds}
        for i, it in enumerate(self.pending_intents):
            if str(it.intent).split(".")[-1] in want:
                return self.pending_intents.pop(i)
        return None

    def take_recovering_intent(self):
        """安全闸恢复凭据：resume / next 任一。"""
        return self.take_intent("resume", "next")

    # -- 口部采样（runner 每 tick 调用） ----------------------------------------
    def sample_mouth(self):
        """采样口部（相机角色感知）：wrist 角色传 cam_pose=FK×手眼（契约 v1.1）。

        返回 MouthPose（或 None，未注入 mouth 依赖时）；每次采样记入
        mouth_samples 审计（ts、当时角色、有效性、采样时的 T_base_flange）。
        """
        if self.deps.mouth is None:
            return None
        state = self.arm_state()
        t_flange = flange_pose_mat(state.ee_pos, state.ee_quat)
        pose = self.deps.mouth.sample(t_flange)
        if pose is not None:
            self.bb_set("mouth", pose)
            self.mouth_samples.append(
                (int(pose.ts_ns), str(self.camera_role), bool(pose.valid), t_flange))
            if len(self.mouth_samples) > 8192:  # 防长餐内存膨胀（保留近段审计）
                del self.mouth_samples[:4096]
        return pose

    # -- 口生命周期 --------------------------------------------------------------
    def open_bite(self) -> BiteState:
        self.bite = BiteState(
            idx=len(self.bites_done) + 1,
            ts_start_ns=self.now_ns(),
            phase=BitePhase.SELECT_BOWL,
        )
        self.trace.add("bite_open", ts_ns=self.bite.ts_start_ns, bite=self.bite.idx)
        return self.bite

    def close_bite(self, outcome: BiteOutcome) -> BiteRecord:
        """记录并关闭当前口（正常 RECORD 与各中止路径共用）。

        b.outcome 已被前置（如重舀耗尽的 retry / 跳过等待的 rejected）时以
        前置值为准；重复关闭（口已不在场）视为程序错误。
        """
        b = self.bite
        assert b is not None, "close_bite 要求口处于打开状态"
        final = b.outcome if b.outcome is not None else outcome
        now = self.now_ns()
        rec = BiteRecord(
            bite_id=b.idx - 1,
            ts_start_ns=int(b.ts_start_ns),
            ts_end_ns=int(now),
            outcome=final,
            grams_before=None,
            grams_after=None,
        )
        if self.deps.sink is not None:
            self.deps.sink.post_bite(rec)
        if self.session is not None:
            self.session.bites.append(rec)
        self.bites_done.append(rec)
        b.outcome = outcome
        self.bb_set("session", self.session)
        self.trace.add("bite_recorded", ts_ns=now, bite=b.idx,
                       outcome=str(outcome), sim_s=round((now - b.ts_start_ns) / 1e9, 3))
        self.bite = None
        return rec

    def abort_current_bite(self, outcome: BiteOutcome, reason: str) -> None:
        """中止当前口：停臂、切回 scene（若在腕部角色）、按 outcome 记录。"""
        self.env.halt()
        b = self.bite
        role_reason = "estop_abort" if reason == "estop" else "zone_abort"
        if b is not None:
            b.phase = BitePhase.RETRACT  # 其余节点按"已过阶段"跳过
            if b.route is not None and b.route.journal:
                self.aborted_journal = [q.copy() for q in b.route.journal]
            b.route = None
            b.delivered = b.delivered or b.delivery_entered
            if self.camera_role is CameraRole.WRIST_MOUTH:
                self.ledger.switch(self, CameraRole.SCENE, role_reason)
            self.close_bite(outcome)
        self.trace.add("bite_aborted", ts_ns=self.now_ns(), reason=reason)


class _WallClock:
    """缺省墙钟（perf_counter_ns；mock eval 一律注入 VirtualClock）。"""

    def now_ns(self) -> int:
        return time.perf_counter_ns()
