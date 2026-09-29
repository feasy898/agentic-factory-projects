"""M5 分类 RulesV0 · 规则表驱动的经典分类器（plan/开发指令.md §4 M5）。

满足冻结 ``ClsModel`` Protocol::

    classify(crop_rgba, mask) -> (defect, conf, severity_rank)

裁决语义（开发指令 M5 spec）：

- 规则表（``configs/rules_v0.yaml``）逐条评估：全部 ``when`` 条件 AND 命中
  即该规则命中，输出 ``(defect, conf)``；
- **多规则命中取 severity 高者**（severity_rank 从 taxonomy 读，单一真源）；
  平级取 conf 高者；
- 无规则命中 → normal（conf 取配置 ``defaults.normal_conf``，rank=0）；
- 特征提取退化（空 crop 等）→ normal、conf 0——分类器自身绝不抛异常阻塞
  管线（管线对输出另有契约校验，见 beaneye.app.pipeline._validate_cls_output）。

conf = 规则命中强度（规则表逐条配置的静态强度；不做逐条件裕度调制——
阈值是数据，回填走 YAML，见 D7 约定）。

``area_ratio`` 特征需要「盘内豆面积中位数」参考：本实现按调用顺序维护一个
滚动窗口（``FeatureParams.area_window``），已见粒数 ≥ ``area_min_ref`` 才
产出有效面积比，否则该特征为 −1（引用它的规则自然不命中）——单粒零散调用
时面积比规则静默失效是**记录在案的行为**，不是缺陷。
"""

from __future__ import annotations

import operator
from collections import deque

import numpy as np

from beaneye.classify.config import RuleDef, RulesV0Config, load_rules_config
from beaneye.classify.features import (
    BeanFeatures,
    ColorRefs,
    FeatureParams,
    extract_features,
    feature_value,
)
from beaneye.schemas import BeanMask
from beaneye.taxonomy import Taxonomy, load_taxonomy

__all__ = ["RulesV0"]


_OP = {
    "lt": operator.lt,
    "le": operator.le,
    "gt": operator.gt,
    "ge": operator.ge,
}


class RulesV0:
    """规则分类器 v0：LAB/几何/纹理特征 + YAML 规则表 → (defect, conf, rank)。"""

    stage = "classify"
    version = "rules_v0:v1"

    def __init__(
        self,
        cfg: RulesV0Config | None = None,
        taxonomy: Taxonomy | None = None,
    ) -> None:
        self.cfg = cfg if cfg is not None else load_rules_config()
        self.tax = taxonomy if taxonomy is not None else load_taxonomy()
        self._params: FeatureParams = self.cfg.feature_params
        self._refs: ColorRefs = self.cfg.color_refs
        self._area_window: deque[float] = deque(maxlen=int(self._params.area_window))

    # ------------------------------------------------------------------
    # ClsModel Protocol
    # ------------------------------------------------------------------

    def classify(self, crop_rgba: np.ndarray, mask: BeanMask) -> tuple[str, float, int]:
        """冻结协议入口：crop RGBA + BeanMask → (defect, conf, severity_rank)。"""
        defect, conf, rank, _hits = self._decide(crop_rgba, mask)
        return defect, conf, rank

    # ------------------------------------------------------------------
    # 扩展入口（评测/调试用；协议调用方不依赖）
    # ------------------------------------------------------------------

    def explain(
        self, crop_rgba: np.ndarray, mask: BeanMask
    ) -> tuple[str, float, int, list[str]]:
        """同 :meth:`classify`，另返回命中的规则列表（评测报告用）。"""
        return self._decide(crop_rgba, mask)

    def decide_features(self, feats: BeanFeatures) -> tuple[str, float, int, list[str]]:
        """对已提取的特征做规则裁决（评测脚本可复用同一裁决路径）。"""
        best: tuple[int, float, str, int] | None = None
        hits: list[str] = []
        for idx, rule in enumerate(self.cfg.rules):
            if not _rule_matches(rule, feats):
                continue
            hits.append(f"rules[{idx}]:{rule.defect}")
            rank = int(self.tax.severity_rank(rule.defect))
            cand = (rank, float(rule.conf), rule.defect, idx)
            if best is None or (cand[0], cand[1]) > (best[0], best[1]):
                best = cand
        if best is None:
            return "normal", float(self.cfg.normal_conf), 0, hits
        return best[2], best[1], best[0], hits

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _decide(
        self, crop_rgba: np.ndarray, mask: BeanMask
    ) -> tuple[str, float, int, list[str]]:
        area_ref = self._area_reference(float(mask.area_mm2))
        feats = extract_features(
            crop_rgba, mask, self._params, self._refs, area_ref=area_ref
        )
        if feats is None:
            return "normal", 0.0, 0, []
        return self.decide_features(feats)

    def _area_reference(self, area_mm2: float) -> float | None:
        """滚动窗口维护 + 面积比参考（中位数）；样本不足返回 None。"""
        self._area_window.append(float(area_mm2))
        if len(self._area_window) < int(self._params.area_min_ref):
            return None
        return float(np.median(np.asarray(self._area_window, dtype=np.float64)))


def _rule_matches(rule: RuleDef, feats: BeanFeatures) -> bool:
    for c in rule.when:
        if not _OP[c.op](feature_value(feats, c.feat), c.value):
            return False
    return True
