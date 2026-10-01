"""扫描件 OCR 路线（M6 · T4.1）：页面位图 → OCR → 重建可检测文本 + 命中框。

路线（开发指令 §6 M6「scan_pdf：渲染 300dpi → OCR 引擎」；真实库名只进
``config/filechannel.yaml``，铁律 E：源码经 importlib 动态加载、零库名）：

1. 页面渲染：复用 ``pdf_text_reader.module`` 读取库（与文本层同源），按
   ``ocr_engine.render_dpi``（默认 300）逐页渲染位图；
2. OCR 引擎（``ocr_engine.module`` + ``ocr_engine.factory``）：**纯 CPU 推理**——
   该引擎 API 无 ``enable_mkldnn`` 一类开关，等价的强制 = ``ocr_engine.params``
   显式关闭全部硬件加速执行提供器（cuda/dml/cann/coreml 全 false），会话只挂
   CPU 执行器；
3. 重建：逐条识别行（文本 + 像素坐标框）换算 pt（**render 坐标系**：原点左上、
   y 向下，契约口径），按页序以换行拼接为可检测文本并记录行首偏移——体检命中
   span 据此映射回 OCR 框（:class:`OcrTextLayer.union`：行内按字符渲染宽度加权
   插值，全角 1.0 / 半角 0.5；跨行 span 逐行取子框再并集）。

容差口径（如实报告，不装满）：OCR 为概率识别，行内数字可能整行误读或被检测
截断——召回与零残留验收均以「重建文本上的检测命中」为准，识别容差在 eval
报告中原样呈现（§6 M6「OCR 数字识别容差如实报告」）。
"""
from __future__ import annotations

import importlib
import io
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import yaml

from common.logs import get_logger
from filechannel.errors import DocumentParseError
from filechannel.parsers import FILECHANNEL_CONFIG_PATH, BBox, load_pdf_reader

log = get_logger(__name__)

#: 全角/CJK 字符的近似渲染宽度权重（行内 x 轴加权插值用）
CHAR_WEIGHT_FULL = 1.0
#: 半角（ASCII）字符的近似渲染宽度权重
CHAR_WEIGHT_HALF = 0.5


def char_weight(ch: str) -> float:
    """单字符近似渲染宽度：CJK/全角区（≥ U+2E80）记 1.0，其余（ASCII 等）记 0.5。"""
    return CHAR_WEIGHT_FULL if ord(ch) >= 0x2E80 else CHAR_WEIGHT_HALF


@dataclass(frozen=True)
class OcrLine:
    """一条 OCR 识别行：页文本中的起始偏移 + 文本 + render 系框（pt）。"""

    start: int
    text: str
    box: BBox


class OcrTextLayer:
    """逐页识别行表：span（页文本切片）→ render 系 bbox 并集。

    与文本层 :class:`filechannel.parsers.PdfTextLayer` 同一 ``union`` 契约面
    （1 起始页码 + Python 切片语义 span → render 系 bbox），inspect 层零分支切换。
    """

    def __init__(self, page_lines: list[list[OcrLine]]) -> None:
        self.pages = page_lines

    def page_text(self, page_index: int) -> str:
        """0 起始页索引 → 该页重建文本（行间以换行拼接，与行首偏移一致）。"""
        return "\n".join(line.text for line in self.pages[page_index])

    def union(self, page: int, start: int, end: int) -> BBox | None:
        """1 起始页码 + 页内 span → render 系 bbox（跨行逐行取子框再并集）。"""
        idx = page - 1
        if not (0 <= idx < len(self.pages)) or start >= end:
            return None
        subs: list[BBox] = []
        for line in self.pages[idx]:
            lo = max(start, line.start)
            hi = min(end, line.start + len(line.text))
            if lo >= hi:
                continue
            weights = [char_weight(ch) for ch in line.text]
            total = sum(weights) or 1.0
            x0, y0, x1, y1 = line.box
            fx0 = sum(weights[: lo - line.start]) / total
            fx1 = sum(weights[: hi - line.start]) / total
            sx0 = x0 + (x1 - x0) * fx0
            sx1 = x0 + (x1 - x0) * fx1
            subs.append((min(sx0, sx1), y0, max(sx0, sx1), y1))
        if not subs:
            return None
        return (min(b[0] for b in subs), min(b[1] for b in subs),
                max(b[2] for b in subs), max(b[3] for b in subs))


@lru_cache(maxsize=1)
def _ocr_config() -> dict[str, Any]:
    """config/filechannel.yaml 的 ``ocr_engine`` 段（缺失返回空 dict）。"""
    cfg = yaml.safe_load(FILECHANNEL_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    return cfg.get("ocr_engine") or {}


@lru_cache(maxsize=1)
def load_ocr_engine() -> Any:
    """按配置装载 OCR 引擎（惰性单例；缺配置/不可导入报解析语义异常）。

    引擎坐标（包名/工厂类名/纯 CPU 强制参数）全部来自
    ``config/filechannel.yaml``；体检链路对文本层 pdf 零开销（不触发本函数）。
    """
    group = _ocr_config()
    module_name = str(group.get("module", "")).strip()
    factory_name = str(group.get("factory", "")).strip()
    if not module_name or not factory_name:
        raise DocumentParseError(
            f"config missing ocr_engine.module/factory: {FILECHANNEL_CONFIG_PATH}")
    try:
        mod = importlib.import_module(module_name)
        factory = getattr(mod, factory_name)
    except (ImportError, AttributeError) as exc:
        raise DocumentParseError(
            f"ocr engine not importable: {module_name}.{factory_name} "
            f"(见 {FILECHANNEL_CONFIG_PATH.name})") from exc
    params = dict(group.get("params") or {})
    try:
        return factory(params=params)
    except TypeError:  # 旧签名无 params 形参 → 裸构造兜底
        return factory()


def ocr_dpi() -> int:
    """扫描页渲染 DPI（config ocr_engine.render_dpi，缺省 300）。"""
    return int(_ocr_config().get("render_dpi", 300) or 300)


def ocr_text_score() -> float | None:
    """识别置信度阈值（config ocr_engine.text_score；缺省用引擎默认）。"""
    raw = _ocr_config().get("text_score")
    return None if raw is None else float(raw)


def _box_to_pt(box: Any, scale: float) -> BBox:
    """单条识别框（4 点像素坐标，原点左上）→ render 系轴对齐框（pt）。"""
    xs: list[float] = []
    ys: list[float] = []
    for pt in box:
        xs.append(float(pt[0]))
        ys.append(float(pt[1]))
    return (min(xs) / scale, min(ys) / scale, max(xs) / scale, max(ys) / scale)


def _as_list(value: Any) -> list[Any]:
    """OCR 输出字段（numpy 数组或 None）→ Python 列表（不做真值判断）。"""
    if value is None:
        return []
    return list(value)


def ocr_page_lines(data: bytes) -> OcrTextLayer:
    """pdf 字节 → 逐页 OCR 识别行表（render 系；页序、行序均按阅读序）。"""
    engine = load_ocr_engine()
    dpi = ocr_dpi()
    scale = dpi / 72.0
    score = ocr_text_score()
    reader = load_pdf_reader()
    try:
        doc = reader.PdfDocument(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 — 畸形输入统一转 422 语义
        raise DocumentParseError(f"pdf 解析失败: {exc}") from exc
    page_lines: list[list[OcrLine]] = []
    try:
        for page in doc:
            img = page.render(scale=scale).to_pil().convert("RGB")
            result = engine(_image_arg(img), text_score=score) if score is not None \
                else engine(_image_arg(img))
            txts = _as_list(result.txts)
            boxes = _as_list(result.boxes)
            rows = sorted(zip(txts, boxes, strict=True),
                          key=lambda tb: (_box_to_pt(tb[1], scale)[1],
                                          _box_to_pt(tb[1], scale)[0]))
            lines: list[OcrLine] = []
            offset = 0
            for text, box in rows:
                text = str(text)
                if not text.strip():
                    continue
                lines.append(OcrLine(offset, text, _box_to_pt(box, scale)))
                offset += len(text) + 1  # 行间以一个换行拼接
            page_lines.append(lines)
    except DocumentParseError:
        raise
    except Exception as exc:  # noqa: BLE001 — OCR 运行期异常归一为解析语义
        raise DocumentParseError(f"扫描件 OCR 失败: {exc}") from exc
    finally:
        try:
            doc.close()
        except Exception:  # noqa: BLE001 — 关闭失败不影响主流程
            pass
    log.info("filechannel.ocr.done", extra={
        "pages": len(page_lines),
        "lines": sum(len(p) for p in page_lines),
    })
    return OcrTextLayer(page_lines)


def _image_arg(img: Any) -> Any:
    """页位图 → OCR 引擎输入（numpy ndarray 视图；无 numpy 导入依赖）。"""
    try:
        import numpy  # noqa: PLC0415 — OCR 引擎输入面要求 ndarray

        return numpy.asarray(img)
    except ImportError:  # pragma: no cover — 依赖随 OCR 引擎装齐，防御性兜底
        return img
