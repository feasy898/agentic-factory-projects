"""G1 技术门禁: 解析器纯函数 + ffmpeg 真跑(skipif)。"""

from __future__ import annotations

import subprocess

import pytest

from src.gates.g1_tech import (
    build_ffprobe_argv,
    build_flatdetect_argv,
    check_tech,
    g1_tech,
    parse_probe,
    parse_yavg,
    probe,
)
from tests.conftest import requires_ffmpeg


def test_build_ffprobe_argv():
    argv = build_ffprobe_argv("v.mp4")
    assert argv[:5] == ["ffprobe", "-v", "quiet", "-print_format", "json"]
    assert argv[-1] == "v.mp4" and "-show_format" in argv and "-show_streams" in argv


def test_build_flatdetect_argv():
    argv = build_flatdetect_argv("v.mp4")
    assert argv[0] == "ffmpeg" and "-f" in argv and argv[argv.index("-f") + 1] == "null"
    vf = argv[argv.index("-vf") + 1]
    assert "signalstats" in vf and "metadata=print" in vf and "YAVG" in vf
    argv2 = build_flatdetect_argv("v.mp4", sample_fps=4)
    assert argv2[argv2.index("-vf") + 1].startswith("fps=4,")


def test_parse_probe():
    j = {
        "format": {"duration": "5.062500"},
        "streams": [
            {"codec_type": "audio", "codec_name": "aac"},
            {"codec_type": "video", "codec_name": "h264", "width": 480, "height": 832, "r_frame_rate": "16/1"},
        ],
    }
    info = parse_probe(j)
    assert info == {"duration_s": 5.0625, "width": 480, "height": 832, "fps": 16.0, "codec": "h264"}
    with pytest.raises(ValueError):
        parse_probe({"format": {}, "streams": [{"codec_type": "audio"}]})


def test_parse_yavg():
    text = (
        "frame:0    pts:0      pts_time:0\n"
        "lavfi.signalstats.YAVG=16.000000\n"
        "frame:1    pts:1      pts_time:0.0625\n"
        "lavfi.signalstats.YAVG=128.4\n"
        "lavfi.signalstats.YMIN=3\n"
        "frame:2\n"
        "lavfi.signalstats.YAVG=NA\n"
    )
    assert parse_yavg(text) == [16.0, 128.4]


def test_check_tech_matrix():
    info = {"duration_s": 5.1, "width": 480, "height": 832, "fps": 16.0}
    ok, checks = check_tech(info, 480, 832, 16, 5.0, 0.5)
    assert ok and all(checks.values())
    ok2, checks2 = check_tech({**info, "duration_s": 6.0}, 480, 832, 16, 5.0, 0.5)
    assert not ok2 and checks2["duration_ok"] is False
    ok3, checks3 = check_tech({**info, "width": 832, "height": 480}, 480, 832, 16, 5.0, 0.5)
    assert not ok3 and checks3["resolution_ok"] is False
    ok4, checks4 = check_tech({**info, "fps": 24.0}, 480, 832, 16, 5.0, 0.5)
    assert not ok4 and checks4["fps_ok"] is False


def test_g1_with_stub_runner():
    probe_json = '{"format": {"duration": "1.0"}, "streams": [{"codec_type": "video", "codec_name": "h264", "width": 64, "height": 64, "r_frame_rate": "8/1"}]}'
    yavg_out = "lavfi.signalstats.YAVG=120.0\nlavfi.signalstats.YAVG=110.5\n"

    class FakeCP:
        def __init__(self, stdout, rc=0, stderr=""):
            self.stdout, self.returncode, self.stderr = stdout, rc, stderr

    calls = []

    def runner(argv, **kw):
        calls.append(argv)
        if argv[0] == "ffprobe":
            return FakeCP(probe_json)
        return FakeCP(yavg_out)

    g = g1_tech("v.mp4", 64, 64, 8, 1.0, 0.5, runner=runner)
    assert g["gate"] == "G1" and g["passed"] is True and g["score"] == 1.0
    assert g["detail"]["black_frames"] == 0 and g["detail"]["frames_sampled"] == 2

    # 全黑帧 → 拒
    yavg_black = "lavfi.signalstats.YAVG=3.0\n"
    g2 = g1_tech("v.mp4", 64, 64, 8, 1.0, 0.5, runner=lambda argv, **kw: FakeCP(
        probe_json) if argv[0] == "ffprobe" else FakeCP(yavg_black))
    assert g2["passed"] is False and g2["detail"]["black_frames"] == 1

    # ffprobe 失败 → 拒
    def bad_runner(argv, **kw):
        return FakeCP("", rc=1, stderr="boom")

    g3 = g1_tech("v.mp4", 64, 64, 8, 1.0, 0.5, runner=bad_runner)
    assert g3["passed"] is False and "ffprobe" in g3["detail"]["error"]


def _make_video(tmp_path, color, name, fps=16, dur=1.0, size="64x64"):
    out = tmp_path / name
    argv = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:size={size}:rate={fps}:duration={dur}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)]
    subprocess.run(argv, check=True, capture_output=True, text=True, timeout=120)
    return str(out)


@requires_ffmpeg
def test_g1_real_pass(tmp_path):
    v = _make_video(tmp_path, "orange", "ok.mp4")
    g = g1_tech(v, 64, 64, 16, 1.0, 0.5)
    assert g["passed"] is True, g
    assert g["detail"]["checks"]["fps_ok"] is True


@requires_ffmpeg
def test_g1_real_black_frames_fail(tmp_path):
    v = _make_video(tmp_path, "black", "black.mp4")
    g = g1_tech(v, 64, 64, 16, 1.0, 0.5)
    assert g["passed"] is False
    assert g["detail"]["black_frames"] >= 1


@requires_ffmpeg
def test_g1_real_duration_mismatch(tmp_path):
    v = _make_video(tmp_path, "orange", "long.mp4", dur=2.0)
    g = g1_tech(v, 64, 64, 16, 1.0, 0.5)
    assert g["passed"] is False and g["detail"]["checks"]["duration_ok"] is False


@requires_ffmpeg
def test_probe_helper(tmp_path):
    v = _make_video(tmp_path, "white", "w.mp4")
    info = probe(v)
    assert (info["width"], info["height"]) == (64, 64)
