"""blueprint —— 诊断卷蓝图生成器（重生成实例，依 specs/frozen/blueprint.spec.md）。

纯规划：输入目标知识点集合 + 预算题数 + 认知维度配比，输出 Blueprint
（每个目标知识点各维度题数、维度合计、(kp × 维度) 细目）。不查题库、不选题。

行为契约：最大余数法维度配额（fsum 精确求和语义、精确 float 并列按规范维度序
破缺）、覆盖约束（预算足够时每个目标 ≥1 题，不足则校验期拒绝）、同输入同输出
（含输入顺序无关）。只依赖标准库；graph 按鸭子类型消费（仅 has()）。
"""
import math
from dataclasses import dataclass

__all__ = [
    "Blueprint",
    "BlueprintError",
    "DEFAULT_RATIOS",
    "DIFFICULTY_TARGET",
    "DIMENSIONS",
    "build_blueprint",
]

DIMENSIONS = ("记忆", "理解", "应用")  # 规范维度序：一切并列破缺与输出序的基准
DEFAULT_RATIOS = {"记忆": 0.4, "理解": 0.4, "应用": 0.2}  # TIMSS 8 年级 40/40/20
DIFFICULTY_TARGET = {"记忆": 0.2, "理解": 0.5, "应用": 0.8}  # 维度 -> 难度目标

_DIM_INDEX = {d: i for i, d in enumerate(DIMENSIONS)}


class BlueprintError(ValueError):
    """build_blueprint 的 V1–V4 校验失败（异常类型即契约，不依赖消息文本）。"""


@dataclass
class Blueprint:
    """诊断卷蓝图。四个容器字段全部为构造期新建（无别名条款，规格 §3.2）。"""

    targets: list[str]  # 排序去重后的目标知识点 id（升序）
    budget: int  # 预算题数 N
    ratios: dict[str, float]  # 生效配比：规范维度序、仅正配比维度、已归一化
    allocation: dict[str, dict[str, int]]  # kp -> {维度: n}；仅含正数格，内层键规范序
    dimension_totals: dict[str, int]  # 维度 -> 合计；仅正配比维度，值可为 0（§3.6）

    def counts(self) -> dict[str, int]:
        """{kp: 该 kp 各维度合计}；键 = targets 升序；合计恰为 budget；每次新 dict。"""
        out: dict[str, int] = {}
        for kp in self.targets:
            cells = self.allocation.get(kp, {})
            total = 0
            for n in cells.values():
                total += n
            out[kp] = total
        return out

    def per_dimension(self) -> list[tuple[str, dict[str, int], float]]:
        """按规范维度序、仅合计 >= 1 的维度：(维度, {kp: 题数}, 难度目标)。

        各维 sub-dict 划分 counts()（正数格语义，缺键按 0）；sub-dict 为新 dict。
        """
        per: list[tuple[str, dict[str, int], float]] = []
        for d in DIMENSIONS:
            if self.dimension_totals.get(d, 0) < 1:
                continue
            sub: dict[str, int] = {}
            for kp in self.targets:
                n = self.allocation.get(kp, {}).get(d, 0)
                if n > 0:
                    sub[kp] = n
            per.append((d, sub, DIFFICULTY_TARGET[d]))
        return per


def build_blueprint(targets, budget, graph, ratios=None) -> Blueprint:
    """从 (目标知识点集合, 预算, 图, 配比) 确定性生成蓝图；校验失败抛 BlueprintError。"""
    # ---------- V1 targets（先于一切计算） ----------
    if isinstance(targets, str):
        raise BlueprintError("targets 不能是裸 str（字符串按字符迭代是调用方错误）")
    try:
        materialized = list(targets)
    except TypeError:
        raise BlueprintError("targets 不可迭代") from None
    ordered: list[str] = []
    seen: set[str] = set()
    for elem in materialized:
        if not isinstance(elem, str) or not elem:  # 元素校验先于去重
            raise BlueprintError("targets 元素必须是非空 str")
        if elem not in seen:
            seen.add(elem)
            ordered.append(elem)
    ordered.sort()  # 码点序升序
    if not ordered:
        raise BlueprintError("targets 去重后为空")

    # ---------- V2 budget ----------
    if isinstance(budget, bool) or not isinstance(budget, int):
        raise BlueprintError("budget 必须是非 bool 的 int")
    if budget < len(ordered):
        raise BlueprintError("budget 小于去重目标数，覆盖不可能")

    # ---------- V3 ratios ----------
    if ratios is None:
        t: dict[str, float] = {d: float(DEFAULT_RATIOS[d]) for d in DIMENSIONS}
    elif isinstance(ratios, dict):
        for key in ratios:
            if key not in _DIM_INDEX:
                raise BlueprintError(f"未知维度名: {key!r}")
        t = {}
        for d in DIMENSIONS:
            if d not in ratios:
                t[d] = 0.0  # 缺省键视为 0
                continue
            w = ratios[d]
            if isinstance(w, bool) or not isinstance(w, (int, float)):
                raise BlueprintError(f"维度 {d!r} 权重必须是 int/float（bool 拒绝）")
            fw = float(w)
            if not math.isfinite(fw):
                raise BlueprintError(f"维度 {d!r} 权重必须有限（NaN/inf 拒绝）")
            if fw < 0:
                raise BlueprintError(f"维度 {d!r} 权重不能为负")
            t[d] = fw
    else:
        raise BlueprintError("ratios 必须是 dict 或 None")
    total_w = math.fsum(t[d] for d in DIMENSIONS)
    if total_w <= 0:
        raise BlueprintError("配比总和必须为正")

    # ---------- V4 图存在性 ----------
    for kp in ordered:
        if not graph.has(kp):
            raise BlueprintError(f"未知知识点: {kp!r}")

    # ---------- P0 归一化（fsum 求和语义，序无关） ----------
    dims = [d for d in DIMENSIONS if t[d] > 0]  # 正配比维度集，规范序
    w_norm = {d: t[d] / total_w for d in dims}

    # ---------- C1 维度配额（最大余数法，配额恒为先乘后除） ----------
    denom = math.fsum(w_norm[d] for d in dims)
    quota = {d: (budget * w_norm[d]) / denom for d in dims}
    totals = {d: math.floor(quota[d]) for d in dims}
    remaining = budget - sum(totals.values())
    if remaining > 0:
        by_remainder = sorted(
            dims, key=lambda d: (-(quota[d] - totals[d]), _DIM_INDEX[d])
        )
        for d in by_remainder[:remaining]:  # 余数并列（精确 float 相等）按规范序取最前
            totals[d] += 1

    # ---------- C2 维度内均分 ----------
    k = len(ordered)
    cells: dict[str, dict[str, int]] = {kp: {} for kp in ordered}  # 仅正数格
    for d in dims:
        base, extra = divmod(totals[d], k)
        if base > 0:
            for kp in ordered:
                cells[kp][d] = base
        for kp in ordered[:extra]:  # 目标 id 升序的前 extra 个各 +1
            cells[kp][d] = cells[kp].get(d, 0) + 1

    # ---------- C3 覆盖修复（同维移动，维度合计不变） ----------
    while True:
        zero_kp = None
        for kp in ordered:  # 每轮取 id 升序最前的零额者
            if not cells[kp]:
                zero_kp = kp
                break
        if zero_kp is None:
            break
        # 捐出者 = 合计最大者（max 取首个最大值，ordered 升序即并列取 id 最小）
        donor = max(ordered, key=lambda kp: sum(cells[kp].values()))
        give = None
        give_n = 0
        for d in DIMENSIONS:  # 捐出者内部计数最大的维度，并列按规范序取最前
            n = cells[donor].get(d, 0)
            if n > give_n:
                give_n = n
                give = d
        cells[donor][give] -= 1
        if cells[donor][give] == 0:
            del cells[donor][give]
        cells[zero_kp][give] = cells[zero_kp].get(give, 0) + 1

    # ---------- C4 组装（全部新建容器，键按规范序） ----------
    allocation: dict[str, dict[str, int]] = {}
    for kp in ordered:
        inner: dict[str, int] = {}
        for d in DIMENSIONS:
            n = cells[kp].get(d, 0)
            if n > 0:
                inner[d] = n
        allocation[kp] = inner
    return Blueprint(
        targets=list(ordered),
        budget=budget,
        ratios={d: w_norm[d] for d in dims},
        allocation=allocation,
        dimension_totals={d: totals[d] for d in dims},
    )
