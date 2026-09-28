"""M5 镜头切分 + 说话人区分 + 主动说话人 + 正脸近景判定（规划 §4 M5）。

职责（只读写 02_shots/ 与 04_dial/ 两层 + 05_cast 音色库；跨层交换只经冻结契约）：
  1. 镜头切分（shot-cut 组件，本机 CPU）：视频逐帧 48x27 RGB → 单帧转场概率
     → 转场点（阈值 ``--shot-threshold`` 默认 0.5，最小镜头长守卫）→ 契约 C1
     ``02_shots/shots.json``（``faces`` = 镜头内最大并发人脸数）；
  2. 人脸/正脸近景判定（facemesh 组件，本机 CPU）：按 ``--face-step`` 采样帧，
     人脸网格 478 点 + 头部姿态（几何代理 ∨ 矩阵欧拉，阈值取 configs/pipeline.yaml
     ``lip`` 段：偏航/俯仰 ±25°）→ 正脸；人脸框高 ≥ 画幅 1/4 → 近景；IoU 贪心
     关联成轨迹 → ``02_shots/frontal_closeups.json``（正脸近景镜头表，M5 模块级
     报告 —— C1 schema 冻结不含正脸字段，故独立落盘）；
  3. 说话人嵌入聚类（voxdia 组件，本机 CPU）：说话段窗口（B1 冻结规则 10：
     窗口切分归 M4/VAD，本模块不重切；无 ``diar.jsonl`` 时能量 VAD 兜底）→
     每窗 16k 人声切片嵌入（192 维，CMN + L2）→ 余弦亲和谱聚类（说话人数
     由特征值间隙估计，upper-bound = 角色数+1，plan §4 M5 ②）→ 回填
     ``04_dial/diar.jsonl``（C2-pre 段级 schema：仅 start/end/speaker）；
  4. 主动说话人（actspk MVP 口径）：轨迹嘴部开合运动在段窗内打分；单轨迹
     直接绑定，多轨迹取嘴动最大者（模型化 ASD 集成见 models.yaml actspk 条目）；
  5. 回填 C2 ``04_dial/utterances.jsonl``（utt_id 替换原子写）：``speaker``/
     ``char_id``（05_cast/speaker_map.json 绑定表）/``overlap``/``face``
     （正脸近景判定 + 框）；
  6. voicebank 管理子命令（每剧音色库）：见 ``voice`` 子命令帮助。

CLI（规划 §4 M5 冻结形态 + voicebank 子命令）::

    python -m pipeline.m5_diar --ep ep01
    python -m pipeline.m5_diar --ep ep01 --jobs-dir <dir> --no-video
    python -m pipeline.m5_diar voice add --cast ep01 --char char_nan --wav ref.wav
    python -m pipeline.m5_diar voice list [--cast ep01]
    python -m pipeline.m5_diar voice bind --cast ep01 --spk spk0 --char char_nan [--ep ep01]

退出码：0 成功；1 输入/组件/契约校验错误；2 用法错误。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np
import soundfile as sf
import yaml
from pydantic import ValidationError

from pipeline import contracts as C
from pipeline._facemesh_face import (
    FaceScanner,
    FaceTrack,
    build_tracks,
    decide_closeup,
    decide_frontal,
    estimate_head_pose,
)
from pipeline._scdet_net import ScDetError, load_scdet_net, predict_scene_frames
from pipeline._voxdia_net import SpeakerEmbedder, VoxDiaError
from pipeline.config import load_pipeline_config
from pipeline.m1_ingest import ffprobe_json
from pipeline.scaffold import create_workspace, ep_dir

__all__ = ["run", "main", "DiarError", "energy_vad_windows", "cluster_speakers",
           "detect_shots", "scan_face_tracks", "label_windows", "build_face_fact",
           "voice_register", "voice_list", "voice_bind"]

#: 能量 VAD 兜底切分参数（16k 口径）
_VAD_FRAME_S = 0.025
_VAD_HOP_S = 0.010
_VAD_MERGE_GAP_S = 0.30   # 相邻有声帧间隙 ≤ 此值则桥接
_VAD_MIN_SEG_S = 0.40     # 最短说话段（过短嵌入无意义，标 unknown）
#: 嵌入聚类参数
_MIN_EMBED_SIM = 0.30     # 平均余弦低于此值判全 unknown（无可分说话人）
#: 轨迹绑定 C2 的窗口重叠下限
_TRACK_OVERLAP_MIN = 0.5
#: 正脸近景镜头表 schema（模块级报告，非冻结契约）
_FACES_SCHEMA_VERSION = 1


class DiarError(RuntimeError):
    """M5 执行错误（输入缺失/组件失败/校验不过）。"""


# ---------------------------------------------------------------------------
# 时间轴与输入
# ---------------------------------------------------------------------------

def _audio_duration(wav_path: Path) -> float:
    info = sf.info(str(wav_path))
    return float(info.frames) / float(info.samplerate)


def _load_mono16k(wav_path: Path) -> tuple[np.ndarray, int]:
    data, sr = sf.read(str(wav_path), dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if sr != 16000:
        import librosa

        mono = librosa.resample(mono, orig_sr=sr, target_sr=16000)
        sr = 16000
    return mono.astype(np.float32), sr


# ---------------------------------------------------------------------------
# 能量 VAD 兜底切分（diar.jsonl 缺席时；B1 冻结规则 10：窗口切分归 M4/VAD）
# ---------------------------------------------------------------------------

def energy_vad_windows(mono: np.ndarray, sr: int = 16000) -> list[tuple[float, float]]:
    """RMS 能量 VAD：帧平方均值 → 双侧阈值（p20 噪底 +10dB 与 p95-25dB 取大）
    → 桥接短间隙 → 丢弃过短段。返回 [(start_s, end_s), ...] 按时间排序。"""
    n_frame = int(_VAD_FRAME_S * sr)
    n_hop = int(_VAD_HOP_S * sr)
    if mono.shape[0] < n_frame:
        return []
    frames = np.lib.stride_tricks.sliding_window_view(mono, n_frame)[::n_hop]
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1)) + 1e-12
    rms_db = 20.0 * np.log10(rms)
    p20, p95 = float(np.percentile(rms_db, 20)), float(np.percentile(rms_db, 95))
    thr_db = max(p20 + 10.0, p95 - 25.0)
    voiced = rms_db > thr_db

    windows: list[tuple[float, float]] = []
    start = None
    last_voice = -1
    for i, v in enumerate(voiced):
        if v:
            if start is None:
                start = i
            last_voice = i
        elif start is not None and (i - last_voice) * _VAD_HOP_S > _VAD_MERGE_GAP_S:
            windows.append((start * _VAD_HOP_S, (last_voice + 1) * _VAD_HOP_S + _VAD_FRAME_S))
            start = None
    if start is not None:
        windows.append((start * _VAD_HOP_S, (last_voice + 1) * _VAD_HOP_S + _VAD_FRAME_S))
    dur = mono.shape[0] / sr
    merged = [(max(0.0, s), min(dur, e)) for s, e in windows if e - s >= _VAD_MIN_SEG_S]
    return [(round(s, 3), round(e, 3)) for s, e in merged]


# ---------------------------------------------------------------------------
# 说话人嵌入 + 谱聚类
# ---------------------------------------------------------------------------

def cluster_speakers(embeddings: np.ndarray, *, max_speakers: int = 4,
                     min_avg_sim: float = _MIN_EMBED_SIM) -> tuple[np.ndarray, dict]:
    """余弦亲和谱聚类。返回 (labels, info)。

    说话人数估计（plan §4 M5 ②：上限 = 角色数+1，由调用方给 max_speakers）：
    kNN 稀疏图（每点保留 top-k 近邻，k=⌈√n⌉−1）→ 对称归一拉普拉斯特征值间隙
    （近全连通稠密图上间隙失效 —— 簇内/簇间余弦同为正锥高位，T7 实测
    λ0≈0.9995 吞掉全部结构；稀疏化后簇结构呈近似不连通分量，间隙干净）。
    k* 截到 [1, max_speakers]。嵌入过近（平均余弦 < min_avg_sim）时全部标 -1。
    """
    n = embeddings.shape[0]
    if n == 0:
        return np.zeros(0, dtype=int), {"n_speakers": 0}
    if n == 1:
        return np.zeros(1, dtype=int), {"n_speakers": 1, "method": "single"}

    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    unit = embeddings / np.maximum(norms, 1e-9)
    sim = unit @ unit.T
    np.fill_diagonal(sim, 1.0)
    upper = sim[np.triu_indices(n, k=1)]
    avg_sim = float(upper.mean())
    info: dict[str, Any] = {"avg_cos": round(avg_sim, 4)}
    if avg_sim < min_avg_sim:
        info.update({"n_speakers": 0, "method": "below-min-avg-sim"})
        return np.full(n, -1, dtype=int), info

    k_cap = min(max_speakers, n)
    k = _estimate_n_speakers(sim, k_cap=k_cap)
    info["n_speakers_est"] = k

    if k <= 1:
        info["n_speakers"] = 1
        return np.zeros(n, dtype=int), info

    from sklearn.cluster import SpectralClustering

    sc = SpectralClustering(n_clusters=k, affinity="precomputed",
                            assign_labels="kmeans", random_state=0)
    labels = sc.fit_predict(sim)
    info["n_speakers"] = int(len(set(labels.tolist())))
    return labels.astype(int), info


def _estimate_n_speakers(sim: np.ndarray, *, k_cap: int) -> int:
    """kNN 稀疏图上的特征值间隙估说话人数（细节见 :func:`cluster_speakers`）。"""
    from scipy.linalg import eigh

    n = sim.shape[0]
    if n <= 2 or k_cap <= 1:
        return 1 if n else 0
    knn = max(2, min(int(np.ceil(np.sqrt(n))) - 1, n - 2))
    sparse = np.zeros_like(sim)
    sim_nodiag = sim.copy()
    np.fill_diagonal(sim_nodiag, -2.0)  # 邻居选择排除自身
    for i in range(n):
        idx = np.argsort(sim_nodiag[i])[::-1][:knn]
        sparse[i, idx] = sim[i, idx]
    sparse = np.maximum(sparse, sparse.T)  # 对称化
    np.fill_diagonal(sparse, 0.0)
    deg = sparse.sum(axis=1)
    deg[deg <= 1e-12] = 1e-12
    d_inv_sqrt = 1.0 / np.sqrt(deg)
    lap = np.eye(n) - (sparse * d_inv_sqrt[:, None]) * d_inv_sqrt[None, :]
    evals = eigh(lap, subset_by_index=[0, min(k_cap, n - 1)],
                 eigvals_only=True)  # 升序
    gaps = evals[1:] - evals[0:-1]  # 升序谱的后向间隙
    k = int(np.argmax(gaps)) + 1
    return max(1, min(k, k_cap))


def label_windows(windows: list[tuple[float, float]], embeddings: np.ndarray,
                  *, max_speakers: int) -> tuple[list[str], dict]:
    """簇标签 → 说话人名（spk0.. 按首次出现时间排序）；-1 → unknown。"""
    labels, info = cluster_speakers(embeddings, max_speakers=max_speakers)
    order: list[int] = []
    for lab, (s, _e) in sorted(zip(labels.tolist(), windows), key=lambda x: x[1][0]):
        if lab >= 0 and lab not in order:
            order.append(lab)
    names = {lab: f"spk{i}" for i, lab in enumerate(order)}
    speakers = [names.get(int(lab), "unknown") for lab in labels.tolist()]
    info["speaker_order"] = [names[i] for i in order]
    return speakers, info


# ---------------------------------------------------------------------------
# 镜头切分（shot-cut）
# ---------------------------------------------------------------------------

def _iter_video_frames_resized(video: Path, size: tuple[int, int] = (48, 27)):
    """顺序解码视频 → uint8 RGB 帧（48x27，shot-cut 输入口径）。"""
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise DiarError(f"视频打不开: {video}")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            small = cv2.resize(rgb, size, interpolation=cv2.INTER_AREA)
            yield small
    finally:
        cap.release()


def detect_shots(video: Path, *, fps: float, threshold: float = 0.5,
                 min_shot_s: float = 0.8) -> tuple[list[dict], np.ndarray, float]:
    """shot-cut 推理 → (镜头列表 dict, 每帧转场概率, 视频时长 s)。

    转场点 = 概率局部峰且 > threshold；镜头最短 ``min_shot_s``（把过短镜头
    并入前一镜）。镜头列表元素 {shot_id,start,end,cut}（faces 由人脸扫描回填）。
    """
    frames = np.stack(list(_iter_video_frames_resized(video)))  # [T, 27, 48, 3]
    if frames.shape[0] == 0:
        raise DiarError(f"视频无帧: {video}")
    import torch

    net = load_scdet_net()
    if torch.get_num_threads() > 16:
        torch.set_num_threads(16)
    probs = predict_scene_frames(net, torch.from_numpy(frames))
    total = frames.shape[0] / fps

    cuts = [float(i) / fps for i in range(1, probs.shape[0] - 1)
            if probs[i] > threshold and probs[i] >= probs[i - 1]
            and probs[i] >= probs[i + 1]]
    # 最小镜头长守卫：相邻转场间隔不足则保留概率更高者
    kept: list[float] = []
    for c in cuts:
        if kept and c - kept[-1] < min_shot_s:
            continue
        kept.append(c)
    bounds = [0.0] + kept + [total]
    shots = []
    for i, (s, e) in enumerate(zip(bounds, bounds[1:])):
        if e - s <= 1e-3:
            continue
        shots.append({"shot_id": f"s{i:04d}", "start": round(float(s), 3),
                      "end": round(float(e), 3),
                      "cut": "hard" if i > 0 else "hard"})
    return shots, probs, total


# ---------------------------------------------------------------------------
# 人脸扫描（facemesh）
# ---------------------------------------------------------------------------

def _frame_count(video: Path) -> int:
    cap = cv2.VideoCapture(str(video))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return n


def scan_face_tracks(video: Path, *, fps: float, face_step_s: float,
                     frontal_yaw_deg: float, min_face_height_ratio: float
                     ) -> tuple[list[FaceTrack], list[FaceTrack], dict]:
    """采样扫描人脸 → (全轨迹列表, 每镜头代表轨迹聚合留空占位, 计时信息)。

    轨迹 frontal/closeup 取多数票（frontal_ratio/closeup_ratio ≥ 0.5）。
    """
    step = max(1, int(round(face_step_s * fps)))
    scanner = FaceScanner(frontal_yaw_deg=frontal_yaw_deg,
                          min_face_height_ratio=min_face_height_ratio)
    observations = []
    cap = cv2.VideoCapture(str(video))
    idx, t0 = 0, time.perf_counter()
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % step == 0:
                observations.extend(scanner.observe_frame(frame, idx / fps))
            idx += 1
    finally:
        cap.release()
        scanner.close()
    tracks = build_tracks(observations)
    info = {"frames": idx, "sampled": len(range(0, idx, step)),
            "n_obs": len(observations), "n_tracks": len(tracks),
            "scan_s": round(time.perf_counter() - t0, 2)}
    return tracks, info


def _track_overlaps(tr: FaceTrack, s: float, e: float) -> float:
    """轨迹对窗口 [s,e] 的**窗口覆盖率**：轨迹时间跨度与窗口的交 / 窗长。

    （语义=「说话窗内该轨迹在画多久」；不是轨迹自身被窗口覆盖的比例 ——
    轨迹常跨句+间隙延伸，按轨迹长度归一会漏绑，T7 实测。）"""
    if not tr.obs:
        return 0.0
    t0, t1 = tr.t_span
    inter = min(e, t1) - max(s, t0)
    if inter <= 0:
        return 0.0
    inside = sum(1 for o in tr.obs if s - 1e-6 <= o.t <= e + 1e-6)
    if inside == 0:
        return 0.0
    return min(1.0, inter / max(e - s, 1e-6))


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def _shotsheet_from(shots: list[dict], ep: str, fps: int, dur: float) -> C.ShotSheet:
    return C.ShotSheet(ep=ep, fps=fps, dur=round(float(dur), 3),
                       shots=[C.Shot(shot_id=s["shot_id"], start=s["start"],
                                     end=s["end"], cut=s["cut"],
                                     faces=s.get("faces", 0)) for s in shots])


def _covering_shot(t: float, shots: list[dict]) -> Optional[dict]:
    """时刻 t 所在镜头（末镜闭区间兜底；无镜头返回 None）。"""
    for s in shots:
        if s["start"] - 1e-6 <= t < s["end"] - 1e-6:
            return s
    if shots and abs(t - shots[-1]["end"]) <= 1e-3:
        return shots[-1]
    return None


def build_face_fact(track: FaceTrack, win: tuple[float, float],
                    frame_size: tuple[int, int]) -> Optional[C.FaceFact]:
    """说话段窗 → C2 FaceFact（多数票判定 + 中位框；无覆盖轨迹返回 None）。

    actspk（主动说话人）语义：调用方已把「在说话」的轨迹排在前（嘴动打分），
    本函数只取首个满足覆盖率的轨迹；多脸画面由 ``ranked_tracks`` 排序决定。
    """
    if not track.obs:
        return None
    if _track_overlaps(track, win[0], win[1]) < _TRACK_OVERLAP_MIN:
        return None
    frontal_ratio = track.frontal_ratio()
    closeup_ratio = track.closeup_ratio()
    bbox = track.median_bbox()
    # 框夹取进画面
    x0, y0, x1, y1 = bbox
    w, h = frame_size
    bbox = [int(max(0, x0)), int(max(0, y0)), int(min(w - 1, x1)), int(min(h - 1, y1))]
    return C.FaceFact(frontal=bool(frontal_ratio >= 0.5),
                      closeup=bool(closeup_ratio >= 0.5), bbox=bbox)


def _voices_cast(cfg: dict, cast_id: str) -> dict:
    voices_path = Path(cfg.get("_voices_path")
                       or (Path(__file__).resolve().parents[1] / "configs" / "voices.yaml"))
    doc = yaml.safe_load(voices_path.read_text(encoding="utf-8")) or {}
    cast = ((doc.get("casts") or {}).get(cast_id) or {}).get("characters") or {}
    return cast


def run(ep: str, *, jobs_dir: str | Path | None = None, audio: Path | None = None,
        video: Path | None = None, max_speakers: int | None = None,
        shot_threshold: float = 0.5, face_step_s: float = 0.4,
        no_video: bool = False, cfg: dict | None = None) -> dict[str, Any]:
    """M5 主流程。返回摘要 dict（同时打印由 CLI 层负责）。"""
    cfg = cfg if cfg is not None else load_pipeline_config()
    root = Path(jobs_dir) if jobs_dir else Path(cfg["paths"]["jobs_dir"])
    create_workspace(ep, root)  # 幂等：本模块要写 02_shots/04_dial/05_cast（m1 同款）
    ws = ep_dir(ep, root)
    dial = ws / "04_dial"
    shots_dir = ws / "02_shots"
    cast_dir = ws / "05_cast"

    # ---- 输入定位：音频（B1 同源：优先 M3 人声；缺则混音口径并如实记录）----
    vocals = dial / "vocals.wav"
    mix16 = ws / "01_media" / "audio_16k.wav"
    wav = Path(audio) if audio else (vocals if vocals.is_file() else mix16)
    if not wav.is_file():
        raise DiarError(
            f"音频输入不存在: 依次尝试 {vocals}（M3 人声）与 {mix16}（混音），"
            "或 --audio 显式指定")

    # ---- ① 说话段窗口：M4 预分段（diar.jsonl）优先，能量 VAD 兜底 ----
    diar_path = dial / "diar.jsonl"
    vad_source = "energy_vad"
    windows: list[tuple[float, float]] = []
    if diar_path.is_file():
        existing = [r.model_dump() for r in C.load_jsonl(diar_path, C.DiarTable).root]
        windows = [(float(r["start"]), float(r["end"])) for r in existing]
        windows.sort()
        if windows:
            vad_source = "m4_diar_windows"
    if not windows:
        mono, _sr = _load_mono16k(wav)
        windows = energy_vad_windows(mono)
    if not windows:
        raise DiarError("无说话段：diar.jsonl 缺席且能量 VAD 未检出语音段")

    # ---- ② 说话人嵌入聚类（voxdia，本机 CPU）----
    t_emb = time.perf_counter()
    embedder = SpeakerEmbedder()
    mono, sr = _load_mono16k(wav)
    embeddings = np.zeros((len(windows), embedder.dim), dtype=np.float32)
    for i, (s, e) in enumerate(windows):
        i0, i1 = int(s * sr), int(e * sr)
        if i1 - i0 < sr // 10:
            continue  # <0.1s 无法嵌入 → 保持零向量 → unknown
        embeddings[i] = embedder.embed_waveform(
            torch_from(mono[i0:i1])).cpu().numpy()
    if max_speakers is None:
        cast = _voices_cast(cfg, ep)
        max_speakers = max(1, len(cast) + 1) if cast else 4
    speakers, cluster_info = label_windows(windows, embeddings, max_speakers=max_speakers)
    emb_s = round(time.perf_counter() - t_emb, 2)

    # ---- ③ diar.jsonl 回填（C2-pre；窗口不重切，仅补 speaker）----
    diar_rows = [C.DiarSegment(start=round(s, 3), end=round(e, 3), speaker=spk)
                 for (s, e), spk in zip(windows, speakers)]
    C.dump_jsonl(diar_path, C.DiarTable.model_validate(
        sorted([r.model_dump() for r in diar_rows], key=lambda r: r["start"])))

    # ---- ④⑤ 镜头 + 人脸（无视频或 --no-video 时跳过，产物如实缺省）----
    tracks: list[FaceTrack] = []
    media_dir = ws / "01_media"
    vid = Path(video) if video else (media_dir / "video_1080x1920_25fps.mp4")
    face_reports: dict[str, Any] = {"schema_version": _FACES_SCHEMA_VERSION, "ep": ep,
                                    "shots": []}
    frame_size = (int(cfg.get("media", {}).get("width", 1080)),
                  int(cfg.get("media", {}).get("height", 1920)))
    lip_cfg = cfg.get("lip") or {}
    frontal_deg = float(lip_cfg.get("frontal_yaw_deg", 25.0))
    close_ratio = float(lip_cfg.get("min_face_height_ratio", 0.25))
    n_shots = 0
    if no_video or not vid.is_file():
        shots = []
    else:
        probe = ffprobe_json(vid)
        vstream = next((s for s in probe.get("streams", [])
                        if s.get("codec_type") == "video"), None)
        fps_num, _, fps_den = str(vstream.get("r_frame_rate", "25/1")).partition("/")
        fps = float(fps_num) / float(fps_den or 1)
        frame_size = (int(vstream["width"]), int(vstream["height"]))

        t_shot = time.perf_counter()
        shots, probs, total = detect_shots(vid, fps=fps, threshold=shot_threshold)
        shot_s = round(time.perf_counter() - t_shot, 2)

        tracks, face_info = scan_face_tracks(
            vid, fps=fps, face_step_s=face_step_s,
            frontal_yaw_deg=frontal_deg, min_face_height_ratio=close_ratio)

        # 镜头聚合：faces=镜头内最大并发脸数；轨迹按时间归属镜头
        for s in shots:
            inside = [tr for tr in tracks
                      if sum(1 for o in tr.obs
                             if s["start"] <= o.t < s["end"]) >= max(1, len(tr.obs) // 2)]
            max_conc = 0
            for tr in tracks:
                max_conc = max(max_conc, sum(1 for o in tr.obs
                                             if s["start"] <= o.t < s["end"]))
            s["faces"] = max_conc
            s["tracks"] = inside
        n_shots = len(shots)

        face_reports["shots"] = [{
            "shot_id": s["shot_id"], "start": s["start"], "end": s["end"],
            "faces": s["faces"],
            "frontal": bool(any(t.frontal_ratio() >= 0.5 for t in s["tracks"])),
            "closeup": bool(any(t.closeup_ratio() >= 0.5 for t in s["tracks"])),
            "tracks": [{
                "track_id": t.track_id,
                "frontal": bool(t.frontal_ratio() >= 0.5),
                "closeup": bool(t.closeup_ratio() >= 0.5),
                "frontal_ratio": round(t.frontal_ratio(), 3),
                "closeup_ratio": round(t.closeup_ratio(), 3),
                "bbox": list(t.median_bbox()),
                "t_span": [round(v, 3) for v in t.t_span],
            } for t in s["tracks"]],
        } for s in shots]
        (shots_dir / "frontal_closeups.json").write_text(
            json.dumps(face_reports, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        shotsheet = _shotsheet_from(shots, ep, int(round(fps)), total)
        (shots_dir / "shots.json").write_text(
            shotsheet.model_dump_json(indent=None) + "\n", encoding="utf-8")
        face_info["shot_s"] = shot_s

    # ---- ⑥ 回填 C2 utterances（存在才回填；M4/M2 先行产出口径）----
    utt_path = dial / "utterances.jsonl"
    n_backfilled = 0
    if utt_path.is_file():
        utt_table = C.load_jsonl(utt_path, C.UtteranceTable)
        # 每说话段窗的主动轨迹（actspk：嘴动均值最高者；单轨迹直接绑定）
        def active_track(win: tuple[float, float]) -> Optional[FaceTrack]:
            cands = [(tr.ratio_at((win[0] + win[1]) / 2.0), tr) for tr in tracks
                     if _track_overlaps(tr, win[0], win[1]) >= _TRACK_OVERLAP_MIN]
            if not cands:
                return None
            if len(cands) == 1:
                return cands[0][1]
            cands.sort(key=lambda x: -x[0])
            return cands[0][1]

        seg_track = {i: active_track(w) for i, w in enumerate(windows)}
        seg_speaker = {i: spk for i, spk in enumerate(speakers)}

        def utt_speaker(u: C.Utterance) -> tuple[Optional[str], bool]:
            # 句窗与段窗的重叠覆盖率：取覆盖最高段；段窗两两时间交叠>0.2s 且都
            # 显著落在句窗 → 重叠说话（VAD 窗互斥时如实 False，重叠检测归 M4 事件）
            scores = []
            for i, w in enumerate(windows):
                inter = min(u.end, w[1]) - max(u.start, w[0])
                if inter <= 0:
                    continue
                cover = inter / max(u.end - u.start, 1e-6)
                scores.append((cover, i))
            scores.sort(reverse=True)
            if not scores:
                return None, False
            overlap_flag = False
            for (_c1, i1) in scores:
                for (_c2, i2) in scores:
                    if i2 <= i1:
                        continue
                    w1, w2 = windows[i1], windows[i2]
                    pair_inter = min(w1[1], w2[1]) - max(w1[0], w2[0])
                    if pair_inter > 0.2 and _c1 >= 0.3:
                        overlap_flag = True
            return seg_speaker.get(scores[0][1]), overlap_flag

        speaker_map_path = cast_dir / "speaker_map.json"
        spk2char: dict[str, str] = {}
        if speaker_map_path.is_file():
            spk2char = json.loads(speaker_map_path.read_text(encoding="utf-8"))

        updated: list[C.Utterance] = []
        for u in utt_table.root:
            spk, ov = utt_speaker(u)
            face = None
            tr = seg_track.get(next((i for i, w in enumerate(windows)
                                     if spk == seg_speaker.get(i)
                                     and min(u.end, w[1]) - max(u.start, w[0]) > 0), None))
            if tr is not None:
                face = build_face_fact(tr, (u.start, u.end),
                                       (frame_size[0], frame_size[1]))
            # 镜头回填：句中点所在镜头（C6 lip_plan 需要 shot_id；无视频时保留原值）
            shot_override = None
            if shots:
                mid = (u.start + u.end) / 2.0
                covering = _covering_shot(mid, shots)
                shot_override = covering["shot_id"] if covering else None
            updated.append(u.model_copy(update={
                "shot_id": shot_override or u.shot_id,
                "speaker": spk or u.speaker,
                "char_id": (spk2char.get(spk) if spk else None) or u.char_id,
                "overlap": bool(ov or u.overlap),
                "face": face or u.face,
            }))
        C.upsert_jsonl(utt_path, updated, container=C.UtteranceTable)
        n_backfilled = len(updated)

    # ---- ⑦ 报告 ----
    weights = (Path(__file__).resolve().parents[1].parent / "models" / "voxdia"
               / "campplus_cn_common.bin")
    report = {
        "ep": ep,
        "module": "m5_diar",
        "schema_version": 1,
        "audio_input": str(wav),
        "audio_role": "vocals" if wav == vocals else "mix-fallback",
        "vad_source": vad_source,
        "n_windows": len(windows),
        "n_speakers": cluster_info.get("n_speakers", 0),
        "speaker_order": cluster_info.get("speaker_order", []),
        "avg_cos": cluster_info.get("avg_cos"),
        "max_speakers": max_speakers,
        "speakers": speakers,
        "embedding": {
            "component": "voxdia",
            "dim": embedder.dim,
            "weights_sha256_12": (hashlib.sha256(weights.read_bytes()).hexdigest()[:12]
                                  if weights.is_file() else None),
        },
        "n_shots": n_shots,
        "n_utterances_backfilled": n_backfilled,
        "timing": {"embed_cluster_s": emb_s},
    }
    (dial / "diar_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def torch_from(arr: np.ndarray):
    import torch

    return torch.from_numpy(np.ascontiguousarray(arr))


# ---------------------------------------------------------------------------
# voicebank 子命令（每剧音色库：角色 ↔ 参考音频登记）
# ---------------------------------------------------------------------------

_VOICES_HEADER = """# ============================================================================
# 角色 → 音色参考映射（configs/voices.yaml）
# 项目级默认模板 + M5 voice 子命令登记的每剧音色库（casts.<cast>）。
# 与契约 C3 characters.json 的关系：本文件是**项目级默认模板**；
# 每部剧人工确认一次（M5/审校台回写 05_cast/characters.json），各集复用。
# 本文件由 `python -m pipeline.m5_diar voice ...` 机写（保留 schema_version/defaults）。
# ============================================================================
"""


def _voices_doc_path(cfg: dict | None, voices: str | Path | None) -> Path:
    if voices:
        return Path(voices)
    cfg = cfg or load_pipeline_config()
    return Path(__file__).resolve().parents[1] / "configs" / "voices.yaml"


def _load_voices_doc(path: Path) -> dict:
    if path.is_file():
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    else:
        doc = {}
    doc.setdefault("schema_version", 1)
    doc.setdefault("defaults", {
        "engine": "dub-tts",
        "emo_alpha_default": 0.7,
        "duration_factor_default": 1.0,
        "ref_dur_s_range": [10.0, 15.0],
    })
    doc.setdefault("casts", {})
    return doc


def _write_voices_doc(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = _VOICES_HEADER + yaml.safe_dump(doc, allow_unicode=True,
                                           sort_keys=False, default_flow_style=False)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def voice_register(cast: str, char_id: str, wav: Path, *, name: str | None = None,
                   gender: str = "u", desc: str = "", terms: dict[str, str] | None = None,
                   ep: str | None = None, voices_path: str | Path | None = None,
                   jobs_dir: str | Path | None = None, cfg: dict | None = None,
                   consent_subject: str | None = None) -> dict[str, Any]:
    """登记角色参考音频：wav 复制入 jobs/<ep>/05_cast/voicebank/，角色卡写
    configs/voices.yaml ``casts.<cast>.characters.<char_id>``（含 ref 实测时长；
    超出 defaults.ref_dur_s_range 记 warning 不拒绝），有 ``--ep`` 时同步回写
    C3 ``05_cast/characters.json``（CastBook 强校验）。"""
    if gender not in ("m", "f", "u"):
        raise DiarError(f"gender 须为 m/f/u，得到 {gender!r}")
    if not wav.is_file():
        raise DiarError(f"参考音频不存在: {wav}")
    info = sf.info(str(wav))
    ref_dur = float(info.frames) / float(info.samplerate)

    cfg = cfg or load_pipeline_config()
    vpath = _voices_doc_path(cfg, voices_path)
    doc = _load_voices_doc(vpath)
    rng = (doc["defaults"].get("ref_dur_s_range") or [10.0, 15.0])
    lo, hi = float(rng[0]), float(rng[1])
    warnings: list[str] = []
    if not (lo <= ref_dur <= hi):
        warnings.append(f"参考时长 {ref_dur:.1f}s 超出 [{lo}, {hi}]（规划 §4 M5 ④："
                        "10-15s 干净参考）—— 已登记，建议补录")

    rel_ref = f"05_cast/voicebank/{char_id}_ref.wav"
    cast_entry = doc["casts"].setdefault(cast, {"note": "", "characters": {}})
    if not isinstance(cast_entry.get("characters"), dict):
        cast_entry["characters"] = {}
    cast_entry["characters"][char_id] = {
        "name": name or char_id,
        "gender": gender,
        "voice_ref": rel_ref,
        "ref_dur_s": round(ref_dur, 3),
        "desc": desc,
        "terms": terms or {},
        "consent_scope": "比赛演示",
        **({"consent_subject": consent_subject} if consent_subject else {}),
    }
    _write_voices_doc(vpath, doc)

    copied: str | None = None
    if ep:
        root = Path(jobs_dir) if jobs_dir else Path(cfg["paths"]["jobs_dir"])
        vb_dir = ep_dir(ep, root) / "05_cast" / "voicebank"
        vb_dir.mkdir(parents=True, exist_ok=True)
        dst = vb_dir / f"{char_id}_ref.wav"
        import shutil

        shutil.copy2(wav, dst)
        copied = str(dst)
        _sync_characters_json(ep, root, doc["casts"][cast]["characters"])

    return {"cast": cast, "char_id": char_id, "ref_dur_s": round(ref_dur, 3),
            "voices_path": str(vpath), "copied_to": copied, "warnings": warnings}


def _sync_characters_json(ep: str, jobs_root: Path, characters: dict) -> Path:
    """voices.yaml 角色表 → C3 characters.json（CastBook 强校验后原子写）。"""
    from pipeline.contracts import _atomic_write_lines  # 写盘唯一出口

    book = {}
    for cid, c in characters.items():
        book[cid] = {
            "name": c.get("name") or cid,
            "aliases": [],
            "gender": c.get("gender", "u"),
            "voice_ref": c["voice_ref"],
            "ref_dur_s": float(c.get("ref_dur_s", 0.0)),
            "desc": c.get("desc", ""),
            "terms": c.get("terms") or {},
            "consent": ({"subject": c.get("consent_subject") or c.get("name") or cid,
                         "form": "05_cast/consent/pending.pdf",
                         "scope": c.get("consent_scope", "比赛演示"),
                         "date": None} if c.get("consent_subject") else None),
        }
    validated = C.CastBook.model_validate(book)
    path = ep_dir(ep, jobs_root) / "05_cast" / "characters.json"
    _atomic_write_lines(path, [validated.model_dump_json()])
    return path


def voice_list(cast: str | None = None, *, voices_path: str | Path | None = None,
               cfg: dict | None = None) -> list[dict]:
    """列出音色库（全部剧或指定剧）。"""
    cfg = cfg or load_pipeline_config()
    doc = _load_voices_doc(_voices_doc_path(cfg, voices_path))
    casts = doc["casts"] if cast is None else {cast: doc["casts"].get(cast, {})}
    rows = []
    for cid_cast, entry in casts.items():
        for cid, c in (entry.get("characters") or {}).items():
            rows.append({"cast": cid_cast, "char_id": cid, "name": c.get("name"),
                         "gender": c.get("gender"), "voice_ref": c.get("voice_ref"),
                         "ref_dur_s": c.get("ref_dur_s")})
    return rows


def voice_bind(cast: str, spk: str, char_id: str, *, ep: str | None = None,
               jobs_dir: str | Path | None = None, cfg: dict | None = None,
               voices_path: str | Path | None = None) -> dict[str, Any]:
    """把聚类说话人（spk0..）绑定到角色（char_id）→ jobs/<ep>/05_cast/
    speaker_map.json（M5 回填 C2 char_id 的依据；角色须已登记）。"""
    cfg = cfg or load_pipeline_config()
    doc = _load_voices_doc(_voices_doc_path(cfg, voices_path))
    chars = (doc["casts"].get(cast) or {}).get("characters") or {}
    if char_id not in chars:
        raise DiarError(f"角色 {char_id!r} 未登记于 {cast}（先 voice add）")
    if not ep:
        return {"cast": cast, "spk": spk, "char_id": char_id, "written": None}
    root = Path(jobs_dir) if jobs_dir else Path(cfg["paths"]["jobs_dir"])
    path = ep_dir(ep, root) / "05_cast" / "speaker_map.json"
    mapping = {}
    if path.is_file():
        mapping = json.loads(path.read_text(encoding="utf-8"))
    mapping[spk] = char_id
    from pipeline.contracts import _atomic_write_lines

    _atomic_write_lines(path, [json.dumps(mapping, ensure_ascii=False)])
    return {"cast": cast, "spk": spk, "char_id": char_id, "written": str(path)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.m5_diar",
        description="M5 镜头切分 + 说话人区分 + 主动说话人 + 正脸近景判定")
    sub = parser.add_subparsers(dest="cmd")

    p_run = sub.add_parser("run", help="全流程（默认）")
    _add_run_args(p_run)

    p_voice = sub.add_parser("voice", help="voicebank 管理（每剧音色库）")
    vsub = p_voice.add_subparsers(dest="voice_cmd", required=True)
    p_add = vsub.add_parser("add", help="登记角色参考音频（角色↔参考音频绑定）")
    p_add.add_argument("--cast", required=True, help="剧 ID（每剧音色库键，如 ep01）")
    p_add.add_argument("--char", required=True, help="角色 ID，如 char_nan")
    p_add.add_argument("--wav", required=True, help="参考音频（10-15s 干净人声）")
    p_add.add_argument("--name", default=None, help="角色名")
    p_add.add_argument("--gender", default="u", choices=["m", "f", "u"])
    p_add.add_argument("--desc", default="", help="角色描述")
    p_add.add_argument("--ep", default=None, help="同步写入 jobs/<ep>/05_cast（可选）")
    p_add.add_argument("--jobs-dir", default=None)
    p_add.add_argument("--voices", default=None, help="voices.yaml 路径（默认 configs/voices.yaml）")
    p_add.add_argument("--consent-subject", default=None, help="授权人（写入 C3 consent）")
    p_lst = vsub.add_parser("list", help="列出音色库")
    p_lst.add_argument("--cast", default=None)
    p_lst.add_argument("--voices", default=None)
    p_bind = vsub.add_parser("bind", help="聚类说话人 → 角色绑定")
    p_bind.add_argument("--cast", required=True)
    p_bind.add_argument("--spk", required=True, help="聚类说话人标签，如 spk0")
    p_bind.add_argument("--char", required=True, help="已登记角色 ID")
    p_bind.add_argument("--ep", default=None, help="写入 jobs/<ep>/05_cast/speaker_map.json")
    p_bind.add_argument("--jobs-dir", default=None)
    p_bind.add_argument("--voices", default=None)

    # 规划 §4 M5 冻结形态 ``--ep ep01``（无子命令）→ 等价 ``run --ep ep01``；
    # 首个非选项 token 不是已知子命令时注入 run（argparse 原生 subparsers 会
    # 把 --ep 当子命令名报错，T7 实测）。
    argv2 = list(sys.argv[1:] if argv is None else argv)
    if not argv2 or argv2[0] not in {"run", "voice"}:
        argv2 = ["run", *argv2]
    args = parser.parse_args(argv2)

    if args.cmd == "voice":
        return _main_voice(args)
    return _main_run(args)


def _add_run_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--ep", required=True, help="集 ID，如 ep01")
    p.add_argument("--jobs-dir", default=None, help="jobs 根目录（默认 configs/pipeline.yaml）")
    p.add_argument("--audio", default=None, help="音频覆盖（默认 04_dial/vocals.wav → audio_16k.wav）")
    p.add_argument("--video", default=None, help="视频覆盖（默认 01_media/video_*.mp4）")
    p.add_argument("--max-speakers", type=int, default=None,
                   help="说话人数上限（默认 = 已登记角色数+1，无登记则 4）")
    p.add_argument("--shot-threshold", type=float, default=0.5, help="转场概率阈值")
    p.add_argument("--face-step", type=float, default=0.4, help="人脸采样步长（秒）")
    p.add_argument("--no-video", action="store_true", help="跳过镜头/人脸（纯说话人）")


def _main_run(args) -> int:
    try:
        report = run(
            args.ep,
            jobs_dir=args.jobs_dir,
            audio=Path(args.audio) if getattr(args, "audio", None) else None,
            video=Path(args.video) if getattr(args, "video", None) else None,
            max_speakers=getattr(args, "max_speakers", None),
            shot_threshold=getattr(args, "shot_threshold", 0.5),
            face_step_s=getattr(args, "face_step", 0.4),
            no_video=getattr(args, "no_video", False),
        )
    except (DiarError, VoxDiaError, ScDetError, ValidationError, FileNotFoundError) as exc:
        print(f"FAIL m5_diar: {exc}")
        return 1
    print(
        f"OK m5_diar ep={report['ep']} windows={report['n_windows']} "
        f"speakers={report['n_speakers']}({','.join(report['speaker_order']) or '-'}) "
        f"shots={report['n_shots']} vad={report['vad_source']} "
        f"backfilled={report['n_utterances_backfilled']}"
    )
    print(f"  04_dial/diar.jsonl + diar_report.json；02_shots/shots.json + frontal_closeups.json")
    return 0


def _main_voice(args) -> int:
    try:
        if args.voice_cmd == "add":
            terms = {}
            out = voice_register(
                args.cast, args.char, Path(args.wav), name=args.name,
                gender=args.gender, desc=args.desc, terms=terms, ep=args.ep,
                voices_path=args.voices, jobs_dir=args.jobs_dir,
                consent_subject=args.consent_subject)
            print(f"OK voice add cast={out['cast']} char={out['char_id']} "
                  f"ref_dur_s={out['ref_dur_s']} → {out['voices_path']}")
            for w in out["warnings"]:
                print(f"  WARN {w}")
            if out["copied_to"]:
                print(f"  wav → {out['copied_to']}")
            return 0
        if args.voice_cmd == "list":
            rows = voice_list(args.cast, voices_path=args.voices)
            if not rows:
                print("（音色库为空——先 voice add 登记）")
                return 0
            for r in rows:
                print(f"{r['cast']}\t{r['char_id']}\t{r['name']}\t{r['gender']}\t"
                      f"{r['ref_dur_s']}s\t{r['voice_ref']}")
            return 0
        if args.voice_cmd == "bind":
            out = voice_bind(args.cast, args.spk, args.char, ep=args.ep,
                             jobs_dir=args.jobs_dir, voices_path=args.voices)
            tgt = out["written"] or "（未指定 --ep，仅校验）"
            print(f"OK voice bind {out['spk']} → {out['char_id']}（{out['cast']}）→ {tgt}")
            return 0
    except (DiarError, ValidationError) as exc:
        print(f"FAIL voice: {exc}")
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
