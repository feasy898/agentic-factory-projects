"""指标 4 —— 时长对齐率（M8 产出入窗比，实测口径）。

测法（任务 T21 定案，规划 §4 M15 表行 4）：C5（``synth_plan.<lang>.jsonl``）
每句取**实测时长**（soundfile 帧数/采样率）对照目标窗（C4 ``budget.lo/hi``，
即原句窗 ±10%；C4 缺行按 pipeline.yaml ``budget.lo_ratio/hi_ratio`` 从 C2
句窗自算，与 M8 的兜底口径一致），``lo ≤ meas ≤ hi`` 计入命中：

- ``keep_original`` 句（nonverbal/缺译文复刻原声）实测时长 = C2 句窗长
  （M9 按 [start,end) 摆放），天然在窗内，如实计入；
- 合成 wav 缺失 = 未命中并单列（不静默跳过假装全中）；
- 明细带 M8 自报的对齐率（align_report，基于 est×df/atempo 预测口径）作
  交叉参照——本指标用**实测**口径，两者差异即"计划 vs 落盘"的差距。

规划通过线 ≥0.70（自研时长可控翻译训练前）/≥0.80（训练后）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pipeline import contracts as C
from pipeline.config import load_pipeline_config
from pipeline.m15_metrics._common import CallLedger, metric_result, wav_duration
from pipeline.m6_translate import budget_for

KEY = "duration_alignment_rate"
TITLE = "时长对齐率（M8 产出入窗比）"
#: 规划 §4 M15 通过线（自研时长可控翻译训练前；报告口径）
THRESHOLD = 0.70
METHOD = ("C5 每句实测时长（soundfile）落 C4 预算窗 lo/hi（±10%）占比；"
          "keep_original 按复刻句窗长计；缺 wav 计未命中")


def compute(ws: Path, lang: str, ledger: Optional[CallLedger] = None,
            *, cfg: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    ledger = ledger or CallLedger()
    cfg = cfg if cfg is not None else load_pipeline_config()
    budget_cfg = cfg.get("budget") or {}
    lo_ratio = float(budget_cfg.get("lo_ratio", 0.9))
    hi_ratio = float(budget_cfg.get("hi_ratio", 1.1))

    plan_path = ws / "07_synth" / f"synth_plan.{lang}.jsonl"
    if not plan_path.is_file():
        return metric_result(KEY, TITLE, None, status="unavailable",
                             threshold=THRESHOLD, method=METHOD,
                             reason=f"C5 缺失: {plan_path}")
    items = C.load_jsonl(plan_path, C.SynthPlanTable).root
    if not items:
        return metric_result(KEY, TITLE, None, status="unavailable",
                             threshold=THRESHOLD, method=METHOD, reason="C5 为空")

    utt_path = ws / "04_dial" / "utterances.jsonl"
    utts = ({u.utt_id: u for u in C.load_jsonl(utt_path, C.UtteranceTable).root}
            if utt_path.is_file() else {})
    budgets: dict[str, C.Budget] = {}
    trans_path = ws / "06_mt" / "translations.jsonl"
    if trans_path.is_file():
        for t in C.load_jsonl(trans_path, C.TranslationTable).root:
            if t.tgt == lang:
                budgets[t.utt_id] = t.budget

    per_utt: list[dict[str, Any]] = []
    missing_wav: list[str] = []
    no_window: list[str] = []
    n_in = 0
    with ledger.stage("dur_align.measure"):
        for it in items:
            u = utts.get(it.utt_id)
            budget = budgets.get(it.utt_id)
            if budget is not None:
                lo, hi = float(budget.lo), float(budget.hi)
            elif u is not None:
                b = budget_for(u, lo_ratio, hi_ratio)
                lo, hi = float(b.lo), float(b.hi)
            else:
                per_utt.append({"utt_id": it.utt_id, "in_window": None,
                                "why": "无 C2 句窗且无 C4 预算，无法定窗"})
                no_window.append(it.utt_id)
                continue
            if it.keep_original:
                meas = round(u.end - u.start, 3) if u is not None else None
                src = "keep_original(C2 句窗)"
            else:
                wav = Path(it.out)
                wav = wav if wav.is_absolute() else (ws / it.out)
                if not wav.is_file():
                    per_utt.append({"utt_id": it.utt_id, "in_window": False,
                                    "meas_dur": None, "window": [lo, hi],
                                    "why": f"合成 wav 缺失: {it.out}"})
                    missing_wav.append(it.utt_id)
                    continue
                meas = wav_duration(wav)
                src = "wav 实测"
            in_win = bool(meas is not None and lo <= meas <= hi)
            n_in += int(in_win)
            per_utt.append({"utt_id": it.utt_id, "meas_dur": meas,
                            "window": [lo, hi], "in_window": in_win, "src": src})

    n_total = len(items)
    m8_rate = _m8_report_rate(ws, lang)
    detail = {
        "n_total": n_total, "n_in_window": n_in,
        "n_missing_wav": len(missing_wav), "missing_wav": missing_wav,
        "n_no_window": len(no_window), "no_window": no_window,
        "per_utt": per_utt,
        "window_semantics": "C4 budget.lo/hi（原句窗 ±10%；C4 缺行按 C2 窗×ratio 自算）",
        "m8_report_alignment_rate_pred": m8_rate,
        "threshold_source": "规划 §4 M15 通过线（自研时长可控翻译训练前；报告口径）",
    }
    return metric_result(KEY, TITLE, n_in / n_total, status="ok",
                         threshold=THRESHOLD, method=METHOD, detail=detail)


def _m8_report_rate(ws: Path, lang: str) -> Optional[float]:
    report = ws / "07_synth" / f"align_report.{lang}.json"
    if not report.is_file():
        return None
    try:
        import json

        data = json.loads(report.read_text(encoding="utf-8"))
        rate = (data.get("summary") or {}).get("alignment_rate")
        return float(rate) if rate is not None else None
    except (OSError, ValueError):
        return None
