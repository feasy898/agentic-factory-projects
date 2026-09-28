"""彻底删除式导出（M6 · T3.2）：命中内容物理删除后重写文件，杜绝"隐藏/白字覆盖"假清理。

口径（开发指令 §6 M6，验收铁律：**对导出物重新走「解析+检测」，seeded PII
命中数必须为 0**；本模块把该口径实现为导出管线内的硬闸，而非仅验收断言）：

- docx：删除命中 span 所覆盖的 run 文本片段（正文/表格（含嵌套）/页眉/页脚
  （含其中表格）；run 边界跨越命中时逐 run 切除，非替换非隐藏）；
- xlsx：命中单元格**删值**（值+批注清空）；命中落在**隐藏列/隐藏行**时整列/
  整行删除（隐藏列里的数据正是"假删除"重灾区，§6：删列而非隐藏）；导出前
  解除全部残余隐藏行列与隐藏工作表（不留任何以隐藏形态存在的数据面）；
- pdf：按体检报告命中框/命中值走 :mod:`filechannel/pdf_engine` 引擎链——
  逐引擎「涂删 → 导出物 re-ingest → detect 复核」，复核不净或引擎不适用即
  **自动回退下一引擎**，链尽仍不净报 :class:`ExportBlockedError`。

零残留硬闸（export→re-ingest→detect 零命中断言）：``*_verified`` 三个入口对
清理产物就地重跑 :func:`filechannel.inspect.inspect_bytes`（与体检同一条权威
管线），存在**非白名单**残留命中即继续清理/回退，收敛失败报
:class:`ExportBlockedError`——导出宁可阻止不可漏删。白名单命中（公开文号等）
照常保留（§5.1：白名单不参与脱敏，也就不参与删除）。
"""
from __future__ import annotations

import io
from typing import Any

from common.logs import get_logger
from filechannel.errors import DocumentParseError
from filechannel.models import FileReport
from recognizers.rule.detect import detect

log = get_logger(__name__)

#: 验证收敛轮数上限（删除 span 后相邻文本拼接可能产生新命中，二轮内必收敛；
#: 更多是异常形态，报 ExportBlockedError 而不是无限循环）
SANITIZE_MAX_PASSES = 3

#: 导出方式标注（SanitizeResult.method / X-Sanitize-Method）
METHOD_DOCX = "docx-run-delete"
METHOD_XLSX = "xlsx-cell-column-delete"
METHOD_PDF_UNTOUCHED = "pdf-noop"


class ExportBlockedError(RuntimeError):
    """导出被阻止：存在无法物理删除的命中（宁可阻止不可漏删）。"""


def _scrub_targets(text: str) -> list[tuple[int, int]]:
    """一段文本内需删除的 span（非白名单命中；按 start 降序便于从尾向前删）。"""
    spans = [(f.start, f.end) for f in detect(text) if not f.whitelisted]
    return sorted(set(spans), key=lambda s: s[0], reverse=True)


def _dirty_findings(report: FileReport) -> list[Any]:
    """报告中的非白名单命中（零残留硬闸的判定分母）。"""
    return [ff for ff in report.findings if not ff.finding.whitelisted]


def _verified(fn, data: bytes, filename: str, method: str) -> tuple[bytes, str]:
    """删除 → re-ingest → detect 复核的收敛循环（docx/xlsx 共用）。"""
    out = fn(data)
    for _ in range(SANITIZE_MAX_PASSES - 1):
        residue = _dirty_findings(_reinspect(filename, out))
        if not residue:
            return out, method
        log.warning("filechannel.sanitize.residue_retry", extra={
            "kind": method, "residue": len(residue)})
        out = fn(out)  # 残留继续删（删除拼接可能产生新词面，二轮内收敛）
    residue = _dirty_findings(_reinspect(filename, out))
    if residue:
        raise ExportBlockedError(
            f"{method} 导出复核仍有 {len(residue)} 处非白名单命中，导出已阻止"
            "（宁可阻止不可漏删）")
    return out, method


def _reinspect(filename: str, data: bytes) -> FileReport:
    """导出物 re-ingest：与体检同一条权威管线（parse→detect→FileReport）。"""
    from filechannel.inspect import inspect_bytes  # noqa: PLC0415 — 延迟避免环导入

    return inspect_bytes(filename, data)


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


def _walk_docx_table(table: Any):
    """表格 → 单元格段落（合并单元格去重 + 嵌套表递归，与 parse_docx 同面）。

    去重按底层 XML 元素身份，dict 值**持有元素强引用**——防 lxml 代理被 GC 后
    ``id()`` 复用导致不同单元格被误判同一（与 parse_docx 同一陷阱，实测验证）。
    """
    seen: dict[int, Any] = {}
    for row in table.rows:
        for cell in row.cells:
            tc = cell._tc  # noqa: SLF001 — 元素身份（强引用持有）
            key = id(tc)
            if key in seen:
                continue
            seen[key] = tc
            yield from cell.paragraphs
            yield from _walk_nested(cell.tables)


def _walk_nested(tables: Any):
    for nested in tables:
        yield from _walk_docx_table(nested)


def _iter_docx_paragraphs(doc: Any):
    """正文段落 + 表格（嵌套递归）+ 页眉/页脚段落与其中的表格（与 parse_docx 同面）。"""
    yield from doc.paragraphs
    for table in doc.tables:
        yield from _walk_docx_table(table)
    for section in doc.sections:
        for part in (section.header, section.footer):
            yield from part.paragraphs
            for table in part.tables:
                yield from _walk_docx_table(table)


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


def sanitize_docx_verified(data: bytes, filename: str) -> tuple[bytes, str]:
    """docx 删除式导出 + 零残留硬闸（返回 (产物字节, 导出方式标注)）。"""
    return _verified(sanitize_docx, data, filename, METHOD_DOCX)


# ── xlsx：命中删值 + 隐藏列/行整列删 + 残余隐藏全解除 ────────────────


def sanitize_xlsx(data: bytes) -> bytes:
    """xlsx 删除式导出：命中单元格删值；隐藏列/行含命中即整列/整行删除。"""
    from openpyxl import load_workbook  # noqa: PLC0415

    try:
        wb = load_workbook(io.BytesIO(data), data_only=False)
    except Exception as exc:  # noqa: BLE001
        raise DocumentParseError(f"xlsx 解析失败: {exc}") from exc

    removed_cells = 0
    for ws in wb.worksheets:
        hidden_cols: set[int] = set()
        for dim in ws.column_dimensions.values():
            if dim.hidden:
                hidden_cols.add(dim.index if isinstance(dim.index, int)
                                else _col_letter_to_index(str(dim.index)))
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

        # 隐藏列/行里的命中 → 整列/整行删除（列/行号降序删，避免索引位移）
        for col in sorted(drop_cols, reverse=True):
            ws.delete_cols(col, 1)
        for row_idx in sorted(drop_rows, reverse=True):
            ws.delete_rows(row_idx, 1)

        # 残余隐藏行列/隐藏工作表全部解除（不留任何以隐藏形态存在的数据面）
        for dim in ws.column_dimensions.values():
            dim.hidden = False
        for dim in ws.row_dimensions.values():
            dim.hidden = False
    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            ws.sheet_state = "visible"

    buf = io.BytesIO()
    wb.save(buf)
    log.info("filechannel.sanitize.xlsx", extra={"removed_cells": removed_cells})
    return buf.getvalue()


def _col_letter_to_index(letter: str) -> int:
    """列标（A/AA/…）→ 1 起始列号（openpyxl utils 的无 import 等价实现）。"""
    total = 0
    for ch in letter.upper():
        if not "A" <= ch <= "Z":
            raise ValueError(f"非法列标: {letter}")
        total = total * 26 + (ord(ch) - ord("A") + 1)
    return total


def sanitize_xlsx_verified(data: bytes, filename: str) -> tuple[bytes, str]:
    """xlsx 删除式导出 + 零残留硬闸（返回 (产物字节, 导出方式标注)）。"""
    return _verified(sanitize_xlsx, data, filename, METHOD_XLSX)


# ── pdf：报告框/命中值 → 引擎链逐引擎涂删 + 复核回退 ─────────────────


def _pdf_targets(report: FileReport) -> tuple[dict[int, list[tuple[float, float, float, float]]], set[str], int]:
    """体检报告 → (0 起始页索引→命中框, 命中值串集, 无法物理定位的命中数)。"""
    page_boxes: dict[int, list[tuple[float, float, float, float]]] = {}
    needles: set[str] = set()
    unlocated = 0
    for ff in report.findings:
        if ff.finding.whitelisted:
            continue
        # FileReport.page 为 1 起始页码 → 引擎页索引 0 起始
        if ff.bbox is None:
            unlocated += 1
            continue
        page_boxes.setdefault(ff.page - 1, []).append(ff.bbox)
        for value in (ff.finding.raw, ff.finding.normalized):
            if value and value.strip():
                needles.add(value)
    return page_boxes, needles, unlocated


def sanitize_pdf(data: bytes, filename: str, report: FileReport,
                 engines: list[Any]) -> tuple[bytes, str]:
    """pdf 删除式导出：引擎链逐引擎「涂删 → re-ingest 复核 → 不净回退」。

    - 存在非白名单命中但**无定位框** → :class:`ExportBlockedError`（宁可阻止
      不可漏删；scan_pdf OCR 坐标 D4 前不会出现此形态——文本层零命中无框可涂）；
    - 零命中 → 原样返回（如实标注 ``pdf-noop``）；
    - 每个引擎产物就地重跑体检管线复核，非白名单零命中才被采信；引擎不适用
      （:class:`EngineNotApplicable`）或复核不净 → 换下一引擎；链尽 →
      :class:`ExportBlockedError`。
    """
    from filechannel.pdf_engine import EngineNotApplicable  # noqa: PLC0415

    page_boxes, needles, unlocated = _pdf_targets(report)
    if unlocated:
        raise ExportBlockedError(f"{unlocated} 处命中无法物理定位，导出已阻止"
                                 "（宁可阻止不可漏删）")
    if not page_boxes or not engines:
        if not page_boxes:
            return data, METHOD_PDF_UNTOUCHED
        raise ExportBlockedError("pdf 清理引擎不可用（config app.yaml "
                                 "pdf_engine_module / config filechannel.yaml 引擎坐标）")
    failures: list[str] = []
    for engine in engines:
        try:
            candidate = engine.redact(data, page_boxes, needles)
        except EngineNotApplicable as exc:
            failures.append(f"{engine.name}: {exc}")
            log.warning("filechannel.sanitize.pdf_engine_skip",
                        extra={"engine": engine.name, "reason": str(exc)[:120]})
            continue
        residue = _dirty_findings(_reinspect(filename, candidate))
        if not residue:
            log.info("filechannel.sanitize.pdf_done",
                     extra={"engine": engine.name, "bytes_out": len(candidate)})
            return candidate, engine.name
        failures.append(f"{engine.name}: 导出复核仍有 {len(residue)} 处命中")
    raise ExportBlockedError("pdf 引擎链全部未通过零残留复核（"
                             + "；".join(failures) + "）——导出已阻止（宁可阻止不可漏删）")
