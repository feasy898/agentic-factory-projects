"""文件体检/导出服务（T3.3 门面，T3.2 收敛导出链）：体检委托 T3.1 权威管线，
导出走删除式重写 + **导出物零残留硬闸**。

- 体检：委托 :func:`filechannel.inspect.inspect_bytes`（T3.1 文本层权威实现：
  docx 全位面 / xlsx 隐藏面+公式缓存值+批注 / pdf 坐标级 charbox bbox +
  scan_pdf 如实降级）；本门面只加**报告登记表**（内存有界 LRU，file_id →
  FileReport，供 X-Report-Id 关联查询）；
- 导出：``mode=sanitize`` → 同源体检 → 按种类删除式重写 + **re-ingest 复核**
  （:mod:`filechannel.sanitize`：docx 删 run 片段 / xlsx 命中删值+隐藏列整列删+
  残余隐藏全解除 / pdf 引擎链涂删重写——逐引擎复核不净自动回退，见
  :mod:`filechannel.pdf_engine` / scan_pdf 重打码渲染版=渲染→黑框覆盖→整页
  重栅格化，零残留复核即再 OCR，T4.1）；X-Report-Id = **导出前体检报告** id，
  ``method`` = 实际生效的导出方式（响应头 ``X-Sanitize-Method`` 如实标注）；
- 错误语义（filechannel.errors 文档口径，HTTP 层映射在 gateway/app.py）：
  FileTooLargeError→413、UnsupportedFileType→400、DocumentParseError→422、
  ExportBlockedError→422（导出特有：命中无法定位/零残留复核不净，宁可阻止
  不可漏删）。

端点鉴权面（与 /internal/* 的差异，审查口径）：/v1/files/* 面向公开前体检的
操作者与演示页（M9 不做登录），报告中的 raw 是**上传者自带文件**的内容回显，
不构成服务端持有信息的泄露，故不做部门 Key 鉴权；生产部署仍应置于管理面/
内网（README 安全注记同 /internal/*）。
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from common.config import AppConfig
from common.logs import get_logger
from filechannel.errors import UnsupportedFileType
from filechannel.inspect import inspect_bytes
from filechannel.models import FileReport
from filechannel.pdf_engine import PdfRedactionEngine, load_engine_chain
from filechannel.sanitize import (  # noqa: F401 — ExportBlockedError 门面再导出（gateway 错误映射用）
    ExportBlockedError,
    sanitize_docx_verified,
    sanitize_pdf,
    sanitize_scan_pdf,
    sanitize_xlsx_verified,
)

log = get_logger(__name__)

#: 报告登记表容量（内存有界；演示规模足够）
REPORT_REGISTRY_CAP = 128

#: 内容类型（导出响应 Content-Type；scan_pdf 同 pdf 容器）
CONTENT_TYPES: dict[str, str] = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
    "scan_pdf": "application/pdf",
}

class BadModeError(ValueError):
    """导出 mode 不受支持（当前仅 sanitize）。"""


@dataclass
class SanitizeResult:
    """导出结果：清理后字节流 + 导出前体检报告 + 响应面元数据。"""

    data: bytes
    report: FileReport
    content_type: str
    download_name: str
    method: str = ""  # 实际生效的导出方式（X-Sanitize-Method 如实标注）


class FileService:
    """体检/导出门面（gateway 持有；evals 可独立构造）。"""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self._pdf_engine_module = str(getattr(cfg, "pdf_engine_module", "") or "")
        # 引擎链惰性加载（涂删主引擎 → 内容流手术 → 栅格兜底；坐标见
        # config/app.yaml pdf_engine_module 与 config/filechannel.yaml）
        self._pdf_engines: list[PdfRedactionEngine] = load_engine_chain(
            self._pdf_engine_module)
        self._reports: OrderedDict[str, FileReport] = OrderedDict()

    # ── 体检（T3.1 权威管线 + 登记表）─────────────────────────────────

    def inspect_bytes(self, filename: str, data: bytes) -> FileReport:
        """上传字节流 → 体检报告（§5.5）；大小/种类/解析异常由 T3.1 语义层抛出。"""
        report = inspect_bytes(filename, data)
        self._remember(report)
        log.info("filechannel.inspected", extra={
            "file_id": report.file_id, "kind": report.kind,
            "findings": len(report.findings), "risk": report.risk_level,
        })
        return report

    # ── 导出（删除式重写 + 零残留硬闸）───────────────────────────────

    def export_bytes(self, filename: str, data: bytes, mode: str) -> SanitizeResult:
        """mode=sanitize：体检 → 删除式重写 → 导出物 re-ingest 零残留复核。"""
        if mode != "sanitize":
            raise BadModeError(f"不支持的导出 mode: {mode}（当前仅 sanitize）")
        report = self.inspect_bytes(filename, data)
        if report.kind == "docx":
            out, method = sanitize_docx_verified(data, filename)
        elif report.kind == "xlsx":
            out, method = sanitize_xlsx_verified(data, filename)
        elif report.kind == "scan_pdf":
            # 扫描件：无文本层可删 → 重打码渲染版（渲染→黑框覆盖→整页重栅格化），
            # 零残留复核=再 OCR（T4.1）；method 如实标注 scan-raster-redaction
            out, method = sanitize_scan_pdf(data, filename, report, self._pdf_engines)
        elif report.kind == "pdf":
            out, method = sanitize_pdf(data, filename, report, self._pdf_engines)
        else:
            raise UnsupportedFileType(f"暂不支持导出种类: {report.kind}")
        return SanitizeResult(
            data=out, report=report,
            content_type=CONTENT_TYPES.get(report.kind, "application/octet-stream"),
            download_name=f"sanitized_{filename}" if filename else "sanitized_file",
            method=method,
        )

    # ── 报告登记表 ───────────────────────────────────────────────────

    def _remember(self, report: FileReport) -> None:
        self._reports[report.file_id] = report
        while len(self._reports) > REPORT_REGISTRY_CAP:
            self._reports.popitem(last=False)

    def get_report(self, file_id: str) -> FileReport | None:
        return self._reports.get(file_id)
