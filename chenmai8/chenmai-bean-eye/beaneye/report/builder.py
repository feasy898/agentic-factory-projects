"""M10 质量护照构建：BatchResult → 三语 HTML + PassportReport。

流程（``build_passport``）：

1. ``canonical_sha256``：BatchResult 规范化 JSON 的 sha256（校验和）；
2. ``build_qr_payload``：``{verify_base_url}/r/{report_id}|{sha256}``，
   segno 渲染 PNG 内嵌（``qr_data_uri``）；
3. 逐语言渲染 ``templates/report_{lang}.html.j2``（继承 base 布局），
   所有数值/文案在 Python 侧预组装（视图函数 ``_*_view``），模板零逻辑；
4. 写 ``{out_dir}/{report_id}.{lang}.html``（UTF-8，自包含单文件：
   图表/二维码/证据图全部 data URI 内嵌），返回 :class:`PassportReport`
   （``html_paths`` 值为写入文件的绝对路径，posix 风格）。

标准核对角标（契约 §3.3/§9）：``standard_verified`` 为 ``False`` 时页脚
显示「标准阈值核对中」（对应标准 YAML ``verified:false`` 上报口径）；
``None`` 不显示角标；``True`` 显示已对照角标。若 ``GradingDecision``
带 ``warnings`` 字段（契约 v1.1 增补，M9 填写标准核对告警），则
``standard_verified`` 未显式指定时按「warnings 非空 → 核对中」自动判定；
字段尚不存在（v1.0 冻结版）时安全回退为仅看显式参数。
"""

from __future__ import annotations

import base64
import time
from datetime import datetime
from pathlib import Path
from typing import Sequence

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from beaneye.schemas import (
    AgentReport,
    BatchResult,
    Measurements,
    PairedBean,
    PassportReport,
)
from beaneye.taxonomy import DefectClass, Taxonomy, load_taxonomy

from .charts import sieve_histogram_png
from .evidence import side_image
from .errors import ReportError
from .i18n import LANGS, STAGE_I18N, STANDARD_DISPLAY, ui_for
from .qr import DEFAULT_VERIFY_BASE_URL, build_qr_payload, canonical_sha256, qr_data_uri

__all__ = ["build_passport", "TEMPLATES_DIR"]

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def build_passport(
    result: BatchResult,
    out_dir: str | Path,
    *,
    langs: Sequence[str] = LANGS,
    verify_base_url: str = DEFAULT_VERIFY_BASE_URL,
    crop_root: str | Path | None = None,
    standard_verified: bool | None = None,
    generated_at: str | None = None,
    taxonomy: Taxonomy | None = None,
) -> PassportReport:
    """构建三语质量护照，返回 :class:`beaneye.schemas.PassportReport`。

    参数：
        result: 整盘结果（数据源与校验和对象）。
        out_dir: 输出目录（不存在则创建）。
        langs: 要生成的语言（默认中/英/越三语）。
        verify_base_url: 验真 URL 前缀（QR 负载第一段）。
        crop_root: 相对 ``crop_path`` 的解析根目录；缺省用当前工作目录。
        standard_verified: 标准阈值核对状态（None=不显示角标）。
        generated_at: 报告生成时间 ISO8601；缺省取当前本地时间。
        taxonomy: 缺陷体系（缺省加载 ``configs/taxonomy.yaml``）。
    """
    t0 = time.perf_counter()
    lang_list = [langs] if isinstance(langs, str) else list(langs)
    if not lang_list:
        raise ReportError("langs 不能为空")
    for lg in lang_list:
        ui_for(lg)  # 未知语言即刻报错
    tax = taxonomy if taxonomy is not None else load_taxonomy()
    root = Path(crop_root).resolve() if crop_root is not None else Path.cwd()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    sha = canonical_sha256(result)
    payload = build_qr_payload(result.result_id, sha, verify_base_url=verify_base_url)
    qr_uri = qr_data_uri(payload)
    gen_at = generated_at or datetime.now().astimezone().isoformat(timespec="seconds")
    if standard_verified is None:
        # M10 spec：角标引用 GradingDecision.warnings；v1.0 无该字段时回退
        warnings = getattr(result.grading, "warnings", None) or []
        standard_verified = False if warnings else None

    meta = {
        "report_id": result.result_id,
        "sample_id": result.sample_id,
        "scan_ids": ", ".join(result.scan_ids) if result.scan_ids else "—",
        "generated_at": gen_at,
        "standard_id": result.grading.standard_id,
        "standard_sha": result.grading.standard_yaml_sha,
    }

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    html_paths: dict[str, str] = {}
    for lg in lang_list:
        ui = ui_for(lg)
        ctx = {
            "lang": lg,
            "ui": ui,
            "meta": meta,
            "standard_display": STANDARD_DISPLAY.get(meta["standard_id"], {}).get(lg, meta["standard_id"]),
            "standard_verified": standard_verified,
            "sha": sha,
            "payload": payload,
            "qr_uri": qr_uri,
            "grade": _grading_view(result, ui),
            "defects": _defects_view(result, tax, lg),
            "metro": _metrology_view(result.measurements, lg),
            "cards": _cards_view(result, tax, lg, crop_root=root),
            "agent": _agent_view(result.agent_report, tax, lg),
        }
        ctx["evidence_line"] = ui["evidence.count"].format(n=len(ctx["cards"]))
        html = env.get_template(f"report_{lg}.html.j2").render(**ctx)
        path = out / f"{result.result_id}.{lg}.html"
        path.write_text(html, encoding="utf-8")
        html_paths[lg] = path.as_posix()

    report = PassportReport(
        report_id=result.result_id,
        langs=lang_list,
        html_paths=html_paths,
        qr_payload=payload,
        sha256=sha,
    )
    _ = time.perf_counter() - t0  # 时限（≤5s/份）由 eval 计测
    return report


# ---------------------------------------------------------------------------
# 视图组装（模板零逻辑：所有显示值在此格式化；语言 lang 显式传参）
# ---------------------------------------------------------------------------


def _grading_view(result: BatchResult, ui: dict[str, str]) -> dict[str, object]:
    g = result.grading
    # reasons 是 i18n 模板键（如 grading.reason.*）；未登记的键原样显示
    reasons = [ui.get(r, r) for r in g.reasons]
    return {
        "passed": g.passed,
        "result_label": ui["grading.result.passed"] if g.passed else ui["grading.result.failed"],
        "grade": g.grade,
        "reasons": reasons,
        "primary_count": g.primary_count,
        "secondary_count": g.secondary_count,
        "standard_sha": g.standard_yaml_sha,
    }


def _defects_view(result: BatchResult, tax: Taxonomy, lang: str) -> dict[str, object]:
    ui = ui_for(lang)
    counts = result.grading.defect_counts
    total = sum(counts.values()) or 1

    def rank_desc(key: str) -> int:
        return -_rank(tax, key)

    rows = []
    defective = 0
    for key in sorted(counts, key=rank_desc):
        dc = _defect_class(tax, key)
        kind_label = ui[f"defect.kind.{_kind(dc)}"]
        rows.append(
            {
                "key": key,
                "name": _localize(dc, key, lang),
                "kind": kind_label,
                "count": counts[key],
                "share": f"{100.0 * counts[key] / total:.1f}%",
            }
        )
        if dc is None or dc.counts_as_defect:
            defective += counts[key]
    bean_count = result.measurements.bean_count
    return {
        "bean_count": bean_count,
        "defective_count": defective,
        "defect_rate": f"{100.0 * defective / bean_count:.2f}%" if bean_count else "—",
        "rows": rows,
    }


def _metrology_view(measurements: Measurements, lang: str) -> dict[str, object]:
    ui = ui_for(lang)
    m = measurements
    png, _meta = sieve_histogram_png(m, lang=lang)
    chart_uri = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    sieve_total = sum(m.sieve_hist.values()) or 1
    sieve_rows = [
        {"sieve": k, "count": m.sieve_hist[k], "share": f"{100.0 * m.sieve_hist[k] / sieve_total:.1f}%"}
        for k in _numeric_sorted(m.sieve_hist)
    ]
    de_rows = [{"bucket": k, "count": m.delta_e_hist[k]} for k in _numeric_sorted(m.delta_e_hist)]
    st = m.eq_diameter_mm_stats
    lab = m.color_lab_mean
    return {
        "chart_uri": chart_uri,
        "sieve_rows": sieve_rows,
        "sieve_pass": _tri_bool(m.sieve_pass, ui),
        "diam": {
            "min": f"{st.min:.2f}",
            "max": f"{st.max:.2f}",
            "mean": f"{st.mean:.2f}",
            "median": f"{st.median:.2f}",
        },
        "weight": f"{m.est_weight_g:.1f} g",
        "weight_model": m.weight_model,
        "color": f"L {lab[0]:.1f} / a {lab[1]:.1f} / b {lab[2]:.1f}",
        "delta_e": f"{m.delta_e_mean:.2f}",
        "de_rows": de_rows,
    }


def _cards_view(
    result: BatchResult, tax: Taxonomy, lang: str, *, crop_root: Path
) -> list[dict[str, object]]:
    ui = ui_for(lang)
    cards: list[dict[str, object]] = []
    for b in result.beans:
        if b.final_severity_rank <= 0:  # normal（好豆）不立证据卡
            continue
        winner_key = _winner_side_key(b)
        winner_obs = b.top if winner_key == "top" else b.bottom
        sides = []
        for side_key, obs in (("top", b.top), ("bottom", b.bottom)):
            if obs is None:
                continue
            si = side_image(obs, bean_id=b.bean_id, defect_key=b.final_defect, crop_root=crop_root)
            sides.append(
                {
                    "label": ui[f"evidence.img.{side_key}"],
                    "conf": f"{obs.defect_conf * 100:.1f}%",
                    "coord": si["coord_text"],
                    "diam": f"{obs.eq_diameter_mm:.2f} mm",
                    "img_uri": si["img_uri"],
                    "placeholder": bool(si["placeholder"]),
                    "is_winner": side_key == winner_key,
                }
            )
        cards.append(
            {
                "bean_id": b.bean_id,
                "defect_key": b.final_defect,
                "defect_name": _localize(_defect_class(tax, b.final_defect), b.final_defect, lang),
                "rank": b.final_severity_rank,
                "worst_label": ui[f"side.{b.worst_side}"],
                "conf": f"{winner_obs.defect_conf * 100:.1f}%" if winner_obs is not None else "—",
                "sides": sides,
            }
        )
    return cards


def _agent_view(agent: AgentReport | None, tax: Taxonomy, lang: str) -> dict[str, object] | None:
    if agent is None:
        return None
    ui = ui_for(lang)
    causes = [
        {
            "defect": _localize(_defect_class(tax, c.defect), c.defect, lang),
            "stage": _stage_label(c.stage, lang),
            "likelihood": f"{c.likelihood:.2f}",
            "evidence": c.evidence_summary,
        }
        for c in agent.causes
    ]
    return {
        "causes": causes,
        "advice": list(agent.advice),
        "citations": list(agent.citations),
        "backend": ui[f"agent.backend.{agent.backend}"],
    }


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


def _rank(tax: Taxonomy, key: str) -> int:
    try:
        return tax.severity_rank(key)
    except Exception:  # 未知类排最后（契约外键不应出现，防御性）
        return -1


def _defect_class(tax: Taxonomy, key: str) -> DefectClass | None:
    return tax.get(key) if tax.is_valid_key(key) else None


def _kind(dc: DefectClass | None) -> str:
    return dc.kind if dc is not None else "secondary"


def _localize(dc: DefectClass | None, fallback: str, lang: str) -> str:
    if dc is None:
        return fallback
    return getattr(dc, lang, None) or getattr(dc, "en", None) or fallback


def _stage_label(stage: str, lang: str) -> str:
    """CauseItem.stage（契约规范值为中文环节名）→ 目标语言；未知值原样。"""
    if stage in STAGE_I18N:
        return STAGE_I18N[stage].get(lang, stage)
    if any(stage in names.values() for names in STAGE_I18N.values()):
        return stage  # 已是某语言规范名
    return stage


def _tri_bool(v: bool | None, ui: dict[str, str]) -> str:
    return ui["common.yes"] if v is True else (ui["common.no"] if v is False else ui["common.dash"])


def _winner_side_key(b: PairedBean) -> str:
    """证据卡主判定面：worst_side 即为判定面；both 时按契约取 conf 高者。"""
    if b.worst_side in ("top", "bottom"):
        return b.worst_side
    if b.worst_side == "both" and b.top is not None and b.bottom is not None:
        return "top" if b.top.defect_conf >= b.bottom.defect_conf else "bottom"
    return "top" if b.bottom is None else "bottom"


def _numeric_sorted(hist: dict[str, int]) -> list[str]:
    """目数/ΔE 分桶键按数值升序（"0-2" 取下界；非数值键垫底按字典序）。"""

    def key(k: str) -> tuple[int, float, str]:
        try:
            return (0, float(str(k).split("-", 1)[0]), str(k))
        except ValueError:
            return (1, 0.0, str(k))

    return sorted(hist, key=key)
