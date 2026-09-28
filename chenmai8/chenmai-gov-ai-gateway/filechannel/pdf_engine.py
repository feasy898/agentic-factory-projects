"""PDF 清理引擎抽象 + 多实现（M6 导出引擎，开发指令 §8.6「配置选择+自动回退」）。

统一适配面（:class:`PdfRedactionEngine`）：``name`` + ``redact(data, page_boxes,
needles) -> bytes``——按框/按值彻底删除命中文字并重写文件，导出物重抽取即零残留。

三实现（真实库名只写 config，铁律 E：源码经 importlib 动态加载、零库名）：

1. :class:`RenderRedactionEngine`——涂删主引擎（``config/app.yaml
   pdf_engine_module``）：按 render 系命中框标注涂删重写（框外扩
   :data:`REDACT_BOX_PAD_PT` 防笔画残边）；
2. :class:`ContentStreamRedactionEngine`——内容流手术引擎
   （``config/filechannel.yaml pdf_content_stream_engine.module``）：
   **算子级删除——整块移除含命中值的文本对象（BT…ET），而非盖黑框**，导出物
   内容流中命中对象物理不存在；页内存在无法解码的文本对象、或未定位到任何
   含命中对象即报 :class:`EngineNotApplicable` 换下一引擎（不能证明无残留时
   绝不静默通过）；
3. :class:`RasterRedactionEngine`——重渲染栅格化兜底引擎
   （``config/filechannel.yaml pdf_raster_engine.*``）：**重渲染打码版**——
   逐页渲染位图 → 命中框涂黑 → 重建纯图像 PDF（输出零文本层；scan_pdf
   重打码渲染版同路径，§6 M6）。

:func:`load_engine_chain` 按配置装配引擎链；导出侧（:mod:`filechannel.sanitize`）
逐引擎「涂删 → 重抽取复核」，前一引擎不适用或复核不净即自动回退下一引擎，
链尽仍不净报 :class:`ExportBlockedError`（宁可阻止不可漏删）。引擎模块一律
**惰性加载**（首次 redact 才 import）：体检不受引擎可用性影响，坏配置只削弱
导出面。
"""
from __future__ import annotations

import importlib
import io
import re
from functools import lru_cache
from typing import Any, Protocol

import yaml

from common.config import REPO_ROOT
from common.logs import get_logger

log = get_logger(__name__)

#: 涂删框外扩（pt）：字符级紧贴框易留笔画残边，四周各扩 1pt
REDACT_BOX_PAD_PT = 1.0

#: 栅格兜底渲染倍率（2.0 = 144dpi：复检/演示足够）
RASTER_RENDER_SCALE = 2.0

#: filechannel 引擎坐标配置（真实库名只允许出现在 config/）
FILECHANNEL_CONFIG_PATH = REPO_ROOT / "config" / "filechannel.yaml"

#: render 坐标系四元组 (x0, y0, x1, y1)，原点左上、y 向下、单位 pt
Box = tuple[float, float, float, float]


class EngineNotApplicable(RuntimeError):
    """引擎对本文件不适用（打不开/无法解码/未定位到命中）——调用方换下一引擎。"""


class PdfRedactionEngine(Protocol):
    """引擎适配面（三实现均对齐：涂删重写，输出物重抽取零残留）。"""

    name: str

    def redact(self, data: bytes, page_boxes: dict[int, list[Box]],
               needles: set[str]) -> bytes: ...


# ── 实现一：标注框涂删重写（主引擎，app.yaml pdf_engine_module）────────


class RenderRedactionEngine:
    """涂删主引擎：按 render 系命中框标注涂删后重写（无框页保持原样）。"""

    def __init__(self, module_name: str) -> None:
        self.name = "render-redaction"
        self._module_name = module_name
        self._mod: Any = None

    def _load(self) -> Any:
        if self._mod is None:
            try:
                self._mod = importlib.import_module(self._module_name)
            except ImportError as exc:
                raise EngineNotApplicable(
                    f"涂删引擎模块不可用: {self._module_name}（{exc}）") from exc
        return self._mod

    def redact(self, data: bytes, page_boxes: dict[int, list[Box]],
               needles: set[str]) -> bytes:
        if not page_boxes:
            return data
        mod = self._load()
        try:
            doc = mod.open(stream=data, filetype="pdf")
        except Exception as exc:  # noqa: BLE001 — 打不开归一为「不适用」换下一引擎
            raise EngineNotApplicable(f"涂删引擎打不开文件: {exc}") from exc
        try:
            for page_index, boxes in sorted(page_boxes.items()):
                page = doc[page_index]
                for box in boxes:
                    x0, y0, x1, y1 = box
                    rect = mod.Rect(x0 - REDACT_BOX_PAD_PT, y0 - REDACT_BOX_PAD_PT,
                                    x1 + REDACT_BOX_PAD_PT, y1 + REDACT_BOX_PAD_PT)
                    page.add_redact_annot(rect)
                page.apply_redactions()
            return doc.tobytes(garbage=3, deflate=True)
        finally:
            try:
                doc.close()
            except Exception:  # noqa: BLE001 — 关闭失败不影响主流程
                log.warning("pdf_engine.render.close_failed",
                            extra={"module": self._module_name})


# ── 实现二：内容流手术（算子级删除文本对象，非盖黑框）────────────────

#: 文本显示算子（PDF 32000-1 §9.4：Tj/TJ 直显，'/" 换行直显）
_TEXT_SHOW_OPS = frozenset({"Tj", "TJ", "'", '"'})

_HEXPAT = re.compile(r"<([0-9A-Fa-f]*)>")
_BF_SECTION = re.compile(r"begin(bfchar|bfrange)(.*?)end\1", re.S)


def _utf16be(raw: bytes) -> str:
    """UTF-16BE 字节（可带 BOM）→ 文本；奇数字节按单字节容错。"""
    if raw[:2] == b"\xfe\xff":
        raw = raw[2:]
    elif raw[:2] == b"\xff\xfe":
        raw = raw[2:]
        return raw.decode("utf-16-le")
    if len(raw) % 2:
        return raw.decode("latin-1")
    return raw.decode("utf-16-be")


def _parse_tounicode_cmap(raw: bytes) -> dict[int, str]:
    """最小 ToUnicode CMap 解析（bfchar/bfrange 段 → 码点 → 文本）。

    覆盖常规导出面：``<src> <dst>`` 单映射、``<lo> <hi> <dst基址>`` 等差区间、
    ``<lo> <hi> [<d1> <d2>…]`` 数组形区间。解析不出的条目跳过——调用方对未知
    码点一律按「无法解码」处理，不猜。
    """
    mapping: dict[int, str] = {}
    try:
        text = raw.decode("latin-1")
    except Exception:  # noqa: BLE001 — 非 latin-1 字节的 CMap 视为不可解析
        return mapping
    for kind, body in _BF_SECTION.findall(text):
        if kind == "bfchar":
            tokens = _HEXPAT.findall(body)
            for i in range(0, len(tokens) - 1, 2):
                mapping[int(tokens[i] or "0", 16)] = _utf16be(bytes.fromhex(tokens[i + 1]))
        else:
            mapping.update(_parse_bfrange(body))
    return mapping


def _parse_bfrange(body: str) -> dict[int, str]:
    """bfrange 段：等差形 ``<lo> <hi> <dst基址>`` 与数组形 ``<lo> <hi> [<d…]``
    逐条展开（未知形态跳过，不中断整段）。"""
    out: dict[int, str] = {}
    pos = 0
    while True:
        m_lo = _HEXPAT.search(body, pos)
        if not m_lo:
            return out
        m_hi = _HEXPAT.search(body, m_lo.end())
        if not m_hi:
            return out
        lo, hi = int(m_lo.group(1) or "0", 16), int(m_hi.group(1) or "0", 16)
        if hi < lo or hi - lo > 65535:  # 异常区间防御：跳过这一条
            pos = m_hi.end()
            continue
        m_dst = _HEXPAT.search(body, m_hi.end())
        bracket = body.find("[", m_hi.end())
        if m_dst is None:
            return out
        if bracket != -1 and bracket < m_dst.start():  # 数组形
            close = body.find("]", bracket)
            if close == -1:
                return out
            items = _HEXPAT.findall(body[bracket:close])
            for off, item in enumerate(items[:hi - lo + 1]):
                out[lo + off] = _utf16be(bytes.fromhex(item))
            pos = close + 1
        else:  # 等差形
            base = int(m_dst.group(1) or "0", 16)
            width = max(1, len(m_dst.group(1)) // 2)
            for off in range(hi - lo + 1):
                code = (base + off) % (1 << (width * 8))
                out[lo + off] = _utf16be(code.to_bytes(width, "big"))
            pos = m_dst.end()


def _raw_string_bytes(item: Any) -> bytes | None:
    """TJ 数组元素 → 字符串原始字节（数值 kerning 项返回 None；不猜类型）。"""
    if isinstance(item, bool) or isinstance(item, int) or isinstance(item, float):
        return None
    try:
        return bytes(item)
    except (TypeError, ValueError):
        return None


def _strings_of(inst: Any) -> list[bytes]:
    """一条文本算子的全部字符串实参原始字节（TJ 数组跳过 kerning 数值）。"""
    op = str(inst.operator)
    operands = getattr(inst, "operands", [])
    if op == "TJ" and operands:
        out = []
        for item in operands[0]:
            raw = _raw_string_bytes(item)
            if raw is not None:
                out.append(raw)
        return out
    if op in ("Tj", "'") and operands:
        raw = _raw_string_bytes(operands[0])
        return [raw] if raw is not None else []
    if op == '"' and len(operands) >= 3:
        raw = _raw_string_bytes(operands[2])
        return [raw] if raw is not None else []
    return []


def _font_decoder(font: Any) -> Any:
    """字体字典 → 解码函数 ``(bytes) -> str | None``（None=不可解码，绝不猜）。"""
    if font is None:
        return None
    cmap: dict[int, str] = {}
    to_unicode = font.get("/ToUnicode")
    if to_unicode is not None:
        try:
            cmap = _parse_tounicode_cmap(bytes(to_unicode.read_bytes()))
        except Exception:  # noqa: BLE001 — CMap 坏损按无表处理
            cmap = {}
    is_type0 = str(font.get("/Subtype", "")) == "/Type0"
    if is_type0:
        width = 2  # 复合字体 CMap 码长按 2 字节（演示面全部命中此形态）
        if cmap:
            def decode_cid(raw: bytes, _w: int = width,
                           _m: dict[int, str] = cmap) -> str | None:
                if len(raw) % _w:
                    return None
                out: list[str] = []
                for i in range(0, len(raw), _w):
                    ch = _m.get(int.from_bytes(raw[i:i + _w], "big"))
                    if ch is None:
                        return None
                    out.append(ch)
                return "".join(out)
            return decode_cid
        enc = font.get("/Encoding")
        enc_name = str(enc) if enc is not None else ""
        if "UTF16" in enc_name.upper() or "UCS2" in enc_name.upper():
            return lambda raw: _utf16be(raw) if len(raw) % 2 == 0 else None
        return None  # Identity 等无 ToUnicode 的复合字体：无法解码 → 不适用

    if cmap:  # 简单字体：1 字节码 + ToUnicode
        def decode_simple(raw: bytes, _m: dict[int, str] = cmap) -> str | None:
            out: list[str] = []
            for b in raw:
                ch = _m.get(b)
                if ch is None:
                    return None
                out.append(ch)
            return "".join(out)
        return decode_simple
    return lambda raw: raw.decode("latin-1")  # 简单字体无表：单字节直解


def _collect_text_objects(ops: list[Any]) -> list[tuple[bool, list[Any]]]:
    """内容流算子表 → [(块内含文本算子?, 算子列表)]；BT…ET 为一块，
    块外孤立文本算子各自成块（病态流也要能手术）。"""
    objects: list[tuple[bool, list[Any]]] = []
    current: list[Any] = []
    in_text = False
    has_text = False
    for inst in ops:
        op = str(inst.operator)
        if op == "BT":
            if current:
                objects.append((has_text, current))
            current, in_text, has_text = [inst], True, False
            continue
        if in_text:
            current.append(inst)
            if op == "ET":
                objects.append((has_text, current))
                current, in_text = [], False
            elif op in _TEXT_SHOW_OPS:
                has_text = True
            continue
        if op in _TEXT_SHOW_OPS:
            objects.append((True, [inst]))
        else:
            if current:
                objects.append((has_text, current))
                current, has_text = [], False
            objects.append((False, [inst]))
    if current:
        objects.append((has_text, current))
    return objects


class ContentStreamRedactionEngine:
    """内容流手术引擎：**整块移除含命中值的文本对象**（算子级物理删除）。

    安全口径：仅当页内全部文本对象均可解码、且至少移除一个含命中对象时才算
    成功；否则报 :class:`EngineNotApplicable` 交回退链（宁可换引擎不可假删除）。
    """

    def __init__(self, module_name: str) -> None:
        self.name = "content-stream"
        self._module_name = module_name
        self._mod: Any = None

    def _load(self) -> Any:
        if self._mod is None:
            try:
                self._mod = importlib.import_module(self._module_name)
            except ImportError as exc:
                raise EngineNotApplicable(
                    f"内容流引擎模块不可用: {self._module_name}（{exc}）") from exc
        return self._mod

    def redact(self, data: bytes, page_boxes: dict[int, list[Box]],
               needles: set[str]) -> bytes:
        if not page_boxes or not needles:
            return data
        pike = self._load()
        try:
            pdf = pike.Pdf.open(io.BytesIO(data))
        except Exception as exc:  # noqa: BLE001
            raise EngineNotApplicable(f"内容流引擎打不开文件: {exc}") from exc
        try:
            changed = False
            for page_index in sorted(page_boxes):
                if page_index >= len(pdf.pages):
                    raise EngineNotApplicable(f"页索引越界: {page_index}")
                page = pdf.pages[page_index]
                ops = list(pike.parse_content_stream(page))
                kept, removed, decodable = self._sift_page(page, ops, needles)
                if not decodable:
                    raise EngineNotApplicable(
                        f"第{page_index + 1}页存在无法解码的文本对象（不能证明无残留）")
                if removed:
                    page.Contents = pdf.make_stream(pike.unparse_content_stream(kept))
                    changed = True
            if not changed:
                raise EngineNotApplicable("内容流未定位到任何含命中的文本对象"
                                          "（疑似跨对象拼接/异体编码）")
            buf = io.BytesIO()
            pdf.save(buf)
            return buf.getvalue()
        finally:
            try:
                pdf.close()
            except Exception:  # noqa: BLE001 — 关闭失败不影响主流程
                pass

    def _sift_page(self, page: Any, ops: list[Any],
                   needles: set[str]) -> tuple[list[Any], int, bool]:
        """逐块判码：返回 (保留算子表, 移除块数, 页内是否全部可解码)。"""
        fonts: dict[str, Any] = {}
        try:
            fonts = {str(k): v for k, v in page["/Resources"]["/Font"].items()}
        except KeyError:
            fonts = {}
        decoders: dict[str, Any] = {}
        kept: list[Any] = []
        removed = 0
        decodable = True
        for has_text, block in _collect_text_objects(ops):
            if not has_text:
                kept.extend(block)
                continue
            text, block_decodable = self._decode_block(block, fonts, decoders)
            if not block_decodable:
                decodable = False
                kept.extend(block)  # 不可解码块不动；引擎整体将被判不适用
                continue
            if any(needle and needle in text for needle in needles):
                removed += 1
                continue  # 整块移除：BT/ET 与状态设置一并消失，内容流物理删除
            kept.extend(block)
        return kept, removed, decodable

    def _decode_block(self, block: list[Any], fonts: dict[str, Any],
                      decoders: dict[str, Any]) -> tuple[str, bool]:
        parts: list[str] = []
        current_key = ""
        for inst in block:
            if str(inst.operator) == "Tf" and inst.operands:
                current_key = str(inst.operands[0])
            if str(inst.operator) not in _TEXT_SHOW_OPS:
                continue
            if current_key not in decoders:
                decoders[current_key] = _font_decoder(fonts.get(current_key))
            decode = decoders[current_key]
            for raw in _strings_of(inst):
                if decode is None:
                    return "", False
                piece = decode(raw)
                if piece is None:
                    return "", False
                parts.append(piece)
        return "".join(parts), True


# ── 实现三：重渲染栅格化打码（兜底；scan_pdf 重打码渲染版同路径）──────


class RasterRedactionEngine:
    """兜底引擎：逐页渲染位图 → 命中框涂黑 → 重建纯图像 PDF（输出零文本层）。

    删除式不可行时的最后防线（§6 M6「重打码渲染版」）：命中文字随原始文本层
    一并消失，导出物重抽取为空——如实以 ``kind=scan_pdf`` 呈现。
    """

    def __init__(self, reader_module: str, image_module: str,
                 image_draw_module: str = "") -> None:
        self.name = "raster"
        self._reader_module = reader_module
        self._image_module = image_module
        self._draw_module = image_draw_module
        self._reader: Any = None
        self._image: Any = None
        self._draw: Any = None

    def _load(self) -> tuple[Any, Any, Any]:
        if self._reader is None:
            try:
                self._reader = importlib.import_module(self._reader_module)
                self._image = importlib.import_module(self._image_module)
                self._draw = (importlib.import_module(self._draw_module)
                              if self._draw_module else None)
            except ImportError as exc:
                raise EngineNotApplicable(f"栅格引擎模块不可用: {exc}") from exc
        return self._reader, self._image, self._draw

    def redact(self, data: bytes, page_boxes: dict[int, list[Box]],
               needles: set[str]) -> bytes:
        if not page_boxes:
            return data
        if not self._draw_module:
            raise EngineNotApplicable(
                "栅格引擎绘制模块未配置（pdf_raster_engine.image_draw_module）")
        reader, _image, draw_mod = self._load()
        try:
            src = reader.PdfDocument(io.BytesIO(data))
        except Exception as exc:  # noqa: BLE001
            raise EngineNotApplicable(f"栅格引擎打不开文件: {exc}") from exc
        scale = RASTER_RENDER_SCALE
        pages: list[Any] = []
        try:
            for page_index, page in enumerate(src):
                img = page.render(scale=scale).to_pil().convert("RGB")
                boxes = page_boxes.get(page_index, [])
                if boxes:
                    draw = draw_mod.Draw(img)
                    w, h = img.size
                    for box in boxes:
                        x0, y0, x1, y1 = box
                        pad = REDACT_BOX_PAD_PT * scale
                        rect = [max(0.0, x0 * scale - pad), max(0.0, y0 * scale - pad),
                                min(float(w), x1 * scale + pad),
                                min(float(h), y1 * scale + pad)]
                        if rect[2] > rect[0] and rect[3] > rect[1]:
                            draw.rectangle(rect, fill=(0, 0, 0))
                pages.append(img)
        except Exception as exc:  # noqa: BLE001
            raise EngineNotApplicable(f"栅格渲染失败: {exc}") from exc
        finally:
            try:
                src.close()
            except Exception:  # noqa: BLE001 — 关闭失败不影响主流程
                pass
        if not pages:
            raise EngineNotApplicable("栅格渲染零页")
        buf = io.BytesIO()
        # resolution=72*scale 使重建页尺寸与原页一致（像素 ÷ 分辨率 × 72 = pt）
        pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:],
                      resolution=72.0 * scale)
        return buf.getvalue()


# ── 引擎链装配（配置选择 + 自动回退）────────────────────────────────


@lru_cache(maxsize=1)
def _filechannel_engine_config() -> dict[str, Any]:
    """config/filechannel.yaml 的引擎坐标段（缺失/空配置返回空 dict）。"""
    try:
        return yaml.safe_load(FILECHANNEL_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except OSError:
        return {}


def load_engine_chain(primary_module: str) -> list[PdfRedactionEngine]:
    """按配置装配引擎链：涂删主引擎 → 内容流手术 → 栅格兜底（顺序即回退序）。

    引擎模块惰性加载：本函数只装配坐标，import 失败在 redact 时报
    :class:`EngineNotApplicable` 并由调用方回退——配置缺失/库不可用不抛异常。
    """
    chain: list[PdfRedactionEngine] = []
    if str(primary_module or "").strip():
        chain.append(RenderRedactionEngine(str(primary_module).strip()))
    cfg = _filechannel_engine_config()
    content = cfg.get("pdf_content_stream_engine") or {}
    if str(content.get("module", "")).strip():
        chain.append(ContentStreamRedactionEngine(str(content["module"]).strip()))
    raster = cfg.get("pdf_raster_engine") or {}
    if str(raster.get("reader_module", "")).strip() and \
            str(raster.get("image_module", "")).strip():
        chain.append(RasterRedactionEngine(
            str(raster["reader_module"]).strip(),
            str(raster["image_module"]).strip(),
            str(raster.get("image_draw_module", "")).strip()))
    return chain


def union_boxes(boxes: list[Box]) -> Box | None:
    """多个命中框合并为一个外接框（空表返回 None）。"""
    if not boxes:
        return None
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    return (x0, y0, x1, y1)
