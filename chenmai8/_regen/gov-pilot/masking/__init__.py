"""M3 可逆脱敏包（masking-placeholder / masking-normalize spec，重生成实现）。

模块构成（本 pilot 范围 = evals.m3_masking 全部依赖）：
- ``models``    映射条目冻结形状（§5.3.3）
- ``mapper``    会话稳定占位符 + 可逆还原（§5.3.1）
- ``normalize`` 号码/写法归一化表（§5.3.2，见 masking-normalize spec）
- ``remap``     SSE 文本增量流式还原状态机（§5）
- ``toolbuf``   工具调用参数缓冲还原（§6）

会话存储落盘（spec §3–4：SQLite + LRU + TTL，evals.m7_audit C 节覆盖）不在本
pilot gate 范围；``SessionMapper(on_insert=...)`` 为写路径承接位。
"""
from __future__ import annotations

from masking.mapper import RESTORE_PATTERN, DIGEST_WIDTHS, SessionMapper
from masking.models import MappingEntry
from masking.normalize import normalize_digits, normalize_value, to_halfwidth
from masking.remap import MAX_PLACEHOLDER_LEN, StreamRestorer
from masking.toolbuf import (
    MAX_ARGUMENTS_CHARS,
    ToolArgumentsOverflowError,
    ToolCallBuffer,
    restore_arguments,
)

__all__ = [
    "DIGEST_WIDTHS",
    "MAX_ARGUMENTS_CHARS",
    "MAX_PLACEHOLDER_LEN",
    "MappingEntry",
    "RESTORE_PATTERN",
    "SessionMapper",
    "StreamRestorer",
    "ToolArgumentsOverflowError",
    "ToolCallBuffer",
    "normalize_digits",
    "normalize_value",
    "restore_arguments",
    "to_halfwidth",
]
