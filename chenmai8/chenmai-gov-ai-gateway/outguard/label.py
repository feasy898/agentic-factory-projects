"""AI 生成标识（开发指令 §5.6 / §6 M5）：文本尾注行 + ``annotations`` 元数据 + 响应头。

注入方式（§5.6 冻结）：
- **非流式**：``choices[0].message.content`` 尾部加标识行 +
  ``choices[0].message.annotations`` 字段（:func:`apply_message_label`）；
- **流式**：最后一个内容 delta 尾部标识行（实现：finish 前注入一个只含尾注的
  content delta，gateway/sse.py 组合管线）+ finish chunk
  ``choices[0].delta.annotations``——与非流式 ``message.annotations`` 同名同形；
- **响应头**：``x-anongw-ai-label: 1``（流式随 SSE 头下发，§6 M5）。

文案可配置：config/app.yaml ``ai_label``（默认「本内容由AI生成」）。
标识只加在**成功回答**上：BLOCK/上游错误的错误信封不是 AI 生成内容，不加。
"""
from __future__ import annotations

from typing import Any

#: AI 生成标识响应头（§6 M5：x-anongw-ai-label: 1）
HEADER_AI_LABEL = "x-anongw-ai-label"

#: annotations 元数据的注解类型值（§5.6；字段只增不改名）
AI_ANNOTATION_TYPE = "ai_generated"

#: annotations 元数据字段名（流式加在 delta、非流式加在 message，同名字段）
ANNOTATIONS_FIELD = "annotations"


def ai_label_tail(label: str) -> str:
    """标识行文本（作为内容尾部一行注入；含前导换行）。"""
    return "\n" + label


def ai_annotations(label: str) -> list[dict[str, str]]:
    """``annotations`` 元数据字段值（流式/非流式同形）。"""
    return [{"type": AI_ANNOTATION_TYPE, "text": label}]


def apply_message_label(message: dict[str, Any], label: str) -> None:
    """非流式注入（原地改写单个 message dict）：content 尾注 + annotations 字段。

    - ``content`` 为 str 时尾部追加标识行（含 content 为空串的情形——尾注独占一行）；
    - ``content`` 非 str（如纯工具调用响应的 null）不追加尾注，仅补 annotations
      元数据（标识语义仍在元数据面成立）；
    - 幂等：已有 ``annotations`` 键不覆盖、content 已以标识行结尾不重复追加
      （重复调用不叠加尾注）。
    """
    if ANNOTATIONS_FIELD not in message:
        message[ANNOTATIONS_FIELD] = ai_annotations(label)
    tail = ai_label_tail(label)
    if isinstance(message.get("content"), str) and not message["content"].endswith(tail):
        message["content"] = message["content"] + tail
