"""输出侧防护（M5，开发指令 §6）：AI 生成标识、拦截代答/拒答文案库、输出审核钩子。

模块地图：
- :mod:`outguard.label` —— AI 生成标识：非流式 content 尾注 + ``annotations``
  元数据（:func:`apply_message_label`）、流式尾注 delta + finish chunk 元数据
  （gateway/sse.py 组合管线调用）、响应头 ``x-anongw-ai-label``；
- :mod:`outguard.fallback` —— 拦截文案库：config/outguard_texts.yaml 加载、
  reason code 模板回退（:func:`block_message`）、关键词代答（:func:`canned_answer`）；
- :mod:`outguard.moderation` —— 输出侧复检钩子：``moderate(response)`` 接口
  （P0 always-safe 空后端；P1 语义审核模型采样执行）；
- :mod:`outguard.service` —— :class:`OutguardService` 门面（gateway 唯一依赖面）。
"""
from outguard.label import (
    AI_ANNOTATION_TYPE,
    ANNOTATIONS_FIELD,
    HEADER_AI_LABEL,
    ai_annotations,
    ai_label_tail,
    apply_message_label,
)
from outguard.models import CannedEntry, ModerationVerdict, OutguardTexts
from outguard.service import OutguardService

__all__ = [
    "AI_ANNOTATION_TYPE",
    "ANNOTATIONS_FIELD",
    "HEADER_AI_LABEL",
    "CannedEntry",
    "ModerationVerdict",
    "OutguardService",
    "OutguardTexts",
    "ai_annotations",
    "ai_label_tail",
    "apply_message_label",
]
