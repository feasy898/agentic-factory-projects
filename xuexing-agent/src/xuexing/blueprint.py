"""blueprint —— 诊断卷蓝图生成器（组卷的前置规划器）。

输入目标知识点集合、预算题数与认知维度配比（记忆/理解/应用——TIMSS 2019
数学框架"内容域 × 认知域"二维矩阵的认知域一侧；官方 8 年级 knowing/applying/
reasoning ≈ 40/40/20 冻结为缺省配比），输出一份 Blueprint 规划：每个目标知识
点各出几道题（counts() 可直接传给 paper.generate_paper 的 blueprint 参数）、
每个认知维度合计几道题、以及 (知识点 × 维度) 细目。

行为契约（specs/drafts/blueprint.spec.md，本文件为参考实现）：
- 认知维度配比约束：各维度合计按最大余数法落在 {floor(q), floor(q)+1}；
- 覆盖约束：预算足够时每个目标知识点 ≥ 1 题（不足则拒绝）；
- 同输入同输出（含输入顺序无关）：纯规划，不查题库、不选题、无随机、无 IO。

分配算法（顺序为绑定条款）：C1 维度配额（最大余数法，余数并列按规范维度序
破缺）→ C2 维度内按目标 id 升序均分 → C3 覆盖修复（同维移动，维度合计不变；
捐出者取合计最大者并列取最小 id，移出维度取捐出者内部最大格并列取规范序最前）
→ C4 组装（只保留正数格/正配比维度）。
"""
# 注入装载约束（见 specs/drafts/blueprint.spec.md §2）：不用 from __future__ import
# annotations——dataclass 字符串注解在 _regen_* 顶层模块名下会触发未受保护的
# sys.modules 解析。
import math
from dataclasses import dataclass

__all__ = [
    "DIMENSIONS",
    "DEFAULT_RATIOS",
    "DIFFICULTY_TARGET",
    "Blueprint",
    "BlueprintError",
    "build_blueprint",
]

# ---- 冻结常量（specs/drafts/blueprint.spec.md §3.1）----

DIMENSIONS = ("记忆", "理解", "应用")  # 规范维度序：一切并列破缺与输出序的基准
DEFAULT_RATIOS = {"记忆": 0.4, "理解": 0.4, "应用": 0.2}  # TIMSS 8 年级 40/40/20
DIFFICULTY_TARGET = {"记忆": 0.2, "理解": 0.5, "应用": 0.8}  # 维度 -> 难度目标


class BlueprintError(ValueError):
    """blueprint 模块所有校验失败的异常类型。"""


@dataclass
class Blueprint:
    """诊断卷蓝图：目标知识点 × 认知维度的出题规划。

    targets 排序去重；ratios 为归一化生效配比（规范维度序、仅正配比维度）；
    allocation 只含正数格（kp -> {维度: n}，内层键按规范维度序）；
    dimension_totals 只含正配比维度（值可为 0，见规格 §3.4）。
    """

    targets: list
    budget: int
    ratios: dict
    allocation: dict
    dimension_totals: dict

    def counts(self) -> dict:
        """{知识点: 该点各维度合计}，合计恰为 budget；每次返回新 dict。"""
        return {kp: sum(cells.values()) for kp, cells in self.allocation.items()}

    def per_dimension(self) -> list:
        """[(维度, {kp: 该维度题数}, DIFFICULTY_TARGET[维度]), ...]。

        按规范维度序、仅合计 ≥ 1 的维度；各 sub-dict 恰好划分 counts()。
        """
        out = []
        for dim in DIMENSIONS:
            if self.dimension_totals.get(dim, 0) < 1:
                continue
            sub = {
                kp: cells[dim]
                for kp, cells in self.allocation.items()
                if cells.get(dim, 0) > 0
            }
            out.append((dim, sub, DIFFICULTY_TARGET[dim]))
        return out


# ---------- 内部工具 ----------

def _as_target_list(targets) -> list:
    """targets 校验与规范化：非 str 可迭代对象、元素非空 str；去重 + 码点升序。"""
    if isinstance(targets, str):
        raise BlueprintError("targets must be an iterable of knowledge point ids, not a bare str")
    try:
        raw = list(targets)
    except TypeError:
        raise BlueprintError(f"targets must be an iterable, got {type(targets).__name__}")
    for i, kp in enumerate(raw):
        if not isinstance(kp, str) or not kp:
            raise BlueprintError(f"targets[{i}] must be a non-empty str, got {kp!r}")
    ids = sorted(set(raw))
    if not ids:
        raise BlueprintError("targets must not be empty")
    return ids


def _as_budget(budget, n_targets: int) -> int:
    """budget 校验：int 且非 bool；预算 ≥ 目标数（否则覆盖不可能）。"""
    if isinstance(budget, bool) or not isinstance(budget, int):
        raise BlueprintError(f"budget must be an int, got {type(budget).__name__}")
    if budget < n_targets:
        raise BlueprintError(
            f"budget {budget} smaller than {n_targets} targets: coverage impossible")
    return budget


def _effective_ratios(ratios) -> dict:
    """ratios 校验与归一化：键 ⊆ DIMENSIONS、值为有限非负数字（bool 拒绝）、Σ>0；
    返回 {维度: w/Σw}（规范维度序，仅正配比维度）。"""
    if ratios is None:
        ratios = dict(DEFAULT_RATIOS)
    if not isinstance(ratios, dict):
        raise BlueprintError(f"ratios must be a dict, got {type(ratios).__name__}")
    for dim, w in ratios.items():
        if dim not in DIMENSIONS:
            raise BlueprintError(f"unknown dimension: {dim!r}")
        if isinstance(w, bool) or not isinstance(w, (int, float)):
            raise BlueprintError(f"ratios[{dim!r}] must be a number, got {type(w).__name__}")
        wf = float(w)
        if not math.isfinite(wf) or wf < 0.0:  # NaN/inf/负全部拒绝
            raise BlueprintError(f"ratios[{dim!r}] must be a finite non-negative number, got {w!r}")
    total = sum(float(ratios.get(d, 0)) for d in DIMENSIONS)
    if total <= 0.0:
        raise BlueprintError("ratios must have a positive sum")
    return {d: float(ratios.get(d, 0.0)) / total for d in DIMENSIONS
            if float(ratios.get(d, 0.0)) > 0.0}


def _apportion(total: int, weights: list) -> list:
    """最大余数法：把 total 按权重（全 > 0）分配，返回与 weights 等长的计数列表。

    余数 = 配额 − floor(配额)，配额按 total*w/Σw 浮点计算；余数并列（精确 float
    相等）按位置序破缺（调用方保证传入序为规范序）。
    """
    s = sum(weights)
    quotas = [total * w / s for w in weights]
    base = [int(math.floor(q)) for q in quotas]
    remaining = total - sum(base)
    order = sorted(range(len(weights)), key=lambda i: (-(quotas[i] - base[i]), i))
    for i in order[:remaining]:
        base[i] += 1
    return base


# ---------- 核心：蓝图生成 ----------

def build_blueprint(targets, budget, graph, ratios=None) -> Blueprint:
    """按目标知识点集合 + 预算题数 + 认知维度配比生成诊断卷蓝图。

    校验先于任何计算（顺序见规格 §3.3）：targets → budget → ratios → 图存在性，
    任何一条失败抛 BlueprintError。计算四步：C1 维度配额（最大余数法）→
    C2 维度内按 id 升序均分 → C3 覆盖修复（同维移动，维度合计不变）→
    C4 组装（只留正数格）。

    副作用：无 —— 不修改 targets、ratios、graph；Blueprint 持有的容器均为新建
    （counts()/per_dimension() 每次另返回新 dict）。
    """
    # ---- 校验 ----
    ids = _as_target_list(targets)
    n = _as_budget(budget, len(ids))
    eff = _effective_ratios(ratios)
    for kp in ids:
        if not graph.has(kp):
            raise BlueprintError(f"unknown knowledge point: {kp}")

    # ---- C1 维度配额 ----
    dims = list(eff)  # 规范维度序中的正配比维度
    totals_list = _apportion(n, [eff[d] for d in dims])
    totals = dict(zip(dims, totals_list))

    # ---- C2 维度内均分（id 升序，前 T mod K 个 +1）----
    k = len(ids)
    alloc = {kp: {d: 0 for d in dims} for kp in ids}
    for dim in dims:
        base, extra = divmod(totals[dim], k)
        for i, kp in enumerate(ids):
            alloc[kp][dim] = base + (1 if i < extra else 0)

    # ---- C3 覆盖修复：同维移动，维度合计不变 ----
    # 可行性（n ≥ k 时必然成立）：若某 kp 为 0，则其余 ≤ k−1 个 kp 持有 n ≥ k 题，
    # 由抽屉原理必有合计 ≥ 2 者可作捐出者。
    while True:
        zero = next((kp for kp in ids if sum(alloc[kp].values()) == 0), None)
        if zero is None:
            break
        donor = max(ids, key=lambda kp: sum(alloc[kp].values()))  # 并列取 id 最小
        out_dim = next(d for d in dims
                       if alloc[donor][d] == max(alloc[donor][x] for x in dims))  # 规范序
        alloc[donor][out_dim] -= 1
        alloc[zero][out_dim] += 1

    # ---- C4 组装：只留正数格 ----
    allocation = {
        kp: {d: v for d, v in cells.items() if v > 0}
        for kp, cells in alloc.items()
    }
    return Blueprint(
        targets=list(ids),
        budget=n,
        ratios=dict(eff),
        allocation=allocation,
        dimension_totals=dict(totals),
    )
