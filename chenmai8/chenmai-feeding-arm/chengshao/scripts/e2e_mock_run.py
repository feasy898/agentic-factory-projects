"""端到端全链路 mock 验收（开发指令 §5.8 / §7，任务 T9）。

全链同进程：cs_voice（预录话语 -> 意图解析 -> 队列注入，不经麦克风）
→ cs_food.BowlSelector（场景基准码选碗，合成场景帧）→ 舀取（MockScoop）
→ cs_food.HeuristicSpoonClassifier（腕部合成勺帧 -> HSV 启发式勺检）
→ 腕部相机角色切换（camera_role 台账 + 曝光稳定窗 + FK×手眼审计）
→ 送达（SafetyEnvelope 限速/禁入区硬闸，包络送达停点）→ 等咬合（脚本用户）
→ 撤回 → cs_dashboard（真实 uvicorn 随机端口 + SQLite，HTTP 契约落库）。
cs_mouth 腕部契约另做一次真实推理冒烟（MediaPipe + IPD 估距 + cam_pose 换算）；
树内口部通道用脚本化用户（相机角色语义与生产通道 runtime.WristMouthChannel
同契约）——预录 face 视频资产尚未入库（D2 前补采），真感知链路由 §5.3 eval
覆盖，本脚本冒烟证明运行环境具备 cs_mouth v1.1 腕部路径。

注入事件（§5.8 三类 + 舀空重舀 + 语音点菜）：
  第 1 口  语音"我想吃芋泥" -> select -> 菜序映射选碗（此后清偏好，
           其余口走场景基准码选碗——两条选碗路径都实跑）；
  第 3 口  首轮舀空 -> 腕部检查不过 -> 闭环重舀命中；
  第 7 口  送达中转头 2.5s -> 保持+播报后恢复；
  第 9 口  闭嘴等待 6s（长反应延时）；
  第 12 口 送达中软件急停（latch SafetyEnvelope，与真机空格键同路径）
           -> 本口 aborted + 操作员复位 + "继续"恢复后续餐；
  第 30 口 等待咬合时语音"我吃饱了" -> 拒食撤回 + 会话结束。

断言通过线（任务 T9 + §5.8，全部满足才 exit 0）：
  1) 全流程完成：30 口闭环、无超时、无意外失败、会话收尾；
  2) 看板口数一致：GET /api/session/current 与行为树记录逐口一致（30/30）；
  3) 软急停可中断：latch 后 <=0.1 仿真秒内树响应（停+播报+本口 aborted），
     复位+resume 后续餐正常；
  4) 无禁入区穿越：逐 tick TCP 采样与段级检查间隙全部 >0、
     包络禁入区闩锁 0 次、包络拒绝 0 条；
  5) 送达停点数值余量 >0：delivery_margin() >= 5mm，且送达停点实测在
     面部球面之外（TCP-口部距离 > 面部球半径）。
另断言（§5.6/§7 契约）：camera_role 每进入送达的口恰 2 次切换、scene->wrist
后先等曝光稳定窗再采信口部帧、单口仿真时延中位数 <=20s。

用法（cwd 任意；报告/trace 缺省落包根 reports/）::

    python scripts/e2e_mock_run.py                       # 自验收命令
    python scripts/e2e_mock_run.py --report reports/e2e_mock.json
    python scripts/e2e_mock_run.py --profile rerun       # 关节流+角色事件推 Rerun

报告 JSON 遵循开发指令 §10.2：{module, date, cmd, metrics, thresholds, pass}。
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import tempfile
import threading
import time
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np

_SCRIPT_DIR = Path(__file__).resolve().parent          # .../chengshao/scripts
PKG_ROOT = _SCRIPT_DIR.parent                          # .../chengshao
_REPO_ROOT = PKG_ROOT.parent                           # 仓库根
if str(_REPO_ROOT) not in sys.path:                    # 任意 cwd 可跑（chengshao.* 形态）
    sys.path.insert(0, str(_REPO_ROOT))

from chengshao.cs_dashboard.app import create_app      # noqa: E402
from chengshao.cs_food.bowls import BowlSelector       # noqa: E402
from chengshao.cs_food.config import DEFAULT_BOWL_CONFIG_PATH  # noqa: E402
from chengshao.cs_food.spoons import HeuristicSpoonClassifier  # noqa: E402
from chengshao.cs_mouth.estimator import MouthEstimator  # noqa: E402
from chengshao.cs_mouth.prior import MouthPrior        # noqa: E402
from chengshao.cs_mouth.synth import draw_cartoon_face  # noqa: E402
from chengshao.cs_orchestra.core import (              # noqa: E402
    NOMINAL_T_FLANGE_CAM,
    OrchestraParams,
)
from chengshao.cs_orchestra.mock import (              # noqa: E402
    ScenarioDriver,
    ScriptState,
    make_mock_episode,
)
from chengshao.cs_orchestra.runtime import HttpDashboardSink  # noqa: E402
from chengshao.cs_schema import IntentKind             # noqa: E402
from chengshao.cs_schema.constants import (            # noqa: E402
    DEFAULT_DISH_REGISTRY,
)
from chengshao.cs_voice.intent import IntentParser     # noqa: E402
from chengshao.cs_voice.link import VoiceLink          # noqa: E402

import cv2  # noqa: E402
import httpx  # noqa: E402
import uvicorn  # noqa: E402

DEFAULT_REPORT = PKG_ROOT / "reports" / "e2e_mock.json"
DEFAULT_TRACE = PKG_ROOT / "reports" / "e2e_mock_trace.jsonl"

# ---- 30 口 e2e 注入脚本（§5.8 事件 + 舀空/点菜/长等待） -------------------------
E2E_BITES = 30
E2E_MEAL_SCRIPT: dict[int, dict] = {
    3: {"first_scoop_empty": True},
    7: {"turn_s": 2.5, "turn_delay_s": 0.0},
    9: {"reaction_s": 6.0},
    12: {"estop": True},
    30: {"done": True},
}
E2E_EXPECTED_OUTCOMES = {
    i: ("aborted" if i == 12 else "rejected" if i == 30 else "success")
    for i in range(1, E2E_BITES + 1)
}

# 预录话语（assets/voice_samples/labels.json 的实录转写；ASR 链路已由 §5.4
# eval 验收，本脚本按 §7.4 "不经麦克风"注入解析后的意图）
UTTERANCE_SELECT = ("我想吃芋泥", "select_1.wav")
UTTERANCE_DONE = ("我吃饱了", "done_1.wav")

THRESHOLDS: dict = {
    "bites_expected": E2E_BITES,
    "median_bite_sim_s_max": 20.0,
    "estop_response_sim_s_max": 0.10,
    "zone_violation_latches_max": 0,
    "envelope_rejections_max": 0,
    "min_point_clearance_m_min": 0.0,   # 严格 > 0
    "min_segment_clearance_m_min": 0.0,  # 严格 > 0
    "delivery_margin_min_m": 0.005,     # 与 cs_sim 送达余量断言一致
    "camera_switches_per_delivered_bite": 2,
    "exposure_settle_min_s": 0.5,
    "unexpected_failures_max": 0,
}


# ---- 语音总线（cs_voice 冻结接口 + 脚本话语注入） ------------------------------


class _QuietSpeaker:
    """静音播报器：记录文本不发声（缺省）；--tts 时换 cs_voice.Speaker 真发声。"""

    def __init__(self) -> None:
        self.texts: list[str] = []

    def say(self, text: str, timeout_s: float = 15.0) -> bool:
        self.texts.append(text)
        return True

    def shutdown(self) -> None:
        pass


class E2eVoiceBus:
    """行为树 Deps.voice 协议适配：真实 cs_voice.VoiceLink（注入模式）。

    - poll()/say() 透传 VoiceLink 冻结接口（§3.2）；
    - inject_utterance(text, wav)：预录话语 -> IntentParser（生产解析器）
      -> VoiceIntent -> VoiceLink 队列（ts 用仿真时钟，trace 时间轴一致）；
    - inject(kind, slots)：直接注入一条意图（操作员"继续"等非语音动作），
      兼容 ScenarioDriver 的调用面。
    """

    def __init__(self, link: VoiceLink | None = None, tts: bool = False) -> None:
        self.parser = IntentParser()
        speaker = None
        if not tts:
            speaker = _QuietSpeaker()
        self.link = link if link is not None else VoiceLink(
            parser=self.parser, speaker=speaker)
        self.ctx = None
        self.utterances: list[dict] = []
        self.injections: list[dict] = []

    # -- Deps.voice 协议 --------------------------------------------------------
    def bind(self, ctx, _env, _mock) -> None:
        self.ctx = ctx

    def poll(self):
        return self.link.poll()

    def say(self, text: str) -> None:
        self.link.say(text)

    # -- 注入入口 ---------------------------------------------------------------
    def _now_ns(self) -> int:
        return int(self.ctx.now_ns()) if self.ctx is not None else time.time_ns()

    def inject_utterance(self, text: str, wav: str | None = None):
        """预录话语 -> 意图解析 -> 队列；返回 (VoiceIntent, 命中意图字面量)。"""
        vi = self.parser.parse(text, ts_ns=self._now_ns())
        self.link.inject_intent(vi)
        self.utterances.append({
            "text": text, "wav": wav, "intent": str(vi.intent),
            "slots": dict(vi.slots or {}), "confidence": float(vi.confidence),
        })
        return vi

    def inject(self, kind, slots: dict | None = None):
        """直接注入一条契约意图（操作员动作；不经解析器）。"""
        vi = IntentKind(kind) if not isinstance(kind, IntentKind) else kind
        from chengshao.cs_schema import VoiceIntent

        payload = VoiceIntent(ts_ns=self._now_ns(), intent=vi,
                              slots=dict(slots or {}), confidence=1.0)
        self.link.inject_intent(payload)
        self.injections.append({"intent": str(vi), "slots": dict(slots or {})})
        return payload


# ---- 场景选碗（cs_food.BowlSelector + 合成场景帧） ------------------------------


class ArUcoSceneScanner:
    """选碗生产链路：按当前口序渲染单码合成场景帧 -> 真实基准码检测选碗。

    口序 -> 碗序轮换（(口序-1)%碗数），场景帧只画该碗的登记码（最大可见码
    即选中之，检测确定性可复现）。cam_ref/码表/最小边长全部取 config。
    """

    def __init__(self, config_path=DEFAULT_BOWL_CONFIG_PATH) -> None:
        self.selector = BowlSelector(config_path=config_path)
        self.ctx = None
        self.n_bowls = len(self.selector._marker_to_bowl)
        # 碗序 -> 码 id（config/bowl_markers.json 的 marker_to_bowl 反查）
        self.bowl_to_marker = {int(b): int(m)
                               for m, b in self.selector._marker_to_bowl.items()}
        self.render_ms_total = 0.0
        self.detect_ms_total = 0.0
        self.calls = 0

    def bind(self, ctx, _env, _mock) -> None:
        self.ctx = ctx

    def _scene_frame(self, bowl_index: int) -> np.ndarray:
        t0 = time.perf_counter()
        side = 160
        img = np.full((480, 640, 3), (58, 62, 66), np.uint8)
        marker = cv2.aruco.generateImageMarker(
            self.selector._dictionary, self.bowl_to_marker[int(bowl_index)], side)
        img[160:160 + side, 240:240 + side] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
        self.render_ms_total += (time.perf_counter() - t0) * 1000.0
        return img

    def select_bowl(self) -> int | None:
        ctx = self.ctx
        if ctx is None or ctx.bite is None:
            return None
        want = (ctx.bite.idx - 1) % self.n_bowls
        frame = self._scene_frame(want)
        t0 = time.perf_counter()
        picked = self.selector.select(frame)
        self.detect_ms_total += (time.perf_counter() - t0) * 1000.0
        self.calls += 1
        return picked


# ---- 勺上检查（cs_food.HeuristicSpoonClassifier + 合成腕部帧） ------------------


class SyntheticWristSpoonSource:
    """勺检生产链路：世界状态渲染腕部勺区帧 -> 真实 HSV 启发式分类器判决。

    世界事实（ScriptState.food_on_spoon）由 MockScoop 的行程结果驱动；本类
    只负责"把事实画进帧里"（有食物=食物色大椭圆占 ~1/3 视场；空勺=中性灰
    背景，HSV 掩码占比 0），判决完全由 cs_food 分类器给出——检查节点拿到的
    SpoonCheck 与真机同构（has_food/score 由像素决定，而非世界直读）。
    """

    def __init__(self, state: ScriptState) -> None:
        self.state = state
        self.classifier = HeuristicSpoonClassifier(
            ts_ns_source=self._now_ns)
        self.ctx = None
        self.stats = {"food_frames": 0, "empty_frames": 0,
                      "verdict_food": 0, "verdict_empty": 0,
                      "false_positive": 0, "false_negative": 0}

    def bind(self, ctx, _env, _mock) -> None:
        self.ctx = ctx

    def _now_ns(self) -> int:
        return int(self.ctx.now_ns()) if self.ctx is not None else time.time_ns()

    def _wrist_frame(self, has_food: bool) -> np.ndarray:
        crop = np.full((90, 120, 3), (126, 126, 126), np.uint8)  # 中性灰（勺背）
        cv2.ellipse(crop, (60, 62), (52, 10), 0, 0, 360, (150, 150, 152), -1)
        if has_food:  # 食物色：HSV h≈60 s≈200 v≈200（config 区间 2 内）
            cv2.ellipse(crop, (60, 45), (40, 26), 0, 0, 360, (0, 200, 200), -1)
        return crop

    def check(self):
        has_food = bool(self.state.food_on_spoon) and not self.state.bitten
        check = self.classifier.from_bgr(self._wrist_frame(has_food))
        st = self.stats
        if has_food:
            st["food_frames"] += 1
        else:
            st["empty_frames"] += 1
        if check.has_food:
            st["verdict_food"] += 1
            st["false_positive"] += 0 if has_food else 1
        else:
            st["verdict_empty"] += 1
            st["false_negative"] += 1 if has_food else 0
        return check


# ---- e2e 回合驱动器（话语调度 + 逐 tick 安全采样） ------------------------------


class E2eDriver(ScenarioDriver):
    """在 §5.6 注入驱动器之上叠加：脚本话语注入、偏好清场、TCP 安全采样。"""

    def __init__(self, state, env, mock, voice: E2eVoiceBus,
                 validator, sample_every: int = 1) -> None:
        super().__init__(state, env, mock, voice)
        self.voice_bus = voice
        self.validator = validator
        self.sample_every = int(sample_every)
        self.select_injected = False
        self.preference_cleared = False
        self.done_utterance_injected = False
        self.tcp_samples: list[tuple[int, np.ndarray]] = []  # (sim_ns, tcp)
        self.rerun_hook = None  # 可选：--profile rerun 时外部注入

    # -- 话语调度（先于 §5.6 注入逻辑执行） --------------------------------------
    def on_tick(self, ctx, tick_i: int) -> None:
        # 1) 开餐语音点菜（一次）：真实解析链 select -> 菜序->碗序映射
        if not self.select_injected:
            self.voice_bus.inject_utterance(*UTTERANCE_SELECT)
            ctx.trace.add("utterance_injected", ts_ns=ctx.now_ns(),
                          text=UTTERANCE_SELECT[0], wav=UTTERANCE_SELECT[1])
            self.select_injected = True
        # 2) 语音点菜偏好：等到"带菜名的选碗事件"落地（菜序->碗序映射真实
        #    生效一次）随即清偏好——其余口走场景基准码选碗（两条路径都实跑）
        if not self.preference_cleared and any(
                e["kind"] == "bowl_selected" and e.get("dish")
                for e in ctx.trace.events):
            ctx.requested_dish = None
            self.preference_cleared = True
        # 3) 末口"吃饱了"走语音话语（done 意图来自真实解析器而非直注）
        b = ctx.bite
        cfg = self.state.cfg_of(b.idx) if b is not None else {}
        if cfg.get("done") and not self.done_utterance_injected \
                and b is not None and b.phase.value in (5, 6):
            self.voice_bus.inject_utterance(*UTTERANCE_DONE)
            ctx.trace.add("utterance_injected", ts_ns=ctx.now_ns(),
                          text=UTTERANCE_DONE[0], wav=UTTERANCE_DONE[1])
            self.done_utterance_injected = True
            self.done_injected = True  # 父类直注路径让位（话语路径已覆盖）
        super().on_tick(ctx, tick_i)
        # 4) TCP 安全采样（段级禁入区审计的数据面）
        if tick_i % self.sample_every == 0:
            state = ctx.arm_state()
            self.tcp_samples.append(
                (int(ctx.now_ns()),
                 np.asarray(state.ee_pos, dtype=float).copy()))
        if self.rerun_hook is not None:
            self.rerun_hook(ctx, tick_i)


# ---- 看板服务器（随机端口 uvicorn + 临时 SQLite） --------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class DashboardServer:
    """§5.7 冻结 HTTP 契约的真实服务（独立线程、独立事件循环、临时库）。"""

    def __init__(self, db_dir: Path) -> None:
        self.port = _free_port()
        self.db_path = db_dir / "care.db"
        self.app = create_app(db_path=self.db_path)
        config = uvicorn.Config(self.app, host="127.0.0.1", port=self.port,
                                log_level="warning", access_log=False)
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "DashboardServer":
        self.thread.start()
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{self.base}/api/health", timeout=1.0).status_code == 200:
                    return self
            except httpx.HTTPError:
                time.sleep(0.1)
        raise RuntimeError("看板 uvicorn 20s 内未就绪")

    def __exit__(self, *exc: object) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10.0)
        store = getattr(self.app.state, "store", None)
        if store is not None:  # 释放 SQLite 连接（Windows 下临时目录才能删除）
            try:
                store.close()
            except Exception:  # noqa: BLE001 —— 清理失败不掩盖主流程结果
                pass


# ---- cs_mouth 腕部契约真实推理冒烟 ------------------------------------------------


def mouth_contract_smoke(stop_point: np.ndarray) -> dict:
    """真实 MouthEstimator（MediaPipe + IPD 估距 + FK×手眼）单帧冒烟。

    名义腕部位姿（送达停点）+ 名义手眼外参 -> 合成腕部视角帧 -> MouthPose。
    断言 valid 且 source=="wrist"（v1.1 契约路径）；估距绝对精度属 §5.3
    wrist-view eval 口径，此处只记录。
    """
    try:
        est = MouthEstimator(backend="mono", prior=MouthPrior.load())
        t_flange = np.eye(4)
        t_flange[:3, 3] = np.asarray(stop_point, dtype=float)
        t_hand = np.asarray(NOMINAL_T_FLANGE_CAM, dtype=float)
        t0 = time.perf_counter()
        pose = est.from_bgr(draw_cartoon_face(640, 480, mouth_open=0.5),
                            cam_pose=(t_flange, t_hand))
        wall_ms = (time.perf_counter() - t0) * 1000.0
        return {
            "valid": bool(pose.valid),
            "source": str(pose.source),
            "jaw_open": round(float(pose.jaw_open), 4),
            "pos_base_m": [round(float(pose.x), 4), round(float(pose.y), 4),
                           round(float(pose.z), 4)],
            "wall_ms_first": round(wall_ms, 1),
        }
    except Exception as exc:  # noqa: BLE001 —— 模型缺失等环境问题如实记录
        return {"valid": False, "source": None, "error": f"{type(exc).__name__}: {exc}"}


# ---- 阶段耗时分解（trace 事件对差分） ----------------------------------------------

_STAGE_PAIRS = (
    # (阶段名, 起事件, 止事件——取该口最后一次出现)
    ("scoop_check_s", "bite_open", "spoon_check"),
    ("deliver_s", "delivery_entry", "delivered"),
    ("wait_bite_s", "delivered", "jaw_closed"),
    ("retract_record_s", "retracted", "bite_recorded"),
)


def stage_breakdown(trace_events: list[dict]) -> dict:
    """按口聚合阶段耗时（仿真秒）；缺事件的口不计入该阶段。"""
    by_bite: dict[int, dict[str, int]] = {}
    for ev in trace_events:
        kind, bite = ev.get("kind"), ev.get("bite")
        if bite is None:
            continue
        by_bite.setdefault(int(bite), {})[kind] = int(ev["ts_ns"])
    rows: dict[str, list[float]] = {name: [] for name, _, _ in _STAGE_PAIRS}
    for _bite, kinds in by_bite.items():
        for name, k_start, k_end in _STAGE_PAIRS:
            if k_start in kinds and k_end in kinds and kinds[k_end] > kinds[k_start]:
                rows[name].append((kinds[k_end] - kinds[k_start]) / 1e9)
    med = {name: (round(float(np.median(v)), 2) if v else None)
           for name, v in rows.items()}
    return {"median_s": med, "n_per_stage": {k: len(v) for k, v in rows.items()}}


# ---- 主流程 ------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="python scripts/e2e_mock_run.py",
        description="端到端全链路 mock 验收（§5.8/§7，任务 T9；全 Mock 零硬件）")
    ap.add_argument("--report", default=str(DEFAULT_REPORT), help="报告 JSON 路径")
    ap.add_argument("--trace", default=str(DEFAULT_TRACE), help="trace JSONL 路径")
    ap.add_argument("--bites", type=int, default=E2E_BITES, help="额定口数（默认 30）")
    ap.add_argument("--seed", type=int, default=20260929, help="随机种子")
    ap.add_argument("--tts", action="store_true",
                    help="播报走真实 TTS 扬声（缺省静音记录，不阻塞验收）")
    ap.add_argument("--profile", choices=["none", "rerun"], default="none",
                    help="rerun：关节流/角色事件镜像到 .rrd（演示与调试，§7.7）")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report_path = Path(args.report)
    trace_path = Path(args.trace)

    params = OrchestraParams.load()
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text("", encoding="utf-8")  # 本轮全量重写

    # ---- 链路预置：语音（cs_voice）+ 真实推理冒烟（cs_mouth） -------------------
    with tempfile.TemporaryDirectory(prefix="e2e_care_") as db_dir:
        with DashboardServer(Path(db_dir)) as dash:
            sink = HttpDashboardSink(dash.base)
            voice_bus = E2eVoiceBus(tts=args.tts)

            # ---- 装配回合（mock 臂 + 包络 + 行为树 + 生产链路依赖） --------------
            ns = make_mock_episode(
                episode=1, script=dict(E2E_MEAL_SCRIPT), bites=args.bites,
                params=params, seed=args.seed, trace_path=trace_path)
            ctx = ns.ctx
            validator = ns.validator
            # 生产链路依赖换装：看板 HTTP 池 + 语音总线 + 基准码选碗 + 启发式勺检
            ctx.deps.sink = sink
            ctx.deps.voice = voice_bus
            voice_bus.bind(ctx, ns.env, ns.mock)
            scanner = ArUcoSceneScanner()
            ctx.deps.scene = scanner
            scanner.bind(ctx, ns.env, ns.mock)
            spoon_src = SyntheticWristSpoonSource(ns.state)
            ctx.deps.spoon = spoon_src
            spoon_src.bind(ctx, ns.env, ns.mock)
            driver = E2eDriver(ns.state, ns.env, ns.mock, voice_bus,
                               validator=validator)

            # ---- cs_mouth 腕部契约冒烟（送达停点位姿） --------------------------
            smoke = mouth_contract_smoke(validator.delivery_stop_point())

            # ---- 可选：Rerun 镜像（§7.7，演示/调试，不参与判定） ----------------
            rerun_note = None
            if args.profile == "rerun":
                rerun_note = _wire_rerun(driver)

            # ---- 跑一整餐（50Hz tick，虚拟时钟） --------------------------------
            t0 = time.perf_counter()
            summary = ns.runner.run(driver)
            wall_s = time.perf_counter() - t0

            # ---- 看板侧证：GET 快照比对（§7.6） ---------------------------------
            http_current = httpx.get(f"{dash.base}/api/session/current",
                                     timeout=5.0)
            dash_session = http_current.json() if http_current.status_code == 200 else None
            dash_summary = httpx.get(f"{dash.base}/api/summary", timeout=5.0).json()

    bites = ctx.bites_done
    tree_outcomes = [str(r.outcome) for r in bites]
    http_bites = (dash_session or {}).get("bites", [])
    http_outcomes = [b["outcome"] for b in http_bites]

    # ---- 安全审计：逐点 + 段级禁入区间隙（采样面 = 每 tick TCP） ----------------
    tcp = [p for _, p in driver.tcp_samples]
    min_point_clear = min((validator.min_zone_clearance(p) for p in tcp),
                          default=None)
    min_seg_clear = None
    max_tcp_speed = 0.0
    tick_s = params.tick_s
    for a, b in zip(tcp, tcp[1:]):
        seg = validator._zone_segment_violation(np.asarray(a), np.asarray(b))
        min_seg_clear = seg[1] if min_seg_clear is None else min(min_seg_clear, seg[1])
        max_tcp_speed = max(max_tcp_speed, float(np.linalg.norm(np.asarray(b) - np.asarray(a))) / tick_s)
    face_center = np.asarray(validator.config.face_center, dtype=float)
    tcp_face_dist = [float(np.linalg.norm(p - face_center)) for p in tcp]
    min_tcp_face_dist = min(tcp_face_dist) if tcp_face_dist else None

    # ---- 急停事件审计 ------------------------------------------------------------
    estop_inj = [e for e in ctx.trace.events if e["kind"] == "estop_injected"]
    estop_det = [e for e in ctx.trace.events if e["kind"] == "estop_detected"]
    estop_response_s = None
    if estop_inj and estop_det:
        estop_response_s = (estop_det[0]["ts_ns"] - estop_inj[0]["ts_ns"]) / 1e9

    # ---- 相机角色台账 + 曝光稳定窗 ------------------------------------------------
    switches_ok = all(ctx.ledger.per_bite_report(i, delivered=True)["ok"]
                      for i in range(1, len(bites) + 1))
    settle_min = None
    for sw in ctx.ledger.switches:
        if sw["reason"] != "delivery_entry" or sw["bite"] is None:
            continue
        after = [s[0] for s in ctx.mouth_samples
                 if s[1] == "wrist_mouth" and s[2] and s[0] >= sw["ts_ns"]
                 and sw["bite"] is not None]
        if after:
            gap = (min(after) - sw["ts_ns"]) / 1e9
            settle_min = gap if settle_min is None else min(settle_min, gap)

    # ---- 选碗序列（trace bowl_selected） ------------------------------------------
    bowl_rows = [e for e in ctx.trace.events if e["kind"] == "bowl_selected"]
    bowls_selected = [e.get("bowl") for e in bowl_rows]
    n_bowls = len(params.bowls_m())
    # 口1：场景基准码轮换 (1-1)%3=0；口2：语音点菜映射（芋泥→菜序0→碗0）；
    # 口3+：偏好已清，回到场景基准码轮换 (k-1)%3
    expect_bowls = [0 if k <= 2 else (k - 1) % n_bowls
                    for k in range(1, len(bites) + 1)]

    # ---- 阶段耗时 / 单口时延 --------------------------------------------------------
    stages = stage_breakdown(ctx.trace.events)
    durations = [(r.ts_end_ns - r.ts_start_ns) / 1e9 for r in bites]
    median_bite = float(np.median(durations)) if durations else float("inf")

    margin_rep = validator.delivery_margin()
    env_stats = ns.env.stats

    # ---- 断言（任务 T9 通过线 + §5.6/§5.8 契约） -----------------------------------
    delivered_rows = [e for e in ctx.trace.events if e["kind"] == "delivered"]
    stop_errs = [float(e.get("err_m", 1.0)) for e in delivered_rows]
    face_radius = validator.face_radius
    estop_bite_rec = next((r for r in bites if r.bite_id == 11), None)
    after_estop = [r for r in bites if r.bite_id >= 12]
    announces = ctx.announce_counts
    checks: dict[str, bool] = {
        # 1) 全流程完成
        "full_flow_completed": (
            not summary["timeout"] and ctx.meal_finished
            and len(bites) == args.bites
            and not ctx.unexpected_failures
            and bool(ctx.session is not None and ctx.session.ended_ns is not None)),
        # 2) 看板口数一致（HTTP 契约回读比对）
        "dashboard_bite_count_consistent": (
            len(http_bites) == len(bites)
            and http_outcomes == tree_outcomes
            and dash_summary.get("bite_count") == len(bites)
            and (dash_session or {}).get("ended_ns") is not None
            and [b["bite_id"] for b in http_bites] == list(range(len(bites)))),
        # 3) 软急停可中断且恢复
        "soft_estop_interrupts": (
            bool(estop_inj and estop_det)
            and estop_response_s is not None
            and estop_response_s <= THRESHOLDS["estop_response_sim_s_max"]
            and estop_bite_rec is not None
            and str(estop_bite_rec.outcome) == "aborted"
            and int(env_stats.get("estop_count", 0)) == 1
            and announces.get("estop", 0) == 1
            and any(e["kind"] == "operator_reset_resume" for e in ctx.trace.events)
            and len(after_estop) == args.bites - 12),
        # 4) 无禁入区穿越
        "no_forbidden_zone_crossing": (
            int(env_stats.get("zone_latches", 0)) == THRESHOLDS["zone_violation_latches_max"]
            and int(env_stats.get("rejected", 0)) <= THRESHOLDS["envelope_rejections_max"]
            and min_point_clear is not None and min_point_clear > THRESHOLDS["min_point_clearance_m_min"]
            and min_seg_clear is not None and min_seg_clear > THRESHOLDS["min_segment_clearance_m_min"]),
        # 5) 送达停点数值余量 >0（标称余量 + 实测停点球外）
        "delivery_stop_margin_positive": (
            float(margin_rep["margin_m"]) >= THRESHOLDS["delivery_margin_min_m"]
            and bool(margin_rep["pass"])
            and min_tcp_face_dist is not None
            and min_tcp_face_dist > face_radius
            and all(e <= params.arrive_tolerance_m for e in stop_errs)),
        # 契约增补：camera_role 台账 / 曝光稳定窗 / 单口中位时延
        "camera_role_contract": (
            switches_ok and str(ctx.camera_role) == "scene"
            and len(ctx.ledger.switches) == 2 * len(bites)),
        "exposure_settle_before_first_frame": (
            settle_min is not None
            and settle_min >= THRESHOLDS["exposure_settle_min_s"] - 0.05),
        "median_bite_sim_s": median_bite <= THRESHOLDS["median_bite_sim_s_max"],
        # 链路证据：语音 / 选碗 / 勺检 / cs_mouth 冒烟
        "voice_leg_parsed": (
            len(voice_bus.utterances) == 2
            and voice_bus.utterances[0]["intent"] == "select"
            and voice_bus.utterances[0]["slots"].get("dish") == "芋泥"
            and voice_bus.utterances[1]["intent"] == "done"
            and announces.get("done", 0) == 1
            and announces.get("turn", 0) == 1),
        "bowl_selection_leg": (
            bowls_selected == expect_bowls
            and scanner.calls >= len(bites) - 2),
        "spoon_classifier_leg": (
            spoon_src.stats["verdict_food"] >= len(bites)
            and spoon_src.stats["verdict_empty"] >= 1
            and spoon_src.stats["false_positive"] == 0
            and spoon_src.stats["false_negative"] == 0),
        "cs_mouth_wrist_smoke": (
            bool(smoke.get("valid")) and smoke.get("source") == "wrist"),
    }

    failures = [k for k, v in checks.items() if not v]
    passed = not failures
    outcomes_counter = Counter(tree_outcomes)

    per_bite_rows = []
    for r in bites:
        idx = r.bite_id + 1
        sw = ctx.ledger.for_bite(idx)
        per_bite_rows.append({
            "bite": idx,
            "outcome": str(r.outcome),
            "sim_s": round((r.ts_end_ns - r.ts_start_ns) / 1e9, 2),
            "switches": len(sw),
            "switch_reasons": [s["reason"] for s in sw],
            "bowl": None,
        })
    for row in per_bite_rows:
        ev = next((e for e in bowl_rows if e.get("bite") == row["bite"]), None)
        row["bowl"] = None if ev is None else ev.get("bowl")

    report = {
        "module": "e2e_mock",
        "date": date.today().isoformat(),
        "cmd": "python scripts/e2e_mock_run.py " + " ".join(
            f"{a}={v}" for a, v in vars(args).items() if a != "report"
        ) + f" --report {report_path}",
        "mode": "mock（全 Mock 零硬件：MockArm+SafetyEnvelope+脚本用户+真实看板 HTTP）",
        "metrics": {
            "bites": len(bites),
            "outcomes": dict(outcomes_counter),
            "expected_outcomes_match": all(
                i <= len(bites) and str(rec.outcome) == E2E_EXPECTED_OUTCOMES[i]
                for i, rec in enumerate(bites, start=1)),
            "meal_sim_s": summary["sim_s"],
            "wall_s": round(wall_s, 1),
            "ticks": summary["ticks"],
            "median_bite_sim_s": round(median_bite, 2),
            "max_bite_sim_s": round(max(durations), 2) if durations else None,
            "stages": stages,
            "per_bite": per_bite_rows,
            "dashboard": {
                "base_url": dash.base,
                "http_status_current": http_current.status_code,
                "session_id": (dash_session or {}).get("session_id"),
                "bite_count_http": len(http_bites),
                "bite_count_summary": dash_summary.get("bite_count"),
                "outcomes_http": dict(Counter(http_outcomes)),
                "outcomes_tree": dict(outcomes_counter),
                "session_ended": (dash_session or {}).get("ended_ns") is not None,
                "total_grams": dash_summary.get("total_grams"),
            },
            "safety": {
                "zone_latches": int(env_stats.get("zone_latches", 0)),
                "envelope_rejected": int(env_stats.get("rejected", 0)),
                "envelope_written": int(env_stats.get("written", 0)),
                "estop_count": int(env_stats.get("estop_count", 0)),
                "estop_response_sim_s": (None if estop_response_s is None
                                         else round(estop_response_s, 4)),
                "min_point_clearance_m": (None if min_point_clear is None
                                          else round(min_point_clear, 4)),
                "min_segment_clearance_m": (None if min_seg_clear is None
                                            else round(min_seg_clear, 4)),
                "min_tcp_face_dist_m": (None if min_tcp_face_dist is None
                                        else round(min_tcp_face_dist, 4)),
                "face_radius_m": face_radius,
                "max_tcp_speed_mps": round(max_tcp_speed, 3),
                "tcp_samples": len(tcp),
                "unexpected_failures": list(ctx.unexpected_failures),
            },
            "delivery_margin": margin_rep,
            "camera_role": {
                "switches_total": len(ctx.ledger.switches),
                "switches_per_delivered_bite": 2,
                "final_role": str(ctx.camera_role),
                "settle_gap_min_s": (None if settle_min is None
                                     else round(settle_min, 3)),
            },
            "voice": {
                "utterances": voice_bus.utterances,
                "operator_injections": voice_bus.injections,
                "announces": dict(announces),
                "tts": ("real Speaker（--tts）" if args.tts else "quiet（静音记录）"),
            },
            "bowl_selection": {
                "selected": bowls_selected,
                "expected": expect_bowls,
                "aruco_calls": scanner.calls,
                "render_ms": round(scanner.render_ms_total, 1),
                "detect_ms": round(scanner.detect_ms_total, 1),
            },
            "spoon_classifier": spoon_src.stats,
            "cs_mouth_smoke": smoke,
            "injections": {str(k): v for k, v in E2E_MEAL_SCRIPT.items()},
        },
        "thresholds": THRESHOLDS,
        "trace": str(trace_path),
        "pass": bool(passed),
        "failures": failures,
    }
    if rerun_note:
        report["metrics"]["rerun"] = rerun_note
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"e2e_mock: bites={len(bites)} outcomes={dict(outcomes_counter)} "
          f"median_bite_sim_s={report['metrics']['median_bite_sim_s']} "
          f"dashboard={dash_summary.get('bite_count')}口 "
          f"wall_s={report['metrics']['wall_s']}")
    print(f"report -> {report_path}")
    print(f"trace  -> {trace_path}")
    if failures:
        for line in failures:
            print("FAIL", line, file=sys.stderr)
        return 1
    return 0


# ---- Rerun 镜像（可选路径） ---------------------------------------------------------


def _wire_rerun(driver: E2eDriver) -> dict:
    """把关节流/相机角色/口事件镜像到 .rrd 文件（§7.7；不可用则如实降级）。"""
    try:
        import rerun as rr
    except Exception as exc:  # noqa: BLE001
        return {"enabled": False, "note": f"rerun-sdk 不可用：{exc}"}
    out = PKG_ROOT / "reports" / "e2e_mock.rrd"
    try:
        rr.init("chengshao-e2e-mock")
        rr.save(str(out))
        state = {"last_role": None}

        def hook(ctx, tick_i: int) -> None:
            if tick_i % 5:  # 10Hz 足够回放
                return
            st = ctx.arm_state()
            t = ctx.now_ns() / 1e9
            rr.log("arm/joints", rr.Scalars([float(v) for v in st.joint_pos]))
            rr.log("arm/tcp_x", rr.Scalars(float(st.ee_pos[0])))
            rr.log("arm/tcp_y", rr.Scalars(float(st.ee_pos[1])))
            rr.log("arm/tcp_z", rr.Scalars(float(st.ee_pos[2])))
            role = str(ctx.camera_role)
            if role != state["last_role"]:
                rr.log("camera/role", rr.TextLog(role))
                state["last_role"] = role

        driver.rerun_hook = hook
        return {"enabled": True, "out": str(out), "note": "演示后用 `rerun <file>` 打开"}
    except Exception as exc:  # noqa: BLE001
        return {"enabled": False, "note": f"rerun 初始化失败：{exc}"}


if __name__ == "__main__":
    raise SystemExit(main())
