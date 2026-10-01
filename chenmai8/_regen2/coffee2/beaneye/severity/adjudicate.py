"""M7 严重度裁决实现（仅凭 docs/assets/specs/severity.md + 冻结测试从零实现）。

spec 依据：
- §1 裁决规则六条（表驱动）；明细版 WorstResult 六字段；未知类/未知序位明确报错。
- §3 severity_order 可换序的根：构造即校验（非空/无重复/[0]=normal）；标准 YAML 覆盖序
  必须恰好覆盖 taxonomy 全部类别（ensure_covers_taxonomy，缺失/未知都报错）；
  rank 按序现场 keys.index() 线性查找，不做预计算表/跨调用缓存，序一换 rank 立即随新序；
  rebase_observation 改写存储位次后契约不变式在任意标准序下成立；
  adjudicate_pairs = rebase + 裁决 + 契约构造 的一条龙入口。
- §4 计数规则：count_defects 独立实现（与契约 defect_counts_from_beans 交叉验证），
  include_normal 缺省 False；effective_defect_counts 再剔除 counts_as_defect=false；
  primary_secondary_counts 按 kind 归属且只计可计类。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Optional, Sequence

import yaml

from beaneye.schemas import BeanObservation, PairedBean, defect_is_countable
from beaneye.taxonomy import Taxonomy, load_taxonomy

__all__ = [
    "CQI_COUNT_RULE",
    "SeverityAdjudicator",
    "SeverityError",
    "SeverityOrder",
    "WorstResult",
    "adjudicate_pairs",
    "count_defects",
    "default_severity_order",
    "effective_defect_counts",
    "primary_secondary_counts",
    "rebase_observation",
    "worst",
    "worst_detail",
]

#: CQI 计数规则（spec §4：一粒只计一次）
CQI_COUNT_RULE = "most_severe_per_bean"


class SeverityError(ValueError):
    """严重度序/裁决参数不合法。"""


def default_severity_order() -> list[str]:
    """taxonomy 默认序（configs/taxonomy.yaml 的 severity_order）。"""
    return load_taxonomy().severity_order


class SeverityOrder:
    """可换序的严重度根：构造即校验；rank 每次现场 index 查找（无缓存）。"""

    def __init__(self, keys: Iterable[str], source: str = "taxonomy:default"):
        seq = tuple(str(k) for k in keys)
        if not seq:
            raise SeverityError("severity_order 不能为空")
        if len(set(seq)) != len(seq):
            raise SeverityError(f"severity_order 存在重复类别: {list(seq)}")
        if seq[0] != "normal":
            raise SeverityError(f"severity_order[0] 必须是 normal，得到 {seq[0]!r}（0=normal 是契约）")
        self.keys: tuple[str, ...] = seq
        self.source = source

    def rank(self, key: str) -> int:
        """序位（下标即 severity_rank）；不在序中的类别明确拒绝，不静默。"""
        if key not in self.keys:
            raise SeverityError(f"类别 {key!r} 不在 severity_order 中: {list(self.keys)}")
        return self.keys.index(key)

    def ensure_covers_taxonomy(self, tax: Optional[Taxonomy] = None) -> None:
        """序必须恰好覆盖 taxonomy 全部类别（缺失/未知都报错）。"""
        tax = tax if tax is not None else load_taxonomy()
        expected = set(tax.keys())
        got = set(self.keys)
        if got != expected:
            raise SeverityError(
                f"severity_order 类别与 taxonomy 不一致: "
                f"缺失={sorted(expected - got)} 未知={sorted(got - expected)}"
            )

    @classmethod
    def from_standard_yaml(cls, path: str | Path) -> "SeverityOrder":
        """标准 YAML 覆盖序：须含 severity_order 且恰好覆盖 taxonomy。"""
        p = Path(path)
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "severity_order" not in data:
            raise SeverityError(f"标准 YAML 缺少 severity_order 节: {p}")
        order = cls(data["severity_order"], source=f"standard:{data.get('standard', '')}")
        order.ensure_covers_taxonomy()
        return order

    def __contains__(self, key: object) -> bool:
        return key in self.keys

    def __len__(self) -> int:
        return len(self.keys)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SeverityOrder):
            return self.keys == other.keys
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.keys)

    def __repr__(self) -> str:
        return f"SeverityOrder(source={self.source!r}, keys={list(self.keys)})"


def _coerce_order(severity_order) -> SeverityOrder:
    """None → taxonomy 默认序；SeverityOrder 原样；list/tuple 等可迭代 → 构造即校验。"""
    if severity_order is None:
        return SeverityOrder(default_severity_order())
    if isinstance(severity_order, SeverityOrder):
        return severity_order
    return SeverityOrder(severity_order)


@dataclass(frozen=True)
class WorstResult:
    """裁决明细（供展示与调试；核心字段与 worst() 逐位一致）。"""

    final_defect: str
    worst_side: str
    final_severity_rank: int
    winner_side: str
    winner_conf: Optional[float]
    tie: bool


def worst_detail(
    top: Optional[BeanObservation],
    bottom: Optional[BeanObservation],
    severity_order=None,
) -> WorstResult:
    """明细版裁决：按当前序现场查 rank（现查，不读观测的存储位次）。"""
    order = _coerce_order(severity_order)

    # #1 两面皆 None → ("normal","none")，rank 0
    if top is None and bottom is None:
        return WorstResult("normal", "none", 0, "none", None, False)
    # #2 仅一面有观测 → 取该面
    if bottom is None:
        return WorstResult(
            top.defect, "top", order.rank(top.defect), "top", top.defect_conf, False
        )
    if top is None:
        return WorstResult(
            bottom.defect, "bottom", order.rank(bottom.defect), "bottom", bottom.defect_conf, False
        )

    # #3/#4 存在可计缺陷面 → 只在可计面之间裁决；否则退回全量比较
    faces = [("top", top), ("bottom", bottom)]
    pool = [(s, o) for s, o in faces if defect_is_countable(o.defect)]
    if not pool:
        pool = faces

    # #5 rank 不等 → 高者胜（rank 按当前序现查）
    best = max(order.rank(o.defect) for _, o in pool)
    pool = [(s, o) for s, o in pool if order.rank(o.defect) == best]

    if len(pool) == 1:
        side, obs = pool[0]
        return WorstResult(obs.defect, side, best, side, obs.defect_conf, False)

    # #6 rank 相等（同序位=同缺陷）→ conf 高者，worst_side="both"；conf 完全相等偏向 top
    (_, a), (_, b) = pool
    if a.defect_conf >= b.defect_conf:
        winner_side, winner_conf = "top", a.defect_conf
    else:
        winner_side, winner_conf = "bottom", b.defect_conf
    return WorstResult(a.defect, "both", best, winner_side, winner_conf, True)


def worst(
    top: Optional[BeanObservation],
    bottom: Optional[BeanObservation],
    severity_order=None,
) -> tuple[str, str]:
    """核心裁决 -> (final_defect, worst_side)；规则同 worst_detail。"""
    d = worst_detail(top, bottom, severity_order)
    return (d.final_defect, d.worst_side)


class SeverityAdjudicator:
    """绑定一份序的裁决器（缺省 taxonomy 默认序）。"""

    def __init__(self, severity_order=None):
        self.order = _coerce_order(severity_order)

    def rank(self, key: str) -> int:
        return self.order.rank(key)

    def worst(self, top, bottom, severity_order=None) -> tuple[str, str]:
        return worst(top, bottom, self.order if severity_order is None else severity_order)

    def worst_detail(self, top, bottom, severity_order=None) -> WorstResult:
        return worst_detail(top, bottom, self.order if severity_order is None else severity_order)


def rebase_observation(obs: BeanObservation, severity_order) -> BeanObservation:
    """把已有观测的 severity_rank 改写为当前序位次（其余字段不变）。"""
    order = _coerce_order(severity_order)
    return replace(obs, severity_rank=order.rank(obs.defect))


def adjudicate_pairs(items: Iterable[tuple], severity_order=None) -> list[PairedBean]:
    """一条龙入口：rebase + 裁决 + 契约构造。

    items 的每项为 (bean_id, top, bottom, pairing_cost)；severity_order 缺省为
    taxonomy 默认序。任意标准序下先 rebase 存储位次，PairedBean 契约不变式即成立。
    """
    order = _coerce_order(severity_order)
    out: list[PairedBean] = []
    for bean_id, top, bottom, cost in items:
        t = rebase_observation(top, order) if top is not None else None
        b = rebase_observation(bottom, order) if bottom is not None else None
        out.append(PairedBean.from_sides(bean_id, t, b, cost))
    return out


# ---------------------------------------------------------------------------
# CQI 计数规则（独立实现，与契约 defect_counts_from_beans 交叉验证）
# ---------------------------------------------------------------------------


def count_defects(beans: Sequence[PairedBean], *, include_normal: bool = False) -> dict[str, int]:
    """每粒按 final_defect 计一次的直方；include_normal 缺省 False（normal 不入直方）。"""
    hist: dict[str, int] = {}
    for b in beans:
        d = b.final_defect
        if d == "normal" and not include_normal:
            continue
        hist[d] = hist.get(d, 0) + 1
    return hist


def effective_defect_counts(beans: Sequence[PairedBean]) -> dict[str, int]:
    """再剔除 counts_as_defect=false 的类（peaberry 不入缺陷直方）。"""
    hist: dict[str, int] = {}
    for b in beans:
        d = b.final_defect
        if not defect_is_countable(d):
            continue
        hist[d] = hist.get(d, 0) + 1
    return hist


def primary_secondary_counts(beans: Sequence[PairedBean]) -> tuple[int, int]:
    """主/次分计：按 taxonomy kind 归属、只计 counts_as_defect=true（peaberry 不计入）。"""
    tax = load_taxonomy()
    primary = secondary = 0
    for b in beans:
        d = b.final_defect
        if not defect_is_countable(d):
            continue
        kind = tax.kind(d)
        if kind == "primary":
            primary += 1
        elif kind == "secondary":
            secondary += 1
    return (primary, secondary)
