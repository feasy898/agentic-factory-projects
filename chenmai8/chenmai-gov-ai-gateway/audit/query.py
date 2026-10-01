"""审计查询面（T5.1）：``/admin/api/*`` 的只读查询 / 聚合 / CSV 行集层。

上游契约（开发指令 §5.6，路径与筛选参数名冻结——只增不改名）::

    GET /admin/api/audit      ?dept=&route=&blocked=&from=&to=&limit=&offset=
                              → :class:`AuditPage`（total + 本页 events，id 降序）
    GET /admin/api/metrics    ?dept=&from=&to=
                              → :class:`MetricsSummary`（拦截数/路由分布/延迟分位，按部门）
    GET /admin/api/report.csv ?dept=&from=&to=
                              → text/csv（保密自查报告；列 = :data:`CSV_HEADERS`，id 升序）

四条约束（设计红线）：
1. **只读**：本模块只以 :func:`connect_readonly` 打开审计库（``mode=ro`` URI，
   ``query_only`` 兜底），绝不新开写连接、绝不触 masking_map（会话映射按设计另库存
   归一化原值，见 masking/session_store.py 模块文档）；
2. **全常量 SQL + 参数绑定**：所有 SQL 语句均为**模块级整常量**（:data:`_SQL_*`），
   运行期零字符串拼接/零 format/零 f-string；外部输入（筛选值/分页参数）一律经
   ``?`` 占位绑定注入，筛选为「可空绑定」形态（``(? IS NULL OR dept = ?)``——
   ``None`` 即不加该条件），从结构上排除注入面；
3. **零明文延续**：查询/导出的全部字段直接来自 audit_events 表（脱敏预览），不引入
   任何原始文本路径（红线来源 §5.4 / §11 风险 9）；
4. **只读契约**：函数只接受 :class:`sqlite3.Connection`（调用方负责连接生命周期）。

时间窗口径：库内 ``ts`` 为定长 UTC ISO8601 文本（common.timeutil.iso_utc →
``YYYY-MM-DDTHH:MM:SS.ffffffZ``），字典序即时间序；``from``/``to`` 先解析再
:func:`common.timeutil.iso_utc` 归一为同形态做字符串比较——边界为**闭区间**
（``from <= ts <= to``）。``from``/``to`` 仅给日期（``YYYY-MM-DD``）时按自然日
解释：``from`` 取当日 00:00:00.000000，``to`` 取当日 23:59:59.999999（含当天）。
"""
from __future__ import annotations

import csv
import io
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from audit.models import AuditPage, DeptMetrics, LatencyStats, MetricsSummary
from audit.writer import row_to_event
from common.timeutil import iso_utc, parse_utc

#: 允许筛选的路由值（§5.2 RouteDecision.route；契约外值由调用方拒绝）
VALID_ROUTES: tuple[str, ...] = ("INTERNET", "GOVCLOUD", "BLOCK")

#: 保密自查报告 CSV 列序（§5.4 AuditEvent 字段 + 行 id；列名即形状，只增不改名）
CSV_HEADERS: tuple[str, ...] = (
    "id", "ts", "request_id", "session_id", "dept", "route", "blocked",
    "reasons", "class_counts", "prompt_preview", "response_preview",
    "upstream", "latency_ms", "flags",
)

#: CSV 公式注入高危首字符（OWASP CSV Injection 缓解：前置一个半角单引号）
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

# ── SQL（全部为模块级整常量；外部输入只经 ``?`` 绑定，运行期零拼接）─────────
_EVENT_COLUMNS = (
    "SELECT id, ts, request_id, session_id, dept, route, blocked, reasons, class_counts, "
    "prompt_preview, response_preview, upstream, latency_ms, flags FROM audit_events"
)
_METRICS_COLUMNS = (
    "SELECT dept, route, blocked, reasons, latency_ms FROM audit_events"
)
#: 可空绑定谓词：绑定值为 NULL（Python None）时该条件不加
#: （参数序：dept,dept,route,route,blocked,blocked,from,from,to,to）
_PREDICATES = (
    " WHERE (? IS NULL OR dept = ?)"
    " AND (? IS NULL OR route = ?)"
    " AND (? IS NULL OR blocked = ?)"
    " AND (? IS NULL OR ts >= ?)"
    " AND (? IS NULL OR ts <= ?)"
)
_SQL_COUNT = "SELECT COUNT(*) FROM audit_events" + _PREDICATES
_SQL_PAGE = _EVENT_COLUMNS + _PREDICATES + " ORDER BY id DESC LIMIT ? OFFSET ?"
_SQL_ROWS = _EVENT_COLUMNS + _PREDICATES + " ORDER BY id"
_SQL_METRICS = _METRICS_COLUMNS + _PREDICATES + " ORDER BY id"


# ── 筛选条件 ─────────────────────────────────────────────────────
@dataclass(frozen=True)
class EventFilter:
    """事件筛选（None = 不加该条件）。字段名与 §5.6 查询参数一一对应。"""

    dept: str | None = None
    route: str | None = None
    blocked: bool | None = None
    ts_from: datetime | None = None
    ts_to: datetime | None = None

    def bind_params(self) -> tuple[Any, ...]:
        """→ 可空绑定参数元组（顺序与 :data:`_PREDICATES` 占位符一一对应）。

        布尔字段以库内存储形态（0/1）绑定；时间边界先归一为定长 ISO 存储文本
        （字符串比较即时间比较，闭区间）。
        """
        return (
            self.dept, self.dept,
            self.route, self.route,
            (None if self.blocked is None else (1 if self.blocked else 0)),
            (None if self.blocked is None else (1 if self.blocked else 0)),
            (iso_utc(self.ts_from) if self.ts_from is not None else None),
            (iso_utc(self.ts_from) if self.ts_from is not None else None),
            (iso_utc(self.ts_to) if self.ts_to is not None else None),
            (iso_utc(self.ts_to) if self.ts_to is not None else None),
        )


# ── 只读连接 ─────────────────────────────────────────────────────
def connect_readonly(db_path: str | Path) -> sqlite3.Connection:
    """只读打开审计库（``mode=ro`` URI 优先；失败回退普通连接 + ``query_only``）。

    URI 形如 ``file:///D:/.../audit.db?mode=ro``（:meth:`Path.as_uri` 负责
    转义）；只读连接在写方持有热 WAL 时同样可读（-shm 旁挂存在即可，见
    仓库实测探针 tmp/probe_ro_conn.py）。文件不存在时抛 OperationalError——
    调用方（端点层）负责把"库未初始化"呈现为空结果，而不是让只读连接顺手
    把空库文件创建出来。
    """
    path = Path(db_path).resolve()
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()  # 探测可打开
    except sqlite3.Error:
        if conn is not None:
            conn.close()
        conn = sqlite3.connect(str(path))  # 兜底：正常连接 + query_only（仍不可写）
        conn.execute("PRAGMA query_only=ON")
    return conn


@contextmanager
def open_readonly(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    """只读连接的 with 形态（请求级短连接，用完即关）。"""
    conn = connect_readonly(db_path)
    try:
        yield conn
    finally:
        conn.close()


# ── 分页查询 ─────────────────────────────────────────────────────
def count_events(conn: sqlite3.Connection, f: EventFilter) -> int:
    """筛选命中总数（与分页参数无关）。"""
    row = conn.execute(_SQL_COUNT, f.bind_params()).fetchone()
    return int(row[0])


def page_events(
    conn: sqlite3.Connection, f: EventFilter, *, limit: int, offset: int
) -> AuditPage:
    """分页事件页：``ORDER BY id DESC``（新→旧），``LIMIT``/``OFFSET`` 绑定注入。"""
    total = count_events(conn, f)
    rows = conn.execute(_SQL_PAGE, (*f.bind_params(), limit, offset)).fetchall()
    events = [row_to_event(r) for r in rows]
    return AuditPage(total=total, limit=limit, offset=offset, events=events)


# ── 聚合（metrics）───────────────────────────────────────────────
def _percentile(sorted_vals: list[float], q: float) -> float:
    """线性插值分位（q∈[0,100]）；空集返回 0.0。

    口径：rank = (n-1)·q/100，向两侧线性插值（与常见统计库默认一致）。
    """
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    if n == 1:
        return float(sorted_vals[0])
    rank = (n - 1) * (q / 100.0)
    lo = int(rank)
    hi = min(lo + 1, n - 1)
    frac = rank - lo
    return float(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac)


def _latency_stats(values: list[int]) -> LatencyStats:
    ordered = sorted(float(v) for v in values)
    if not ordered:
        return LatencyStats(count=0)
    count = len(ordered)
    return LatencyStats(
        count=count,
        avg_ms=round(sum(ordered) / count, 6),
        p50_ms=round(_percentile(ordered, 50), 6),
        p90_ms=round(_percentile(ordered, 90), 6),
        p95_ms=round(_percentile(ordered, 95), 6),
        p99_ms=round(_percentile(ordered, 99), 6),
    )


def _rate(part: int, total: int) -> float:
    return round(part / total, 6) if total else 0.0


class _Accum:
    """单桶聚合累加器（内部）。"""

    __slots__ = ("requests", "blocked", "routes", "reasons", "latencies")

    def __init__(self) -> None:
        self.requests = 0
        self.blocked = 0
        self.routes: dict[str, int] = {}
        self.reasons: dict[str, int] = {}
        self.latencies: list[int] = []

    def add(self, route: str, blocked: bool, reasons_json: str, latency_ms: int) -> None:
        self.requests += 1
        if blocked:
            self.blocked += 1
        self.routes[route] = self.routes.get(route, 0) + 1
        for code in _parse_reasons(reasons_json):
            self.reasons[code] = self.reasons.get(code, 0) + 1
        self.latencies.append(int(latency_ms))


def _parse_reasons(reasons_json: str) -> list[str]:
    """reasons 列（JSON 数组文本）→ 理由码列表；坏值按空表处理（查询面不抛）。"""
    try:
        value = json.loads(reasons_json)
    except ValueError:
        return []
    return [str(v) for v in value] if isinstance(value, list) else []


def aggregate_metrics(conn: sqlite3.Connection, f: EventFilter) -> MetricsSummary:
    """按部门聚合：请求数 / 拦截数 / 路由分布 / 理由码 / 延迟分位 + 全局汇总。

    单次窗口查询取出 (dept, route, blocked, reasons, latency_ms) 后 Python 侧
    聚合——聚合口径（计数/分位）与明细直读互为独立交叉验证（e2e U5 即用其对账）。
    """
    rows = conn.execute(_SQL_METRICS, f.bind_params()).fetchall()

    per_dept: dict[str, _Accum] = {}
    overall = _Accum()
    for dept, route, blocked, reasons_json, latency in rows:
        acc = per_dept.setdefault(dept, _Accum())
        overall.add(route, bool(blocked), reasons_json, latency)
        acc.add(route, bool(blocked), reasons_json, latency)

    by_dept = [
        DeptMetrics(
            dept=dept,
            requests=acc.requests,
            blocked=acc.blocked,
            block_rate=_rate(acc.blocked, acc.requests),
            routes=dict(sorted(acc.routes.items())),
            reasons=dict(sorted(acc.reasons.items())),
            latency_ms=_latency_stats(acc.latencies),
        )
        for dept, acc in sorted(per_dept.items())
    ]
    return MetricsSummary(
        window_from=iso_utc(f.ts_from) if f.ts_from is not None else None,
        window_to=iso_utc(f.ts_to) if f.ts_to is not None else None,
        requests=overall.requests,
        blocked=overall.blocked,
        block_rate=_rate(overall.blocked, overall.requests),
        routes=dict(sorted(overall.routes.items())),
        reasons=dict(sorted(overall.reasons.items())),
        latency_ms=_latency_stats(overall.latencies),
        by_dept=by_dept,
    )


# ── 保密自查报告 CSV ─────────────────────────────────────────────
def _csv_cell(value: Any) -> Any:
    """CSV 单元格公式注入缓解：文本以 =/+/-/@ 等开头时前置半角单引号。

    审计库里可导出字段是预览/摘要（占位符文本），但自我检查报告要落到
    终端用户的 Excel 里——这是演示口径上也该有的卫生动作（OWASP CSV
    Injection 缓解；数字/空值不受影响）。
    """
    if isinstance(value, str) and value.startswith(_CSV_FORMULA_PREFIXES):
        return "'" + value
    return value


def report_rows(conn: sqlite3.Connection, f: EventFilter) -> Iterator[dict[str, Any]]:
    """报告数据行（``id`` 升序=时间序；键 = :data:`CSV_HEADERS`）。"""
    for row in conn.execute(_SQL_ROWS, f.bind_params()):
        row_dict = {name: _csv_cell(row[i + 1]) for i, name in enumerate(CSV_HEADERS[1:])}
        yield {"id": int(row[0]), **row_dict}


def report_csv(conn: sqlite3.Connection, f: EventFilter) -> str:
    """保密自查报告 CSV 文本（UTF-8；调用方加 BOM 后以 text/csv 回传）。

    列：:data:`CSV_HEADERS`（事件形态 + 时间序）。``reasons`` / ``class_counts`` /
    ``flags`` 为库内 JSON 串（ensure_ascii=False → 中文理由码可读）；``blocked``
    为 0/1（库内存储形态，机器可解析）。
    """
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=list(CSV_HEADERS), extrasaction="raise")
    writer.writeheader()
    for row in report_rows(conn, f):
        writer.writerow(row)
    return buf.getvalue()


# ── 时间解析（端点层调用；失败抛 ValueError → 400 错误信封）─────────
def parse_bound(raw: str | None, *, end_of_day: bool) -> datetime | None:
    """解析时间窗边界（ISO8601 或 ``YYYY-MM-DD``；空串/None → None）。

    ``end_of_day=True``（``to`` 侧）的纯日期输入解释为当日 23:59:59.999999
    （含当天）；``False``（``from`` 侧）为当日 00:00:00.000000。
    """
    if raw is None or raw.strip() == "":
        return None
    text = raw.strip()
    if len(text) == 10:  # 纯日期（strptime 拒绝带时间部分的脏值）
        try:
            day = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError as exc:
            raise ValueError(f"invalid date: {raw!r}") from exc
        if end_of_day:
            return day + timedelta(hours=23, minutes=59, seconds=59, microseconds=999999)
        return day
    try:
        return parse_utc(text)
    except ValueError as exc:
        raise ValueError(f"invalid timestamp: {raw!r}") from exc
