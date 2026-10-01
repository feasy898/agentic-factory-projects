"""舀取参数网格搜索（D4 真机逐食物调参的**仿真预扫**，开发指令 §5.9 舀取通过线）。

用途：在真机上做"盲扫"代价高（每食物 50 次 × N 组参数）。本模块在 cs_sim 内
对 :class:`cs_orchestra.runtime.ScriptedScoop` 的五个扫参维度做网格搜索，为
3060 真机给出**初始参数**，压缩盲扫轮次。

五个维度（与 ScriptedScoop 构造参数同名）：入勺深度 ``dip_offset_m`` /
进勺轴倾角 ``tilt_deg`` / 接近速度 ``approach_speed_mps`` / 回撤速度
``retract_speed_mps`` / 刮碗边开关 ``bowl_rim_scrape``。

**结论口径（务必与真机区分）**
------------------------------------------
本模块给出的是**仿真预扫结论，不是真机结论**。两类结论的边界：

1. **运动学/安全面（真）**：每组参数都在 cs_sim 的 ArmModel + EnvelopeValidator
   上实跑——位置 IK、关节限位、禁入区/限速/连杆扫掠/关节角速度
   （``check_joint_trajectory``，与执行层 SafetyEnvelope 同一校验器同口径）。
   推荐参数另跑一遍**执行层真链路**（MockArm + SafetyEnvelope + VirtualClock，
   ArmCommand 逐条下发），记录拒绝原因与余量。
2. **舀取成功率（模型）**：成功率来自"球冠勺碗几何 + 食物流变先验"的解析捕获
   模型（:func:`attempt_outcome`），**不是**物理仿真、更不是实测。食物卡上的
   每个系数都在 config/scoop_params.json 里显式登记并标注 provenance=
   "工程先验（未实测）"。模型排序只与先验同好，真机首轮仍须按 §5.9 复测
   （每食物 50 次，最终 ≥90% / 首次 ≥70%）。

**已知的模型局限（读数前必读）**
------------------------------------------
- **倾角维度不被模型识别**：倾角以"进勺轴相对铅垂线"实现（笛卡尔位置层，
  工具姿态沿程保持），而捕获模型把它当作勺面倾角用于留存判定——两者口径
  不同。留存随倾角单调下降、装载不随倾角增加，故扫描恒定选 tilt=0。**这是
  模型构造的结果，不是"真机应当 0° 倾"的结论**；真机舀取是否需要倾角
  （沿勺口前缘插入再拖出）由 D4 实测回答。
- **入勺深度维度弱识别**：捕获量在 immersion ≥ spoon_bowl_depth_m 时饱和，
  网格内多数取值同为满载，仅靠刮底惩罚与过浅欠载区分。
- **最优组合成功率接近饱和**：在当前先验下最优组合常达 ~1.0。因此报告里的
  成功率**只能用于组间排序**，不能用来预测 §5.9 的 90%/70% 通过线——后者
  只能由真机 50 次实测回答。
- 无"过浸溢流"独立项（过浸部分已由 load_frac 封顶计过，重复计会双重扣分）。

依赖口径：本模块的库函数只依赖 cs_sim（+ 标准库/numpy）；``cs_orchestra`` 的
``ScriptedScoop`` / ``OrchestraParams`` 仅在 CLI 装配处（:func:`main`）注入，
不构成 cs_sim → cs_orchestra 的模块级依赖（保持 §6 重生成依赖图 2→3→8 的方向）。

用法（cwd = chengshao/ 包根）::

    ../.venv/Scripts/python.exe -m cs_sim.scoop_sweep --config config/scoop_params.json \
        --report reports/scoop_sweep.json

分批扫参（先小网格跑通 / 逐食物分批时）::

    ... -m cs_sim.scoop_sweep --max-trials 40 --foods 芋泥 南瓜粥 --report <临时报告>
    # --max-trials 覆盖 config 的 search.trials_per_food（B2 契约每食物 ≤200）；
    # --foods 只扫子集（未扫食物不进本报告）；两者都不改 config 落盘值，
    # --write-config 的回写按网格规模合并旧 recommended，且要求写后全食物覆盖。

退出码：0 = 扫参完成且每食物推荐参数通过运动学/安全面静态复核；
1 = 存在无可行参数的食物或写报告失败。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from .ik_solver import solve_with_restarts
from .scoop_params import (
    FOOD_SET_SOURCE,
    GRID_DIMS,
    MAX_TRIALS_PER_FOOD,
    FoodCard,
    ScoopConfig,
    load_scoop_config,
)

__all__ = [
    "ScoopCombo",
    "iter_combos",
    "RouteSim",
    "attempt_outcome",
    "simulate_food",
    "tilt_retention_fraction",
    "run_sweep",
]

# 执行层时长规划的镜像（公式逐项对应 cs_arm/kinematics.py::plan_motion，
# 本模块不 import cs_arm 以免形成 cs_sim → cs_arm 的反向依赖）：
#   t_joint  = max|Δq| / joint_speed_limit
#   t_linear = arc_len × 1.05 / min(弧上各点限速)，且 ≥ arc_len / max_speed
LINEAR_TIME_SAFETY_FACTOR = 1.05


# ---- 参数组合 -------------------------------------------------------------------

@dataclass(frozen=True)
class ScoopCombo:
    """一组扫参（与 config/scoop_params.json 的 recommended 同构）。"""

    dip_offset_m: float
    tilt_deg: float
    approach_speed_mps: float
    retract_speed_mps: float
    bowl_rim_scrape: bool

    def as_dict(self) -> dict:
        return {
            "dip_offset_m": self.dip_offset_m,
            "tilt_deg": self.tilt_deg,
            "approach_speed_mps": self.approach_speed_mps,
            "retract_speed_mps": self.retract_speed_mps,
            "bowl_rim_scrape": bool(self.bowl_rim_scrape),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ScoopCombo":
        return cls(
            dip_offset_m=float(d["dip_offset_m"]),
            tilt_deg=float(d["tilt_deg"]),
            approach_speed_mps=float(d["approach_speed_mps"]),
            retract_speed_mps=float(d["retract_speed_mps"]),
            bowl_rim_scrape=bool(d["bowl_rim_scrape"]),
        )


def iter_combos(grid) -> list[ScoopCombo]:
    """网格展开（顺序稳定：按 GRID_DIMS 逐维笛卡尔积，后者变化最快）。"""
    v = grid.values
    out: list[ScoopCombo] = []
    for scrape in v["bowl_rim_scrape"]:
        for retract in v["retract_speed_mps"]:
            for approach in v["approach_speed_mps"]:
                for tilt in v["tilt_deg"]:
                    for dip in v["dip_offset_m"]:
                        out.append(ScoopCombo(float(dip), float(tilt), float(approach),
                                              float(retract), bool(scrape)))
    return out


# ---- 球冠勺碗的倾角留存（真实几何，数值积分） -----------------------------------

_TILT_CACHE: dict[tuple[float, float, int], float] = {}


def tilt_retention_fraction(radius_m: float, depth_m: float, tilt_deg: float,
                            samples: int = 26) -> float:
    """勺碗绕 Y 轴倾斜 tilt_deg 后，勺口平面以下仍留在碗内的容积占比。

    球冠球半径 R=(r²+h²)/(2h)、球心 (0,0,h−R)，碗口平面过 z=h、倾斜后法向
    (sinθ,0,cosθ)。对碗内体元做确定性网格积分（无随机性、可复现）。
    """
    key = (round(float(radius_m), 6), round(float(depth_m), 6), round(float(tilt_deg), 4))
    if key in _TILT_CACHE:
        return _TILT_CACHE[key]
    r, h = float(radius_m), float(depth_m)
    theta = math.radians(float(tilt_deg))
    R = (r * r + h * h) / (2.0 * h)
    cz = h - R
    lin = np.linspace(-r, r, samples)
    kept = 0
    total = 0
    for x in lin:
        for y in lin:
            rr = x * x + y * y
            if rr > r * r:
                continue
            z_top = cz + math.sqrt(max(R * R - rr, 0.0))
            if z_top <= cz:
                continue
            zs = np.linspace(cz, z_top, samples)
            total += zs.size
            plane = (zs - h) * math.cos(theta) + x * math.sin(theta)
            kept += int(np.count_nonzero(plane <= 0.0))
    frac = float(kept) / float(total) if total else 0.0
    _TILT_CACHE[key] = frac
    return frac


# ---- 轨迹仿真（IK / 关节限位 / 安全包络；真 cs_sim 口径） -----------------------

class RouteSim:
    """把一条舀取路线按执行层同口径跑一遍（IK + 时长规划 + 包络校验）。

    逐项对应 cs_orchestra.core.RouteFollower：
    - cart 项按 ``step`` 展开为 ≤step 的绝对途经点，逐点位置 IK（姿态保持，
      与 cs_arm.kinematics.resolve_target_joints 的位置分支同口径）；
    - grip 项只改夹爪分量；
    - jtrack_reverse 逆序回放本路线此前写过的关节目标，回放速度按 TCP 增益收严；
    - 每段时长按 plan_motion 公式推（见模块顶部镜像说明）。
    """

    def __init__(self, model, validator, params) -> None:
        self.model = model
        self.validator = validator
        self.params = params
        self.joint_limit = float(validator.config.joint_speed_limit)
        self.backend = model._backend

    # -- 基础动作 ------------------------------------------------------------
    def _fk_point(self, q: np.ndarray) -> np.ndarray:
        return np.asarray(self.model.fk([float(v) for v in q])[0:3], dtype=float)

    def _ik(self, point: np.ndarray, seed: np.ndarray) -> np.ndarray | None:
        lo = np.asarray(self.model.joint_lower, dtype=float)
        hi = np.asarray(self.model.joint_upper, dtype=float)
        seed = np.clip(np.asarray(seed, dtype=float), lo, hi)
        _, rot_cur = self.model.fk_pose([float(v) for v in seed])
        res = solve_with_restarts(self.backend, [float(v) for v in point],
                                  rot_cur, seed=seed, pos_only=True)
        if res is None or not res.converged:
            return None
        return np.clip(np.asarray(res.q, dtype=float), lo, hi)

    def _duration_s(self, q0: np.ndarray, q1: np.ndarray, speed: float) -> float:
        n = 25
        f = np.linspace(0.0, 1.0, n)[:, None]
        qs = q0[None, :] + f * (q1 - q0)[None, :]
        pts = np.asarray([self._fk_point(q) for q in qs], dtype=float)
        arc = float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1)))
        t_joint = float(np.max(np.abs(q1 - q0))) / self.joint_limit
        bound = float(min(self.validator.speed_limit_at(p) for p in pts))
        t_linear = arc * LINEAR_TIME_SAFETY_FACTOR / max(bound, 1e-9)
        t_linear = max(t_linear, arc / max(float(speed), 1e-9))
        return float(max(t_joint, t_linear, 1e-3))

    def _replay_speed(self, q_prev: np.ndarray, q_next: np.ndarray) -> float:
        p0, p1 = self._fk_point(q_prev), self._fk_point(q_next)
        chord = float(np.linalg.norm(p1 - p0))
        dq = float(np.max(np.abs(q_next - q_prev)))
        if dq < 1e-9:
            return 0.5
        limit = float(self.validator.speed_limit_at((p0 + p1) / 2.0))
        return float(min(self.params.jtrack_replay_speed_rad_s,
                         0.8 * limit / max(chord / dq, 1e-6)))

    # -- 整条路线 ------------------------------------------------------------
    def run(self, scoop, bowl_pos, start_point=None, start_q=None) -> dict:
        """跑一条 plan_round 路线，返回 IK/关节限位/包络/余量结论。"""
        lo = np.asarray(self.model.joint_lower, dtype=float)
        hi = np.asarray(self.model.joint_upper, dtype=float)
        items = scoop.plan_round(1, np.asarray(bowl_pos, dtype=float), 1)
        if start_q is None:
            start_point = np.asarray(
                self.params.home_point_m if start_point is None else start_point,
                dtype=float)
            q = self._ik(start_point, np.zeros(len(lo)))
            if q is None:
                return {"ok": False, "reason": "ik_no_solution_home", "stage": "home"}
        else:
            q = np.clip(np.asarray(start_q, dtype=float), lo, hi)

        times = [0.0]
        qs: list[np.ndarray] = [q]
        journal: list[np.ndarray] = []
        stage = "start"
        rejected_reason = None

        for item in items:
            kind = item[0]
            if kind == "cart":
                _, point, speed, step = item
                target = np.asarray(point, dtype=float)
                cur = self._fk_point(q)
                n = max(1, int(math.ceil(float(np.linalg.norm(target - cur))
                                         / max(float(step), 1e-4))))
                stage = f"cart->{np.round(target, 3).tolist()}"
                for k in range(1, n + 1):
                    sp = cur + (target - cur) * (k / n)
                    q1 = self._ik(sp, q)
                    if q1 is None:
                        rejected_reason = "ik_no_solution"
                        break
                    times.append(times[-1] + self._duration_s(q, q1, speed))
                    qs.append(q1)
                    journal.append(q1)
                    q = q1
            elif kind == "grip":
                _, value, _speed = item
                qg = q.copy()
                qg[-1] = float(value)
                times.append(times[-1] + self._duration_s(q, qg, 1.5))
                qs.append(qg)
                journal.append(qg)
                q = qg
            elif kind == "jtrack_reverse":
                _, _speed = item
                track = [j.copy() for j in reversed(journal)]
                stage = "jtrack_reverse"
                for qt in track:
                    times.append(times[-1] + self._duration_s(q, qt,
                                                             self._replay_speed(q, qt)))
                    qs.append(qt)
                    q = qt
            else:  # pragma: no cover - plan_round 不会产出其他类型
                raise ValueError(f"未知路线项 {kind!r}")
            if rejected_reason is not None:
                break

        if rejected_reason is not None:
            return {"ok": False, "reason": rejected_reason, "stage": stage}

        q_arr = np.asarray(qs, dtype=float)
        in_limits = bool(np.all(q_arr >= lo - 1e-9) and np.all(q_arr <= hi + 1e-9))
        rep = self.validator.check_joint_trajectory(
            [float(t) for t in times], [[float(v) for v in qq] for qq in qs],
            self.model, label="scoop_route")
        rot_drift = self._tool_orientation_drift_deg(qs)
        return {
            "ok": not rep["rejected"] and in_limits,
            "reason": ("joint_limits" if not in_limits else
                       (rep["violations"][0]["kind"] if rep["violations"] else None)),
            "stage": stage,
            "violations": [dict(v) for v in rep["violations"]][:4],
            "n_points": int(len(times)),
            "duration_s": float(times[-1] - times[0]),
            "min_zone_clearance_m": float(rep["min_zone_clearance_m"]),
            "min_link_clearance_m": float(rep["min_link_clearance_m"]),
            "max_joint_speed_rad_s": float(rep["max_joint_speed_rad_s"]),
            "max_speed_mps": float(rep["max_speed_mps"]),
            "joint_speed_limit_rad_s": self.joint_limit,
            "joints_in_limits": in_limits,
            "tool_orientation_drift_deg": rot_drift,
        }

    def _tool_orientation_drift_deg(self, qs: Sequence[np.ndarray]) -> float:
        """悬停点与入勺点的工具姿态夹角（倾角实现口径的实测漂移量，度）。"""
        if len(qs) < 4:
            return 0.0
        rots = []
        for qq in (qs[0], qs[-1]):
            _, rot = self.model.fk_pose([float(v) for v in qq])
            rots.append(np.asarray(rot, dtype=float))
        cos = float((np.trace(rots[0].T @ rots[1]) - 1.0) / 2.0)
        return float(math.degrees(math.acos(max(-1.0, min(1.0, cos)))))


# ---- 捕获模型（解析模型 + 逐食物先验；非物理仿真、非实测） ---------------------

@dataclass(frozen=True)
class AttemptResult:
    has_food: bool
    load_ml: float
    retained_ml: float
    immersion_m: float
    wall_strike: bool
    floor_strike: bool


def attempt_outcome(combo: ScoopCombo, card: FoodCard, geom, *,
                    surface_jitter_m: float, lateral_m: float,
                    bowl_dy_m: float = 0.0,
                    floor_clearance_min_m: float = 0.002,
                    hsv_detectable: bool | None = None) -> AttemptResult:
    """单次入勺尝试的模型结论。

    几何部分（真实计算）：液面下行程、球冠装载率、倾角留存占比。
    先验部分（config 内登记、未实测）：``fill_factor`` / ``push_speed_mps`` /
    ``tilt_knee_deg``-``tilt_fail_deg`` 内聚带 / ``retention_speed_mps`` /
    ``scrape_extra_ml``。
    """
    cap_ml = geom.spoon_capacity_ml()
    detect = card.hsv_detectable if hsv_detectable is None else bool(hsv_detectable)

    # 勺碗最低点相对 bowls_m 参考面的高度与液面下浸没深度（几何）
    tip_h = combo.dip_offset_m - geom.spoon_tip_drop_m
    floor_strike = tip_h < floor_clearance_min_m
    food_surface = geom.food_fill_depth_m + surface_jitter_m
    immersion = food_surface - tip_h
    if immersion <= 0.0:
        return AttemptResult(False, 0.0, 0.0, immersion, False, floor_strike)

    # 贴壁：横向进勺偏移使勺碗越过碗内壁可用余量 -> 沿壁上滑，本轮无收获
    lateral = abs(float(lateral_m) + float(bowl_dy_m))
    wall_strike = lateral > (geom.bowl_interior_radius_m - geom.spoon_bowl_radius_m)
    if wall_strike:
        return AttemptResult(False, 0.0, 0.0, immersion, True, floor_strike)

    cos_t = max(math.cos(math.radians(combo.tilt_deg)), 1e-6)
    load_frac = min(1.0, immersion / max(geom.spoon_bowl_depth_m, 1e-6))
    load = cap_ml * load_frac * card.fill_factor
    if floor_strike:
        load *= 0.35  # 刮底：装载效率显著下降（先验，见 config provenance）
    if combo.approach_speed_mps > card.push_speed_mps:
        load *= card.push_speed_mps / combo.approach_speed_mps  # 进勺过快把食物推开
    if combo.bowl_rim_scrape:
        load = min(cap_ml, load + card.scrape_extra_ml)

    # 抬勺留存：几何（勺口平面以下）+ 内聚（先验 knee/fail）+ 回撤甩出
    geo = tilt_retention_fraction(geom.spoon_bowl_radius_m, geom.spoon_bowl_depth_m,
                                  combo.tilt_deg)
    if combo.tilt_deg <= card.tilt_knee_deg:
        cohesion = 1.0
    elif combo.tilt_deg >= card.tilt_fail_deg:
        cohesion = 0.0
    else:
        span = max(card.tilt_fail_deg - card.tilt_knee_deg, 1e-6)
        cohesion = 1.0 - (combo.tilt_deg - card.tilt_knee_deg) / span
    # 动态甩出：抬勺速度相对该食物的留持速度上限（先验 retention_speed_mps）。
    # 注：过浸（immersion > spoon_bowl_depth_m）的部分已由 load_frac 封顶，
    # 不再另设溢流项——旧实现用 `tilt_knee_deg*0.001`（度×1mm）与 immersion
    # （米）相比，量纲不一致且与 load_frac 重复扣分，会把所有稀薄食物组合
    # 一律判失败（见 module docstring "已知的模型局限"）。
    spill = min(0.999, (combo.retract_speed_mps / card.retention_speed_mps) ** 2)
    retained = load * geo * cohesion * (1.0 - spill)
    has_food = bool(detect and retained / cap_ml >= geom.detect_fill_ratio())
    return AttemptResult(has_food, float(load), float(retained), float(immersion),
                         False, floor_strike)


def simulate_food(cfg: ScoopConfig, card: FoodCard, combo: ScoopCombo, *,
                  trials: int, max_attempts: int, seed: int,
                  hsv_detectable: bool | None = None) -> dict:
    """单食物 × 单参数组合的闭环蒙特卡洛（勺检不过 -> 重舀，最多 max_attempts 轮）。

    噪声口径（config 登记）：食物液面抖动（每次尝试重抽）、进勺横向误差
    （均匀分布；首轮全幅，重舀轮先扣掉腕部相机可重瞄的上限
    ``search.entry_lateral_correction_m``，再按 ``closed_loop_gain`` 收缩）、
    碗位放置误差（每次试验固定一次）。
    """
    geom = cfg.geometry
    correction = float(cfg.search.get("entry_lateral_correction_m", 0.0))
    rng = np.random.default_rng(seed)
    first_ok = 0
    final_ok = 0
    attempts_used: list[int] = []
    empty_checks = 0
    wall_strikes = 0
    floor_strikes = 0
    retained_sum = 0.0
    for _ in range(int(trials)):
        bowl_dy = float(rng.normal(0.0, card.bowl_place_error_m))
        ok = False
        used = 0
        for attempt in range(int(max_attempts)):
            gain = 1.0 if attempt == 0 else card.closed_loop_gain ** attempt
            jitter = float(rng.normal(0.0, card.surface_jitter_m))
            lateral = float(rng.uniform(-card.entry_lateral_error_m,
                                       card.entry_lateral_error_m))
            if attempt > 0:  # 腕部相机闭环：先按重瞄上限修正，再按增益收缩
                lateral -= math.copysign(min(abs(lateral), correction), lateral)
                lateral *= gain
            res = attempt_outcome(combo, card, geom, surface_jitter_m=jitter,
                                  lateral_m=lateral, bowl_dy_m=bowl_dy,
                                  hsv_detectable=hsv_detectable)
            used = attempt + 1
            if res.wall_strike:
                wall_strikes += 1
            if res.floor_strike:
                floor_strikes += 1
            if res.has_food:
                ok = True
                if attempt == 0:
                    first_ok += 1
                retained_sum += res.retained_ml
                break
            empty_checks += 1
        attempts_used.append(used)
        if ok:
            final_ok += 1
    n = float(max(trials, 1))
    return {
        "trials": int(trials),
        "max_attempts": int(max_attempts),
        "first_attempt_rate": first_ok / n,
        "final_success_rate": final_ok / n,
        "mean_attempts_per_trial": float(np.mean(attempts_used)) if attempts_used else 0.0,
        "empty_spoon_checks": int(empty_checks),
        "wall_strikes": int(wall_strikes),
        "floor_strikes": int(floor_strikes),
        "mean_retained_ml_when_ok": (retained_sum / final_ok) if final_ok else 0.0,
    }


# ---- 扫参主流程 -----------------------------------------------------------------

def _stable_seed_offset(*parts: str) -> int:
    """按 (食物, 变体) 生成**跨进程稳定**的种子偏移（0..9999）。

    不用内置 ``hash()``——CPython 对 str 的 hash 按进程随机化（PYTHONHASHSEED），
    会让同一配置两次运行的蒙特卡洛数字对不上，报告不可复现。
    """
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % 10_000


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """二项比例 Wilson 区间（50 次试验下 ±~7% —— 真机复测前不要当结论用）。"""
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    d = 1.0 + z * z / n
    c = p + z * z / (2 * n)
    s = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - s) / d), min(1.0, (c + s) / d))


def _score(row: dict) -> tuple:
    """排序键：最终成功率 -> 首次成功率 -> 运动学可行 -> 更快（回撤速度大者优先）。

    最后一项按"回撤速度大"排序是刻意偏向作业节拍：同等成功率下取更快的组合，
    由真机复测兜底（§5.9）。
    """
    return (row["final_success_rate"], row["first_attempt_rate"],
            1 if row["feasible"] else 0, row["combo"]["retract_speed_mps"])


def run_sweep(cfg: ScoopConfig, *, model, validator, params, make_scoop,
              bowls: Iterable[np.ndarray], report_cmd: str,
              progress=None) -> dict:
    """网格搜索主流程（运动学可行性与捕获模型分开记录，不混算）。"""
    t_start = time.time()
    sim = RouteSim(model, validator, params)
    bowls = [np.asarray(b, dtype=float) for b in bowls]
    combos = iter_combos(cfg.grid)

    # 1) 运动学/安全面：逐组合逐碗实跑（与推荐食物无关，只跑一次复用）
    feas: list[dict] = []
    for i, combo in enumerate(combos):
        scoop = make_scoop(combo)
        worst = None
        for bowl in bowls:
            res = sim.run(scoop, bowl)
            if worst is None or (not res["ok"]) and worst["ok"]:
                worst = res
            if not res["ok"]:
                break
        ok = bool(worst and worst["ok"])
        feas.append({
            "combo": combo.as_dict(),
            "feasible": ok,
            "min_zone_clearance_m": (worst or {}).get("min_zone_clearance_m"),
            "max_joint_speed_rad_s": (worst or {}).get("max_joint_speed_rad_s"),
            "tool_orientation_drift_deg": (worst or {}).get("tool_orientation_drift_deg"),
            "route_duration_s": (worst or {}).get("duration_s"),
            "reject_reason": None if ok else (worst or {}).get("reason"),
        })
        if progress is not None:
            progress("feasibility", i + 1, len(combos))

    by_key = {json.dumps(r["combo"], sort_keys=True): r for r in feas}

    # 2) 捕获模型：逐食物逐可行组合跑蒙特卡洛
    per_food: dict[str, dict] = {}
    for name, card in cfg.foods.items():
        t_food = time.time()
        rows: list[dict] = []
        variants = [("as_configured", None)]
        if not card.hsv_detectable:
            variants.append(("counterfactual_hsv_extended", True))
        for variant, override in variants:
            for combo in combos:
                f = by_key[json.dumps(combo.as_dict(), sort_keys=True)]
                simres = simulate_food(
                    cfg, card, combo,
                    trials=cfg.search["trials_per_food"],
                    max_attempts=cfg.search["max_attempts"],
                    seed=cfg.search["seed"] + _stable_seed_offset(name, variant),
                    hsv_detectable=override)
                rows.append({"variant": variant, "combo": combo.as_dict(),
                             "feasible": f["feasible"], **simres})
        rows.sort(key=_score, reverse=True)
        top = rows[0]
        best = top["combo"]
        lo, hi = _wilson(int(round(top["final_success_rate"] * top["trials"])),
                         top["trials"])
        per_food[name] = {
            "rheology": card.rheology,
            "hsv_detectable": card.hsv_detectable,
            "variant_selected": top["variant"],
            "recommended": {
                **best,
                "sim_first_attempt_rate": round(top["first_attempt_rate"], 4),
                "sim_final_success_rate": round(top["final_success_rate"], 4),
                "sim_trials": top["trials"],
                "sim_attempts_per_trial": cfg.search["max_attempts"],
                "source_report": "reports/scoop_sweep.json",
                # 去重计数：不可检出的食物会多跑一个反事实变体，rows 重复同一组合
                "feasible_combos": len({json.dumps(r["combo"], sort_keys=True)
                                        for r in rows if r["feasible"]}),
                "grid_size": len(combos),
            },
            "final_success_wilson95": [round(lo, 4), round(hi, 4)],
            "top5": [
                {"variant": r["variant"], **r["combo"],
                 "sim_first_attempt_rate": round(r["first_attempt_rate"], 4),
                 "sim_final_success_rate": round(r["final_success_rate"], 4),
                 "feasible": r["feasible"]}
                for r in rows[:5]
            ],
            "n_rows": len(rows),
            "sweep_seconds": round(time.time() - t_food, 2),
        }
        if progress is not None:
            progress(f"capture:{name}", len(combos), len(combos))

    elapsed = time.time() - t_start
    n_feasible = sum(1 for r in feas if r["feasible"])
    all_ok = all(f["recommended"]["sim_final_success_rate"] >= 0.9
                 or not f["hsv_detectable"] for f in per_food.values())
    return {
        "per_food": per_food,
        "feasibility": feas,
        "grid_size": len(combos),
        "n_feasible": n_feasible,
        "elapsed_s": round(elapsed, 2),
        "sim_scoop_retries_max": int(params.scoop_retries_max),
        "acceptance_preview_ok": bool(all_ok),
        "report_cmd": report_cmd,
    }


# ---- 报告 / 配置写回 ------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    """CLI：扫参 -> 写 config/scoop_params.json 的 recommended 段 + 报告 JSON。"""
    ap = argparse.ArgumentParser(description="舀取参数网格搜索（仿真预扫）")
    ap.add_argument("--config", default="config/scoop_params.json")
    ap.add_argument("--report", default="reports/scoop_sweep.json")
    ap.add_argument("--model", default="auto", help="cs_sim 模型回退链入口")
    ap.add_argument("--max-trials", type=int, default=None, metavar="N",
                    help="覆盖 config 的 search.trials_per_food（分批扫参用；"
                         "1..%d，B2 契约每食物 ≤200）" % MAX_TRIALS_PER_FOOD)
    ap.add_argument("--foods", nargs="+", default=None, metavar="NAME",
                    help="只扫指定食物（分批扫参用；必须是 config foods 子集，"
                         "未扫食物不进本报告，--write-config 时要求推荐段最终全覆盖）")
    ap.add_argument("--write-config", action="store_true",
                    help="把推荐参数写回配置文件（默认只落报告）")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    pkg_root = Path(__file__).resolve().parents[1]
    cfg_path = Path(args.config)
    if not cfg_path.is_absolute():
        cfg_path = pkg_root / cfg_path
    report_path = Path(args.report)
    if not report_path.is_absolute():
        report_path = pkg_root / report_path

    # cs_orchestra 只在 CLI 装配处引入（模块级不依赖，见模块 docstring）
    from cs_orchestra.core import OrchestraParams  # type: ignore[import-not-found]
    from cs_orchestra.runtime import ScriptedScoop  # type: ignore[import-not-found]
    from cs_schema.constants import DEFAULT_DISH_REGISTRY  # type: ignore[import-not-found]

    from .arm_model import load_arm
    from .safety_envelope import EnvelopeValidator

    cfg_obj = load_scoop_config(cfg_path, allowed_foods=DEFAULT_DISH_REGISTRY)
    # 分批扫参覆盖（先于任何使用）：--max-trials 覆盖试验数；--foods 收窄食物子集
    all_config_foods = list(cfg_obj.foods)
    if args.max_trials is not None:
        if not (1 <= args.max_trials <= MAX_TRIALS_PER_FOOD):
            ap.error(f"--max-trials 必须在 1..{MAX_TRIALS_PER_FOOD}"
                     f"（得到 {args.max_trials}）")
        cfg_obj.search["trials_per_food"] = int(args.max_trials)
    if args.foods is not None:
        unknown = [f for f in args.foods if f not in cfg_obj.foods]
        if unknown:
            ap.error(f"--foods 含未声明食物 {unknown}；可选集合 {all_config_foods}")
        cfg_obj = replace(
            cfg_obj, foods={f: cfg_obj.foods[f] for f in dict.fromkeys(args.foods)})
    params = OrchestraParams.load()
    model = load_arm(args.model)
    validator = EnvelopeValidator()
    tier = getattr(model, "tier", "unknown")

    def make_scoop(combo: ScoopCombo):
        return ScriptedScoop(params, **combo.as_dict())

    def progress(stage, i, n):
        if not args.quiet:
            print(f"  [{stage}] {i}/{n}", flush=True)

    cmd = (f"python -m cs_sim.scoop_sweep --config {cfg_path.name} "
           f"--report {report_path.name} --model {args.model}"
           + (" --write-config" if args.write_config else ""))
    if not args.quiet:
        print(f"cs_sim.scoop_sweep: grid={cfg_obj.grid.size()} "
              f"trials/food={cfg_obj.search['trials_per_food']} foods={len(cfg_obj.foods)}",
              flush=True)
    sweep = run_sweep(cfg_obj, model=model, validator=validator, params=params,
                      make_scoop=make_scoop, bowls=params.bowls_m(),
                      report_cmd=cmd, progress=progress)

    # 推荐参数的运动学静态复核（运动学/安全面；含入勺抖动四角）
    static = _static_recheck(cfg_obj, sweep, model, validator, params, make_scoop)
    exec_layer = _exec_layer_recheck(cfg_obj, sweep, params, make_scoop, model, validator)

    report = {
        "module": "cs_sim.scoop_sweep",
        "date": date.today().isoformat(),
        "cmd": cmd,
        "metrics": {
            "grid_size": sweep["grid_size"],
            "grid_dims": list(GRID_DIMS),
            "grid_values_per_dim": {k: len(v) for k, v in cfg_obj.grid.values.items()},
            "combos_kinematically_feasible": sweep["n_feasible"],
            "combos_total": sweep["grid_size"],
            "trials_per_food": cfg_obj.search["trials_per_food"],
            "max_attempts_per_trial": cfg_obj.search["max_attempts"],
            "scoop_retries_max": sweep["sim_scoop_retries_max"],
            "foods": {name: {
                "rheology": f["rheology"],
                "hsv_detectable": f["hsv_detectable"],
                "variant_selected": f["variant_selected"],
                "recommended": f["recommended"],
                "final_success_wilson95": f["final_success_wilson95"],
                "top5": f["top5"],
                "sweep_seconds": f["sweep_seconds"],
            } for name, f in sweep["per_food"].items()},
            "static_recheck": static,
            "exec_layer_recheck": exec_layer,
            "elapsed_s": sweep["elapsed_s"],
        },
        "thresholds": {
            "dev_instruction_5_9_scoop": {
                "trials_per_food": 50,
                "final_success_rate_min": 0.90,
                "first_attempt_rate_min": 0.70,
                "scope": "真机 3060 硬件实测；本报告未测，不得据此宣称达标",
            },
            "sim_pre_sweep": {
                "grid_values_per_dim_max": 3,
                "trials_per_food_max": 500,
                "recommended_must_be_kinematically_feasible": True,
                "recommended_must_pass_static_envelope": True,
            },
        },
        "evidence_kind": "simulation_pre_sweep",
        "real_machine_measured": False,
        "success_rate_kind": "analytic_capture_model",
        "model_provenance": {
            "kinematics_and_envelope": "真跑 cs_sim（ArmModel FK/IK + EnvelopeValidator"
                                       ".check_joint_trajectory，与执行层 SafetyEnvelope"
                                       "同一校验器）",
            "capture_model": "球冠勺碗几何（球冠容积/倾角留存积分/液面下行程）"
                             "+ config/scoop_params.json 登记的逐食物流变先验；"
                             "系数未实测（D4 需实测覆盖）",
            "tilt_mapping": "倾角以进勺轴（悬停前一点->入勺点连线）相对铅垂线的"
                            "夹角实现（笛卡尔位置层，姿态保持）；与勺面相对液面"
                            "真实夹角的映射待真机实测",
        },
        "calibration_gaps": [
            "spoon_tip_drop_m（TCP->勺碗最低点）与 food_fill_depth_m（液面相对 "
            "bowls_m 参考面高度）均为假设值；D4 装臂后实测覆盖，推荐入勺深度随之"
            "同向平移",
            "进勺轴倾角与勺面倾角的映射未标定（工具姿态沿程保持，见 model_provenance）",
            "逐食物流变系数（fill_factor/push_speed_mps/tilt_knee_deg/"
            "retention_speed_mps/scrape_extra_ml）为工程先验",
            "碗内食物初始液面与碗位放置误差为模型噪声项，未在真机标定",
        ],
        "pass": bool(
            sweep["acceptance_preview_ok"]
            and all(s["ok"] for s in static["per_food"].values())
            and exec_layer["all_ok"]
        ),
        "pass_meaning": "扫参完成且每食物推荐参数通过运动学/关节限位/安全包络静态复核；"
                        "**不代表**开发指令 §5.9 的舀取成功率通过线达标（那需要真机实测）",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    if not args.quiet:
        print(f"report -> {report_path}")
    if args.write_config:
        _write_recommended(cfg_path, cfg_obj, sweep, all_food_names=all_config_foods)
        if not args.quiet:
            print(f"config -> {cfg_path}")
    return 0 if report["pass"] else 1


def _static_recheck(cfg_obj, sweep, model, validator, params, make_scoop) -> dict:
    """推荐参数的运动学/安全面静态复核：三个碗位 ×（名义 + 抖动四角）。"""
    sim = RouteSim(model, validator, params)
    corners = [(0.0, 0.0), (0.01, 0.0), (-0.01, 0.0), (0.0, 0.01), (0.0, -0.01)]
    out: dict[str, dict] = {}
    for name, f in sweep["per_food"].items():
        scoop = make_scoop(ScoopCombo.from_dict(f["recommended"]))
        runs: list[dict] = []
        for bowl in params.bowls_m():
            for dy, dz in corners:
                res = sim.run(scoop, np.asarray(bowl, dtype=float) + [0.0, dy, dz])
                runs.append(res)
        ok = all(r["ok"] for r in runs)
        out[name] = {
            "ok": ok,
            "runs": len(runs),
            "reject_reasons": sorted({str(r.get("reason")) for r in runs if not r["ok"]}),
            "min_zone_clearance_m": round(min(r["min_zone_clearance_m"] for r in runs), 4),
            "min_link_clearance_m": round(min(r["min_link_clearance_m"] for r in runs), 4),
            "max_joint_speed_rad_s": round(max(r["max_joint_speed_rad_s"] for r in runs), 4),
            "joint_speed_limit_rad_s": runs[0]["joint_speed_limit_rad_s"],
            "max_tool_orientation_drift_deg": round(
                max(r["tool_orientation_drift_deg"] for r in runs), 3),
        }
    return {"per_food": out, "jitter_corners_m": list(corners),
            "note": "入勺抖动 ±1cm（腕部闭环修正量级，取自 mock.MockScoop.plan_round）"}


def _exec_layer_recheck(cfg_obj, sweep, params, make_scoop, model, validator) -> dict:
    """推荐参数经**执行层真链路**复核：MockArm + SafetyEnvelope + VirtualClock。

    逐条 ArmCommand 下发（cart/grip/joints 与 RouteFollower 同源的改写路径），
    记录拒绝原因、包络判定与仿真时长。这是"真机同款下发路径"的静态验证，
    不含物理执行（MockArm 为虚拟执行器，无硬件）。
    """
    try:
        from cs_arm import (  # type: ignore[import-not-found]
            ArmCommandRejected,
            MockArm,
            SafetyEnvelope,
            VirtualClock,
        )
        from cs_schema import ArmCommand, CommandMode  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - 装配缺件时如实降级
        return {"all_ok": False, "skipped": True, "reason": f"import_failed: {exc}"}

    n_joints = int(model.n_joints)

    def _run(cmd: ArmCommand) -> None:
        env.write(cmd)
        while mock.in_motion:
            clock.advance_s(params.tick_s)
            env.read()

    out: dict[str, dict] = {}
    for name, f in sweep["per_food"].items():
        scoop = make_scoop(ScoopCombo.from_dict(f["recommended"]))
        clock = VirtualClock()
        mock = MockArm(model, clock=clock, validator=validator)
        env = SafetyEnvelope(mock, model=model, validator=validator, clock=clock)
        env.enable()
        res = solve_with_restarts(model._backend, list(params.home_point_m),
                                  np.eye(3), seed=np.zeros(n_joints), pos_only=True)
        if res is None or not res.converged:
            out[name] = {"ok": False, "reason": "home_ik_no_solution"}
            continue
        mock.teleport(np.clip(res.q, model.joint_lower, model.joint_upper))
        rejected: list[str] = []
        written = 0
        journal: list[np.ndarray] = []
        bowl = np.asarray(params.bowls_m()[0], dtype=float)
        for item in scoop.plan_round(1, bowl, 1):
            kind = item[0]
            if rejected:
                break
            try:
                if kind == "cart":
                    _, point, speed, step = item
                    target = np.asarray(point, dtype=float)
                    pos0 = np.asarray(env.read().ee_pos, dtype=float)
                    n = max(1, int(math.ceil(float(np.linalg.norm(target - pos0))
                                             / max(float(step), 1e-4))))
                    for k in range(1, n + 1):
                        sp = pos0 + (target - pos0) * (k / n)
                        _run(ArmCommand(
                            mode=CommandMode.CARTESIAN,
                            target=[float(v) for v in sp],
                            max_speed=float(speed),
                            timeout_s=float(params.cmd_timeout_s)))
                        written += 1
                        journal.append(np.asarray(env.read().joint_pos, dtype=float))
                elif kind == "grip":
                    _, value, _s = item
                    q_cur = np.asarray(env.read().joint_pos, dtype=float).copy()
                    q_cur[-1] = float(value)
                    _run(ArmCommand(mode=CommandMode.JOINTS,
                                    target=[float(v) for v in q_cur],
                                    max_speed=1.0,
                                    timeout_s=float(params.cmd_timeout_s)))
                    written += 1
                    journal.append(q_cur)
                elif kind == "jtrack_reverse":
                    for qt in reversed(journal):
                        _run(ArmCommand(mode=CommandMode.JOINTS,
                                        target=[float(v) for v in qt],
                                        max_speed=0.5,
                                        timeout_s=float(params.cmd_timeout_s)))
                        written += 1
                else:  # pragma: no cover
                    raise ValueError(f"未知路线项 {kind!r}")
            except ArmCommandRejected as exc:
                rejected.append(exc.reason)
        state = env.safety_state()
        out[name] = {"ok": not rejected, "commands_written": written,
                     "rejected": rejected, "sim_seconds": round(clock.s, 3),
                     "envelope_stats": {k: v for k, v in env.stats.items()
                                        if k != "rejected_by_reason"},
                     "safety_state": {
                         "clear_to_move": bool(state.clear_to_move),
                         "estop_latched": bool(state.estop_latched),
                         "violation": str(state.violation)}}
    return {"all_ok": all(v.get("ok") for v in out.values()), "per_food": out,
            "note": "执行层真链路（MockArm 虚拟执行 + SafetyEnvelope 包络硬闸），"
                    "非物理执行、非真机"}


def _write_recommended(cfg_path: Path, cfg_obj: ScoopConfig, sweep: dict,
                       all_food_names: Sequence[str] | None = None) -> None:
    """把推荐参数写回配置文件（只动 recommended 段，其余原样保留）。

    分批扫参（--foods）场景与既有 recommended **合并**：网格已改（grid_size 与
    当前网格不一致）的旧条目视为过期丢弃；合并后若仍有食物缺推荐条目则拒绝
    写盘（ValueError，fail-closed）——避免落一个装载不过的半覆盖配置。
    """
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    grid_size = int(cfg_obj.grid.size())
    rec: dict[str, dict] = {
        k: dict(v) for k, v in (data.get("recommended") or {}).items()
        if isinstance(v, dict) and int(v.get("grid_size", -1)) == grid_size
    }
    for name, f in sweep["per_food"].items():
        r = dict(f["recommended"])
        rec[name] = {
            "dip_offset_m": r["dip_offset_m"],
            "tilt_deg": r["tilt_deg"],
            "approach_speed_mps": r["approach_speed_mps"],
            "retract_speed_mps": r["retract_speed_mps"],
            "bowl_rim_scrape": r["bowl_rim_scrape"],
            "sim_first_attempt_rate": round(float(r["sim_first_attempt_rate"]), 4),
            "sim_final_success_rate": round(float(r["sim_final_success_rate"]), 4),
            "sim_trials": int(r["sim_trials"]),
            "sim_attempts_per_trial": int(r["sim_attempts_per_trial"]),
            "source_report": r["source_report"],
            "feasible_combos": int(r["feasible_combos"]),
            "grid_size": int(r["grid_size"]),
        }
    missing = sorted(set(all_food_names or ()) - set(rec))
    if missing:
        raise ValueError(
            f"scoop_params.recommended 写回后仍缺少食物 {missing}"
            f"（分批扫参须先扫齐全部食物再 --write-config）")
    data["recommended"] = rec
    cfg_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
