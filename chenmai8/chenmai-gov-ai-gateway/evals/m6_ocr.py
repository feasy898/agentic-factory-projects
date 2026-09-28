"""M6 扫描件 OCR 路径验收（T4.1：渲染→OCR→重建可检测文本→体检→重打码导出）。

运行::

    cd REPO_ROOT && PYTHONUTF8=1 ./.venv/Scripts/python.exe -m evals.m6_ocr

范围（开发指令 §6 M6「scan_pdf：渲染 300dpi → OCR 引擎（纯 CPU）」+ 本任务单）：
被测对象为 :mod:`filechannel.ocr`（页面渲染→OCR→重建文本+命中框）+
:func:`filechannel.inspect.inspect_bytes`（scan_pdf 体检：身份证+位置）+
:func:`filechannel.sanitize.sanitize_scan_pdf`（经 :class:`FileService` 门面：
导出=重栅格化打码版 → **再 OCR 零残留**）。

夹具：**合成扫描 PDF** —— 文字以绘图方式画进位图再封装为纯图像 PDF
（零文本层，与扫描件同形态）；seeded 值来自 M8 生成器（身份证带正确校验位、
区划含澄迈配比），每份 4 个身份证 + 1 手机号，共 ``th.OCR_SEEDED_SCANS`` 份。

通过线（开发指令 §6 M6 / evals.thresholds）：

1. 体检报出身份证：``kind=scan_pdf``，seeded 身份证逐个命中（类别一致 +
   归一化等价，与 m6_filesvc 同口径）；
2. 身份证召回 ≥ ``th.OCR_ID_CARD_RECALL_MIN``（0.90；**OCR 数字识别容差如实
   报告**：逐 seed 列出重建文本读出形态与命中结论，误读/截断如实计 miss）；
3. 位置映射：每个身份证命中 ``page=1`` + render 系 bbox（页内、与绘制行
   y 带相交）；
4. 导出=重栅格化打码版：``method=scan-raster-redaction``（渲染→黑框覆盖→
   整页重栅格化，纯图像 PDF 零文本层）→ 导出物 re-ingest **再 OCR** 零残留
   （seeded 值零命中，重建文本零出现）；零命中扫描件导出原样返回
   （``pdf-noop``）。
"""
from __future__ import annotations

import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmark.generator import numbers as nums  # noqa: E402
from common.config import load_app_config  # noqa: E402
from evals import thresholds as th  # noqa: E402
from filechannel import inspect_bytes  # noqa: E402
from filechannel.parsers import parse_pdf  # noqa: E402
from filechannel.service import FileService  # noqa: E402
from masking.normalize import normalize_value  # noqa: E402
from recognizers.models import EntityClass  # noqa: E402

RESULTS: list[tuple[bool, str]] = []
DATA_DIR = REPO_ROOT / "data"
OUT_DIR = DATA_DIR / "fixtures" / "ocr"

#: 绘制参数（合成扫描件：绘图文字进位图 → 纯图像 PDF；render_dpi 与 OCR 路线一致）
SCAN_DPI = 300
FONT_SIZE_PX = 48
PAGE_INCH = (8.27, 11.69)
DRAW_X_PX = 250
DRAW_Y0_PX = 300
LINE_STEP_PX = 130
FONT_CANDIDATES = ("simhei.ttf", "msyh.ttc", "simsun.ttc")
CN_NUMS = "一二三四"
PERSONS = ("张三", "李四", "王五", "赵六")

#: fixture 仓（模块级缓存：build 一次，多检查共用）
_SCANS: dict[str, ScanFixture] = {}


@dataclass
class ScanFixture:
    """一份合成扫描件：字节、seeded 值与绘制坐标（pt 换算基准）。"""

    filename: str
    data: bytes
    ids: list[str]
    phone: str
    id_draw_y_px: dict[str, int] = field(default_factory=dict)

    def px_to_pt(self, px: float) -> float:
        return px * 72.0 / SCAN_DPI


def _record(name: str, fn):
    try:
        detail = fn()
        RESULTS.append((True, f"PASS  {name}" + (f" — {detail}" if detail else "")))
    except Exception as exc:  # noqa: BLE001 — 汇总所有失败后统一退出
        RESULTS.append((False, f"FAIL  {name} — {type(exc).__name__}: {exc}"))


def _load_font():
    from PIL import ImageFont

    last: Exception | None = None
    for name in FONT_CANDIDATES:
        path = Path(r"C:\Windows\Fonts") / name
        if path.exists():
            try:
                return ImageFont.truetype(str(path), FONT_SIZE_PX)
            except OSError as exc:  # noqa: PERF203 — 逐个候选回退
                last = exc
    raise AssertionError(f"no CJK font for synthetic scan: {FONT_CANDIDATES} ({last})")


def _build_scan(index: int) -> ScanFixture:
    """第 index 份合成扫描件（seed 固定；绘图文字 → 纯图像 PDF，零文本层）。"""
    from PIL import Image, ImageDraw

    rng = random.Random(20261010 + index)
    region, _ = nums.pick_region(rng)
    ids = [nums.gen_id_card(rng, region, nums.gen_birth(rng))
           for _ in range(th.OCR_IDS_PER_SCAN)]
    phone = nums.gen_mobile(rng)

    w_px, h_px = int(PAGE_INCH[0] * SCAN_DPI), int(PAGE_INCH[1] * SCAN_DPI)
    img = Image.new("RGB", (w_px, h_px), "white")
    draw = ImageDraw.Draw(img)
    font = _load_font()
    y = DRAW_Y0_PX
    draw.text((DRAW_X_PX, y), f"澄迈县某某镇低保对象名单公示（第{index + 1}批）",
              fill="black", font=font)
    y += LINE_STEP_PX
    y_by_id: dict[str, int] = {}
    for i, (person, ident) in enumerate(zip(PERSONS, ids, strict=True)):
        draw.text((DRAW_X_PX, y),
                  f"{CN_NUMS[i]}、{person}　公民身份号码 {ident}",
                  fill="black", font=font)
        y_by_id[ident] = y
        y += LINE_STEP_PX
    draw.text((DRAW_X_PX, y), f"咨询电话 {phone}", fill="black", font=font)
    y += LINE_STEP_PX
    draw.text((DRAW_X_PX, y), "公示期七天，如有异议请向镇民政办反映。",
              fill="black", font=font)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"scan_roster_{index + 1:02d}.pdf"
    path = OUT_DIR / filename
    img.save(path, "PDF", resolution=SCAN_DPI)
    data = path.read_bytes()
    assert path.stat().st_size == len(data)
    return ScanFixture(filename=filename, data=data, ids=ids, phone=phone,
                       id_draw_y_px=y_by_id)


def _fixtures() -> list[ScanFixture]:
    for i in range(th.OCR_SEEDED_SCANS):
        name = f"scan_roster_{i + 1:02d}.pdf"
        if name not in _SCANS:
            _SCANS[name] = _build_scan(i)
    return list(_SCANS.values())


def _matches(report, etype: str, value: str) -> list:
    """类别一致 + 归一化等价（§5.3.2）的命中列表（与 m6_filesvc 同口径）。"""
    want = normalize_value(EntityClass(etype), value)
    return [ff for ff in report.findings
            if ff.finding.type.value == etype and ff.finding.normalized == want]


def _rebuilt_text(data: bytes) -> str:
    """扫描件 OCR 重建文本（parse 层；仅供容差报告与导出物复核）。"""
    parsed = parse_pdf(data)
    assert parsed.text_layer is not None
    assert not any(t.strip() for t in parsed.text_layer.page_texts), \
        "合成扫描件应零文本层"
    return "\n".join(seg.text for seg in parsed.segments)


# ── 1. 合成扫描件体检（kind/零文本层/身份证+位置命中）────────────────


def check_scans() -> str:
    hits_total = 0
    for fx in _fixtures():
        report = inspect_bytes(fx.filename, fx.data)
        assert report.kind == "scan_pdf", (fx.filename, report.kind)
        assert report.pages == 1, report.pages
        for ident in fx.ids:
            hits = _matches(report, "ID_CARD", ident)
            assert len(hits) >= 1, f"{fx.filename} seeded 身份证未命中: {ident}"
            hits_total += len(hits)
        assert _matches(report, "PHONE_MOBILE", fx.phone), \
            f"{fx.filename} seeded 手机号未命中"
        assert report.risk_level == "HIGH", report.risk_level  # 批量身份证（4 ≥ 3）
    return (f"{len(_fixtures())} 份 scan_pdf：身份证+手机号体检命中 "
            f"{hits_total} 处，批量身份证→HIGH")


def check_recall() -> str:
    """身份证召回 ≥ 阈值；OCR 数字识别容差如实报告（误读/截断计 miss）。"""
    table: list[str] = []
    misses: list[str] = []
    seeded = hit = 0
    for fx in _fixtures():
        report = inspect_bytes(fx.filename, fx.data)
        rebuilt = _rebuilt_text(fx.data)
        for ident in fx.ids:
            seeded += 1
            read = "完整读出" if ident in rebuilt else "未完整读出（OCR 容差）"
            n = len(_matches(report, "ID_CARD", ident))
            if n >= 1:
                hit += 1
            else:
                misses.append(f"{fx.filename}:{ident}（{read}）")
            table.append(f"{ident[:6]}…{ident[-4:]} {read} 命中{n}")
    recall = hit / seeded if seeded else 0.0
    assert not misses, f"OCR 容差 miss（如实计入）: {misses}；逐 seed: {table}"
    assert seeded == th.OCR_SEEDED_SCANS * th.OCR_IDS_PER_SCAN, seeded
    assert recall >= th.OCR_ID_CARD_RECALL_MIN, recall
    return f"召回 {hit}/{seeded} = {recall:.2f} ≥ {th.OCR_ID_CARD_RECALL_MIN}"


def check_bbox() -> str:
    """位置映射：身份证命中 page=1 + render 系 bbox，与绘制行 y 带相交。"""
    checked = 0
    for fx in _fixtures():
        report = inspect_bytes(fx.filename, fx.data)
        w_pt, h_pt = fx.px_to_pt(PAGE_INCH[0] * SCAN_DPI), \
            fx.px_to_pt(PAGE_INCH[1] * SCAN_DPI)
        for ident, draw_y in fx.id_draw_y_px.items():
            hits = _matches(report, "ID_CARD", ident)
            assert hits, (fx.filename, ident)
            band_lo = fx.px_to_pt(draw_y) - 10.0
            band_hi = fx.px_to_pt(draw_y + FONT_SIZE_PX) + 10.0
            for h in hits:
                assert h.page == 1 and h.bbox is not None, (fx.filename, h)
                x0, y0, x1, y1 = h.bbox
                assert 0 <= x0 < x1 <= w_pt and 0 <= y0 < y1 <= h_pt, h.bbox
                assert y0 <= band_hi and y1 >= band_lo, \
                    (fx.filename, h.bbox, band_lo, band_hi)
                assert x0 >= fx.px_to_pt(DRAW_X_PX) - 10.0, h.bbox
                checked += 1
    return f"{checked} 处身份证命中 bbox 全部在页内且与绘制行 y 带相交（render 系）"


def check_rebuilt_text() -> str:
    """重建可检测文本：零文本层自证 + seeded 身份证在重建文本中原样出现。"""
    fx = _fixtures()[0]
    parsed = parse_pdf(fx.data)
    assert parsed.kind == "scan_pdf" and parsed.ocr_layer is not None
    assert parsed.text_layer is not None
    assert not any(t.strip() for t in parsed.text_layer.page_texts), "应零文本层"
    rebuilt = "\n".join(seg.text for seg in parsed.segments)
    assert rebuilt.strip(), "OCR 重建文本为空"
    for ident in fx.ids:
        assert ident in rebuilt, f"重建文本缺 seeded 身份证: {ident}"
    assert fx.phone in rebuilt, "重建文本缺 seeded 手机号"
    lines = [ln for ln in rebuilt.splitlines() if ln.strip()]
    return f"零文本层 + 重建文本 {len(lines)} 行（身份信号原样在位）"


# ── 2. 导出：重栅格化打码版 → 再 OCR 零残留 ─────────────────────────


def check_export() -> str:
    svc = FileService(load_app_config())
    for fx in _fixtures():
        result = svc.export_bytes(fx.filename, fx.data, "sanitize")
        assert result.method == "scan-raster-redaction", result.method
        assert result.content_type == "application/pdf"
        rep2 = svc.inspect_bytes(fx.filename, result.data)
        assert rep2.kind == "scan_pdf", rep2.kind
        assert rep2.pages == 1, rep2.pages
        dirty = [ff.finding.raw for ff in rep2.findings
                 if not ff.finding.whitelisted]
        assert not dirty, (fx.filename, dirty[:5])
        rebuilt = _rebuilt_text(result.data)
        for ident in fx.ids:
            assert ident not in rebuilt, f"导出物重建文本残留身份证: {ident}"
        assert fx.phone not in rebuilt, f"导出物重建文本残留手机号: {fx.phone}"
    return (f"{len(_fixtures())} 份导出 method=scan-raster-redaction"
            "（渲染→黑框覆盖→整页重栅格化），再 OCR 零残留")


def check_noop() -> str:
    """零命中扫描件导出原样返回（method=pdf-noop，字节不变）。"""
    from PIL import Image

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "scan_blank.pdf"
    w_px, h_px = int(PAGE_INCH[0] * SCAN_DPI), int(PAGE_INCH[1] * SCAN_DPI)
    Image.new("RGB", (w_px, h_px), "white").save(path, "PDF", resolution=SCAN_DPI)
    data = path.read_bytes()
    report = inspect_bytes(path.name, data)
    assert report.kind == "scan_pdf" and report.findings == [] \
        and report.risk_level == "NONE", (report.kind, len(report.findings))
    svc = FileService(load_app_config())
    result = svc.export_bytes(path.name, data, "sanitize")
    assert result.method == "pdf-noop", result.method
    assert result.data == data, "零命中扫描件导出被改动"
    return "blank scan → 零命中 / 导出 pdf-noop 字节原样"


def main() -> int:
    _record("scans(3份合成扫描件 kind/体检命中/HIGH)", check_scans)
    _record("ocr-recall(身份证召回≥90% 容差如实报告)", check_recall)
    _record("bbox(身份证位置映射 render 系)", check_bbox)
    _record("ocr-text(重建可检测文本/零文本层)", check_rebuilt_text)
    _record("export(重栅格化打码版→再OCR零残留)", check_export)
    _record("noop(零命中扫描件 pdf-noop)", check_noop)

    for _, line in RESULTS:
        print(line)
    passed = sum(1 for ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"M6 OCR(scan-pdf): {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
