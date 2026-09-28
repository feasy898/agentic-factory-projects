"""M10 质量护照：计量图表（matplotlib 出 PNG）。

- 用面向对象的 ``Figure`` API + Agg，不引入 pyplot 状态；
- 中文字体：在候选表（SimHei 黑体优先）中探测已装字体；命中即用，并把
  ``axes.unicode_minus=False`` 一并设置（CJK 字体缺 U+2212，负号会变方框
  ——spec 明示「注意负号」）；LAB/ΔE 数值中的负号在图内因此用 ASCII 连字符；
- **字体回退**：一个 CJK 字体都没有时，图表文案回退英文（避免中文变方框），
  由 :func:`chart_labels` 统一决策，调用方无需关心。
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import matplotlib
from matplotlib import font_manager
from matplotlib.figure import Figure

from .i18n import ui_for

if TYPE_CHECKING:  # 仅供类型标注
    from beaneye.schemas import Measurements

__all__ = ["CJK_FONT_CANDIDATES", "resolve_cjk_font", "chart_labels", "chart_font_chain", "sieve_histogram_png"]

# 中文字体候选（按优先级；黑体 SimHei 为 spec 指定首选）
CJK_FONT_CANDIDATES = (
    "SimHei",
    "Microsoft YaHei",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "DengXian",
    "Microsoft JhengHei",
    "PingFang SC",
)


def resolve_cjk_font() -> str | None:
    """返回第一个已安装的 CJK 字体名；没有则 None（调用方回退英文文案）。"""
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for name in CJK_FONT_CANDIDATES:
        if name in installed:
            return name
    return None


def chart_labels(lang: str) -> tuple[str, str, str, str]:
    """图表文案 ``(title, xlabel, ylabel, lang_used)``。

    中文文案依赖 CJK 字体：一个都没有时回退英文（避免中文变方框）。
    越南语是拉丁加符文字，由 :func:`chart_font_chain` 用 DejaVu Sans
    覆盖，无需回退。
    """
    if lang == "zh" and resolve_cjk_font() is None:
        lang = "en"
    ui = ui_for(lang)
    return ui["metrology.chart.sieve"], ui["metrology.chart.screen"], ui["metrology.chart.count"], lang


def chart_font_chain(lang: str) -> list[str]:
    """图表字体链（按序逐字形回退）。

    - zh：CJK 字体优先（黑体/雅黑），DejaVu Sans 兜底西文与数字；
    - vi：DejaVu Sans 优先（SimHei 等中文字体缺越南语声调字形，
      实测渲染为方框——eval 抓获后改为按语言选链）；
    - en：同 vi。
    """
    cjk = resolve_cjk_font()
    if lang in ("en", "vi") or cjk is None:
        return ["DejaVu Sans", cjk] if cjk else ["DejaVu Sans"]
    return [cjk, "DejaVu Sans"]


def _sorted_sieve_keys(hist: dict[str, int]) -> list[str]:
    """目数键按数值升序；非数值键排在后面按字典序（防御性，正常不会出现）。"""
    def key(k: str) -> tuple[int, float, str]:
        try:
            return (0, float(k), k)
        except ValueError:
            return (1, 0.0, k)
    return sorted(hist, key=key)


def sieve_histogram_png(measurements: Measurements, *, lang: str = "zh") -> tuple[bytes, dict[str, str]]:
    """目数分布柱状图 PNG。

    返回 ``(png_bytes, meta)``；``meta`` 含 ``font``（实际用字体，可能为
    None=回退拉丁字体）与 ``lang_used``（实际文案语言）。
    """
    font_chain = chart_font_chain(lang)
    title, xlabel, ylabel, lang_used = chart_labels(lang)
    hist = measurements.sieve_hist
    keys = _sorted_sieve_keys(hist)
    values = [hist[k] for k in keys]

    rc = {
        "font.family": "sans-serif",
        "font.sans-serif": font_chain,
        "axes.unicode_minus": False,  # CJK 字体缺 U+2212，负号回退 ASCII 连字符
    }
    with matplotlib.rc_context(rc):
        fig = Figure(figsize=(6.4, 3.0), dpi=150)
        ax = fig.add_subplot(111)
        bars = ax.bar(keys, values, color="#8a5a2b", edgecolor="#5a3a1a", width=0.62)
        ax.bar_label(bars, fontsize=8, padding=2)
        ax.set_title(title, fontsize=11)
        ax.set_xlabel(xlabel, fontsize=9)
        ax.set_ylabel(ylabel, fontsize=9)
        ax.grid(axis="y", alpha=0.3, linewidth=0.6)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
        if values:
            ax.set_ylim(0, max(values) * 1.18)
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png")
    return buf.getvalue(), {"font": font_chain[0], "lang_used": lang_used}
