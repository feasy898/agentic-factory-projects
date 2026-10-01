"""会话存储：内存 LRU + SQLite 落盘双层 + TTL（开发指令 §5.3.3 / §8.4，T1.3）。

双层结构：
- 写路径：:class:`masking.mapper.SessionMapper` 首次插入新映射时经 ``on_insert``
  回调即时写 ``masking_map`` 表（INSERT OR REPLACE，主键 ``(session_id, placeholder)``）；
- 读路径：LRU 未命中（被换出/进程重启）→ 工厂按 ``session_id`` 从库中恢复
  **未过期**行（:meth:`SessionMapper.hydrate`），还原能力随即恢复；
- 会话稳定：占位符 = HMAC(key, session_id|type|normalized)，确定性——重启、
  换出、甚至 TTL 过期后同 session 同值再到达仍得到**同一占位符**，只是过期后
  映射行被删、还原能力失效（lookup 返回 None，占位符原样保留）；
- TTL：默认 24h（config ``session_ttl_h``）；:meth:`SessionStore.cleanup` 删过期行
  并换出空闲会话；:meth:`SessionStore.cleanup_loop` 为事件循环里的清理协程。

库文件边界（有意分文件）：``masking_map`` 按设计必须存归一化原值才能还原，
而审计库有 bytes 级全文件零明文断言（§9 U5 / audit.store.assert_db_no_raw_pii）
——两表不得同文件，故本存储持有独立 db 路径（config ``session_db``）。

线程模型：连接 ``check_same_thread=False`` + 内部锁（网关事件循环线程 get、
清理协程/eval 线程 cleanup 共用一把连接）。
"""
from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from common.logs import get_logger
from common.timeutil import iso_utc, parse_utc
from masking.mapper import SessionMapper, SessionRegistry
from masking.models import MappingEntry
from recognizers.models import EntityClass

log = get_logger(__name__)

#: masking_map 表 schema（§5.3.3 MappingEntry 行形状；字段只增不改名）
SCHEMA = """
CREATE TABLE IF NOT EXISTS masking_map (
  placeholder       TEXT    NOT NULL,
  type              TEXT    NOT NULL,
  normalized        TEXT    NOT NULL,
  first_seen        TEXT    NOT NULL,   -- 定长 UTC ISO8601（common.timeutil.iso_utc）
  session_id        TEXT    NOT NULL,
  preserve_semantic INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (session_id, placeholder)
);
CREATE INDEX IF NOT EXISTS idx_masking_map_first_seen ON masking_map(first_seen);
"""

#: TTL 缺省（config/app.yaml session_ttl_h=24）
DEFAULT_TTL = timedelta(hours=24)

_INSERT_SQL = (
    "INSERT OR REPLACE INTO masking_map "
    "(placeholder, type, normalized, first_seen, session_id, preserve_semantic) "
    "VALUES (?, ?, ?, ?, ?, ?)"
)
_SELECT_BY_SESSION_SQL = (
    "SELECT placeholder, type, normalized, first_seen, session_id, preserve_semantic "
    "FROM masking_map WHERE session_id = ? AND first_seen >= ? ORDER BY first_seen"
)


def connect_db(db_path: str | Path) -> sqlite3.Connection:
    """打开（必要时创建）WAL 模式的 SQLite 库并确保 schema 在位。"""
    path = Path(db_path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _row_to_entry(row: tuple) -> MappingEntry:
    return MappingEntry(
        placeholder=row[0], type=EntityClass(row[1]), normalized=row[2],
        first_seen=parse_utc(row[3]), session_id=row[4], preserve_semantic=bool(row[5]),
    )


class SessionStore:
    """占位符映射会话存储：LRU 注册表 + masking_map 落盘 + TTL 清理。

    对网关而言是 ``registry`` 的直接替代品（``store.get(session_id)`` 返回
    :class:`SessionMapper`，其余用法与进程内注册表完全一致）。
    """

    def __init__(self, key: bytes, db_path: str | Path, *, ttl: timedelta | None = None,
                 capacity: int = 1024) -> None:
        if not key:
            raise ValueError("masking key must be non-empty")
        self.ttl = ttl if ttl is not None else DEFAULT_TTL
        if self.ttl <= timedelta(0):
            raise ValueError(f"ttl must be positive, got {self.ttl}")
        self.db_path = Path(db_path)
        self._key = key
        self._conn = connect_db(self.db_path)
        self._sql_lock = threading.Lock()
        self._last_activity: dict[str, float] = {}   # session_id → time.monotonic()
        self._closed = False
        self.registry = SessionRegistry(key, capacity=capacity,
                                        mapper_factory=self._load_session)

    # ── 读路径（网关入口）────────────────────────────────────────
    def get(self, session_id: str) -> SessionMapper:
        """会话映射器（LRU 未命中时经工厂从库恢复未过期行）。"""
        self._last_activity[session_id] = time.monotonic()
        return self.registry.get(session_id)

    def _load_session(self, session_id: str) -> SessionMapper:
        """注册表工厂：构造空 mapper 并从库中恢复该会话未过期映射行。"""
        cutoff = iso_utc(datetime.now(UTC) - self.ttl)
        with self._sql_lock:
            rows = self._conn.execute(_SELECT_BY_SESSION_SQL, (session_id, cutoff)).fetchall()
        mapper = SessionMapper(session_id, self._key, on_insert=self._persist)
        restored = mapper.hydrate(_row_to_entry(r) for r in rows)
        if restored:
            log.info("session_store.hydrated", extra={
                "session_id": session_id, "entries": restored,
            })
        return mapper

    # ── 写路径（on_insert 回调，即时落盘）────────────────────────
    def _persist(self, entry: MappingEntry) -> None:
        if self._closed:
            return
        with self._sql_lock:
            self._conn.execute(_INSERT_SQL, (
                entry.placeholder, entry.type.value, entry.normalized,
                iso_utc(entry.first_seen), entry.session_id, int(entry.preserve_semantic),
            ))
            self._conn.commit()

    # ── TTL 清理 ────────────────────────────────────────────────
    def cleanup(self, *, now: datetime | None = None) -> int:
        """删除过期映射行（库+内存同口径）并换出空闲超 TTL 的会话；返回删除行数。"""
        now = now or datetime.now(UTC)
        cutoff_dt = now - self.ttl
        cutoff = iso_utc(cutoff_dt)
        with self._sql_lock:
            deleted = self._conn.execute(
                "DELETE FROM masking_map WHERE first_seen < ?", (cutoff,)).rowcount
            self._conn.commit()
        # 内存条目与落盘行同口径过期（活跃会话的旧条目也不能再还原）
        self.registry.apply(lambda m: m.purge_expired(cutoff_dt))
        idle_cutoff = time.monotonic() - self.ttl.total_seconds()
        stale = [sid for sid, seen in self._last_activity.items() if seen < idle_cutoff]
        if stale:
            stale_set = set(stale)
            self.registry.evict_where(lambda m: m.session_id in stale_set)
            for sid in stale:
                self._last_activity.pop(sid, None)
        if deleted:
            log.info("session_store.expired_rows_deleted", extra={"rows": deleted})
        return max(0, deleted)

    async def cleanup_loop(self, interval_s: float = 300.0) -> None:
        """TTL 清理协程（app lifespan 启动；取消即退出）。"""
        log.info("session_store.cleanup_loop.start", extra={
            "interval_s": interval_s, "ttl_s": self.ttl.total_seconds(),
        })
        while True:
            await asyncio.sleep(interval_s)
            try:
                self.cleanup()
            except sqlite3.Error as exc:  # 清理失败不致命，下轮重试
                log.error("session_store.cleanup_failed", extra={
                    "exc_type": type(exc).__name__,
                })

    # ── 观测/生命周期 ────────────────────────────────────────────
    def row_count(self) -> int:
        with self._sql_lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM masking_map").fetchone()[0])

    def __len__(self) -> int:
        return self.row_count()

    def close(self) -> None:
        self._closed = True
        with self._sql_lock:
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass
            self._conn.close()
