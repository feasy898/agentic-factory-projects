"""指标 1 —— 说话人相似度（声纹嵌入余弦：合成句 vs 角色音色参考）。

测法（任务 T21 定案，规划 §4 M15 表行 1）：对 C5（``07_synth/synth_plan.<lang>.jsonl``）
每个 ``keep_original=false`` 且合成 wav 与 ``voice_ref`` 参考文件都在的句子，
用 M5 同款声纹嵌入组件（``pipeline._voxdia_net.SpeakerEmbedder``，192 维、
CMN+L2）分别嵌入合成句与角色参考，余弦 = 两 L2 归一化嵌入的内积；
指标值 = 句级余弦的算术平均。规划通过线 ≥0.70（本模块只出数不门禁）。

嵌入组件与 M5 说话人聚类同源（configs/models.yaml ``voxdia`` 条目）——
M7 合成以角色参考为音色锚，本指标即"合成音色是否还像该角色"的度量。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pipeline import contracts as C
from pipeline.m15_metrics._common import CallLedger, metric_result

KEY = "speaker_similarity"
TITLE = "说话人相似度（声纹嵌入余弦）"
#: 规划 §4 M15 通过线（报告口径，不在此门禁）
THRESHOLD = 0.70
METHOD = ("voxdia 声纹嵌入（192d，CMN+L2）余弦：07_synth 合成句 wav vs "
          "C5.voice_ref 角色参考；值=句级余弦均值")


def compute(ws: Path, lang: str, ledger: Optional[CallLedger] = None) -> dict[str, Any]:
    """工作区 + 语种 → 指标结果（不出数时 status=unavailable + reason）。"""
    ledger = ledger or CallLedger()
    plan_path = ws / "07_synth" / f"synth_plan.{lang}.jsonl"
    if not plan_path.is_file():
        return metric_result(KEY, TITLE, None, status="unavailable",
                             threshold=THRESHOLD, method=METHOD,
                             reason=f"C5 缺失: {plan_path}")
    items = C.load_jsonl(plan_path, C.SynthPlanTable).root
    rows = [it for it in items if not it.keep_original]
    n_keep = len(items) - len(rows)
    if not rows:
        return metric_result(KEY, TITLE, None, status="unavailable",
                             threshold=THRESHOLD, method=METHOD,
                             reason=f"C5 无合成句（keep_original={n_keep}）",
                             detail={"n_keep_original": n_keep})

    # 嵌入器懒装载（权重在 models/voxdia，缺权重如实 unavailable）
    with ledger.stage("speaker_sim.embedder_load"):
        try:
            from pipeline._voxdia_net import SpeakerEmbedder, VoxDiaError

            embedder = SpeakerEmbedder()
        except Exception as exc:  # 权重缺失/装载失败 → 不出数
            return metric_result(KEY, TITLE, None, status="unavailable",
                                 threshold=THRESHOLD, method=METHOD,
                                 reason=f"声纹嵌入组件装载失败: {exc}",
                                 detail={"n_keep_original": n_keep})

    cache: dict[str, Any] = {}
    per_utt: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    cosines: list[float] = []
    with ledger.stage("speaker_sim.embed"):
        for it in rows:
            wav_path = _resolve(ws, it.out)
            ref_path = _resolve(ws, it.voice_ref)
            if not wav_path.is_file():
                skipped.append({"utt_id": it.utt_id, "why": f"合成 wav 缺失: {it.out}"})
                continue
            if not ref_path.is_file():
                skipped.append({"utt_id": it.utt_id, "why": f"音色参考缺失: {it.voice_ref}"})
                continue
            try:
                e_syn = _embed(embedder, wav_path, cache)
                e_ref = _embed(embedder, ref_path, cache)
            except Exception as exc:
                skipped.append({"utt_id": it.utt_id, "why": f"嵌入失败: {exc}"})
                continue
            cos = float(round(_cosine(e_syn, e_ref), 4))
            cosines.append(cos)
            per_utt.append({"utt_id": it.utt_id, "cosine": cos})

    detail: dict[str, Any] = {
        "n_total": len(items), "n_synth": len(rows), "n_keep_original": n_keep,
        "n_scored": len(cosines), "per_utt": per_utt, "skipped": skipped,
    }
    if not cosines:
        return metric_result(KEY, TITLE, None, status="unavailable",
                             threshold=THRESHOLD, method=METHOD,
                             reason="无一句可评分（合成 wav/参考缺失或嵌入失败）",
                             detail=detail)
    mean = sum(cosines) / len(cosines)
    detail.update({
        "cosine_min": round(min(cosines), 4),
        "cosine_max": round(max(cosines), 4),
        "threshold_source": "规划 §4 M15 通过线（报告口径）",
    })
    return metric_result(KEY, TITLE, mean, status="ok", threshold=THRESHOLD,
                         method=METHOD, detail=detail)


def _resolve(ws: Path, rel: str) -> Path:
    """C5 里的工作区相对路径 → 绝对（容忍绝对路径直通）。"""
    p = Path(rel)
    return p if p.is_absolute() else (ws / rel)


def _embed(embedder: Any, path: Path, cache: dict[str, Any]) -> Any:
    key = str(path)
    if key not in cache:
        cache[key] = embedder.embed_file(key)
    return cache[key]


def _cosine(a: Any, b: Any) -> float:
    import numpy as np

    va = np.asarray(a, dtype=np.float64).ravel()
    vb = np.asarray(b, dtype=np.float64).ravel()
    na, nb = float(np.linalg.norm(va)), float(np.linalg.norm(vb))
    if na <= 0 or nb <= 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))
