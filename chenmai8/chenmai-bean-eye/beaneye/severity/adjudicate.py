"""M7 严重度裁决 + CQI 计数规则（每粒只计一次）。

契约依据（schemas.PairedBean 不变式 / M7 spec）：
- ``worst(top, bottom, severity_order) -> (final_defect, worst_side)``：
  severity_rank 高者胜；平级取 defect_conf 高者并记 worst_side="both"
  （conf 完全相等时偏向 top，与契约 ``_resolve_worst`` 逐位一致）；
  任一面为 None 取另一面；两面皆 None → ("normal", "none")。
- severity_order 默认读 ``configs/taxonomy.yaml``；也可从标准 YAML 读
  （不同标准可不同，见标准 YAML 的 ``severity_order`` 字段）。
- CQI 计数规则 ``most_severe_per_bean``：一粒豆无论两面各有什么缺陷，
  只按 final_defect 计一次。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from beaneye.schemas import BeanObservation, PairedBean
from beaneye.taxonomy import Taxonomy, load_taxonomy

__all__ = [
    "CQI_COUNT_RULE",
    "SeverityError",
    "SeverityOrder",
    "SeverityAdjudicator",
    "WorstResult",
    "default_severity_order",
    "worst",
    "worst_detail",
    "adjudicate_pairs",
    "count_defects",
    "effective_defect_counts",
    "primary_secondary_counts",
]

# 标准 YAML count_rule 的取值（§3.3）：每粒只计最严重缺陷
CQI_COUNT_RULE = "most_severe_per_bean"


class SeverityError(ValueError):
    """severity_order 非法 / 缺陷类别不在序中 / 标准 YAML 缺 severity_order。"""


# ---------------------------------------------------------------------------
# 严重度序（taxonomy 默认序或标准 YAML 覆盖序）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeverityOrder:
    """一份可裁决的严重度序：keys 下标即 severity_rank（0=normal，越大越严重）。

    构造即校验：非空、无重复、首元素必须是 ``normal``
    （契约：0=normal，缺陷类 rank 必须 > 0）。
    """

    keys: tuple[str, ...]
    source: str = "explicit"  # taxonomy:<path> | standard:<id> | explicit

    def __post_init__(self) -> None:
        ks = self.keys
        if not ks:
            raise SeverityError("severity_order 不能为空")
        if len(set(ks)) != len(ks):
            dup = sorted({k for k in ks if ks.count(k) > 1})
            raise SeverityError(f"severity_order 存在重复类别: {dup}")
        if ks[0] != "normal":
            raise SeverityError(
                f"severity_order[0] 必须是 normal（0=normal 契约），得到 {ks[0]!r}"
            )

    # -- 构造入口 ----------------------------------------------------------
    @classmethod
    def from_taxonomy(cls, path: str | Path | None = None) -> "SeverityOrder":
        """从 configs/taxonomy.yaml 读默认序。"""
        tax = load_taxonomy(path)
        return cls(tuple(tax.severity_order), source=f"taxonomy:{tax.source_path}")

    @classmethod
    def from_standard_yaml(cls, path: str | Path) -> "SeverityOrder":
        """从标准 YAML 读 severity_order（不同标准可不同），并要求覆盖全部类别。"""
        p = Path(path)
        if not p.is_file():
            raise SeverityError(f"标准 YAML 不存在: {p}")
        try:
            raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise SeverityError(f"标准 YAML 解析失败: {p}\n{e}") from e
        if not isinstance(raw, dict):
            raise SeverityError(f"标准 YAML 顶层必须是映射: {p}")
        order = raw.get("severity_order")
        if not isinstance(order, list) or not order:
            raise SeverityError(f"标准 YAML 缺少非空 severity_order 列表: {p}")
        std_id = raw.get("standard") or p.stem
        so = cls(tuple(order), source=f"standard:{std_id}")
        so.ensure_covers_taxonomy()
        return so

    @classmethod
    def coerce(
        cls, value: "SeverityOrder | Sequence[str] | None"
    ) -> "SeverityOrder":
        """把 None / 键列表 / 已有 SeverityOrder 规范成 SeverityOrder。"""
        if isinstance(value, SeverityOrder):
            return value
        if value is None:
            return cls.from_taxonomy()
        if isinstance(value, Sequence) and not isinstance(value, str):
            return cls(tuple(value))
        raise SeverityError(
            f"无法把 {type(value).__name__} 当作 severity_order（需列表/元组/SeverityOrder/None）"
        )

    # -- 查询 --------------------------------------------------------------
    def rank(self, defect: str) -> int:
        """缺陷类别在本序中的位次；不在序中 → SeverityError。"""
        try:
            return self.keys.index(defect)
        except ValueError:
            raise SeverityError(
                f"缺陷类别 {defect!r} 不在 severity_order({self.source}) 中；"
                f"合法取值: {list(self.keys)}"
            ) from None

    def __contains__(self, defect: object) -> bool:
        return defect in self.keys

    def __len__(self) -> int:
        return len(self.keys)

    def ensure_covers_taxonomy(self, taxonomy: Taxonomy | None = None) -> None:
        """校验本序恰好覆盖 taxonomy 全部类别（标准 YAML 序应为全排列）。"""
        tax = taxonomy if taxonomy is not None else load_taxonomy()
        missing = [k for k in tax.keys() if k not in self.keys]
        extra = [k for k in self.keys if not tax.is_valid_key(k)]
        if missing or extra:
            raise SeverityError(
                f"severity_order({self.source}) 与 taxonomy 不一致：缺失 {missing}，未知 {extra}"
            )


# ---------------------------------------------------------------------------
# 裁决
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorstResult:
    """一次裁决的完整结果（worst() 的明细版）。"""

    final_defect: str
    worst_side: str  # top | bottom | both | none
    final_severity_rank: int
    winner_side: str  # top | bottom | none（平级时为 conf 高的一面）
    winner_conf: float | None
    tie: bool  # 两面同 rank（同缺陷）时 True


class SeverityAdjudicator:
    """「每粒多缺陷取最严重」的裁决器（M7 规范实现）。

    与契约 ``PairedBean`` 校验器共用同一套规则，保证两者裁决逐位一致；
    标准自定义序通过 :meth:`rebase_observation` 把观测的 severity_rank
    改写为该序位次，使 PairedBean 不变式在任意标准序下仍成立。
    """

    def __init__(self, severity_order: SeverityOrder | Sequence[str] | None = None):
        self.order = SeverityOrder.coerce(severity_order)

    def rank(self, defect: str) -> int:
        return self.order.rank(defect)

    # -- 核心 --------------------------------------------------------------
    def worst_detail(
        self, top: BeanObservation | None, bottom: BeanObservation | None
    ) -> WorstResult:
        if top is None and bottom is None:
            return WorstResult("normal", "none", 0, "none", None, False)
        if bottom is None:
            return WorstResult(
                top.defect, "top", self.order.rank(top.defect), "top", top.defect_conf, False
            )
        if top is None:
            return WorstResult(
                bottom.defect,
                "bottom",
                self.order.rank(bottom.defect),
                "bottom",
                bottom.defect_conf,
                False,
            )
        rt, rb = self.order.rank(top.defect), self.order.rank(bottom.defect)
        if rt > rb:
            return WorstResult(top.defect, "top", rt, "top", top.defect_conf, False)
        if rb > rt:
            return WorstResult(
                bottom.defect, "bottom", rb, "bottom", bottom.defect_conf, False
            )
        # 平级（同序位 → 同缺陷）：取 conf 高者；完全相等偏向 top（与契约一致）
        winner = top if top.defect_conf >= bottom.defect_conf else bottom
        return WorstResult(
            winner.defect,
            "both",
            rt,
            "top" if winner is top else "bottom",
            winner.defect_conf,
            True,
        )

    def worst(
        self, top: BeanObservation | None, bottom: BeanObservation | None
    ) -> tuple[str, str]:
        """spec 签名：``(final_defect, worst_side)``。"""
        d = self.worst_detail(top, bottom)
        return d.final_defect, d.worst_side

    # -- 与契约衔接 --------------------------------------------------------
    def rebase_observation(
        self, obs: BeanObservation | None
    ) -> BeanObservation | None:
        """把观测的 severity_rank 改写为当前序位次（已是该位次则原样返回）。"""
        if obs is None:
            return None
        r = self.order.rank(obs.defect)
        if r == obs.severity_rank:
            return obs
        return obs.model_copy(update={"severity_rank": r})

    def adjudicate_pairs(
        self, pairs: Iterable[tuple[str, BeanObservation | None, BeanObservation | None, float]]
    ) -> list[PairedBean]:
        """按当前序裁决 ``(bean_id, top, bottom, pairing_cost)`` 序列 → PairedBean 列表。

        单面/空面豆的 pairing_cost 必须传 -1（契约要求），两面豆传 mm 距离。
        """
        out: list[PairedBean] = []
        for bean_id, top, bottom, cost in pairs:
            detail = self.worst_detail(top, bottom)
            out.append(
                PairedBean(
                    bean_id=bean_id,
                    top=self.rebase_observation(top),
                    bottom=self.rebase_observation(bottom),
                    pairing_cost=cost,
                    worst_side=detail.worst_side,
                    final_defect=detail.final_defect,
                    final_severity_rank=detail.final_severity_rank,
                )
            )
        return out


# ---------------------------------------------------------------------------
# 模块级便捷入口
# ---------------------------------------------------------------------------


def default_severity_order() -> list[str]:
    """taxonomy 默认严重度序（configs/taxonomy.yaml 的 severity_order）。"""
    return list(SeverityOrder.from_taxonomy().keys)


def worst(
    top: BeanObservation | None,
    bottom: BeanObservation | None,
    severity_order: SeverityOrder | Sequence[str] | None = None,
) -> tuple[str, str]:
    """模块级 spec 签名：``worst(top, bottom, severity_order) -> (final_defect, worst_side)``。"""
    return SeverityAdjudicator(severity_order).worst(top, bottom)


def worst_detail(
    top: BeanObservation | None,
    bottom: BeanObservation | None,
    severity_order: SeverityOrder | Sequence[str] | None = None,
) -> WorstResult:
    return SeverityAdjudicator(severity_order).worst_detail(top, bottom)


def adjudicate_pairs(
    pairs: Iterable[tuple[str, BeanObservation | None, BeanObservation | None, float]],
    severity_order: SeverityOrder | Sequence[str] | None = None,
) -> list[PairedBean]:
    return SeverityAdjudicator(severity_order).adjudicate_pairs(pairs)


# ---------------------------------------------------------------------------
# CQI 计数规则（count_rule: most_severe_per_bean，一粒只计一次）
# ---------------------------------------------------------------------------


def count_defects(
    beans: Iterable[PairedBean], *, include_normal: bool = False
) -> dict[str, int]:
    """CQI 计数规则：每粒只按 ``final_defect`` 计一次的缺陷直方。

    本实现独立于契约 ``beaneye.schemas.defect_counts_from_beans``，
    两者一致性由 ``tests/test_severity.py`` 交叉验证。
    ``include_normal=False`` 时不含 "normal"（好豆不是缺陷）。
    """
    hist: dict[str, int] = {}
    for b in beans:
        if b.final_defect == "normal" and not include_normal:
            continue
        hist[b.final_defect] = hist.get(b.final_defect, 0) + 1
    return hist


def effective_defect_counts(
    beans: Iterable[PairedBean], taxonomy: Taxonomy | None = None
) -> dict[str, int]:
    """真正计入缺陷的直方：剔除 ``counts_as_defect=false`` 的类
    （peaberry 计量不计缺陷，仅标注保留，见 configs/taxonomy.yaml）。"""
    tax = taxonomy if taxonomy is not None else load_taxonomy()
    return {
        k: n for k, n in count_defects(beans).items() if tax.get(k).counts_as_defect
    }


def primary_secondary_counts(
    beans: Iterable[PairedBean], taxonomy: Taxonomy | None = None
) -> tuple[int, int]:
    """主/次缺陷粒数（GradingDecision.primary_count / secondary_count 的口径）。

    primary = final_defect 为 primary 类的粒数；secondary = secondary 类且
    counts_as_defect=true（peaberry 不计入）。
    """
    tax = taxonomy if taxonomy is not None else load_taxonomy()
    hist = effective_defect_counts(beans, tax)
    primary = sum(n for k, n in hist.items() if tax.get(k).kind == "primary")
    secondary = sum(n for k, n in hist.items() if tax.get(k).kind == "secondary")
    return primary, secondary
