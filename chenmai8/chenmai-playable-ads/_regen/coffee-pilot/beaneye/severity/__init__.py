"""M7 严重度裁决（重生成实现，唯一依据 docs/assets/specs/severity.md + CONTRACTS C5）。

规则核心：每粒只计最严重缺陷——rank 高者胜、平级取 conf 高并记 ``worst_side="both"``
（conf 完全相等偏向 top）、非可计缺陷类（counts_as_defect=false，peaberry）不参与
比较。与契约侧 ``beaneye.schemas._resolve_worst`` 逐位一致，共用
``defect_is_countable`` 唯一判据。
"""

from beaneye.severity.adjudicate import (
    CQI_COUNT_RULE,
    WorstDetail,
    SeverityAdjudicator,
    SeverityError,
    SeverityOrder,
    adjudicate_pairs,
    count_defects,
    default_severity_order,
    effective_defect_counts,
    primary_secondary_counts,
    rebase_observation,
    worst,
    worst_detail,
)

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
