"""SQLite 持久层: 任务状态机 + 候选 + API 用量 + 事件日志。

- WAL 模式 + busy_timeout + 每操作短事务 + 进程内锁 => 并发安全。
- 状态机: pending→generating→gating→accepted|retrying→fallback→composed;
  另有 pending/generating→blocked (源图缺失)。非法迁移拒绝 (IllegalTransition)。
- 迁移只新增: schema_migrations 记录已应用版本, 迁移体只允许 CREATE TABLE IF NOT EXISTS / ALTER TABLE ADD COLUMN。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

STATUSES = ("pending", "generating", "gating", "accepted", "retrying", "fallback", "composed", "blocked")

TRANSITIONS: dict[str, set[str]] = {
    "pending": {"generating", "blocked"},
    "generating": {"gating", "blocked"},
    "gating": {"accepted", "retrying"},
    "retrying": {"generating", "fallback"},
    "accepted": {"composed"},
    "fallback": {"composed"},
    "composed": set(),
    "blocked": set(),
}

TASK_UPDATABLE = ("attempts", "seed", "steps", "vram_peak_mb", "duration_s", "template", "hint_json", "error")

_MIGRATION_V1 = [
    """CREATE TABLE IF NOT EXISTS tasks(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        shot_id TEXT NOT NULL UNIQUE,
        narrative_slot TEXT NOT NULL,
        lane TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,
        seed INTEGER,
        steps INTEGER,
        vram_peak_mb REAL,
        duration_s REAL,
        updated_at TEXT NOT NULL,
        card_json TEXT NOT NULL DEFAULT '{}',
        template TEXT,
        hint_json TEXT,
        error TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS candidates(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        shot_id TEXT NOT NULL,
        path TEXT NOT NULL,
        gate_json TEXT NOT NULL DEFAULT '{}',
        overall_score REAL,
        verdict TEXT NOT NULL DEFAULT 'pending',
        selected INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS api_usage(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        capability TEXT NOT NULL,
        route TEXT NOT NULL CHECK(route IN ('api','local')),
        success INTEGER NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS events(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        level TEXT NOT NULL,
        msg TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_candidates_shot ON candidates(shot_id)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)",
]

# M5: 成片台账 — compose-video 显式合成的成片清单与每镜头候选追溯 (SPECS §10 门禁明细可追溯)
_MIGRATION_V2 = [
    """CREATE TABLE IF NOT EXISTS m5_videos(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id TEXT NOT NULL UNIQUE,
        template_id TEXT NOT NULL,
        spec_json TEXT NOT NULL DEFAULT '{}',
        shots_json TEXT NOT NULL DEFAULT '[]',
        path TEXT,
        g6_json TEXT,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_m5_videos_template ON m5_videos(template_id)",
]

# V2-M1: 夹具库(M0 建于主库的表收编进迁移, 沙箱新建即有) + G7 每子项分数表 (SPECS_V2 §2/§3)
_MIGRATION_V3 = [
    """CREATE TABLE IF NOT EXISTS fixtures(
        fixture_id TEXT PRIMARY KEY,
        path TEXT NOT NULL,
        label TEXT NOT NULL,
        category TEXT,
        human_source TEXT,
        notes TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS g7_runs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fixture_id TEXT NOT NULL,
        sub TEXT NOT NULL,
        score REAL,
        triggered INTEGER NOT NULL DEFAULT 0,
        skipped INTEGER NOT NULL DEFAULT 0,
        detail_json TEXT,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_g7_runs_fixture ON g7_runs(fixture_id)",
]

MIGRATIONS: dict[int, list[str]] = {1: _MIGRATION_V1, 2: _MIGRATION_V2, 3: _MIGRATION_V3}


class IllegalTransition(Exception):
    def __init__(self, shot_id: str, old: str, new: str):
        self.shot_id, self.old, self.new = shot_id, old, new
        super().__init__(f"非法状态迁移: 任务 {shot_id} 不允许 {old} → {new} (合法目标: {sorted(TRANSITIONS[old])})")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DB:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=10.0)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA synchronous=NORMAL")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- 底层执行(短事务) ----
    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # ---- 迁移(只新增) ----
    def migrate(self) -> int:
        """应用全部未应用的迁移, 返回本次应用的版本数。只增不改。"""
        self._exec(
            "CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        applied = {r["version"] for r in self._query("SELECT version FROM schema_migrations")}
        n = 0
        for version in sorted(MIGRATIONS):
            if version in applied:
                continue
            for stmt in MIGRATIONS[version]:
                self._exec(stmt)
            self._exec("INSERT INTO schema_migrations(version, applied_at) VALUES(?,?)", (version, utcnow()))
            n += 1
        return n

    def schema_version(self) -> int:
        rows = self._query("SELECT MAX(version) AS v FROM schema_migrations")
        return rows[0]["v"] or 0 if rows else 0

    # ---- 事件 / API 用量 ----
    def log_event(self, level: str, msg: str) -> None:
        self._exec("INSERT INTO events(ts, level, msg) VALUES(?,?,?)", (utcnow(), level, msg))

    def recent_events(self, limit: int = 50) -> list[dict]:
        rows = self._query("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def log_api_usage(self, capability: str, route: str, success: bool) -> None:
        assert route in ("api", "local")
        self._exec(
            "INSERT INTO api_usage(capability, route, success, created_at) VALUES(?,?,?,?)",
            (capability, route, int(bool(success)), utcnow()),
        )

    def api_usage_count(self, capability: str, route: str | None = None) -> int:
        if route:
            row = self._query(
                "SELECT COUNT(*) AS c FROM api_usage WHERE capability=? AND route=?", (capability, route)
            )
        else:
            row = self._query("SELECT COUNT(*) AS c FROM api_usage WHERE capability=?", (capability,))
        return int(row[0]["c"])

    def api_usage_summary(self) -> dict:
        rows = self._query(
            "SELECT capability, route, success, COUNT(*) AS c FROM api_usage GROUP BY capability, route, success"
        )
        out: dict[str, dict[str, int]] = {}
        for r in rows:
            cap = out.setdefault(r["capability"], {"api_ok": 0, "api_fail": 0, "local_ok": 0, "local_fail": 0})
            key = f"{r['route']}_{'ok' if r['success'] else 'fail'}"
            cap[key] += r["c"]
        return out

    # ---- 任务 ----
    def ingest_task(
        self,
        shot_id: str,
        narrative_slot: str,
        lane: str,
        card_json: str | dict,
        template: str | None = None,
    ) -> int:
        """插入镜头任务; shot_id 冲突时仅当原任务还是 pending 才更新卡面数据(幂等 ingest)。"""
        if isinstance(card_json, dict):
            card_json = json.dumps(card_json, ensure_ascii=False)
        with self._lock:
            row = self._conn.execute("SELECT id, status FROM tasks WHERE shot_id=?", (shot_id,)).fetchone()
            if row is None:
                cur = self._conn.execute(
                    "INSERT INTO tasks(shot_id, narrative_slot, lane, status, updated_at, card_json, template)"
                    " VALUES(?,?,?,'pending',?,?,?)",
                    (shot_id, narrative_slot, lane, utcnow(), card_json, template),
                )
                self._conn.commit()
                return int(cur.lastrowid)
            if row["status"] == "pending":
                self._conn.execute(
                    "UPDATE tasks SET narrative_slot=?, lane=?, card_json=?, template=?, updated_at=? WHERE id=?",
                    (narrative_slot, lane, card_json, template, utcnow(), row["id"]),
                )
                self._conn.commit()
            return int(row["id"])

    def get_task(self, shot_id: str) -> dict | None:
        rows = self._query("SELECT * FROM tasks WHERE shot_id=?", (shot_id,))
        return dict(rows[0]) if rows else None

    def list_tasks(self, status: str | None = None) -> list[dict]:
        if status:
            rows = self._query("SELECT * FROM tasks WHERE status=? ORDER BY id", (status,))
        else:
            rows = self._query("SELECT * FROM tasks ORDER BY id")
        return [dict(r) for r in rows]

    def counts_by_status(self) -> dict[str, int]:
        rows = self._query("SELECT status, COUNT(*) AS c FROM tasks GROUP BY status")
        counts = {s: 0 for s in STATUSES}
        for r in rows:
            counts[r["status"]] = r["c"]
        return counts

    def set_status(self, shot_id: str, new_status: str) -> None:
        """合法状态机迁移; 非法抛 IllegalTransition。"""
        if new_status not in TRANSITIONS:
            raise IllegalTransition(shot_id, "?", new_status)
        with self._lock:
            row = self._conn.execute("SELECT status FROM tasks WHERE shot_id=?", (shot_id,)).fetchone()
            if row is None:
                raise KeyError(f"任务不存在: {shot_id}")
            old = row["status"]
            if new_status not in TRANSITIONS[old]:
                raise IllegalTransition(shot_id, old, new_status)
            self._conn.execute(
                "UPDATE tasks SET status=?, updated_at=? WHERE shot_id=?", (new_status, utcnow(), shot_id)
            )
            self._conn.commit()
        self.log_event("info", f"status {shot_id}: {old} -> {new_status}")

    def force_status(self, shot_id: str, new_status: str, reason: str) -> None:
        """恢复路径专用: 绕过状态机强制改状态(崩溃恢复/阻塞标记), 全程留事件痕。"""
        with self._lock:
            self._conn.execute(
                "UPDATE tasks SET status=?, updated_at=?, error=? WHERE shot_id=?",
                (new_status, utcnow(), reason, shot_id),
            )
            self._conn.commit()
        self.log_event("warn", f"force_status {shot_id}: -> {new_status} ({reason})")

    def update_task(self, shot_id: str, **fields) -> None:
        unknown = set(fields) - set(TASK_UPDATABLE)
        if unknown:
            raise ValueError(f"tasks 不允许更新字段: {unknown}")
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        params = tuple(
            json.dumps(v, ensure_ascii=False) if k.endswith("_json") and isinstance(v, dict) else v
            for k, v in fields.items()
        )
        self._exec(f"UPDATE tasks SET {cols}, updated_at=? WHERE shot_id=?", (*params, utcnow(), shot_id))

    def set_card_field(self, shot_id: str, card: dict) -> None:
        self._exec(
            "UPDATE tasks SET card_json=?, updated_at=? WHERE shot_id=?",
            (json.dumps(card, ensure_ascii=False), utcnow(), shot_id),
        )

    # ---- 候选 ----
    def add_candidate(
        self,
        shot_id: str,
        path: str,
        gate_json: dict | None = None,
        overall_score: float | None = None,
        verdict: str = "pending",
        selected: bool = False,
    ) -> int:
        cur = self._exec(
            "INSERT INTO candidates(shot_id, path, gate_json, overall_score, verdict, selected, created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (
                shot_id,
                path,
                json.dumps(gate_json or {}, ensure_ascii=False),
                overall_score,
                verdict,
                int(selected),
                utcnow(),
            ),
        )
        return int(cur.lastrowid)

    def update_candidate(
        self,
        candidate_id: int,
        gate_json: dict | None = None,
        overall_score: float | None = None,
        verdict: str | None = None,
        selected: bool | None = None,
    ) -> None:
        sets, params = [], []
        if gate_json is not None:
            sets.append("gate_json=?")
            params.append(json.dumps(gate_json, ensure_ascii=False))
        if overall_score is not None:
            sets.append("overall_score=?")
            params.append(overall_score)
        if verdict is not None:
            sets.append("verdict=?")
            params.append(verdict)
        if selected is not None:
            sets.append("selected=?")
            params.append(int(selected))
        if not sets:
            return
        params.append(candidate_id)
        self._exec(f"UPDATE candidates SET {', '.join(sets)} WHERE id=?", tuple(params))

    def get_candidates(self, shot_id: str) -> list[dict]:
        rows = self._query("SELECT * FROM candidates WHERE shot_id=? ORDER BY id", (shot_id,))
        out = []
        for r in rows:
            d = dict(r)
            d["gate_json"] = json.loads(d["gate_json"] or "{}")
            d["selected"] = bool(d["selected"])
            out.append(d)
        return out

    def clear_candidates(self, shot_id: str) -> None:
        self._exec("DELETE FROM candidates WHERE shot_id=?", (shot_id,))

    def selected_candidate(self, shot_id: str) -> dict | None:
        rows = self._query("SELECT * FROM candidates WHERE shot_id=? AND selected=1", (shot_id,))
        if not rows:
            return None
        d = dict(rows[0])
        d["gate_json"] = json.loads(d["gate_json"] or "{}")
        d["selected"] = True
        return d

    # ---- M5 成片台账 ----
    def record_m5_video(self, video_id: str, template_id: str, spec: dict, shots: list[dict],
                        path: str, g6: dict | None) -> int:
        """记录一条显式合成的成片(video_id 冲突时覆盖, 便于重合成后台账保持一行)。"""
        self._exec(
            "INSERT INTO m5_videos(video_id, template_id, spec_json, shots_json, path, g6_json, created_at)"
            " VALUES(?,?,?,?,?,?,?)"
            " ON CONFLICT(video_id) DO UPDATE SET template_id=excluded.template_id,"
            " spec_json=excluded.spec_json, shots_json=excluded.shots_json, path=excluded.path,"
            " g6_json=excluded.g6_json, created_at=excluded.created_at",
            (
                video_id,
                template_id,
                json.dumps(spec, ensure_ascii=False),
                json.dumps(shots, ensure_ascii=False),
                path,
                json.dumps(g6 or {}, ensure_ascii=False),
                utcnow(),
            ),
        )
        row = self._query("SELECT id FROM m5_videos WHERE video_id=?", (video_id,))
        return int(row[0]["id"])

    def list_m5_videos(self) -> list[dict]:
        rows = self._query("SELECT * FROM m5_videos ORDER BY id")
        out = []
        for r in rows:
            d = dict(r)
            d["spec_json"] = json.loads(d["spec_json"] or "{}")
            d["shots_json"] = json.loads(d["shots_json"] or "[]")
            d["g6_json"] = json.loads(d["g6_json"] or "{}")
            out.append(d)
        return out

    # ---- V2-M1: 夹具库 + G7 分数 ----
    def list_fixtures(self, label: str | None = None) -> list[dict]:
        """夹具库全量(或按 label 过滤), fixture_id 升序。"""
        if label:
            rows = self._query("SELECT * FROM fixtures WHERE label=? ORDER BY fixture_id", (label,))
        else:
            rows = self._query("SELECT * FROM fixtures ORDER BY fixture_id")
        return [dict(r) for r in rows]

    def add_g7_run(self, fixture_id: str, sub: str, score: float, triggered: bool,
                   skipped: bool, detail: dict) -> str:
        """落一条 G7 分数(sub ∈ a/b/c/d/e/overall), 返回时间戳。"""
        ts = utcnow()
        self._exec(
            "INSERT INTO g7_runs(fixture_id, sub, score, triggered, skipped, detail_json, created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (fixture_id, sub, float(score), int(bool(triggered)), int(bool(skipped)),
             json.dumps(detail, ensure_ascii=False), ts),
        )
        return ts

    def list_g7_runs(self, fixture_id: str | None = None) -> list[dict]:
        if fixture_id:
            rows = self._query("SELECT * FROM g7_runs WHERE fixture_id=? ORDER BY id", (fixture_id,))
        else:
            rows = self._query("SELECT * FROM g7_runs ORDER BY id")
        out = []
        for r in rows:
            d = dict(r)
            d["detail_json"] = json.loads(d["detail_json"] or "{}")
            out.append(d)
        return out
