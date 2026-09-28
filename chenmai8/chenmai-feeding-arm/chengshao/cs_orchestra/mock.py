"""mock 依赖注入实现：脚本化用户/场景/勺检/语音/记录池 + 回合驱动器。

本模块全部为无硬件 mock（开发指令 §5.6 eval 与 tests 使用），各实现对齐
生产实现消费的同一契约接口（生产接线见 :mod:`.runtime`）：

- :class:`FakeMouthChannel` 口部通道：scene 角色返回失效帧（顶部相机无面部
  职责）；wrist_mouth 角色在曝光稳定窗内不采信帧，其后输出 source="wrist"
  的基座系口部位姿（脚本化用户模拟器驱动 jaw/头姿）；同时记录收到的
  ``T_base_flange``（FK×手眼审计用）。
- :class:`FakeSceneScanner` 场景扫描：按口序轮换登记碗（场景基准码 mock）。
- :class:`FakeSpoonSource` 勺上检查源：世界状态（勺上是否有食物）出
  ``SpoonCheck``。
- :class:`MockScoop` 舀取策略（ScriptedScoop 的 mock 实现，同交互契约）：
  参数化轨迹（悬停->慢降->合爪->抬勺），重舀轮次带闭环修正抖动。
- :class:`ScriptedVoice` 语音总线：队列注入意图（不经麦克风），播报记录。
- :class:`MemorySink` 进餐记录池：内存保存（生产为 cs_dashboard HTTP）。
- :class:`ScenarioDriver` 回合驱动器：按 :class:`MealScript` 在 tick 间注入
  操作员/场景事件（急停、复位+继续、吃饱了、转头窗口由通道自驱动）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import numpy as np

try:  # 仓库根运行与包根运行双形态
    from chengshao.cs_orchestra.core import (
        Deps,
        OrchestraParams,
        TickContext,
        load_t_flange_cam,
    )
    from chengshao.cs_orchestra.nodes import MealRunner
    from chengshao.cs_arm import MockArm, SafetyEnvelope, VirtualClock
    from chengshao.cs_schema import (
        IntentKind,
        MouthPose,
        MouthSource,
        SpoonCheck,
        VoiceIntent,
    )
    from chengshao.cs_sim import EnvelopeValidator, load_arm
    from chengshao.cs_sim.ik_solver import solve_with_restarts
except ImportError:  # pragma: no cover - 包根直跑形态
    from cs_orchestra.core import (  # type: ignore[no-redef]
        Deps,
        OrchestraParams,
        TickContext,
        load_t_flange_cam,
    )
    from cs_orchestra.nodes import MealRunner  # type: ignore[no-redef]
    from cs_arm import MockArm, SafetyEnvelope, VirtualClock  # type: ignore[no-redef]
    from cs_schema import (  # type: ignore[no-redef]
        IntentKind,
        MouthPose,
        MouthSource,
        SpoonCheck,
        VoiceIntent,
    )
    from cs_sim import EnvelopeValidator, load_arm  # type: ignore[no-redef]
    from cs_sim.ik_solver import solve_with_restarts  # type: ignore[no-redef]

# 转头判定演示值（rad，约 35° > 25° 冻结阈值）与正常头姿
_TURN_YAW_RAD = 0.62
_NORMAL_YAW_RAD = 0.05
_JAW_CLOSED = 0.05
_JAW_OPEN = 0.85


# ---- 世界状态（各 mock 共享） ---------------------------------------------------


@dataclass
class ScriptState:
    """单回合世界状态：脚本 + 运行期标志（用户嘴部/勺上食物/事件窗口）。"""

    script: dict[int, dict]
    params: OrchestraParams
    face_center: np.ndarray
    bite_idx: int = 0
    bite_cfg: dict = field(default_factory=dict)
    food_on_spoon: bool = False
    bitten: bool = False
    miss_rounds: int = 0  # 前 N 轮舀取不命中（脚本）
    rounds_done: int = 0  # 已完成的舀取行程轮数
    # 用户状态机
    user_phase: str = "idle"  # idle -> opening -> open -> biting -> done
    user_t0_ns: int = 0
    jaw: float = _JAW_CLOSED
    turn_started: bool = False
    turn_until_ns: int = 0
    face_lost_until_ns: int = 0

    def cfg_of(self, bite_idx: int) -> dict:
        return dict(self.script.get(bite_idx, {}))

    def new_bite(self, bite_idx: int, cfg: dict) -> None:
        self.bite_idx = int(bite_idx)
        self.bite_cfg = cfg
        self.food_on_spoon = False
        self.bitten = False
        miss = cfg.get("miss_rounds")
        if miss is None and cfg.get("first_scoop_empty"):
            miss = 1
        if cfg.get("scoop_always_empty"):
            miss = 99
        self.miss_rounds = int(miss or 0)
        self.rounds_done = 0
        self.user_phase = "idle"
        self.user_t0_ns = 0
        self.jaw = _JAW_CLOSED
        self.turn_started = False
        self.turn_until_ns = 0
        self.face_lost_until_ns = 0

    def ensure_bite(self, ctx: TickContext) -> None:
        """随 tick 对齐当前口（开新口时重置世界状态）。"""
        b = ctx.bite
        if b is not None and b.idx != self.bite_idx:
            self.new_bite(b.idx, self.cfg_of(b.idx))

    def reaction_delay_s(self) -> float:
        return float(self.bite_cfg.get("reaction_s", self.params.user_reaction_delay_s))


# ---- 口部通道（用户模拟器 + 角色语义） ------------------------------------------


class FakeMouthChannel:
    """口部通道 mock：契约同生产实现（set_role/sample；scene 角色无面部帧）。"""

    cam_ref = "wrist_cam"

    def __init__(self, state: ScriptState, rng: np.random.Generator) -> None:
        self.state = state
        self.rng = rng
        self.role = "scene"
        self.role_ts_ns = 0
        self.ctx: TickContext | None = None
        self.received_t_flange: list[np.ndarray] = []  # FK×手眼 审计
        self.cam_positions: list[np.ndarray] = []  # T_base_cam 平移审计

    # -- 绑定（工厂在 ctx 构造后调用） ------------------------------------------
    def bind(self, ctx: TickContext, _env, _mock) -> None:
        self.ctx = ctx

    def set_role(self, role, ts_ns: int) -> None:
        self.role = str(role)
        self.role_ts_ns = int(ts_ns)

    # -- 采样（每 tick 由 runner 调用） -----------------------------------------
    def sample(self, t_base_flange: np.ndarray) -> MouthPose:
        ctx = self.ctx
        assert ctx is not None, "bind() 未调用"
        t = np.asarray(t_base_flange, dtype=float)
        self.received_t_flange.append(t.copy())
        if len(self.received_t_flange) > 512:  # 审计留近段
            del self.received_t_flange[:256]
        now = ctx.now_ns()
        self.state.ensure_bite(ctx)
        # 腕部相机位姿（名义手眼外参与 cs_orchestra.core 一致）
        t_base_cam = t @ load_t_flange_cam()
        self.cam_positions.append(t_base_cam[:3, 3].copy())
        if len(self.cam_positions) > 512:
            del self.cam_positions[:256]

        self._tick_user(now)
        if self.role != "wrist_mouth":
            return self._invalid(now)  # 顶部相机无面部职责
        if now - self.role_ts_ns < int(ctx.params.exposure_settle_s * 1e9):
            return self._invalid(now)  # 曝光稳定窗内不采信
        if now < self.state.face_lost_until_ns:
            return self._invalid(now)  # 脚本人脸丢失窗口
        yaw = _TURN_YAW_RAD if now < self.state.turn_until_ns else _NORMAL_YAW_RAD
        face = self.state.face_center
        noise = self.rng.uniform(-0.002, 0.002, size=3)
        return MouthPose(
            ts_ns=now,
            valid=True,
            x=float(face[0] + noise[0]),
            y=float(face[1] + noise[1]),
            z=float(face[2] + noise[2]),
            jaw_open=float(self.state.jaw),
            frown=float(self.state.bite_cfg.get("frown", 0.02)),
            head_yaw=float(yaw),
            head_pitch=0.02,
            head_roll=0.0,
            source=MouthSource.WRIST,
            confidence=0.9,
        )

    # -- 用户状态机（仅腕部角色且勺已到位时推进） --------------------------------
    def _tick_user(self, now: int) -> None:
        ctx = self.ctx
        st = self.state
        b = ctx.bite
        if b is None:
            return
        cfg = st.bite_cfg
        # 转头/人脸丢失窗口：首次进入腕部角色的送达阶段后触发一次
        if cfg.get("turn_s") and not st.turn_started \
                and self.role == "wrist_mouth" \
                and b.phase.value >= 4:  # DELIVER 起
            st.turn_started = True
            st.turn_until_ns = now + int(float(cfg["turn_s"]) * 1e9)
        if cfg.get("face_lost_s") and st.face_lost_until_ns == 0 \
                and self.role == "wrist_mouth" and b.phase.value >= 4:
            st.face_lost_until_ns = now + int(float(cfg["face_lost_s"]) * 1e9)

        if b.phase.value < 5:  # 未到 WAIT_OPEN：勺未停稳，用户闭嘴等待
            st.jaw = _JAW_CLOSED
            st.user_phase = "idle"
            return
        if st.bitten:
            st.jaw = _JAW_CLOSED
            return
        p = st.params
        if st.user_phase == "idle":
            if now >= b.delivered_ns + int(st.reaction_delay_s() * 1e9):
                st.user_phase = "opening"
                st.user_t0_ns = now
        elif st.user_phase == "opening":
            f = min(1.0, (now - st.user_t0_ns) / 0.3e9)
            st.jaw = _JAW_CLOSED + (_JAW_OPEN - _JAW_CLOSED) * f
            if f >= 1.0:
                st.user_phase = "open"
                st.user_t0_ns = now
        elif st.user_phase == "open":
            st.jaw = _JAW_OPEN
            if now - st.user_t0_ns >= int(p.user_open_dwell_s * 1e9):
                st.user_phase = "biting"
                st.user_t0_ns = now
        elif st.user_phase == "biting":
            f = min(1.0, (now - st.user_t0_ns) / max(p.user_bite_close_s * 1e9, 1e6))
            st.jaw = _JAW_OPEN * (1.0 - f)
            if st.jaw <= 0.20:  # 咬合完成：勺空（世界事实）
                st.jaw = _JAW_CLOSED
                st.bitten = True
                st.food_on_spoon = False
                st.user_phase = "done"

    def _invalid(self, now: int) -> MouthPose:
        pos = self.state.face_center
        return MouthPose(
            ts_ns=now, valid=False,
            x=float(pos[0]), y=float(pos[1]), z=float(pos[2]),
            jaw_open=0.0, frown=0.0, head_yaw=0.0, head_pitch=0.0, head_roll=0.0,
            source=MouthSource.MONO, confidence=0.0)


# ---- 场景扫描 / 勺检 / 舀取策略 --------------------------------------------------


class FakeSceneScanner:
    """场景扫描 mock：按口序轮换登记碗（对应 3 碗 3 码）。"""

    cam_ref = "scene_cam"

    def __init__(self, n_bowls: int = 3) -> None:
        self.n_bowls = int(n_bowls)
        self.ctx: TickContext | None = None

    def bind(self, ctx: TickContext, _env, _mock) -> None:
        self.ctx = ctx

    def select_bowl(self) -> int | None:
        assert self.ctx is not None
        b = self.ctx.bite
        if b is None:
            return None
        return (b.idx - 1) % self.n_bowls


class FakeSpoonSource:
    """勺上检查源 mock：世界状态（勺上是否有食物）-> SpoonCheck（腕部相机）。"""

    cam_ref = "wrist_cam"

    def __init__(self, state: ScriptState) -> None:
        self.state = state
        self.ctx: TickContext | None = None

    def bind(self, ctx: TickContext, _env, _mock) -> None:
        self.ctx = ctx

    def check(self) -> SpoonCheck:
        st = self.state
        has_food = bool(st.food_on_spoon) and not st.bitten
        return SpoonCheck(
            ts_ns=self.ctx.now_ns() if self.ctx else 0,
            has_food=has_food,
            score=0.86 if has_food else 0.02,
            cam_ref=self.cam_ref,
        )


class MockScoop:
    """舀取策略 mock（ScriptedScoop 的同交互 mock 实现）。

    轨迹：碗上悬停 -> 慢降到碗内（重舀轮次带闭环修正抖动）-> 合爪 -> 抬勺。
    世界侧：行程完成即"命中"（前 miss_rounds 轮除外——模拟舀空）。
    """

    def __init__(self, params: OrchestraParams, state: ScriptState,
                 rng: np.random.Generator) -> None:
        self.params = params
        self.state = state
        self.rng = rng

    def plan_round(self, round_idx: int, bowl_pos, bite_idx: int) -> list[tuple]:
        p = self.params
        bowl = np.asarray(bowl_pos, dtype=float)
        hover = bowl + np.array([0.0, 0.0, p.bowl_hover_offset_m])
        dip = bowl + np.array([0.0, 0.0, p.bowl_dip_offset_m])
        if round_idx > 1:  # 腕部闭环修正：重舀轮次微调入碗点
            dip = dip + np.asarray(
                self.rng.uniform(-0.01, 0.01, size=2).tolist() + [0.0], dtype=float)
        return [
            ("cart", hover, p.cruise_speed_mps, p.route_step_m),
            ("cart", dip, p.scoop_descend_speed_mps, p.final_step_m),
            ("grip", p.gripper_close, 0.8),
            # 抬勺：逆序回放入碗段的关节路径（路径反转）——入碗段已逐点过包络，
            # 反向同样可通行；避免点式 IK 在腕部滚转重构区换支（3+ rad 突跳）。
            # 回放终点为入碗段首点（悬停下沿一档），补一记短笛卡尔腿到悬停点。
            ("jtrack_reverse", p.jtrack_replay_speed_rad_s),
            ("cart", hover, p.scoop_descend_speed_mps, p.final_step_m),
        ]

    def on_round_complete(self, round_idx: int) -> None:
        self.state.rounds_done = int(round_idx)
        self.state.food_on_spoon = round_idx > self.state.miss_rounds

    def on_spoon_check(self, check: SpoonCheck) -> bool:
        return bool(check.has_food)

    def retries_left(self) -> int:
        """剩余重舀次数（含首次共 <=scoop_retries_max+1 次行程）。"""
        return max(0, self.params.scoop_retries_max - max(0, self.state.rounds_done - 1))


# ---- 语音总线 / 记录池 ----------------------------------------------------------


class ScriptedVoice:
    """语音总线 mock：队列注入意图（不经麦克风），播报记录列表。"""

    def __init__(self) -> None:
        self.queue: list[VoiceIntent] = []
        self.said: list[str] = []
        self.ctx: TickContext | None = None

    def bind(self, ctx: TickContext, _env, _mock) -> None:
        self.ctx = ctx

    def poll(self) -> VoiceIntent | None:
        return self.queue.pop(0) if self.queue else None

    def say(self, text: str) -> None:
        self.said.append(text)

    def inject(self, intent: IntentKind, slots: dict | None = None) -> VoiceIntent:
        vi = VoiceIntent(
            ts_ns=self.ctx.now_ns() if self.ctx else 0,
            intent=intent, slots=dict(slots or {}), confidence=0.95)
        self.queue.append(vi)
        return vi


class MemorySink:
    """进餐记录池 mock：内存保存会话与单口（生产为 cs_dashboard HTTP sink）。"""

    def __init__(self) -> None:
        self.sessions: list[dict] = []
        self.bites: list[dict] = []

    def start_session(self, user_id: str) -> str:
        sid = f"s-{len(self.sessions) + 1:03d}"
        self.sessions.append({"session_id": sid, "user_id": user_id, "ended": False})
        return sid

    def post_bite(self, record) -> None:
        self.bites.append(record.model_dump(mode="json"))

    def end_session(self) -> None:
        if self.sessions and not self.sessions[-1]["ended"]:
            self.sessions[-1]["ended"] = True


# ---- 回合脚本与驱动器 ------------------------------------------------------------

# 开发指令 §5.6 注入表（每回合同一脚本，30 回合全覆盖五类行为 + 相机角色断言）：
#   第 3 口 勺空重舀（首轮舀空，闭环重试命中）
#   第 7 口 送达中转头 2.5s（保持+播报后恢复）
#   第 9 口 闭嘴等待 6s（长反应延时）
#   第 12 口 送达中软件急停（中止本口；操作员复位+“继续”后续餐）
#   第 15 口 等待咬合时“吃饱了”（拒食撤回+会话结束）
SPEC_MEAL_SCRIPT: dict[int, dict] = {
    3: {"first_scoop_empty": True},
    7: {"turn_s": 2.5, "turn_delay_s": 0.0},
    9: {"reaction_s": 6.0},
    12: {"estop": True},
    15: {"done": True},
}
SPEC_MEAL_BITES = 15
# 期望结局表（状态转移表的 eval 具象化）
SPEC_MEAL_EXPECTED_OUTCOMES = {
    i: ("aborted" if i == 12 else "rejected" if i == 15 else "success")
    for i in range(1, SPEC_MEAL_BITES + 1)
}


class ScenarioDriver:
    """回合驱动器：按脚本在 tick 间注入操作员/场景事件（急停/复位/语音）。"""

    def __init__(self, state: ScriptState, env: SafetyEnvelope,
                 mock: MockArm, voice: ScriptedVoice) -> None:
        self.state = state
        self.env = env
        self.mock = mock
        self.voice = voice
        self.estop_done = False
        self.resume_done = False
        self.done_injected = False
        self.zone_done = False
        self.zone_moved_out = False
        self.zone_resume_done = False

    def on_tick(self, ctx: TickContext, tick_i: int) -> None:
        del tick_i
        b = ctx.bite
        cfg = self.state.cfg_of(b.idx) if b is not None else {}
        # 急停注入：进入送达且在途时（模拟空格键 latch 包络，与真机路径一致）
        if cfg.get("estop") and not self.estop_done and b is not None \
                and b.phase.value == 4 and b.delivery_entered and ctx.arm.busy():
            self.env.estop()
            ctx.trace.add("estop_injected", ts_ns=ctx.now_ns(), bite=b.idx)
            self.estop_done = True
            return
        # 急停善后：闸已响应（本口已记 aborted）→ 操作员复位 + “继续”
        if self.estop_done and not self.resume_done and ctx.estop_entered \
                and not ctx.pending_intents:
            self.env.reset()
            self.voice.inject(IntentKind.RESUME)
            ctx.trace.add("operator_reset_resume", ts_ns=ctx.now_ns())
            self.resume_done = True
            return
        # 禁入区演练：送达在途把 TCP 挪入面部球域（mock teleport 装配）
        if cfg.get("zone") and not self.zone_done and b is not None \
                and b.phase.value == 4 and b.delivery_entered and ctx.arm.busy():
            face = np.asarray(self.state.face_center, dtype=float)
            res = solve_with_restarts(
                _model_of(self.mock), (face + np.array([-0.02, 0.0, 0.0])).tolist(),
                np.eye(3), seed=self.mock.current_q(), pos_only=True)
            assert res is not None and res.converged, "zone 演练位姿 IK 失败"
            self.mock.teleport(np.clip(res.q, _model_of(self.mock).joint_lower,
                                       _model_of(self.mock).joint_upper))
            ctx.trace.add("zone_intrusion_injected", ts_ns=ctx.now_ns(), bite=b.idx)
            self.zone_done = True
            return
        # 禁入区善后：闸已响应 → 把 TCP 挪回家位（包络复位可行），再“继续”
        if self.zone_done and not self.zone_resume_done and ctx.zone_entered \
                and not ctx.pending_intents:
            if not self.zone_moved_out:
                self.mock.teleport(_home_q(self.mock, self.state.params))
                self.zone_moved_out = True
                return
            self.env.reset()
            if self.env.safety_state().clear_to_move:
                self.voice.inject(IntentKind.RESUME)
                ctx.trace.add("operator_reset_resume", ts_ns=ctx.now_ns())
                self.zone_resume_done = True
            return
        # 吃饱了：等待咬合阶段注入 done
        if cfg.get("done") and not self.done_injected and b is not None \
                and b.phase.value in (5, 6):
            self.voice.inject(IntentKind.DONE)
            ctx.trace.add("done_injected", ts_ns=ctx.now_ns(), bite=b.idx)
            self.done_injected = True


def _model_of(mock: MockArm):
    """MockArm 的运动学后端（solve_with_restarts 需要 backend 接口）。"""
    return mock.model._backend


def _home_q(mock: MockArm, params: OrchestraParams) -> np.ndarray:
    """家位关节角（IK 于 home_point_m；失败回退当前位形）。"""
    model = mock.model
    res = solve_with_restarts(model._backend, list(params.home_point_m), np.eye(3),
                              seed=mock.current_q(), pos_only=True)
    if res is None or not res.converged:
        return mock.current_q()
    return np.clip(res.q, model.joint_lower, model.joint_upper)


# ---- 回合工厂 --------------------------------------------------------------------


def make_mock_episode(
    *,
    episode: int = 1,
    script: dict[int, dict] | None = None,
    bites: int = SPEC_MEAL_BITES,
    params: OrchestraParams | None = None,
    model=None,
    validator: EnvelopeValidator | None = None,
    seed: int = 20260929,
    user_id: str = "user-mock",
    trace_path=None,
):
    """装配一整回合（mock 臂 + 包络 + 注入依赖 + 行为树 + 驱动器）。"""
    params = params if params is not None else OrchestraParams.load()
    model = model if model is not None else load_arm("auto")
    validator = validator if validator is not None else EnvelopeValidator()
    clock = VirtualClock()

    # 家位关节角（就位点 IK；每回合确定性）
    res = solve_with_restarts(model._backend, list(params.home_point_m), np.eye(3),
                              seed=np.zeros(model.n_joints), pos_only=True)
    if res is None or not res.converged:
        raise RuntimeError("家位 IK 无解（检查 home_point_m 配置）")
    q_home = np.clip(res.q, model.joint_lower, model.joint_upper)

    mock = MockArm(model, q_home=[float(v) for v in q_home],
                   validator=validator, clock=clock)
    env = SafetyEnvelope(mock, model=model, validator=validator, clock=clock)
    env.enable()

    rng = np.random.default_rng(seed + episode)
    state = ScriptState(script=script if script is not None else dict(SPEC_MEAL_SCRIPT),
                        params=params,
                        face_center=np.asarray(validator.config.face_center, dtype=float))
    deps = Deps(
        mouth=FakeMouthChannel(state, rng),
        scene=FakeSceneScanner(len(params.bowls_m())),
        spoon=FakeSpoonSource(state),
        voice=ScriptedVoice(),
        sink=MemorySink(),
        scoop=MockScoop(params, state, rng),
    )
    ctx = TickContext(env=env, clock=clock, params=params, deps=deps,
                      validator=validator, episode=episode, user_id=user_id,
                      trace_path=trace_path)
    ctx.max_bites = int(bites)
    deps.mouth.bind(ctx, env, mock)
    deps.scene.bind(ctx, env, mock)
    deps.spoon.bind(ctx, env, mock)
    deps.voice.bind(ctx, env, mock)
    runner = MealRunner(ctx)
    driver = ScenarioDriver(state, env, mock, deps.voice)
    return SimpleNamespace(ctx=ctx, runner=runner, driver=driver, env=env,
                           mock=mock, clock=clock, validator=validator,
                           model=model, deps=deps, params=params, state=state)
