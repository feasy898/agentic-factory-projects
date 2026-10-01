"""M7 审计验收（T1.3 落库/零明文/会话存储 + T5.1 管理面查询 API）。

运行::

    cd REPO_ROOT && PYTHONUTF8=1 ./.venv/Scripts/python.exe -m evals.m7_audit

exit 0 = 通过。本任务覆盖面（开发指令 §6 M7 + workflow T1.3 / T5.1）：

A. audit/writer 落库完整性
   - WAL 生效（journal_mode=wal）、schema 在位；
   - 30 条混合事件（三路由/blocked/flags/class_counts 混合）全部落库：行数正确、
     id 自增唯一、逐字段往返全等（含 ts UTC Z 形态）；
   - 关闭写线程后重开库直读（read_events）数据仍在（WAL 持久性）；
   - 入队 30 次总耗时 < AUDIT_APPEND_BATCH_MS（请求路径不阻塞）；
B. 零明文硬闸 + 全库文件扫描
   - 含原值的事件被 assert_no_raw_pii 拒之队外（未入队=未落库，行数不变）；
   - 全部落库事件所在的 SQLite 文件（主文件 + WAL/SHM 旁挂）bytes 级 grep
     所有原值 → 命中数 == AUDIT_RAW_PII_HITS_ALLOWED (0)，且扫描字节 > 0；
   - 扫描器负控（防假绿）：绕过 writer 直插含原值的"毒行"（落在 WAL 未合流态），
     assert_db_no_raw_pii 必须命中并抛 RawPiiLeakError——证明 bytes 级扫描
     真实可见库内容（含 -wal 旁挂文件）；
C. masking/session_store（SQLite + TTL，会话稳定）
   - 会话稳定：同 session 重复请求占位符全等（first_seen 不变）、跨 session 不同；
   - 落库完整性：masking_map 行数 == 插入数；close 后新开 store 同 key 同路径
     恢复（hydrate）→ 还原成功、占位符与重启前全等（确定性摘要）；
   - LRU 换出复活：capacity=2 塞 3 会话 → 换出者重新 get 后还原仍成功；
   - 会话过期：短 TTL 下 cleanup() 删除过期行；过期后 lookup 返回 None
     （还原能力失效），同值再到达占位符不变（确定性）但不可还原；
   - TTL 窗口内不误删：未过期行 cleanup 后仍在。
D. 管理面查询 API（T5.1：§6 M7「20 个混合请求 → 行数正确/聚合与明细一致/CSV
   可下载」口径 + §5.6 三端点）——20 条混合事件（两部门 × 三路由 × blocked ×
   延迟，时间窗每分钟一条）经 HTTP ASGI 直打 create_app：
   - 鉴权负例：缺 key / 错 key → 401（error.code=unauthorized）；有效部门 key → 200
     （三条端点逐一验证）；
   - /admin/api/audit 分页+筛选：总数/逐条 §5.4 形状（ts Z 形态、无 raw 字段）；
     dept/route/blocked/from-to（含纯日期含当天、闭区间边界）过滤正确；
     分页不重不漏（limit/offset 页拼接 == 全量、total 恒定；越界 400）；
   - /admin/api/metrics 聚合正确性：按部门 requests/blocked/block_rate/路由分布/
     理由码/延迟分位（p50/p90/p95）与**手算冻结期望值**逐项相等，且与
     writer.fetch_all() 明细计数互为交叉一致；
   - /admin/api/report.csv 保密自查报告：text/csv + utf-8-sig BOM、列序==CSV_HEADERS、
     行序 id 升序、CSV 往返逐字段与明细全等、公式注入高危单元格已前置引号、
     CSV 字节 bytes 级扫描全部原值零命中（红线延续）、筛选联动。
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import sqlite3
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from audit.models import AuditEvent  # noqa: E402
from audit.query import CSV_HEADERS  # noqa: E402
from audit.store import (  # noqa: E402
    RawPiiLeakError,
    assert_db_no_raw_pii,
    assert_no_raw_pii,
    scan_db_files,
)
from audit.writer import SqliteAuditWriter, count_events, read_events  # noqa: E402
from common.config import AppConfig  # noqa: E402
from evals.thresholds import (  # noqa: E402
    AUDIT_ADMIN_EVENTS,
    AUDIT_APPEND_BATCH_MS,
    AUDIT_FLUSH_TIMEOUT_S,
    AUDIT_PAGE_LIMIT_DEFAULT,
    AUDIT_RAW_PII_HITS_ALLOWED,
    AUDIT_SESSION_STABILITY_VALUES,
    AUDIT_WRITER_EVENTS,
    SESSION_TTL_PROBE_MS,
)
from gateway import deps  # noqa: E402
from gateway.app import create_app  # noqa: E402
from masking.mapper import RESTORE_PATTERN, SessionRegistry  # noqa: E402
from masking.session_store import SessionStore  # noqa: E402
from recognizers.models import EntityClass  # noqa: E402

RESULTS: list[tuple[bool, str]] = []


def _record(name: str, fn):
    try:
        detail = fn() or ""
        RESULTS.append((True, f"PASS  {name}" + (f" — {detail}" if detail else "")))
    except Exception as exc:  # noqa: BLE001 — 汇总所有失败后统一退出
        RESULTS.append((False, f"FAIL  {name} — {type(exc).__name__}: {exc}"))


# ── 夹具：原值与事件 ─────────────────────────────────────────────────
def _valid_id(prefix17: str) -> str:
    weights = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
    codes = "10X98765432"
    total = sum(int(ch) * w for ch, w in zip(prefix17, weights, strict=True))
    return prefix17 + codes[total % 11]


ID_A = "11010519491231002X"
ID_B = _valid_id("46002219900307123")
PHONE_A = "13800138000"
PHONE_B = "13900139000"
PHONE_C = "13700137000"
USCC_A = "91469023MA5T1234XA"[:18]
BANK_A = "6222020200112233456"[:16]
#: 本批请求涉及的全部 normalized 原值（bytes 级扫描对象）
RAW_VALUES: tuple[str, ...] = (ID_A, ID_B, PHONE_A, PHONE_B, PHONE_C, USCC_A, BANK_A)

_EVENT_SEQ: list[tuple[str, str, str, str, dict[str, int], bool, list[str], int]] = [
    # (request_id, session_id, route, reasons, class_counts, blocked, flags, latency)
    ("req_m7_a01", "sess_m7_a", "INTERNET", [], {"PHONE_MOBILE": 2}, False, [], 81),
    ("req_m7_a02", "sess_m7_a", "INTERNET", [], {"ID_CARD": 1, "PERSON": 1}, False, [], 95),
    ("req_m7_a03", "sess_m7_b", "GOVCLOUD", ["SENSITIVE_ATTR"], {"SENSITIVE_ATTR": 2, "ID_CARD": 3},
     False, [], 120),
    ("req_m7_a04", "sess_m7_b", "BLOCK", ["CLASSIFICATION_MARK"], {"CLASSIFICATION_MARK": 1},
     True, [], 12),
    ("req_m7_a05", "sess_m7_c", "INTERNET", [], {"BANK_CARD": 1, "USCC": 1}, False, [], 66),
]


def _masked_preview(kind: str, seq: int) -> str:
    """占位符形态的预览（与网关实际落库内容同构）。"""
    return (f"〔身份证·{seq:08x}〕〔手机号·{seq + 1:08x}〕"
            f"{kind}事项编号 M7-{seq:04d}，请经办同志按规定办理。")


def _events(n: int) -> list[tuple[AuditEvent, list[str]]]:
    """n 条混合事件（预览全部为占位符版本，不含量探原值）。"""
    out: list[tuple[AuditEvent, list[str]]] = []
    base = datetime.now(UTC) - timedelta(seconds=n + 1)
    for i in range(n):
        rid, sid, route, reasons, counts, blocked, flags, latency = _EVENT_SEQ[i % len(_EVENT_SEQ)]
        rid = f"{rid[:-2]}{i:02d}"
        ev = AuditEvent(
            ts=base + timedelta(milliseconds=i), request_id=rid, session_id=sid,
            dept="民政局", route=route, blocked=blocked, reasons=reasons,
            class_counts=counts, prompt_preview=_masked_preview("低保", i),
            response_preview=("" if blocked else f"已受理〔人名·{i + 9:08x}〕的申请。"),
            upstream=(None if blocked else ("govcloud_local" if route == "GOVCLOUD" else "internet_mock")),
            latency_ms=latency + i, flags=flags,
        )
        out.append((ev, list(RAW_VALUES)))
    return out


def _tmp_db(tmp_dir: str, name: str) -> Path:
    """临时目录（with 写法给出的 str 路径）→ 库文件路径。"""
    return Path(tmp_dir) / name


def _wipe_db(db: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)


# ── A. 落库完整性 ───────────────────────────────────────────────────
def check_writer_wal_schema() -> str:
    with tempfile.TemporaryDirectory() as tmp:
        db = _tmp_db(tmp, "wal.db")
        writer = SqliteAuditWriter(db)
        try:
            mode = writer.journal_mode()
            assert mode.lower() == "wal", f"journal_mode={mode}"
            conn = sqlite3.connect(str(db))
            try:
                tables = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            finally:
                conn.close()
            assert "audit_events" in tables, f"tables={tables}"
            return f"journal_mode={mode}, tables={sorted(tables)}"
        finally:
            writer.close()


def check_writer_roundtrip() -> str:
    n = AUDIT_WRITER_EVENTS
    with tempfile.TemporaryDirectory() as tmp:
        db = _tmp_db(tmp, "rt.db")
        writer = SqliteAuditWriter(db)
        original = _events(n)
        try:
            started = time.perf_counter()
            for ev, values in original:
                writer.append(ev, values)
            enqueue_ms = (time.perf_counter() - started) * 1000
            assert enqueue_ms < AUDIT_APPEND_BATCH_MS, \
                f"enqueue {enqueue_ms:.1f}ms >= {AUDIT_APPEND_BATCH_MS}ms (请求路径被阻塞)"
            assert writer.flush(timeout_s=AUDIT_FLUSH_TIMEOUT_S), "queue did not drain"
            rows = writer.fetch_all()
            assert len(rows) == n, f"rows={len(rows)} != {n}"
            ids = [i for i, _ in rows]
            assert ids == sorted(ids) and len(set(ids)) == n, f"ids not strictly increasing: {ids}"
            for (want, _), (_, got) in zip(original, rows, strict=True):
                assert got.model_dump() == want.model_dump(), \
                    f"round-trip drift on {want.request_id}:\n got={got.model_dump()}\n want={want.model_dump()}"
            assert all(e.model_dump(mode="json")["ts"].endswith("Z") for _, e in rows), \
                "ts must serialize as UTC Z"
            return (f"{n} events: rows/ids/fields exact; enqueue {enqueue_ms:.1f}ms "
                    f"(< {AUDIT_APPEND_BATCH_MS}ms)")
        finally:
            writer.close()


def check_writer_persistence_after_close() -> str:
    n = AUDIT_WRITER_EVENTS
    with tempfile.TemporaryDirectory() as tmp:
        db = _tmp_db(tmp, "persist.db")
        writer = SqliteAuditWriter(db)
        original = _events(n)
        for ev, values in original:
            writer.append(ev, values)
        writer.flush(timeout_s=AUDIT_FLUSH_TIMEOUT_S)
        writer.close()
        assert count_events(db) == n, f"count after close = {count_events(db)} != {n}"
        rows = read_events(db)
        assert len(rows) == n, f"read after close = {len(rows)} != {n}"
        for (want, _), (_, got) in zip(original, rows, strict=True):
            assert got.model_dump() == want.model_dump(), f"drift after close on {want.request_id}"
        return f"close → reopen(db): {n} events intact (WAL 持久性)"


# ── B. 零明文硬闸 + 全库扫描 ─────────────────────────────────────────
def check_gate_blocks_before_enqueue() -> str:
    with tempfile.TemporaryDirectory() as tmp:
        db = _tmp_db(tmp, "gate.db")
        writer = SqliteAuditWriter(db)
        try:
            leaking = AuditEvent(ts=datetime.now(UTC), request_id="req_leak",
                                 prompt_preview=f"身份证{ID_A}联系电话{PHONE_A}")
            try:
                writer.append(leaking, [ID_A, PHONE_A])
            except RawPiiLeakError as exc:
                assert exc.kind == "masked_finding", f"kind={exc.kind}"
            else:
                raise AssertionError("raw-PII gate did not trip")
            assert writer.count() == 0, "rejected event must not be enqueued/stored"
            clean = AuditEvent(ts=datetime.now(UTC), request_id="req_ok",
                               prompt_preview="身份证〔身份证·abcd1234〕")
            writer.append(clean, [ID_A])
            assert writer.flush(timeout_s=AUDIT_FLUSH_TIMEOUT_S)
            assert writer.count() == 1, "clean event must be stored"
            # 事件级闸独立可用（store 断言函数直调）
            assert_no_raw_pii(clean, [ID_A])  # 不抛 = 通过
            return "leaking event rejected pre-enqueue (0 rows); clean event stored"
        finally:
            writer.close()


def check_db_file_scan_zero_hit() -> str:
    n = AUDIT_WRITER_EVENTS
    with tempfile.TemporaryDirectory() as tmp:
        db = _tmp_db(tmp, "scan.db")
        writer = SqliteAuditWriter(db)
        try:
            for ev, values in _events(n):
                writer.append(ev, values)
            assert writer.flush(timeout_s=AUDIT_FLUSH_TIMEOUT_S)
            writer.checkpoint()
            scanned = assert_db_no_raw_pii(db, RAW_VALUES)
            assert scanned > 0, "scanned 0 bytes — scan target missing"
            hits = [v for v in RAW_VALUES if v.encode("utf-8") in scan_db_files(db)]
            assert not hits, f"raw values in db file: {hits}"
            assert len(hits) == AUDIT_RAW_PII_HITS_ALLOWED
            return f"{n} rows; db(+wal/shm) bytes-scan {scanned}B → 0/{len(RAW_VALUES)} 原值命中"
        finally:
            writer.close()


def check_db_file_scan_negative_control() -> str:
    """负控：绕过 writer 直插毒行（留 WAL 未合流态）→ 扫描必须命中。"""
    with tempfile.TemporaryDirectory() as tmp:
        db = _tmp_db(tmp, "poison.db")
        writer = SqliteAuditWriter(db)
        try:
            clean = _events(3)
            for ev, values in clean:
                writer.append(ev, values)
            assert writer.flush(timeout_s=AUDIT_FLUSH_TIMEOUT_S)
            # 绕过写入口（模拟"意外落原文"的事故形态）：直插含原值的事件，
            # 且不做 checkpoint——毒行留在 -wal 旁挂文件里
            conn = sqlite3.connect(str(db))
            try:
                conn.execute(
                    "INSERT INTO audit_events (ts, request_id, session_id, dept, route, blocked, "
                    "reasons, class_counts, prompt_preview, response_preview, upstream, "
                    "latency_ms, flags) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("2026-09-28T00:00:00.000000Z", "req_poison", "sess_poison", "民政局",
                     "INTERNET", 0, "[]", "{}", f"身份证{ID_A}", "", None, 1, "[]"),
                )
                conn.commit()
            finally:
                conn.close()
            wal_must_exist = Path(str(db) + "-wal")
            assert wal_must_exist.exists(), "expected -wal sidecar to hold the poisoned row"
            try:
                assert_db_no_raw_pii(db, RAW_VALUES)
            except RawPiiLeakError as exc:
                assert exc.kind == "db_file_scan", f"kind={exc.kind}"
                blob = scan_db_files(db)
                assert ID_A.encode("utf-8") in blob, "poison value not actually in scanned bytes"
            else:
                raise AssertionError("scanner missed a poisoned row — 假绿")
            return "poisoned row (in -wal) caught by bytes-level scan → RawPiiLeakError(db_file_scan)"
        finally:
            writer.close()


# ── C. 会话存储 ─────────────────────────────────────────────────────
def _key() -> bytes:
    return b"m7-eval-mask-key-0123456789abcdef"


def check_session_stability() -> str:
    n = AUDIT_SESSION_STABILITY_VALUES
    with tempfile.TemporaryDirectory() as tmp:
        db = _tmp_db(tmp, "sess.db")
        store = SessionStore(_key(), db)
        try:
            mapper = store.get("sess_m7_stab")
            id_values = [_valid_id(f"{110105194900000 + i:017d}") for i in range(n)]
            first: dict[str, tuple[str, Any]] = {}
            for v in id_values:
                ph, entry = mapper.placeholder_for(EntityClass.ID_CARD, v)
                first[v] = (ph, entry.first_seen)
            for v, (ph, seen) in first.items():   # 同 session 重复请求 → 全等
                ph2, entry2 = mapper.placeholder_for(EntityClass.ID_CARD, v)
                assert ph2 == ph and entry2.first_seen == seen, f"placeholder drift for {v}"
            other = store.get("sess_m7_other")
            for v in id_values[:10]:              # 跨 session → 必不同
                ph_other, _ = other.placeholder_for(EntityClass.ID_CARD, v)
                assert ph_other != first[v][0], f"cross-session placeholder collision for {v}"
            assert store.row_count() == n + 10, f"rows={store.row_count()} != {n + 10}"
            return f"{n} values ×2 identical; cross-session distinct; {store.row_count()} rows on disk"
        finally:
            store.close()


def check_session_persistence_reopen() -> str:
    with tempfile.TemporaryDirectory() as tmp:
        db = _tmp_db(tmp, "reopen.db")
        store = SessionStore(_key(), db)
        sid = "sess_m7_reopen"
        mapper = store.get(sid)
        values = [_valid_id("46002219900307123"), _valid_id("11010519491231001")]
        masked: dict[str, str] = {}
        for v in values:
            ph, _ = mapper.placeholder_for(EntityClass.ID_CARD, v)
            masked[v] = ph
        rows_before = store.row_count()
        store.close()

        store2 = SessionStore(_key(), db)   # 同 key 同路径 = "重启"
        try:
            assert store2.row_count() == rows_before, "rows lost across reopen"
            mapper2 = store2.get(sid)
            for v in values:
                restored = mapper2.restore(masked[v])
                assert restored == v, f"restore after reopen: {masked[v]!r} → {restored!r}"
                ph2, _ = mapper2.placeholder_for(EntityClass.ID_CARD, v)
                assert ph2 == masked[v], "placeholder drifted across reopen"
            unknown = store2.get("sess_m7_fresh")
            assert unknown.lookup(masked[values[0]]) is None, "cross-session lookup must miss"
            return (f"close → new store: {rows_before} rows; restore + placeholder 全等; "
                    f"跨会话 lookup 不串")
        finally:
            store2.close()


def check_session_lru_revive() -> str:
    with tempfile.TemporaryDirectory() as tmp:
        db = _tmp_db(tmp, "lru.db")
        store = SessionStore(_key(), db, capacity=2)
        try:
            value = _valid_id("46002219900307123")
            phs: dict[str, str] = {}
            for sid in ("sess_lru_1", "sess_lru_2", "sess_lru_3"):
                mapper = store.get(sid)
                ph, _ = mapper.placeholder_for(EntityClass.ID_CARD, value)
                phs[sid] = ph
            # sess_lru_1 已被 LRU 换出（capacity=2）→ 重新 get 须从库复活
            revived = store.get("sess_lru_1")
            restored = revived.restore(phs["sess_lru_1"])
            assert restored == value, f"revived restore: {restored!r}"
            return "capacity=2 ×3 sessions: evicted session rehydrated from db, restore intact"
        finally:
            store.close()


def check_session_ttl_expiry() -> str:
    ttl = timedelta(milliseconds=SESSION_TTL_PROBE_MS)
    with tempfile.TemporaryDirectory() as tmp:
        db = _tmp_db(tmp, "ttl.db")
        store = SessionStore(_key(), db, ttl=ttl)
        try:
            value = _valid_id("46002219900307123")
            sid = "sess_m7_ttl"
            mapper = store.get(sid)
            ph, entry = mapper.placeholder_for(EntityClass.ID_CARD, value)
            first_seen = entry.first_seen
            assert store.row_count() == 1
            time.sleep(ttl.total_seconds() + 0.08)
            deleted = store.cleanup()
            assert deleted == 1, f"cleanup deleted {deleted} != 1"
            assert store.row_count() == 0, "expired row still on disk"
            # 过期后（同值再次使用前）：还原能力随行删除而失效——内存与库同口径
            assert mapper.lookup(ph) is None, "expired mapping must not restore (in-memory)"
            assert mapper.restore(ph) == ph, "restore must leave unknown placeholder as-is"
            store2 = SessionStore(_key(), db, ttl=ttl)
            try:
                fresh = store2.get(sid)
                assert fresh.lookup(ph) is None, "expired row must not rehydrate"
            finally:
                store2.close()
            # 占位符确定性：同 session 同值再到达 → 同占位符，映射以新 first_seen 重新建立
            ph_again, entry_again = mapper.placeholder_for(EntityClass.ID_CARD, value)
            assert ph_again == ph, "placeholder must stay deterministic after expiry"
            assert entry_again.first_seen > first_seen, "re-established mapping must be fresh"
            assert store.row_count() == 1, "re-used value must re-persist its mapping"
            assert mapper.restore(ph) == value, "mapping usable again after re-establish"
            assert RESTORE_PATTERN.search(ph) is not None
            return (f"ttl={SESSION_TTL_PROBE_MS}ms: cleanup deleted 1 row; unrestorable until "
                    f"re-use; placeholder deterministic; re-persisted on use")
        finally:
            store.close()


def check_session_ttl_keeps_fresh() -> str:
    with tempfile.TemporaryDirectory() as tmp:
        db = _tmp_db(tmp, "fresh.db")
        store = SessionStore(_key(), db)
        try:
            value = _valid_id("46002219900307123")
            mapper = store.get("sess_m7_fresh_ttl")
            ph, _ = mapper.placeholder_for(EntityClass.ID_CARD, value)
            deleted = store.cleanup()
            assert deleted == 0, f"fresh row deleted ({deleted})"
            assert store.row_count() == 1, "fresh row missing after cleanup"
            assert mapper.restore(ph) == value
            return "ttl=24h 窗口内 cleanup 删 0 行，映射仍可还原"
        finally:
            store.close()


# ── D. 管理面查询 API（T5.1）──────────────────────────────────────
#: 管理面夹具时刻基（UTC；第 i 条 = +i 分钟，时间窗每分钟一条）
_ADMIN_T0 = datetime(2026, 9, 28, 3, 0, 0, tzinfo=UTC)
#: 两个部门的演示部门 key（配置库只存 sha256；这里给明文走鉴权）
_ADMIN_KEYS = {"民政局": "dk_admin_minzheng", "某镇": "dk_admin_ezt"}

#: 公式注入探针预览（CSV 导出必须前置引号；断言高危单元格已被缓解）
_FORMULA_PREVIEW = "=SUM(A1:A99)〔密级·已拦截〕公式注入探针"

#: 20 条混合事件（两部门 × 三路由 × blocked × 延迟分位；i 0-11 民政局、12-19 某镇）
_ADMIN_FIXTURE: tuple[tuple[str, str, bool, list[str], int, list[str], dict[str, int]], ...] = (
    ("民政局", "INTERNET", False, [], 100, [], {"PHONE_MOBILE": 1}),
    ("民政局", "INTERNET", False, [], 120, [], {"PHONE_MOBILE": 1}),
    ("民政局", "INTERNET", False, [], 140, [], {"ID_CARD": 1}),
    ("民政局", "INTERNET", False, [], 160, [], {"PHONE_MOBILE": 1}),
    ("民政局", "INTERNET", False, [], 180, [], {"PERSON": 2}),
    ("民政局", "INTERNET", False, [], 200, [], {"PHONE_MOBILE": 1}),
    ("民政局", "GOVCLOUD", False, ["SENSITIVE_ATTR"], 220, [], {"SENSITIVE_ATTR": 2, "ID_CARD": 3}),
    ("民政局", "GOVCLOUD", False, ["SENSITIVE_ATTR"], 240, [], {"SENSITIVE_ATTR": 1}),
    ("民政局", "BLOCK", True, ["CLASSIFICATION_MARK"], 15, [], {"CLASSIFICATION_MARK": 1}),
    ("民政局", "INTERNET", False, [], 90, [], {"EMAIL": 1}),
    ("民政局", "GOVCLOUD", False, ["SENSITIVE_ATTR"], 260, [], {"SENSITIVE_ATTR": 1}),
    ("民政局", "INTERNET", False, [], 110, [], {"PHONE_MOBILE": 2}),
    ("某镇", "INTERNET", False, [], 80, [], {"PHONE_MOBILE": 1}),
    ("某镇", "INTERNET", False, [], 70, [], {"PHONE_MOBILE": 1}),
    ("某镇", "GOVCLOUD", False, ["WORK_SECRET"], 300, [], {"WORK_SECRET": 1}),
    ("某镇", "BLOCK", True, ["CLASSIFICATION_MARK"], 10, [], {"CLASSIFICATION_MARK": 1}),
    ("某镇", "BLOCK", True, ["INJECTION"], 12, ["injection"], {"INJECTION": 1}),
    ("某镇", "INTERNET", False, [], 85, [], {"PHONE_MOBILE": 1}),
    ("某镇", "INTERNET", False, [], 95, [], {}),
    ("某镇", "INTERNET", False, [], 75, [], {"PHONE_MOBILE": 1}),
)

#: 聚合期望值（**手算冻结**：上方夹具的独立推导，不复用被测代码公式——
#: 民政局 12 条 latency 排序 [15,90,100,110,120,140,160,180,200,220,240,260]
#:   p50=(140+160)/2=150；p90=220+0.9×(240-220)=238；p95=240+0.45×20=249；
#:   avg=1835/12≈152.916667；
#: 某镇 8 条排序 [10,12,70,75,80,85,95,300]
#:   p50=(75+80)/2=77.5；p90=95+0.3×(300-95)=156.5；p95=95+0.65×205=228.25；
#:   avg=727/8=90.875；
#: 全局 20 条排序 [10,12,15,70,75,80,85,90,95,100,110,120,140,160,180,200,220,240,260,300]
#:   p50=(100+110)/2=105；p90=240+0.1×(260-240)=242；p95=260+0.05×40=262；
#:   avg=2562/20=128.1）
_EXPECTED_METRICS: dict[str, Any] = {
    "全局": {"requests": 20, "blocked": 3, "block_rate": 0.15,
             "routes": {"INTERNET": 13, "GOVCLOUD": 4, "BLOCK": 3},
             "reasons": {"SENSITIVE_ATTR": 3, "CLASSIFICATION_MARK": 2,
                         "WORK_SECRET": 1, "INJECTION": 1},
             "latency_ms": {"count": 20, "avg_ms": 128.1, "p50_ms": 105.0,
                            "p90_ms": 242.0, "p95_ms": 262.0}},
    "民政局": {"requests": 12, "blocked": 1, "block_rate": 0.083333,
              "routes": {"INTERNET": 8, "GOVCLOUD": 3, "BLOCK": 1},
              "reasons": {"SENSITIVE_ATTR": 3, "CLASSIFICATION_MARK": 1},
              "latency_ms": {"count": 12, "avg_ms": 152.916667, "p50_ms": 150.0,
                             "p90_ms": 238.0, "p95_ms": 249.0}},
    "某镇": {"requests": 8, "blocked": 2, "block_rate": 0.25,
             "routes": {"INTERNET": 5, "GOVCLOUD": 1, "BLOCK": 2},
             "reasons": {"WORK_SECRET": 1, "CLASSIFICATION_MARK": 1, "INJECTION": 1},
             "latency_ms": {"count": 8, "avg_ms": 90.875, "p50_ms": 77.5,
                            "p90_ms": 156.5, "p95_ms": 228.25}},
}


def _admin_fixture(n: int = AUDIT_ADMIN_EVENTS) -> list[tuple[AuditEvent, list[str]]]:
    """20 条混合管理面事件（预览全为占位符版本；i=8 带公式注入探针）。"""
    out: list[tuple[AuditEvent, list[str]]] = []
    for i, (dept, route, blocked, reasons, latency, flags, counts) in \
            enumerate(_ADMIN_FIXTURE[:n]):
        ev = AuditEvent(
            ts=_ADMIN_T0 + timedelta(minutes=i), request_id=f"req_admin_{i:02d}",
            session_id=f"sess_admin_{i % 3:02d}", dept=dept, route=route, blocked=blocked,
            reasons=reasons, class_counts=counts,
            prompt_preview=(_FORMULA_PREVIEW if i == 8 else _masked_preview("自查", i)),
            response_preview=("" if blocked else f"已受理〔人名·{i + 7:08x}〕的申请。"),
            upstream=(None if blocked else
                      ("govcloud_local" if route == "GOVCLOUD" else "internet_mock")),
            latency_ms=latency, flags=flags,
        )
        out.append((ev, list(RAW_VALUES)))
    return out


def _admin_app(tmp: str) -> tuple[Any, SqliteAuditWriter, Path]:
    """SQLite 写库 + create_app（真实 ASGI，审计队列注入 T5.1 事件）。

    会话映射走内存 SessionRegistry（管理面验收与会话无关，且避免测试目录里
    落第二个库文件、干扰 TemporaryDirectory 清理）。
    """
    db = _tmp_db(tmp, "admin_ctx.db")
    writer = SqliteAuditWriter(db)
    for ev, values in _admin_fixture():
        writer.append(ev, values)
    assert writer.flush(timeout_s=AUDIT_FLUSH_TIMEOUT_S), "fixture audit queue did not drain"
    cfg = AppConfig(audit_db=str(db), session_db=str(_tmp_db(tmp, "admin_sess.db")))
    mask_key = "41" * 32
    registry = SessionRegistry(mask_key.encode("utf-8"), capacity=16)
    app = create_app(cfg=cfg, mask_key=mask_key,
                     dept_key_digests={d: deps.sha256_hex(k) for d, k in _ADMIN_KEYS.items()},
                     audit_store=writer, session_registry=registry)
    return app, writer, db


def _admin_get(app: Any, path: str, *, key: str | None,
               params: dict[str, Any] | None = None) -> httpx.Response:
    """ASGI 层 GET（缺省=生产真实 create_app；key=None 模拟未带鉴权头）。"""
    from httpx import ASGITransport

    async def run() -> httpx.Response:
        async with httpx.AsyncClient(transport=ASGITransport(app=app),
                                     base_url="http://anongw.test") as client:
            headers = {"Authorization": f"Bearer {key}"} if key else {}
            return await client.get(path, params=params, headers=headers)
    return asyncio.run(run())


def check_admin_auth_negatives() -> str:
    with tempfile.TemporaryDirectory() as tmp:
        app, writer, _db = _admin_app(tmp)
        try:
            for path in ("/admin/api/audit", "/admin/api/metrics", "/admin/api/report.csv"):
                r = _admin_get(app, path, key=None)
                assert r.status_code == 401, f"{path} 缺 key → {r.status_code}"
                if not path.endswith(".csv"):   # JSON 端点校验错误信封形状
                    err = r.json()
                    assert err["error"]["code"] == "unauthorized", f"{path} code={err}"
                r = _admin_get(app, path, key="dk_wrong_key_value")
                assert r.status_code == 401, f"{path} 错 key → {r.status_code}"
            # 有效部门 key（两个部门各自验证）= 200
            for dept, key in _ADMIN_KEYS.items():
                r = _admin_get(app, "/admin/api/audit", key=key)
                assert r.status_code == 200 and r.json()["total"] == AUDIT_ADMIN_EVENTS, \
                    f"{dept} valid key → {r.status_code}"
            return ("三端点：缺 key/错 key → 401（unauthorized 信封）；"
                    f"两个有效部门 key → 200 total={AUDIT_ADMIN_EVENTS}")
        finally:
            writer.close()


def check_admin_page_filters() -> str:
    """分页+筛选：全部/部门/路由/blocked/时间窗/纯日期 + 400 负例。"""
    event_keys = set(AuditEvent.model_fields)
    with tempfile.TemporaryDirectory() as tmp:
        app, writer, _db = _admin_app(tmp)
        try:
            full = _admin_get(app, "/admin/api/audit", key=_ADMIN_KEYS["民政局"]).json()
            assert set(full) == {"total", "limit", "offset", "events"}, f"keys={set(full)}"
            assert full["total"] == AUDIT_ADMIN_EVENTS == len(full["events"]), \
                f"total={full['total']} events={len(full['events'])}"
            assert full["limit"] == AUDIT_PAGE_LIMIT_DEFAULT and full["offset"] == 0
            ts_list = [e["ts"] for e in full["events"]]
            assert ts_list == sorted(ts_list, reverse=True), "events must be id-desc (ts desc)"
            for ev in full["events"]:
                assert set(ev) == event_keys, f"event key drift: {set(ev) ^ event_keys}"
                assert ev["ts"].endswith("Z"), f"ts not UTC Z: {ev['ts']}"
                assert "raw" not in ev, "§5.4 红线：事件不含 raw 字段"

            def _query(params: dict[str, Any]) -> dict[str, Any]:
                r = _admin_get(app, "/admin/api/audit", key=_ADMIN_KEYS["民政局"],
                               params=params)
                assert r.status_code == 200, f"{params} → {r.status_code}"
                return r.json()

            p = _query({"dept": "民政局"})
            assert p["total"] == 12 and all(e["dept"] == "民政局" for e in p["events"])
            p = _query({"dept": "某镇"})
            assert p["total"] == 8 and all(e["dept"] == "某镇" for e in p["events"])
            p = _query({"route": "BLOCK"})
            assert p["total"] == 3 and all(e["route"] == "BLOCK" and e["blocked"]
                                           for e in p["events"])
            p = _query({"route": "GOVCLOUD"})
            assert p["total"] == 4 and all(e["route"] == "GOVCLOUD" and not e["blocked"]
                                           for e in p["events"])
            p = _query({"blocked": "true"})
            assert p["total"] == 3 and all(e["blocked"] for e in p["events"])
            p = _query({"blocked": "false"})
            assert p["total"] == 17 and not any(e["blocked"] for e in p["events"])
            p = _query({"dept": "某镇", "route": "BLOCK"})
            assert p["total"] == 2 and {e["request_id"] for e in p["events"]} == \
                {"req_admin_15", "req_admin_16"}
            # 时间窗：闭区间 [03:02, 03:04] → i=2,3,4 三条
            p = _query({"from": "2026-09-28T03:02:00Z", "to": "2026-09-28T03:04:00Z"})
            assert p["total"] == 3 and [e["request_id"] for e in p["events"]] == \
                ["req_admin_04", "req_admin_03", "req_admin_02"]
            # 纯日期：to 含当天（全天 20 条）；from 次日 → 0 条
            assert _query({"to": "2026-09-28"})["total"] == 20
            assert _query({"from": "2026-09-29"})["total"] == 0
            # 非法参数 → 400 bad_request
            for bad in ({"route": "NOPE"}, {"blocked": "maybe"}, {"from": "abc"},
                        {"to": "18:99"}, {"limit": "abc"}, {"limit": "0"},
                        {"offset": "-1"}, {"limit": "100000"}):
                r = _admin_get(app, "/admin/api/audit", key=_ADMIN_KEYS["民政局"],
                               params=bad)
                assert r.status_code == 400, f"{bad} → {r.status_code}"
                assert r.json()["error"]["code"] == "bad_request", f"{bad} 信封"
            return ("total/events/形状/降序 ✓；dept×2、route、blocked、组合 ✓；"
                    "闭区间时间窗+纯日期含当天 ✓；8 类非法参数全部 400 bad_request")
        finally:
            writer.close()


def check_admin_page_pagination() -> str:
    """分页不重不漏：页拼接 == 全量、total 恒定、越界空页。"""
    with tempfile.TemporaryDirectory() as tmp:
        app, writer, _db = _admin_app(tmp)
        try:
            key = _ADMIN_KEYS["民政局"]
            full = _admin_get(app, "/admin/api/audit", key=key).json()
            whole = [e["request_id"] for e in full["events"]]
            pages: list[str] = []
            for offset in (0, 7, 14):
                p = _admin_get(app, "/admin/api/audit", key=key,
                               params={"limit": "7", "offset": str(offset)}).json()
                assert p["total"] == AUDIT_ADMIN_EVENTS, f"total drift at offset={offset}"
                assert len(p["events"]) == (7 if offset < 14 else 6), \
                    f"page size at offset={offset}: {len(p['events'])}"
                pages.extend(e["request_id"] for e in p["events"])
            assert pages == whole, "分页页拼接 != 全量（顺序或内容漂移）"
            assert len(set(pages)) == AUDIT_ADMIN_EVENTS, "分页页间有重叠"
            beyond = _admin_get(app, "/admin/api/audit", key=key,
                                params={"offset": "99999"}).json()
            assert beyond["total"] == AUDIT_ADMIN_EVENTS and beyond["events"] == [], \
                "越界 offset 应为空页"
            return ("limit=7 × 3 页：页大小 7/7/6、total 恒定 20、"
                    "拼接==全量且零重叠；offset=99999 → 空页")
        finally:
            writer.close()


def check_admin_metrics() -> str:
    """聚合正确性：手算冻结期望值 + 与明细交叉一致 + 部门/时间窗筛选。"""
    with tempfile.TemporaryDirectory() as tmp:
        app, writer, _db = _admin_app(tmp)
        try:
            key = _ADMIN_KEYS["民政局"]
            m = _admin_get(app, "/admin/api/metrics", key=key).json()
            for name, exp in _EXPECTED_METRICS.items():
                got = m if name == "全局" else next(
                    d for d in m["by_dept"] if d["dept"] == name)
                for field in ("requests", "blocked", "block_rate"):
                    assert got[field] == exp[field], f"{name}.{field}: {got[field]} != {exp[field]}"
                assert got["routes"] == exp["routes"], f"{name}.routes: {got['routes']}"
                assert got["reasons"] == exp["reasons"], f"{name}.reasons: {got['reasons']}"
                for field, want in exp["latency_ms"].items():
                    assert got["latency_ms"][field] == want, \
                        f"{name}.latency.{field}: {got['latency_ms'][field]} != {want}"

            # 交叉一致：聚合 == writer.fetch_all() 明细直读（各自独立取数）
            detail = [e for _, e in writer.fetch_all()]
            assert len(detail) == m["requests"] == 20
            dept_count: dict[str, int] = {}
            for e in detail:
                dept_count[e.dept] = dept_count.get(e.dept, 0) + 1
            assert {d["dept"]: d["requests"] for d in m["by_dept"]} == dept_count, \
                "明细与聚合不一致"
            assert sum(m["routes"].values()) == m["requests"], "routes 合计 != requests"

            # 部门筛选：仅该部门聚合
            sub = _admin_get(app, "/admin/api/metrics", key=key,
                             params={"dept": "民政局"}).json()
            assert [d["dept"] for d in sub["by_dept"]] == ["民政局"], sub["by_dept"]
            assert sub["requests"] == 12 and sub["blocked"] == 1
            # 时间窗筛选：闭区间 [03:02,03:04] → 库行 id 3/4/5（夹具 i2/i3/i4，
            # 均 INTERNET）：requests=3、blocked=0、routes={INTERNET:3}、reasons={}
            win = _admin_get(app, "/admin/api/metrics", key=key,
                             params={"from": "2026-09-28T03:02:00Z",
                                     "to": "2026-09-28T03:04:00Z"}).json()
            assert win["requests"] == 3 and win["blocked"] == 0, win
            assert win["routes"] == {"INTERNET": 3} and win["reasons"] == {}, win
            # 含拦截行的窗口 [03:06,03:09] → 库行 id 7/8/9/10（夹具 i6/i7/i8/i9：
            # GOVCLOUD×2 + BLOCK×1 + INTERNET×1）
            win2 = _admin_get(app, "/admin/api/metrics", key=key,
                              params={"from": "2026-09-28T03:06:00Z",
                                      "to": "2026-09-28T03:09:00Z"}).json()
            assert win2["requests"] == 4 and win2["blocked"] == 1, win2
            assert win2["routes"] == {"GOVCLOUD": 2, "BLOCK": 1, "INTERNET": 1}, win2
            assert win2["reasons"] == {"SENSITIVE_ATTR": 2, "CLASSIFICATION_MARK": 1}, win2
            return ("全局+两部门 13 项指标与手算冻结期望全等（含 p50/p90/p95、block_rate）；"
                    "聚合与明细直读交叉一致；dept/时间窗筛选联动正确")
        finally:
            writer.close()


def check_admin_report_csv() -> str:
    """保密自查报告 CSV：BOM/列序/行序/往返全等/公式注入缓解/零明文/筛选。"""
    with tempfile.TemporaryDirectory() as tmp:
        app, writer, _db = _admin_app(tmp)
        try:
            key = _ADMIN_KEYS["民政局"]
            r = _admin_get(app, "/admin/api/report.csv", key=key)
            assert r.status_code == 200, f"status={r.status_code}"
            assert "text/csv" in r.headers.get("content-type", ""), r.headers.get("content-type")
            assert "attachment" in r.headers.get("content-disposition", "").lower()
            raw = r.content
            assert raw.startswith(b"\xef\xbb\xbf"), "CSV 缺 utf-8-sig BOM（Excel 中文兼容）"
            text = raw.decode("utf-8-sig")
            rows = list(csv.reader(io.StringIO(text, newline="")))
            assert rows[0] == list(CSV_HEADERS), f"列序 != CSV_HEADERS: {rows[0]}"
            body = rows[1:]
            assert len(body) == AUDIT_ADMIN_EVENTS, f"rows={len(body)} != {AUDIT_ADMIN_EVENTS}"
            ids = [int(row[0]) for row in body]
            assert ids == sorted(ids) == list(range(1, AUDIT_ADMIN_EVENTS + 1)), \
                "CSV 行序必须 id 升序（时间序）"
            header_index = {name: i for i, name in enumerate(CSV_HEADERS)}
            fixture = _admin_fixture()
            for row, (expect, _values) in zip(body, fixture, strict=True):
                assert row[header_index["ts"]] == expect.ts.strftime(
                    "%Y-%m-%dT%H:%M:%S.%f") + "Z", f"ts 形态: {row[header_index['ts']]}"
                assert row[header_index["request_id"]] == expect.request_id
                assert row[header_index["dept"]] == expect.dept
                assert row[header_index["blocked"]] == ("1" if expect.blocked else "0")
                assert json.loads(row[header_index["reasons"]]) == expect.reasons
                assert json.loads(row[header_index["class_counts"]]) == expect.class_counts
                assert row[header_index["prompt_preview"]] == (
                    expect.prompt_preview if expect.prompt_preview[0] not in "=+-@"
                    else "'" + expect.prompt_preview), \
                    f"公式注入高危单元格未缓解: {row[header_index['prompt_preview']]!r}"
            # 公式注入已缓解：无单元格以 =/+/-/@ 开头（探针行已被前置单引号）
            for row in body:
                for cell in row:
                    assert not cell.startswith(("=", "+", "-", "@")), \
                        f"CSV 公式注入未缓解: {cell[:20]!r}"
            # 红线延续：CSV 字节 bytes 级扫描原值零命中
            hits = [v for v in RAW_VALUES if v.encode("utf-8") in raw]
            assert not hits and len(hits) == AUDIT_RAW_PII_HITS_ALLOWED, \
                f"CSV 导出出现原值: {hits}"
            # 筛选联动 + 空窗
            filtered = _admin_get(app, "/admin/api/report.csv", key=key,
                                  params={"dept": "某镇"})
            frows = list(csv.reader(io.StringIO(filtered.content.decode("utf-8-sig"),
                                                newline="")))
            assert len(frows) - 1 == 8 and all(row[4] == "某镇" for row in frows[1:])
            empty = _admin_get(app, "/admin/api/report.csv", key=key,
                               params={"from": "2027-01-01"})
            assert empty.content.decode("utf-8-sig").strip() == ",".join(CSV_HEADERS), \
                "空窗报告应只剩表头"
            assert len(body) == len(fixture) == AUDIT_ADMIN_EVENTS
            return (f"text/csv + utf-8-sig；列序==CSV_HEADERS；{len(body)} 行 id 升序；"
                    "JSON 字段往返全等；公式注入高危单元格前置引号；"
                    f"{len(raw)} 字节 bytes 级零明文；dept 筛选 8 行、空窗仅表头")
        finally:
            writer.close()


CHECKS = (
    ("audit:wal+schema", check_writer_wal_schema),
    ("audit:writer-roundtrip(30)", check_writer_roundtrip),
    ("audit:persistence-after-close", check_writer_persistence_after_close),
    ("gate:raw-pii-pre-enqueue", check_gate_blocks_before_enqueue),
    ("gate:db-file-bytes-scan", check_db_file_scan_zero_hit),
    ("gate:scan-negative-control", check_db_file_scan_negative_control),
    ("session:stability(100)", check_session_stability),
    ("session:persistence-reopen", check_session_persistence_reopen),
    ("session:lru-revive", check_session_lru_revive),
    ("session:ttl-expiry", check_session_ttl_expiry),
    ("session:ttl-keeps-fresh", check_session_ttl_keeps_fresh),
    ("admin:/admin-api-auth-negatives", check_admin_auth_negatives),
    ("admin:audit-page-filters", check_admin_page_filters),
    ("admin:audit-page-pagination", check_admin_page_pagination),
    ("admin:metrics-aggregation", check_admin_metrics),
    ("admin:report-csv", check_admin_report_csv),
)


def main() -> int:
    for name, fn in CHECKS:
        _record(name, fn)
    for _, line in RESULTS:
        print(line)
    passed = sum(1 for ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"M7 AUDIT(落库完整性/零明文/会话存储 + T5.1 管理面查询 API): "
          f"{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
