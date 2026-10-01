"""契约模型：脱敏映射条目 MappingEntry（开发指令 §5.3.3，冻结——字段只增不改名）。

masking 内部 + ``/internal/anonymize`` 输出使用。占位符算法（HMAC-SHA256 摘要、
碰撞升位）与归一化规则在 masking 包实现，不在本契约文件内。

会话存储（内存 LRU + SQLite 表 masking_map，TTL 默认 24h）由 masking/session_store
负责；本模型即落盘行的形状。
"""
from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, field_validator

from recognizers.models import EntityClass


class MappingEntry(BaseModel):
    """占位符 ↔ 原值映射的单条记录（§5.3.3 JSON 形状一字不差）。"""

    model_config = ConfigDict(extra="forbid")

    placeholder: str                          # 形如 〔手机号·9a1b2c3d〕
    type: EntityClass                         # 占位符中文标签取 EntityClass.label
    normalized: str                           # 归一化原值（等价写法 → 同占位符）
    first_seen: datetime                      # UTC ISO8601，序列化为 ...Z
    session_id: str
    preserve_semantic: bool = False           # 语义保留替换（P1）开启标志

    @field_validator("first_seen", mode="after")
    @classmethod
    def _utc_first_seen(cls, v: datetime) -> datetime:
        """naive datetime 一律视为 UTC（工程约定：时间统一 UTC ISO8601 存储）。"""
        return v.replace(tzinfo=UTC) if v.tzinfo is None else v
