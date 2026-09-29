"""管理面查询 API（T5.1）：``/admin/api/audit`` / ``/admin/api/metrics`` / ``/admin/api/report.csv``。

契约（开发指令 §5.6，路径与筛选参数名冻结——只增不改名）::

    GET /admin/api/audit      ?dept=&route=&blocked=&from=&to=&limit=&offset=
                              → {"total", "limit", "offset", "events": [AuditEvent…]}
                                （events = §5.4 形状，id 降序=新→旧；total = 筛选命中总数）
    GET /admin/api/metrics    ?dept=&from=&to=
                              → MetricsSummary（拦截数/路由分布/理由码/延迟分位，按部门）
    GET /admin/api/report.csv ?dept=&from=&to=
                              → text/csv；utf-8-sig（Excel 中文兼容）；列=CSV_HEADERS，id 升序

筛选参数（与 §5.6 表一致）：
- ``dept``：精确部门名（如 民政局）；
- ``route``：``INTERNET`` | ``GOVCLOUD`` | ``BLOCK``；
- ``blocked``：``true``/``false``/``1``/``0``；
- ``from`` / ``to``：ISO8601 或 ``YYYY-MM-DD``（闭区间；纯日期含当天，见
  audit/query.py 时间窗口径）；
- ``limit`` / ``offset``：分页（缺省 limit=AUDIT_PAGE_LIMIT_DEFAULT、上限
  AUDIT_PAGE_LIMIT_MAX，offset 缺省 0）；非整数 / 越界 → 400 ``bad_request``。

鉴权（全部管理面端点，与 /internal/* 同一硬口径）：任意一个有效部门 Key
（``Authorization: Bearer <dept_key>``）放行——管理面语义=看板/自查/管理用途的
只读脱敏视图；缺 key / 错 key → 401 ``unauthorized``。生产部署另须仅经本地
管理面/内网访问（与 /internal/* 同一安全注记，见 gateway/app.py 模块文档）。

只读：三条端点只经 audit/query.py 的只读连接读 audit_events（脱敏预览，
§5.4 红线），绝不暴露 raw 路径、绝不触 masking_map（会话映射另库存归一化原值）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from audit.models import AuditPage, MetricsSummary
from audit.query import (
    VALID_ROUTES,
    EventFilter,
    aggregate_metrics,
    open_readonly,
    page_events,
    parse_bound,
    report_csv,
)
from audit.writer import SqliteAuditWriter
from evals.thresholds import AUDIT_PAGE_LIMIT_DEFAULT, AUDIT_PAGE_LIMIT_MAX
from gateway import deps
from gateway.models import ApiError, ErrorBody

# 错误信封 code（与 gateway/pipeline 错误词表同源——只增不改名）
CODE_BAD_REQUEST = "bad_request"
CODE_UNAUTHORIZED = "unauthorized"

#: CSV 上报头附件名（保密自查报告；中文名走 RFC 5987 扩展）
REPORT_FILENAME = "保密自查报告.csv"


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    """§5.6 错误信封（与 gateway/app 同一形状）。"""
    return JSONResponse(ApiError(error=ErrorBody(code=code, message=message)).model_dump(),
                        status_code=status_code)


def _audit_db_path(app: FastAPI) -> Path:
    """审计库路径：优先取生产写库实例（SqliteAuditWriter.db_path），否则按 cfg 解析。"""
    from gateway.app import resolve_db_path  # noqa: PLC0415 — 防环导入

    audit = getattr(app.state, "audit", None)
    if isinstance(audit, SqliteAuditWriter):
        return Path(audit.db_path)
    return resolve_db_path(app.state.cfg.audit_db)


def _authenticate(app: FastAPI, request: Request) -> str | None:
    """部门 Key 鉴权（常量时间比较，与 /v1/chat/completions 同一实现）；未命中 None。"""
    return deps.authenticate(
        deps.extract_bearer(request.headers.get("authorization")),
        app.state.dept_key_digests,
    )


def _parse_common_filters(query: Any) -> EventFilter:
    """解析公共筛选参数（dept/route/blocked/from/to）；非法值抛 ValueError。"""
    route = query.get("route")
    if route is not None and route != "":
        if route not in VALID_ROUTES:
            raise ValueError(f"route must be one of {VALID_ROUTES}, got {route!r}")
    else:
        route = None

    blocked_raw = query.get("blocked")
    blocked: bool | None
    if blocked_raw in (None, ""):
        blocked = None
    elif blocked_raw in ("true", "1"):
        blocked = True
    elif blocked_raw in ("false", "0"):
        blocked = False
    else:
        raise ValueError(f"blocked must be true/false, got {blocked_raw!r}")

    return EventFilter(
        dept=(query.get("dept") or None),
        route=route,
        blocked=blocked,
        ts_from=parse_bound(query.get("from"), end_of_day=False),
        ts_to=parse_bound(query.get("to"), end_of_day=True),
    )


def _parse_paging(query: Any) -> tuple[int, int]:
    """分页参数（limit/offset）：limit 缺省　AUDIT_PAGE_LIMIT_DEFAULT、超上限钳制；
    offset 缺省 0。非整数 / limit<1 / offset<0 → ValueError。"""
    limit = _parse_int(query.get("limit"), AUDIT_PAGE_LIMIT_DEFAULT, "limit")
    offset = _parse_int(query.get("offset"), 0, "offset")
    if limit < 1 or limit > AUDIT_PAGE_LIMIT_MAX:
        raise ValueError(f"limit must be in [1, {AUDIT_PAGE_LIMIT_MAX}], got {limit}")
    if offset < 0:
        raise ValueError(f"offset must be >= 0, got {offset}")
    return limit, offset


def mount(app: FastAPI) -> None:
    """把管理面查询 API 挂到网关应用（create_app 末尾调用）。"""

    @app.get("/admin/api/audit")
    async def admin_api_audit(request: Request) -> JSONResponse:
        if _authenticate(app, request) is None:
            return _error_response(401, CODE_UNAUTHORIZED,
                                   "无效部门 Key（Authorization: Bearer dk_***）")
        try:
            f = _parse_common_filters(request.query_params)
            limit, offset = _parse_paging(request.query_params)
        except ValueError as exc:
            return _error_response(400, CODE_BAD_REQUEST, str(exc))

        db_path = _audit_db_path(app)
        if not db_path.exists():
            return JSONResponse(AuditPage(total=0, limit=limit, offset=offset).model_dump(mode="json"))
        with open_readonly(db_path) as conn:
            page = page_events(conn, f, limit=limit, offset=offset)
        return JSONResponse(page.model_dump(mode="json"))

    @app.get("/admin/api/metrics")
    async def admin_api_metrics(request: Request) -> JSONResponse:
        if _authenticate(app, request) is None:
            return _error_response(401, CODE_UNAUTHORIZED,
                                   "无效部门 Key（Authorization: Bearer dk_***）")
        try:
            f = _parse_common_filters(request.query_params)
        except ValueError as exc:
            return _error_response(400, CODE_BAD_REQUEST, str(exc))

        db_path = _audit_db_path(app)
        if not db_path.exists():
            return JSONResponse(MetricsSummary().model_dump(mode="json"))
        with open_readonly(db_path) as conn:
            summary = aggregate_metrics(conn, f)
        return JSONResponse(summary.model_dump(mode="json"))

    @app.get("/admin/api/report.csv")
    async def admin_api_report_csv(request: Request) -> Response:
        if _authenticate(app, request) is None:
            return _error_response(401, CODE_UNAUTHORIZED,
                                   "无效部门 Key（Authorization: Bearer dk_***）")
        try:
            f = _parse_common_filters(request.query_params)
        except ValueError as exc:
            return _error_response(400, CODE_BAD_REQUEST, str(exc))

        db_path = _audit_db_path(app)
        text = ""
        if db_path.exists():
            with open_readonly(db_path) as conn:
                text = report_csv(conn, f)
        payload = b"\xef\xbb\xbf" + text.encode("utf-8")   # utf-8-sig：Excel 中文兼容
        return Response(content=payload, media_type="text/csv; charset=utf-8", headers={
            "Content-Disposition": _content_disposition(REPORT_FILENAME),
        })


def _parse_int(raw: str | None, default: int, name: str) -> int:
    """查询参数 → 非负整数；缺省回落 default，非整数抛 ValueError。"""
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _content_disposition(filename: str) -> str:
    """附件下载头：ASCII 兜底名 + RFC 5987 UTF-8 扩展名（报头仅允许 latin-1 字节）。"""
    ascii_name = filename.encode("ascii", "replace").decode("ascii").replace('"', "_")
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(filename)}'
