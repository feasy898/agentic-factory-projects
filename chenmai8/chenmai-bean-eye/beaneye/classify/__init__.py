"""M5 分类包（plan/开发指令.md §4 M5）。

当前内容：``RulesV0``——规则表驱动的经典分类器（逐粒 LAB/几何/纹理特征 +
``configs/rules_v0.yaml`` 规则表 → 缺陷类别）。``ONNXCls``（未来训练产物
``models/cls.onnx``）与 ``RFDETRJoint``（联合检测分类）按同一冻结
``ClsModel`` Protocol 后续并入本包。

装配约定（``beaneye.app.components``）：本包暴露 ``build_default(**kwargs)``
工厂，应用壳探测到即可零改动接线。
"""

from __future__ import annotations

from beaneye.classify.config import (
    DEFAULT_RULES_CONFIG_PATH,
    RULES_OPS,
    RuleCondition,
    RuleDef,
    RulesConfigError,
    RulesV0Config,
    load_rules_config,
)
from beaneye.classify.features import (
    FEATURE_NAMES,
    BeanFeatures,
    ColorRefs,
    FeatureParams,
    extract_features,
)
from beaneye.classify.rules import RulesV0

__all__ = [
    "RulesV0",
    "RulesV0Config",
    "RulesConfigError",
    "RuleDef",
    "RuleCondition",
    "RULES_OPS",
    "DEFAULT_RULES_CONFIG_PATH",
    "load_rules_config",
    "FeatureParams",
    "ColorRefs",
    "BeanFeatures",
    "FEATURE_NAMES",
    "extract_features",
    "build_default",
]


def build_default(**kwargs) -> RulesV0:
    """M13 装配器接线约定：``<pkg>.build_default(**kwargs) -> ClsModel 实现``。"""
    return RulesV0(**kwargs)
