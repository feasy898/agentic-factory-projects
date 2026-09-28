"""审计存储：零明文硬闸（单事件 + 全库文件）+ 进程内事件表。

双层防线（§5.4 + §9 U5 + §11 风险 9）：
1. 入库前 :func:`assert_no_raw_pii`——用本次请求的敏感值列表断言
   （失败即 500 且不落库）；落库层（内存表 / SQLite 写队列）共用此闸。
   断言清单由调用方合并传入**归一化值 + 表面形式**两类（如 ``13900139000`` 与
   ``139 0013 9000`` 都要查，否则分隔符写法绕过硬闸）；并对恰好 500 字符截断的
   preview 做**截断边界守护**——尾部出现某敏感串的非空前缀即判定「切中」拒写；
2. 库文件级 :func:`assert_db_no_raw_pii`——对审计 SQLite 库文件（含 WAL/SHM
   旁挂文件）做 bytes 级 grep，任何原值命中即抛错；evals.m7_audit 与 e2e U5
   以此为最终口径；
3. 截断本身走 :func:`safe_preview`——截断点落在任一敏感串内部时回退到串起点，
   从源头保证入库 preview 不出现「半截敏感串」。

注意边界：全库文件断言只对**审计库**成立——masking_map 表按设计必须存归一化
原值才能还原，因此与会话存储分文件（见 masking/session_store.py 模块文档）。
"""
from __future__ import annotations

import threading
from collections import deque
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from audit.models import AuditEvent

#: SQLite WAL 模式的旁挂文件后缀（bytes 级扫描必须一并覆盖：新写入先落 -wal）
DB_SIDECAR_SUFFIXES: tuple[str, ...] = ("-wal", "-shm")


class RawPiiLeakError(ValueError):
    """零明文断言失败：审计面出现了本应被脱敏的原值。

    ``kind``：``masked_finding``（单事件 preview 命中）｜ ``db_file_scan``
    （库文件 bytes 级扫描命中）｜ ``truncated_sensitive``（截断点切中敏感串）。
    """

    def __init__(self, kind: str) -> None:
        self.kind = kind
        super().__init__(f"audit leaks raw value (gate={kind})")


#: preview 截断上限（与 audit.models.AuditEvent.prompt_preview/response_preview
#: 的 max_length 同源；改模型上限时同步此处）
PREVIEW_LIMIT = 500

#: 截断边界守护的最小敏感串长度（更短的串做「切中」判定误报面过大，不参与）
TRUNCATION_GUARD_MIN_LEN = 4


def assert_no_raw_pii(event: AuditEvent, normalized_values: Iterable[str],
                      surface_forms: Iterable[str] = ()) -> None:
    """零明文硬闸：preview 逐字符包含任一敏感值即抛错。

    - ``normalized_values``：归一化值（``13900139000``）；
    - ``surface_forms``：同一请求敏感实体的**表面形式**（``139 0013 9000``）——
      只查归一化串时分隔符写法会对不上而绕闸，故调用方必须两类合并传入
      （网关管线把两集合合并进 ``normalized_values`` 一个参数，写库层零改动）；
    - 截断边界守护：长度恰为 :data:`PREVIEW_LIMIT` 的 preview（盲截形态）若
      以任一敏感串的 ≥:data:`TRUNCATION_GUARD_MIN_LEN` 字符前缀结尾，判定
      截断点切中敏感串 → :class:`RawPiiLeakError("truncated_sensitive")`。
      经 :func:`safe_preview` 回退截断的 preview 短于上限，天然不触发。
    """
    values = [v for v in (*normalized_values, *surface_forms) if v]
    blob = "\n".join((event.prompt_preview, event.response_preview))
    for value in values:
        if value in blob:
            raise RawPiiLeakError("masked_finding")
    for preview in (event.prompt_preview, event.response_preview):
        if len(preview) != PREVIEW_LIMIT:
            continue
        for value in values:
            if len(value) <= TRUNCATION_GUARD_MIN_LEN:
                continue
            for k in range(min(len(value) - 1, len(preview)), TRUNCATION_GUARD_MIN_LEN - 1, -1):
                if preview.endswith(value[:k]):
                    raise RawPiiLeakError("truncated_sensitive")


def safe_preview(text: str, forbidden: Iterable[str], limit: int = PREVIEW_LIMIT) -> str:
    """截断到 ``limit`` 字符，且截断点不得落在任一敏感串内部。

    某敏感串的出现区间横跨截断点时，把截断点回退到该串起点（宁可少留不可留
    半截）；回退可能使更早的串重新横跨新截断点，故循环到不再变化为止。
    短于 ``limit`` 的文本原样返回（无截断即无切中）。
    """
    if len(text) <= limit:
        return text
    cut = limit
    values = [v for v in forbidden if v]
    changed = True
    while changed:
        changed = False
        for value in values:
            start = 0
            while True:
                idx = text.find(value, start, cut + len(value) - 1)
                if idx < 0:
                    break
                if idx < cut < idx + len(value):
                    cut = idx
                    changed = True
                    break
                start = idx + 1
    return text[:cut]


def scan_db_files(db_path: str | Path) -> bytes:
    """审计库主文件 + ``-wal``/``-shm`` 旁挂文件的原始字节拼接。

    WAL 模式下新提交的内容可能仍在 ``-wal`` 中尚未合入主文件——
    漏扫旁挂文件会漏掉最新写入，故三者一并纳入扫描对象。
    """
    main = Path(db_path)
    parts: list[bytes] = []
    for suffix in ("", *DB_SIDECAR_SUFFIXES):
        f = Path(str(main) + suffix)
        if f.exists():
            parts.append(f.read_bytes())
    return b"".join(parts)


def assert_db_no_raw_pii(db_path: str | Path, normalized_values: Iterable[str]) -> int:
    """全库文件 bytes 级零明文断言（§9 U5 最终口径）；返回扫描字节数。

    对库文件（含旁挂文件）逐个原值做 bytes 级 grep，任一命中即抛
    :class:`RawPiiLeakError(kind="db_file_scan")`。
    """
    blob = scan_db_files(db_path)
    hits = [v for v in normalized_values if v and v.encode("utf-8") in blob]
    if hits:
        raise RawPiiLeakError("db_file_scan")
    return len(blob)


class AuditSink(Protocol):
    """审计写入口的最小形状（网关管线依赖面；SQLite 写队列同样满足）。"""

    def append(self, event: AuditEvent,
               normalized_values: Iterable[str] = ()) -> AuditEvent: ...


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
