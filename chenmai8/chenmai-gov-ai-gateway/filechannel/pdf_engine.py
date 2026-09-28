"""PDF 清理引擎适配层（M6 导出引擎抽象，开发指令 §8.6）。

真实清理库模块名只允许写在 ``config/app.yaml pdf_engine_module``（铁律 E：公开
仓库源码零上游名），本模块经 importlib 动态加载并封装为统一适配面——**三能力**：

1. 文本抽取：``page_text(doc, page_index) -> str``（逐页全文，体检检测输入）；
2. 串检索定位：``search(doc, page_index, needle) -> [box]``（Finding → 页面坐标框，
   render 坐标系：原点左上、y 轴向下、单位 pt；同页多处命中合并为一个外接框，
   宁可多涂不可漏涂）；
3. 涂删重写：``redact(data, page_boxes) -> bytes``（按框彻底删除文字+重写文件，
   导出物重抽取即零残留；框空缺的页保持原样）。

第二引擎（内容流手术式删除，§11 风险 2 的许可合规备选）由导出引擎任务按同一
适配面补全；配置切换，调用方无感。
"""
from __future__ import annotations

import importlib
from typing import Any, Protocol

from common.logs import get_logger
from filechannel.errors import DocumentParseError

log = get_logger(__name__)

#: 涂删框外扩（pt）：字符级紧贴框易留笔画残边，四周各扩 1pt
REDACT_BOX_PAD_PT = 1.0

#: render 坐标系四元组 (x0, y0, x1, y1)，原点左上、y 向下、单位 pt
Box = tuple[float, float, float, float]


class PdfEngineProtocol(Protocol):
    """引擎适配面（第二引擎实现时对齐此协议）。"""

    def open(self, data: bytes) -> Any: ...
    def close(self, doc: Any) -> None: ...
    def page_count(self, doc: Any) -> int: ...
    def page_text(self, doc: Any, page_index: int) -> str: ...
    def search(self, doc: Any, page_index: int, needle: str) -> list[Box]: ...
    def redact(self, data: bytes, page_boxes: dict[int, list[Box]]) -> bytes: ...


class PdfEngine:
    """按配置模块名加载的 PDF 清理引擎（当前适配面 = 配置库原生三能力）。"""

    def __init__(self, module_name: str) -> None:
        if not module_name:
            raise ValueError("pdf 清理引擎未配置（config app.yaml pdf_engine_module）")
        self._module_name = module_name
        try:
            self._mod = importlib.import_module(module_name)
        except ImportError as exc:
            raise DocumentParseError(f"pdf 清理引擎模块不可用: {module_name}（{exc}）") from exc

    # ── 能力 1：打开/关闭/抽取 ────────────────────────────────────────

    def open(self, data: bytes) -> Any:
        try:
            return self._mod.open(stream=data, filetype="pdf")
        except Exception as exc:  # noqa: BLE001 — 库级打开失败归一为解析错误
            raise DocumentParseError(f"pdf 打开失败: {exc}") from exc

    def close(self, doc: Any) -> None:
        try:
            doc.close()
        except Exception:  # noqa: BLE001 — 关闭失败不影响主流程
            log.warning("pdf_engine.close.failed", extra={"module": self._module_name})

    def page_count(self, doc: Any) -> int:
        return len(doc)

    def page_text(self, doc: Any, page_index: int) -> str:
        text = doc[page_index].get_text("text")
        return text if isinstance(text, str) else ""

    # ── 能力 2：串检索定位（render 坐标，同页多处合并外接框）──────────

    def search(self, doc: Any, page_index: int, needle: str) -> list[Box]:
        if not needle or not needle.strip():
            return []
        rects = doc[page_index].search_for(needle) or []
        return [(float(r.x0), float(r.y0), float(r.x1), float(r.y1)) for r in rects]

    # ── 能力 3：涂删重写（彻底删除框内文字，杜绝"隐藏/覆盖层"假清理）──

    def redact(self, data: bytes, page_boxes: dict[int, list[Box]]) -> bytes:
        """``page_boxes`` 键为 **0 起始页索引**（调用方负责从 1 起始页码换算）。"""
        if not page_boxes:
            return data
        doc = self.open(data)
        try:
            for page_index, boxes in sorted(page_boxes.items()):
                page = doc[page_index]
                for box in boxes:
                    x0, y0, x1, y1 = box
                    rect = self._mod.Rect(x0 - REDACT_BOX_PAD_PT, y0 - REDACT_BOX_PAD_PT,
                                          x1 + REDACT_BOX_PAD_PT, y1 + REDACT_BOX_PAD_PT)
                    page.add_redact_annot(rect)
                page.apply_redactions()
            return doc.tobytes(garbage=3, deflate=True)
        finally:
            self.close(doc)


def union_boxes(boxes: list[Box]) -> Box | None:
    """多个命中框合并为一个外接框（空表返回 None）。"""
    if not boxes:
        return None
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    return (x0, y0, x1, y1)


def image_bytes_to_pdf_pages(png_pages: list[bytes]) -> bytes:
    """占位：重栅格化打码版（scan_pdf 导出）由 OCR 任务（T4.1）接入。"""
    raise NotImplementedError("scan_pdf 重打码渲染版导出由 T4.1（OCR 路径）接入")
