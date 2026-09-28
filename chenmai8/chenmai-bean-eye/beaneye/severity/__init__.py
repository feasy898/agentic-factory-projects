"""M7 严重度裁决：每粒多缺陷取最严重（依 taxonomy/标准 YAML 严重度序）
+ CQI 计数规则（count_rule: most_severe_per_bean，一粒只计一次）。
"""

from beaneye.severity.adjudicate import (
    CQI_COUNT_RULE,
    SeverityAdjudicator,
    SeverityError,
    SeverityOrder,
    WorstResult,
    adjudicate_pairs,
    count_defects,
    default_severity_order,
    effective_defect_counts,
    primary_secondary_counts,
    worst,
    worst_detail,
)

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
