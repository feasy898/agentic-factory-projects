"""看板存储层：SQLite 单文件持久化（开发指令 §5.7：文件 data/care.db）。

职责：
- 会话（MealSession）与单口记录（BiteRecord）的唯一持久化点；
- 事件流镜像表（供回放/取证，开发指令 §7 的 trace 思路在数据层落地）；
- 聚合统计（口数 / 时长 / 摄入克数 / 结局分布），供 HTTP 契约与 SSE 快照使用。

线程模型：uvicorn 单事件循环 + 锁保护，连接 check_same_thread=False，
测试线程与服务器线程共用本类亦安全。

领域错误（由 app 层映射为 HTTP 状态码）：
- NoActiveSessionError：无进行中会话时写入口记录/结束会话；
- DuplicateBiteError：同一会话内 bite_id 重复（防双计，保证"无丢失"语义）；
- ActiveSessionExistsError：已有进行中会话时再次 start。

克数聚合口径：全部单口都有 grams_before/grams_after 时，累计摄入 =
Σ max(0, grams_before - grams_after)（碗/勺减重）；任一缺失（无称重硬件）
则 total_grams=None（与契约 §3.1 "无称重硬件时为 None" 一致）。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

try:  # 以仓库根为 cwd（pytest / pythonpath=. / python -m chengshao.cs_dashboard）
    from chengshao.cs_schema import BiteRecord, MealSession
except ImportError:  # 以 chengshao/ 为 cwd（python -m cs_dashboard）
    from cs_schema import BiteRecord, MealSession  # type: ignore[no-redef]

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: 默认数据库文件：仓库根 data/care.db（data/ 已 gitignore，运行期数据不入库）
DEFAULT_DB_PATH = Path(
    os.environ.get("CS_DASHBOARD_DB", str(_REPO_ROOT / "data" / "care.db"))
)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    started_ns INTEGER NOT NULL,
    ended_ns   INTEGER
);
CREATE TABLE IF NOT EXISTS bites (
    session_id   TEXT NOT NULL REFERENCES sessions(session_id),
    bite_id      INTEGER NOT NULL,
    ts_start_ns  INTEGER NOT NULL,
    ts_end_ns    INTEGER NOT NULL,
    outcome      TEXT NOT NULL,
    grams_before REAL,
    grams_after  REAL,
    PRIMARY KEY (session_id, bite_id)
);
CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ns   INTEGER NOT NULL,
    kind    TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts_ns);
"""


class StoreError(Exception):
    """存储层领域错误基类。"""


class NoActiveSessionError(StoreError):
    """无进行中会话。"""


class ActiveSessionExistsError(StoreError):
    """已有进行中会话。"""


class DuplicateBiteError(StoreError):
    """同会话内 bite_id 重复。"""


class Store:
    """SQLite 看板存储（线程安全）。"""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.db_path), check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(_SCHEMA_SQL)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- 会话 ---------------------------------------------------------------

    def start_session(
        self,
        user_id: str,
        started_ns: int | None = None,
        session_id: str | None = None,
    ) -> MealSession:
        """新开进餐会话；已有进行中会话则拒绝（避免看板口径串味）。"""
        started_ns = time.time_ns() if started_ns is None else started_ns
        session_id = session_id or f"sess-{started_ns}-{uuid.uuid4().hex[:8]}"
        with self._lock:
            if self._active_row() is not None:
                raise ActiveSessionExistsError("已有进行中的会话，不能重复开始")
            self._conn.execute(
                "INSERT INTO sessions(session_id, user_id, started_ns) VALUES (?,?,?)",
                (session_id, user_id, started_ns),
            )
            self._record_event("session_started", {"session_id": session_id, "user_id": user_id})
            self._conn.commit()
        return MealSession(session_id=session_id, user_id=user_id, started_ns=started_ns)

    def end_session(self, ended_ns: int | None = None) -> MealSession:
        """结束当前进行中会话（ended_ns 缺省取当前时间）。"""
        ended_ns = time.time_ns() if ended_ns is None else ended_ns
        with self._lock:
            row = self._active_row()
            if row is None:
                raise NoActiveSessionError("没有进行中的会话")
            self._conn.execute(
                "UPDATE sessions SET ended_ns=? WHERE session_id=?",
                (ended_ns, row["session_id"]),
            )
            self._record_event(
                "session_ended", {"session_id": row["session_id"], "ended_ns": ended_ns}
            )
            self._conn.commit()
        session = self._row_to_session(row)
        return session.model_copy(update={"ended_ns": ended_ns})

    def active_session(self) -> MealSession | None:
        """当前进行中的会话（无则 None）。"""
        with self._lock:
            row = self._active_row()
            return None if row is None else self._row_to_session(row)

    def current_session(self) -> MealSession | None:
        """看板展示对象：进行中会话；若都已结束，取最近一餐（按开始时间）。"""
        with self._lock:
            row = self._active_row()
            if row is None:
                row = self._conn.execute(
                    "SELECT * FROM sessions ORDER BY started_ns DESC LIMIT 1"
                ).fetchone()
            return None if row is None else self._row_to_session(row)

    # ---- 单口 ---------------------------------------------------------------

    def add_bite(self, record: BiteRecord, session_id: str | None = None) -> str:
        """向进行中会话写入单口记录；返回会话 id。

        契约（§3.2）POST /api/bite 的 body 为裸 BiteRecord（无会话字段），
        归属即当前进行中会话；session_id 参数仅供内部/测试显式指定。
        """
        with self._lock:
            if session_id is None:
                row = self._active_row()
                if row is None:
                    raise NoActiveSessionError("没有进行中的会话，先 POST /api/session/start")
                session_id = row["session_id"]
            exists = self._conn.execute(
                "SELECT 1 FROM bites WHERE session_id=? AND bite_id=?",
                (session_id, record.bite_id),
            ).fetchone()
            if exists is not None:
                raise DuplicateBiteError(
                    f"会话 {session_id} 内 bite_id={record.bite_id} 已存在"
                )
            self._conn.execute(
                "INSERT INTO bites(session_id, bite_id, ts_start_ns, ts_end_ns,"
                " outcome, grams_before, grams_after) VALUES (?,?,?,?,?,?,?)",
                (
                    session_id,
                    record.bite_id,
                    record.ts_start_ns,
                    record.ts_end_ns,
                    str(record.outcome.value),
                    record.grams_before,
                    record.grams_after,
                ),
            )
            self._record_event(
                "bite",
                {
                    "session_id": session_id,
                    "bite": record.model_dump(mode="json"),
                },
            )
            self._conn.commit()
        return session_id

    # ---- 聚合 ---------------------------------------------------------------

    def summary(self, session: MealSession | None = None) -> dict[str, Any]:
        """看板聚合（§5.7：口数 / 时长 / 克数 / 结局分布）。

        duration_s：已结束会话 = 结束-开始；进行中 = 当前时间-开始（实数秒）。
        """
        with self._lock:
            session = self.current_session() if session is None else session
            if session is None:
                return {"session": None}
            rows = self._conn.execute(
                "SELECT * FROM bites WHERE session_id=? ORDER BY bite_id",
                (session.session_id,),
            ).fetchall()
            outcomes = {"success": 0, "retry": 0, "rejected": 0, "aborted": 0}
            grams_pairs: list[tuple[float, float]] = []
            for r in rows:
                outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
                if r["grams_before"] is not None and r["grams_after"] is not None:
                    grams_pairs.append((r["grams_before"], r["grams_after"]))
            total_grams: float | None = (
                sum(max(0.0, b - a) for b, a in grams_pairs) if grams_pairs else None
            )
            if len(grams_pairs) != len(rows):
                total_grams = None  # 任一单口缺称重 → 聚合口径为 None
            reference_ns = session.ended_ns if session.ended_ns is not None else time.time_ns()
            duration_s = max(0.0, (reference_ns - session.started_ns) / 1e9)
            return {
                "session_id": session.session_id,
                "user_id": session.user_id,
                "started_ns": session.started_ns,
                "ended_ns": session.ended_ns,
                "bite_count": len(rows),
                "outcomes": outcomes,
                "total_grams": total_grams,
                "duration_s": round(duration_s, 3),
                "last_bite_end_ns": max((r["ts_end_ns"] for r in rows), default=None),
            }

    def recent_events(self, limit: int = 100) -> list[dict[str, Any]]:
        """事件流镜像（倒序，回放/取证用）。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts_ns, kind, payload FROM events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"ts_ns": r["ts_ns"], "kind": r["kind"], "payload": json.loads(r["payload"])}
            for r in rows
        ]

    # ---- 内部 ---------------------------------------------------------------

    def _active_row(self) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM sessions WHERE ended_ns IS NULL ORDER BY started_ns DESC LIMIT 1"
        ).fetchone()

    def _row_to_session(self, row: sqlite3.Row) -> MealSession:
        bites = self._conn.execute(
            "SELECT * FROM bites WHERE session_id=? ORDER BY bite_id",
            (row["session_id"],),
        ).fetchall()
        return MealSession(
            session_id=row["session_id"],
            user_id=row["user_id"],
            started_ns=row["started_ns"],
            ended_ns=row["ended_ns"],
            bites=[
                BiteRecord(
                    bite_id=b["bite_id"],
                    ts_start_ns=b["ts_start_ns"],
                    ts_end_ns=b["ts_end_ns"],
                    outcome=b["outcome"],
                    grams_before=b["grams_before"],
                    grams_after=b["grams_after"],
                )
                for b in bites
            ],
            total_grams=None,  # 聚合口径见 summary()；MealSession 字段留给有称重的上游填
        )

    def _record_event(self, kind: str, payload: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO events(ts_ns, kind, payload) VALUES (?,?,?)",
            (time.time_ns(), kind, json.dumps(payload, ensure_ascii=False)),
        )


__all__ = [
    "DEFAULT_DB_PATH",
    "ActiveSessionExistsError",
    "DuplicateBiteError",
    "NoActiveSessionError",
    "Store",
    "StoreError",
]
