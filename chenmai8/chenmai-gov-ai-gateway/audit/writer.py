"""审计落库（T1.3）：后台队列批量写 SQLite（WAL），请求路径不阻塞（§6 M7 / §8.5）。

结构：
- :meth:`SqliteAuditWriter.append` 在**入队前**同步跑零明文硬闸
  :func:`audit.store.assert_no_raw_pii`（§5.4：失败即 500 且不落库——
  未入队即未落库，异常向网关调用方传播，app 层映射 500）；
- 单写线程按 ``batch_size``/``flush_interval_s`` 批量 INSERT（单事务提交），
  ``PRAGMA journal_mode=WAL`` + ``synchronous=NORMAL``；队列饱和视为审计
  完整性事故，抛错拒写而非静默丢弃；
- 读取面（eval/e2e/后续 T5.1 查询 API 共用）：:meth:`count` /
  :meth:`fetch_all` / :meth:`journal_mode` / :meth:`checkpoint`，以及
  重开库直读的模块级 :func:`read_events` / :func:`count_events`；
- 生命周期：写线程随构造启动，:meth:`close` 排干队列后收尾（app lifespan 挂钩）。

红线：本库只存 :class:`AuditEvent`（脱敏预览，≤500 字符）——库文件须能通过
bytes 级全文件零明文扫描（audit.store.assert_db_no_raw_pii，§9 U5）。
"""
from __future__ import annotations

import json
import queue
import sqlite3
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from audit.models import AuditEvent
from audit.store import assert_no_raw_pii
from common.logs import get_logger
from common.timeutil import iso_utc, parse_utc

log = get_logger(__name__)

#: audit_events 表 schema（§5.4 AuditEvent 字段形状 + id 自增；字段只增不改名）
SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  ts               TEXT    NOT NULL,   -- 定长 UTC ISO8601（common.timeutil.iso_utc）
  request_id       TEXT    NOT NULL DEFAULT '',
  session_id       TEXT    NOT NULL DEFAULT '',
  dept             TEXT    NOT NULL DEFAULT '',
  route            TEXT    NOT NULL,
  blocked          INTEGER NOT NULL,
  reasons          TEXT    NOT NULL,   -- JSON 数组（理由码）
  class_counts     TEXT    NOT NULL,   -- JSON 对象（类别计数）
  prompt_preview   TEXT    NOT NULL DEFAULT '',
  response_preview TEXT    NOT NULL DEFAULT '',
  upstream         TEXT,
  latency_ms       INTEGER NOT NULL DEFAULT 0,
  flags            TEXT    NOT NULL    -- JSON 数组
);
CREATE INDEX IF NOT EXISTS idx_audit_events_ts ON audit_events(ts);
CREATE INDEX IF NOT EXISTS idx_audit_events_dept ON audit_events(dept);
"""

_INSERT_SQL = (
    "INSERT INTO audit_events (ts, request_id, session_id, dept, route, blocked, "
    "reasons, class_counts, prompt_preview, response_preview, upstream, latency_ms, flags) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
_ROW_SQL = (
    "SELECT id, ts, request_id, session_id, dept, route, blocked, reasons, class_counts, "
    "prompt_preview, response_preview, upstream, latency_ms, flags FROM audit_events ORDER BY id"
)


def connect_db(db_path: str | Path) -> sqlite3.Connection:
    """打开（必要时创建）WAL 模式的审计库并确保 schema 在位。"""
    path = Path(db_path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _event_to_row(event: AuditEvent) -> tuple:
    return (
        iso_utc(event.ts), event.request_id, event.session_id, event.dept,
        event.route, int(event.blocked),
        json.dumps(event.reasons, ensure_ascii=False),
        json.dumps(event.class_counts, ensure_ascii=False),
        event.prompt_preview, event.response_preview, event.upstream,
        event.latency_ms, json.dumps(event.flags, ensure_ascii=False),
    )


def _row_to_event(row: tuple[Any, ...]) -> AuditEvent:
    return AuditEvent(
        ts=parse_utc(row[1]), request_id=row[2], session_id=row[3], dept=row[4],
        route=row[5], blocked=bool(row[6]),
        reasons=json.loads(row[7]), class_counts=json.loads(row[8]),
        prompt_preview=row[9], response_preview=row[10], upstream=row[11],
        latency_ms=int(row[12]), flags=json.loads(row[13]),
    )


def count_events(db_path: str | Path) -> int:
    """重开库直读行数（eval 断言"关闭后数据仍在"用，不经任何存活实例）。"""
    conn = sqlite3.connect(str(db_path))
    try:
        return int(conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0])
    finally:
        conn.close()


def read_events(db_path: str | Path) -> list[tuple[int, AuditEvent]]:
    """重开库直读全部事件（按 id 升序）；元素 = (id, AuditEvent)。"""
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(_ROW_SQL).fetchall()
    finally:
        conn.close()
    return [(int(r[0]), _row_to_event(r)) for r in rows]


class SqliteAuditWriter:
    """审计写队列：append（同步硬闸+入队）→ 后台线程批量落 SQLite（WAL）。"""

    def __init__(self, db_path: str | Path, *, batch_size: int = 100,
                 flush_interval_s: float = 0.25, queue_max: int = 10_000,
                 put_timeout_s: float = 5.0) -> None:
        self.db_path = Path(db_path)
        self._conn = connect_db(self.db_path)
        self._sql_lock = threading.Lock()
        self.batch_size = max(1, batch_size)
        self.flush_interval_s = max(0.01, flush_interval_s)
        self.put_timeout_s = max(0.1, put_timeout_s)
        self._queue: queue.Queue[tuple[AuditEvent, list[str]]] = queue.Queue(
            maxsize=max(1, queue_max))
        self._stopping = threading.Event()
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="audit-writer", daemon=True)
        self._thread.start()

    # ── 写入口（网关审计路径）────────────────────────────────────
    def append(self, event: AuditEvent, normalized_values: Iterable[str] = ()) -> AuditEvent:
        """零明文硬闸（同步，失败即抛且不入队=不落库）→ 入队，立即返回不阻塞。"""
        values = list(normalized_values)
        assert_no_raw_pii(event, values)
        try:
            self._queue.put((event, values), timeout=self.put_timeout_s)
        except queue.Full as exc:
            # 审计完整性优先：拒写并向上抛（app 映射 500），绝不静默丢弃
            raise RuntimeError("audit write queue saturated; refusing to drop events") from exc
        return event

    # ── 后台写线程 ──────────────────────────────────────────────
    def _run(self) -> None:
        while True:
            items: list[tuple[AuditEvent, list[str]]] = []
            try:
                items.append(self._queue.get(timeout=self.flush_interval_s))
                while len(items) < self.batch_size:
                    items.append(self._queue.get_nowait())
            except queue.Empty:
                pass
            if items:
                try:
                    self._insert(items)
                except sqlite3.Error as exc:
                    log.error("audit.writer.insert_failed", extra={
                        "batch": len(items), "exc_type": type(exc).__name__,
                    })
                finally:
                    for _ in items:
                        self._queue.task_done()
            if self._stopping.is_set() and self._queue.empty():
                break

    def _insert(self, items: list[tuple[AuditEvent, list[str]]]) -> None:
        rows = [_event_to_row(event) for event, _ in items]
        with self._sql_lock:
            self._conn.executemany(_INSERT_SQL, rows)
            self._conn.commit()

    # ── 排干/观测/生命周期 ───────────────────────────────────────
    def flush(self, timeout_s: float = 5.0) -> bool:
        """等待队列全部落库；超时返回 False（eval/e2e 结算窗口用）。"""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self._queue.unfinished_tasks == 0:
                return True
            time.sleep(0.01)
        return self._queue.unfinished_tasks == 0

    def count(self) -> int:
        with self._sql_lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0])

    def __len__(self) -> int:
        return self.count()

    def fetch_all(self) -> list[tuple[int, AuditEvent]]:
        """全部已落库事件（按 id 升序）；元素 = (id, AuditEvent)。"""
        with self._sql_lock:
            rows = self._conn.execute(_ROW_SQL).fetchall()
        return [(int(r[0]), _row_to_event(r)) for r in rows]

    def journal_mode(self) -> str:
        with self._sql_lock:
            return str(self._conn.execute("PRAGMA journal_mode").fetchone()[0])

    def checkpoint(self) -> None:
        """WAL → 主文件合流（TRUNCATE；bytes 级扫描前调用确保口径完整）。"""
        with self._sql_lock:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def close(self, timeout_s: float = 5.0) -> None:
        if self._closed:
            return
        self._closed = True
        self._stopping.set()
        self._thread.join(timeout=timeout_s)
        with self._sql_lock:
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass
            self._conn.close()
