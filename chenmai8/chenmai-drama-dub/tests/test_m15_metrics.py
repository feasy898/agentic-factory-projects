"""M15 指标体系 eval（规划 §4 M15；任务 T21 自验收口径）。

冻结 eval 命令::

    bash scripts/eval_m15.sh          # 或: pytest tests/test_m15_metrics.py

覆盖面：
  ① 纯函数：WER/CER 编辑距离与分语种口径（词/字）、归一化、Pearson（含零方差
     退化）、RMS 包络；
  ② 说话人相似度：同源音频（同一 wav 作合成句与参考）余弦≈1.0（真嵌入组件，
     权重缺失时 skip——非冻结线的环境性 skip，与 fbank parity 同口径）；
  ③ 时长对齐率（实测口径）：in-window / 超窗 / keep_original / 缺 wav 四类逐句
     落窗核验 + 值精确断言 + M8 预测口径交叉参照字段；
  ④ 口型评分：合成"动嘴"视频（矩形块随配音包络开合）r 显著为正，静止视频
     |r| 显著低——度量对面部-语音同步信号的敏感性；
  ⑤ 桩服务（:9001 契约）：情绪回判一致率与配音回听 WER 对桩响应的精确断言；
  ⑥ CLI（python -m pipeline.m15_metrics）：在线六项全出数 exit 0（服务可达时，
     TTS 真合成 + 桩外真 :9001）；--asr-url 指死端口 + --allow-degraded 时缺项
     如实落盘 exit 0；C2 缺失 exit 1。

口径注记（如实区分）：
  - 全部指标断言"出数与口径正确"，不对数值做规划通过线门禁（T21 定案：数值
    如实、无基准则记 baseline v0，判定归消费方）；
  - 在线组依赖本机 SAPI 声库 + GPU :9002/:9001 隧道，任一不可达整组 skip
    （test_m4/test_m7 同口径；服务不可达类跳过，非代码缺陷）。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from pipeline import contracts as C
from pipeline.m15_metrics import _common
from pipeline.m15_metrics._common import (
    CallLedger,
    edit_distance,
    normalize_text,
    pearson,
    rms_envelope,
    tokenize,
    wer_rate,
    write_json_atomic,
)
from pipeline.m15_metrics import dur_align, lip_score, speaker_sim, wer
from pipeline.m15_metrics import emotion_sim
from pipeline.m15_metrics.__main__ import main as m15_main, run_metrics
from pipeline.scaffold import create_workspace, ep_dir

EP = "epm15"
LANG = "en"
FPS = 25
VW, VH = 320, 240  # 离线用小画幅（口型评分逻辑与画幅无关；成片链路归自验收样本）

#: 离线语料：(utt_id 后缀毫秒, start, end, zh 文本, en 译文, emo 标签)
CORPUS = [
    (500, 0.5, 1.9, "你到底想怎么样", "what do you really want", "neutral"),
    (2200, 2.2, 3.6, "把话说清楚", "say it clearly", "angry"),
]
MASTER_DUR = 4.0
FACE_BBOX = [40, 80, 280, 200]  # 小画幅下的人脸框（嘴区=下半 45%）


# ---------------------------------------------------------------------------
# 素材构造助手（确定性）
# ---------------------------------------------------------------------------

def _tone(freq: float, dur: float, sr: int, amp: float = 0.25) -> np.ndarray:
    n = int(round(dur * sr))
    return amp * np.sin(2 * np.pi * freq * np.arange(n) / sr)


def _utt_ids() -> list[str]:
    return [C.make_utt_id(EP, start) for _ms, start, _e, *_r in CORPUS]


def _write_c2(root: Path) -> list[C.Utterance]:
    utts = [
        C.Utterance(
            utt_id=C.make_utt_id(EP, start), shot_id="s0000", start=start, end=end,
            lang="zh", speaker="spk0", char_id="char_a", text=zh,
            emo=C.EmoTag(label=emo, score=0.9),
            face=C.FaceFact(frontal=True, closeup=True, bbox=FACE_BBOX),
        )
        for (_ms, start, end, zh, _en, emo) in CORPUS
    ]
    C.dump_jsonl(root / "04_dial" / "utterances.jsonl",
                 C.UtteranceTable.model_validate(utts))
    return utts


def _write_c4(root: Path, utts: list[C.Utterance]) -> None:
    rows = []
    for u, (_ms, _s, _e, _zh, en, _emo) in zip(utts, CORPUS):
        orig = round(u.end - u.start, 3)
        rows.append(C.Translation(
            utt_id=u.utt_id, tgt=LANG,
            budget=C.Budget(orig_dur=orig, lo=round(orig * 0.9, 3),
                            hi=round(orig * 1.1, 3)),
            candidates=[C.Candidate(text=en, syl=len(en.split()),
                                    est_dur=orig, src="mock", q=0.9)],
            chosen=0,
        ))
    C.dump_jsonl(root / "06_mt" / "translations.jsonl",
                 C.TranslationTable.model_validate(rows))


def _write_c5(root: Path, utts: list[C.Utterance], *, durations: dict[str, float],
              keep_original: set[str] | None = None) -> list[C.SynthPlanItem]:
    keep_original = keep_original or set()
    items = []
    for u, (_ms, _s, _e, _zh, en, _emo) in zip(utts, CORPUS):
        items.append(C.SynthPlanItem(
            utt_id=u.utt_id, engine="dub-tts",
            voice_ref="05_cast/voicebank/char_a_ref.wav",
            emo_ref=None, emo_alpha=0.7, duration_factor=1.0, atempo=1.0,
            text=en, out=f"07_synth/wavs/{u.utt_id}.wav",
            expect_dur=round(u.end - u.start, 3),
            keep_original=u.utt_id in keep_original))
    C.dump_jsonl(root / "07_synth" / f"synth_plan.{LANG}.jsonl",
                 C.SynthPlanTable.model_validate(items))
    # 合成 wav（默认 tone，时长由 durations 控制）
    freqs = [440.0, 520.0]
    for i, (u, _c) in enumerate(zip(utts, CORPUS)):
        if u.utt_id in keep_original:
            continue
        d = durations[u.utt_id]
        sf.write(root / "07_synth" / "wavs" / f"{u.utt_id}.wav",
                 _tone(freqs[i], d, 16000).astype(np.float32), 16000,
                 subtype="PCM_16")
    return items


def _gate_per_frame(n_frames: int, fps: int = FPS) -> np.ndarray:
    """确定性音节门控 0..1（1.7Hz 平滑正弦——离线语料的"语音起伏"）。"""
    i = np.arange(n_frames)
    return 0.5 + 0.5 * np.sin(2 * np.pi * 1.7 * i / fps)


def _write_dubbed(root: Path, utts: list[C.Utterance],
                  durations: dict[str, float], sr: int = 16000,
                  gate_frames: np.ndarray | None = None,
                  wavs: dict[str, Path] | None = None) -> Path:
    """把合成句按 C2 窗起点摆到整轨（m9 人声时间轴的极简复刻）。

    ``wavs`` 给定时按句读真实 wav（重采样到 sr）摆放；否则用 tone。
    ``gate_frames`` 给定时句内波形按逐帧门控调幅（模拟语音能量起伏，使能量
    包络与视频动嘴门控同源可比）；None=原样（TTS 真语音自带起伏）。
    """
    track = np.zeros(int(MASTER_DUR * sr), dtype=np.float64)
    freqs = [440.0, 520.0]
    fps = FPS
    for i, (u, _c) in enumerate(zip(utts, CORPUS)):
        if wavs and u.utt_id in wavs:
            data, asr = sf.read(str(wavs[u.utt_id]), dtype="float32", always_2d=True)
            seg = data.mean(axis=1)
            if asr != sr:
                import librosa
                seg = librosa.resample(seg, orig_sr=asr, target_sr=sr)
        else:
            seg = _tone(freqs[i], durations[u.utt_id], sr)
        if gate_frames is not None:
            n_fr = gate_frames.shape[0]
            idx = np.clip((np.arange(seg.shape[0]) / sr * fps).astype(int),
                          0, n_fr - 1)
            seg = seg * gate_frames[idx]
        j0 = int(u.start * sr)
        j1 = min(track.shape[0], j0 + seg.shape[0])
        track[j0:j1] = seg[: j1 - j0]
    out = root / "08_mix" / f"dubbed.{LANG}.wav"
    sf.write(out, track.astype(np.float32), sr, subtype="PCM_16")
    return out


def _write_video(path: Path, *, jitter_gate: np.ndarray | None,
                 fps: int = FPS, size: tuple[int, int] = (VW, VH)) -> Path:
    """ffmpeg rawvideo 管道压制：暗底 + 嘴区矩形块随机向抖动（幅度∝门控）。

    帧差活性 ≈ 相邻帧位移幅度 ∝ 门控（随机符号让位移均方随当前幅度增长，
    规避"恒尺寸动画只产生与能量正交的导数信号"的构造陷阱）；
    ``jitter_gate=None`` → 全静止（负例）。
    """
    import subprocess

    import cv2

    w, h = size
    mx0, my0, mx1, my1 = lip_score.mouth_box(FACE_BBOX, w, h)
    cx, cy = (mx0 + mx1) // 2, (my0 + my1) // 2
    half = max(8, min(mx1 - mx0, my1 - my0) // 8)
    max_shift = max(4, half // 2)
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", str(fps),
         "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
         "-crf", "28", str(path)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    n_frames = int(MASTER_DUR * fps)
    for i in range(n_frames):
        frame = np.full((h, w, 3), 24, dtype=np.uint8)
        if jitter_gate is not None:
            k = float(np.clip(jitter_gate[i], 0.0, 1.0))
            # 逐帧交替向左/右位移（模拟嘴开合）：相邻帧位移幅度 ≈ A_i + A_{i-1}
            # → 帧差活性单调随门控增长（确定性，无随机符号噪声）
            a = int(round(max_shift * k))
            d = a if i % 2 == 0 else -a
            cv2.rectangle(frame, (cx + d - half, cy - half),
                          (cx + d + half, cy + half), (200, 200, 200), -1)
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    proc.wait(timeout=120)
    assert path.is_file() and path.stat().st_size > 500
    return path


def _video_envelope(dubbed: Path, fps: int = FPS) -> np.ndarray:
    """配音轨逐帧 RMS 包络（归一 0-1；与 lip_score 的能量序列同口径）。"""
    wav, sr = _common.read_mono(dubbed)
    env = np.zeros(int(MASTER_DUR * fps))
    for i in range(env.shape[0]):
        i0 = int(round((i / fps) * sr))
        i1 = max(i0 + 1, int(round(((i + 1) / fps) * sr)))
        seg = wav[i0:min(i1, wav.shape[0])]
        env[i] = float(np.sqrt(np.mean(seg ** 2) + 1e-12))
    env = env / max(env.max(), 1e-9)
    return env


def _compose_finished(root: Path, video: Path, dubbed: Path) -> Path:
    """12_out/<ep>.<lang>.mp4 = 视频 + 配音轨（ffmpeg mux，成片极简复刻）。"""
    import subprocess

    out = root / "12_out" / f"{EP}.{LANG}.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-i", str(video), "-i", str(dubbed), "-c:v", "copy", "-c:a", "aac",
         "-shortest", str(out)],
        check=True, timeout=300, capture_output=True, text=True)
    return out


def _build_workspace(jobs_root: Path, *, durations: dict[str, float] | None = None,
                     keep_original: set[str] | None = None,
                     moving_mouth: bool = True, finished: bool = True,
                     with_c4: bool = True) -> tuple[Path, list[C.Utterance]]:
    """离线工作区：C2 + C4 + C5 + 合成 wav + 配音轨 + 成片（全 tone/合成帧）。"""
    create_workspace(EP, jobs_root)
    root = ep_dir(EP, jobs_root)
    utts = _write_c2(root)
    if with_c4:
        _write_c4(root, utts)
    durs = durations or {u.utt_id: round(u.end - u.start, 3) for u in utts}
    _write_c5(root, utts, durations=durs, keep_original=keep_original)
    gate = _gate_per_frame(int(MASTER_DUR * FPS)) if moving_mouth else None
    dubbed = _write_dubbed(root, utts, durs, gate_frames=gate)
    # 参考音色（与首句合成同源 tone → 离线余弦可预期地高）
    sf.write(root / "05_cast" / "voicebank" / "char_a_ref.wav",
             _tone(440.0, 1.5, 16000).astype(np.float32), 16000, subtype="PCM_16")
    if finished:
        video = _write_video(
            root / "01_media" / "sample.mp4",
            jitter_gate=(_video_envelope(dubbed) if moving_mouth else None))
        _compose_finished(root, video, dubbed)
    return root, utts


def _voxdia_weights_present() -> bool:
    from pipeline._voxdia_net import default_weights_path

    return default_weights_path().is_file()


# ---------------------------------------------------------------------------
# ① 纯函数
# ---------------------------------------------------------------------------

def test_wer_and_normalization():
    assert normalize_text("Hello, World!") == "hello world"
    assert edit_distance(list("abc"), list("abc")) == 0
    assert edit_distance(list("kitten"), list("sitting")) == 3
    # 英文按词：8 词参考错 1 词 → 0.125
    ref = tokenize("what do you really want say it clearly", "en")
    hyp = tokenize("what do you really want say it clearly now", "en")
    assert wer_rate(ref, hyp) == pytest.approx(1 / 8, abs=1e-4)
    # 中文按字（去标点）：3 字参考错 1 字 → 1/3
    assert len(tokenize("你到底想怎么样。", "zh")) == 7
    assert wer_rate(tokenize("你到底想怎么样", "zh"), tokenize("你到底像怎么样", "zh")) \
        == pytest.approx(1 / 7, abs=1e-4)
    # 参考空：假设空 → 0；假设非空 → 1
    assert wer_rate([], []) == 0.0
    assert wer_rate([], tokenize("x", "en")) == 1.0


def test_pearson_and_envelope():
    t = np.linspace(0, np.pi, 100)
    assert pearson(np.sin(t), np.sin(t)) == pytest.approx(1.0)
    assert pearson(np.sin(t), -np.sin(t)) == pytest.approx(-1.0)
    assert pearson(np.ones(50), np.sin(t[:50])) == 0.0       # 零方差退化
    assert pearson([1.0], [2.0]) == 0.0                       # 长度不足
    # RMS 包络：0.25 幅度正弦的 RMS ≈ 0.25/√2（1s@16k / 25ms hop = 40 hop）
    x = _tone(440.0, 1.0, 16000, amp=0.25)
    rms, times = rms_envelope(x, 16000, 0.025)
    assert rms.shape == times.shape and rms.shape[0] == 40
    assert float(np.mean(rms)) == pytest.approx(0.25 / np.sqrt(2), rel=0.05)
    assert times[0] == pytest.approx(0.0125)


def test_write_json_atomic(tmp_path):
    p = write_json_atomic(tmp_path / "a" / "b.json", {"x": 1})
    assert json.loads(p.read_text(encoding="utf-8")) == {"x": 1}
    assert not (tmp_path / "a" / "b.json.tmp").exists()


# ---------------------------------------------------------------------------
# ② 说话人相似度（真嵌入组件）
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _voxdia_weights_present(), reason="voxdia 权重缺失（models/voxdia）")
def test_speaker_sim_same_source_cosine_one(tmp_path):
    root, utts = _build_workspace(tmp_path / "jobs")
    # 合成句 wav 直接取参考文件副本（同一文件）→ 余弦恒等 1.0 的确定性断言
    ref = root / "05_cast" / "voicebank" / "char_a_ref.wav"
    for u in utts:
        (root / "07_synth" / "wavs" / f"{u.utt_id}.wav").write_bytes(ref.read_bytes())
    ledger = CallLedger()
    res = speaker_sim.compute(root, LANG, ledger)
    assert res["status"] == "ok"
    assert res["value"] >= 0.999
    assert res["detail"]["n_scored"] == 2
    assert res["threshold"] == speaker_sim.THRESHOLD == 0.70
    assert "speaker_sim.embed" in ledger.stages


@pytest.mark.skipif(not _voxdia_weights_present(), reason="voxdia 权重缺失（models/voxdia）")
def test_speaker_sim_missing_inputs(tmp_path):
    create_workspace(EP, tmp_path / "jobs")
    root = ep_dir(EP, tmp_path / "jobs")
    res = speaker_sim.compute(root, LANG, CallLedger())
    assert res["status"] == "unavailable" and "C5 缺失" in res["reason"]


# ---------------------------------------------------------------------------
# ③ 时长对齐率（实测口径）
# ---------------------------------------------------------------------------

def test_dur_align_measured(tmp_path):
    ids = _utt_ids()
    # u0 原窗 1.4s（窗 [1.26,1.54]）：1.40 在窗；u1 原窗 1.4s：2.00 超窗
    durations = {ids[0]: 1.40, ids[1]: 2.00}
    root, _utts = _build_workspace(tmp_path / "jobs", durations=durations,
                                   finished=False)
    res = dur_align.compute(root, LANG, CallLedger())
    assert res["status"] == "ok"
    d = res["detail"]
    assert res["value"] == pytest.approx(0.5, abs=1e-4)
    by_id = {p["utt_id"]: p for p in d["per_utt"]}
    assert by_id[ids[0]]["in_window"] is True
    assert by_id[ids[1]]["in_window"] is False
    assert by_id[ids[0]]["src"] == "wav 实测"
    assert d["n_total"] == 2 and d["n_in_window"] == 1


def test_dur_align_keep_original_in_window(tmp_path):
    ids = _utt_ids()
    root, utts = _build_workspace(tmp_path / "jobs",
                                  keep_original={ids[1]}, finished=False)
    res = dur_align.compute(root, LANG, CallLedger())
    assert res["status"] == "ok"
    # u0 合成实测=句窗长在窗；u1 keep_original 按复刻句窗长计 → 也在窗
    assert res["value"] == pytest.approx(1.0, abs=1e-4)
    by_id = {p["utt_id"]: p for p in res["detail"]["per_utt"]}
    assert by_id[ids[1]]["src"] == "keep_original(C2 句窗)"


def test_dur_align_missing_wav_counts_fail(tmp_path):
    ids = _utt_ids()
    root, _utts = _build_workspace(tmp_path / "jobs", finished=False)
    (root / "07_synth" / "wavs" / f"{ids[0]}.wav").unlink()
    res = dur_align.compute(root, LANG, CallLedger())
    assert res["status"] == "ok"
    assert res["value"] == pytest.approx(0.5, abs=1e-4)
    assert res["detail"]["missing_wav"] == [ids[0]]


# ---------------------------------------------------------------------------
# ④ 口型评分
# ---------------------------------------------------------------------------

def test_lip_score_correlated_vs_static(tmp_path):
    root, utts = _build_workspace(tmp_path / "jobs", moving_mouth=True)
    ledger = CallLedger()
    res = lip_score.compute(root, LANG, EP, ledger)
    assert res["status"] == "ok"
    # 矩形块开合由配音包络驱动 → 活性与能量显著正相关
    assert res["value"] > 0.5
    assert res["threshold"] is None and res["detail"]["baseline"].startswith("v0")
    assert res["detail"]["region_source"].startswith("C2 face.bbox")
    assert len(res["detail"]["per_utt"]) == 2
    assert "lip_score.frames" in ledger.stages

    root2, _utts2 = _build_workspace(tmp_path / "jobs_static", moving_mouth=False)
    res2 = lip_score.compute(root2, LANG, EP, CallLedger())
    assert res2["status"] == "ok"
    # 静止视频：帧差只剩编码噪声 → 相关性显著低于动嘴样本
    assert abs(res2["value"]) < 0.5


def test_lip_score_no_video(tmp_path):
    create_workspace(EP, tmp_path / "jobs")
    root = ep_dir(EP, tmp_path / "jobs")
    _write_c2(root)
    res = lip_score.compute(root, LANG, EP, CallLedger())
    assert res["status"] == "unavailable" and "无成片视频" in res["reason"]


# ---------------------------------------------------------------------------
# ⑤ 桩服务（:9001 契约形态）—— 情绪回判 + 回听 WER
# ---------------------------------------------------------------------------

class _StubAsrHandler(BaseHTTPRequestHandler):
    """按上传文件名区分响应：dubbed16k → 整轨转写；<utt_id>.wav → 情绪回判。"""

    def log_message(self, *a):  # 静默
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        if b"dubbed16k" in body:
            payload = {
                "text": "what do you really want say it cleanly",
                "segments": [
                    {"i": 0, "start": 0.5, "end": 1.9, "text": "what do you really want"},
                    {"i": 1, "start": 2.2, "end": 3.6, "text": "say it cleanly"},
                ],
                "words": [], "emo": None,
            }
        else:
            # 情绪回判：u0 命中参考 neutral；u1 回判 angry ≠ 参考 sad→angry? 语料
            # u1 参考 angry：此处故意回判 happy → 一致率 1/2
            payload = {"text": "x", "words": [],
                       "emo": {"label": "happy", "score": 0.8}}
            for uid in _utt_ids():
                if uid.encode() in body:
                    payload["emo"] = {"label": _STUB_EMO[uid], "score": 0.8}
                    break
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


_STUB_EMO: dict[str, str] = {}  # 由 fixture 按 C2 参考标签填充（u1 故意不一致）


@pytest.fixture()
def stub_asr():
    _STUB_EMO.clear()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _StubAsrHandler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def test_emotion_and_wer_against_stub(tmp_path, stub_asr):
    root, utts = _build_workspace(tmp_path / "jobs", finished=False)
    _STUB_EMO.update({u.utt_id: ("neutral" if i == 0 else "happy")
                      for i, u in enumerate(utts)})  # u1 参考 angry → 不一致

    from pipeline.gpu_client import GpuClient
    cli = GpuClient(stub_asr, retries=0)

    emo = emotion_sim.compute(root, LANG, CallLedger(), client=cli)
    assert emo["status"] == "ok"
    assert emo["value"] == pytest.approx(0.5, abs=1e-4)
    assert emo["detail"]["n_judged"] == 2
    matches = {p["utt_id"]: p["match"] for p in emo["detail"]["per_utt"]}
    assert matches[utts[0].utt_id] is True and matches[utts[1].utt_id] is False

    w = wer.compute(root, LANG, CallLedger(), client=cli)
    assert w["status"] == "ok"
    # ref = "what do you really want say it clearly"（8 词），hyp 尾词 cleanly≠clearly
    assert w["value"] == pytest.approx(1 / 8, abs=1e-4)
    assert w["detail"]["n_windows_mapped"] == 2
    per = {p["utt_id"]: p for p in w["detail"]["per_utt"]}
    assert per[utts[0].utt_id]["wer"] == 0.0
    assert per[utts[1].utt_id]["wer"] == pytest.approx(1 / 3, abs=1e-4)


# ---------------------------------------------------------------------------
# ⑥ CLI 与 run_metrics
# ---------------------------------------------------------------------------

def test_run_metrics_offline_degraded(tmp_path):
    root, _utts = _build_workspace(tmp_path / "jobs")
    payload, code = run_metrics(EP, LANG, jobs_dir=tmp_path / "jobs",
                                asr_url="http://127.0.0.1:9")  # 死端口 → :9001 类缺项
    assert payload["schema_version"] == 1
    assert payload["baseline"] == "v0"
    assert set(payload["metrics"]) == set(
        ("speaker_similarity", "emotion_similarity", "listen_wer",
         "duration_alignment_rate", "lip_score", "cost_per_minute"))
    # 离线四项必须出数；:9001 两项 unavailable 且带 reason
    for k in ("speaker_similarity", "duration_alignment_rate", "lip_score",
              "cost_per_minute"):
        assert payload["metrics"][k]["status"] == "ok", k
        assert payload["metrics"][k]["value"] is not None
    for k in ("emotion_similarity", "listen_wer"):
        assert payload["metrics"][k]["status"] == "unavailable", k
        assert payload["metrics"][k]["reason"]
    assert payload["all_measured"] is False
    assert code == 1
    assert payload["wall_clock_s"]["stages"]


def test_run_metrics_missing_c2(tmp_path):
    create_workspace(EP, tmp_path / "jobs")
    with pytest.raises(FileNotFoundError):
        run_metrics(EP, LANG, jobs_dir=tmp_path / "jobs")


def test_cli_allow_degraded_exit_zero(tmp_path, capsys):
    _build_workspace(tmp_path / "jobs")
    rc = m15_main(["--ep", EP, "--lang", LANG, "--jobs-dir", str(tmp_path / "jobs"),
                   "--asr-url", "http://127.0.0.1:9", "--allow-degraded"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "UNAVAIL" in out and "--allow-degraded" in out
    m = json.loads((tmp_path / "jobs" / EP / "12_out" / "metrics.json")
                   .read_text(encoding="utf-8"))
    assert m["n_metrics_total"] == 6


def test_cli_missing_c2_exit_one(tmp_path, capsys):
    create_workspace(EP, tmp_path / "jobs")
    rc = m15_main(["--ep", EP, "--lang", LANG, "--jobs-dir", str(tmp_path / "jobs")])
    assert rc == 1
    assert "FAIL" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 在线组：SAPI + :9002 TTS + :9001 真服务（任一不可达整组 skip，m4/m7 同口径）
# ---------------------------------------------------------------------------

def _sapi_voice(culture_prefix: str) -> str | None:
    import subprocess

    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$s.GetInstalledVoices()|ForEach-Object{"
        "$_.VoiceInfo.Name+'|'+$_.VoiceInfo.Culture.Name}"
    )
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                             capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in out.splitlines():
        name, _, culture = line.strip().partition("|")
        if culture.lower().startswith(culture_prefix) and name:
            return name
    return None


def _sapi_wav(out_wav: Path, text: str, voice: str) -> Path:
    import subprocess

    raw = out_wav.with_name(out_wav.stem + "_raw.wav")
    ps = (
        "$ErrorActionPreference='Stop';"
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.SelectVoice('{voice}');"
        "$s.SetOutputToWaveFile('" + str(raw).replace("\\", "/") + "');"
        f"$s.Speak('{text}');"
        "$s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True,
                   timeout=120, capture_output=True, text=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw),
                    "-ar", "16000", "-ac", "1", str(out_wav)],
                   check=True, timeout=120, capture_output=True, text=True)
    return out_wav


def _services_up() -> tuple[bool, bool]:
    from pipeline.gpu_client import GpuClient, GpuServiceError
    from pipeline.tts_client import TtsClient

    try:
        asr_ok = bool(GpuClient(retries=0).health().get("loaded", {}).get("asr-core"))
    except GpuServiceError:
        asr_ok = False
    try:
        tts_ok = bool(TtsClient(timeout=30.0, retries=0).health()
                      .get("loaded", {}).get("dub-tts"))
    except Exception:
        tts_ok = False
    return asr_ok, tts_ok


@pytest.fixture(scope="module")
def online_ws(tmp_path_factory: pytest.TempPathFactory):
    """真服务在线工作区：SAPI zh 参考/情绪参考 + :9002 英文配音 + 成片。"""
    from pipeline.tts_client import TtsClient

    asr_ok, tts_ok = _services_up()
    voice = _sapi_voice("zh")
    if not (asr_ok and tts_ok and voice):
        pytest.skip(f"在线组前置不可用（asr={asr_ok}, tts={tts_ok}, sapi={bool(voice)}）")

    tmp = tmp_path_factory.mktemp("m15_online")
    jobs = tmp / "jobs"
    create_workspace(EP, jobs)
    root = ep_dir(EP, jobs)
    utts = _write_c2(root)
    _write_c4(root, utts)

    zh_voice = voice
    ref = _sapi_wav(root / "05_cast" / "voicebank" / "char_a_ref.wav",
                    "三年了，老城的基地哪一样不是我亲手做起来的。你到底想怎么样。把话说清楚。",
                    zh_voice)
    assert ref.is_file()
    # emo_refs = 源句人声切片（M4 产出口径）
    vocals = np.zeros(int(MASTER_DUR * 16000), dtype=np.float32)
    for i, (u, (_ms, s, e, zh, _en, _emo)) in enumerate(zip(utts, CORPUS)):
        w = _sapi_wav(tmp / f"src_{i}.wav", zh, zh_voice)
        data, sr = sf.read(str(w), dtype="float32")
        if sr != 16000:
            import librosa
            data = librosa.resample(data, orig_sr=sr, target_sr=16000)
        seg = data[: int((e - s) * 16000)]
        vocals[int(s * 16000):int(s * 16000) + seg.shape[0]] = seg
        sf.write(root / "04_dial" / "emo_refs" / f"{u.utt_id}.wav", seg, 16000,
                 subtype="PCM_16")
    sf.write(root / "04_dial" / "vocals.wav", vocals, 16000, subtype="PCM_16")

    # C5 + :9002 真合成（emo_ref 通道开启，emo_alpha=0.7）
    items = []
    for u, (_ms, _s, _e, _zh, en, _emo) in zip(utts, CORPUS):
        items.append(C.SynthPlanItem(
            utt_id=u.utt_id, engine="dub-tts",
            voice_ref="05_cast/voicebank/char_a_ref.wav",
            emo_ref=f"04_dial/emo_refs/{u.utt_id}.wav", emo_alpha=0.7,
            duration_factor=1.0, atempo=1.0, text=en,
            out=f"07_synth/wavs/{u.utt_id}.wav",
            expect_dur=round(u.end - u.start, 3), keep_original=False))
    C.dump_jsonl(root / "07_synth" / f"synth_plan.{LANG}.jsonl",
                 C.SynthPlanTable.model_validate(items))
    cli = TtsClient(timeout=300.0, retries=2)
    for it in items:
        cli.synth(it.text, root / it.voice_ref, emo_ref=root / it.emo_ref,
                  lang=LANG, emo_alpha=it.emo_alpha, out=root / it.out,
                  utt_id=it.utt_id)
        assert (root / it.out).is_file()

    dubbed = _write_dubbed(root, utts,
                           {it.utt_id: _common.wav_duration(root / it.out)
                            for it in items}, sr=48000,
                           wavs={it.utt_id: root / it.out for it in items})
    video = _write_video(root / "01_media" / "sample.mp4",
                         jitter_gate=_video_envelope(dubbed))
    _compose_finished(root, video, dubbed)
    return root


def test_online_six_metrics_full(online_ws):
    rc = m15_main(["--ep", EP, "--lang", LANG, "--jobs-dir", str(online_ws.parent)])
    assert rc == 0
    payload = json.loads((online_ws / "12_out" / "metrics.json")
                         .read_text(encoding="utf-8"))
    assert payload["all_measured"] is True, {
        k: (v["status"], v.get("reason")) for k, v in payload["metrics"].items()
    }
    m = payload["metrics"]
    # 数值健全性（不门禁规划线，只断"量纲与方向合理"）
    assert 0.0 <= m["speaker_similarity"]["value"] <= 1.0
    assert m["speaker_similarity"]["value"] > 0.2          # 同参考合成的同源下界
    assert 0.0 <= m["emotion_similarity"]["value"] <= 1.0
    assert 0.0 <= m["listen_wer"]["value"] <= 1.0
    assert 0.0 <= m["duration_alignment_rate"]["value"] <= 1.0
    assert -1.0 <= m["lip_score"]["value"] <= 1.0
    assert m["cost_per_minute"]["value"] > 0
