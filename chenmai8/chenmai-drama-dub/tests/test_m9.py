"""M9 混音 + 成片合成 eval（规划 §4 M9；任务 T15 自验收口径，全离线零 GPU）。

冻结 eval 命令::

    bash scripts/eval_m9.sh          # 或: pytest tests/test_m9.py

§4 M9 原文通过线（T15 自验收口径）：
  ① 时长差 ≤0.2s（mix/dubbed/成片 vs master）；
  ② loudnorm 报告 I∈[-17,-15]（T15：实测 ±1LU —— 对交付文件**复测**，不只信报告）；
  ③ 人声段/bg 峰值比 ≥8dB（对白可懂度；同步给 RMS 口径）。

B1 样本口径（与 tasks 基线一致）：分离背景 ``01_media/bgm.wav``（稳态 150Hz 音，
RMS −20dBFS）+ **占位人声**（07_synth/wavs 合成句按 C5/C2 摆放到原时间轴；
keep_original 句复刻 ``04_dial/vocals.wav`` 原人声）+ M1 口径基带视频 +
M11 装配器生成的目标语 ASS + C7 labels.json。四句语料覆盖：常规合成句、故意
超窗句（overflow 裁切+上报）、异采样率合成句（22050Hz → ffmpeg 重采样路径）、
nonverbal keep_original 句（16k 原人声复刻）。

覆盖面：
  ① 纯函数：梯形窗/ducking 包络（窗外 0dB、提前量区 −6dB、句心 −9dB、斜坡单调）、
     配置读取、RMS/峰值/区间度量；
  ② 端到端 mix_episode：产物三件（dubbed/mix/mix_report）+ 无后缀副本 + 成片；
  ③ ducking 实测：报告实测值（core≈−9dB/pad≈−6dB/outside≈0dB）+ **交付文件频段
     对拍**（同一交付响度下 bgm 频段在对白区 vs 关闭 ducking 对照混音的压低量）；
  ④ 响度实测：对 ``08_mix/mix.en.wav`` 复跑 loudnorm 测量，I∈[-17,-15]；
  ⑤ 人声存在性与 keep_original 复刻：交付 mix 中人声频段能量在句窗内远大于句隙；
  ⑥ 可懂度：人声/ducked-bg 峰值比 ≥8dB（逐窗最小值）；
  ⑦ 成片：时长差、视频+音频双流、48k 立体声音轨、ASS 已烧（抽帧非纯色）、
     AI 隐式标识元数据位（ffprobe 回读精确匹配）+ M11 成品接入路径（-c:v copy）；
  ⑧ 缺失/兜底/CLI：缺合成 wav WARN 且 exit 0（--strict-missing 升级 exit 1）、
     缺 bgm/C5/C2 exit 1、--no-compose 跳过合成、幂等重跑。

口径注记（如实区分）：
  - 本文件断言 = T15 自验收（实测响度/对白背景电平/成片要素）；规划 §4 M9 的
    完整验收（真实人声/BGM 素材）在自拍素材链路上由集成跑覆盖；
  - "bgm 侧链 −6dB" 按任务 T15 定案落地为确定性语音驱动侧链（C2 句窗驱动包络），
    非 ffmpeg sidechaincompress 的信号相关压缩（深度不可复现实测，口径见
    docs/m9_mix_notes.md）；
  - 占位人声为稳态单音（峰均比 1），故"峰值比"与"RMS 比"在本语料上同阶；
    真实语音（峰均比≈12dB）下以 RMS 口径为准，两者均在报告如实给出。
"""

from __future__ import annotations

import filecmp
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from pipeline import contracts as C
from pipeline import m11_subs as M11
from pipeline.config import REPO_ROOT, load_pipeline_config
from pipeline.m9_mix import (
    MixParams,
    duck_gain,
    interval_peak_dbfs,
    interval_rms_dbfs,
    loudnorm_measure,
    main as m9_main,
    mix_episode,
    params_from_cfg,
    peak_dbfs,
    ramped_rect,
    rms_dbfs,
)
from pipeline.scaffold import create_workspace

EP = "ep01"
LANG = "en"
SR = 48000
MASTER_DUR = 8.0

#: 语料：(utt_id, start, end, source, freq_hz, wav_sr, wav_extra_s)
#: source: synth=合成占位人声 / original=nonverbal keep_original（复刻原人声）
CORPUS: list[tuple[str, float, float, str, float, int, float]] = [
    ("ep01-u00000800", 0.8, 2.4, "synth", 400.0, 48000, 0.0),    # 常规合成句
    ("ep01-u00003200", 3.2, 4.2, "synth", 520.0, 48000, 0.6),    # 故意超窗 → overflow
    ("ep01-u00005000", 5.0, 6.2, "original", 640.0, 16000, 0.0),  # keep_original
    ("ep01-u00006800", 6.8, 7.6, "synth", 300.0, 22050, 0.0),    # 异采样率 → 重采样
]
BGM_FREQ = 150.0
BGM_AMP = 0.1           # bgm 峰值 0.1（≈-20dBFS RMS）
VOICE_AMP = 0.2         # 占位人声峰值 0.2（≈-14dBFS RMS）

#: AI 隐式标识位（C7 labels.json；本测试自填具体值以便精确回读断言）
LABELS = {
    "service_provider": "澄迈短剧出海测试",
    "content_id": "ep01-en",
    "standard": "GB45438-2025",
    "explicit": {"text": "本内容由AI生成", "video": "片头提示字幕≥3s",
                 "audio_announce": False},
    "implicit": {"metadata_field": "XMP:aiGeneratedContent",
                 "value": "ep01-en|澄迈短剧出海测试"},
    "c2pa": "11_labels/c2pa_manifest.json",
    "audio_wm": {"engine": "audmark", "payload": "ep01-en", "bits": 16},
}
LABEL_FIELD = LABELS["implicit"]["metadata_field"]
LABEL_VALUE = LABELS["implicit"]["value"]


# ---------------------------------------------------------------------------
# 素材构造（确定性；同输入恒同输出）
# ---------------------------------------------------------------------------

def _tone(freq: float, dur: float, sr: int, amp: float = VOICE_AMP) -> np.ndarray:
    n = int(round(dur * sr))
    return amp * np.sin(2 * np.pi * freq * np.arange(n) / sr)


def _video_name() -> str:
    media = {**{"width": 1080, "height": 1920, "fps": 25},
             **(load_pipeline_config().get("media") or {})}
    return f"video_{int(media['width'])}x{int(media['height'])}_{int(media['fps'])}fps.mp4"


def _make_base_video(dst: Path) -> Path:
    """M1 口径基带视频（lens：纯色源；M9 自己在成片上烧 ASS，故无需 drawtext）。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i",
         f"color=c=0x101820:size=1080x1920:rate=25:duration={MASTER_DUR}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
         "-crf", "28", str(dst)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
    )
    assert r.returncode == 0, r.stderr[-500:]
    return dst


def _build_workspace(jobs_root: Path, *, base_video: Path | None = None,
                     missing_wav: str | None = None, with_labels: bool = True) -> Path:
    """建 ep 工作区：C2 + 原人声 + C5 + 占位合成 wav + bgm + 视频 + ASS + C7。"""
    create_workspace(EP, jobs_root)
    root = jobs_root / EP

    # ---- C2：四句（含一句 nonverbal keep_original）----
    utts = [
        C.Utterance(utt_id=u, shot_id="s0000", start=s, end=e, lang="zh",
                    speaker="spk0", text=f"line {i + 1}",
                    nonverbal=(src == "original"))
        for i, (u, s, e, src, _f, _sr, _x) in enumerate(CORPUS)
    ]
    C.dump_jsonl(root / "04_dial" / "utterances.jsonl",
                 C.UtteranceTable.model_validate(utts))

    # ---- 04_dial/vocals.wav：16k 单声道，keep_original 句区间有原人声 ----
    v = np.zeros(int(MASTER_DUR * 16000))
    u3 = next(u for u in utts if u.nonverbal)
    seg = _tone(640.0, u3.end - u3.start, 16000)
    v[int(u3.start * 16000):int(u3.end * 16000)] = seg
    sf.write(root / "04_dial" / "vocals.wav", v.astype(np.float32), 16000,
             subtype="PCM_16")

    # ---- C5（每语种文件；M9 按 --lang 读）----
    items = [
        C.SynthPlanItem(
            utt_id=u, engine="dub-tts", voice_ref=f"05_cast/voicebank/{u}_ref.wav",
            emo_ref=None, emo_alpha=0.7, duration_factor=1.0, atempo=1.0,
            text=f"line {i + 1}", out=f"07_synth/wavs/{u}.wav",
            expect_dur=round(e - s, 3), keep_original=(src == "original"))
        for i, (u, s, e, src, _f, _sr, _x) in enumerate(CORPUS)
    ]
    C.dump_jsonl(root / "07_synth" / f"synth_plan.{LANG}.jsonl",
                 C.SynthPlanTable.model_validate(items))

    # ---- 占位合成人声（C5.out；missing_wav 可故意缺一个）----
    wavs = root / "07_synth" / "wavs"
    wavs.mkdir(parents=True, exist_ok=True)
    for u, s, e, src, freq, sr, extra in CORPUS:
        if src != "synth" or u == missing_wav:
            continue
        sf.write(wavs / f"{u}.wav", _tone(freq, (e - s) + extra, sr).astype(np.float32),
                 sr, subtype="PCM_16")

    # ---- 01_media/bgm.wav：48k 立体声稳态背景 ----
    bgm = _tone(BGM_FREQ, MASTER_DUR, SR, amp=BGM_AMP)
    sf.write(root / "01_media" / "bgm.wav",
             np.stack([bgm, bgm], axis=1).astype(np.float32), SR, subtype="PCM_16")

    # ---- 01_media 基带视频 ----
    if base_video is not None:
        shutil.copyfile(base_video, root / "01_media" / _video_name())

    # ---- 10_subs/tgt.en.ass（复用 M11 装配器，避免重复实现样式逻辑）----
    events = [M11.AssEvent(start=s, end=e, text=f"line {i + 1}")
              for i, (_u, s, e, *_r) in enumerate(CORPUS)]
    style, _font = M11.style_for_lang(load_pipeline_config(), LANG)
    (root / "10_subs").mkdir(parents=True, exist_ok=True)
    (root / "10_subs" / f"tgt.{LANG}.ass").write_text(
        M11.build_ass(events, style=style), encoding="utf-8")

    # ---- 11_labels/labels.json（C7）----
    if with_labels:
        (root / "11_labels" / "labels.json").write_text(
            json.dumps(LABELS, ensure_ascii=False, indent=1), encoding="utf-8")
    return root


@pytest.fixture(scope="session")
def base_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """会话级基带视频（全测试只编码一次；各 workspace 复制）。"""
    return _make_base_video(tmp_path_factory.mktemp("base") / _video_name())


@pytest.fixture()
def workspace(tmp_path: Path, base_video: Path) -> Path:
    return _build_workspace(tmp_path / "jobs", base_video=base_video)


# ---------------------------------------------------------------------------
# 度量助手（频段隔离：交付文件级对拍用）
# ---------------------------------------------------------------------------

def _band_rms_dbfs(x: np.ndarray, sr: int, f0: float, bw: float, s: float,
                   e: float) -> float:
    """FFT 隔离 [f0-bw, f0+bw] 频段后取 [s,e) 区间 RMS（dBFS）。"""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    n = x.shape[0]
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    spec = np.where((freqs >= f0 - bw) & (freqs <= f0 + bw), spec, 0.0)
    band = np.fft.irfft(spec, n)
    return rms_dbfs(band[int(s * sr):int(e * sr)])


def _read_wav(path: Path) -> tuple[np.ndarray, int]:
    x, sr = sf.read(str(path), dtype="float64", always_2d=False)
    return x, int(sr)


# ---------------------------------------------------------------------------
# 纯函数：梯形窗 / ducking 包络 / 配置 / 度量
# ---------------------------------------------------------------------------

def test_ramped_rect_shape():
    t = np.linspace(0.0, 4.0, 4001)
    r = ramped_rect(t, 1.0, 3.0, 0.5, 1.0)
    assert r[0] == 0.0 and r[-1] == 0.0
    assert r[500] == pytest.approx(0.0, abs=1e-9)      # t=0.5 < 起点
    assert r[1000] == pytest.approx(0.0, abs=1e-9)     # t=1.0 = 起点（rise 0%）
    assert r[1250] == pytest.approx(0.5, abs=1e-6)     # t=1.25 = rise 50%
    assert r[1500] == pytest.approx(1.0, abs=1e-9)     # t=1.5 = rise 完（hold 起）
    assert r[1750] == pytest.approx(1.0, abs=1e-9)     # hold
    assert r[2000] == pytest.approx(1.0, abs=1e-9)     # t=2.0 = fall 始（t1-fall）
    assert r[2500] == pytest.approx(0.5, abs=1e-6)     # t=2.5 = fall 50%
    assert r[3000] == pytest.approx(0.0, abs=1e-9)     # t=3.0 = t1（fall 完）
    # rise/fall ≤0 → 阶跃边（t≥t0 / t≤t1）
    rect = ramped_rect(t, 1.0, 2.0, 0.0, 0.0)
    assert rect[1000] == 1.0 and rect[1200] == 1.0
    assert rect[800] == 0.0 and rect[2800] == 0.0


def test_duck_gain_levels_and_ramps():
    pad = 0.15
    duck_windows = [(1.0 - pad, 3.0 + pad)]   # 电平区 [-6dB]
    core_windows = [(1.0, 3.0)]               # 句心 [再 -3dB]
    t = np.arange(0, int(6 * 48000)) / 48000
    g = duck_gain(t, duck_windows, core_windows)
    gdb = 20 * np.log10(g)

    def at(ts: float) -> float:
        return float(gdb[int(ts * 48000)])

    # 窗外 0dB（attack 前 / release 后）
    assert at(0.2) == pytest.approx(0.0, abs=0.05)
    assert at(5.0) == pytest.approx(0.0, abs=0.05)
    # 电平区：提前量区 -6dB（attack 完成后 / release 开始前），句心 -9dB
    assert at(0.95) == pytest.approx(-6.0, abs=0.3)    # 左提前量区（s-0.15..s）
    assert at(3.05) == pytest.approx(-6.0, abs=0.3)    # 右提前量区（e..e+0.15）
    assert at(2.0) == pytest.approx(-9.0, abs=0.1)     # 句心：再 -3dB
    # 斜坡贴在窗外：attack [0.80,0.85] 中点 -3dB；release [3.15,3.45] 中点 -3dB
    assert at(0.825) == pytest.approx(-3.0, abs=0.2)
    assert at(3.30) == pytest.approx(-3.0, abs=0.2)
    # 压低沿单调（attack 内只降不升），恢复沿单调（release 内只升不降）
    up = gdb[int(0.80 * 48000):int(0.85 * 48000) + 1]
    assert np.all(np.diff(up) <= 1e-9)
    down = gdb[int(3.15 * 48000):int(3.45 * 48000) + 1]
    assert np.all(np.diff(down) >= -1e-9)
    # 全程不超过 0dB（只压不抬）
    assert g.max() <= 1.0 + 1e-12
    # 多窗重叠取最大压低（不叠加穿透）
    g2 = duck_gain(t, [(0.9, 3.05), (2.9, 5.2)], [(1.0, 3.0), (3.2, 5.0)])
    assert 20 * np.log10(g2[int(1.5 * 48000)]) == pytest.approx(-9.0, abs=0.1)
    assert 20 * np.log10(g2[int(3.1 * 48000)]) == pytest.approx(-6.0, abs=0.3)


def test_params_from_repo_config():
    p = params_from_cfg(load_pipeline_config())
    cfg = load_pipeline_config()
    assert p.duck_db == 6.0 and p.duck_extra_db == 3.0      # "侧链 -6dB，句内再 -3dB"
    assert p.window_pad_s == 0.15
    assert (p.attack_s, p.release_s, p.core_ramp_s) == (0.05, 0.30, 0.02)
    assert p.target_lufs == cfg["loudness_lufs"] == -16.0   # 顶层单一事实源
    assert (p.tp_dbtp, p.lra) == (-1.5, 11.0)
    assert p.min_ratio_db == 8.0                            # 对白可懂度冻结线
    assert p.label_field == "XMP:aiGeneratedContent"
    assert p.service_provider == "未申报主体"


def test_metric_helpers():
    x = np.full(1000, 0.5)
    assert rms_dbfs(x) == pytest.approx(20 * np.log10(0.5))
    assert peak_dbfs(x) == pytest.approx(20 * np.log10(0.5))
    assert interval_rms_dbfs(x, 100, 5.0, 6.0) == pytest.approx(rms_dbfs(x))
    assert interval_rms_dbfs(x, 100, 20.0, 21.0) == -120.0   # 越界 → 兜底
    assert interval_peak_dbfs(x, 100, 0.5, 0.6) == pytest.approx(peak_dbfs(x))


# ---------------------------------------------------------------------------
# 自验收核心：端到端混音 + 三项冻结线
# ---------------------------------------------------------------------------

def test_mix_episode_products_and_durations(workspace: Path):
    rep = mix_episode(EP, LANG, jobs_dir=workspace.parent, compose=True)
    root = workspace
    mix_dir = root / "08_mix"
    for name in (f"dubbed.{LANG}.wav", f"mix.{LANG}.wav", "dubbed.wav", "mix.wav",
                 f"mix_report.{LANG}.json"):
        assert (mix_dir / name).is_file(), name
    out = root / "12_out" / f"{EP}.{LANG}.mp4"
    assert out.is_file()

    # ① 时长差 ≤0.2s（mix / dubbed / 成片 vs master=视频时长）
    master = rep["inputs"]["master_duration_s"]
    assert abs(rep["mix"]["duration_s"] - master) <= 0.2
    assert abs(rep["dubbed"]["duration_s"] - master) <= 0.2
    assert abs(rep["compose"]["duration_s"] - master) <= 0.2
    # 成片口径：48k 立体声 pcm_s16le
    assert sf.info(str(mix_dir / f"mix.{LANG}.wav")).samplerate == 48000
    assert sf.info(str(mix_dir / f"mix.{LANG}.wav")).channels == 2
    # 无后缀副本 = 当前语种产物（内容一致）
    assert filecmp.cmp(mix_dir / f"mix.{LANG}.wav", mix_dir / "mix.wav", shallow=False)

    # 人声时间轴统计：3 合成 + 1 keep_original + 0 缺失 + 1 超窗
    vt = rep["inputs"]["voice_track"]
    assert vt["n_synth"] == 3 and vt["n_keep_original"] == 1 and vt["missing"] == []
    assert [o["utt_id"] for o in vt["overflow"]] == ["ep01-u00003200"]
    assert vt["overflow"][0]["overflow_s"] == pytest.approx(0.6, abs=0.01)


def test_loudness_measured_within_1lu(workspace: Path):
    """② loudnorm 报告 I∈[-17,-15]（T15 ±1LU）：对交付文件复测，不只信报告。"""
    rep = mix_episode(EP, LANG, jobs_dir=workspace.parent, compose=True)
    mix_wav = workspace / "08_mix" / f"mix.{LANG}.wav"
    measured = loudnorm_measure(mix_wav, i=rep["config"]["target_lufs"],
                                tp=rep["config"]["tp_dbtp"], lra=rep["config"]["lra"])
    assert -17.0 <= measured["input_i"] <= -15.0
    assert measured["input_i"] == pytest.approx(rep["loudness"]["final"]["input_i"], abs=0.2)
    assert rep["loudness"]["in_tolerance"] is True
    assert abs(rep["loudness"]["delta_i"]) <= 1.0
    assert rep["loudness"]["measured_raw"]["input_i"] < -15.0   # 归一前确实更轻
    assert rep["loudness"]["mode"] in ("linear", "dynamic", "dynamic-fallback")


def test_ducking_measured_on_deliverable(tmp_path: Path, base_video: Path):
    """对白区间背景电平实测达标：报告实测 + 交付文件频段对拍（关 ducking 对照）。"""
    jobs = tmp_path / "jobs"
    root_main = _build_workspace(jobs / "main", base_video=base_video)
    root_ctrl = _build_workspace(jobs / "ctrl", base_video=base_video)
    rep = mix_episode(EP, LANG, jobs_dir=root_main.parent, compose=False)

    # —— 报告实测（进程内 raw vs ducked，同一参考系）——
    d = rep["ducking"]
    assert d["criteria"]["core_reduction_ge_duck_plus_extra_minus_1p5db"] is True
    assert d["criteria"]["pad_reduction_ge_duck_minus_1db"] is True
    assert d["criteria"]["outside_reduction_le_0p5db"] is True
    assert d["core_reduction_db"] == pytest.approx(9.0, abs=1.5)   # 句心 -9dB
    assert d["pad_reduction_db"] == pytest.approx(6.0, abs=1.0)    # 提前量区 -6dB
    assert d["outside_reduction_db"] == pytest.approx(0.0, abs=0.5)

    # —— 交付文件频段对拍：同交付响度（-16LUFS）下 bgm 频段在句心的压低量 ——
    ctrl_params = MixParams(**{**params_from_cfg(load_pipeline_config()).__dict__,
                               "duck_db": 0.0, "duck_extra_db": 0.0})
    rep_ctrl = mix_episode(EP, LANG, jobs_dir=root_ctrl.parent, compose=False,
                           params=ctrl_params)
    x_main, sr_main = _read_wav(root_main / "08_mix" / f"mix.{LANG}.wav")
    x_ctrl, sr_ctrl = _read_wav(root_ctrl / "08_mix" / f"mix.{LANG}.wav")
    assert sr_main == sr_ctrl == 48000
    # 句心 [0.8,2.4]（两句心取一句；150Hz 频段 ±20Hz）
    i_main = loudnorm_measure(root_main / "08_mix" / f"mix.{LANG}.wav",
                              i=-16.0, tp=-1.5, lra=11.0)["input_i"]
    i_ctrl = loudnorm_measure(root_ctrl / "08_mix" / f"mix.{LANG}.wav",
                              i=-16.0, tp=-1.5, lra=11.0)["input_i"]
    band_main = _band_rms_dbfs(x_main, sr_main, BGM_FREQ, 20.0, 0.8, 2.4)
    band_ctrl = _band_rms_dbfs(x_ctrl, sr_ctrl, BGM_FREQ, 20.0, 0.8, 2.4)
    # 相对各自节目响度的 bgm 频段电平（消除归一化增益差）之差 = ducking 压低量
    rel_main = band_main - i_main
    rel_ctrl = band_ctrl - i_ctrl
    assert (rel_ctrl - rel_main) >= 8.0, (rel_ctrl, rel_main)
    # 句心外（[2.6,3.1] 两句间隙）无压低（bgm 恢复）
    band_main_gap = _band_rms_dbfs(x_main, sr_main, BGM_FREQ, 20.0, 2.6, 3.1)
    band_ctrl_gap = _band_rms_dbfs(x_ctrl, sr_ctrl, BGM_FREQ, 20.0, 2.6, 3.1)
    assert abs((band_main_gap - i_main) - (band_ctrl_gap - i_ctrl)) <= 1.0


def test_voice_presence_and_keep_original_band(workspace: Path):
    """人声摆放在原时间轴上：句窗内人声频段能量 >> 句隙；keep_original 复刻原人声。"""
    rep = mix_episode(EP, LANG, jobs_dir=workspace.parent, compose=True)
    x, sr = _read_wav(workspace / "08_mix" / f"mix.{LANG}.wav")
    prog_i = loudnorm_measure(workspace / "08_mix" / f"mix.{LANG}.wav",
                              i=-16.0, tp=-1.5, lra=11.0)["input_i"]
    # ① 合成句（400Hz）：窗内 vs 句隙
    in_win = _band_rms_dbfs(x, sr, 400.0, 15.0, 0.8, 2.4) - prog_i
    in_gap = _band_rms_dbfs(x, sr, 400.0, 15.0, 2.6, 3.05) - prog_i
    assert in_win - in_gap >= 15.0
    # ② 异采样率合成句（300Hz，22050Hz wav → 重采样路径）
    in_win4 = _band_rms_dbfs(x, sr, 300.0, 15.0, 6.8, 7.6) - prog_i
    in_gap4 = _band_rms_dbfs(x, sr, 300.0, 15.0, 5.0, 5.9) - prog_i
    assert in_win4 - in_gap4 >= 15.0
    # ③ keep_original 句（640Hz 原人声被复刻进混音）
    keep_win = _band_rms_dbfs(x, sr, 640.0, 15.0, 5.0, 6.2) - prog_i
    keep_gap = _band_rms_dbfs(x, sr, 640.0, 15.0, 7.75, 8.0) - prog_i
    assert keep_win - keep_gap >= 15.0
    # ④ dubbed 轨本身含原人声复刻（不经过混音也成立）
    xd, srd = _read_wav(workspace / "08_mix" / f"dubbed.{LANG}.wav")
    assert _band_rms_dbfs(xd, srd, 640.0, 15.0, 5.0, 6.2) - \
        _band_rms_dbfs(xd, srd, 640.0, 15.0, 7.75, 8.0) >= 15.0
    # ⑤ keep_original 句不计入可懂度统计（仅合成句）
    assert rep["intelligibility"]["n_windows"] == 3


def test_intelligibility_ratio(workspace: Path):
    """③ 人声段/bg 峰值比 ≥8dB（规划 §4 M9 冻结线；同步给 RMS 口径）。"""
    rep = mix_episode(EP, LANG, jobs_dir=workspace.parent, compose=True)
    intel = rep["intelligibility"]
    assert intel["n_windows"] == 3
    assert intel["min_voice_bg_peak_ratio_db"] >= 8.0
    assert intel["min_voice_bg_rms_ratio_db"] >= 8.0
    assert intel["criteria_peak_ge_threshold"] is True


def test_final_mp4_has_video_audio_subs_and_ai_bit(workspace: Path):
    rep = mix_episode(EP, LANG, jobs_dir=workspace.parent, compose=True)
    out = workspace / "12_out" / f"{EP}.{LANG}.mp4"
    pr = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format",
         "-print_format", "json", str(out)],
        capture_output=True, text=True, encoding="utf-8", timeout=300).stdout)
    streams = pr["streams"]
    vstreams = [s for s in streams if s["codec_type"] == "video"]
    astreams = [s for s in streams if s["codec_type"] == "audio"]
    assert len(vstreams) == 1 and len(astreams) == 1
    assert int(astreams[0]["sample_rate"]) == 48000
    assert int(astreams[0]["channels"]) == 2
    assert astreams[0]["codec_name"] == "aac"
    # AI 隐式标识位：ffprobe 回读精确匹配（C7 implicit 字段/值）
    tags = dict(pr["format"].get("tags") or {})
    assert tags.get(LABEL_FIELD) == LABEL_VALUE
    assert rep["compose"]["ai_label"]["verified"] is True
    assert rep["compose"]["subs_burned"] is True

    # ASS 确已烧入：抽帧与基带（无字幕）比较，底部字幕带像素有差异
    frame_sub = _extract_frame(out, 1.5)
    frame_base = _extract_frame(workspace / "01_media" / _video_name(), 1.5)
    band = slice(1560, 1720)  # 字幕带（margin_v=220 → y≈1650 附近）
    diff = np.abs(frame_sub[band].astype(int) - frame_base[band].astype(int))
    assert diff.max() > 30, "成片字幕带与基带无差异（ASS 未烧入？）"


def _extract_frame(video: Path, t: float) -> np.ndarray:
    """抽一帧 → HxWx3 uint8 numpy（rawvideo 管道，BGR→RGB）。"""
    w, h = 1080, 1920
    r = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", str(t),
         "-i", str(video), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-"],
        capture_output=True, timeout=300)
    assert r.returncode == 0 and len(r.stdout) == w * h * 3, len(r.stdout)
    return np.frombuffer(r.stdout, dtype=np.uint8).reshape(h, w, 3)


def test_m11_product_mux_path(tmp_path: Path, base_video: Path):
    """M11 成片（已烧字幕）存在时：M9 只替换音频（-c:v copy）+ 补 AI 标识位。"""
    root = _build_workspace(tmp_path / "jobs", base_video=base_video)
    # 以基带视频模拟 M11 产物（已烧字幕的成片路径 12_out/<ep>.<lang>.mp4）
    shutil.copyfile(root / "01_media" / _video_name(),
                    root / "12_out" / f"{EP}.{LANG}.mp4")
    rep = mix_episode(EP, LANG, jobs_dir=root.parent, compose=True)
    comp = rep["compose"]
    assert comp["status"] == "ok"
    assert comp["video_codec"] == "copy" and comp["subs_burned"] is False
    assert comp["ai_label"]["verified"] is True
    assert comp["duration_s"] == pytest.approx(rep["inputs"]["master_duration_s"], abs=0.2)
    # 音频确已替换为混音（非基带原声道）：响度达标
    measured = loudnorm_measure(root / "12_out" / f"{EP}.{LANG}.mp4",
                                i=-16.0, tp=-1.5, lra=11.0)
    assert -17.0 <= measured["input_i"] <= -15.0


def test_missing_synth_wav_warns_and_strict_fails(tmp_path: Path, base_video: Path):
    root = _build_workspace(tmp_path / "jobs", base_video=base_video,
                            missing_wav="ep01-u00000800")
    # 默认：缺失如实 WARN + exit 0（留空不伪造音频）
    rep = mix_episode(EP, LANG, jobs_dir=root.parent, compose=False)
    assert "ep01-u00000800" in rep["inputs"]["voice_track"]["missing"]
    assert rep["inputs"]["voice_track"]["n_synth"] == 2
    assert m9_main(["--ep", EP, "--lang", LANG, "--jobs-dir", str(root.parent),
                    "--no-compose"]) == 0
    assert m9_main(["--ep", EP, "--lang", LANG, "--jobs-dir", str(root.parent),
                    "--no-compose", "--strict-missing"]) == 1


def test_without_labels_falls_back_to_config(tmp_path: Path, base_video: Path):
    """C7 labels.json 缺省 → 标识位回落配置兜底（来源如实标注，值可回读）。"""
    root = _build_workspace(tmp_path / "jobs", base_video=base_video, with_labels=False)
    rep = mix_episode(EP, LANG, jobs_dir=root.parent, compose=True)
    label = rep["compose"]["ai_label"]
    assert label["source"].startswith("config-fallback")
    assert label["value"] == f"{EP}-{LANG}|{params_from_cfg(load_pipeline_config()).service_provider}"
    pr = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format_tags",
         "-print_format", "json", str(root / "12_out" / f"{EP}.{LANG}.mp4")],
        capture_output=True, text=True, encoding="utf-8", timeout=300).stdout)
    assert (pr["format"].get("tags") or {}).get(label["field"]) == label["value"]


# ---------------------------------------------------------------------------
# CLI / 错误路径 / 幂等
# ---------------------------------------------------------------------------

def test_cli_exit0_and_stdout(workspace: Path):
    env = {**os.environ, "PYTHONUTF8": "1"}
    rc = subprocess.run(
        [sys.executable, "-m", "pipeline.m9_mix", "--ep", EP, "--lang", LANG,
         "--jobs-dir", str(workspace.parent)],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=900,
    )
    assert rc.returncode == 0, rc.stdout + rc.stderr
    assert "OK m9_mix" in rc.stdout
    assert "I=" in rc.stdout and "TP=" in rc.stdout
    assert "duck: core" in rc.stdout and "voice/bg peak ratio=" in rc.stdout
    assert (workspace / "12_out" / f"{EP}.{LANG}.mp4").is_file()
    assert (workspace / "08_mix" / f"mix_report.{LANG}.json").is_file()


def test_cli_error_paths(tmp_path: Path, base_video: Path):
    env = {**os.environ, "PYTHONUTF8": "1"}
    root = _build_workspace(tmp_path / "jobs", base_video=base_video)
    jobs = root.parent

    def _cli(*extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "pipeline.m9_mix", "--ep", EP, "--lang", LANG,
             "--jobs-dir", str(jobs), *extra],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=900,
        )

    # 缺 bgm → exit 1
    (root / "01_media" / "bgm.wav").unlink()
    r = _cli("--no-compose")
    assert r.returncode == 1 and "FAIL m9_mix" in r.stdout and "bgm.wav" in r.stdout
    # 缺 C5 → exit 1（先补回 bgm）
    _rebuild_bgm(root)
    (root / "07_synth" / f"synth_plan.{LANG}.jsonl").unlink()
    (root / "07_synth" / "synth_plan.jsonl").unlink(missing_ok=True)
    r2 = _cli("--no-compose")
    assert r2.returncode == 1 and "C5" in r2.stdout
    # 缺 C2 → exit 1
    _rebuild_plan(root)
    (root / "04_dial" / "utterances.jsonl").unlink()
    r3 = _cli("--no-compose")
    assert r3.returncode == 1 and "C2" in r3.stdout


def _rebuild_bgm(root: Path) -> None:
    bgm = _tone(BGM_FREQ, MASTER_DUR, SR, amp=BGM_AMP)
    sf.write(root / "01_media" / "bgm.wav",
             np.stack([bgm, bgm], axis=1).astype(np.float32), SR, subtype="PCM_16")


def _rebuild_plan(root: Path) -> None:
    items = [
        C.SynthPlanItem(
            utt_id=u, engine="dub-tts", voice_ref=f"05_cast/voicebank/{u}_ref.wav",
            emo_ref=None, emo_alpha=0.7, duration_factor=1.0, atempo=1.0,
            text=f"line {i + 1}", out=f"07_synth/wavs/{u}.wav",
            expect_dur=round(e - s, 3), keep_original=(src == "original"))
        for i, (u, s, e, src, _f, _sr, _x) in enumerate(CORPUS)
    ]
    C.dump_jsonl(root / "07_synth" / f"synth_plan.{LANG}.jsonl",
                 C.SynthPlanTable.model_validate(items))


def test_no_compose_skips_final_mp4(tmp_path: Path, base_video: Path):
    root = _build_workspace(tmp_path / "jobs", base_video=base_video)
    rep = mix_episode(EP, LANG, jobs_dir=root.parent, compose=False)
    assert rep["compose"]["status"] == "skipped"
    assert rep["compose"]["reason"] == "--no-compose"
    assert not (root / "12_out" / f"{EP}.{LANG}.mp4").exists()
    assert (root / "08_mix" / f"mix.{LANG}.wav").is_file()


def test_idempotent_rerun(workspace: Path):
    r1 = mix_episode(EP, LANG, jobs_dir=workspace.parent, compose=True)
    r2 = mix_episode(EP, LANG, jobs_dir=workspace.parent, compose=True)
    assert r1["mix"]["duration_s"] == r2["mix"]["duration_s"]
    assert r1["loudness"]["final"]["input_i"] == pytest.approx(
        r2["loudness"]["final"]["input_i"], abs=1e-6)
    assert (workspace / "08_mix" / f"mix.{LANG}.wav").is_file()
