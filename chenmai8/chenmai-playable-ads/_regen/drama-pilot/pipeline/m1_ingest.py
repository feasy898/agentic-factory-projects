"""M1 摄取与预处理（重生成实现）。

依据：spec ``docs/assets/specs/m1-ingest.md``（frozen）+ 冻结测试
``tests/test_m1.py``（7 用例，一字不改）。未参考原实现源码。

职责边界（spec §1）：任意输入 → 规范化媒体三件 + probe.json + 原件收件；
只读写 ``00_raw/`` 与 ``01_media/``。不分离、不识别、不做精响度两通归一
（成片级归一属 M9；此处只做摄取级 loudnorm 动态单通基础归一）。

CLI（冻结形态，spec §3）::

    python -m pipeline.m1_ingest --ep ep01 --in clips/ep01_raw.mp4 [--jobs-dir <dir>]

退出码：0 成功；1 媒体处理失败（IngestError 携 stderr 尾 2000 字符）；2 用法错误。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from pipeline.config import jobs_dir as default_jobs_dir
from pipeline.config import media_config

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

FFMPEG_TIMEOUT_S = 1800.0  # spec §3：子进程统一 timeout（默认 1800s，ffprobe 300s）
FFPROBE_TIMEOUT_S = 300.0
STDERR_TAIL_CHARS = 2000

# M9 直接 import 复用的响度目标常量（spec §2）
LOUDNESS_LUFS = -16.0
TRUE_PEAK_DBTP = -1.5
LRA = 11

AUDIO_ONLY_VIDEO_TAIL_S = 0.05  # 纯音频补黑底：长度以音频为准 +50ms 余量防切尾帧

VIDEO_NAME = "video_1080x1920_25fps.mp4"
AUDIO_MIX_NAME = "audio_48k.wav"
AUDIO_ASR_NAME = "audio_16k.wav"
PROBE_NAME = "probe.json"

_RAW_COPY_NAME = "input.mp4"  # 原件收件固定名（冻结测试口径）

_RE_INPUT_INTEGRATED = re.compile(r"Input Integrated:\s*(-?[\d.]+|-\*?inf)")
_RE_INPUT_TRUE_PEAK = re.compile(r"Input True Peak:\s*(-?[\d.]+|-\*?inf)")
_RE_INPUT_LRA = re.compile(r"Input LRA:\s*(-?[\d.]+|-\*?inf)")


class IngestError(RuntimeError):
    """媒体处理失败（消息携带 stderr 尾 2000 字符）。"""


# ---------------------------------------------------------------------------
# 子进程底座（spec §3：统一 utf-8 解码 + timeout）
# ---------------------------------------------------------------------------

def _stderr_tail(raw: bytes | None) -> str:
    return (raw or b"").decode("utf-8", errors="replace")[-STDERR_TAIL_CHARS:]


def _run(cmd: list[str], timeout_s: float) -> subprocess.CompletedProcess:
    exe = shutil.which(cmd[0])
    if exe is None:
        raise IngestError(f"可执行文件不在 PATH：{cmd[0]}")
    try:
        proc = subprocess.run([exe, *cmd[1:]], capture_output=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        raise IngestError(
            f"{cmd[0]} 超时（>{timeout_s:g}s）；stderr尾: {_stderr_tail(exc.stderr)}"
        ) from None
    if proc.returncode != 0:
        raise IngestError(
            f"{cmd[0]} 退出码 {proc.returncode}；stderr尾: {_stderr_tail(proc.stderr)}"
        )
    return proc


def ffprobe_json(path: str | Path, timeout_s: float = FFPROBE_TIMEOUT_S) -> dict:
    """ffprobe -show_format -show_streams 的 JSON 解析（失败抛 IngestError）。"""
    proc = _run(
        [FFPROBE, "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        timeout_s,
    )
    return json.loads(proc.stdout.decode("utf-8", errors="replace"))


def _require_tools() -> None:
    missing = [name for name in (FFMPEG, FFPROBE) if shutil.which(name) is None]
    if missing:
        raise IngestError(f"找不到可执行文件：{', '.join(missing)}（M1 硬依赖）")


# ---------------------------------------------------------------------------
# probe 辅助
# ---------------------------------------------------------------------------

def _streams(probe: dict) -> list[dict]:
    return probe.get("streams") or []


def _has_stream(probe: dict, kind: str) -> bool:
    return any(s.get("codec_type") == kind for s in _streams(probe))


def _duration_s(probe: dict) -> float | None:
    fmt = probe.get("format") or {}
    if fmt.get("duration") is not None:
        return float(fmt["duration"])
    for s in _streams(probe):
        if s.get("duration") is not None:
            return float(s["duration"])
    return None


def _video_fps(probe: dict) -> float | None:
    for s in _streams(probe):
        if s.get("codec_type") == "video":
            num, _, den = str(s.get("r_frame_rate") or "0/1").partition("/")
            d = float(den) if den else 1.0
            return float(num) / d if d else None
    return None


def _video_summary(probe: dict) -> dict:
    streams = _streams(probe)
    v = next(s for s in streams if s.get("codec_type") == "video")
    return {
        "width": int(v["width"]),
        "height": int(v["height"]),
        "fps": _video_fps(probe),
        "video_codec": v.get("codec_name"),
        "audio_tracks": sum(1 for s in streams if s.get("codec_type") == "audio"),
        "duration_s": _duration_s(probe),
        "streams": streams,
    }


def _audio_summary(probe: dict) -> dict:
    a = _streams(probe)[0]
    return {
        "sample_rate": int(a["sample_rate"]),
        "channels": int(a["channels"]),
        "duration_s": _duration_s(probe),
        "streams": _streams(probe),
    }


def _summary_value(match: re.Match | None) -> float | None:
    if match is None:
        return None
    text = match.group(1)
    if "inf" in text:
        return None  # 静音等极端输入：如实记 None
    return float(text)


def _targets() -> dict:
    m = media_config()
    return {
        "width": int(m["width"]),
        "height": int(m["height"]),
        "fps": int(m["fps"]),
        "asr_sr": int(m["asr_sr"]),
        "mix_sr": int(m["mix_sr"]),
        "loudness_lufs": float(m["loudness_lufs"]),
    }


def _scale_filter(w: int, h: int, fps: int) -> str:
    # 等比缩放 + 黑边 pad + setsar=1 + 恒定 fps；force_divisible_by=2（spec §2）
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,"
        f"setsar=1,fps={fps}"
    )


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def ingest(ep: str, src: str | Path, jobs_root: str | Path) -> dict:
    """任意输入 → 规范化三件 + probe.json + 原件收件；失败抛 IngestError。"""
    src = Path(src)
    if not src.is_file():
        raise IngestError(f"输入不存在：{src}")
    _require_tools()

    ep_dir = Path(jobs_root) / ep
    raw_dir = ep_dir / "00_raw"
    media = ep_dir / "01_media"
    raw_dir.mkdir(parents=True, exist_ok=True)
    media.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, raw_dir / _RAW_COPY_NAME)  # 原件收件（工作区自含）

    src_probe = ffprobe_json(src)
    has_video = _has_stream(src_probe, "video")
    has_audio = _has_stream(src_probe, "audio")
    if not has_video and not has_audio:
        raise IngestError("既无视频轨也无音轨，无法摄取")

    t = _targets()
    w, h, fps = t["width"], t["height"], t["fps"]
    m = media_config()
    crf, preset, abit = int(m["crf"]), str(m["preset"]), str(m["video_audio_bitrate"])

    # --- 视频规范化：mp4/H.264 + 黑边 pad + 恒定 fps + yuv420p + faststart ---
    out_video = media / VIDEO_NAME
    vcmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "info", "-nostats"]
    if has_video:
        vcmd += ["-i", str(src), "-map", "0:v:0"]
        if has_audio:
            vcmd += ["-map", "0:a:0"]  # 容器内音轨仅统一编码（不做响度处理，M9 替换）
    else:  # 纯音频：lavfi 黑底补视频轨，长度以音频为准 +50ms 防切尾帧
        audio_dur = _duration_s(src_probe)
        if audio_dur is None:
            raise IngestError("音频时长未知，无法补黑底视频轨")
        vcmd += ["-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={fps}",
                 "-i", str(src), "-map", "0:v", "-map", "1:a:0",
                 "-t", f"{audio_dur + AUDIO_ONLY_VIDEO_TAIL_S:.6f}"]
    vcmd += ["-vf", _scale_filter(w, h, fps),
             "-c:v", "libx264", "-crf", str(crf), "-preset", preset,
             "-pix_fmt", "yuv420p"]
    vcmd += (["-c:a", "aac", "-b:a", abit, "-ar", str(t["mix_sr"]), "-ac", "2"]
             if has_audio else ["-an"])
    vcmd += ["-movflags", "+faststart", str(out_video)]
    _run(vcmd, FFMPEG_TIMEOUT_S)

    # --- 音频两路（无音轨则整体跳过，probe.json 如实记录） ---
    loudness: dict | None = None
    audio_mix: dict | None = None
    audio_asr: dict | None = None
    if has_audio:
        out_mix = media / AUDIO_MIX_NAME
        mproc = _run(
            [FFMPEG, "-y", "-hide_banner", "-loglevel", "info", "-nostats",
             "-i", str(src), "-map", "0:a:0", "-vn",
             "-af", (f"loudnorm=I={t['loudness_lufs']:g}"
                     f":TP={float(m['true_peak_dbtp']):g}:LRA={int(m['lra'])}"
                     ":print_format=summary"),
             "-ar", str(t["mix_sr"]), "-ac", "2", "-c:a", "pcm_s16le", str(out_mix)],
            FFMPEG_TIMEOUT_S,
        )
        summary = mproc.stderr.decode("utf-8", errors="replace")
        loudness = {
            "target_lufs": t["loudness_lufs"],
            "true_peak_dbtp": float(m["true_peak_dbtp"]),
            "lra": int(m["lra"]),
            "mode": "loudnorm-single-pass",
            "input_integrated_lufs": _summary_value(
                _RE_INPUT_INTEGRATED.search(summary)),
            "input_true_peak_dbtp": _summary_value(
                _RE_INPUT_TRUE_PEAK.search(summary)),
            "input_lra": _summary_value(_RE_INPUT_LRA.search(summary)),
        }
        audio_mix = _audio_summary(ffprobe_json(out_mix))

        # 识别用 16k 单声道：由 48k 产物降采样派生（同源同增益，spec §2）
        out_asr = media / AUDIO_ASR_NAME
        _run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(out_mix),
              "-ac", "1", "-ar", str(t["asr_sr"]), "-c:a", "pcm_s16le", str(out_asr)],
             FFMPEG_TIMEOUT_S)
        audio_asr = _audio_summary(ffprobe_json(out_asr))

    # --- probe.json：源/产物流清单 + 响度实测 + 时长偏差表 ---
    video_summary = _video_summary(ffprobe_json(out_video))
    src_dur = _duration_s(src_probe)
    deltas = [
        abs(s["duration_s"] - src_dur)
        for s in (video_summary, audio_mix, audio_asr)
        if s is not None and s.get("duration_s") is not None and src_dur is not None
    ]
    outputs: dict = {"video": video_summary, "audio_mix": audio_mix,
                     "audio_asr": audio_asr}
    if not has_audio:
        outputs["audio"] = "skip(源无音轨)"
    probe_data = {
        "ep": ep,
        "module": "m1_ingest",
        "targets": t,
        "source": {
            "path": str(src),
            "container": (src_probe.get("format") or {}).get("format_name", ""),
            "has_video": has_video,
            "has_audio": has_audio,
            "duration_s": src_dur,
            "streams": _streams(src_probe),
        },
        "outputs": outputs,
        "loudness": loudness,
        "durations": {
            "source_s": src_dur,
            "video_s": video_summary.get("duration_s"),
            "audio_mix_s": (audio_mix or {}).get("duration_s"),
            "audio_asr_s": (audio_asr or {}).get("duration_s"),
            "max_abs_delta_s": max(deltas) if deltas else None,
        },
    }
    (media / PROBE_NAME).write_text(
        json.dumps(probe_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return probe_data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pipeline.m1_ingest", description="M1 摄取与预处理：任意输入 → 规范化三件 + probe.json")
    parser.add_argument("--ep", required=True, help="集号，如 ep01")
    parser.add_argument("--in", dest="src", required=True, help="原始输入媒体路径")
    parser.add_argument("--jobs-dir", dest="jobs_dir", default=None,
                        help="工作区根目录（默认 <REPO_ROOT>/jobs）")
    args = parser.parse_args(argv)

    jobs_root = Path(args.jobs_dir) if args.jobs_dir else default_jobs_dir()
    try:
        ingest(args.ep, args.src, jobs_root)
    except IngestError as exc:
        print(f"FAIL m1_ingest {args.ep}: {exc}")
        return 1
    print(f"OK m1_ingest {args.ep} -> {Path(jobs_root) / args.ep / '01_media'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
