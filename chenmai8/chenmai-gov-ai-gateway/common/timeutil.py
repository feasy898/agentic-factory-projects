"""UTC 时间工具（工程约定：时间统一 UTC ISO8601 存储）。

SQLite 里时间戳按**定长**形态 ``YYYY-MM-DDTHH:MM:SS.ffffffZ`` 文本存储：
含微秒且长度恒定 → 字典序即时间序，TTL 过期清理可直接用字符串比较（不逐行解析）。
契约层（§5）示例的无微秒 ``...Z`` 形态在解析侧兼容。
"""
from __future__ import annotations

from datetime import UTC, datetime

#: 定长存储格式（strftime 后再补 'Z'）
UTC_STORE_FMT = "%Y-%m-%dT%H:%M:%S.%f"


def iso_utc(value: datetime) -> str:
    """datetime → 定长 UTC ISO8601 存储文本（naive 一律视为 UTC）。"""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime(UTC_STORE_FMT) + "Z"


def parse_utc(text: str) -> datetime:
    """存储文本（兼容无微秒的 ``...Z`` 契约形态）→ UTC aware datetime。"""
    v = text.strip()
    if v.endswith(("Z", "z")):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
