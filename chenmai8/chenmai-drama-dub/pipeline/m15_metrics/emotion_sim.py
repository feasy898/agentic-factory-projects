"""指标 2 —— 情绪相似度（情绪标签一致率：源句标签 vs 配音轨回判）。

测法（任务 T21 定案，规划 §4 M15 表行 2）：C2 每句的源情绪标签
（``utterances[*].emo.label``，M4 在源人声上判出）与**配音轨**上同时间窗切片
经 :9001 情绪回判（do_emo=true）标签的一致率。情绪迁移（M7 emo_ref 通道）的
目标就是"配音把源句情绪带过去"，故参考=源句标签、假设=配音回判标签；
两侧同一判别器（同一服务组件），标签空间同源可比。

服务不可达/情绪参考缺失等不出数情形如实 ``unavailable``，不静默给 0。
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from pipeline import contracts as C
from pipeline.gpu_client import GpuClient
from pipeline.m15_metrics._common import CallLedger, metric_result, slice_wav

KEY = "emotion_similarity"
TITLE = "情绪相似度（标签一致率）"
#: 规划 §4 M15 通过线（报告口径）
THRESHOLD = 0.70
#: 切片最短秒数（过短切片情绪判别无意义，如实跳过计 n_too_short）
MIN_SLICE_S = 0.25
METHOD = ("C2 源句 emo.label vs 配音轨句窗切片 :9001 回判 label 一致率"
          "（同一判别组件，标签空间同源）")


def compute(ws: Path, lang: str, ledger: Optional[CallLedger] = None,
            *, url: Optional[str] = None,
            client: Optional[GpuClient] = None) -> dict[str, Any]:
    ledger = ledger or CallLedger()
    utt_path = ws / "04_dial" / "utterances.jsonl"
    if not utt_path.is_file():
        return metric_result(KEY, TITLE, None, status="unavailable",
                             threshold=THRESHOLD, method=METHOD,
                             reason=f"C2 缺失: {utt_path}")
    utts = C.load_jsonl(utt_path, C.UtteranceTable).root

    dubbed = _dubbed_track(ws, lang)
    if dubbed is None:
        return metric_result(KEY, TITLE, None, status="unavailable",
                             threshold=THRESHOLD, method=METHOD,
                             reason=f"配音轨缺失（08_mix/dubbed.{lang}.wav）")
    cli = client or GpuClient(url, retries=3, retry_wait_s=3.0)
    keep_ids = _keep_original_ids(ws, lang)

    per_utt: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    hits = n_judged = 0
    with tempfile.TemporaryDirectory(prefix="m15_emo_") as td:
        for u in utts:
            ref = u.emo.label if u.emo is not None else None
            if not ref:
                skipped.append({"utt_id": u.utt_id, "why": "C2 无源情绪标签"})
                continue
            if (u.end - u.start) < MIN_SLICE_S:
                skipped.append({"utt_id": u.utt_id, "why": f"句窗过短(<{MIN_SLICE_S}s)"})
                continue
            try:
                sl = slice_wav(dubbed, u.start, u.end, Path(td) / f"{u.utt_id}.wav")
            except Exception as exc:
                skipped.append({"utt_id": u.utt_id, "why": f"切片失败: {exc}"})
                continue
            t = time.perf_counter()
            try:
                resp = cli.asr_align(sl, lang=lang, do_align=False, do_emo=True)
            except Exception as exc:
                ledger.call("asr:9001", "emo_rejudge", time.perf_counter() - t,
                            ok=False, note=u.utt_id)
                return metric_result(KEY, TITLE, None, status="unavailable",
                                     threshold=THRESHOLD, method=METHOD,
                                     reason=f":9001 回判失败: {exc}",
                                     detail={"n_judged": n_judged, "per_utt": per_utt})
            ledger.call("asr:9001", "emo_rejudge", time.perf_counter() - t, ok=True)
            hyp = ((resp.get("emo") or {}).get("label") or "").strip()
            if not hyp:
                skipped.append({"utt_id": u.utt_id, "why": "回判标签为空"})
                continue
            n_judged += 1
            hit = bool(hyp == ref)
            hits += int(hit)
            per_utt.append({"utt_id": u.utt_id, "ref": ref, "hyp": hyp,
                            "match": hit,
                            "keep_original": u.utt_id in keep_ids})

    detail = {"n_ref": len(utts), "n_judged": n_judged, "n_match": hits,
              "per_utt": per_utt, "skipped": skipped,
              "dubbed_track": str(dubbed)}
    if n_judged == 0:
        return metric_result(KEY, TITLE, None, status="unavailable",
                             threshold=THRESHOLD, method=METHOD,
                             reason="无可回判句（无源标签/句窗过短/回判为空）",
                             detail=detail)
    return metric_result(KEY, TITLE, hits / n_judged, status="ok",
                         threshold=THRESHOLD, method=METHOD, detail=detail)


def _dubbed_track(ws: Path, lang: str) -> Optional[Path]:
    for name in (f"dubbed.{lang}.wav", "dubbed.wav"):
        p = ws / "08_mix" / name
        if p.is_file():
            return p
    return None


def _keep_original_ids(ws: Path, lang: str) -> set[str]:
    plan_path = ws / "07_synth" / f"synth_plan.{lang}.jsonl"
    if not plan_path.is_file():
        return set()
    try:
        items = C.load_jsonl(plan_path, C.SynthPlanTable).root
    except Exception:
        return set()
    return {it.utt_id for it in items if it.keep_original}
