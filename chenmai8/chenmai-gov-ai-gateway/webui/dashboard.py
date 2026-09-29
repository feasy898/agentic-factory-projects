"""看板聚合（T5.2）：审计事件 → 指标卡/路由分布/Top 部门/SVG 柱状图/分页明细。

纯函数层（无副作用、无 SQL——事件读取经 :func:`read_events` 适配既有审计存储
``InMemoryAuditStore.snapshot()`` / ``SqliteAuditWriter.fetch_all()`` 两种形态，
分页/过滤在 Python 内存完成，不触碰数据库查询面）：

- :func:`daily_kpi`   指标卡：今日（UTC 日界）请求/拦截、拦截率、事件总数；
- :func:`route_distribution`  路由分布（INTERNET/GOVCLOUD/BLOCK 计数）；
- :func:`top_depts`   Top 部门（按请求数降序，取前 N）；
- :func:`top_categories`  命中类别 Top N（class_counts 跨事件求和）；
- :func:`bar_chart_svg`   手写 SVG 柱状图（无前端框架、无外部库——字符串拼装）；
- :func:`paginate`    明细分页（新→旧，钳位越界页码）。

SVG 安全注记：标签文本一律经 :func:`html.escape` 转义后拼入 ``<text>``，
数值全部 int 化，杜绝模板注入面。
"""
from __future__ import annotations

import html
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from audit.models import AuditEvent

#: 路由取值与展示顺序（冻结契约 §5.2 route 枚举）
ROUTES: tuple[str, ...] = ("INTERNET", "GOVCLOUD", "BLOCK")

#: route 徽标 CSS 类（看板明细表与聊天页共用口径）
ROUTE_BADGE_CLASS: dict[str, str] = {
    "INTERNET": "badge-internet",
    "GOVCLOUD": "badge-govcloud",
    "BLOCK": "badge-block",
}

#: 图表/榜单默认条数
TOP_N = 6

#: 明细分页默认与可选页大小（页面下拉即此清单）
PAGE_SIZE_DEFAULT = 10
PAGE_SIZES: tuple[int, ...] = (10, 20, 50)


def read_events(store: Any) -> list[AuditEvent]:
    """从审计存储读全部事件（适配两种既有形态；读不到返回空表）。

    - :class:`audit.store.InMemoryAuditStore` → ``snapshot()``（事件列表）；
    - :class:`audit.writer.SqliteAuditWriter` → ``fetch_all()``（(id, event) 元组列表）。
    """
    for name in ("snapshot", "fetch_all"):
        fn = getattr(store, name, None)
        if callable(fn):
            rows = fn()
            return [row[1] if isinstance(row, tuple) and len(row) == 2 else row
                    for row in rows]
    return []


def daily_kpi(events: list[AuditEvent], *, now: datetime | None = None) -> dict[str, Any]:
    """指标卡数值：今日请求/今日拦截（UTC 日界）、拦截率（今日）、事件总数。"""
    moment = now or datetime.now(UTC)
    today = moment.astimezone(UTC).date()
    today_events = [e for e in events if e.ts.astimezone(UTC).date() == today]
    blocked_today = sum(1 for e in today_events if e.blocked)
    rate = round(blocked_today * 100 / len(today_events), 1) if today_events else 0.0
    return {
        "total": len(events),
        "today_total": len(today_events),
        "today_blocked": blocked_today,
        "today_block_rate": rate,
        "blocked_total": sum(1 for e in events if e.blocked),
    }


def route_distribution(events: list[AuditEvent]) -> list[dict[str, Any]]:
    """三路由计数（保持 INTERNET/GOVCLOUD/BLOCK 展示顺序；零计数也保留行）。"""
    counts = Counter(e.route for e in events)
    total = len(events)
    return [{"route": route, "count": counts.get(route, 0),
             "pct": round(counts.get(route, 0) * 100 / total, 1) if total else 0.0}
            for route in ROUTES]


def top_depts(events: list[AuditEvent], n: int = TOP_N) -> list[dict[str, Any]]:
    """Top 部门（请求数降序；空部门名归入「（未记部门）」）。"""
    counts = Counter(e.dept or "（未记部门）" for e in events)
    return [{"dept": dept, "count": count}
            for dept, count in counts.most_common(max(1, n))]


def top_categories(events: list[AuditEvent], n: int = TOP_N) -> list[dict[str, Any]]:
    """命中类别 Top N（class_counts 跨事件求和降序）。"""
    counts: Counter[str] = Counter()
    for e in events:
        counts.update({k: int(v) for k, v in e.class_counts.items() if v})
    return [{"category": cat, "count": count}
            for cat, count in counts.most_common(max(1, n))]


def bar_chart_svg(rows: list[dict[str, Any]], *, label_key: str, value_key: str,
                  title: str, color: str = "#2563eb", width: int = 460) -> str:
    """手写 SVG 水平柱状图（无前端框架/无图表库）。

    - 每行：类别标签（左，最长 140px 区右对齐）+ 柱条 + 数值（柱条右侧）；
    - 比例尺：最大值为满宽；全零数据画零宽柱（数值仍可见）；
    - 行高固定 30px，标签 12px 省略到 10 字符（演示数据均为短标签）。
    """
    label_w, bar_gap, row_h, pad_top = 140, 8, 30, 6
    value_w = 52
    bar_max = max(10, width - label_w - value_w - 2 * bar_gap)
    values = [max(0, int(r[value_key])) for r in rows]
    peak = max(values, default=0)
    height = pad_top * 2 + row_h * len(rows)
    parts = [
        f'<svg class="chart" role="img" aria-label="{html.escape(title)}" '
        f'viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'xmlns="http://www.w3.org/2000/svg">',
        f'<title>{html.escape(title)}</title>',
    ]
    for i, row in enumerate(rows):
        y = pad_top + i * row_h
        label = str(row[label_key])
        if len(label) > 10:
            label = label[:9] + "…"
        value = values[i]
        bar_w = round(value * bar_max / peak) if peak else 0
        parts.append(
            f'<text x="{label_w - 6}" y="{y + 14}" text-anchor="end" '
            f'class="chart-label">{html.escape(label)}</text>'
            f'<rect x="{label_w}" y="{y + 2}" width="{bar_w}" height="18" rx="3" '
            f'fill="{color}"></rect>'
            f'<text x="{label_w + bar_w + 6}" y="{y + 16}" class="chart-value">{value}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def route_badge(route: str) -> str:
    """route 徽标 HTML（明细表/聊天页共用视觉：INTERNET 蓝 / GOVCLOUD 绿 / BLOCK 红）。"""
    cls = ROUTE_BADGE_CLASS.get(route, "badge-internet")
    return f'<span class="badge {cls}">{html.escape(route)}</span>'


def paginate(events: list[AuditEvent], page: int, page_size: int) -> dict[str, Any]:
    """明细表分页（新→旧即 id/ts 倒序；页码/页大小钳位，杜绝越界与非法输入）。"""
    size = page_size if page_size in PAGE_SIZES else PAGE_SIZE_DEFAULT
    total = len(events)
    total_pages = max(1, -(-total // size))
    cur = min(max(1, page), total_pages)
    ordered = sorted(events, key=lambda e: e.ts, reverse=True)
    start = (cur - 1) * size
    rows = ordered[start:start + size]
    return {"rows": rows, "page": cur, "page_size": size,
            "total": total, "total_pages": total_pages}


def summarize(events: list[AuditEvent]) -> dict[str, Any]:
    """看板页一揽子视图模型（页面路由一次取齐）。"""
    return {
        "kpi": daily_kpi(events),
        "routes": route_distribution(events),
        "depts": top_depts(events),
        "categories": top_categories(events),
    }
