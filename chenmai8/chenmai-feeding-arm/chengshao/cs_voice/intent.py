"""意图解析：ASR 文本 → 契约 ``VoiceIntent``（关键词规则，离线、可解释）。

规则要点：
- 归一化后做包含匹配（去空白/标点），同句命中多条时按规则表顺序取最优先
  （done > select > pause > next > resume > greet）；
- select 的槽位 ``slots["dish"]`` 只取自预注册菜名表（契约约束，
  缺省表为 ``DEFAULT_DISH_REGISTRY``，可经 config 扩展）；
- 未命中返回 ``unknown``（置信度低但结果仍合法，供行为树记录）。

已知局限（文档化）：否定句/复杂从句不在关键词规则能力内
（如"我不想吃芋泥了"会被解析为 select），由行为树的确认策略兜底。
"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

from ._compat import schema_constants, schema_enums, schema_models

if TYPE_CHECKING:  # 仅注解用：契约模型（运行时经 _compat 动态获取）
    from chengshao.cs_schema import VoiceIntent

# 归一化：只去空白与标点（保留全部汉字，避免误伤关键词）
_NORMALIZE = re.compile(r"[\s，。！？、,.!?~～…]+")

# 命中置信度（无校准信号可用，取保守常数；ASR 端未提供逐句置信度）
_CONF_HIT = 0.95
_CONF_SELECT = 0.90
_CONF_UNKNOWN = 0.30

# 规则表：intent -> 关键词（顺序即优先级）
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("done", ("吃饱了", "吃饱", "吃不下了", "不吃了", "饱了")),
    ("pause", ("等一下", "暂停", "等一等", "等等", "停一下", "别动", "慢一点")),
    ("next", ("下一口", "再来一口", "来一口", "喂我", "接着喂下一口")),
    ("resume", ("继续", "接着来", "可以了", "接着喂")),
    ("greet", ("你好", "您好", "在吗", "嗨")),
)

# select 触发词（菜名命中即触发，触发词仅用于置信度分档）
_SELECT_CUES = ("我想吃", "想吃", "来点", "要吃", "换个", "换")


class IntentParser:
    """关键词意图解析器。线程安全（无共享可变状态）。"""

    def __init__(self, dish_registry: tuple[str, ...] | None = None) -> None:
        if dish_registry is None:
            dish_registry = tuple(schema_constants().DEFAULT_DISH_REGISTRY)
        if not dish_registry:
            raise ValueError("dish_registry 不能为空")
        self.dish_registry: tuple[str, ...] = tuple(dish_registry)

    # -- 公开接口 ----------------------------------------------------------

    def parse(self, text: str, ts_ns: int | None = None,
              confidence: float | None = None) -> "VoiceIntent":
        """解析一句识别文本，返回 ``VoiceIntent``（契约模型）。"""
        models = schema_models()
        enums = schema_enums()
        ts = time.time_ns() if ts_ns is None else ts_ns
        norm = _NORMALIZE.sub("", text or "")

        intent, slots, conf = enums.IntentKind.UNKNOWN, {}, _CONF_UNKNOWN
        if norm:
            hit = self._match(norm)
            if hit is not None:
                kind, extra_conf = hit
                intent = enums.IntentKind(kind)
                conf = extra_conf
            else:
                dish, cue = self._match_dish(norm)
                if dish is not None:
                    intent = enums.IntentKind.SELECT
                    slots = {"dish": dish}
                    conf = _CONF_SELECT if cue else 0.75

        return models.VoiceIntent(
            ts_ns=ts,
            intent=intent,
            slots=slots,
            confidence=confidence if confidence is not None else conf,
        )

    # -- 内部 --------------------------------------------------------------

    def _match(self, norm: str) -> tuple[str, float] | None:
        for kind, keywords in _RULES:
            for kw in keywords:
                if kw in norm:
                    return kind, _CONF_HIT
        return None

    def _match_dish(self, norm: str) -> tuple[str | None, bool]:
        for dish in self.dish_registry:
            if dish in norm:
                return dish, any(cue in norm for cue in _SELECT_CUES)
        return None, False
