"""生产接线：编排依赖的各模块契约消费实现（T9 e2e / 真机使用）。

全部为薄封装：编排树经 :class:`cs_orchestra.core.Deps` 的鸭子协议交互，
本模块把各模块冻结契约接到协议上——

- :class:`WristMouthChannel`  消费 cs_mouth.MouthEstimator（v1.1 契约：
  ``from_bgr(img, cam_pose=(T_base_flange, T_flange_cam))`` 出基座系
  source="wrist" 口部位姿；scene 角色或曝光稳定窗内不采帧）；
- :class:`SceneBowlScanner`   消费 cs_food.BowlSelector（场景相机基准码）；
- :class:`WristSpoonSource`   消费 cs_food.SpoonClassifier 协议（腕部帧裁剪）；
- :class:`ScriptedScoop`      脚本参数化舀取（与 MockScoop 同交互，无抖动；
  学习型策略延后接入时对齐同一协议，不重构树）；
- :class:`VoiceBusLink`       消费 cs_voice.VoiceLink 冻结接口（start/poll/say）；
- :class:`HttpDashboardSink`  消费 cs_dashboard HTTP 契约（§3.2）。

相机帧源一律经 ``frame_provider`` 注入（相机采集/预录流由上层接线），
本模块不直接开设备——与"全 Mock 零硬件"边界一致。
"""

from __future__ import annotations

import numpy as np

from .core import load_t_flange_cam

try:  # 仓库根运行与包根运行双形态
    from chengshao.cs_schema import CameraRole, MouthPose, MouthSource, SpoonCheck
except ImportError:  # pragma: no cover - 包根直跑形态
    from cs_schema import (  # type: ignore[no-redef]
        CameraRole,
        MouthPose,
        MouthSource,
        SpoonCheck,
    )

__all__ = [
    "WristMouthChannel",
    "SceneBowlScanner",
    "WristSpoonSource",
    "ScriptedScoop",
    "VoiceBusLink",
    "HttpDashboardSink",
]


class WristMouthChannel:
    """腕部双职口部通道（生产实现）：cs_mouth.MouthEstimator + FK×手眼。"""

    cam_ref = "wrist_cam"

    def __init__(self, estimator, frame_provider,
                 t_flange_cam: np.ndarray | None = None, settle_s: float = 0.5) -> None:
        self.estimator = estimator            # cs_mouth.MouthEstimator（契约 §3.2）
        self.frame_provider = frame_provider  # () -> BGR | None
        self.T_flange_cam = (np.asarray(t_flange_cam, dtype=float)
                             if t_flange_cam is not None else load_t_flange_cam())
        self.settle_s = float(settle_s)
        self.role = str(CameraRole.SCENE)
        self.role_ts_ns = 0

    def set_role(self, role, ts_ns: int) -> None:
        self.role = str(role)
        self.role_ts_ns = int(ts_ns)

    def sample(self, t_base_flange: np.ndarray) -> MouthPose:
        import time

        now = time.time_ns()
        if self.role != str(CameraRole.WRIST_MOUTH):
            return self._invalid(now)  # 顶部相机无面部职责
        if now - self.role_ts_ns < int(self.settle_s * 1e9):
            return self._invalid(now)  # 曝光稳定窗内不采信
        frame = self.frame_provider()
        if frame is None:
            return self._invalid(now)
        # 契约 v1.1：cam_pose=(T_base_flange, T_flange_cam) -> IPD 估距 + 基座系
        return self.estimator.from_bgr(
            frame, cam_pose=(np.asarray(t_base_flange, dtype=float),
                             self.T_flange_cam))

    def _invalid(self, ts_ns: int) -> MouthPose:
        nominal = getattr(self.estimator, "prior", None)
        d = float(getattr(nominal, "distance_m", 0.42))
        h = float(getattr(nominal, "mouth_height_m", 0.25))
        return MouthPose(
            ts_ns=ts_ns, valid=False, x=d, y=0.0, z=h,
            jaw_open=0.0, frown=0.0, head_yaw=0.0, head_pitch=0.0, head_roll=0.0,
            source=MouthSource.MONO, confidence=0.0)


class SceneBowlScanner:
    """场景选碗（生产实现）：cs_food.BowlSelector + 顶部相机帧源。"""

    def __init__(self, selector, frame_provider) -> None:
        self.selector = selector  # cs_food.BowlSelector
        self.frame_provider = frame_provider

    def select_bowl(self) -> int | None:
        frame = self.frame_provider()
        if frame is None:
            return None
        return self.selector.select(frame)


class WristSpoonSource:
    """勺上检查源（生产实现）：SpoonClassifier 协议 + 腕部相机帧源。"""

    def __init__(self, classifier, frame_provider, crop_box=None) -> None:
        self.classifier = classifier  # 满足 cs_food.SpoonClassifier 协议
        self.frame_provider = frame_provider
        self.crop_box = crop_box  # (x0, y0, x1, y1) 勺区裁剪；None=整帧

    def check(self) -> SpoonCheck:
        import time

        frame = self.frame_provider()
        if frame is None:
            return SpoonCheck(ts_ns=time.time_ns(), has_food=False, score=0.0,
                              cam_ref="wrist_cam")
        if self.crop_box is not None:
            x0, y0, x1, y1 = self.crop_box
            frame = frame[y0:y1, x0:x1]
        return self.classifier.from_bgr(frame)


class ScriptedScoop:
    """脚本参数化舀取（生产实现；与 MockScoop 同交互，无抖动）。

    轨迹：碗上悬停 -> 慢降 -> 合爪 -> 抬勺；闭环重试由树回流驱动
    （SpoonCheckGate 不过 -> 再走一轮 plan_round）。
    """

    def __init__(self, params) -> None:
        self.params = params
        self.rounds_done = 0

    def plan_round(self, round_idx: int, bowl_pos, bite_idx: int) -> list[tuple]:
        del bite_idx
        p = self.params
        bowl = np.asarray(bowl_pos, dtype=float)
        hover = bowl + np.array([0.0, 0.0, p.bowl_hover_offset_m])
        dip = bowl + np.array([0.0, 0.0, p.bowl_dip_offset_m])
        return [
            ("cart", hover, p.cruise_speed_mps, p.route_step_m),
            ("cart", dip, p.scoop_descend_speed_mps, p.final_step_m),
            ("grip", p.gripper_close, 0.8),
            # 抬勺：逆序回放入碗段关节路径 + 短笛卡尔腿到悬停（见 mock.MockScoop 同注）
            ("jtrack_reverse", p.jtrack_replay_speed_rad_s),
            ("cart", hover, p.scoop_descend_speed_mps, p.final_step_m),
        ]

    def on_round_complete(self, round_idx: int) -> None:
        self.rounds_done = int(round_idx)

    def on_spoon_check(self, check: SpoonCheck) -> bool:
        return bool(check.has_food)

    def retries_left(self) -> int:
        return 0  # 生产重试由树按 scoop_round 与 scoop_retries_max 驱动


class VoiceBusLink:
    """语音总线（生产实现）：透传 cs_voice.VoiceLink 冻结接口。"""

    def __init__(self, link) -> None:
        self.link = link  # cs_voice.VoiceLink

    def bind(self, _ctx, _env, _mock) -> None:
        pass  # 协议占位（mock 实现需要；生产透传无绑定）

    def poll(self):
        return self.link.poll()

    def say(self, text: str) -> None:
        self.link.say(text)


class HttpDashboardSink:
    """进餐记录池（生产实现）：消费 cs_dashboard 冻结 HTTP 契约（§3.2）。

    POST /api/session/start -> {session_id}；POST /api/bite (BiteRecord) -> 204；
    POST /api/session/end。连接失败上抛（上层决定降级策略）。
    """

    def __init__(self, base_url: str, timeout_s: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = float(timeout_s)

    def start_session(self, user_id: str) -> str:
        import httpx

        with httpx.Client(timeout=self.timeout_s) as client:
            r = client.post(f"{self.base_url}/api/session/start",
                            json={"user_id": user_id})
            r.raise_for_status()
            return str(r.json()["session_id"])

    def post_bite(self, record) -> None:
        import httpx

        with httpx.Client(timeout=self.timeout_s) as client:
            r = client.post(f"{self.base_url}/api/bite",
                            json=record.model_dump(mode="json"))
            r.raise_for_status()

    def end_session(self) -> None:
        import httpx

        with httpx.Client(timeout=self.timeout_s) as client:
            r = client.post(f"{self.base_url}/api/session/end")
            r.raise_for_status()
