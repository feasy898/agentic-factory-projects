"""M7 严重度裁决：可换序的 severity_order + 裁决规则 + CQI 计数。

重生成实现依据（逐条对照）：

- docs/assets/specs/severity.md
  §1 裁决规则六条（两面皆 None / 单面 / 可计面间裁决 / 退回全量 / rank 定胜 /
  平级 conf 定胜记 both、完全相等偏 top）
  §2 severity_order 三来源（taxonomy 默认序 / 标准 YAML 覆盖序须恰全覆盖 /
  构造即校验：非空、无重复、[0]=normal）+ rebase_observation 换序衔接
  §3 CQI 计数三函数（count_defects / effective_defect_counts /
  primary_secondary_counts，count_rule=most_severe_per_bean）
- docs/assets/CONTRACTS.md C5（契约双侧逐位一致，共用 defect_is_countable）
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import yaml

from beaneye.schemas import (
    BeanObservation,
    PairedBean,
    defect_is_countable,
)
from beaneye.taxonomy import load_taxonomy

__all__ = [
    "CQI_COUNT_RULE",
    "SeverityAdjudicator",
    "SeverityError",
    "SeverityOrder",
    "WorstDetail",
    "adjudicate_pairs",
    "count_defects",
    "default_severity_order",
    "effective_defect_counts",
    "primary_secondary_counts",
    "rebase_observation",
    "worst",
    "worst_detail",
]

#: CQI 计数规则口径（spec §3：一粒只计一次）
CQI_COUNT_RULE = "most_severe_per_bean"


class SeverityError(ValueError):
    """severity_order 非法 / 类别不在序中 / 标准 YAML 覆盖不全。"""


# ---------------------------------------------------------------------------
# severity_order（可换序的根；构造即校验）
# ---------------------------------------------------------------------------


class SeverityOrder:
    """严重度全序：非空、无重复、``[0]`` 恒 normal，下标即 severity_rank。"""

    def __init__(self, keys: Iterable[str], source: str = "custom") -> None:
        keys = [str(k) for k in keys]
        if not keys:
            raise SeverityError("severity_order 不能为空")
        if len(set(keys)) != len(keys):
            raise SeverityError(f"severity_order 存在重复类别: {keys}")
        if keys[0] != "normal":
            raise SeverityError(
                f"severity_order[0] 必须是 normal（0=normal 是契约），得到 {keys[0]!r}"
            )
        unknown = [k for k in keys if k not in load_taxonomy()]
        if unknown:
            raise SeverityError(f"severity_order 含未知类别（不在 taxonomy）: {unknown}")
        self._order: list[str] = keys
        self._rank: dict[str, int] = {k: i for i, k in enumerate(keys)}
        self.source = source

    # -- 容器协议 -----------------------------------------------------------
    def __len__(self) -> int:
        return len(self._order)

    def __contains__(self, key: object) -> bool:
        return key in self._rank

    def __iter__(self) -> Iterator[str]:
        return iter(self._order)

    @property
    def order(self) -> list[str]:
        return list(self._order)

    def rank(self, key: str) -> int:
        """类别位次；不在序中的类别明确报错（不得静默裁决）。"""
        if key not in self._rank:
            raise SeverityError(f"类别 {key!r} 不在 severity_order")
        return self._rank[key]

    # -- 来源 -----------------------------------------------------------------
    @classmethod
    def from_taxonomy(cls) -> "SeverityOrder":
        """taxonomy 默认序。"""
        return cls(load_taxonomy().severity_order, source="taxonomy")

    @classmethod
    def from_standard_yaml(cls, path: str | Path) -> "SeverityOrder":
        """标准 YAML 覆盖序：必须恰好覆盖 taxonomy 全部类别（缺失/未知都报错）。"""
        p = Path(path)
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as exc:
            raise SeverityError(f"标准 YAML 无法读取: {p} ({exc})") from exc
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise SeverityError(f"标准 YAML 顶层必须是映射: {p}")
        std = str(data.get("standard", p.stem))
        order = data.get("severity_order")
        if order is None:
            raise SeverityError(f"标准 {std} 的 YAML 缺少 severity_order 节: {p}")
        if not isinstance(order, (list, tuple)) or not order:
            raise SeverityError(f"标准 {std} 的 severity_order 必须是非空列表: {p}")
        keys = [str(k) for k in order]
        tax_keys = set(load_taxonomy().keys())
        missing = sorted(tax_keys - set(keys))
        extra = sorted(set(keys) - tax_keys)
        if missing or extra or len(set(keys)) != len(keys):
            raise SeverityError(
                f"标准 {std} 的 severity_order 与 taxonomy 类别不一致"
                f"（缺失: {missing}，未知: {extra}）"
            )
        return cls(keys, source=f"standard:{std}")


def default_severity_order() -> list[str]:
    """taxonomy 默认严重度序（configs/taxonomy.yaml severity_order）。"""
    return load_taxonomy().severity_order


def _coerce_order(order: Sequence[str] | SeverityOrder | None) -> SeverityOrder:
    """None→taxonomy 默认序；list/tuple→构造即校验；SeverityOrder→原样。"""
    if order is None:
        return SeverityOrder.from_taxonomy()
    if isinstance(order, SeverityOrder):
        return order
    return SeverityOrder(order)


# ---------------------------------------------------------------------------
# 裁决规则（spec §1 六条；与契约 _resolve_worst 逐位一致）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorstDetail:
    """裁决明细（核心三元组 + 展示/调试字段）。"""

    final_defect: str
    worst_side: str  # top / bottom / both / none
    final_severity_rank: int
    winner_side: str  # top / bottom / none
    winner_conf: float
    tie: bool


def worst_detail(
    top: BeanObservation | None,
    bottom: BeanObservation | None,
    severity_order: Sequence[str] | SeverityOrder | None = None,
) -> WorstDetail:
    """按 severity_order 裁决两面，返回明细。

    规则（spec §1，rank 一律由**序**查类别得出，非读观测缓存位次）：
    1. 两面皆 None → normal / none / rank 0；
    2. 仅一面有观测 → 取该面；
    3. 两面都有且存在可计缺陷面 → 只在可计面之间裁决
       （W13：peaberry 位次再高也不吞另一面可计缺陷）；
    4. 两面都有、皆非可计 → 退回全量比较（peaberry 标注语义不丢失）；
    5. 可计面之间（或全量）rank 不等 → rank 高者胜，worst_side=胜面；
    6. rank 相等（同序位=同缺陷）→ conf 高者胜并记 worst_side="both"；
       conf 完全相等偏向 top。
    """
    order = _coerce_order(severity_order)
    if top is None and bottom is None:
        return WorstDetail("normal", "none", 0, "none", 0.0, False)
    present = [(side, obs) for side, obs in (("top", top), ("bottom", bottom)) if obs is not None]
    countable = [(side, obs) for side, obs in present if defect_is_countable(obs.defect)]
    pool = countable if (len(present) == 2 and countable) else present
    if len(pool) == 1:
        side, obs = pool[0]
        return WorstDetail(
            final_defect=obs.defect,
            worst_side=side,
            final_severity_rank=order.rank(obs.defect),
            winner_side=side,
            winner_conf=obs.defect_conf,
            tie=False,
        )
    (t_side, t_obs), (b_side, b_obs) = pool
    t_rank = order.rank(t_obs.defect)
    b_rank = order.rank(b_obs.defect)
    if t_rank != b_rank:
        if t_rank > b_rank:
            return WorstDetail(t_obs.defect, t_side, t_rank, t_side, t_obs.defect_conf, False)
        return WorstDetail(b_obs.defect, b_side, b_rank, b_side, b_obs.defect_conf, False)
    # 平级（同序位=同缺陷）：conf 高者胜、worst_side="both"，完全相等偏向 top
    top_wins = t_obs.defect_conf >= b_obs.defect_conf
    winner = t_obs if top_wins else b_obs
    return WorstDetail(
        final_defect=winner.defect,
        worst_side="both",
        final_severity_rank=t_rank,
        winner_side=t_side if top_wins else b_side,
        winner_conf=winner.defect_conf,
        tie=True,
    )


def worst(
    top: BeanObservation | None,
    bottom: BeanObservation | None,
    severity_order: Sequence[str] | SeverityOrder | None = None,
) -> tuple[str, str]:
    """裁决入口（spec 签名）：返回 ``(final_defect, worst_side)``。"""
    detail = worst_detail(top, bottom, severity_order)
    return (detail.final_defect, detail.worst_side)


class SeverityAdjudicator:
    """按固定 severity_order 的裁决器（默认 taxonomy 默认序）。"""

    def __init__(self, severity_order: Sequence[str] | SeverityOrder | None = None) -> None:
        self._order = _coerce_order(severity_order)

    @property
    def severity_order(self) -> list[str]:
        return self._order.order

    @property
    def source(self) -> str:
        return self._order.source

    def rank(self, key: str) -> int:
        """类别位次（与 taxonomy 默认序一致：normal=0）。"""
        return self._order.rank(key)

    def worst(self, top: BeanObservation | None, bottom: BeanObservation | None) -> tuple[str, str]:
        return worst(top, bottom, self._order)

    def worst_detail(
        self, top: BeanObservation | None, bottom: BeanObservation | None
    ) -> WorstDetail:
        return worst_detail(top, bottom, self._order)


# ---------------------------------------------------------------------------
# 换序衔接（spec §2：rebase + 裁决 + 契约构造一条龙）
# ---------------------------------------------------------------------------


def rebase_observation(
    obs: BeanObservation,
    severity_order: Sequence[str] | SeverityOrder | None = None,
) -> BeanObservation:
    """把观测的 ``severity_rank`` 改写为给定序的位次（其余字段不变）。"""
    order = _coerce_order(severity_order)
    return obs.model_copy(update={"severity_rank": order.rank(obs.defect)})


def adjudicate_pairs(
    entries: Iterable[tuple[str, BeanObservation | None, BeanObservation | None, float]],
    severity_order: Sequence[str] | SeverityOrder | None = None,
) -> list[PairedBean]:
    """一条龙入口：rebase 观测位次 → 契约构造 ``PairedBean``（构造期复核不变式）。

    ``entries`` 逐项为 ``(bean_id, top, bottom, pairing_cost)``。
    """
    order = _coerce_order(severity_order)
    beans: list[PairedBean] = []
    for bean_id, top, bottom, cost in entries:
        top_r = rebase_observation(top, order) if top is not None else None
        bottom_r = rebase_observation(bottom, order) if bottom is not None else None
        beans.append(PairedBean.from_sides(bean_id, top_r, bottom_r, cost))
    return beans


# ---------------------------------------------------------------------------
# CQI 计数（spec §3：count_rule=most_severe_per_bean，一粒只计一次）
# ---------------------------------------------------------------------------


def count_defects(
    beans: Sequence[PairedBean],
    include_normal: bool = False,
) -> dict[str, int]:
    """每粒按 ``final_defect`` 计一次的直方（normal 不计，除非 include_normal）。

    独立实现（Counter 口径），与契约 ``schemas.defect_counts_from_beans``
    交叉验证一致性（tests/test_severity.py 锁定）。
    """
    hist: Counter[str] = Counter()
    for bean in beans:
        if bean.final_defect == "normal" and not include_normal:
            continue
        hist[bean.final_defect] += 1
    return dict(hist)


def effective_defect_counts(
    beans: Sequence[PairedBean],
    include_normal: bool = False,
) -> dict[str, int]:
    """在 ``count_defects`` 基础上再剔除 counts_as_defect=false 的类。

    peaberry 计量不计缺陷：标注留在 ``final_defect``，但不入有效缺陷直方。
    """
    return {
        key: n
        for key, n in count_defects(beans, include_normal=include_normal).items()
        if defect_is_countable(key)
    }


def primary_secondary_counts(beans: Sequence[PairedBean]) -> tuple[int, int]:
    """主/次缺陷分计（GradingDecision.primary_count/secondary_count 口径）。

    只计 counts_as_defect=true 的类；主/次归属取 taxonomy ``kind``
    （primary/secondary）；peaberry 等不可计类与 normal 不计。
    """
    taxonomy = load_taxonomy()
    primary = 0
    secondary = 0
    for bean in beans:
        defect = bean.final_defect
        if not defect_is_countable(defect):
            continue
        kind = taxonomy.kind(defect)
        if kind == "primary":
            primary += 1
        elif kind == "secondary":
            secondary += 1
        else:
            raise SeverityError(f"类别 {defect!r} 的 kind={kind!r} 不是 primary/secondary")
    return (primary, secondary)
