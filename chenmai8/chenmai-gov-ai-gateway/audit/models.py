"""契约模型：审计事件 AuditEvent（开发指令 §5.4，冻结——字段只增不改名）。

红线：本模型**不含 raw 字段**，且只存脱敏内容——
- ``prompt_preview`` / ``response_preview``：≤500 字符，且必须已是占位符版本；
- ``reasons`` 为理由码字符串（如 "SENSITIVE_ATTR"）；``class_counts`` 为类别计数；
- 入库前的零明文硬闸 ``assert_no_raw_pii()``（用本次请求 normalized 值列表断言）
  由 audit 包写库层实现（M7/T1.3），失败即 500 且不落库。

T5.1 增补（管理面查询响应，只增不改名；形状定义见 audit/query.py 模块文档）：
- :class:`AuditPage` —— ``GET /admin/api/audit`` 分页响应；
- :class:`LatencyStats` / :class:`DeptMetrics` / :class:`MetricsSummary` ——
  ``GET /admin/api/metrics`` 按部门聚合响应。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AuditEvent(BaseModel):
    """单条审计事件（§5.4 JSON 形状一字不差；库表 audit_events + id 自增在写库层）。"""

    model_config = ConfigDict(extra="forbid")

    ts: datetime                              # UTC ISO8601，序列化为 ...Z
    request_id: str = ""
    session_id: str = ""
    dept: str = ""                            # 由 dept key 反查
    route: Literal["INTERNET", "GOVCLOUD", "BLOCK"] = "INTERNET"
    blocked: bool = False
    reasons: list[str] = Field(default_factory=list)          # 理由码，如 SENSITIVE_ATTR
    class_counts: dict[str, int] = Field(default_factory=dict)  # {"ID_CARD": 2, ...}
    prompt_preview: str = Field(default="", max_length=500)
    response_preview: str = Field(default="", max_length=500)
    upstream: str | None = None
    latency_ms: int = Field(default=0, ge=0)
    flags: list[str] = Field(default_factory=list)            # 如 injection

    @field_validator("ts", mode="after")
    @classmethod
    def _utc_ts(cls, v: datetime) -> datetime:
        """naive datetime 一律视为 UTC（工程约定：时间统一 UTC ISO8601 存储）。"""
        return v.replace(tzinfo=UTC) if v.tzinfo is None else v


class AuditPage(BaseModel):
    """``GET /admin/api/audit`` 分页响应（T5.1）。

    - ``total``：筛选命中总数（与分页参数无关，看板/交叉核对口径）；
    - ``events``：本页事件（§5.4 形状，``id`` 降序=新→旧）；
    - ``limit`` / ``offset``：实际生效的分页参数（调用方已校验范围）。
    """

    model_config = ConfigDict(extra="forbid")

    total: int
    limit: int
    offset: int
    events: list[AuditEvent] = Field(default_factory=list)


class LatencyStats(BaseModel):
    """延迟分位统计（单位 ms；线性插值分位，0 条事件时全部为 0.0）。"""

    model_config = ConfigDict(extra="forbid")

    count: int = 0
    avg_ms: float = 0.0
    p50_ms: float = 0.0
    p90_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0


class DeptMetrics(BaseModel):
    """单部门聚合（拦截数 / 路由分布 / 理由码 / 延迟分位）。"""

    model_config = ConfigDict(extra="forbid")

    dept: str
    requests: int = 0
    blocked: int = 0
    block_rate: float = 0.0
    routes: dict[str, int] = Field(default_factory=dict)
    reasons: dict[str, int] = Field(default_factory=dict)
    latency_ms: LatencyStats = Field(default_factory=LatencyStats)


class MetricsSummary(BaseModel):
    """``GET /admin/api/metrics`` 聚合响应（T5.1）：全局汇总 + 按部门明细。"""

    model_config = ConfigDict(extra="forbid")

    window_from: str | None = None
    window_to: str | None = None
    requests: int = 0
    blocked: int = 0
    block_rate: float = 0.0
    routes: dict[str, int] = Field(default_factory=dict)
    reasons: dict[str, int] = Field(default_factory=dict)
    latency_ms: LatencyStats = Field(default_factory=LatencyStats)
    by_dept: list[DeptMetrics] = Field(default_factory=list)
