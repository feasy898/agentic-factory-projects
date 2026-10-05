"""契约最小面（severity 重生成所需）。

重生成实现依据：docs/assets/CONTRACTS.md C1.1（BeanMask）/ C1.2（BeanObservation）/
C2.4（PairedBean）/ C5（裁决与计数契约）+ docs/assets/specs/severity.md §1/§4。
完整契约（13 模型）不在本次重生成范围；本文件只实现 M7 冻结测试触达的模型与函数。

要点（severity spec §4）：
- ``_resolve_worst`` 是契约侧裁决：``PairedBean`` 校验器**每次构造都重跑**，
  任何来源写入的 ``final_*`` 与两面观测不一致立即 ``ValidationError``；
- ``defect_is_countable`` 是唯一可计判据，契约与 M7 severity 共用；
- ``defect_counts_from_beans`` 与 M7 ``count_defects`` 独立双实现，eval 交叉验证。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from beaneye.taxonomy import Taxonomy, load_taxonomy

__all__ = [
    "BeanMask",
    "BeanObservation",
    "PairedBean",
    "Side",
    "WorstSide",
    "defect_counts_from_beans",
    "defect_is_countable",
]

Side = Literal["top", "bottom"]
WorstSide = Literal["top", "bottom", "both", "none"]


def _taxonomy() -> Taxonomy:
    return load_taxonomy()


# ---------------------------------------------------------------------------
# C1.1 BeanMask（单面单粒几何；盘面毫米坐标系）
# ---------------------------------------------------------------------------


class BeanMask(BaseModel):
    """单面单粒几何（``extra="forbid"``：多余字段报错）。"""

    model_config = ConfigDict(extra="forbid")

    mask_id: str = Field(min_length=1)
    side: Side
    polygon: list[list[float]]
    bbox_mm: tuple[float, float, float, float]
    area_mm2: float = Field(ge=0)
    centroid_mm: tuple[float, float]
    source: Literal["oracle", "classic", "nn"]
    conf: float = Field(default=1.0, ge=0, le=1)

    @field_validator("polygon")
    @classmethod
    def _check_polygon(cls, v: list[list[float]]) -> list[list[float]]:
        if not v:
            raise ValueError("polygon 不能为空")
        for i, pt in enumerate(v):
            if len(pt) != 2:
                raise ValueError(f"polygon[{i}] 必须恰 2 个坐标")
        return v

    @field_validator("bbox_mm")
    @classmethod
    def _check_bbox(cls, v: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        x0, y0, x1, y1 = v
        if not (x0 <= x1 and y0 <= y1):
            raise ValueError("bbox_mm 必须 x0<=x1 且 y0<=y1")
        return v


# ---------------------------------------------------------------------------
# C1.2 BeanObservation（单面单粒观测：几何+类别+颜色+证据）
# ---------------------------------------------------------------------------


class BeanObservation(BaseModel):
    """单面单粒观测（defect 构造期校验必须在 taxonomy；lab8 单一标度）。"""

    model_config = ConfigDict(extra="forbid")

    obs_id: str = Field(min_length=1)
    side: Side
    defect: str
    defect_conf: float = Field(ge=0, le=1)
    severity_rank: int = Field(ge=0)
    crop_path: str = Field(min_length=1)
    mask: BeanMask
    color_lab: tuple[float, float, float]
    eq_diameter_mm: float = Field(gt=0)

    @field_validator("defect")
    @classmethod
    def _defect_in_taxonomy(cls, v: str) -> str:
        if v not in _taxonomy():
            raise ValueError(f"defect {v!r} 不在 taxonomy（非法类别）")
        return v

    @model_validator(mode="after")
    def _check_consistency(self) -> "BeanObservation":
        if self.obs_id != self.mask.mask_id:
            raise ValueError("obs_id 必须等于 mask.mask_id")
        if self.side != self.mask.side:
            raise ValueError("side 必须等于 mask.side")
        for i, ch in enumerate(self.color_lab):
            if not (0.0 <= ch <= 255.0):
                raise ValueError(f"color_lab[{i}]={ch} 越界（lab8 单一标度，三通道 ∈ [0,255]）")
        # 0=normal 是契约（severity spec §2）：normal 恒 0，缺陷类恒 >0
        if self.defect == "normal":
            if self.severity_rank != 0:
                raise ValueError("normal 的 severity_rank 恒为 0")
        elif self.severity_rank <= 0:
            raise ValueError(f"缺陷类 {self.defect!r} 的 severity_rank 必须 >0")
        return self


# ---------------------------------------------------------------------------
# C5 唯一可计判据（契约与 M7 共用）
# ---------------------------------------------------------------------------


def defect_is_countable(defect: str) -> bool:
    """类别是否计入缺陷计数：counts_as_defect=true 才可计。

    normal 与未知类别（不在 taxonomy）一律 False——severity spec §1：
    ``defect_is_countable`` 是唯一判据，M7 与契约共用。
    """
    if defect == "normal":
        return False
    return _taxonomy().counts_as_defect(defect)


# ---------------------------------------------------------------------------
# C5 契约侧裁决（与 M7 severity 逐位一致）
# ---------------------------------------------------------------------------


def _resolve_worst(
    top: BeanObservation | None,
    bottom: BeanObservation | None,
) -> tuple[str, WorstSide, int]:
    """契约裁决规则，返回 ``(final_defect, worst_side, final_severity_rank)``。

    逐条对照 CONTRACTS C5 与 severity spec §1：
    1. 两面皆 None → ("normal", "none", 0)；
    2. 仅一面有观测 → 取该面；
    3. 两面都有且存在可计缺陷面 → 只在可计面之间裁决（W13：peaberry 不吞可计缺陷）；
    4. 两面都有、皆非可计 → 退回全量比较（peaberry 标注语义不丢失）；
    5. rank 不等 → rank 高者胜，worst_side=胜面；
    6. rank 相等（同序位=同缺陷）→ conf 高者胜并记 worst_side="both"；
       conf 完全相等偏向 top（与 M7 逐位一致）。
    """
    if top is None and bottom is None:
        return ("normal", "none", 0)
    present = [(side, obs) for side, obs in (("top", top), ("bottom", bottom)) if obs is not None]
    if len(present) == 1:
        side, obs = present[0]
        return (obs.defect, side, obs.severity_rank)
    countable = [(side, obs) for side, obs in present if defect_is_countable(obs.defect)]
    pool = countable if countable else present
    if len(pool) == 1:
        side, obs = pool[0]
        return (obs.defect, side, obs.severity_rank)
    (t_side, t_obs), (b_side, b_obs) = pool
    if t_obs.severity_rank != b_obs.severity_rank:
        if t_obs.severity_rank > b_obs.severity_rank:
            return (t_obs.defect, t_side, t_obs.severity_rank)
        return (b_obs.defect, b_side, b_obs.severity_rank)
    winner = t_obs if t_obs.defect_conf >= b_obs.defect_conf else b_obs
    return (winner.defect, "both", winner.severity_rank)


# ---------------------------------------------------------------------------
# C2.4 PairedBean（配对后的一粒；「每粒只计最严重缺陷」的载体）
# ---------------------------------------------------------------------------


class PairedBean(BaseModel):
    """一粒豆的两面合成（final_* 三元组构造期与裁决规则逐位复核）。"""

    model_config = ConfigDict(extra="forbid")

    bean_id: str = Field(min_length=1)
    top: BeanObservation | None = None
    bottom: BeanObservation | None = None
    pairing_cost: float
    worst_side: WorstSide
    final_defect: str
    final_severity_rank: int

    @model_validator(mode="after")
    def _check_worst_matches_adjudication(self) -> "PairedBean":
        expect = _resolve_worst(self.top, self.bottom)
        got = (self.final_defect, self.worst_side, self.final_severity_rank)
        if got != expect:
            raise ValueError(
                f"final_* 三元组 {got} 与两面观测按契约裁决规则重算结果 {expect} 不一致"
            )
        if self.top is not None and self.bottom is not None:
            if self.pairing_cost < 0:
                raise ValueError("双面配对 pairing_cost 必须 >=0（mm 距离）")
        elif self.pairing_cost != -1.0:
            raise ValueError("单面/占位 pairing_cost 恒为 -1")
        return self

    @classmethod
    def from_sides(
        cls,
        bean_id: str,
        top: "BeanObservation | None",
        bottom: "BeanObservation | None",
        pairing_cost: float,
    ) -> "PairedBean":
        """规范构造入口：按契约裁决规则填 final_* 三元组。"""
        defect, side, rank = _resolve_worst(top, bottom)
        return cls(
            bean_id=bean_id,
            top=top,
            bottom=bottom,
            pairing_cost=pairing_cost,
            worst_side=side,
            final_defect=defect,
            final_severity_rank=rank,
        )


# ---------------------------------------------------------------------------
# C5 契约侧计数（与 M7 count_defects 独立双实现，eval 交叉验证）
# ---------------------------------------------------------------------------


def defect_counts_from_beans(
    beans: list[PairedBean],
    include_normal: bool = False,
) -> dict[str, int]:
    """契约侧直方：每粒按 ``final_defect`` 计一次（most_severe_per_bean）。

    normal 不入直方（``include_normal=True`` 才计）；实现刻意与 M7 侧
    （dict 累加 vs Counter）相互独立，一致由测试锁定。
    """
    hist: dict[str, int] = {}
    for bean in beans:
        key = bean.final_defect
        if key == "normal" and not include_normal:
            continue
        hist[key] = 1 + (hist[key] if key in hist else 0)
    return hist
