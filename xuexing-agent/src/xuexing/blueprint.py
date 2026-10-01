"""blueprint —— 诊断卷蓝图生成器（重生成 v0.2.0）。

纯规划内核：输入目标知识点集合、预算题数与认知维度配比（记忆/理解/应用），
产出每个知识点的出题格规划（kp × 维度 → 题数）。行为契约见
specs/frozen/blueprint.spec.md：最大余数法配额 + 规范序破缺 + 覆盖修复；
全部浮点求和取精确和的正确舍入（math.fsum，序无关）；同输入同输出。
不查题库、不选题、无 IO。
"""
import math
from dataclasses import dataclass

DIMENSIONS = ("记忆", "理解", "应用")
DEFAULT_RATIOS = {"记忆": 0.4, "理解": 0.4, "应用": 0.2}
DIFFICULTY_TARGET = {"记忆": 0.2, "理解": 0.5, "应用": 0.8}


class BlueprintError(ValueError):
    """blueprint 输入非法（契约只约束异常类型）。"""


@dataclass
class Blueprint:
    """规划结果；全部容器字段为构造期新建，不与入参或模块级容器别名共享。"""

    targets: list[str]
    budget: int
    ratios: dict[str, float]
    allocation: dict[str, dict[str, int]]
    dimension_totals: dict[str, int]

    def counts(self) -> dict[str, int]:
        """kp -> 该 kp 各维度合计；键为 targets 升序，合计恰为 budget。每次返回新 dict。"""
        out = {}
        for kp in self.targets:
            n = 0
            for v in self.allocation[kp].values():
                n += v
            out[kp] = n
        return out

    def per_dimension(self) -> list[tuple[str, dict[str, int], float]]:
        """按规范维度序返回 (维度, {kp: 该维度题数}, 难度目标)；仅含合计 >= 1 的维度。

        各 sub-dict 划分 counts()（只含正数格），且每次调用返回新容器。
        """
        out = []
        for d in DIMENSIONS:
            if self.dimension_totals.get(d, 0) < 1:
                continue
            sub = {}
            for kp in self.targets:
                n = self.allocation[kp].get(d, 0)
                if n > 0:
                    sub[kp] = n
            out.append((d, sub, DIFFICULTY_TARGET[d]))
        return out


def build_blueprint(targets, budget, graph, ratios=None) -> Blueprint:
    # ---- V1 targets ----
    if isinstance(targets, str):
        raise BlueprintError("targets 不能是裸字符串")
    try:
        elems = list(targets)
    except TypeError:
        raise BlueprintError("targets 不可迭代") from None
    for e in elems:
        if not isinstance(e, str) or not e:
            raise BlueprintError("targets 元素必须是非空 str")
    kps = sorted(set(elems))  # 元素校验先于去重；码点序升序
    if not kps:
        raise BlueprintError("targets 为空")

    # ---- V2 budget ----
    if isinstance(budget, bool) or not isinstance(budget, int):
        raise BlueprintError("budget 必须是非 bool 的 int")
    if budget < len(kps):
        raise BlueprintError("budget 小于目标数，覆盖不可能")

    # ---- V3 ratios ----
    if ratios is None:
        t = {d: float(DEFAULT_RATIOS[d]) for d in DIMENSIONS}
    else:
        if not isinstance(ratios, dict):
            raise BlueprintError("ratios 必须是 dict")
        for key in ratios:
            if key not in DIMENSIONS:
                raise BlueprintError(f"未知维度: {key!r}")
        t = {}
        for d in DIMENSIONS:
            if d not in ratios:
                t[d] = 0.0
                continue
            v = ratios[d]
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise BlueprintError(f"配比必须是非 bool 数值: {d}")
            fv = float(v)
            if not math.isfinite(fv) or fv < 0.0:
                raise BlueprintError(f"配比必须有限且非负: {d}")
            t[d] = fv
    if math.fsum(t[d] for d in DIMENSIONS) <= 0.0:
        raise BlueprintError("配比总和必须为正")

    # ---- V4 图存在性 ----
    for kp in kps:
        if not graph.has(kp):
            raise BlueprintError(f"未知知识点: {kp}")

    # ---- P0 归一化（fsum：序无关精确和的正确舍入） ----
    total_w = math.fsum(t[d] for d in DIMENSIONS)
    dims = [d for d in DIMENSIONS if t[d] > 0.0]
    w = {d: t[d] / total_w for d in dims}

    # ---- C1 维度配额（最大余数法；余数精确并列按规范维度序破缺） ----
    denom = math.fsum(w[d] for d in DIMENSIONS if d in w)
    q = {d: (budget * w[d]) / denom for d in dims}  # 先乘后除
    totals = {d: math.floor(q[d]) for d in dims}
    by_remainder = sorted(dims, key=lambda d: -(q[d] - totals[d]))  # 稳定排序保规范序
    rest = budget - sum(totals.values())
    for i in range(rest):
        totals[by_remainder[i]] += 1

    # ---- C2 维度内均分（id 升序前 T_d % K 个 +1） ----
    k = len(kps)
    cells = {kp: {} for kp in kps}
    for d in dims:
        base = totals[d] // k
        extra = totals[d] % k
        for i, kp in enumerate(kps):
            n = base + (1 if i < extra else 0)
            if n > 0:
                cells[kp][d] = n

    # ---- C3 覆盖修复（同一维度内移动；维度合计不变。budget >= K 时每轮
    # 捐出者合计 >= 2，零额知识点数单调递减，循环必然终止） ----
    while True:
        zero = None
        for kp in kps:  # id 升序最前的零额者
            if sum(cells[kp].values()) == 0:
                zero = kp
                break
        if zero is None:
            break
        donor = kps[0]  # 合计最大者；并列取 id 最小（严格 > 保首个）
        donor_total = sum(cells[donor].values())
        for kp in kps[1:]:
            n = sum(cells[kp].values())
            if n > donor_total:
                donor, donor_total = kp, n
        move_dim = None  # 捐出者内部计数最大维度；并列按规范序取最前
        move_n = 0
        for d in DIMENSIONS:
            n = cells[donor].get(d, 0)
            if n > move_n:
                move_dim, move_n = d, n
        cells[donor][move_dim] -= 1
        cells[zero][move_dim] = cells[zero].get(move_dim, 0) + 1

    # ---- C4 组装（allocation 仅正数格；键序：外层 targets 升序、内层规范维度序） ----
    allocation = {}
    for kp in kps:
        inner = {}
        for d in DIMENSIONS:
            n = cells[kp].get(d, 0)
            if n > 0:
                inner[d] = n
        allocation[kp] = inner
    return Blueprint(
        targets=list(kps),
        budget=budget,
        ratios={d: w[d] for d in dims},
        allocation=allocation,
        dimension_totals={d: totals[d] for d in dims},
    )
