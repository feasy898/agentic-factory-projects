"""指标 5 —— 口型评分（口型区帧差活性 vs 人声能量相关性）。

测法（任务 T21 定案）：对成片（优先 ``09_lip/done/<ep>.<lang>.lip.mp4``，
缺则 ``12_out/<ep>.<lang>.mp4``）逐帧计算**口型区**灰度帧差的平均绝对值
（口型区 = C2 ``face.bbox`` 下半 45%，与 M10 嘴区口径同源；无脸句回退
画面下中区域并如实标注），同时从配音轨（``08_mix/dubbed.<lang>.wav``）
取每帧区间的 RMS 能量包络，两序列做 **Pearson 相关**：

- 只在 C2 句窗内的相邻帧对参与计算（句间静默段不计）；
- 主值 = 逐句中心化后池化的 Pearson r（消除不同句口型区亮度基准差异）；
  明细给逐句 r；
- r 越高 = 嘴动与语音能量越同步（配音-口型一致性的代理度量）。

基线 v0：该代理口径为本任务首测（规划原表行的 LSE-C 线依赖口型引擎自带
判别权重，T21 以帧差活性×人声能量相关性替代），无历史基准，通过线记
``null``，首测值即基线 v0（metrics.json 顶层 ``baseline`` 同步标注）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import numpy as np

from pipeline import contracts as C
from pipeline.m15_metrics._common import CallLedger, metric_result, pearson, read_mono

KEY = "lip_score"
TITLE = "口型评分（口型区帧差活性 vs 人声能量相关性）"
#: 基线 v0：无历史基准 → threshold 记 None（首测值即基线）
THRESHOLD: Optional[float] = None
#: 无 C2 人脸框时的回退口型区（画面比例：下中区域）
FALLBACK_REGION = (0.25, 0.55, 0.75, 0.85)  # (x0r, y0r, x1r, y1r)
METHOD = ("Pearson r：口型区（C2 face.bbox 下半 45%，缺则下中回退区）灰度帧差"
          "活性 vs 配音轨帧区间 RMS 能量；仅 C2 句窗内相邻帧对参与")


def compute(ws: Path, lang: str, ep: str, ledger: Optional[CallLedger] = None,
            *, video: Optional[Path] = None,
            audio: Optional[Path] = None) -> dict[str, Any]:
    ledger = ledger or CallLedger()
    utt_path = ws / "04_dial" / "utterances.jsonl"
    if not utt_path.is_file():
        return metric_result(KEY, TITLE, None, status="unavailable",
                             threshold=THRESHOLD, method=METHOD,
                             reason=f"C2 缺失: {utt_path}")
    utts = C.load_jsonl(utt_path, C.UtteranceTable).root

    vid = _resolve_video(ws, ep, lang, video)
    if vid is None:
        return metric_result(KEY, TITLE, None, status="unavailable",
                             threshold=THRESHOLD, method=METHOD,
                             reason="无成片视频（09_lip/done 与 12_out 均缺）")
    aud = _resolve_audio(ws, lang, audio)
    if aud is None:
        return metric_result(KEY, TITLE, None, status="unavailable",
                             threshold=THRESHOLD, method=METHOD,
                             reason="无配音轨（08_mix/dubbed.<lang>.wav）")

    windows = [(u.start, u.end) for u in utts]
    bboxes: dict[int, list[int]] = {}
    for i, u in enumerate(utts):
        if u.face is not None and u.face.bbox:
            bboxes[i] = list(u.face.bbox)
    # 评价窗：有人脸框的句逐句用其框；全片无框时退化为全部句 + 画面下中回退区
    if bboxes:
        eval_idx = sorted(bboxes)
        region_source = "C2 face.bbox 下半 45%"
    else:
        eval_idx = list(range(len(utts)))
        region_source = "下中回退区（无 C2 人脸框，全句窗参与）"
    eval_windows = [windows[i] for i in eval_idx]
    eval_boxes = {k: bboxes[i] for k, i in enumerate(eval_idx) if i in bboxes}

    with ledger.stage("lip_score.frames"):
        try:
            per_utt_series = _scan(vid, aud, eval_windows, eval_boxes)
        except Exception as exc:
            return metric_result(KEY, TITLE, None, status="unavailable",
                                 threshold=THRESHOLD, method=METHOD,
                                 reason=f"视频/音频序列提取失败: {exc}",
                                 detail={"video": str(vid), "audio": str(aud)})
    # 池化主值：逐句段内去均值后拼接（消除不同句口型区亮度基准/能量台差异）
    acts, energies = [], []
    for wi in sorted(per_utt_series):
        a, e = per_utt_series[wi]
        if a.size >= 2:
            acts.append(a - a.mean())
            energies.append(e - e.mean())
    if not acts:
        return metric_result(KEY, TITLE, None, status="unavailable",
                             threshold=THRESHOLD, method=METHOD,
                             reason="句窗内可评帧对不足 2（句窗过短或视频帧数不足）",
                             detail={"video": str(vid)})
    act = np.concatenate(acts)
    energy = np.concatenate(energies)
    value = pearson(act, energy)
    per_utt = [
        {"utt_id": utts[eval_idx[wi]].utt_id,
         "r": (pearson(a, e) if a.size >= 2 else None),
         "n": int(a.size)}
        for wi, (a, e) in sorted(per_utt_series.items())
    ]
    detail = {
        "video": str(vid), "audio": str(aud),
        "region_source": region_source,
        "fallback_region_ratio": (None if bboxes else list(FALLBACK_REGION)),
        "n_frames_eval": int(act.shape[0]),
        "activity_mean": round(float(np.mean(act)), 6) if act.shape[0] else None,
        "energy_mean": round(float(np.mean(energy)), 6) if energy.shape[0] else None,
        "per_utt": per_utt,
        "baseline": "v0（代理口径首测，无历史基准；规划原表行判别器线不适用）",
    }
    return metric_result(KEY, TITLE, value, status="ok", threshold=THRESHOLD,
                         method=METHOD, detail=detail)


# ---------------------------------------------------------------------------
# 序列提取
# ---------------------------------------------------------------------------

def mouth_box(bbox: Optional[list[int]], width: int, height: int) -> tuple[int, int, int, int]:
    """口型区像素框：有人脸框取其下半 45%（与 M10 嘴区同式）；否则回退区。"""
    if bbox and len(bbox) == 4:
        x0, y0, x1, y1 = bbox
        h = max(1, y1 - y0)
        return (int(x0), int(y0 + h * 0.55), int(x1), int(y1))
    return (int(width * FALLBACK_REGION[0]), int(height * FALLBACK_REGION[1]),
            int(width * FALLBACK_REGION[2]), int(height * FALLBACK_REGION[3]))


def _scan(vid: Path, aud: Path, windows: list[tuple[float, float]],
          bboxes: dict[int, list[int]]) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    """单次解码扫描：句窗内相邻帧对的口型区帧差活性 + 同帧区间配音 RMS。

    帧归属句 = 帧起点 t=i/fps 落入的 C2 句窗；口型区取该句的框。
    返回 {句下标: (activity[n], energy[n])}（原始序列，未中心化）。
    """
    import cv2

    wav, sr = read_mono(aud)
    cap = cv2.VideoCapture(str(vid))
    if not cap.isOpened():
        raise RuntimeError(f"VideoCapture 打不开: {vid}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps <= 0:
        cap.release()
        raise RuntimeError(f"视频 fps 无效: {fps}")

    def win_of(t: float) -> Optional[int]:
        for i, (s, e) in enumerate(windows):
            if s <= t < e:
                return i
        return None

    seg_act: dict[int, list[float]] = {}
    seg_energy: dict[int, list[float]] = {}
    prev_gray: Optional[np.ndarray] = None
    prev_idx: Optional[int] = None
    fi = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t = fi / fps
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            wi = win_of(t)
            if prev_gray is not None and wi is not None and wi == prev_idx:
                h, w = gray.shape[:2]
                x0, y0, x1, y1 = mouth_box(bboxes.get(wi), w, h)
                x0, y0 = max(0, x0), max(0, y0)
                x1, y1 = min(w, x1), min(h, y1)
                if x1 > x0 + 1 and y1 > y0 + 1:
                    diff = cv2.absdiff(gray[y0:y1, x0:x1], prev_gray[y0:y1, x0:x1])
                    seg_act.setdefault(wi, []).append(
                        float(diff.astype(np.float32).mean()))
                    seg_energy.setdefault(wi, []).append(
                        _rms_interval(wav, sr, t - 1.0 / fps, t))
            prev_gray = gray
            prev_idx = wi
            fi += 1
    finally:
        cap.release()
    acts: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for wi in sorted(seg_act):
        acts[wi] = (np.asarray(seg_act[wi], dtype=np.float64),
                    np.asarray(seg_energy[wi], dtype=np.float64))
    return acts


def _rms_interval(wav: np.ndarray, sr: int, t0: float, t1: float) -> float:
    i0 = max(0, int(round(t0 * sr)))
    i1 = max(i0 + 1, min(wav.shape[0], int(round(t1 * sr))))
    seg = wav[i0:i1]
    return float(np.sqrt(np.mean(seg ** 2) + 1e-12))


def _resolve_video(ws: Path, ep: str, lang: str, video: Optional[Path]) -> Optional[Path]:
    if video is not None:
        return video if video.is_file() else None
    for rel in (f"09_lip/done/{ep}.{lang}.lip.mp4", f"12_out/{ep}.{lang}.mp4"):
        p = ws / rel
        if p.is_file():
            return p
    return None


def _resolve_audio(ws: Path, lang: str, audio: Optional[Path]) -> Optional[Path]:
    if audio is not None:
        return audio if audio.is_file() else None
    for name in (f"dubbed.{lang}.wav", "dubbed.wav", f"mix.{lang}.wav"):
        p = ws / "08_mix" / name
        if p.is_file():
            return p
    return None
