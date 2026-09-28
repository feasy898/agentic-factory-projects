"""文件体检/导出服务（T3.3 门面）：体检委托 T3.1 权威管线，导出走删除式重写。

- 体检：委托 :func:`filechannel.inspect.inspect_bytes`（T3.1 文本层权威实现：
  docx 全位面 / xlsx 隐藏面+公式缓存值+批注 / pdf 坐标级 charbox bbox +
  scan_pdf 如实降级）；本门面只加**报告登记表**（内存有界 LRU，file_id →
  FileReport，供 X-Report-Id 关联查询）；
- 导出：``mode=sanitize`` → 同源体检 → 按种类删除式重写
  （:mod:`filechannel.sanitize`：docx 删 run 片段 / xlsx 命中删值+隐藏列整列删 /
  pdf 引擎涂删重写）；X-Report-Id = **导出前体检报告** id；
- 错误语义（filechannel.errors 文档口径，HTTP 层映射在 gateway/app.py）：
  FileTooLargeError→413、UnsupportedFileType→400、DocumentParseError→422、
  ExportBlockedError→422（导出特有：命中无法物理定位，宁可阻止不可漏删）。

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
from filechannel.sanitize import ExportBlockedError, sanitize_docx, sanitize_pdf, sanitize_xlsx

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


class FileService:
    """体检/导出门面（gateway 持有；evals 可独立构造）。"""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self._pdf_engine_module = str(getattr(cfg, "pdf_engine_module", "") or "")
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

    # ── 导出（删除式重写）────────────────────────────────────────────

    def export_bytes(self, filename: str, data: bytes, mode: str) -> SanitizeResult:
        """mode=sanitize：体检 → 删除式重写 → 清理后文件（X-Report-Id = 导出前体检）。"""
        if mode != "sanitize":
            raise BadModeError(f"不支持的导出 mode: {mode}（当前仅 sanitize）")
        report = self.inspect_bytes(filename, data)
        if report.kind == "docx":
            out = sanitize_docx(data)
        elif report.kind == "xlsx":
            out = sanitize_xlsx(data)
        elif report.kind in ("pdf", "scan_pdf"):
            # scan_pdf（零文本层）D4 前如实降级：文本层零命中 → 无框可涂 → 原样返回
            if not self._pdf_engine_module:
                raise ExportBlockedError("pdf 清理引擎未配置（config app.yaml pdf_engine_module）")
            out = sanitize_pdf(data, report, self._pdf_engine_module)
        else:
            raise UnsupportedFileType(f"暂不支持导出种类: {report.kind}")
        return SanitizeResult(
            data=out, report=report,
            content_type=CONTENT_TYPES.get(report.kind, "application/octet-stream"),
            download_name=f"sanitized_{filename}" if filename else "sanitized_file",
        )

    # ── 报告登记表 ───────────────────────────────────────────────────

    def _remember(self, report: FileReport) -> None:
        self._reports[report.file_id] = report
        while len(self._reports) > REPORT_REGISTRY_CAP:
            self._reports.popitem(last=False)

    def get_report(self, file_id: str) -> FileReport | None:
        return self._reports.get(file_id)
