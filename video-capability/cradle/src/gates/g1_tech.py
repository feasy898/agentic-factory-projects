"""G1 技术门禁: ffprobe 解析(时长±tol/分辨率/fps) + 全黑全白帧检测 (signalstats YAVG)。

所有命令构建为纯函数返回 argv, 便于单测与复用; 实际执行依赖 ffmpeg/ffprobe
(缺失时由测试 skipif / 调用方降级处理)。
"""

from __future__ import annotations

import json
import shutil
import subprocess

from . import make_gate

BLACK_YAVG = 16.0  # signalstats YAVG 低于此视为全黑
WHITE_YAVG = 235.0  # 高于此视为全白


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


# ---------------- 纯函数: argv 构建 ----------------

def build_ffprobe_argv(path: str) -> list[str]:
    return ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path]


def build_flatdetect_argv(path: str, sample_fps: float | None = None) -> list[str]:
    """抽帧统计每帧 YAVG; metadata=print 输出到 stdout(file=-), 视频丢弃到 null。"""
    pre = f"fps={sample_fps}," if sample_fps else ""
    vf = f"{pre}signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-"
    return ["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-vf", vf, "-f", "null", "-"]


# ---------------- 纯函数: 解析 ----------------

def parse_probe(probe_json: dict) -> dict:
    """从 ffprobe JSON 提取 {duration_s, width, height, fps, codec}。"""
    fmt = probe_json.get("format", {})
    duration = float(fmt.get("duration", 0.0))
    stream = None
    for s in probe_json.get("streams", []):
        if s.get("codec_type") == "video":
            stream = s
            break
    if stream is None:
        raise ValueError("ffprobe 输出中无视频流")
    num, _, den = (stream.get("r_frame_rate") or "0/1").partition("/")
    fps = float(num) / float(den or 1)
    return {
        "duration_s": duration,
        "width": int(stream.get("width", 0)),
        "height": int(stream.get("height", 0)),
        "fps": fps,
        "codec": stream.get("codec_name", ""),
    }


def parse_yavg(text: str) -> list[float]:
    """从 ffmpeg metadata=print 输出解析每帧 YAVG 列表。"""
    vals = []
    for line in text.splitlines():
        if "lavfi.signalstats.YAVG=" in line:
            raw = line.split("=", 1)[1].strip()
            try:
                vals.append(float(raw))
            except ValueError:
                continue
    return vals


def probe(path: str, runner=None) -> dict:
    runner = runner or subprocess.run
    cp = runner(build_ffprobe_argv(path), capture_output=True, text=True, timeout=120)
    if cp.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {cp.stderr[:300]}")
    return parse_probe(json.loads(cp.stdout))


def probe_duration(path: str, runner=None) -> float:
    return probe(path, runner=runner)["duration_s"]


def detect_flat_frames(path: str, runner=None) -> list[float]:
    """返回每抽样帧的 YAVG 列表。"""
    runner = runner or subprocess.run
    cp = runner(build_flatdetect_argv(path), capture_output=True, text=True, timeout=300)
    return parse_yavg(cp.stdout or "")


# ---------------- 门禁本体 ----------------

def check_tech(probe_info: dict, expect_w: int, expect_h: int, expect_fps: float, expect_duration: float, duration_tol: float) -> tuple[bool, dict]:
    checks = {
        "duration_ok": abs(probe_info["duration_s"] - expect_duration) <= duration_tol,
        "resolution_ok": (probe_info["width"], probe_info["height"]) == (expect_w, expect_h),
        "fps_ok": abs(probe_info["fps"] - expect_fps) < 0.51,  # 容忍容器取整
    }
    return all(checks.values()), checks


def g1_tech(
    video_path: str,
    expect_w: int,
    expect_h: int,
    expect_fps: float,
    expect_duration: float,
    duration_tol: float = 0.5,
    runner=None,
) -> dict:
    """G1: 时长/分辨率/fps/无全黑全白帧 — 硬性。runner 可注入(单测 stub)。"""
    try:
        info = probe(video_path, runner=runner)
    except Exception as e:
        return make_gate("G1", False, 0.0, error=f"ffprobe 解析失败: {e}")

    passed_basic, checks = check_tech(info, expect_w, expect_h, expect_fps, expect_duration, duration_tol)

    flat: list[float] = []
    flat_error = None
    try:
        flat = detect_flat_frames(video_path, runner=runner)
        black = [v for v in flat if v <= BLACK_YAVG]
        white = [v for v in flat if v >= WHITE_YAVG]
        no_flat = not black and not white
    except Exception as e:  # pragma: no cover
        black, white = [], []
        no_flat = False
        flat_error = str(e)

    passed = passed_basic and no_flat
    score = 1.0 if passed else 0.0
    return make_gate(
        "G1",
        passed,
        score,
        probe=info,
        expect={"resolution": [expect_w, expect_h], "fps": expect_fps, "duration_s": expect_duration},
        checks=checks,
        frames_sampled=len(flat),
        black_frames=len(black),
        white_frames=len(white),
        flatdetect_error=flat_error,
    )
