"""M10 质量护照：BatchResult → 中/英/越三语 HTML（A4 打印 CSS）+ 验真二维码。

公开入口：

- :func:`build_passport`：一次性生成全部语言并返回 ``PassportReport``；
- ``canonical_sha256 / canonical_json``：BatchResult 规范化校验和；
- ``build_qr_payload / parse_qr_payload``：验真负载组装与回读解析；
- ``render_qr_png / qr_data_uri``：segno 渲染；
- ``STRINGS / LANGS / ui_for``：三语文案表（键集三语对齐，eval 有校验）；
- ``sieve_histogram_png``：目数分布直方（matplotlib，CJK 字体回退英文）。

使用::

    from beaneye.report import build_passport

    passport = build_passport(batch_result, "out/reports",
                              crop_root="out", standard_verified=False)
"""

from beaneye.report.charts import (
    CJK_FONT_CANDIDATES,
    chart_labels,
    resolve_cjk_font,
    sieve_histogram_png,
)
from beaneye.report.errors import ReportError
from beaneye.report.i18n import LANGS, STAGE_I18N, STANDARD_DISPLAY, STRINGS, ui_for
from beaneye.report.qr import (
    DEFAULT_VERIFY_BASE_URL,
    build_qr_payload,
    canonical_json,
    canonical_sha256,
    parse_qr_payload,
    qr_data_uri,
    render_qr_png,
)
from beaneye.report.builder import TEMPLATES_DIR, build_passport

__all__ = [
    "ReportError",
    "build_passport",
    "TEMPLATES_DIR",
    "canonical_json",
    "canonical_sha256",
    "build_qr_payload",
    "parse_qr_payload",
    "render_qr_png",
    "qr_data_uri",
    "DEFAULT_VERIFY_BASE_URL",
    "LANGS",
    "STRINGS",
    "STAGE_I18N",
    "STANDARD_DISPLAY",
    "ui_for",
    "CJK_FONT_CANDIDATES",
    "resolve_cjk_font",
    "chart_labels",
    "sieve_histogram_png",
]
