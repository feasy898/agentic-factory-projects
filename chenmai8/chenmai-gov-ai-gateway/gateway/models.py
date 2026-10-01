"""契约模型：HTTP API 错误体（开发指令 §5.6，冻结——字段只增不改名）。

线上形状（一字不差）::

    HTTP 403
    {"error": {"code": "content_blocked",
               "message": "涉密/涉敏内容已拦截…",
               "reasons": [{"code": "CLASSIFICATION_MARK", "fid": "f_0007",
                            "detail": "命中 机密★"}]}}

- BLOCK 拦截：code 固定 ``content_blocked``，WebUI 将其渲染为提示卡；
- 其他 4xx/5xx 复用同一信封（code 取 ``bad_request`` / ``payload_too_large`` /
  ``unauthorized`` / ``internal_error`` 等），``reasons`` 通常为空。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from routing.models import RouteReason

#: 拦截类错误的固定码值（§5.6）
CODE_CONTENT_BLOCKED = "content_blocked"


class ErrorBody(BaseModel):
    """错误详情（信封 ``error`` 键的值）。"""

    model_config = ConfigDict(extra="forbid")

    code: str = CODE_CONTENT_BLOCKED
    message: str = ""                         # 人类可读提示（代答/拒答文案由 outguard 提供）
    reasons: list[RouteReason] = Field(default_factory=list)


class ApiError(BaseModel):
    """错误响应信封（顶层只有一个 ``error`` 键）。"""

    model_config = ConfigDict(extra="forbid")

    error: ErrorBody

    @classmethod
    def content_blocked(cls, message: str, reasons: list[RouteReason] | None = None) -> ApiError:
        """构造 BLOCK 拦截响应（code=content_blocked）。"""
        return cls(error=ErrorBody(code=CODE_CONTENT_BLOCKED, message=message,
                                   reasons=reasons or []))
