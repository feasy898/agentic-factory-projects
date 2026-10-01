"""M1 摄取与预处理（spec m1-ingest.md 回炉二稿；重生成实现）。

职责：任意输入 → 规范化媒体三件 + probe.json + 原件收件（00_raw/ 与 01_media/）。
收件先行：原件先 copy2 进 00_raw/input.mp4，两路处理一律以收件副本为输入。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from pipeline.config import load_pipeline_config
from pipeline.scaffold import create_workspace, ep_dir

__all__ = ["FFMPEG", "FFPROBE", "IngestError", "ffprobe_json", "ingest", "main"]

#: 可执行文件名（调用时经 shutil.which 解析；spec §3 import 面逐名冻结）
FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

#: loudnorm 真峰值/响度域常量（代码常量，非配置键；M9 直接 import 复用）
TRUE_PEAK_DBTP = -1.5
LRA = 11.0

#: 默认媒体目标（configs/pipeline.yaml media 段缺失时的兜底；spec §2.1）
_DEFAULT_MEDIA = {
    "width": 1080,
    "height": 1920,
    "fps": 25,
    "audio": {"asr_sr": 16000, "mix_sr": 48000},
}
_DEFAULT_LUFS = -16.0


class IngestError(RuntimeError):
    """ffmpeg/ffprobe 执行失败（携带工具 stderr 摘要）。"""


# ---------------------------------------------------------------------------
# 子进程与 ffprobe（spec §3：utf-8 解码 errors=replace + timeout 纪律）
# ---------------------------------------------------------------------------

def _run(cmd: list[str], timeout_s: float = 1800.0) -> subprocess.CompletedProcess[str]:
    """执行外部命令（默认 1800s；失败抛 IngestError，stderr 尾部 2000 字符入消息）。"""
    exe = cmd[0]
    if shutil.which(exe) is None:
        raise IngestError(f"未找到可执行文件 {exe!r}（请确认 ffmpeg 已安装并在 PATH）")
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise IngestError(f"{exe} 超时（>{timeout_s:.0f}s）: {' '.join(cmd[:6])}...") from exc
    if r.returncode != 0:
        tail = (r.stderr or "").strip()[-2000:]
        raise IngestError(f"{exe} 退出码 {r.returncode}: {' '.join(cmd)}\n{tail}")
    return r


def ffprobe_json(path: str | Path) -> dict[str, Any]:
    """ffprobe 单文件 → format+streams 原始 JSON dict（timeout 300s）。"""
    r = _run([FFPROBE, "-v", "error", "-show_format", "-show_streams",
              "-print_format", "json", str(path)], timeout_s=300.0)
    return json.loads(r.stdout)


def _real_streams(probe: dict[str, Any]) -> list[dict[str, Any]]:
    """剔除封面图（attached_pic）后的真实流清单（spec §2.3 流型判定）。"""
    out = []
    for s in probe.get("streams", []):
        if s.get("codec_type") == "video" and int(s.get("disposition", {}).get("attached_pic", 0)):
            continue
        out.append(s)
    return out


def _duration_s(probe: dict[str, Any]) -> float:
    """容器时长（秒）：format.duration 优先（round 3）；缺失取各流最大值；仍无则 0.0。"""
    try:
        return round(float(probe["format"]["duration"]), 3)
    except (KeyError, TypeError, ValueError):
        ds = [float(s["duration"]) for s in probe.get("streams", [])
              if s.get("duration") not in (None, "N/A")]
        return round(max(ds), 3) if ds else 0.0


def _fps_of(stream: dict[str, Any]) -> float:
    """r_frame_rate "25/1" → 25.0（round 3；0/1 → 0.0）。"""
    num, _, den = str(stream.get("r_frame_rate", "0/1")).partition("/")
    try:
        return round(float(num) / float(den or "1"), 3)
    except (ZeroDivisionError, ValueError):
        return 0.0


def _loudnorm_measures(stderr: str) -> dict[str, Any]:
    """从 loudnorm summary（stderr）提取输入实测响度（取不到或 -inf/nan → null）。"""
    def grab(label: str) -> float | None:
        m = re.search(rf"{label}:\s*(-?[\d.]+|-inf|-nan|nan)", stderr)
        if m is None:
            return None
        v = m.group(1)
        return None if v in ("-inf", "inf", "-nan", "nan") else float(v)

    return {
        "input_integrated_lufs": grab("Input Integrated"),
        "input_true_peak_dbtp": grab("Input True Peak"),
        "input_lra": grab("Input LRA"),
        "input_threshold_lufs": grab("Input Threshold"),
    }


# ---------------------------------------------------------------------------
# 规范化步骤（spec §2.3 滤镜链逐字）
# ---------------------------------------------------------------------------

def normalize_video(
    src: Path, dst: Path, *, width: int, height: int, fps: int,
    has_video: bool, has_audio: bool, duration_s: float | None = None,
) -> None:
    """视频规范化：mp4/H.264 + {W}x{H} 等比缩放黑边 pad + 恒定 fps + yuv420p + faststart。

    纯音频输入 → lavfi 黑底补视频轨（时长以音频为准 +50ms 余量防切尾帧）；
    容器内音轨仅统一编码（AAC 192k/48k/立体声，不做响度处理）；无音轨 -an。
    """
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease"
        f":force_divisible_by=2,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fps={fps},setsar=1,format=yuv420p"
    )
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error"]
    if has_video:
        cmd += ["-i", str(src)]
    else:
        # 视频轨补底：纯音频 → 黑场视频
        cmd += ["-i", str(src), "-f", "lavfi",
                "-i", f"color=black:s={width}x{height}:r={fps}"]
    cmd += ["-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-movflags", "+faststart"]
    if has_video:
        cmd += ["-map", "0:v:0"]
        cmd += (["-map", "0:a:0", "-c:a", "aac", "-b:a", "192k",
                 "-ar", "48000", "-ac", "2"] if has_audio else ["-an"])
    else:
        cmd += ["-map", "1:v:0"]
        if has_audio:
            cmd += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "192k",
                    "-ar", "48000", "-ac", "2"]
            if duration_s:
                cmd += ["-t", f"{duration_s + 0.05:.3f}"]
        else:  # 既无视频也无音轨在 ingest 已拦截
            cmd += ["-an"]
    cmd.append(str(dst))
    _run(cmd)


def normalize_audio_mix(
    src: Path, dst: Path, *, mix_sr: int, lufs: float,
) -> dict[str, Any]:
    """混音底座：重采样 {mix_sr}Hz 立体声 + loudnorm 动态单通基础响度归一。

    返回输入响度实测（probe.json loudness 段；summary 从 stderr 正则抓取）。
    """
    cmd = [FFMPEG, "-y", "-hide_banner", "-v", "info", "-i", str(src),
           "-vn", "-af",
           f"loudnorm=I={lufs}:TP={TRUE_PEAK_DBTP}:LRA={LRA}:print_format=summary",
           "-ar", str(mix_sr), "-ac", "2", "-c:a", "pcm_s16le", str(dst)]
    r = _run(cmd)
    return _loudnorm_measures(r.stderr or "")


def derive_audio_asr(src: Path, dst: Path, *, asr_sr: int) -> None:
    """识别用音频：由 48k 立体声（已归一）降采样单声道 {asr_sr}Hz（同源同增益）。"""
    _run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
          "-ar", str(asr_sr), "-ac", "1", "-c:a", "pcm_s16le", str(dst)])


# ---------------------------------------------------------------------------
# 主流程（spec §2.4 probe.json schema）
# ---------------------------------------------------------------------------

def _output_summary(path: Path, probe: dict[str, Any]) -> dict[str, Any]:
    """产物 ffprobe → 摘要（13 字段；无对应流时相应字段为 null）。"""
    streams = _real_streams(probe)
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = [s for s in streams if s.get("codec_type") == "audio"]
    return {
        "path": str(path),
        "duration_s": _duration_s(probe),
        "width": int(v["width"]) if v else None,
        "height": int(v["height"]) if v else None,
        "fps": _fps_of(v) if v else None,
        "video_codec": v.get("codec_name") if v else None,
        "audio_tracks": len(a),
        "audio_codec": a[0].get("codec_name") if a else None,
        "sample_rate": int(a[0]["sample_rate"]) if a and a[0].get("sample_rate") else None,
        "channels": int(a[0]["channels"]) if a and a[0].get("channels") else None,
        "n_streams": len(streams),
        "streams": streams,  # ffprobe 原始流清单（剔除封面后）
        "format": probe.get("format", {}),
    }


def ingest(
    ep: str,
    src: str | Path,
    jobs_dir: str | Path,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """M1 主流程：00_raw 收件 → 01_media 三件产物 + probe.json。返回 probe dict。"""
    cfg = cfg if cfg is not None else load_pipeline_config()
    # 配置合并：media 段浅合并 + audio 子字典再合并（spec §2.1；部分覆盖合法）
    media_cfg = {**_DEFAULT_MEDIA, **(cfg.get("media") or {})}
    media_cfg["audio"] = {**_DEFAULT_MEDIA["audio"], **(media_cfg.get("audio") or {})}
    width = int(media_cfg["width"])
    height = int(media_cfg["height"])
    fps = int(media_cfg["fps"])
    asr_sr = int(media_cfg["audio"]["asr_sr"])
    mix_sr = int(media_cfg["audio"]["mix_sr"])
    lufs = float((cfg.get("loudness_lufs") or _DEFAULT_LUFS))

    src = Path(src).resolve()
    if not src.is_file():
        raise IngestError(f"输入不存在: {src}")

    create_workspace(ep, jobs_dir)  # 幂等：13 层骨架就绪（ep 白名单校验先于建目录）
    root = ep_dir(ep, jobs_dir)
    raw_dir, media_dir = root / "00_raw", root / "01_media"

    # ① 原件收件（固定名 input.mp4，任意容器一律此名；同路径幂等跳过复制）
    raw_input = raw_dir / "input.mp4"
    if src.resolve() != raw_input.resolve():
        shutil.copy2(src, raw_input)

    # ② 源探针 → 流型判定（先剔除封面图）
    src_probe = ffprobe_json(raw_input if raw_input.is_file() else src)
    src_streams = _real_streams(src_probe)
    has_video = any(s.get("codec_type") == "video" for s in src_streams)
    has_audio = any(s.get("codec_type") == "audio" for s in src_streams)
    if not has_video and not has_audio:
        raise IngestError(f"输入既无视频轨也无音轨: {src}")
    src_dur = _duration_s(src_probe)

    # ③ 视频规范化（产物名随 targets 联动：video_{W}x{H}_{fps}fps.mp4）
    video_name = f"video_{width}x{height}_{fps}fps.mp4"
    video_dst = media_dir / video_name
    normalize_video(raw_input, video_dst, width=width, height=height, fps=fps,
                    has_video=has_video, has_audio=has_audio, duration_s=src_dur)

    # ④ 音频：48k 立体声（loudnorm 基础归一）→ 派生 16k 单声道
    loudness: dict[str, Any] | None = None
    audio_mix_path: Path | None = None
    audio_asr_path: Path | None = None
    if has_audio:
        audio_mix_path = media_dir / "audio_48k.wav"
        loudness = normalize_audio_mix(raw_input, audio_mix_path, mix_sr=mix_sr, lufs=lufs)
        audio_asr_path = media_dir / "audio_16k.wav"
        derive_audio_asr(audio_mix_path, audio_asr_path, asr_sr=asr_sr)
        loudness.update({"mode": "loudnorm-single-pass", "target_lufs": lufs,
                         "true_peak_dbtp": TRUE_PEAK_DBTP, "lra": LRA})

    # ⑤ 产物探针 + probe.json 回写
    video_sum = _output_summary(video_dst, ffprobe_json(video_dst))
    mix_sum = _output_summary(audio_mix_path, ffprobe_json(audio_mix_path)) if audio_mix_path else None
    asr_sum = _output_summary(audio_asr_path, ffprobe_json(audio_asr_path)) if audio_asr_path else None

    durations = {"source_s": src_dur, "video_s": video_sum["duration_s"],
                 "audio_mix_s": mix_sum["duration_s"] if mix_sum else None,
                 "audio_asr_s": asr_sum["duration_s"] if asr_sum else None}
    deltas = [abs(durations[k] - src_dur) for k in ("video_s", "audio_mix_s", "audio_asr_s")
              if durations[k] is not None]
    durations["max_abs_delta_s"] = round(max(deltas), 3) if deltas else None

    probe_doc: dict[str, Any] = {
        "ep": ep,
        "module": "m1_ingest",
        "schema_version": 1,
        "targets": {"width": width, "height": height, "fps": fps,
                    "asr_sr": asr_sr, "mix_sr": mix_sr, "loudness_lufs": lufs},
        "source": {
            "path": str(src),
            "container": src_probe.get("format", {}).get("format_name", ""),
            "duration_s": src_dur,
            "has_video": has_video,
            "has_audio": has_audio,
            "streams": src_streams,
            "format": src_probe.get("format", {}),
        },
        "outputs": {
            "video": video_sum,
            "audio_mix": mix_sum,   # 48k 立体声（混音底座，M3/M9 消费）
            "audio_asr": asr_sum,   # 16k 单声道（识别/对齐/分离输入，M3/M4/M5 消费）
        },
        "loudness": loudness,
        "durations": durations,
    }
    probe_path = media_dir / "probe.json"
    probe_path.write_text(json.dumps(probe_doc, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    return probe_doc


# ---------------------------------------------------------------------------
# CLI（spec §3 冻结形态）
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.m1_ingest",
        description="M1 摄取与预处理：任意输入 → 1080x1920/25fps H.264 + 16k/48k wav + probe.json",
    )
    parser.add_argument("--ep", required=True, help="集 ID，如 ep01")
    parser.add_argument("--in", dest="src", required=True, help="输入媒体路径（任意容器）")
    parser.add_argument("--jobs-dir", default=None,
                        help="jobs 根目录（默认取 configs/pipeline.yaml paths.jobs_dir）")
    args = parser.parse_args(argv)  # 用法错误：argparse 直接 SystemExit(2)，本函数不捕获

    cfg = load_pipeline_config()
    jobs_root = Path(args.jobs_dir) if args.jobs_dir else Path(cfg["paths"]["jobs_dir"])
    try:
        probe = ingest(args.ep, args.src, jobs_root, cfg)
    except IngestError as exc:
        print(f"FAIL m1_ingest: {exc}")
        return 1

    v = probe["outputs"]["video"]
    parts = [f"video {v['duration_s']}s {v['width']}x{v['height']}@{v['fps']}"]
    if probe["outputs"]["audio_mix"]:
        am = probe["outputs"]["audio_mix"]
        parts.append(f"audio_48k {am['sample_rate']}Hz/{am['channels']}ch")
    if probe["outputs"]["audio_asr"]:
        aa = probe["outputs"]["audio_asr"]
        parts.append(f"audio_16k {aa['sample_rate']}Hz/{aa['channels']}ch")
    if not probe["source"]["has_audio"]:
        parts.append("audio=skip(源无音轨)")
    ln = probe.get("loudness") or {}
    if ln.get("input_integrated_lufs") is not None:
        parts.append(f"loudness in={ln['input_integrated_lufs']}→{ln.get('target_lufs')} LUFS")
    print(f"OK m1_ingest {args.ep}: " + ", ".join(parts))
    print(f"   probe.json → {Path(probe['outputs']['video']['path']).parent / 'probe.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
