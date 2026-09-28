"""outguard 内部模型：文案库形状与输出审核判定（包内契约，仅 gateway 消费）。

与 §5 冻结契约的区别：本文件形状属 outguard 包内部接口（字段只增不改名的
纪律同样遵守，但不在 §5 冻结面内）；跨模块边界只有 gateway → outguard 的
服务调用（outguard/service.py）。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CannedEntry(BaseModel):
    """单条代答：关键词组 → 固定口径问答（MVP 关键词子串匹配，P2 升级语义匹配）。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    keywords: list[str] = Field(min_length=1)
    answer: str = Field(min_length=1)


class OutguardTexts(BaseModel):
    """拦截代答/拒答文案库（``config/outguard_texts.yaml`` 的加载形状）。

    - ``block_default``：决定性 reason code 未配置模板时的兜底拒答文案；
    - ``block_by_code``：reason code → 拒答模板（密级→保密提示卡、注入→安全提示、
      输出复检→复检拦截提示）；
    - ``canned``：代答条目表（条目序即匹配优先级，首个命中生效）。
    """

    model_config = ConfigDict(extra="forbid")

    block_default: str
    block_by_code: dict[str, str] = Field(default_factory=dict)
    canned: list[CannedEntry] = Field(default_factory=list)


class ModerationVerdict(BaseModel):
    """输出侧复检判定（词汇与语义审核适配器一致：``safe | flagged``）。

    ``flagged`` → 网关按 content_blocked 拦截本次响应（reasons code=
    ``OUTPUT_MODERATION``）；P0 空后端恒 ``safe``，主链路零影响。
    """

    model_config = ConfigDict(extra="forbid")

    verdict: Literal["safe", "flagged"] = "safe"
    categories: list[str] = Field(default_factory=list)   # 风险类目（面向审计/日志，非原文）
    detail: str = ""                                      # 后端自由文本说明
