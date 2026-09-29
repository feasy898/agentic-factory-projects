"""M9 混音 + 成片合成（规划 §4 M9；任务 T15 定案口径，【本机】零 GPU 依赖，全离线可验收）。

职责（只读 01_media / 04_dial / 07_synth / 10_subs / 11_labels，只写 08_mix / 12_out）：
  ① 人声时间轴 ``08_mix/dubbed.<lang>.wav``：C5（``07_synth/synth_plan.<lang>.jsonl``）
    逐句把合成 wav 按 C2 句窗起点摆到原时间轴上（句间隙保留原时间轴）；``keep_original``
    句（nonverbal/缺译文，冻结规则 4）复刻 ``04_dial/vocals.wav`` 对应区间原人声；
    超窗末尾按 C2 句窗裁切并在报告记 ``overflow_s``；缺合成文件如实记 ``missing``
    （不静默补静音假装成功，``--strict-missing`` 可升级为 exit 1）。
  ② 背景 ducking + 混音 ``08_mix/mix.<lang>.wav``：``01_media/bgm.wav``（M3 背景轨）
    按 C2 句窗驱动包络压低 —— **窗内（句窗±提前量）−6dB、句心（C2 窗内）再 −3dB**，
    attack/release 斜坡避免抽吸感 → 48k 立体声与新人声相加 → 峰值保护。
  ③ EBU R128 响度归一（``-16 LUFS``，短剧平台惯例；TP=-1.5dBTP/LRA=11 取
     :data:`pipeline.m1_ingest.TRUE_PEAK_DBTP` / :data:`pipeline.m1_ingest.LRA`）：
    两趟 loudnorm（先测量、后 linear 应用），产出后复测 I/TP/LRA 入报告；
    linear 结果超出 ±1LU 容差时如实回落单趟 dynamic 并记录所用模式。
  ④ 成片合成 ``12_out/<ep>.<lang>.mp4``：画面（M11 已烧字幕的成片优先，否则
    擦除基带/原片 + 烧 ``10_subs/tgt.<lang>.ass``）+ 混音响轨（AAC 192k/48k/立体声）
    + **AI 隐式标识元数据位**（C7 ``implicit``：``-metadata <field>=<value>``，
    mp4 需 ``-movflags +use_metadata_tags`` 才能落任意键，落盘后 ffprobe 回读校验）。
     显式 drawtext 片头标识 / C2PA manifest / 音频水印属 M12（T16+），本模块只写
     隐式元数据位，不与 M12 重复绘制（职责边界见 docs/m9_mix_notes.md）。

口径定案（任务 T15，与规划 §4 M9 原文的对应关系）：
  - "bgm 侧链 −6dB" 落地为**确定性的语音驱动侧链**：包络由 C2 句窗 + 合成人声实际
    摆放驱动（ attack/release 斜坡的乘性增益），而非 ffmpeg ``sidechaincompress``
    的信号相关压缩 —— 后者的压低深度依赖语音瞬时电平，无法复现到 ±1dB，eval 冻结线
    （对白区间背景电平实测达标）无从判定；窗口法在 B1 样本上可精确实测与回归。
  - "句内再 −3dB" = 句心（C2 句窗内部）在窗压低 −6dB 基础上再 −3dB（合计 −9dB），
    斜坡 ``core_ramp_s`` 默认 20ms；窗 = 句窗四边外扩 ``window_pad_s``（默认 0.15s
    提前量，语音进入前 bgm 已就位 —— 生产 ducking 惯例，也使两个电平层级可分辨）。
  - 时长基准（master）= 01_media 视频时长（ffprobe），缺视频时回退 bgm 时长；
    人声/背景轨按 master 截断或补零（eval 冻结线：成片/混音时长差 ≤0.2s）。
  - 响度容差 ±1LU（T15 自验收口径；规划 §4 M9 的 ``I∈[-17,-15]`` 为其整数化表述）。

契约与边界（B1 冻结规则 9：只通过契约交换）：
  - 只读：01_media/{bgm.wav, video_*.mp4, video_*_clean.mp4}、04_dial/{vocals.wav,
    utterances.jsonl}、07_synth/{synth_plan.<lang>.jsonl, wavs/*.wav}、
    10_subs/{tgt.<lang>.ass, src.ass}、11_labels/labels.json；
    不写任何冻结契约（C2/C5 一律只读；C7 labels.json 只读不写）。
  - 写入：08_mix/{dubbed,mix}.<lang>.wav（+ 无后缀当前语种副本，对齐规划 §3 布局）、
    08_mix/mix_report.<lang>.json（工作纸、非冻结契约）、12_out/<ep>.<lang>.mp4。
  - 多语种分文件：同 M8 的理由（音频无语种键），按 --lang 分文件 + 无后缀副本。

CLI（规划 §4 M9 冻结形态）::

    python -m pipeline.m9_mix --ep ep01 --lang en
    python -m pipeline.m9_mix --ep ep01 --lang en --jobs-dir <dir> [--no-compose]
        [--target-lufs -16] [--strict-missing] [--strict-loudness]

退出码：0 成功（响度/缺失等质量问题按 WARN 记入报告）；1 输入/执行错误或
``--strict-missing`` 下有合成文件缺失；2 用法错误。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np
import soundfile as sf

from pipeline import contracts as C
from pipeline.config import load_pipeline_config
from pipeline.m1_ingest import FFMPEG, FFPROBE, LRA, TRUE_PEAK_DBTP
from pipeline.scaffold import create_workspace, ep_dir

__all__ = [
    "MixError",
    "MixParams",
    "params_from_cfg",
    "ramped_rect",
    "duck_gain",
    "rms_dbfs",
    "peak_dbfs",
    "interval_rms_dbfs",
    "interval_peak_dbfs",
    "region_reduction_db",
    "loudnorm_measure",
    "loudnorm_apply",
    "build_voice_track",
    "mix_episode",
    "main",
]

# ---------------------------------------------------------------------------
# 冻结常量（configs/pipeline.yaml ``m9`` 段可覆盖；默认值=本文件事实源）
# ---------------------------------------------------------------------------

#: 支持的目标语（与 M8/M11 同口径）
SUPPORTED_LANGS = ("en", "es", "ar")
#: 混音产物口径：48k 立体声（规划 §4 M9 "48k 立体声 mix.wav"）
MIX_SR = 48000
MIX_CHANNELS = 2
#: 人声轨（dubbed.wav）口径：48k 单声道（人声本质单声道；报告如实记 channels）
DUBBED_SR = 48000
DUBBED_CHANNELS = 1
#: ducking 默认参数（"bgm 侧链 -6dB，句内再 -3dB"）
DEFAULT_DUCK_DB = 6.0
DEFAULT_DUCK_EXTRA_DB = 3.0
DEFAULT_ATTACK_S = 0.05        # 压低沿（快进，防语音削头）
DEFAULT_RELEASE_S = 0.30       # 恢复沿（慢出，防抽吸）
DEFAULT_CORE_RAMP_S = 0.02     # 句心额外 -3dB 的斜坡
DEFAULT_WINDOW_PAD_S = 0.15    # ducking 窗相对 C2 句窗的外扩提前量
#: 增益台（0=不台；生产可按素材把 bgm 台到与人声相称的裕量）
DEFAULT_VOICE_GAIN_DB = 0.0
DEFAULT_BGM_GAIN_DB = 0.0
#: 响度口径（TP/LRA 取 m1_ingest 的 EBU R128 惯例常量）
DEFAULT_TARGET_LUFS = -16.0
LOUDNESS_TOL_LU = 1.0          # T15 自验收：实测 I 与目标差 ≤1LU
#: 对白可懂度冻结线（规划 §4 M9：人声段/bg 峰值比 ≥8dB）
DEFAULT_MIN_RATIO_DB = 8.0
#: 时长差容差（与 M1 同一口径）
DUR_TOL_S = 0.2
#: 成片音频编码档
AAC_BITRATE = "192k"
#: 成片视频编码档（烧字幕时；与 M11 BURN_CRF 同口径）
BURN_CRF = 18
#: 隐式标识元数据位缺省键/主体（11_labels/labels.json 缺省时的兜底，报告记来源）
DEFAULT_LABEL_FIELD = "XMP:aiGeneratedContent"
DEFAULT_SERVICE_PROVIDER = "未申报主体"


class MixError(RuntimeError):
    """M9 混音/合成失败（输入缺失/契约校验失败/ffmpeg 执行错误等）。"""


@dataclass(frozen=True)
class MixParams:
    """M9 策略常量（configs/pipeline.yaml ``m9`` 段可覆盖）。"""

    target_lufs: float = DEFAULT_TARGET_LUFS
    tp_dbtp: float = TRUE_PEAK_DBTP
    lra: float = LRA
    duck_db: float = DEFAULT_DUCK_DB
    duck_extra_db: float = DEFAULT_DUCK_EXTRA_DB
    attack_s: float = DEFAULT_ATTACK_S
    release_s: float = DEFAULT_RELEASE_S
    core_ramp_s: float = DEFAULT_CORE_RAMP_S
    window_pad_s: float = DEFAULT_WINDOW_PAD_S
    voice_gain_db: float = DEFAULT_VOICE_GAIN_DB
    bgm_gain_db: float = DEFAULT_BGM_GAIN_DB
    min_ratio_db: float = DEFAULT_MIN_RATIO_DB
    label_field: str = DEFAULT_LABEL_FIELD
    service_provider: str = DEFAULT_SERVICE_PROVIDER


def params_from_cfg(cfg: Optional[dict[str, Any]]) -> MixParams:
    """configs/pipeline.yaml → :class:`MixParams`（响度目标缺省取顶层 ``loudness_lufs``）。"""
    cfg = cfg or {}
    m9 = cfg.get("m9") or {}
    label = m9.get("label") or {}
    # 顶层 loudness_lufs 为单一事实源；m9.target_lufs 仅作显式覆盖（缺省不同才生效）
    target = m9.get("target_lufs", cfg.get("loudness_lufs", DEFAULT_TARGET_LUFS))
    return MixParams(
        target_lufs=float(target),
        tp_dbtp=float(m9.get("tp_dbtp", TRUE_PEAK_DBTP)),
        lra=float(m9.get("lra", LRA)),
        duck_db=float(m9.get("duck_db", DEFAULT_DUCK_DB)),
        duck_extra_db=float(m9.get("duck_extra_db", DEFAULT_DUCK_EXTRA_DB)),
        attack_s=float(m9.get("attack_s", DEFAULT_ATTACK_S)),
        release_s=float(m9.get("release_s", DEFAULT_RELEASE_S)),
        core_ramp_s=float(m9.get("core_ramp_s", DEFAULT_CORE_RAMP_S)),
        window_pad_s=float(m9.get("window_pad_s", DEFAULT_WINDOW_PAD_S)),
        voice_gain_db=float(m9.get("voice_gain_db", DEFAULT_VOICE_GAIN_DB)),
        bgm_gain_db=float(m9.get("bgm_gain_db", DEFAULT_BGM_GAIN_DB)),
        min_ratio_db=float(m9.get("min_ratio_db", DEFAULT_MIN_RATIO_DB)),
        label_field=str(label.get("metadata_field", DEFAULT_LABEL_FIELD)),
        service_provider=str(label.get("service_provider", DEFAULT_SERVICE_PROVIDER)),
    )


# ---------------------------------------------------------------------------
# ffmpeg/ffprobe 子进程
# ---------------------------------------------------------------------------

def _run(cmd: list[str], *, timeout_s: float = 900.0, cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    """执行外部命令（utf-8；失败抛 MixError，stderr 尾部入消息）。"""
    if shutil.which(cmd[0]) is None:
        raise MixError(f"未找到可执行文件 {cmd[0]!r}（请确认 ffmpeg/ffprobe 已安装并在 PATH）")
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout_s, cwd=str(cwd) if cwd else None,
        )
    except subprocess.TimeoutExpired as exc:
        raise MixError(f"命令超时（>{timeout_s:.0f}s）: {' '.join(cmd[:8])}...") from exc


def _run_ffmpeg(cmd: list[str], *, cwd: Optional[Path] = None,
                timeout_s: float = 1800.0) -> subprocess.CompletedProcess:
    r = _run(cmd, timeout_s=timeout_s, cwd=cwd)
    if r.returncode != 0:
        tail = (r.stderr or "")[-2000:]
        raise MixError(f"ffmpeg 失败（rc={r.returncode}）: {tail}")
    return r


def _probe_duration(path: Path) -> float:
    """ffprobe format.duration（秒）。用于 master 时长与产物时长校验。"""
    r = _run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
              "-print_format", "json", str(path)], timeout_s=300.0)
    if r.returncode != 0:
        raise MixError(f"ffprobe 失败: {(r.stderr or '').strip()[:300]}")
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise MixError(f"ffprobe 输出缺 duration: {path}") from exc


def _video_path(root: Path, cfg: dict[str, Any]) -> Optional[Path]:
    """M1 口径的视频产物路径（configs media 段几何）。"""
    media = {**{"width": 1080, "height": 1920, "fps": 25}, **(cfg.get("media") or {})}
    w, h, fps = int(media["width"]), int(media["height"]), int(media["fps"])
    return root / "01_media" / f"video_{w}x{h}_{fps}fps.mp4"


# ---------------------------------------------------------------------------
# ducking 包络（确定性语音驱动侧链；纯函数，可单测）
# ---------------------------------------------------------------------------

def ramped_rect(t: np.ndarray, t0: float, t1: float, rise: float, fall: float) -> np.ndarray:
    """梯形窗：t<t0 为 0，rise 秒内升到 1，保持，fall 秒内降回 0（t>t1 为 0）。

    rise/fall ≤0 时相应边退化为阶跃（t≥t0 / t≤t1）。向量化实现（整轨一次算完，
    无 Python 逐样本循环）。
    """
    t = np.asarray(t, dtype=np.float64)
    rise = max(float(rise), 0.0)
    fall = max(float(fall), 0.0)
    up = ((t >= t0).astype(np.float64) if rise <= 0
          else np.clip((t - t0) / rise, 0.0, 1.0))
    down = ((t <= t1).astype(np.float64) if fall <= 0
            else np.clip((t1 - t) / fall, 0.0, 1.0))
    return up * down


def duck_gain(
    t: np.ndarray,
    duck_windows: list[tuple[float, float]],
    core_windows: list[tuple[float, float]],
    *,
    duck_db: float = DEFAULT_DUCK_DB,
    extra_db: float = DEFAULT_DUCK_EXTRA_DB,
    attack_s: float = DEFAULT_ATTACK_S,
    release_s: float = DEFAULT_RELEASE_S,
    core_ramp_s: float = DEFAULT_CORE_RAMP_S,
) -> np.ndarray:
    """bgm 乘性压低包络（线性增益，与 ``t`` 等长）。

    - ``duck_windows``（句窗±提前量）**区间内**：−duck_db；进入前 attack_s 斜坡
      压低、离开后 release_s 斜坡恢复（斜坡在区间外，窗内电平恒定可实测）；
    - ``core_windows``（C2 句窗内）再 −extra_db（core_ramp_s 斜坡）；
    - 窗外：0dB。多窗重叠取最大压低（max 组合，相加区不叠加穿透）。
    """
    t = np.asarray(t, dtype=np.float64)
    duck_mask = np.zeros_like(t)
    for w0, w1 in duck_windows:
        # 斜坡贴在窗外：rise 段 = [w0-attack, w0]，fall 段 = [w1, w1+release]
        duck_mask = np.maximum(
            duck_mask, ramped_rect(t, w0 - attack_s, w1 + release_s, attack_s, release_s))
    core_mask = np.zeros_like(t)
    for c0, c1 in core_windows:
        core_mask = np.maximum(core_mask, ramped_rect(t, c0, c1, core_ramp_s, core_ramp_s))
    gain_db = -(float(duck_db) * duck_mask + float(extra_db) * core_mask)
    return np.power(10.0, gain_db / 20.0)


# ---------------------------------------------------------------------------
# 度量原语（dBFS；全零/极小值以 -120dBFS 兜底，同 M3 口径）
# ---------------------------------------------------------------------------

def rms_dbfs(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=np.float64)
    r = float(np.sqrt(np.mean(np.square(x))) if x.size else 0.0)
    return float(max(20.0 * np.log10(r) if r > 0 else -120.0, -120.0))


def peak_dbfs(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=np.float64)
    p = float(np.max(np.abs(x))) if x.size else 0.0
    return float(max(20.0 * np.log10(p) if p > 0 else -120.0, -120.0))


def _slice(x: np.ndarray, sr: int, s: float, e: float) -> np.ndarray:
    i0, i1 = max(0, int(s * sr)), min(x.shape[0], int(e * sr))
    return x[i0:i1] if i1 > i0 else np.zeros(0)


def interval_rms_dbfs(x: np.ndarray, sr: int, s: float, e: float) -> float:
    return rms_dbfs(_slice(x, sr, s, e))


def interval_peak_dbfs(x: np.ndarray, sr: int, s: float, e: float) -> float:
    return peak_dbfs(_slice(x, sr, s, e))


def region_reduction_db(raw_dbfs: float, ducked_dbfs: float) -> float:
    """压低量（dB）：raw − ducked（ducked 越负越大；负值=反而抬升，如实可负）。"""
    if raw_dbfs <= -119.0 or ducked_dbfs <= -119.0:
        return 0.0
    return round(raw_dbfs - ducked_dbfs, 2)


# ---------------------------------------------------------------------------
# EBU R128 响度归一（ffmpeg loudnorm 两趟：测量 → linear 应用 → 复测）
# ---------------------------------------------------------------------------

#: loudnorm print_format=json 的测量块（stderr，INFO 级；单层花括号）
_LOUDNORM_JSON_RE = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)


def loudnorm_measure(path: Path, *, i: float, tp: float, lra: float) -> dict[str, Any]:
    """loudnorm 第一趟测量 → {"input_i","input_tp","input_lra","input_thresh","target_offset",...}。"""
    r = _run(
        [FFMPEG, "-hide_banner", "-loglevel", "info", "-i", str(path),
         "-af", f"loudnorm=I={i}:TP={tp}:LRA={lra}:print_format=json",
         "-f", "null", "-"],
        timeout_s=900.0,
    )
    m = _LOUDNORM_JSON_RE.search(r.stderr or "")
    if not m:
        raise MixError(f"loudnorm 测量失败（未解析到 JSON）: {path}\n{(r.stderr or '')[-500:]}")
    data = json.loads(m.group(0))
    return {
        "input_i": float(data["input_i"]),
        "input_tp": float(data["input_tp"]),
        "input_lra": float(data["input_lra"]),
        "input_thresh": float(data["input_thresh"]),
        "target_offset": float(data.get("target_offset", 0.0)),
        "output_i": float(data.get("output_i", "nan")),
        "normalization_type": str(data.get("normalization_type", "unknown")),
    }


def _fmt_num(v: float) -> str:
    """loudnorm 数值参数序列化（保留精度；避免 1e-05 科学计数法被滤镜解析拒绝）。"""
    return repr(round(float(v), 4))


def loudnorm_apply(
    src: Path, dst: Path, measured: dict[str, Any], *, i: float, tp: float, lra: float,
    sr: int = MIX_SR, channels: int = MIX_CHANNELS,
) -> float:
    """loudnorm 第二趟（linear 应用 measured_*，静态增益变速不变幅）→ 施加的增益 dB。

    loudnorm 内部固定 192k 处理，故链尾 ``aresample=<sr>`` 回口径 + ``-ar/-ac`` 钉死。
    注：linear=true 的应用趟**不打印** normalization_type（实测 ffmpeg 6.1.1），
    故此处返回按 measured 推算的目标增益（``i - input_i + target_offset``）；
    实际生效模式由调用方复测判定（见 :func:`_normalize_loudness`）。
    """
    af = (
        f"loudnorm=I={i}:TP={tp}:LRA={lra}"
        f":measured_I={_fmt_num(measured['input_i'])}"
        f":measured_TP={_fmt_num(measured['input_tp'])}"
        f":measured_LRA={_fmt_num(measured['input_lra'])}"
        f":measured_thresh={_fmt_num(measured['input_thresh'])}"
        f":offset={_fmt_num(measured['target_offset'])}:linear=true"
        f",aresample={sr}"
    )
    _run_ffmpeg([FFMPEG, "-y", "-hide_banner", "-loglevel", "info", "-i", str(src),
                 "-af", af, "-ar", str(sr), "-ac", str(channels),
                 "-c:a", "pcm_s16le", str(dst)])
    return round(i - measured["input_i"] + measured.get("target_offset", 0.0), 3)


def _normalize_loudness(
    raw_wav: Path, out_wav: Path, *, params: MixParams, workdir: Path,
) -> dict[str, Any]:
    """两趟归一 + 复测；linear 结果超 ±1LU 容差时如实回落单趟 dynamic。返回报告段。"""
    i, tp, lra = params.target_lufs, params.tp_dbtp, params.lra
    measured = loudnorm_measure(raw_wav, i=i, tp=tp, lra=lra)
    gain_db = loudnorm_apply(raw_wav, out_wav, measured, i=i, tp=tp, lra=lra)
    final = loudnorm_measure(out_wav, i=i, tp=tp, lra=lra)
    mode = "linear"
    if abs(final["input_i"] - i) > LOUDNESS_TOL_LU:
        # linear 应用不达容差（极端动态范围/TP 受限）：如实回落单趟 dynamic 再复测
        dyn = workdir / "mix_dynamic.wav"
        _run_ffmpeg([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(raw_wav),
                     "-af", f"loudnorm=I={i}:TP={tp}:LRA={lra},aresample={MIX_SR}",
                     "-ar", str(MIX_SR), "-ac", str(MIX_CHANNELS),
                     "-c:a", "pcm_s16le", str(dyn)])
        redone = loudnorm_measure(dyn, i=i, tp=tp, lra=lra)
        if abs(redone["input_i"] - i) <= abs(final["input_i"] - i):
            shutil.copyfile(dyn, out_wav)
            mode = "dynamic-fallback"
            final = redone
    return {
        "target_i": i, "target_tp": tp, "target_lra": lra,
        "measured_raw": measured, "mode": mode, "final": final,
        "linear_gain_db": gain_db,
        "delta_i": round(final["input_i"] - i, 2),
        "in_tolerance": bool(abs(final["input_i"] - i) <= LOUDNESS_TOL_LU),
    }


# ---------------------------------------------------------------------------
# 人声时间轴（C5 逐句摆放到原时间轴；keep_original 复刻原人声）
# ---------------------------------------------------------------------------

def _load_mono(path: Path, *, sr: int, workdir: Path) -> np.ndarray:
    """读 wav → 单声道 float64（采样率不符时经 ffmpeg 重采样，避免线性插值混叠）。"""
    info = sf.info(str(path))
    if info.samplerate == sr and info.channels == 1:
        data, _ = sf.read(str(path), dtype="float64", always_2d=True)
        return data.mean(axis=1)
    dst = workdir / f"{path.stem}_{sr}mono.wav"
    _run_ffmpeg([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(path),
                 "-ar", str(sr), "-ac", "1", "-c:a", "pcm_f32le", str(dst)])
    data, _ = sf.read(str(dst), dtype="float64", always_2d=True)
    return data.mean(axis=1)


def build_voice_track(
    utts: list[C.Utterance],
    plan: dict[str, C.SynthPlanItem],
    *,
    root: Path,
    master_dur: float,
    workdir: Path,
    vocals_path: Optional[Path] = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """C2+C5 → 48k 单声道人声时间轴（句间隙保留原时间轴）+ 统计。

    - ``keep_original``：复刻 ``04_dial/vocals.wav`` 的 [start,end) 区间原人声；
    - 其余：读 C5 ``out`` 合成 wav，从 ``start`` 摆放；超出句窗部分裁切并记 overflow；
    - 缺合成文件：记 ``missing``（留空，不伪造音频）；C5 缺行的句子同样记 ``missing``。
    """
    n = int(round(master_dur * DUBBED_SR))
    track = np.zeros(n, dtype=np.float64)
    stats: dict[str, Any] = {
        "n_utts": len(utts), "n_synth": 0, "n_keep_original": 0,
        "missing": [], "overflow": [], "items": [],
    }
    vocals: Optional[np.ndarray] = None
    need_original = any(plan.get(u.utt_id) is not None and plan[u.utt_id].keep_original
                        for u in utts)
    if need_original:
        if vocals_path is None or not vocals_path.is_file():
            raise MixError(
                "C5 含 keep_original 句但 04_dial/vocals.wav 缺失（M3 分离产物）"
            )
        vocals = _load_mono(vocals_path, sr=DUBBED_SR, workdir=workdir)

    for u in utts:
        item = plan.get(u.utt_id)
        i0 = max(0, int(round(u.start * DUBBED_SR)))
        if i0 >= n:
            stats["missing"].append(u.utt_id)
            continue
        source = "original"
        wav_path: Optional[Path] = None
        if item is None:
            stats["missing"].append(u.utt_id)  # C5 缺行：如实记缺，不摆任何音频
            continue
        if item.keep_original:
            source = "original"
            i1 = min(n, int(round(u.end * DUBBED_SR)))
            seg = vocals[i0:i1] if vocals is not None else np.zeros(0)
            avail = len(seg)
            if avail < i1 - i0:  # 原人声轨短于句窗：补零（保持时间轴，不丢起点）
                seg = np.pad(seg, (0, i1 - i0 - avail))
            stats["n_keep_original"] += 1
            meas_dur = round(avail / DUBBED_SR, 3)
            track[i0:i1] += seg
        else:
            source = "synth"
            wav_path = root / item.out
            if not wav_path.is_file():
                stats["missing"].append(u.utt_id)
                continue
            seg = _load_mono(wav_path, sr=DUBBED_SR, workdir=workdir)
            stats["n_synth"] += 1
            meas_dur = round(len(seg) / DUBBED_SR, 3)
            # 句间隙保留原时间轴：从 start 摆放，超出句窗末尾裁切（记 overflow）
            place_end = min(n, i0 + len(seg))
            overflow_s = round(max(0.0, (i0 + len(seg)) / DUBBED_SR - u.end), 3)
            if overflow_s > 0:
                stats["overflow"].append({"utt_id": u.utt_id, "overflow_s": overflow_s})
            seg = seg[: max(0, place_end - i0)]
            track[i0:place_end] += seg
        stats["items"].append({
            "utt_id": u.utt_id, "source": source,
            "wav": (str(wav_path.relative_to(root).as_posix()) if wav_path else
                    ("04_dial/vocals.wav" if source == "original" else None)),
            "window": [round(u.start, 3), round(u.end, 3)],
            "meas_dur": meas_dur,
            "expect_dur": item.expect_dur,
            "placed_rms_dbfs": round(interval_rms_dbfs(track, DUBBED_SR, u.start, u.end), 2),
        })
    return track, stats


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def _write_json_atomic(path: Path, payload: Any) -> None:
    """单文档 JSON 原子写（与 M6/M8 同口径：tmp + os.replace）。"""
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1,
                              default=lambda o: o.item() if isinstance(o, np.generic) else str(o)) + "\n",
                   encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _load_bgm(path: Path, *, params: MixParams, workdir: Path) -> tuple[np.ndarray, dict[str, Any]]:
    """bgm.wav → 48k 立体声 float64（+bgm_gain_db 增益台）。"""
    info = sf.info(str(path))
    if info.samplerate == MIX_SR and info.channels == MIX_CHANNELS:
        data, _ = sf.read(str(path), dtype="float64", always_2d=True)
    else:
        dst = workdir / f"bgm_{MIX_SR}x{MIX_CHANNELS}.wav"
        _run_ffmpeg([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(path),
                     "-ar", str(MIX_SR), "-ac", str(MIX_CHANNELS),
                     "-c:a", "pcm_f32le", str(dst)])
        data, _ = sf.read(str(dst), dtype="float64", always_2d=True)
    if params.bgm_gain_db:
        data = data * (10.0 ** (params.bgm_gain_db / 20.0))
    return data, {"path": str(path), "sample_rate": int(info.samplerate),
                  "channels": int(info.channels),
                  "duration_s": round(float(info.frames) / info.samplerate, 3)}


def _resolve_label(root: Path, ep: str, lang: str, params: MixParams) -> dict[str, Any]:
    """AI 隐式标识位：C7 labels.json（只读）优先，缺省回落配置兜底（如实记来源）。"""
    labels_path = root / "11_labels" / "labels.json"
    if labels_path.is_file():
        try:
            labels = C.load_model(labels_path, C.Labels)
        except Exception as exc:  # noqa: BLE001 —— 契约校验失败 = 真实故障，不静默兜底
            raise MixError(f"11_labels/labels.json 契约校验失败: {exc}") from exc
        return {
            "field": labels.implicit.metadata_field,
            "value": labels.implicit.value,
            "source": "11_labels/labels.json (C7 implicit)",
            "content_id": labels.content_id,
            "standard": labels.standard,
        }
    return {
        "field": params.label_field,
        "value": f"{ep}-{lang}|{params.service_provider}",
        "source": "config-fallback（11_labels/labels.json 缺省）",
        "content_id": f"{ep}-{lang}",
        "standard": "GB45438-2025",
    }


def _ffprobe_format_tags(path: Path) -> dict[str, str]:
    r = _run([FFPROBE, "-v", "error", "-show_entries", "format_tags",
              "-print_format", "json", str(path)], timeout_s=300.0)
    if r.returncode != 0:
        raise MixError(f"ffprobe 失败: {(r.stderr or '').strip()[:300]}")
    try:
        return dict(json.loads(r.stdout).get("format", {}).get("tags", {}) or {})
    except json.JSONDecodeError as exc:
        raise MixError(f"ffprobe tags 解析失败: {path}") from exc


def _compose_final(
    root: Path, ep: str, lang: str, *, cfg: dict[str, Any], params: MixParams,
    mix_wav: Path, master_dur: float, label: dict[str, Any],
) -> dict[str, Any]:
    """画面 + 混音响轨 + ASS 字幕 + AI 隐式标识位 → 12_out/<ep>.<lang>.mp4。

    M11 成片（已烧字幕）存在时只做音频替换（``-c:v copy``，不二次编码）；
    否则取擦除基带/原片并自行烧 ``10_subs/tgt.<lang>.ass``（M11 同款 cwd 相对引用）。
    成片与 M11 产物同路径 → 先写临时文件再原子替换，绝不边读边写。
    """
    out_path = root / "12_out" / f"{ep}.{lang}.mp4"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    m11_out = out_path  # M11 也写这个路径：存在即视为"已烧字幕的成片"

    subs_dir = root / "10_subs"
    tgt_ass = subs_dir / f"tgt.{lang}.ass"
    src_ass = subs_dir / "src.ass"
    burn_ass: Optional[Path] = None
    copy_video = False
    if m11_out.is_file():
        source = m11_out
        copy_video = True  # M11 已烧字幕 → 不重压
    else:
        media = {**{"width": 1080, "height": 1920, "fps": 25}, **(cfg.get("media") or {})}
        w, h, fps = int(media["width"]), int(media["height"]), int(media["fps"])
        clean = root / "01_media" / f"video_{w}x{h}_{fps}fps_clean.mp4"
        base = root / "01_media" / f"video_{w}x{h}_{fps}fps.mp4"
        if not clean.is_file() and not base.is_file():
            return {"status": "skipped", "reason": "无视频输入（01_media 缺 M1 产物）",
                    "out": str(out_path)}
        source = clean if clean.is_file() else base
        burn_ass = tgt_ass if tgt_ass.is_file() else (src_ass if src_ass.is_file() else None)
        if burn_ass is None:
            return {"status": "skipped",
                    "reason": f"无字幕文件（{tgt_ass.name}/{src_ass.name} 均缺）",
                    "out": str(out_path), "source_video": str(source)}

    tmp_out = out_path.with_name(out_path.name + ".compose.tmp.mp4")
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(source), "-i", str(mix_wav)]
    if burn_ass is not None:
        cmd += ["-vf", f"ass={burn_ass.name}"]
    cmd += ["-map", "0:v:0", "-map", "1:a:0"]
    if copy_video:
        cmd += ["-c:v", "copy"]
    else:
        cmd += ["-c:v", "libx264", "-crf", str(BURN_CRF), "-preset", "medium",
                "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "aac", "-b:a", AAC_BITRATE, "-ar", str(MIX_SR), "-ac", str(MIX_CHANNELS),
            "-movflags", "+faststart+use_metadata_tags",
            "-metadata", f"{label['field']}={label['value']}",
            str(tmp_out)]
    _run_ffmpeg(cmd, cwd=(burn_ass.parent if burn_ass is not None else None), timeout_s=3600.0)
    os.replace(tmp_out, out_path)

    tags = _ffprobe_format_tags(out_path)
    verified = tags.get(label["field"]) == label["value"]
    dur = _probe_duration(out_path)
    return {
        "status": "ok", "out": str(out_path), "source_video": str(source),
        "subs_burned": burn_ass is not None,
        "ass": str(burn_ass) if burn_ass is not None else "m11-product（已烧）",
        "video_codec": "copy" if copy_video else "libx264",
        "audio_codec": f"aac {AAC_BITRATE} {MIX_SR}Hz x{MIX_CHANNELS}",
        "duration_s": round(dur, 3),
        "duration_delta_s": round(dur - master_dur, 3),
        "ai_label": {**label, "verified": verified,
                     "movflags": "+faststart+use_metadata_tags",
                     "note": "隐式元数据位；显式 drawtext/C2PA/音频水印属 M12"},
    }


def mix_episode(
    ep: str,
    lang: str,
    *,
    jobs_dir: str | Path,
    cfg: Optional[dict[str, Any]] = None,
    params: Optional[MixParams] = None,
    compose: bool = True,
) -> dict[str, Any]:
    """M9 主流程：bgm + 合成人声 → ducking 混音 → R128 归一 → 成片合成。

    返回摘要 dict（响度实测/ducking 实测/可懂度比值/产物路径），供 CLI 与 eval 断言。
    """
    t_start = time.time()
    if lang not in SUPPORTED_LANGS:
        raise MixError(f"目标语 {lang!r} 未登记（支持：{', '.join(SUPPORTED_LANGS)}）")
    cfg = cfg if cfg is not None else load_pipeline_config()
    p = params if params is not None else params_from_cfg(cfg)
    jobs_root = Path(jobs_dir)
    create_workspace(ep, jobs_root)
    root = ep_dir(ep, jobs_root)

    # ---- 输入（只读）----
    bgm_path = root / "01_media" / "bgm.wav"
    if not bgm_path.is_file():
        raise MixError(
            f"M3 背景轨不存在: {bgm_path}（先跑 python -m pipeline.m3_separate --ep {ep}）")
    utt_path = root / "04_dial" / "utterances.jsonl"
    if not utt_path.is_file():
        raise MixError(
            f"C2 不存在: {utt_path}（先跑 M2/M4/M5 产出 04_dial/utterances.jsonl）")
    utts = list(C.load_jsonl(utt_path, C.UtteranceTable).root)
    if not utts:
        raise MixError(f"C2 为空: {utt_path}")
    utts.sort(key=lambda u: (u.start, u.end))

    plan_path = root / "07_synth" / f"synth_plan.{lang}.jsonl"
    if not plan_path.is_file():
        plan_path = root / "07_synth" / "synth_plan.jsonl"  # 无后缀当前语种副本兜底
    if not plan_path.is_file():
        raise MixError(
            f"C5 不存在: {plan_path}（先跑 python -m pipeline.m8_align --ep {ep} --lang {lang}）")
    plan = {i.utt_id: i for i in C.load_jsonl(plan_path, C.SynthPlanTable).root}

    video = _video_path(root, cfg)
    master_dur = _probe_duration(video) if (video and video.is_file()) else _probe_duration(bgm_path)
    n_master = int(round(master_dur * MIX_SR))

    with tempfile.TemporaryDirectory(prefix=f"m9_{ep}_") as work:
        workdir = Path(work)

        # ---- ① 人声时间轴 ----
        vocals_path = root / "04_dial" / "vocals.wav"
        voice_mono, vstats = build_voice_track(
            utts, plan, root=root, master_dur=master_dur, workdir=workdir,
            vocals_path=vocals_path if vocals_path.is_file() else None)

        # ---- ② 背景轨 + ducking ----
        bgm, bgm_info = _load_bgm(bgm_path, params=p, workdir=workdir)
        if len(bgm) < n_master:
            bgm = np.vstack([bgm, np.zeros((n_master - len(bgm), bgm.shape[1]))])
        bgm = bgm[:n_master]
        t = np.arange(n_master, dtype=np.float64) / MIX_SR
        duck_windows = [(max(0.0, u.start - p.window_pad_s), u.end + p.window_pad_s)
                        for u in utts]
        core_windows = [(u.start, u.end) for u in utts]
        gain = duck_gain(t, duck_windows, core_windows, duck_db=p.duck_db,
                         extra_db=p.duck_extra_db, attack_s=p.attack_s,
                         release_s=p.release_s, core_ramp_s=p.core_ramp_s)
        bgm_ducked = bgm * gain[:, None]

        # ducking 实测（对白区间背景电平是否达标 —— T15 自验收判据）。
        # 区域按包络物理区间分类：句心（-9dB 电平区）/ 提前量区（-6dB 电平区）/
        # 窗外（斜坡之外，包络=1）；斜坡区单列不计入电平判据。
        core_mask = np.zeros(n_master, dtype=bool)
        for c0, c1 in core_windows:
            core_mask |= (t >= c0) & (t <= c1)
        win_mask = np.zeros(n_master, dtype=bool)
        for w0, w1 in duck_windows:
            win_mask |= (t >= w0) & (t <= w1)
        pad_mask = win_mask & ~core_mask
        active_mask = np.zeros(n_master, dtype=bool)
        for w0, w1 in duck_windows:
            active_mask |= (t >= w0 - p.attack_s - 1e-9) & (t <= w1 + p.release_s + 1e-9)
        outside_mask = ~active_mask
        bgm_mono_raw = bgm.mean(axis=1)
        bgm_mono_duck = bgm_ducked.mean(axis=1)

        def _r(mask: np.ndarray, x: np.ndarray) -> float:
            return rms_dbfs(x[mask]) if mask.any() else -120.0

        duck_meas = {
            "duck_db": p.duck_db, "extra_db": p.duck_extra_db,
            "window_pad_s": p.window_pad_s,
            "attack_s": p.attack_s, "release_s": p.release_s,
            "core_ramp_s": p.core_ramp_s,
            "raw_bgm": {
                "core_dbfs": round(_r(core_mask, bgm_mono_raw), 2),
                "pad_dbfs": round(_r(pad_mask, bgm_mono_raw), 2),
                "outside_dbfs": round(_r(outside_mask, bgm_mono_raw), 2),
            },
            "ducked_bgm": {
                "core_dbfs": round(_r(core_mask, bgm_mono_duck), 2),
                "pad_dbfs": round(_r(pad_mask, bgm_mono_duck), 2),
                "outside_dbfs": round(_r(outside_mask, bgm_mono_duck), 2),
            },
        }
        duck_meas["core_reduction_db"] = region_reduction_db(
            duck_meas["raw_bgm"]["core_dbfs"], duck_meas["ducked_bgm"]["core_dbfs"])
        duck_meas["pad_reduction_db"] = region_reduction_db(
            duck_meas["raw_bgm"]["pad_dbfs"], duck_meas["ducked_bgm"]["pad_dbfs"])
        duck_meas["outside_reduction_db"] = region_reduction_db(
            duck_meas["raw_bgm"]["outside_dbfs"], duck_meas["ducked_bgm"]["outside_dbfs"])
        duck_meas["criteria"] = {
            "core_reduction_ge_duck_plus_extra_minus_1p5db": bool(
                duck_meas["core_reduction_db"] >= p.duck_db + p.duck_extra_db - 1.5),
            "pad_reduction_ge_duck_minus_1db": bool(
                duck_meas["pad_reduction_db"] >= p.duck_db - 1.0),
            "outside_reduction_le_0p5db": bool(
                duck_meas["outside_reduction_db"] <= 0.5),
        }

        # ---- ③ 混音（人声 + ducked bgm）----
        if p.voice_gain_db:
            voice_mono = voice_mono * (10.0 ** (p.voice_gain_db / 20.0))
        voice_stereo = np.stack([voice_mono, voice_mono], axis=1)
        mix = voice_stereo[:n_master] + bgm_ducked
        peak = float(np.max(np.abs(mix))) if mix.size else 0.0
        headroom_scaled = False
        if peak > 1.0:  # 峰值保护：整体回落到 -0.01dBFS（报告如实记）
            mix = mix * (0.999 / peak)
            headroom_scaled = True

        # ---- ④ 产物：dubbed / raw mix / loudnorm 两趟 ----
        mix_dir = root / "08_mix"
        mix_dir.mkdir(parents=True, exist_ok=True)
        dubbed_path = mix_dir / f"dubbed.{lang}.wav"
        raw_path = workdir / "mix_raw.wav"
        final_path = mix_dir / f"mix.{lang}.wav"
        sf.write(str(dubbed_path), voice_mono.astype(np.float32), DUBBED_SR,
                 subtype="PCM_16")
        sf.write(str(raw_path), mix.astype(np.float32), MIX_SR, subtype="PCM_16")
        loud = _normalize_loudness(raw_path, final_path, params=p, workdir=workdir)
        # 无后缀当前语种副本（对齐规划 §3 布局的 08_mix/{dubbed,mix}.wav）
        shutil.copyfile(dubbed_path, mix_dir / "dubbed.wav")
        shutil.copyfile(final_path, mix_dir / "mix.wav")

        # ---- ⑤ 可懂度（人声段 / ducked bgm 比值；规划 §4 M9 峰值/双口径）----
        ratios_peak: list[float] = []
        ratios_rms: list[float] = []
        for u in utts:
            if plan.get(u.utt_id) is None or plan[u.utt_id].keep_original:
                continue
            if u.utt_id in vstats["missing"]:
                continue
            v_peak = interval_peak_dbfs(voice_mono, DUBBED_SR, u.start, u.end)
            b_peak = interval_peak_dbfs(bgm_mono_duck, MIX_SR, u.start, u.end)
            v_rms = interval_rms_dbfs(voice_mono, DUBBED_SR, u.start, u.end)
            b_rms = interval_rms_dbfs(bgm_mono_duck, MIX_SR, u.start, u.end)
            if v_peak > -119.0 and b_peak > -119.0:
                ratios_peak.append(v_peak - b_peak)
            if v_rms > -119.0 and b_rms > -119.0:
                ratios_rms.append(v_rms - b_rms)
        intelligibility = {
            "min_voice_bg_peak_ratio_db": round(min(ratios_peak), 2) if ratios_peak else None,
            "min_voice_bg_rms_ratio_db": round(min(ratios_rms), 2) if ratios_rms else None,
            "threshold_db": p.min_ratio_db,
            "n_windows": len(ratios_peak),
            "criteria_peak_ge_threshold": (
                bool(ratios_peak) and min(ratios_peak) >= p.min_ratio_db),
        }

        # ---- ⑥ 成片合成（画面 + 混音 + ASS + AI 标识位）----
        label = _resolve_label(root, ep, lang, p)
        compose_info: dict[str, Any] = (
            _compose_final(root, ep, lang, cfg=cfg, params=p, mix_wav=final_path,
                           master_dur=master_dur, label=label)
            if compose else {"status": "skipped", "reason": "--no-compose",
                              "out": str(root / "12_out" / f"{ep}.{lang}.mp4")}
        )

    final_dur = _probe_duration(final_path)
    elapsed = round(time.time() - t_start, 2)
    report = {
        "ep": ep, "lang": lang, "module": "m9_mix", "generated_by": "m9",
        "config": {
            "target_lufs": p.target_lufs, "tp_dbtp": p.tp_dbtp, "lra": p.lra,
            "duck_db": p.duck_db, "duck_extra_db": p.duck_extra_db,
            "window_pad_s": p.window_pad_s, "attack_s": p.attack_s,
            "release_s": p.release_s, "core_ramp_s": p.core_ramp_s,
            "voice_gain_db": p.voice_gain_db, "bgm_gain_db": p.bgm_gain_db,
            "mix_sr": MIX_SR, "mix_channels": MIX_CHANNELS,
        },
        "inputs": {
            "bgm": bgm_info,
            "master_duration_s": round(master_dur, 3),
            "master_source": "01_media video (ffprobe)" if (video and video.is_file())
            else "01_media/bgm.wav（无视频输入）",
            "synth_plan": str(plan_path.relative_to(root).as_posix()),
            "vocals": str(vocals_path.relative_to(root).as_posix())
            if vocals_path.is_file() else None,
            "voice_track": vstats,
        },
        "ducking": duck_meas,
        "loudness": loud,
        "intelligibility": intelligibility,
        "mix": {
            "path": str(final_path), "duration_s": round(final_dur, 3),
            "duration_delta_s": round(final_dur - master_dur, 3),
            "sample_rate": MIX_SR, "channels": MIX_CHANNELS,
            "peak_dbfs_pre_guard": round(peak_dbfs(mix), 2),
            "headroom_scaled": headroom_scaled,
        },
        "dubbed": {
            "path": str(dubbed_path), "duration_s": round(_probe_duration(dubbed_path), 3),
            "sample_rate": DUBBED_SR, "channels": DUBBED_CHANNELS,
            "duration_delta_s": round(_probe_duration(dubbed_path) - master_dur, 3),
        },
        "compose": compose_info,
        "elapsed_s": elapsed,
        "notes": (
            "M9 工作纸（非冻结契约）。ducking 为确定性语音驱动侧链：C2 句窗±"
            "window_pad_s 内 −6dB（attack/release 斜坡）、句心再 −3dB；不采用 ffmpeg "
            "sidechaincompress 的信号相关压缩（深度不可复现到 ±1dB，eval 无从冻结）。"
            "loudness 为 ffmpeg loudnorm 两趟（linear 应用 measured_*，不达 ±1LU 容差"
            "时如实回落 dynamic 并记 mode）。compose 的 AI 标识位=隐式元数据"
            "（use_metadata_tags 落 mdta，ffprobe 回读校验 verified）；显式 drawtext/"
            "C2PA/音频水印属 M12。missing=合成 wav 缺失句（留空不伪造；"
            "--strict-missing 可升级为 exit 1）。"
        ),
    }
    report_path = mix_dir / f"mix_report.{lang}.json"
    _write_json_atomic(report_path, report)
    report["report_path"] = str(report_path)
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m pipeline.m9_mix",
        description="M9 混音：bgm ducking（对白区间 -6dB/句心再 -3dB）+ EBU R128 -16LUFS + 成片合成（ASS+AI 标识位）",
    )
    ap.add_argument("--ep", required=True, help="集 ID，如 ep01")
    ap.add_argument("--lang", default="en", choices=list(SUPPORTED_LANGS),
                    help="目标语种（冻结槽位 en/es/ar）")
    ap.add_argument("--jobs-dir", default=None,
                    help="jobs 根目录（默认取 configs/pipeline.yaml paths.jobs_dir）")
    ap.add_argument("--no-compose", action="store_true",
                    help="只做音频（dubbed/mix），不合成最终 mp4")
    ap.add_argument("--target-lufs", type=float, default=None,
                    help=f"响度归一目标 LUFS（默认取 configs loudness_lufs，当前 {DEFAULT_TARGET_LUFS}）")
    ap.add_argument("--strict-missing", action="store_true",
                    help="任一合成 wav 缺失即 exit 1（默认 WARN 记入报告）")
    ap.add_argument("--strict-loudness", action="store_true",
                    help="实测响度超出 ±1LU 容差即 exit 1（默认 WARN 记入报告）")
    args = ap.parse_args(argv)

    cfg = load_pipeline_config()
    params = params_from_cfg(cfg)
    if args.target_lufs is not None:
        params = MixParams(**{**params.__dict__, "target_lufs": args.target_lufs})
    jobs_root = Path(args.jobs_dir) if args.jobs_dir else Path(cfg["paths"]["jobs_dir"])
    try:
        rep = mix_episode(
            args.ep, args.lang, jobs_dir=jobs_root, cfg=cfg, params=params,
            compose=not args.no_compose,
        )
    except (MixError, ValueError, OSError) as exc:  # CLI 统一归一（含契约校验）
        print(f"FAIL m9_mix: {exc}")
        return 1

    duck = rep["ducking"]
    loud = rep["loudness"]
    intel = rep["intelligibility"]
    missing = rep["inputs"]["voice_track"]["missing"]
    print(
        f"OK m9_mix ep={rep['ep']} lang={rep['lang']} "
        f"dur={rep['mix']['duration_s']}s(Δ{rep['mix']['duration_delta_s']:+.3f}s) "
        f"I={loud['final']['input_i']:.2f}LUFS(target {loud['target_i']}, mode={loud['mode']}) "
        f"TP={loud['final']['input_tp']:.2f}dBTP "
        f"duck: core -{duck['core_reduction_db']}dB/pad -{duck['pad_reduction_db']}dB "
        f"voice/bg peak ratio={intel['min_voice_bg_peak_ratio_db']}dB "
        f"(min {intel['threshold_db']}dB)"
    )
    print(f"   ducking 判据: core={duck['criteria']['core_reduction_ge_duck_plus_extra_minus_1p5db']} "
          f"pad={duck['criteria']['pad_reduction_ge_duck_minus_1db']} "
          f"outside={duck['criteria']['outside_reduction_le_0p5db']}")
    if intel["min_voice_bg_peak_ratio_db"] is not None:
        print(f"   人声/bg 比（同步给出 RMS 口径）: peak={intel['min_voice_bg_peak_ratio_db']}dB "
              f"rms={intel['min_voice_bg_rms_ratio_db']}dB（n={intel['n_windows']} 窗）")
    print(f"   loudness in_tolerance={loud['in_tolerance']} (Δ{loud['delta_i']:+.2f}LU)")
    if missing:
        print(f"   WARN 合成 wav 缺失 {len(missing)} 句（留空未伪造）: {missing}")
    comp = rep["compose"]
    if comp.get("status") == "ok":
        print(f"   成片: {comp['out']} (dur={comp['duration_s']}s, subs_burned={comp['subs_burned']}, "
              f"AI标识位 verified={comp['ai_label']['verified']} ← {comp['ai_label']['source']})")
    else:
        print(f"   成片合成跳过: {comp.get('reason')}")
    print(f"   dubbed: {rep['dubbed']['path']}")
    print(f"   mix:    {rep['mix']['path']}")
    print(f"   报告:   {rep['report_path']}")

    if args.strict_missing and missing:
        print(f"FAIL m9_mix: --strict-missing 且缺 {len(missing)} 个合成 wav")
        return 1
    if args.strict_loudness and not loud["in_tolerance"]:
        print(f"FAIL m9_mix: 实测 I={loud['final']['input_i']:.2f} 超出 "
              f"±{LOUDNESS_TOL_LU}LU 容差")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
