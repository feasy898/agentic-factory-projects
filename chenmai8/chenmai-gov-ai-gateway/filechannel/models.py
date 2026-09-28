"""契约模型：文件体检报告 FileReport（开发指令 §5.5，冻结——字段只增不改名）。

filechannel 的 inspect 端点输出 / 导出端点经 ``X-Report-Id`` 关联本报告。
风险分级口径（§5.5）：
- HIGH：含 SENSITIVE_ATTR 或批量结构化号码（批量 ID）；
- MID：含结构化 PII；
- LOW / NONE：其余。
导出验收口径（铁律）：对导出物重新走「解析+检测」，seeded PII 命中数必须为 0。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from recognizers.models import Finding

#: 文件种类（scan_pdf = 扫描件，走 OCR 路径）
FileKind = Literal["pdf", "docx", "xlsx", "scan_pdf"]

#: 风险分级
RiskLevel = Literal["HIGH", "MID", "LOW", "NONE"]


class FileFinding(BaseModel):
    """带物理定位的文件内命中。

    ``page`` 为 1 起始页码；``bbox`` 为 PDF 文本坐标 ``[x0, y0, x1, y1]``
    （render 坐标系：原点左上、y 轴向下、单位 pt；仅 pdf/scan_pdf 提供）；
    ``location`` 为增补字段（§6 M6 要求单元格/段落定位）：
    xlsx 形如 ``Sheet1!B3``，docx 形如 ``para:5`` / ``table:2:r1:c3``。
    """

    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1)
    bbox: tuple[float, float, float, float] | None = None
    location: str | None = None
    finding: Finding


class FileReport(BaseModel):
    """体检报告（§5.5 JSON 形状一字不差）。"""

    model_config = ConfigDict(extra="forbid")

    file_id: str = ""                         # file_...
    filename: str = ""
    sha256: str = ""
    kind: FileKind = "pdf"
    pages: int = Field(default=0, ge=0)
    findings: list[FileFinding] = Field(default_factory=list)
    risk_level: RiskLevel = "NONE"
    summary: dict[str, int] = Field(default_factory=dict)  # {"ID_CARD": 12, "PERSON": 30}
