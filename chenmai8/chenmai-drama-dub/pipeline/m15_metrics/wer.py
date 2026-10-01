"""指标 3 —— 配音回听 WER（:9001 转写配音轨 vs C4 chosen 译文）。

测法（任务 T21 定案，规划 §4 M15 表行 3）：把 ``08_mix/dubbed.<lang>.wav``
整轨送 :9001 识别（目标语，do_emo 关闭、do_align 开启——字级时间戳用于
逐句切分），识别文本与 C4 每句 ``candidates[chosen].text``（按 C2 时间排序
拼接，`keep_original` 句不算——它们保留的是源语人声，与目标语转写对比
无意义）做 WER：

- 分语种口径：无空格连写（zh/ja/yue）按**字**（CER），其余按空白**词**；
- 归一：NFKC + casefold + 去标点（参考与假设同口径）；
- 主值 = 整轨 WER；明细另给按 C2 句窗的逐句 WER（服务**不带文本的**
  segments 不能做句归属——整段 text 与字级时间才有共同基准，B1 冻结规则
  7/8 同源口径；切分按 words 中点落窗，无 words 回退 segments 自带文本，
  两者皆缺如实标 unmapped）。

规划通过线 ≤0.08（报告口径，不在此门禁）。
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from pipeline import contracts as C
from pipeline.gpu_client import GpuClient
from pipeline.m15_metrics._common import (
    CallLedger,
    metric_result,
    to_mono16k,
    tokenize,
    wer_rate,
)

#: 无空格连写语种（逐句切分拼接时同 m4 口径）
_NO_SPACE_LANGS = {"zh", "yue", "ja"}

KEY = "listen_wer"
TITLE = "配音回听 WER"
#: 规划 §4 M15 通过线（报告口径）
THRESHOLD = 0.08
METHOD = (":9001 转写 08_mix/dubbed.<lang> 整轨 vs C4 chosen 译文拼接"
          "（无空格语种按字、其余按词；NFKC+casefold+去标点）")


def compute(ws: Path, lang: str, ledger: Optional[CallLedger] = None,
            *, url: Optional[str] = None,
            client: Optional[GpuClient] = None) -> dict[str, Any]:
    ledger = ledger or CallLedger()
    dubbed = _dubbed_track(ws, lang)
    if dubbed is None:
        return metric_result(KEY, TITLE, None, status="unavailable",
                             threshold=THRESHOLD, method=METHOD,
                             reason=f"配音轨缺失（08_mix/dubbed.{lang}.wav）")

    refs = _reference_rows(ws, lang)
    if not refs:
        return metric_result(KEY, TITLE, None, status="unavailable",
                             threshold=THRESHOLD, method=METHOD,
                             reason="无参考句（C4 无 chosen 译文，或全部 keep_original）")
    ref_concat = " ".join(text for _u, text, _s, _e in refs)

    cli = client or GpuClient(url, retries=3, retry_wait_s=3.0)
    with tempfile.TemporaryDirectory(prefix="m15_wer_") as td:
        try:
            wav16 = to_mono16k(dubbed, Path(td) / "dubbed16k.wav")
        except Exception as exc:
            return metric_result(KEY, TITLE, None, status="unavailable",
                                 threshold=THRESHOLD, method=METHOD,
                                 reason=f"配音轨重采样失败: {exc}")
        t = time.perf_counter()
        try:
            # do_align=true：取字级时间戳用于逐句切分（服务的 segments 不带文本，
            # 整段 text 只有 0 秒基准；字级时间才是句归属依据，见 B1 冻结规则 7/8）
            resp = cli.asr_align(wav16, lang=lang, do_align=True, do_emo=False)
        except Exception as exc:
            ledger.call("asr:9001", "listen_transcribe", time.perf_counter() - t,
                        ok=False)
            return metric_result(KEY, TITLE, None, status="unavailable",
                                 threshold=THRESHOLD, method=METHOD,
                                 reason=f":9001 转写失败: {exc}")
        ledger.call("asr:9001", "listen_transcribe", time.perf_counter() - t, ok=True)
        hyp_text = (resp.get("text") or "").strip()
        if not hyp_text:
            return metric_result(KEY, TITLE, None, status="unavailable",
                                 threshold=THRESHOLD, method=METHOD,
                                 reason=":9001 返回空转写")

    ref_tok = tokenize(ref_concat, lang)
    hyp_tok = tokenize(hyp_text, lang)
    value = wer_rate(ref_tok, hyp_tok)

    per_utt, n_mapped = _per_utt_windows(ws, lang, resp)
    detail = {
        "n_ref": len(refs),
        "ref_text": ref_concat,
        "hyp_text": hyp_text,
        "n_ref_tokens": len(ref_tok),
        "n_hyp_tokens": len(hyp_tok),
        "n_windows_mapped": n_mapped,
        "per_utt": per_utt,
        "dubbed_track": str(dubbed),
        "lang_requested": lang,
        "threshold_source": "规划 §4 M15 通过线（报告口径）",
    }
    return metric_result(KEY, TITLE, value, status="ok", threshold=THRESHOLD,
                         method=METHOD, detail=detail)


def _dubbed_track(ws: Path, lang: str) -> Optional[Path]:
    for name in (f"dubbed.{lang}.wav", "dubbed.wav"):
        p = ws / "08_mix" / name
        if p.is_file():
            return p
    return None


def _reference_rows(ws: Path, lang: str) -> list[tuple[str, str, float, float]]:
    """[(utt_id, chosen 文本, C2 起点, C2 终点)]：chosen 非空且非 keep_original，按时间序。"""
    utt_path = ws / "04_dial" / "utterances.jsonl"
    trans_path = ws / "06_mt" / "translations.jsonl"
    plan_path = ws / "07_synth" / f"synth_plan.{lang}.jsonl"
    if not utt_path.is_file() or not trans_path.is_file():
        return []
    wins = {u.utt_id: (u.start, u.end)
            for u in C.load_jsonl(utt_path, C.UtteranceTable).root}
    keep: set[str] = set()
    if plan_path.is_file():
        keep = {it.utt_id for it in C.load_jsonl(plan_path, C.SynthPlanTable).root
                if it.keep_original}
    rows: list[tuple[str, str, float, float]] = []
    for t in C.load_jsonl(trans_path, C.TranslationTable).root:
        if t.tgt != lang or t.chosen is None or t.utt_id in keep:
            continue
        if t.chosen >= len(t.candidates):
            continue
        text = (t.candidates[t.chosen].text or "").strip()
        if not text:
            continue
        s, e = wins.get(t.utt_id, (0.0, 0.0))
        rows.append((t.utt_id, text, s, e))
    rows.sort(key=lambda r: r[2])
    return rows


def _per_utt_windows(ws: Path, lang: str, resp: dict[str, Any]
                     ) -> tuple[list[dict[str, Any]], int]:
    """整轨转写按 C2 句窗切分 → 逐句 WER（参考=该句 chosen 文本）。

    句归属优先**字级时间戳**（words 中点落窗；服务 segments 不带文本，
    整段 text 与字级时间才有共同基准——B1 冻结规则 7/8 同源口径）；
    无 words 时回退 segments 自带 text 的中点归窗（桩服务/兼容形态），
    两者皆缺如实标 unmapped（主值=整轨 WER，不受影响）。
    """
    refs = _reference_rows(ws, lang)
    words = []
    for w in (resp.get("words") or []):
        try:
            words.append((str(w.get("w") or ""), float(w["s"]), float(w["e"])))
        except (KeyError, TypeError, ValueError):
            continue
    segs = []
    for s in (resp.get("segments") or []):
        try:
            segs.append((float(s["start"]), float(s["end"]), str(s.get("text") or "")))
        except (KeyError, TypeError, ValueError):
            continue
    sep = "" if (lang or "").lower() in _NO_SPACE_LANGS else " "
    out: list[dict[str, Any]] = []
    n_mapped = 0
    for utt_id, text, s0, e0 in refs:
        if words:
            hyp_text = sep.join(w for w, a, b in words if s0 <= (a + b) / 2.0 < e0).strip()
            via = "words"
        else:
            hyp_text = " ".join(
                t for a, b, t in segs if s0 <= (a + b) / 2.0 < e0).strip()
            via = "segments"
        if not hyp_text:
            out.append({"utt_id": utt_id, "wer": None, "mapped": False})
            continue
        n_mapped += 1
        out.append({
            "utt_id": utt_id,
            "wer": wer_rate(tokenize(text, lang), tokenize(hyp_text, lang)),
            "mapped": True,
            "via": via,
        })
    return out, n_mapped
