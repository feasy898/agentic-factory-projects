"""契约模型：路由决策 RouteDecision（开发指令 §5.2，冻结——字段只增不改名）。

routing → gateway 的唯一接口形状；决策矩阵为纯函数（M4 实现），本文件只定契约。

``RouteReason.code`` 取值词汇表（与 §5.2 决策矩阵逐行对应；字段类型为 str，
新增码值不构成契约变更）::

    CLASSIFICATION_MARK / INJECTION          → BLOCK
    WORK_SECRET / SENSITIVE_ATTR             → GOVCLOUD
    BATCH_STRUCTURED_PII（同请求 ≥3 结构化号码）→ GOVCLOUD
    SINGLE_STRUCTURED_PII                    → INTERNET（mask_required=true）
    WHITELIST_ONLY / NO_FINDING              → INTERNET
    WHITELIST_HIT（白名单命中留存条，附于 WHITELIST_ONLY 之后）→ INTERNET
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Route = Literal["INTERNET", "GOVCLOUD", "BLOCK"]

#: 决策矩阵触发的理由码词汇表（文档性常量，供 M4/测试引用）
REASON_CODES: tuple[str, ...] = (
    "CLASSIFICATION_MARK",
    "INJECTION",
    "WORK_SECRET",
    "SENSITIVE_ATTR",
    "BATCH_STRUCTURED_PII",
    "SINGLE_STRUCTURED_PII",
    "WHITELIST_ONLY",
    "WHITELIST_HIT",
    "NO_FINDING",
)


class RouteReason(BaseModel):
    """单条路由理由（有序 reasons 的元素，第一条为决定性理由）。"""

    model_config = ConfigDict(extra="forbid")

    code: str                                 # 见模块 docstring 词汇表
    fid: str | None = None                    # 关联 Finding.fid；无关联时 null
    detail: str = ""                          # 人类可读细节，如 "命中 机密★"


class RouteDecision(BaseModel):
    """路由决策（§5.2 JSON 形状一字不差）。"""

    model_config = ConfigDict(extra="forbid")

    route: Route = "INTERNET"
    reasons: list[RouteReason] = Field(default_factory=list)
    upstream: str | None = None               # config/app.yaml 上游名；BLOCK 时必须为 null
    mask_required: bool = False               # 按实际 findings 决定
    labels: dict[str, bool] = Field(default_factory=lambda: {"ai_generated": True})

    @model_validator(mode="after")
    def _block_drops_upstream(self) -> RouteDecision:
        if self.route == "BLOCK" and self.upstream is not None:
            raise ValueError("route=BLOCK 时 upstream 必须为 null（§5.2）")
        return self
