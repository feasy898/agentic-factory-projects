"""独立违规轨迹生成器（对抗性 oracle；审查 A1/A3 修订）。

定位：cs_sim eval §5.1 的违规轨迹样本此前由与校验器**共用**线段距离实现
的笛卡尔折线生成——100% 拒是自洽，不是独立证据。本模块是独立 oracle：

- **不复用**校验器的距离代码：``cs_sim.frames`` 一概不 import，几何判据
  （点-球穿透、点-胶囊穿透、线段采样最近距）全部在本文件内独立实现；
- 只在**关节空间**生成轨迹（FK 后落在 TCP/连杆上），覆盖校验器此前没有
  样本的三类违规：关节角速度超限、连杆胶囊扫掠入禁区、关节空间插值把
  TCP 带入禁入区（"弦在球外、弧在球内"）；
- 每条轨迹带**预定违规类别**（生成前经独立判据证实违规），eval 要求校验
  器拒绝且违规类别命中预定类别——两边有一边是错的都会暴露。

命名：``oracle`` 字段是生成侧的独立证据（几何/arithmetic），与校验器的
``violations`` 无共享实现。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

__all__ = [
    "AdversarialCase",
    "build_adversarial_cases",
    "run_adversarial",
    "CATEGORY_JOINT_SPEED",
    "CATEGORY_LINK_SWEEP",
    "CATEGORY_TCP_ARC",
]

CATEGORY_JOINT_SPEED = "joint_speed_over_limit"
CATEGORY_LINK_SWEEP = "link_capsule_sweep"
CATEGORY_TCP_ARC = "tcp_arc_zone_intrusion"

# 预定类别 -> 校验器违规 kind（zone 类另带预期区名）
PREDICTED_KINDS: dict[str, str] = {
    CATEGORY_JOINT_SPEED: "joint_speed",
    CATEGORY_LINK_SWEEP: "link_sweep",
    CATEGORY_TCP_ARC: "zone",
}

# ---- 独立几何判据（刻意与 cs_sim.frames 不同实现） ---------------------------


def sphere_penetration(p, center, radius: float) -> float:
    """点对球体的穿透深度（>0 在球内，<0 在球外的距离）。"""
    p = np.asarray(p, dtype=float)
    c = np.asarray(center, dtype=float)
    return float(radius - float(np.linalg.norm(p - c)))


def _point_segment_sq(p, a, b) -> float:
    """点到线段 ab 的距离平方（独立实现：显式端点/投影三分支）。"""
    p = np.asarray(p, dtype=float)
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    ab = b - a
    denom = float(ab @ ab)
    if denom <= 1e-18:
        d = p - a
        return float(d @ d)
    t = float((p - a) @ ab) / denom
    if t <= 0.0:
        d = p - a
    elif t >= 1.0:
        d = p - b
    else:
        d = p - (a + t * ab)
    return float(d @ d)


def capsule_penetration(p, p1, p2, radius: float) -> float:
    """点对胶囊体（线段 p1-p2 加半径）的穿透深度（>0 在体内）。"""
    return float(radius - float(np.sqrt(_point_segment_sq(p, p1, p2))))


def chord_min_distance(a, b, c, n_samples: int = 33) -> float:
    """线段 ab 到点 c 的最近距（独立数值口径：线段等弧长采样取最小）。

    生成器 oracle 只用"穿透深度 ≥ 数毫米"这类远超采样误差的判据，
    采样口径的偏差不影响结论。
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    c = np.asarray(c, dtype=float)
    f = np.linspace(0.0, 1.0, int(n_samples))[:, None]
    pts = a[None, :] + f * (b - a)[None, :]
    return float(np.min(np.linalg.norm(pts - c[None, :], axis=1)))


# ---- 场景快照（把校验器配置读成纯数学生成的独立判据入参） ----------------------


@dataclass
class _Zones:
    """禁入区的纯几何快照（从 EnvelopeConfig 提取，只含数字）。"""

    face_center: np.ndarray
    face_radius: float
    torso_p1: np.ndarray
    torso_p2: np.ndarray
    torso_radius: float

    @classmethod
    def from_validator(cls, val) -> "_Zones":
        face = next(z for z in val.config.zones if z.name == "face")
        torso = next(z for z in val.config.zones if z.name == "torso")
        return cls(
            face_center=np.asarray(face.center, dtype=float),
            face_radius=float(face.radius),
            torso_p1=np.asarray(torso.p1, dtype=float),
            torso_p2=np.asarray(torso.p2, dtype=float),
            torso_radius=float(torso.radius),
        )

    def point_penetration(self, p) -> tuple[str, float]:
        """点对更深禁入区的穿透深度：返回 (区名, 穿透深度)。

        穿透深度 >0 = 在该区内、深入多少；<0 = 在所有区外，其相反数即到
        最近禁区表面的间隙。调用方以 ``pen >= 正阈值`` 判"真在区内"。
        """
        pf = sphere_penetration(p, self.face_center, self.face_radius)
        pt = capsule_penetration(p, self.torso_p1, self.torso_p2, self.torso_radius)
        if pf >= pt:
            return "face", pf
        return "torso", pt

    def point_clearance(self, p) -> float:
        """点到最近禁入区表面的距离（负 = 在区内）。"""
        pf = sphere_penetration(p, self.face_center, self.face_radius)
        pt = capsule_penetration(p, self.torso_p1, self.torso_p2, self.torso_radius)
        return -max(pf, pt)  # 穿透取负即间隙

    def face_penetration(self, p) -> float:
        """点对面部球域的穿透深度（>0 在球内）——TCP 弧类别的专用判据。"""
        return sphere_penetration(p, self.face_center, self.face_radius)


@dataclass
class AdversarialCase:
    """一条带预定违规类别的对抗性关节轨迹。"""

    category: str
    predicted_kind: str
    predicted_zone: str | None
    times_s: list[float]
    q_list: list[list[float]]
    oracle: dict = field(default_factory=dict)


# ---- 干净构型采样（oracle 侧独立判据） ---------------------------------------


def _sample_clean_config(arm, zones: _Zones, rng: np.random.Generator,
                         min_clear_m: float = 0.02, tries: int = 400):
    """采样 TCP 与全部连杆参考点都离禁区至少 min_clear_m 的构型。"""
    lo = np.asarray(arm.joint_lower, dtype=float)
    hi = np.asarray(arm.joint_upper, dtype=float)
    mid = 0.5 * (lo + hi)
    n_arm = arm.n_joints - 1  # 末关节夹爪不改变 TCP
    for _ in range(tries):
        q = mid.copy()
        q[:n_arm] = rng.uniform(lo[:n_arm], hi[:n_arm])
        tcp = np.asarray(arm.fk([float(v) for v in q])[:3])
        if zones.point_clearance(tcp) < min_clear_m:
            continue
        lp = np.asarray(arm.link_points([float(v) for v in q]))
        if min(zones.point_clearance(p) for p in lp) < min_clear_m:
            continue
        return q
    return None


def _link_sweep_hit(arm, zones: _Zones, q, link_radius: float,
                    min_pen_m: float, min_tcp_clear_m: float) -> tuple[int, str, float] | None:
    """连杆扫掠命中发现：返回 (连杆参考点下标, 区名, 穿透深度) 或 None。

    条件：某个**非 TCP** 连杆参考点深入禁区至少 min_pen_m，且 TCP 离所有
    禁区表面至少 min_tcp_clear_m（把"连杆体违规"与"TCP 违规"区分开）。
    """
    lp = np.asarray(arm.link_points([float(v) for v in q]))
    tcp_clear = zones.point_clearance(lp[-1])
    if tcp_clear < min_tcp_clear_m:
        return None
    for i in range(len(lp) - 1):
        name, pen = zones.point_penetration(lp[i])
        if pen >= min_pen_m:
            return i, name, pen
    return None


# ---- 三类生成器 ---------------------------------------------------------------


def _gen_joint_speed(arm, zones: _Zones, val, rng, n: int) -> list[AdversarialCase]:
    """关节角速度超限：干净构型间大步长短时间移动（oracle=纯算术）。"""
    limit = float(val.config.joint_speed_limit)
    lo = np.asarray(arm.joint_lower, dtype=float)
    hi = np.asarray(arm.joint_upper, dtype=float)
    n_arm = arm.n_joints - 1
    cases: list[AdversarialCase] = []
    while len(cases) < n:
        q0 = _sample_clean_config(arm, zones, rng)
        if q0 is None:
            break
        j = int(rng.integers(0, n_arm))
        delta = float(rng.uniform(0.7, 1.1)) * float(rng.choice([-1.0, 1.0]))
        q1 = q0.copy()
        q1[j] = float(np.clip(q1[j] + delta, lo[j], hi[j]))
        if abs(q1[j] - q0[j]) < 0.5:
            continue
        if _sample_clean_config_check(arm, zones, q1) is False:
            continue
        dt = float(rng.uniform(0.15, 0.3))
        speed = abs(q1[j] - q0[j]) / dt
        if speed < 1.5 * limit:  # oracle：显著超限，远离判据边界
            continue
        cases.append(AdversarialCase(
            category=CATEGORY_JOINT_SPEED,
            predicted_kind=PREDICTED_KINDS[CATEGORY_JOINT_SPEED],
            predicted_zone=None,
            times_s=[0.0, dt],
            q_list=[[float(v) for v in q0], [float(v) for v in q1]],
            oracle={
                "joint": j,
                "max_abs_dq_rad": round(abs(q1[j] - q0[j]), 4),
                "dt_s": round(dt, 4),
                "max_joint_speed_rad_s": round(speed, 3),
                "limit_rad_s": limit,
                "ratio_over_limit": round(speed / limit, 2),
            },
        ))
    return cases


def _sample_clean_config_check(arm, zones: _Zones, q) -> bool:
    tcp = np.asarray(arm.fk([float(v) for v in q])[:3])
    if zones.point_clearance(tcp) < 0.015:
        return False
    lp = np.asarray(arm.link_points([float(v) for v in q]))
    return min(zones.point_clearance(p) for p in lp) >= 0.015


def _gen_link_sweep(arm, zones: _Zones, val, rng, n: int,
                    budget: int = 60_000) -> list[AdversarialCase]:
    """连杆胶囊扫掠：TCP 留在禁区外、某连杆体（参考点+半径）深入禁区。

    轨迹形态 = 围绕违规构型的极慢漂移（0.001 rad/s 级）——角速度与 TCP
    检查都干净，预期**唯一**违规类别是 link_sweep。
    """
    lr = float(val.config.link_radius)
    lo = np.asarray(arm.joint_lower, dtype=float)
    hi = np.asarray(arm.joint_upper, dtype=float)
    n_arm = arm.n_joints - 1
    mid = 0.5 * (lo + hi)
    cases: list[AdversarialCase] = []
    seeds: list[np.ndarray] = []
    tried = 0
    while len(cases) < n and tried < budget:
        tried += 1
        if seeds and rng.uniform() < 0.8:
            base = seeds[int(rng.integers(0, len(seeds)))]
            q = base + rng.normal(scale=0.06, size=len(base))
            q = np.clip(q, lo, hi)
        else:
            q = mid.copy()
            q[:n_arm] = rng.uniform(lo[:n_arm], hi[:n_arm])
        hit = _link_sweep_hit(arm, zones, q, lr, min_pen_m=0.006, min_tcp_clear_m=0.015)
        if hit is None:
            continue
        i, zone_name, pen = hit
        seeds.append(q)
        # 极慢漂移：终态同样保持扫掠违规、TCP 干净（oracle 双端核验）
        q1 = q.copy()
        q1[int(rng.integers(0, n_arm))] += 0.004
        q1 = np.clip(q1, lo, hi)
        hit1 = _link_sweep_hit(arm, zones, q1, lr, min_pen_m=0.004, min_tcp_clear_m=0.012)
        if hit1 is None:
            continue
        dur = 8.0  # 0.004 rad / 8s = 0.0005 rad/s << 1.5
        cases.append(AdversarialCase(
            category=CATEGORY_LINK_SWEEP,
            predicted_kind=PREDICTED_KINDS[CATEGORY_LINK_SWEEP],
            predicted_zone=zone_name,
            times_s=[0.0, dur],
            q_list=[[float(v) for v in q], [float(v) for v in q1]],
            oracle={
                "link_point_index": int(i),
                "zone": zone_name,
                "penetration_start_m": round(pen, 4),
                "link_radius_m": lr,
                "tcp_clearance_start_m": round(zones.point_clearance(
                    np.asarray(arm.link_points([float(v) for v in q])[-1])), 4),
                "drift_rad": 0.004,
                "duration_s": dur,
                "samples_tried": tried,
            },
        ))
    return cases


def _clean_config_pool(arm, zones: _Zones, rng, size: int = 200,
                       min_clear_m: float = 0.015) -> list[np.ndarray]:
    """一次性采一批干净构型，供弧线生成循环复用（省去逐候选的采样开销）。"""
    pool: list[np.ndarray] = []
    seen = 0
    while len(pool) < size and seen < size * 60:
        seen += 1
        q = _sample_clean_config(arm, zones, rng, min_clear_m=min_clear_m, tries=1)
        if q is not None:
            pool.append(q)
    return pool


def _gen_tcp_arc(arm, zones: _Zones, val, rng, n: int,
                 budget: int = 30_000) -> list[AdversarialCase]:
    """关节空间插值把 TCP 带入面部球域：两端在球外、弧中段入球（弦检盲区）。

    搜索用粗扫描（15 点 + 早退），入选样本再用 101 点细扫描出 oracle 证据。
    """
    lo = np.asarray(arm.joint_lower, dtype=float)
    hi = np.asarray(arm.joint_upper, dtype=float)
    n_arm = arm.n_joints - 1
    cases: list[AdversarialCase] = []
    pool = _clean_config_pool(arm, zones, rng, size=200, min_clear_m=0.015)
    if not pool:
        return cases
    tried = 0
    while len(cases) < n and tried < budget:
        tried += 1
        qa = pool[int(rng.integers(0, len(pool)))]
        j = int(rng.integers(0, n_arm))
        qb = qa.copy()
        qb[j] = float(np.clip(qb[j] + float(rng.uniform(0.7, 1.5)) * float(rng.choice([-1.0, 1.0])),
                              lo[j], hi[j]))
        # 粗扫描（早退）：中段任一点入球 ≥5mm 才进入细筛
        coarse_worst = -1e9
        for f in np.linspace(0.0, 1.0, 15)[1:-1]:
            qi = qa + f * (qb - qa)
            p = np.asarray(arm.fk([float(v) for v in qi])[:3])
            coarse_worst = max(coarse_worst, zones.face_penetration(p))
            if coarse_worst >= 0.005:
                break
        if coarse_worst < 0.005:
            continue
        # 细扫描出 oracle 证据（101 点 + TCP 弧长）
        arc = 0.0
        prev_p: np.ndarray | None = None
        worst = -1e9
        for f in np.linspace(0.0, 1.0, 101)[1:-1]:
            qi = qa + f * (qb - qa)
            p = np.asarray(arm.fk([float(v) for v in qi])[:3])
            if prev_p is not None:
                arc += float(np.linalg.norm(p - prev_p))
            prev_p = p
            worst = max(worst, zones.face_penetration(p))
        pen_a = -zones.face_penetration(np.asarray(arm.fk([float(v) for v in qa])[:3]))
        pen_b = -zones.face_penetration(np.asarray(arm.fk([float(v) for v in qb])[:3]))
        if worst < 0.006 or pen_a < 0.015 or pen_b < 0.015:
            continue  # oracle：中段入球 ≥6mm，两端离球 ≥15mm
        # 时间刻度：TCP 弧长按 0.06 m/s（< 近脸 0.10 限速），关节速度留裕量
        duration = max(arc / 0.06, 1.0)
        max_joint_speed = abs(qb[j] - qa[j]) / duration
        if max_joint_speed > 0.5 * float(val.config.joint_speed_limit):
            continue  # 类别提纯：不靠关节速度违规
        cases.append(AdversarialCase(
            category=CATEGORY_TCP_ARC,
            predicted_kind=PREDICTED_KINDS[CATEGORY_TCP_ARC],
            predicted_zone="face",
            times_s=[0.0, duration],
            q_list=[[float(v) for v in qa], [float(v) for v in qb]],
            oracle={
                "joint": j,
                "abs_dq_rad": round(abs(qb[j] - qa[j]), 4),
                "endpoint_clearance_m": [round(pen_a, 4), round(pen_b, 4)],
                "max_arc_penetration_m": round(worst, 4),
                "tcp_arc_len_m": round(arc, 4),
                "duration_s": round(duration, 3),
                "implied_tcp_speed_mps": round(arc / duration, 4),
                "implied_joint_speed_rad_s": round(max_joint_speed, 4),
                "samples_tried": tried,
            },
        ))
    return cases


# ---- 汇总入口 -----------------------------------------------------------------


def build_adversarial_cases(arm, val, *, n_joint_speed: int = 60, n_link_sweep: int = 40,
                            n_tcp_arc: int = 50, seed: int = 20260928) -> list[AdversarialCase]:
    """按固定种子生成全部对抗性样本（确定性；oracle 先行核验）。"""
    zones = _Zones.from_validator(val)
    cases: list[AdversarialCase] = []
    cases += _gen_joint_speed(arm, zones, val, np.random.default_rng(seed), n_joint_speed)
    cases += _gen_link_sweep(arm, zones, val, np.random.default_rng(seed + 1), n_link_sweep)
    cases += _gen_tcp_arc(arm, zones, val, np.random.default_rng(seed + 2), n_tcp_arc)
    return cases


def run_adversarial(val, arm, cases: list[AdversarialCase]) -> dict:
    """全部对抗样本过校验器，按预定类别拆开统计（审查 A1"按类别拆开"）。"""
    by_cat: dict[str, dict] = {}
    for case in cases:
        rep = val.check_joint_trajectory(case.times_s, case.q_list, arm,
                                         label=f"adv_{case.category}")
        kinds = {v["kind"] for v in rep["violations"]}
        kind_zone_hits = {
            (v["kind"], v.get("zone")) for v in rep["violations"]
        }
        if case.predicted_zone is None:
            hit = case.predicted_kind in kinds
        else:
            hit = (case.predicted_kind, case.predicted_zone) in kind_zone_hits
        stats = by_cat.setdefault(case.category, {
            "predicted_kind": case.predicted_kind,
            "predicted_zone": case.predicted_zone,
            "n": 0, "rejected": 0, "predicted_kind_hit": 0,
            "kinds_seen": [],
        })
        stats["n"] += 1
        if rep["rejected"]:
            stats["rejected"] += 1
        if hit:
            stats["predicted_kind_hit"] += 1
        for k in sorted(kinds):
            if k not in stats["kinds_seen"]:
                stats["kinds_seen"].append(k)

    total = sum(s["n"] for s in by_cat.values())
    rejected = sum(s["rejected"] for s in by_cat.values())
    hits = sum(s["predicted_kind_hit"] for s in by_cat.values())
    out: dict = {
        "total": total,
        "rejected": rejected,
        "rejection_rate": (rejected / total) if total else 0.0,
        "predicted_kind_hits": hits,
        "predicted_kind_hit_rate": (hits / total) if total else 0.0,
        "by_category": by_cat,
    }
    for s in by_cat.values():
        s["rejection_rate"] = (s["rejected"] / s["n"]) if s["n"] else 0.0
        s["predicted_kind_hit_rate"] = (s["predicted_kind_hit"] / s["n"]) if s["n"] else 0.0
    return out
