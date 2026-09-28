"""审计存储 v0：进程内事件表 + 零明文硬闸（SQLite/队列/查询由审计任务 M7 补全）。"""
from __future__ import annotations

import threading
from collections import deque
from collections.abc import Iterable

from audit.models import AuditEvent


class RawPiiLeakError(ValueError):
    """入库前断言失败：脱敏预览中出现了本次请求的原值（§5.4：失败即 500 且不落库）。"""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        super().__init__(f"audit preview leaks raw value of type {kind}")


def assert_no_raw_pii(event: AuditEvent, normalized_values: Iterable[str]) -> None:
    """零明文硬闸：preview 逐字符包含任一本请求 normalized 原值即抛错。

    断言面 = prompt_preview + response_preview（§5.4 口径：reasons 只存理由码、
    class_counts 只存类别计数，不含原值）。白名单值不在断言清单内（合法保留）。
    """
    blob = "\n".join((event.prompt_preview, event.response_preview))
    for value in normalized_values:
        if value and value in blob:
            raise RawPiiLeakError("masked_finding")


class InMemoryAuditStore:
    """进程内审计事件表（线程安全；容量上限防失控）。

    ``append`` 先跑 :func:`assert_no_raw_pii`，失败抛 :class:`RawPiiLeakError`
    且不落库；调用方（网关）将其映射为 500。
    """

    def __init__(self, capacity: int = 10_000) -> None:
        self._lock = threading.Lock()
        self._events: deque[AuditEvent] = deque(maxlen=max(1, capacity))

    def append(self, event: AuditEvent, normalized_values: Iterable[str] = ()) -> AuditEvent:
        values = list(normalized_values)
        assert_no_raw_pii(event, values)
        with self._lock:
            self._events.append(event)
        return event

    def snapshot(self) -> list[AuditEvent]:
        with self._lock:
            return list(self._events)

    def clear(self) -> int:
        with self._lock:
            cleared = len(self._events)
            self._events.clear()
            return cleared

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)
