"""BeanEye · 契约包（M1）。

公开入口：数据契约模型（beaneye.schemas）与缺陷分类体系加载器
（beaneye.taxonomy）。契约 v1.0 冻结：字段只增不改名。
"""

from beaneye import schemas, taxonomy
from beaneye.schemas import (
    AgentReport,
    BatchResult,
    BeanMask,
    BeanObservation,
    BeanEyeBaseModel,
    CalibResult,
    CameraSource,
    CauseItem,
    ClsModel,
    GradingDecision,
    Measurements,
    PairedBean,
    PassportReport,
    RootCauseAgent,
    SCHEMA_VERSION,
    SegModel,
    SegResult,
    StandardEngine,
    StatsSummary,
    TrayScan,
    defect_counts_from_beans,
)

__version__ = "1.0.0"

__all__ = [
    "__version__",
    "SCHEMA_VERSION",
    "schemas",
    "taxonomy",
    "BeanEyeBaseModel",
    "CalibResult",
    "BeanMask",
    "SegResult",
    "BeanObservation",
    "PairedBean",
    "TrayScan",
    "StatsSummary",
    "Measurements",
    "GradingDecision",
    "CauseItem",
    "AgentReport",
    "PassportReport",
    "BatchResult",
    "SegModel",
    "ClsModel",
    "StandardEngine",
    "RootCauseAgent",
    "CameraSource",
    "defect_counts_from_beans",
]
