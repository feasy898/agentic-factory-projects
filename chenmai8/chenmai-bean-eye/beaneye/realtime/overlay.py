"""实时线 · 着色标注叠加（beaneye.realtime.overlay）。

按 ``configs/taxonomy.yaml`` 的类别 key 建稳定配色表（:data:`CLASS_COLORS_BGR`，
正常豆绿色系、各缺陷类取区分度高的不同色相），在原始帧上画：

- 逐粒外轮廓（类别色）+ 质心圆点 + 类别中文标签（已标定时附豆粒毫米尺寸）；
- HUD（左上：FPS / 分辨率 / 标定状态 / 帧序与检出数）；
- 图例条（底部：全类别色块 + 中文名 + 本帧各类计数，按严重度序排布）。

中文渲染：OpenCV Hershey 字体不含 CJK，中文文本经 PIL + 系统中文字体绘制
（微软雅黑 → 黑体 → 宋体依次探测，``BEANEYE_ZH_FONT`` 环境变量可指定）；
全部文本操作**合并成一次** PIL 往返（720p 逐条转换会吃掉数倍处理预算）。
PIL 或中文字体都不可用时退化为 ASCII 替代文本（键名/英文短语），功能不中断。

确定性：绘制为纯函数（无墙钟/随机），同输入逐像素一致（测试断言依据）。
"""

from __future__ import annotations

import os
from typing import Sequence

import cv2
import numpy as np

from beaneye.taxonomy import Taxonomy, load_taxonomy

__all__ = [
    "CLASS_COLORS_BGR",
    "DEFAULT_COLOR_BGR",
    "color_for",
    "class_label_zh",
    "zh_font_available",
    "draw_overlay",
]

# ---------------------------------------------------------------------------
# 稳定配色表（BGR；key 与 configs/taxonomy.yaml classes 一一对应）
# ---------------------------------------------------------------------------
# 选色原则：normal 绿色系（好豆=安心色）；各缺陷类一色一相、互不相邻撞色；
# 黑豆（最严重）用纯红警示；花豆 peaberry 青色（计量保留类，不算缺陷）。
CLASS_COLORS_BGR: dict[str, tuple[int, int, int]] = {
    "normal":    (0, 230, 0),      # 绿（好豆）
    "broken":    (0, 190, 255),    # 琥珀橙（破碎）
    "faded":     (255, 240, 230),  # 浅蓝白（褪色/白化）
    "brocade":   (120, 0, 230),    # 玫红（花脸）
    "immature":  (0, 255, 200),    # 青柠黄绿（未熟）
    "peaberry":  (255, 255, 0),    # 青（花豆/胡椒粒豆，标注保留不计数）
    "shell":     (255, 160, 0),    # 天蓝（贝壳豆）
    "elephant":  (60, 60, 200),    # 深红棕（象豆）
    "insect":    (255, 0, 0),      # 蓝（虫蛀）
    "dried":     (30, 105, 180),   # 棕（干瘪/僵豆）
    "sour":      (0, 255, 255),    # 黄（酸豆）
    "mold":      (255, 0, 255),    # 品红（霉豆）
    "black":     (0, 0, 255),      # 红（黑豆，严重度最高）
}
DEFAULT_COLOR_BGR = (170, 170, 170)  # 盘外/未知类别兜底（中性灰）

_TAX: Taxonomy | None = None


def _tax() -> Taxonomy:
    global _TAX
    if _TAX is None:
        _TAX = load_taxonomy()
    return _TAX


def color_for(key: str) -> tuple[int, int, int]:
    """类别 key → 稳定 BGR 颜色（未知 key 返回中性灰）。"""
    return CLASS_COLORS_BGR.get(key, DEFAULT_COLOR_BGR)


def class_label_zh(key: str) -> str:
    """类别 key → 中文短标签（取 taxonomy zh 名「/」前的主名，如 花豆/胡椒粒豆 → 花豆）。"""
    zh = _tax().get(key).zh if _tax().is_valid_key(key) else key
    return zh.split("/")[0].strip() or key


# ---------------------------------------------------------------------------
# 中文文本绘制（PIL + 系统字体；全部操作合并一次 PIL 往返）
# ---------------------------------------------------------------------------

try:  # PIL 缺位时退化为 ASCII 叠加（功能不中断）
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover
    Image = None  # type: ignore[assignment]

_FONT_CANDIDATES = (
    os.environ.get("BEANEYE_ZH_FONT", ""),
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
)
_FONT_OK: bool | None = None  # 三态缓存：None=未探测
_FONT_PATH: str | None = None
_FONT_CACHE: dict[int, "ImageFont.FreeTypeFont"] = {}


def _zh_font(px: int) -> "ImageFont.FreeTypeFont | None":
    """按像素号取中文字体（探测一次、按号缓存；全不可用返回 None）。"""
    global _FONT_OK, _FONT_PATH
    if px in _FONT_CACHE:
        return _FONT_CACHE[px]
    if _FONT_OK is None:
        _FONT_OK = False
        if Image is not None:
            for path in _FONT_CANDIDATES:
                if path and os.path.isfile(path):
                    try:
                        ImageFont.truetype(path, 12)
                        _FONT_PATH = path
                        _FONT_OK = True
                        break
                    except Exception:  # noqa: BLE001 — 坏字体文件当作不存在
                        continue
    if not _FONT_OK or Image is None or _FONT_PATH is None:
        return None
    font = ImageFont.truetype(_FONT_PATH, int(px))
    _FONT_CACHE[px] = font
    return font


def zh_font_available() -> bool:
    """当前环境能否用中文渲染（探测一次；测试与降级提示用）。"""
    return _zh_font(12) is not None


def _text_width(text: str, px: int, font) -> int:
    """文本像素宽（PIL 字体优先；无字体按 0.55*px 每字符估）。"""
    if font is not None:
        try:
            return int(round(font.getlength(text)))
        except Exception:  # noqa: BLE001
            pass
    return int(round(0.62 * px * len(text)))


def _blend_rect(img: np.ndarray, x0: int, y0: int, x1: int, y1: int, *, alpha: float = 0.55) -> None:
    """原位混合一块半透明深色底（HUD/图例可读性）。"""
    h, w = img.shape[:2]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return
    roi = img[y0:y1, x0:x1].astype(np.float32)
    dark = np.array([36.0, 30.0, 26.0])  # 深咖啡底（BGR），与啡眼主色一致
    img[y0:y1, x0:x1] = np.clip(roi * (1.0 - alpha) + dark * alpha + 0.5, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def draw_overlay(
    frame_bgr: np.ndarray,
    result: Any,  # beaneye.realtime.engine.FrameResult（避免循环导入，运行期鸭子类型）
    *,
    legend: bool = True,
    hud: bool = True,
    show_mm: bool | None = None,
    thickness: int | None = None,
) -> np.ndarray:
    """原始帧 + FrameResult → 标注帧（不修改输入；同输入逐像素一致）。

    ``show_mm``：是否给豆粒标毫米尺寸（缺省跟随 ``result.calibrated``——
    伪毫米口径绝不冒充毫米，见 engine 模块 docstring）。
    """
    frame = np.asarray(frame_bgr)
    canvas = frame.copy()
    h, w = canvas.shape[:2]
    if show_mm is None:
        show_mm = bool(result.calibrated)
    thick = int(thickness) if thickness else max(2, w // 640)
    base_px = int(min(max(w / 80.0, 11.0), 20.0))  # 字号随分辨率缩放
    texts: list[tuple[int, int, str, str, int, tuple[int, int, int]]] = []  # x,y,zh,ascii_alt,px,color

    # ---- 1) 逐粒：轮廓 + 质心 + 标签 --------------------------------------
    for b in result.beans:
        color = color_for(b.defect)
        cx, cy = b.centroid_px
        pts = np.asarray(b.contour_px, dtype=np.float32)
        if pts.ndim == 2 and len(pts) >= 3:
            cv2.polylines(canvas, [np.round(pts).astype(np.int32).reshape(-1, 1, 2)], True, color, thick, cv2.LINE_AA)
        r = max(2, w // 480)
        cv2.circle(canvas, (int(round(cx)), int(round(cy))), r, color, -1, cv2.LINE_AA)
        label = class_label_zh(b.defect)
        alt = b.defect
        if show_mm and b.eq_diameter_mm is not None:
            label += f" {b.eq_diameter_mm:.1f}mm"
            alt += f" {b.eq_diameter_mm:.1f}mm"
        tx = int(round(cx)) + r + 3
        ty = int(round(cy)) - base_px - 4
        if 0 <= tx < w and 0 <= ty < h:
            texts.append((tx, ty, label, alt, max(11, base_px - 1), color))

    # ---- 2) HUD（左上三行） ------------------------------------------------
    if hud:
        line_h = int(base_px * 1.55)
        pad = 6
        defect_n = sum(
            n for k, n in result.counts.items()
            if _tax().is_valid_key(k) and _tax().get(k).counts_as_defect
        )
        if result.calibrated:
            cal_zh = f"标定 {result.mm_per_px:.3f} mm/px（ArUco）"
            cal_alt = f"calib {result.mm_per_px:.3f} mm/px (aruco)"
        else:
            cal_zh = "未标定 · 无毫米口径"
            cal_alt = "uncalibrated (px only)"
        hud_lines = [
            (f"实时标注 · FPS {result.fps:.1f} · {result.width}x{result.height}",
             f"LIVE FPS {result.fps:.1f} {result.width}x{result.height}"),
            (cal_zh, cal_alt),
            (f"帧 {result.frame_index} · 检出 {len(result.beans)} 粒 · 缺陷 {defect_n} 粒",
             f"frame {result.frame_index} beans {len(result.beans)} defects {defect_n}"),
        ]
        _blend_rect(canvas, 0, 0, int(w * 0.62), pad * 2 + line_h * len(hud_lines))
        y = pad + int(base_px * 0.2)
        for zh, alt in hud_lines:
            texts.append((pad, y, zh, alt, base_px, (240, 240, 240)))
            y += line_h

    # ---- 3) 图例条（底部：全类别色块 + 中文名 + 本帧计数，严重度序） -------
    if legend:
        order: Sequence[str] = _tax().severity_order or list(CLASS_COLORS_BGR)
        font = _zh_font(base_px)
        row_h = int(base_px * 1.6)
        pad = 6
        entries: list[tuple[tuple[int, int, int], str, str, int]] = []
        for key in order:
            n = int(result.counts.get(key, 0))
            entries.append((color_for(key), class_label_zh(key), key, n))
        # 贪心换行排布（小分辨率一行放不下 13 类）
        rows: list[list[int]] = [[]]
        x = pad
        for i, (_c, zh, _k, _n) in enumerate(entries):
            wi = 14 + _text_width(f"{zh} {entries[i][3]}", base_px, font) + 16
            if x + wi > w - pad and rows[-1]:
                rows.append([])
                x = pad
            rows[-1].append(i)
            x += wi
        bar_y0 = h - (pad * 2 + row_h * len(rows))
        _blend_rect(canvas, 0, bar_y0, w, h)
        for ri, row in enumerate(rows):
            x = pad
            y = bar_y0 + pad + ri * row_h + int(base_px * 0.15)
            for i in row:
                color, zh, key, n = entries[i]
                cv2.rectangle(canvas, (x, y + 2), (x + 12, y + 14), color, -1)
                x += 18
                texts.append((x, y, f"{zh} {n}", f"{key} {n}", base_px, (235, 235, 235)))
                x += _text_width(f"{zh} {n}", base_px, font) + 16

    # ---- 4) 文本统一绘制（一次 PIL 往返） ----------------------------------
    _draw_texts(canvas, texts)
    return canvas


def _draw_texts(canvas: np.ndarray, texts: list[tuple[int, int, str, str, int, tuple[int, int, int]]]) -> None:
    """把全部文本操作画到 canvas（中文 PIL 一趟；无字体退化为 ASCII）。"""
    if not texts:
        return
    px_max = max(t[4] for t in texts)
    font = _zh_font(px_max)
    if font is None:
        for x, y, _zh, alt, px, color in texts:
            cv2.putText(
                canvas, alt, (x, y + int(px * 1.0)), cv2.FONT_HERSHEY_SIMPLEX,
                px / 24.0, color, max(1, px // 10), cv2.LINE_AA,
            )
        return
    pil = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)
    for x, y, zh, _alt, px, color in texts:
        f = _zh_font(px) or font
        draw.text((x, y), zh, font=f, fill=(int(color[2]), int(color[1]), int(color[0])))
    canvas[:] = cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)
