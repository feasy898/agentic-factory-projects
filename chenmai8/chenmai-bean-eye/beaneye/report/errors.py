"""M10 质量护照：异常类型。"""

from __future__ import annotations

__all__ = ["ReportError"]


class ReportError(RuntimeError):
    """护照构建失败（语言未知 / i18n 缺键 / QR 负载非法 / 素材不可用等）。"""
