"""M5 分类包（plan/开发指令.md §4 M5）。

当前内容：``RulesV0``——规则表驱动的经典分类器（逐粒 LAB/几何/纹理特征 +
``configs/rules_v0.yaml`` 规则表 → 缺陷类别）；``NnOnnxClassifier``——批9
ONNX 分类头（τ 校准判决，见 ``beaneye.classify.nn_onnx``）。两者满足同一
冻结 ``ClsModel`` Protocol，可互换。

装配约定（``beaneye.app.components``）：本包暴露 ``build_default(**kwargs)``
工厂，应用壳探测到即可零改动接线。**``build_default()`` 缺省仍返回
RulesV0（产品缺省行为不变）**；NN 头按需显式构造并注入（如
``create_app(classify=NnOnnxClassifier("train/runs/crop_cls/b9.onnx"))``，
或实时侧 ``beaneye.realtime.build_classifier("nn", nn_onnx=…)``）。
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
from beaneye.classify.nn_onnx import DEFAULT_TAU, NnOnnxClassifier, NnOnnxError
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
    "NnOnnxClassifier",
    "NnOnnxError",
    "DEFAULT_TAU",
    "build_default",
]


def build_default(**kwargs) -> RulesV0:
    """M13 装配器接线约定：``<pkg>.build_default(**kwargs) -> ClsModel 实现``。"""
    return RulesV0(**kwargs)
