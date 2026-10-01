"""契约模型 MappingEntry（gov2 盲实现，依据 masking-placeholder spec §3）。

§5.3.3 冻结形状，extra="forbid"，字段只增不改名。
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
    first_seen: datetime                      # UTC ISO8601
    session_id: str
    preserve_semantic: bool = False           # 语义保留替换（P1）预留位

    @field_validator("first_seen", mode="after")
    @classmethod
    def _utc_first_seen(cls, v: datetime) -> datetime:
        """naive datetime 一律视为 UTC（工程约定：时间统一 UTC ISO8601 存储）。"""
        return v.replace(tzinfo=UTC) if v.tzinfo is None else v
