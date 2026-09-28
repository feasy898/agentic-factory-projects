"""M6 上下配对：匈牙利算法 + 距离门限 + 单面保留。

spec（plan/开发指令.md §4 M6）：
- 输入 top/bottom 两组 ``BeanObservation``；
- 代价 = 盘面 mm 欧氏距离（观测质心 ``mask.centroid_mm``）；
- 门限 ``gate_mm``（默认 12）：超过门限的候选对不进结果；
- ``scipy.optimize.linear_sum_assignment`` 全局最优求解；
- 只出一面的豆（遮挡/边缘漏检/丢面/伪观测）单独成 ``PairedBean`` 记录并
  标记：``pairing_cost = -1`` 且 ``worst_side`` = 所在面（契约不变式由
  ``PairedBean.from_sides`` 保证，见 beaneye/schemas.py）；
- 输出按锚定观测质心 ``(x, y)`` 排序后编号 ``b0001..``——锚 = top 缺则
  bottom——同输入必同输出（bean_id 稳定可复现）。

实现说明（「置 inf」的等价安全化 + 哑节点 + 整体配准）
----------------------------------------------------
1) **inf 的占位化**：scipy 的 ``linear_sum_assignment`` 在代价含 inf 时要求
   存在避开 inf 的完全匹配，否则抛 ``ValueError("cost matrix is infeasible")``
   （本仓 .venv scipy 1.18.1 实测：两个 top 观测都只落在同一 bottom 的
   门限圈内即触发）。本实现用足够大的有限占位 ``BIG`` 代替 inf，配合下述
   哑节点保证恒可行，语义等价（最优解不会使用 BIG 项）。

2) **「不配对」哑节点**：每条 top 观测配一个哑列、每条 bottom 观测配一个
   哑行，代价 ``lambda = gate_mm + eps``（恰在门限上的对仍严格优于双双
   落单）；哑-哑对角补 0 将矩阵方化。配对规模由全局最优自由决定，落单
   观测走哑节点成单面记录——「单面豆保留」成为一等结果而非被迫成对。

3) **整体配准残差两遍法（标定误差场景）**：上下两面的标定若存在整体
   平移（spec eval 的 5mm 场景），真对距离被系统性拉大、近邻错对反而
   更近，纯逐对距离不可分辨。两遍法：第一遍匈牙利粗配对 → 对成对位移
   ``top质心 - bottom质心`` 取逐分量中位数（对少数错配/伪观测鲁棒）得
   残差 ``mu``；当 ``|mu| >= 1mm`` 且粗配对 ≥8 对时，把 top 坐标平移
   ``-mu`` 后重解（门限语义不变）。**第二遍只有严格变优才替换第一遍**
   （W13 修复）：比较口径 = 在矫正坐标系下重评两解（先比对数、再比总
   距离，见 :func:`_second_pass_wins`）——只要不变优就保留第一遍，防
   「中位数锁错模」的第二遍把本来就对的配对改坏。已知极限：若多数观测
   呈规则点阵且偏移接近点阵间距的整分数，中位数会锁到错误模式（W13
   之前误判「真实随机豆盘不会出现」——密排盘恰恰接近该构型，见
   tests/test_pairing.py 的密排/透视用例）；劣化守卫只能阻止第二遍
   变差，不能修正第一遍已锁错的方向，此局限如实记录。

``pairing_cost`` 语义：返回**配对判定坐标系**下的距离（无配准残差时即
质心原始欧氏距离；有残差时为矫正后距离，两者相差 ≤ |mu|）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from scipy.optimize import linear_sum_assignment

from beaneye.schemas import BeanObservation, PairedBean

DEFAULT_GATE_MM = 12.0
_DUMMY_EPS = 1e-6  # 让「恰在门限上的对」严格优于双双落单
_REG_MIN_PAIRS = 8  # 粗配对少于此数不估配准残差
_REG_MIN_SHIFT_MM = 1.0  # 残差小于此值视作噪声，不触发第二遍

__all__ = [
    "DEFAULT_GATE_MM",
    "PairingConfig",
    "PairingError",
    "PairingSummary",
    "pair_observations",
    "robust_shift_mm",
    "summarize",
]


class PairingError(ValueError):
    """输入观测不符合配对前提（side 不一致 / obs_id 重复 / gate 非法等）。"""


@dataclass(frozen=True)
class PairingConfig:
    """配对参数（v1 仅一个门限；后续如需代价加权只增字段）。"""

    gate_mm: float = DEFAULT_GATE_MM

    def __post_init__(self) -> None:
        if not math.isfinite(self.gate_mm) or self.gate_mm <= 0:
            raise PairingError(f"gate_mm 必须为正有限数，得到 {self.gate_mm!r}")


@dataclass(frozen=True)
class PairingSummary:
    """配对结果统计（M8 计量 / M14 e2e 汇总用）。"""

    n_beans: int
    n_paired: int
    n_top_only: int
    n_bottom_only: int


def _validate_inputs(top: Sequence[BeanObservation], bottom: Sequence[BeanObservation]) -> None:
    for list_name, obs_list, expect_side in (
        ("top", top, "top"),
        ("bottom", bottom, "bottom"),
    ):
        seen: set[str] = set()
        for obs in obs_list:
            if obs.side != expect_side:
                raise PairingError(
                    f"{list_name} 列表收到 side={obs.side!r} 的观测 {obs.obs_id!r}；"
                    f"该列表只接受 side={expect_side!r}"
                )
            if obs.obs_id in seen:
                raise PairingError(f"{list_name} 列表内 obs_id 重复: {obs.obs_id!r}")
            seen.add(obs.obs_id)


def _bean_id(index: int) -> str:
    return f"b{index + 1:04d}"


def robust_shift_mm(displacements: Sequence[tuple[float, float]]) -> tuple[float, float] | None:
    """成对位移样本的鲁棒中心（逐分量中位数）。

    供配准残差估计与测试直接使用；样本不足 4 个返回 ``None``。
    中位数对少数离群位移（错配/伪观测融合）鲁棒。
    """
    if len(displacements) < 4:
        return None
    arr = np.asarray(displacements, dtype=float)
    return float(np.median(arr[:, 0])), float(np.median(arr[:, 1]))


def _second_pass_wins(
    pairs_first: list[tuple[int, int, float]],
    pairs_corrected: list[tuple[int, int, float]],
    txy: np.ndarray,
    bxy: np.ndarray,
    mu: tuple[float, float],
) -> bool:
    """第二遍（矫正坐标系）解是否**严格优于**第一遍解在同一坐标系下的重评。

    比较口径（W13 修复引入的劣化守卫）：把第一遍的配对也放到矫正坐标系
    （top 坐标 - mu）下重算距离，然后按「先比对数（多者优先）、再比总
    距离（小者优先）」的字典序比较；不变优（含完全相等）即返回 False，
    保留第一遍结果。两个解都在同一坐标系下比较，整体平移对二者影响相同，
    不会系统性偏袒任何一方。
    """
    if not pairs_corrected:
        return False
    mu_vec = np.asarray(mu, dtype=float)

    def _key(pairs: list[tuple[int, int, float]], *, corrected: bool) -> tuple[int, float]:
        total = 0.0
        for r, c, d in pairs:
            if corrected:
                total += float(d)  # 第二遍的 d 本就是矫正坐标系距离
            else:
                total += float(np.linalg.norm((txy[r] - mu_vec) - bxy[c]))
        return (len(pairs), -round(total, 9))

    return _key(pairs_corrected, corrected=True) > _key(pairs_first, corrected=False)


def _solve_assignment(
    txy: np.ndarray, bxy: np.ndarray, gate_mm: float
) -> list[tuple[int, int, float]]:
    """哑节点匈牙利：返回门限内的 (top_idx, bottom_idx, 判定坐标系距离)。"""
    n, m = len(txy), len(bxy)
    dist = np.linalg.norm(txy[:, None, :] - bxy[None, :, :], axis=-1)
    lam = gate_mm + _DUMMY_EPS  # 落单代价：略高于门限
    big = lam * (n + m + 1)  # inf 的占位（最优解不会取到）
    size = n + m
    cost = np.full((size, size), big)
    cost[:n, :m] = np.where(dist <= gate_mm, dist, big)
    np.fill_diagonal(cost[:n, m:], lam)  # top_i → 哑列（单面保留）
    np.fill_diagonal(cost[n:, :m], lam)  # bottom_j → 哑行（单面保留）
    cost[n:, m:] = 0.0  # 哑-哑块整体为 0：哑行↔哑列是无意义填充，任意互配免费
    # （哑-哑只在对角置 0 是错的：多余哑行与空闲哑列未必对角对齐——
    #   top 列表位置 ≠ bottom 列表位置——碰撞会逼最优解拆散真对以回避 big）
    rows, cols = linear_sum_assignment(cost)
    return [
        (r, c, float(dist[r, c]))
        for r, c in zip(rows.tolist(), cols.tolist())
        if r < n and c < m and dist[r, c] <= gate_mm  # inf 对不进结果
    ]


def pair_observations(
    top: Sequence[BeanObservation],
    bottom: Sequence[BeanObservation],
    *,
    gate_mm: float = DEFAULT_GATE_MM,
) -> list[PairedBean]:
    """上下两面观测 → 全局最优配对 + 单面保留（M6 主入口）。

    - 代价 = top/bottom 观测质心的盘面 mm 欧氏距离；
    - ``dist <= gate_mm`` 才允许成对（门限含等号：恰在门限上视为可配对）；
    - 两遍法：先粗配对，若成对位移的中位数显示存在整体配准残差
      （≥1mm，标定误差场景），在矫正坐标系重解（见模块 docstring）；
    - 只出一面的豆单独成记录：``pairing_cost=-1``、``worst_side``=所在面；
    - 返回按锚定观测质心 (x, y) 排序的 ``PairedBean`` 列表，bean_id 依排序
      顺序编号 ``b0001..``，同输入同输出。
    """
    cfg = PairingConfig(gate_mm=gate_mm)
    _validate_inputs(top, bottom)

    top_list = list(top)
    bottom_list = list(bottom)

    pairs: list[tuple[int, int, float]] = []
    if top_list and bottom_list:
        txy = np.asarray([o.mask.centroid_mm for o in top_list], dtype=float)
        bxy = np.asarray([o.mask.centroid_mm for o in bottom_list], dtype=float)
        pairs = _solve_assignment(txy, bxy, cfg.gate_mm)

        # ---- 第二遍：整体配准残差矫正（标定误差场景）----
        if len(pairs) >= _REG_MIN_PAIRS:
            mu = robust_shift_mm(
                [
                    (txy[r, 0] - bxy[c, 0], txy[r, 1] - bxy[c, 1])
                    for r, c, _ in pairs
                ]
            )
            if mu is not None and math.hypot(*mu) >= _REG_MIN_SHIFT_MM:
                corrected = _solve_assignment(txy - np.asarray(mu), bxy, cfg.gate_mm)
                # W13 修复：第二遍只有严格变优才替换（劣化守卫，见模块 docstring
                # 与 _second_pass_wins）——原实现「只要有解就覆盖」会把中位数锁
                # 错模后的坏矫正强加给本来就对的配对
                if corrected and _second_pass_wins(pairs, corrected, txy, bxy, mu):
                    pairs = corrected

    matched_top = {r for r, _, _ in pairs}
    matched_bottom = {c for _, c, _ in pairs}

    # ---- 记录集合：成对 + 两侧的单面（遮挡/边缘漏检/伪观测都保留）----
    # 每条记录先挂锚定观测（top 优先，缺则 bottom），排序后统一编号。
    records: list[tuple[tuple[float, float], str, BeanObservation | None, BeanObservation | None, float]] = []
    for r, c, d in pairs:
        anchor = top_list[r]
        records.append((anchor.mask.centroid_mm, anchor.obs_id, top_list[r], bottom_list[c], d))
    for i, obs in enumerate(top_list):
        if i not in matched_top:
            records.append((obs.mask.centroid_mm, obs.obs_id, obs, None, -1.0))
    for i, obs in enumerate(bottom_list):
        if i not in matched_bottom:
            records.append((obs.mask.centroid_mm, obs.obs_id, None, obs, -1.0))

    # ---- bean_id 稳定序：锚定质心 (x, y)，obs_id 兜底打破并列 ----
    records.sort(key=lambda rec: (rec[0][0], rec[0][1], rec[1]))

    return [
        PairedBean.from_sides(_bean_id(i), t, b, pairing_cost=d)
        for i, (_, _, t, b, d) in enumerate(records)
    ]


def summarize(beans: Sequence[PairedBean]) -> PairingSummary:
    """统计成对/单面记录数（单面 = 遮挡、边缘漏检、丢面或伪观测）。"""
    n_paired = sum(1 for b in beans if b.top is not None and b.bottom is not None)
    n_top_only = sum(1 for b in beans if b.top is not None and b.bottom is None)
    n_bottom_only = sum(1 for b in beans if b.top is None and b.bottom is not None)
    return PairingSummary(
        n_beans=len(beans),
        n_paired=n_paired,
        n_top_only=n_top_only,
        n_bottom_only=n_bottom_only,
    )
