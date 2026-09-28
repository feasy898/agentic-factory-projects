"""彻底删除式导出（M6）：命中内容物理删除后重写文件，杜绝"隐藏/白字覆盖"假清理。

口径（开发指令 §6 M6，验收铁律：**对导出物重新走「解析+检测」，seeded PII
命中数必须为 0**）：

- docx：删除命中 span 所覆盖的 run 文本片段（正文/表格/页眉页脚；run 边界
  跨越命中时逐 run 切除，非替换非隐藏）；
- xlsx：命中单元格**删值**（值+批注清空）；命中落在**隐藏列/隐藏行**时整列/整行
  删除（隐藏列里的数据正是"假删除"重灾区，§6：删列而非隐藏）；导出前解除全部
  残余隐藏行列（不留任何以隐藏形态存在的数据面）；
- pdf：按体检报告的命中框走 :mod:`filechannel.pdf_engine` 涂删重写。

删除面 = 非白名单命中（whitelisted=true 的公开文号等照常保留）；白名单命中不
参与脱敏（§5.1），也就不参与删除。
"""
from __future__ import annotations

import io
from typing import Any

from common.logs import get_logger
from filechannel.errors import DocumentParseError
from filechannel.models import FileReport
from recognizers.rule.detect import detect

log = get_logger(__name__)


class ExportBlockedError(RuntimeError):
    """导出被阻止：存在无法物理删除的命中（宁可阻止不可漏删）。"""


def _scrub_targets(text: str) -> list[tuple[int, int]]:
    """一段文本内需删除的 span（非白名单命中；按 start 降序便于从尾向前删）。"""
    spans = [(f.start, f.end) for f in detect(text) if not f.whitelisted]
    return sorted(set(spans), key=lambda s: s[0], reverse=True)


# ── docx：run 级文本切除 ─────────────────────────────────────────────


def _delete_span_in_paragraph(para: Any, start: int, end: int) -> None:
    """删除段落文本 ``[start, end)`` 覆盖的 run 片段（run 累积偏移对齐段落全文）。"""
    pos = 0
    for run in para.runs:
        run_len = len(run.text)
        a, b = pos, pos + run_len
        lo, hi = max(a, start), min(b, end)
        if lo < hi:
            run.text = run.text[:lo - a] + run.text[hi - a:]
        pos = b


def _scrub_paragraph(para: Any) -> int:
    hits = _scrub_targets(para.text)
    for start, end in hits:
        _delete_span_in_paragraph(para, start, end)
    return len(hits)


def _iter_docx_paragraphs(doc: Any):
    """正文段落 + 表格单元格段落 + 页眉/页脚段落（与 parse_docx 同面）。"""
    yield from doc.paragraphs
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from cell.paragraphs
    for section in doc.sections:
        for part in (section.header, section.footer):
            yield from part.paragraphs


def sanitize_docx(data: bytes) -> bytes:
    """docx 删除式导出：命中 run 片段物理切除后重存。"""
    from docx import Document  # noqa: PLC0415 — 与解析同源的三方依赖

    try:
        doc = Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise DocumentParseError(f"docx 解析失败: {exc}") from exc
    removed = sum(_scrub_paragraph(p) for p in _iter_docx_paragraphs(doc))
    buf = io.BytesIO()
    doc.save(buf)
    log.info("filechannel.sanitize.docx", extra={"removed": removed, "bytes_in": len(data)})
    return buf.getvalue()


# ── xlsx：命中删值 + 隐藏列/行整列删 + 残余隐藏全解除 ────────────────


def sanitize_xlsx(data: bytes) -> bytes:
    """xlsx 删除式导出：命中单元格删值；隐藏列/行含命中即整列/整行删除。"""
    from openpyxl import load_workbook  # noqa: PLC0415
    from openpyxl.utils import column_index_from_string  # noqa: PLC0415

    try:
        wb = load_workbook(io.BytesIO(data), data_only=False)
    except Exception as exc:  # noqa: BLE001
        raise DocumentParseError(f"xlsx 解析失败: {exc}") from exc

    removed_cells = 0
    for ws in wb.worksheets:
        hidden_cols: set[int] = set()
        for dim in ws.column_dimensions.values():
            if dim.hidden:
                hidden_cols.add(column_index_from_string(str(dim.index)))
        hidden_rows: set[int] = set()
        for idx, dim in ws.row_dimensions.items():
            if dim.hidden:
                hidden_rows.add(int(idx))

        drop_cols: set[int] = set()
        drop_rows: set[int] = set()
        for row in ws.iter_rows():
            for cell in row:
                texts = [str(cell.value)] if cell.value is not None else []
                if cell.comment is not None and cell.comment.text:
                    texts.append(cell.comment.text)
                if not any(_scrub_targets(t) for t in texts):
                    continue
                removed_cells += 1
                if cell.column in hidden_cols:
                    drop_cols.add(cell.column)
                elif cell.row in hidden_rows:
                    drop_rows.add(cell.row)
                # 删值 + 删批注（命中即物理清空，非隐藏非白字）
                cell.value = None
                cell.comment = None

        # 隐藏列/行里的命中 → 整列/整行删除（列号降序删，避免索引位移）
        for col in sorted(drop_cols, reverse=True):
            ws.delete_cols(col, 1)
        for row_idx in sorted(drop_rows, reverse=True):
            ws.delete_rows(row_idx, 1)

        # 残余隐藏行列全部解除隐藏（不留任何隐藏形态的数据面）
        for dim in ws.column_dimensions.values():
            dim.hidden = False
        for dim in ws.row_dimensions.values():
            dim.hidden = False

    buf = io.BytesIO()
    wb.save(buf)
    log.info("filechannel.sanitize.xlsx", extra={"removed_cells": removed_cells})
    return buf.getvalue()


# ── pdf：报告框 → 引擎涂删重写 ───────────────────────────────────────


def sanitize_pdf(data: bytes, report: FileReport, engine_module: str) -> bytes:
    """pdf 涂删重写：按体检报告命中框（render 坐标）走引擎彻底删除。

    存在「非白名单命中但无定位框」时报 :class:`ExportBlockedError`——导出宁可
    阻止不可漏删（定位失败的常见原因：文本被切成检索不到整串的碎片）。
    """
    from filechannel.pdf_engine import PdfEngine  # noqa: PLC0415

    page_boxes: dict[int, list[tuple[float, float, float, float]]] = {}
    unlocated = 0
    for ff in report.findings:
        if ff.finding.whitelisted:
            continue
        if ff.bbox is None:
            unlocated += 1
            continue
        # FileReport.page 为 1 起始页码 → 引擎页索引 0 起始
        page_boxes.setdefault(ff.page - 1, []).append(ff.bbox)
    if unlocated:
        raise ExportBlockedError(f"{unlocated} 处命中无法物理定位，导出已阻止（宁可阻止不可漏删）")
    if not page_boxes:
        return data
    engine = PdfEngine(engine_module)
    return engine.redact(data, page_boxes)
