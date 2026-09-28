"""安全包络校验器（开发指令 §5.1；v3.1 审查修订）。

包络定义（base 系，默认值见 ``chengshao/config/workspace.json``，缺省常量
与其保持一致）：

- 禁入区 1（面部球域）：以口部点为球心、半径 0.12 m 的球（"面部球域
  r=0.12m@口部点外扩"）；
- 禁入区 2（躯干胶囊）：竖直胶囊体（线段 + 半径）；躯干在口部点后方
  （x=0.48）， chest 表面不遮挡可达工作区；
- 速度上限：接近段 0.15 m/s；口部点 0.15 m 范围内 0.10 m/s；
- 关节角速度上限（v3.1）：1.5 rad/s（关节空间轨迹逐段检查）。

判定语义：
- **轨迹级连续检查**：相邻采样点构成的线段整体参与禁入区相交检测（线段-
  球 / 线段-胶囊最近距离），采样稀疏也不会漏判穿入；
- **速度**：逐线段平均速度与该段两端点处更严限速比较；
- **关节轨迹（v3.1）**：``check_joint_trajectory`` 对关节段做加密 FK 采样
  （防"关节空间弧线弦在球外、弧在球内"），并叠加两类新检查——连杆胶囊
  扫掠（相邻连杆参考点连线 + 连杆半径）与关节角速度上限；
- 违规 => ``rejected=True``（对违规轨迹 100% 拒绝，§5.1 通过线）。

送达停点（v3.1 审查修订：停点必须在面部球面**之外**）：
- ``delivery_stop_point()`` = 口部点沿 -X 退 ``face_radius + stop_clearance``
  （默认 0.12 + 0.05 = 0.17 m）。TCP 停在球外、勺头（``spoon_tip_reach``）
  伸向用户，最终由用户前倾取食——名义送达**不需要**任何豁免。
- ``delivery_margin()`` 数值安全余量：``停距 − 勺头伸出 − 跟踪误差上界 −
  感知误差上界 > 0`` 才判通过（§5.1 eval 的硬断言）。
- 送达豁免登记（``register_delivery_target``）保留给非名义场景（如示教
  微调），豁免仅对"整段完全落在目标球内"的线段生效、不豁免限速与连杆
  扫掠；本包 eval 的名义送达走廊**不登记任何豁免**。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .frames import segment_point_distance, segment_segment_distance

__all__ = [
    "EnvelopeConfig",
    "EnvelopeValidator",
    "DEFAULT_ENVELOPE_CONFIG",
    "SPHERE_FACE",
    "CAPSULE_TORSO",
    "DELIVERY_STOP_CLEARANCE_DEFAULT_M",
    "SPOON_TIP_REACH_DEFAULT_M",
    "TRACKING_ERR_DEFAULT_M",
    "SENSE_ERR_DEFAULT_M",
    "DELIVERY_MARGIN_MIN_DEFAULT_M",
    "JOINT_SPEED_LIMIT_DEFAULT_RAD_S",
    "LINK_RADIUS_DEFAULT_M",
    "JOINT_SAMPLE_MAX_DELTA_RAD",
]

# ---- 默认包络（与 config/workspace.json 缺省一致；config 缺失时的兜底） ------
FACE_CENTER_DEFAULT = (0.42, 0.0, 0.30)  # 口部点（base 系，米）
FACE_RADIUS_DEFAULT = 0.12  # 面部球域半径
TORSO_P1_DEFAULT = (0.48, 0.0, -0.10)  # 躯干胶囊轴线下端（v3.1：躯干在口部点后方）
TORSO_P2_DEFAULT = (0.48, 0.0, 0.22)  # 躯干胶囊轴线上端（颈下）
TORSO_RADIUS_DEFAULT = 0.15
SPEED_APPROACH_DEFAULT = 0.15  # 接近段限速 m/s
SPEED_NEAR_FACE_DEFAULT = 0.10  # 口部点近旁限速 m/s
NEAR_FACE_DISTANCE_DEFAULT = 0.15  # "口部点近旁"判定距离 m

# ---- 送达停点与数值安全余量（v3.1 审查修订） --------------------------------
DELIVERY_STOP_CLEARANCE_DEFAULT_M = 0.05  # 停点在面部球面之外的额外间隙
SPOON_TIP_REACH_DEFAULT_M = 0.08  # 勺头伸出（夹爪口沿→勺尖）：保守常量（未实测；
#                                   取偏大值保余量断言成立），D4 臂上件后实测复测覆盖
TRACKING_ERR_DEFAULT_M = 0.02  # 轨迹跟踪误差上界（执行层标定前保守取值）
SENSE_ERR_DEFAULT_M = 0.05  # 口部感知误差上界（mono fixed 误差带上界；ipd 模式实测后可收紧）
DELIVERY_MARGIN_MIN_DEFAULT_M = 0.005  # 余量断言：margin 必须 ≥ 5mm（严格为正）

# ---- 关节轨迹检查（v3.1） ----------------------------------------------------
JOINT_SPEED_LIMIT_DEFAULT_RAD_S = 1.5  # 关节角速度上限（rad/s，逐段检查）
LINK_RADIUS_DEFAULT_M = 0.03  # 连杆近似半径（连杆参考点连线扫掠胶囊）
JOINT_SAMPLE_MAX_DELTA_RAD = 0.05  # 关节段加密采样步长（rad，防弦切漏判）


@dataclass(frozen=True)
class SphereZone:
    name: str
    center: tuple[float, float, float]
    radius: float

    def distance(self, p: np.ndarray) -> float:
        """点到球面的距离（负值 = 在球内）。"""
        return float(np.linalg.norm(p - np.asarray(self.center)) - self.radius)

    def segment_distance(self, a: np.ndarray, b: np.ndarray) -> float:
        """线段 ab 到球面的最近距离（负值 = 相交）。"""
        return segment_point_distance(np.asarray(a), np.asarray(b), np.asarray(self.center)) - self.radius


@dataclass(frozen=True)
class CapsuleZone:
    name: str
    p1: tuple[float, float, float]
    p2: tuple[float, float, float]
    radius: float

    def distance(self, p: np.ndarray) -> float:
        return segment_point_distance(np.asarray(self.p1), np.asarray(self.p2), np.asarray(p)) - self.radius

    def segment_distance(self, a: np.ndarray, b: np.ndarray) -> float:
        return segment_segment_distance(np.asarray(a), np.asarray(b), np.asarray(self.p1), np.asarray(self.p2)) - self.radius


SPHERE_FACE = SphereZone("face", FACE_CENTER_DEFAULT, FACE_RADIUS_DEFAULT)
CAPSULE_TORSO = CapsuleZone("torso", TORSO_P1_DEFAULT, TORSO_P2_DEFAULT, TORSO_RADIUS_DEFAULT)

DEFAULT_ENVELOPE_CONFIG: dict = {
    "mouth_point_m": list(FACE_CENTER_DEFAULT),
    "forbidden_zones": [
        {"type": "sphere", "name": SPHERE_FACE.name,
         "center_m": list(SPHERE_FACE.center), "radius_m": SPHERE_FACE.radius},
        {"type": "capsule", "name": CAPSULE_TORSO.name,
         "p1_m": list(CAPSULE_TORSO.p1), "p2_m": list(CAPSULE_TORSO.p2),
         "radius_m": CAPSULE_TORSO.radius},
    ],
    "speed_limits_mps": {"approach": SPEED_APPROACH_DEFAULT, "near_face": SPEED_NEAR_FACE_DEFAULT},
    "near_face_distance_m": NEAR_FACE_DISTANCE_DEFAULT,
}


@dataclass
class EnvelopeConfig:
    """包络参数（从 config/workspace.json 或缺省常量构造）。"""

    zones: tuple[object, ...]
    face_center: np.ndarray
    speed_approach: float
    speed_near_face: float
    near_face_distance: float
    # v3.1 扩展（可选键，缺省用冻结常量）
    delivery_stop_clearance: float = DELIVERY_STOP_CLEARANCE_DEFAULT_M
    spoon_tip_reach: float = SPOON_TIP_REACH_DEFAULT_M
    tracking_err_bound: float = TRACKING_ERR_DEFAULT_M
    sense_err_bound: float = SENSE_ERR_DEFAULT_M
    joint_speed_limit: float = JOINT_SPEED_LIMIT_DEFAULT_RAD_S
    link_radius: float = LINK_RADIUS_DEFAULT_M

    @classmethod
    def from_dict(cls, cfg: dict) -> "EnvelopeConfig":
        zones = []
        for z in cfg.get("forbidden_zones", []):
            ztype = (z.get("type") or "").lower()
            if ztype == "sphere":
                zones.append(SphereZone(z.get("name", "sphere"),
                                        tuple(float(v) for v in z["center_m"]),
                                        float(z["radius_m"])))
            elif ztype == "capsule":
                zones.append(CapsuleZone(z.get("name", "capsule"),
                                         tuple(float(v) for v in z["p1_m"]),
                                         tuple(float(v) for v in z["p2_m"]),
                                         float(z["radius_m"])))
            else:
                raise ValueError(f"unknown forbidden zone type: {ztype!r}")
        limits = cfg.get("speed_limits_mps", {})
        dv = cfg.get("delivery", {})
        return cls(
            zones=tuple(zones),
            face_center=np.asarray(cfg.get("mouth_point_m", FACE_CENTER_DEFAULT), dtype=float),
            speed_approach=float(limits.get("approach", SPEED_APPROACH_DEFAULT)),
            speed_near_face=float(limits.get("near_face", SPEED_NEAR_FACE_DEFAULT)),
            near_face_distance=float(cfg.get("near_face_distance_m", NEAR_FACE_DISTANCE_DEFAULT)),
            delivery_stop_clearance=float(
                dv.get("stop_clearance_m", DELIVERY_STOP_CLEARANCE_DEFAULT_M)),
            spoon_tip_reach=float(
                dv.get("spoon_tip_reach_m", SPOON_TIP_REACH_DEFAULT_M)),
            tracking_err_bound=float(
                dv.get("tracking_err_bound_m", TRACKING_ERR_DEFAULT_M)),
            sense_err_bound=float(
                dv.get("sense_err_bound_m", SENSE_ERR_DEFAULT_M)),
            joint_speed_limit=float(
                cfg.get("joint_speed_limit_rad_s", JOINT_SPEED_LIMIT_DEFAULT_RAD_S)),
            link_radius=float(cfg.get("link_radius_m", LINK_RADIUS_DEFAULT_M)),
        )


class EnvelopeValidator:
    """安全包络校验器：点 / 线段 / 轨迹三级检查 + 限速场 + 送达豁免登记。"""

    def __init__(self, config: dict | EnvelopeConfig | None = None,
                 config_path: str | Path | None = None) -> None:
        if isinstance(config, EnvelopeConfig):
            self.config = config
        elif isinstance(config, dict):
            self.config = EnvelopeConfig.from_dict(config)
        elif config_path is not None:
            self.config = EnvelopeConfig.from_dict(
                json.loads(Path(config_path).read_text(encoding="utf-8"))
            )
        else:
            self.config = EnvelopeConfig.from_dict(_load_default_config_dict())
        self._delivery_targets: list[tuple[np.ndarray, float]] = []

    # ---- 豁免登记（送达目标；默认无） ----------------------------------------

    def register_delivery_target(self, point_m, radius_m: float = 0.03) -> int:
        """登记送达目标点：完全落在目标球内的线段豁免禁入区判定（限速不豁免）。"""
        self._delivery_targets.append((np.asarray(point_m, dtype=float).copy(), float(radius_m)))
        return len(self._delivery_targets) - 1

    def clear_delivery_targets(self) -> None:
        self._delivery_targets.clear()

    # ---- 点 / 限速查询 --------------------------------------------------------

    def point_zone_violation(self, p) -> str | None:
        """点所在禁入区名；不在任何禁入区返回 None。"""
        p = np.asarray(p, dtype=float)
        for zone in self.config.zones:
            if zone.distance(p) < 0.0:
                return zone.name
        return None

    def min_zone_clearance(self, p) -> float:
        """点到最近禁入区表面的距离（负值 = 已在区内）。"""
        p = np.asarray(p, dtype=float)
        return float(min(zone.distance(p) for zone in self.config.zones))

    def speed_limit_at(self, p) -> float:
        """点处限速（m/s）：口部点近旁取严限，否则接近段限速。"""
        p = np.asarray(p, dtype=float)
        if float(np.linalg.norm(p - self.config.face_center)) <= self.config.near_face_distance:
            return self.config.speed_near_face
        return self.config.speed_approach

    # ---- 送达停点与数值安全余量（v3.1） ----------------------------------------

    @property
    def face_radius(self) -> float:
        """面部球域半径（取自配置）。"""
        face = next(z for z in self.config.zones if z.name == "face")
        return float(face.radius)

    def delivery_stop_point(self) -> np.ndarray:
        """名义送达停点（TCP 目标）：口部点沿 -X 退 (面部球半径 + 间隙)。

        返回点必在面部球面**之外**（审查修订：停点不再依赖球内豁免）；
        勺头（spoon_tip_reach）伸向用户，最终距离由 delivery_margin 断言。
        """
        d = self.face_radius + self.config.delivery_stop_clearance
        return self.config.face_center + np.array([-d, 0.0, 0.0])

    def delivery_stop_distance(self) -> float:
        """TCP 停点到口部点的名义距离（米）。"""
        return self.face_radius + self.config.delivery_stop_clearance

    def delivery_margin(self) -> dict:
        """数值安全余量：停距 − 勺头伸出 − 跟踪误差上界 − 感知误差上界。

        ``margin_m > 0``（且 ≥ 最小正裕量）才允许通过——"最坏情况下勺尖
        仍不接触面部"的数值证据（审查 B3）。
        """
        d = self.delivery_stop_distance()
        margin = (
            d
            - self.config.spoon_tip_reach
            - self.config.tracking_err_bound
            - self.config.sense_err_bound
        )
        return {
            "stop_distance_m": d,
            "spoon_tip_reach_m": self.config.spoon_tip_reach,
            "tracking_err_bound_m": self.config.tracking_err_bound,
            "sense_err_bound_m": self.config.sense_err_bound,
            "margin_m": margin,
            "pass": margin >= DELIVERY_MARGIN_MIN_DEFAULT_M,
        }

    # ---- 线段 / 轨迹检查 ------------------------------------------------------

    def _zone_segment_violation(self, a: np.ndarray, b: np.ndarray) -> tuple[list, float]:
        """线段的禁入区违规：返回 (违规区命中列表, 最小间隙 m)。

        v3.1 审查补丁：一条段同时穿过多个禁区时**逐区报告**（旧实现只报
        间隙最深的一区，会把同段上的面部球域入侵吞掉）。命中列表元素为
        ``(区名, 该区间隙 m)``，按间隙升序（最深在前）；豁免目标球内的段
        不计违规（仍报告间隙）。
        """
        if self._in_delivery_target(a) and self._in_delivery_target(b):
            # 送达豁免：段整体在目标球内（仍报告间隙，但不计违规）
            clearance = min(z.segment_distance(a, b) for z in self.config.zones)
            return [], clearance
        hits: list[tuple[str, float]] = []
        worst_clear = float("inf")
        for zone in self.config.zones:
            d = zone.segment_distance(a, b)
            worst_clear = min(worst_clear, d)
            if d < 0.0:
                hits.append((zone.name, d))
        hits.sort(key=lambda x: x[1])
        return hits, worst_clear

    def _in_delivery_target(self, p: np.ndarray) -> bool:
        return any(float(np.linalg.norm(p - c)) <= r for c, r in self._delivery_targets)

    def check_segment(self, a, b, dt_s: float) -> dict:
        """单段检查（诊断用）：返回区违规（单区兼容字段 + 全部命中列表）与限速判定。"""
        a = np.asarray(a, dtype=float)
        b = np.asarray(b, dtype=float)
        if dt_s <= 0.0:
            raise ValueError(f"dt must be positive, got {dt_s}")
        zone_hits, clearance = self._zone_segment_violation(a, b)
        speed = float(np.linalg.norm(b - a)) / float(dt_s)
        limit = min(self.speed_limit_at(a), self.speed_limit_at(b))
        return {
            "zone_violation": zone_hits[0][0] if zone_hits else None,
            "zone_violation_hits": [[name, d] for name, d in zone_hits],
            "clearance_m": clearance,
            "speed_mps": speed,
            "speed_limit_mps": limit,
            "speed_violation": speed > limit * (1.0 + 1e-9),
        }

    def check_trajectory(self, times_s, points_m, label: str = "traj") -> dict:
        """轨迹检查：times_s/points_m 等长且 >=2 点；时间须严格递增。

        返回::

            {"label", "n_points", "duration_s", "path_len_m",
             "min_zone_clearance_m", "max_speed_mps",
             "violations": [{"kind": "zone"|"speed", "zone"|"limit_mps",
                              "segment_index", "detail"}],
             "rejected": bool}

        任一违规 => ``rejected=True``（§5.1：违规轨迹 100% 拒绝）。
        """
        t = np.asarray(times_s, dtype=float)
        pts = np.asarray(points_m, dtype=float)
        if pts.ndim != 2 or pts.shape[1] != 3:
            raise ValueError(f"points must be (N,3), got {pts.shape}")
        if len(t) != len(pts):
            raise ValueError(f"times/points length mismatch: {len(t)} vs {len(pts)}")
        if len(t) < 2:
            raise ValueError("trajectory needs at least 2 samples")
        if np.any(np.diff(t) <= 0.0):
            raise ValueError("times must be strictly increasing")

        violations: list[dict] = []
        min_clear = float("inf")
        max_speed = 0.0
        path_len = 0.0
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            dt = float(t[i + 1] - t[i])
            seg = self.check_segment(a, b, dt)
            path_len += float(np.linalg.norm(b - a))
            min_clear = min(min_clear, seg["clearance_m"])
            max_speed = max(max_speed, seg["speed_mps"])
            for zone_name, zone_clear in seg["zone_violation_hits"]:
                violations.append({
                    "kind": "zone",
                    "zone": zone_name,
                    "segment_index": i,
                    "detail": f"clearance {zone_clear * 1000:.1f} mm inside {zone_name}",
                })
            if seg["speed_violation"]:
                violations.append({
                    "kind": "speed",
                    "limit_mps": seg["speed_limit_mps"],
                    "segment_index": i,
                    "detail": f"speed {seg['speed_mps']:.3f} m/s > limit {seg['speed_limit_mps']:.3f} m/s",
                })
        return {
            "label": label,
            "n_points": int(len(pts)),
            "duration_s": float(t[-1] - t[0]),
            "path_len_m": path_len,
            "min_zone_clearance_m": min_clear,
            "max_speed_mps": max_speed,
            "violations": violations,
            "rejected": bool(violations),
        }

    def check_joint_trajectory(self, times_s, q_list, arm_model, label: str = "joint_traj") -> dict:
        """关节空间轨迹检查（v3.1 重做）：TCP 加密采样 + 连杆扫掠 + 关节角速度。

        - **TCP 加密**：关节段按最大关节步长 ``JOINT_SAMPLE_MAX_DELTA_RAD``
          细分为子段、逐点 FK 后仍走线段级连续检查——防"关节空间弧线弦在
          球外、弧在球内"（审查 A3）；
        - **连杆扫掠**：相邻连杆参考点（``arm_model.link_points``）连线叠加
          连杆半径（``config.link_radius``）逐子段检查禁入区（豁免不适用于
          连杆体）；违规类别记 ``link_sweep``；
        - **关节角速度**：逐段 max|Δq|/Δt 对 ``config.joint_speed_limit`` 检查，
          违规类别记 ``joint_speed``。

        返回在 :meth:`check_trajectory` 报告基础上追加
        ``max_joint_speed_rad_s`` / ``min_link_clearance_m`` 字段。
        """
        t = np.asarray(times_s, dtype=float)
        q = np.asarray(q_list, dtype=float)
        if q.ndim != 2 or len(t) != len(q):
            raise ValueError(f"times/q length mismatch: {len(t)} vs {len(q)}")
        if len(t) < 2:
            raise ValueError("trajectory needs at least 2 samples")
        if np.any(np.diff(t) <= 0.0):
            raise ValueError("times must be strictly increasing")

        # 1) 关节段加密 FK → TCP 连续检查
        dense_t: list[float] = []
        dense_q: list[np.ndarray] = []
        for i in range(len(t) - 1):
            dt = float(t[i + 1] - t[i])
            steps = max(1, int(np.ceil(float(np.max(np.abs(q[i + 1] - q[i])))
                                       / JOINT_SAMPLE_MAX_DELTA_RAD))
                        if q.shape[1] else 1)
            for s in range(steps):
                f = s / steps
                dense_t.append(float(t[i] + f * dt))
                dense_q.append(q[i] + f * (q[i + 1] - q[i]))
        dense_t.append(float(t[-1]))
        dense_q.append(q[-1])
        tcp_pts = [list(arm_model.fk([float(v) for v in qq])[0:3]) for qq in dense_q]
        rep = self.check_trajectory(dense_t, tcp_pts, label=label)

        # 2) 连杆扫掠（豁免不适用：连杆体不得进入任何禁入区）
        link_radius = self.config.link_radius
        min_link_clear = float("inf")
        for i in range(len(dense_q) - 1):
            pts0 = arm_model.link_points([float(v) for v in dense_q[i]])
            pts1 = arm_model.link_points([float(v) for v in dense_q[i + 1]])
            for p0, p1 in zip(pts0, pts1):
                a = np.asarray(p0, dtype=float)
                b = np.asarray(p1, dtype=float)
                for zone in self.config.zones:
                    d = zone.segment_distance(a, b) - link_radius
                    min_link_clear = min(min_link_clear, d)
                    if d < 0.0:
                        rep["violations"].append({
                            "kind": "link_sweep",
                            "zone": zone.name,
                            "segment_index": i,
                            "detail": f"link sweep clearance {d * 1000:.1f} mm "
                                      f"(radius {link_radius * 1000:.0f} mm) inside {zone.name}",
                        })

        # 3) 关节角速度（逐原段）
        max_joint_speed = 0.0
        for i in range(len(t) - 1):
            dt = float(t[i + 1] - t[i])
            speed = float(np.max(np.abs(q[i + 1] - q[i]))) / dt
            max_joint_speed = max(max_joint_speed, speed)
            if speed > self.config.joint_speed_limit * (1.0 + 1e-9):
                rep["violations"].append({
                    "kind": "joint_speed",
                    "limit_rad_s": self.config.joint_speed_limit,
                    "segment_index": i,
                    "detail": f"joint speed {speed:.3f} rad/s > limit "
                              f"{self.config.joint_speed_limit:.3f} rad/s",
                })

        rep["max_joint_speed_rad_s"] = max_joint_speed
        rep["min_link_clearance_m"] = min_link_clear
        rep["rejected"] = bool(rep["violations"])
        return rep


# ---- 默认配置装载 -------------------------------------------------------------


def _package_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "workspace.json"


def _load_default_config_dict() -> dict:
    """config/workspace.json 存在则用之，否则用内置缺省（二者数值一致）。"""
    path = _package_config_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return json.loads(json.dumps(DEFAULT_ENVELOPE_CONFIG))
