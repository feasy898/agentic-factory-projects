"""契约层（beaneye/schemas.py）：观测/配对数据结构与契约侧裁决。

spec 依据（docs/assets/specs/severity.md）：
- §1：`defect_is_countable` 是唯一可计判据，M7 与契约共用；未知类别一律 False。
  `BeanObservation` 构造期即校验 defect 必须在 taxonomy（违规 ValidationError）；
  0=normal 是契约，缺陷类 rank 必须 >0（构造期强制）。
- §3：pairing_cost 两口径强制——单面（恰一面 None）与双 None 占位记录必须恰为 -1；
  双面齐全必须 >=0（mm 距离），传 -1 或任何负值即 ValidationError。
- §5：契约侧 `_resolve_worst` 在 `PairedBean` 校验器里每次构造都重跑——任何来源写入
  的 final_* 字段与两面观测不一致立即 ValidationError。比较的是观测的
  `severity_rank` 冻结存储字段（存储，不是缓存）。
- §4：契约直方 `defect_counts_from_beans` 缺省 include_normal=False（normal 不入直方）。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Optional, Sequence

from beaneye.taxonomy import load_taxonomy

__all__ = [
    "BeanMask",
    "BeanObservation",
    "PairedBean",
    "ValidationError",
    "defect_counts_from_beans",
    "defect_is_countable",
]


class ValidationError(ValueError):
    """契约校验失败（构造期拒绝）。"""


@dataclass(frozen=True)
class BeanMask:
    """单面豆粒掩码（几何字段由上游 M4 产出，此处只承载）。"""

    mask_id: str
    side: str
    polygon: Sequence[Sequence[float]]
    bbox_mm: Sequence[float]
    area_mm2: float
    centroid_mm: Sequence[float]
    source: str
    conf: float


@dataclass(frozen=True)
class BeanObservation:
    """单面观测（M5 分类输出）：defect + conf + severity_rank（冻结存储字段）。

    构造期契约校验（spec §1）：
    - defect 必须在 taxonomy classes 内，未知类别 ValidationError（纵深防御：
      合法链路不可能把未知类送进裁决）；
    - 0=normal 是契约：defect=normal 必须 severity_rank==0，缺陷类必须 >0。
    """

    obs_id: str
    side: str
    defect: str
    defect_conf: float
    severity_rank: int
    crop_path: str
    mask: BeanMask
    color_lab: Sequence[float]
    eq_diameter_mm: float

    def __post_init__(self) -> None:
        tax = load_taxonomy()
        if self.defect not in tax:
            raise ValidationError(
                f"未知缺陷类别 {self.defect!r}（不在 taxonomy classes）"
            )
        if self.defect == "normal":
            if self.severity_rank != 0:
                raise ValidationError("normal 的 severity_rank 必须为 0（0=normal 是契约）")
        elif self.severity_rank <= 0:
            raise ValidationError(
                f"缺陷类 {self.defect!r} 的 severity_rank 必须 >0，得到 {self.severity_rank}"
            )


def defect_is_countable(defect: str) -> bool:
    """唯一可计判据（契约与 M7 共用）：counts_as_defect；未知类别一律 False。"""
    return load_taxonomy().is_countable(defect)


def _resolve_worst(
    top: Optional[BeanObservation],
    bottom: Optional[BeanObservation],
) -> tuple[str, str, int]:
    """契约侧裁决（比较 severity_rank 冻结存储字段）。

    返回 (final_defect, worst_side, final_severity_rank)。规则与 M7 逐位一致：
    1. 两面皆 None → ("normal", "none", 0)
    2. 仅一面有观测 → 取该面
    3. 两面都有且存在可计缺陷面 → 只在可计面之间裁决（W13：peaberry 不吞次缺陷）
    4. 两面都非可计缺陷 → 退回全量比较（标注语义不丢失）
    5. rank 不等 → 高者胜
    6. rank 相等 → conf 高者，worst_side 记 "both"；conf 完全相等偏向 top
    """
    if top is None and bottom is None:
        return ("normal", "none", 0)
    if bottom is None:
        return (top.defect, "top", top.severity_rank)
    if top is None:
        return (bottom.defect, "bottom", bottom.severity_rank)

    faces = [("top", top), ("bottom", bottom)]
    pool = [(s, o) for s, o in faces if defect_is_countable(o.defect)]
    if not pool:
        pool = faces  # 两面皆非可计缺陷 → 全量比较（peaberry 标注不丢失）
    best = max(o.severity_rank for _, o in pool)
    pool = [(s, o) for s, o in pool if o.severity_rank == best]
    if len(pool) == 1:
        side, obs = pool[0]
        return (obs.defect, side, obs.severity_rank)
    # 并列（同序位=同缺陷）：conf 高者胜，完全相等偏向 top；worst_side 记 both
    (_, a), (_, b) = pool
    winner = a if a.defect_conf >= b.defect_conf else b
    return (winner.defect, "both", winner.severity_rank)


@dataclass(frozen=True)
class PairedBean:
    """一粒豆的配对与裁决结果（构造即校验，契约不变式）。"""

    bean_id: str
    top: Optional[BeanObservation]
    bottom: Optional[BeanObservation]
    pairing_cost: float
    final_defect: str
    worst_side: str
    final_severity_rank: int

    def __post_init__(self) -> None:
        # pairing_cost 两口径强制（spec §3 末）：两口径之间没有中间地带。
        sides = (self.top is not None) + (self.bottom is not None)
        if sides < 2:
            if self.pairing_cost != -1:
                raise ValidationError(
                    f"单面/双 None 占位记录 pairing_cost 必须恰为 -1，得到 {self.pairing_cost!r}"
                )
        else:
            if self.pairing_cost < 0:
                raise ValidationError(
                    f"双面齐全 pairing_cost 必须 >=0（mm 距离），得到 {self.pairing_cost!r}"
                )
        # 契约不变式：final_* 必须与两面观测的裁决一致（每次构造重跑 _resolve_worst）。
        expected = _resolve_worst(self.top, self.bottom)
        got = (self.final_defect, self.worst_side, self.final_severity_rank)
        if got != expected:
            raise ValidationError(
                f"PairedBean final_* 与两面观测不一致: {got} != 契约裁决 {expected}"
            )

    @classmethod
    def from_sides(
        cls,
        bean_id: str,
        top: Optional[BeanObservation],
        bottom: Optional[BeanObservation],
        pairing_cost: float,
    ) -> "PairedBean":
        """契约入口：按两面观测裁决并构造（校验器随后重跑核验）。"""
        final_defect, worst_side, rank = _resolve_worst(top, bottom)
        return cls(
            bean_id=bean_id,
            top=top,
            bottom=bottom,
            pairing_cost=pairing_cost,
            final_defect=final_defect,
            worst_side=worst_side,
            final_severity_rank=rank,
        )


def defect_counts_from_beans(
    beans: Sequence[PairedBean],
    include_normal: bool = False,
) -> dict[str, int]:
    """契约直方：每粒按 final_defect 计一次；缺省不含 normal 键（好豆不是缺陷）。"""
    hist: Counter[str] = Counter()
    for b in beans:
        if b.final_defect == "normal" and not include_normal:
            continue
        hist[b.final_defect] += 1
    return dict(hist)
