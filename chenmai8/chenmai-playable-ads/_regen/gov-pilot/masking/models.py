"""M3 映射条目模型（masking-placeholder spec §5.3.3，冻结形状）。

重生成实现说明：原模块为 pydantic 模型（``extra="forbid"``，字段只增不改名）；
本实现为无三方依赖的 frozen dataclass，字段集与 JSON 形状一致，
``from_dict``/``to_dict`` 负责边界校验（未知键拒绝 = extra="forbid" 语义）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, fields

_FIELDS = ("placeholder", "type", "normalized", "first_seen", "session_id", "preserve_semantic")


@dataclass(frozen=True, slots=True)
class MappingEntry:
    """会话映射条目：占位符 ↔ 归一化原值（归一化原值只进 masking_map，永不进审计库）。"""

    placeholder: str
    type: str
    normalized: str
    first_seen: str
    session_id: str
    preserve_semantic: bool = field(default=False)

    def to_dict(self) -> dict:
        return {
            "placeholder": self.placeholder,
            "type": self.type,
            "normalized": self.normalized,
            "first_seen": self.first_seen,
            "session_id": self.session_id,
            "preserve_semantic": self.preserve_semantic,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> "MappingEntry":
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:  # extra="forbid"：字段只增不改名，未知键即形状违约
            raise ValueError(f"unknown MappingEntry fields: {sorted(unknown)}")
        missing = known - set(data)
        if missing - {"preserve_semantic"}:
            raise ValueError(f"missing MappingEntry fields: {sorted(missing)}")
        return cls(
            placeholder=data["placeholder"],
            type=data["type"],
            normalized=data["normalized"],
            first_seen=data["first_seen"],
            session_id=data["session_id"],
            preserve_semantic=bool(data.get("preserve_semantic", False)),
        )


__all__ = ["MappingEntry"]
