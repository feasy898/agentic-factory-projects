"""安全包络校验器（开发指令 §5.1）。

包络定义（base 系，默认值见 ``chengshao/config/workspace.json``，缺省常量
与其保持一致）：

- 禁入区 1（面部球域）：以口部点为球心、半径 0.12 m 的球（"面部球域
  r=0.12m@口部点外扩"）；
- 禁入区 2（躯干胶囊）：竖直胶囊体（线段 + 半径）；
- 速度上限：接近段 0.15 m/s；口部点 0.15 m 范围内 0.10 m/s。

判定语义：
- **轨迹级连续检查**：相邻采样点构成的线段整体参与禁入区相交检测（线段-
  球 / 线段-胶囊最近距离），采样稀疏也不会漏判穿入；
- **速度**：逐线段平均速度与该段两端点处更严限速比较；
- 违规 => ``rejected=True``（对违规轨迹 100% 拒绝，§5.1 通过线）。

送达豁免（面向 §5.6/§5.8 的"送达至口前 5cm"语义，默认关闭）：可注册
送达目标点，完全落在目标球内的线段不计面部球域违规；速度上限不受豁免。
本包 eval 不注册任何目标，即默认语义下验收。
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
]

# ---- 默认包络（与 config/workspace.json 缺省一致；config 缺失时的兜底） ------
FACE_CENTER_DEFAULT = (0.42, 0.0, 0.30)  # 口部点（base 系，米）
FACE_RADIUS_DEFAULT = 0.12  # 面部球域半径
TORSO_P1_DEFAULT = (0.40, 0.0, -0.10)  # 躯干胶囊轴线下端
TORSO_P2_DEFAULT = (0.40, 0.0, 0.22)  # 躯干胶囊轴线上端（颈下）
TORSO_RADIUS_DEFAULT = 0.15
SPEED_APPROACH_DEFAULT = 0.15  # 接近段限速 m/s
SPEED_NEAR_FACE_DEFAULT = 0.10  # 口部点近旁限速 m/s
NEAR_FACE_DISTANCE_DEFAULT = 0.15  # "口部点近旁"判定距离 m


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
        return cls(
            zones=tuple(zones),
            face_center=np.asarray(cfg.get("mouth_point_m", FACE_CENTER_DEFAULT), dtype=float),
            speed_approach=float(limits.get("approach", SPEED_APPROACH_DEFAULT)),
            speed_near_face=float(limits.get("near_face", SPEED_NEAR_FACE_DEFAULT)),
            near_face_distance=float(cfg.get("near_face_distance_m", NEAR_FACE_DISTANCE_DEFAULT)),
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

    # ---- 线段 / 轨迹检查 ------------------------------------------------------

    def _zone_segment_violation(self, a: np.ndarray, b: np.ndarray) -> tuple[str | None, float]:
        """线段的禁入区违规：返回 (区名|None, 最小间隙 m)。豁免目标球内的段不计。"""
        if self._in_delivery_target(a) and self._in_delivery_target(b):
            # 送达豁免：段整体在目标球内（仍报告间隙，但不计违规）
            clearance = min(z.segment_distance(a, b) for z in self.config.zones)
            return None, clearance
        worst_name: str | None = None
        worst_clear = float("inf")
        for zone in self.config.zones:
            d = zone.segment_distance(a, b)
            if d < worst_clear:
                worst_clear = d
                if d < 0.0:
                    worst_name = zone.name
        return worst_name, worst_clear

    def _in_delivery_target(self, p: np.ndarray) -> bool:
        return any(float(np.linalg.norm(p - c)) <= r for c, r in self._delivery_targets)

    def check_segment(self, a, b, dt_s: float) -> dict:
        """单段检查（诊断用）：返回 {zone_violation, clearance_m, speed_mps, speed_limit_mps, speed_violation}。"""
        a = np.asarray(a, dtype=float)
        b = np.asarray(b, dtype=float)
        if dt_s <= 0.0:
            raise ValueError(f"dt must be positive, got {dt_s}")
        zone_name, clearance = self._zone_segment_violation(a, b)
        speed = float(np.linalg.norm(b - a)) / float(dt_s)
        limit = min(self.speed_limit_at(a), self.speed_limit_at(b))
        return {
            "zone_violation": zone_name,
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
            if seg["zone_violation"] is not None:
                violations.append({
                    "kind": "zone",
                    "zone": seg["zone_violation"],
                    "segment_index": i,
                    "detail": f"clearance {seg['clearance_m'] * 1000:.1f} mm inside forbidden zone",
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
        """关节空间轨迹检查：先经 ArmModel.fk 映射为 TCP 轨迹再检查。"""
        pts = [arm_model.fk([float(v) for v in q])[0:3] for q in q_list]
        return self.check_trajectory(times_s, pts, label=label)


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
