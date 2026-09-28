"""M7 审计验收（T1.3 覆盖部分：落库完整性 / 零明文硬闸与全库扫描 / 会话存储）。

运行::

    cd REPO_ROOT && PYTHONUTF8=1 ./.venv/Scripts/python.exe -m evals.m7_audit

exit 0 = 通过。本任务覆盖面（开发指令 §6 M7 + workflow T1.3；查询/聚合/CSV 与
20 混合请求口径自 T5.1 起补入本入口）：

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
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from audit.models import AuditEvent  # noqa: E402
from audit.store import (  # noqa: E402
    RawPiiLeakError,
    assert_db_no_raw_pii,
    assert_no_raw_pii,
    scan_db_files,
)
from audit.writer import SqliteAuditWriter, count_events, read_events  # noqa: E402
from evals.thresholds import (  # noqa: E402
    AUDIT_APPEND_BATCH_MS,
    AUDIT_FLUSH_TIMEOUT_S,
    AUDIT_RAW_PII_HITS_ALLOWED,
    AUDIT_SESSION_STABILITY_VALUES,
    AUDIT_WRITER_EVENTS,
    SESSION_TTL_PROBE_MS,
)
from masking.mapper import RESTORE_PATTERN  # noqa: E402
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
)


def main() -> int:
    for name, fn in CHECKS:
        _record(name, fn)
    for _, line in RESULTS:
        print(line)
    passed = sum(1 for ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"M7 AUDIT(T1.3 部分: 落库完整性/零明文/会话存储): {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
