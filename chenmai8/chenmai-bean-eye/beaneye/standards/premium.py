"""精品/普通判定层（轨3 · premium_or_commercial）。

口径（轨3 spec）：
- **精品（premium）** = 严重缺陷（主缺陷）0 粒 **且** 一般缺陷（次缺陷）
  等效粒数 ≤5 —— CQI Fine Robusta 公开口径（v0 每粒 1 等效，1:1 计数）；
- **普通（commercial）** = 其余；
- 传入 DB46 法定表（:mod:`beaneye.standards.db46_legal`）时，同一输入上
  **附带给出 DB46/T 642—2024 法定理化等级**（如 ``理化一级``）；
- 判定理由沿用引擎模板键格式（``<键>:<k>=<v>;...``，键 [A-Za-z0-9_.]），
  未核对告警沿用 ``GradingDecision.warnings`` 机制透传；
- 大中小直方图（轨2）由 ``beaneye.metrology.size_bands`` 提供：可从逐粒
  ``PairedBean`` 计算（:func:`size_band_histogram`，每粒归属+占比），也可
  从 ``Measurements.sieve_hist`` 直接聚合（:func:`aggregate_sieve_hist`）。

本层与定级（``StandardEngineV1.evaluate``）**解耦**：分级回答「符合标准
哪一级」，本层回答「贸易上算精品还是普通」；两者可并存于同一护照。

入口：
- :func:`premium_or_commercial`：纯函数（计数 + 直方 + 水分占位 → 结论）；
- :func:`evaluate_premium`：整盘便捷入口（PairedBean + Measurements）；
  ``StandardEngineV1.evaluate_premium`` 方法即委托本函数。
"""

from __future__ import annotations

from beaneye.metrology.size_bands import (
    SizeBands,
    aggregate_sieve_hist,
    load_size_bands,
    size_band_histogram,
)
from beaneye.schemas import Measurements, PairedBean, PremiumDecision
from beaneye.severity import primary_secondary_counts
from beaneye.standards.db46_legal import DB46Legal, db46_legal_grade, load_db46_legal
from beaneye.standards.loader import Standard, load_standard

__all__ = [
    "DEFAULT_PREMIUM_BASIS_ID",
    "PREMIUM_PRIMARY_LIMIT",
    "PREMIUM_SECONDARY_EQUIV_LIMIT",
    "evaluate_premium",
    "premium_or_commercial",
]

# CQI Fine Robusta 公开口径（轨3 spec 给定）：样品 350 g；精品 = 0 严重缺陷
# + 次缺陷 ≤5；优质（Fine 下一档）= 总缺陷 ≤12；烘焙样 100 g 奎克豆
# 精品 ≤3 / 优质 ≤5；筛目参考 16 号（乌干达实施口径）。奎克/筛目/优质档
# 不进 v0 判定式（管线无烘焙样与杯测），完整口径见 docs/standards_matrix.md。
DEFAULT_PREMIUM_BASIS_ID = "cqi_fine_robusta"
PREMIUM_PRIMARY_LIMIT = 0  # 严重缺陷上限
PREMIUM_SECONDARY_EQUIV_LIMIT = 5.0  # 一般缺陷等效上限


def _reason(key: str, **kv: object) -> str:
    """拼一条理由：``模板键:k=v;k=v``（与 engine._reason 同格式）。"""
    payload = ";".join(f"{k}={v}" for k, v in kv.items())
    return f"{key}:{payload}" if payload else key


def premium_or_commercial(
    primary_count: int,
    secondary_count: int,
    size_band_hist: dict[str, int],
    *,
    bean_count: int,
    standard_id: str = DEFAULT_PREMIUM_BASIS_ID,
    primary_limit: int = PREMIUM_PRIMARY_LIMIT,
    secondary_equiv_limit: float = PREMIUM_SECONDARY_EQUIV_LIMIT,
    secondary_equiv_count: float | None = None,  # v0 缺省 1:1（= 计数）
    moisture_pct: float | None = None,
    size_band_frac: dict[str, float] | None = None,
    warnings: tuple[str, ...] | list[str] = (),
    grade_legal_db46: str | None = None,
    db46_reasons: list[str] | None = None,
) -> PremiumDecision:
    """精品/普通判定（纯函数）：严重/一般缺陷计数 + 大中小直方 + 水分占位。

    判定式（CQI 口径）：``verdict = premium`` 当且仅当
    ``primary_count <= primary_limit(0)`` 且
    ``secondary_equiv_count <= secondary_equiv_limit(5)``；否则 ``commercial``。
    水分为占位输入（v0 恒 None），仅随结论透出、不参与本判定式。
    """
    equiv = float(secondary_equiv_count) if secondary_equiv_count is not None else float(secondary_count)
    reasons: list[str] = []
    ok_primary = primary_count <= primary_limit
    ok_secondary = equiv <= secondary_equiv_limit
    reasons.append(
        _reason(
            "premium.reason.primary_within" if ok_primary else "premium.reason.primary_over",
            count=primary_count,
            limit=primary_limit,
        )
    )
    reasons.append(
        _reason(
            "premium.reason.secondary_within" if ok_secondary else "premium.reason.secondary_over",
            count=equiv,
            limit=secondary_equiv_limit,
        )
    )
    verdict = "premium" if (ok_primary and ok_secondary) else "commercial"
    reasons.append(_reason("premium.reason.verdict", verdict=verdict))
    # 大中小直方（信息性理由；判定式 v0 不消费筛段——CQI 口径的筛目为
    # 参考位（乌干达实施口径 16 号），待真实豆标定后升级为条件）
    reasons.append(
        _reason(
            "premium.reason.size_bands",
            **{k: size_band_hist.get(k, 0) for k in sorted(size_band_hist)},
        )
    )
    if moisture_pct is None:
        reasons.append("premium.reason.moisture_placeholder:moisture=none")
    else:
        reasons.append(_reason("premium.reason.moisture_note", moisture=f"{moisture_pct:g}"))
    if db46_reasons:
        reasons.extend(db46_reasons)
    return PremiumDecision(
        standard_id=standard_id,
        verdict=verdict,  # type: ignore[arg-type]
        primary_count=primary_count,
        secondary_count=secondary_count,
        secondary_equiv_count=equiv,
        primary_limit=primary_limit,
        secondary_equiv_limit=secondary_equiv_limit,
        size_band_hist=dict(size_band_hist),
        size_band_frac=dict(size_band_frac) if size_band_frac is not None else {},
        bean_count=bean_count,
        moisture_pct=moisture_pct,
        grade_legal_db46=grade_legal_db46,
        reasons=reasons,
        warnings=list(warnings),
    )


def evaluate_premium(
    beans: list[PairedBean],
    measurements: Measurements,
    *,
    basis: Standard | None = None,
    bands: SizeBands | None = None,
    db46_legal: DB46Legal | None | str = None,
    moisture_pct: float | None = None,
) -> PremiumDecision:
    """整盘精品/普通判定（便捷入口）。

    - 严重/一般缺陷计数：``severity.primary_secondary_counts``（与引擎同源，
      peaberry 不计缺陷）；
    - 大中小直方：优先从 ``measurements.sieve_hist`` 聚合（与逐粒归属恒一致，
      轨2 有测试钉住）；``size_band_frac`` 用逐粒占比（空盘全 0）；
    - ``basis``：精品阈值来源标准（缺省加载 ``cqi_fine_robusta``；阈值取其
      最优级 ``grades[0].primary_max / secondary_full_max``；若传入的标准
      最优级缺粒数轴（如 DB46 法定百分比档），防御性回退到缺省基准——
      精品口径按轨3 spec 恒为 CQI）；其未核对告警（``Standard.warnings``）
      透传到结论；
    - ``db46_legal``：``True``/``"db46"`` → 加载默认法定表；传路径 → 加载
      指定表；``None`` → 不计算 DB46 法定等级。
    """
    std = basis if basis is not None else load_standard(DEFAULT_PREMIUM_BASIS_ID)
    g0 = std.grades[0]
    if g0.primary_max is None or g0.secondary_full_max is None:
        # 传入基准缺粒数轴（如 DB46 法定百分比档）→ 回退 CQI 缺省基准
        std = load_standard(DEFAULT_PREMIUM_BASIS_ID)
        g0 = std.grades[0]
    sb = bands if bands is not None else load_size_bands()

    primary, secondary = primary_secondary_counts(beans)
    band_hist = aggregate_sieve_hist(measurements.sieve_hist, sb)
    per_bean = size_band_histogram(beans, sb)

    grade_legal: str | None = None
    db46_reasons: list[str] | None = None
    if db46_legal is not None:
        leg = load_db46_legal() if db46_legal is True else load_db46_legal(str(db46_legal)) if isinstance(db46_legal, str) else db46_legal
        grade_legal, db46_reasons = db46_legal_grade(
            primary,
            secondary,
            measurements.bean_count,
            measurements.sieve_hist,
            leg,
            moisture_pct=moisture_pct,
        )

    return premium_or_commercial(
        primary,
        secondary,
        band_hist,
        bean_count=measurements.bean_count,
        standard_id=std.standard_id,
        primary_limit=g0.primary_max,
        secondary_equiv_limit=float(g0.secondary_full_max),
        moisture_pct=moisture_pct,
        size_band_frac=dict(per_bean.frac),
        warnings=std.warnings,
        grade_legal_db46=grade_legal,
        db46_reasons=db46_reasons,
    )
