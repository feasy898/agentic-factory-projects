"""Ken Burns zoompan 命令构建纯函数单测 + ffmpeg 真跑(skipif)。"""

from __future__ import annotations

import subprocess

import pytest

from src.gen.kenburns import (
    build_kenburns_argv,
    build_zoompan_filter,
    parse_motion,
    run_kenburns,
    supersample_size,
)
from tests.conftest import requires_ffmpeg


def test_parse_motion():
    assert parse_motion("zoom_in_1.06") == {"kind": "zoom_in", "cap": 1.06}
    assert parse_motion("zoom_in") == {"kind": "zoom_in", "cap": 1.06}
    assert parse_motion("zoom_out") == {"kind": "zoom_out", "cap": 1.06}
    assert parse_motion("pan_left") == {"kind": "pan_left", "cap": pytest.approx(1.1)}
    assert parse_motion("pan_right") == {"kind": "pan_right", "cap": pytest.approx(1.1)}
    with pytest.raises(ValueError):
        parse_motion("spin_360")


def test_supersample_even_4x():
    assert supersample_size(480, 832) == (1920, 3328)
    w, h = supersample_size(481, 833)
    assert w % 2 == 0 and h % 2 == 0 and w >= 481 * 4 - 1


def test_zoom_in_filter_formula():
    f = build_zoompan_filter("zoom_in_1.06", 5, 16, 480, 832)
    assert f.startswith("scale=1920:3328:flags=lanczos,setsar=1,")
    assert "zoompan=z='min(1+0.060000*on/80,1.060000)'" in f  # z 线性, d=5*16=80
    assert "x='iw/2-(iw/zoom/2)'" in f and "y='ih/2-(ih/zoom/2)'" in f  # 居中
    assert "d=80" in f and "s=480x832" in f and "fps=16" in f


def test_zoom_out_filter_formula():
    f = build_zoompan_filter("zoom_out", 2, 16, 480, 832)
    assert "z='max(1.060000-0.060000*on/32,1.0)'" in f  # 不低于 1, 避免 zoompan 抖动
    assert "d=32" in f


def test_pan_filters():
    fl = build_zoompan_filter("pan_left", 5, 16, 480, 832)
    assert "z='1.100000'" in fl
    assert "x='(iw-iw/zoom)*(1-on/80)'" in fl
    fr = build_zoompan_filter("pan_right", 5, 16, 480, 832)
    assert "x='(iw-iw/zoom)*(on/80)'" in fr
    assert "y='ih/2-(ih/zoom/2)'" in fr


def test_full_argv_structure():
    argv = build_kenburns_argv("img.png", "out.mp4", "zoom_in_1.06", 5, 16, 480, 832)
    assert argv[0] == "ffmpeg" and "-loop" in argv and argv[argv.index("-loop") + 1] == "1"
    assert argv[argv.index("-i") + 1] == "img.png"
    assert argv[argv.index("-frames:v") + 1] == "80"
    assert "-c:v" in argv and "libx264" in argv and "-pix_fmt" in argv and "yuv420p" in argv
    assert argv[-1] == "out.mp4"
    # 1s@8fps → d=8
    argv2 = build_kenburns_argv("img.png", "out.mp4", "zoom_out", 1, 8, 64, 64)
    assert argv2[argv2.index("-frames:v") + 1] == "8"


@requires_ffmpeg
def test_kenburns_real_render(tmp_path):
    from PIL import Image

    img = tmp_path / "src.png"
    Image.new("RGB", (64, 64), (180, 60, 40)).save(img)
    out = tmp_path / "kb.mp4"
    meta = run_kenburns(str(img), str(out), "zoom_in_1.06", 1.0, 8, 64, 64)
    assert out.exists() and meta["duration_s"] == pytest.approx(1.0, abs=0.2)

    from src.gates.g1_tech import probe

    info = probe(str(out))
    assert (info["width"], info["height"]) == (64, 64)
    assert info["fps"] == pytest.approx(8.0)


@requires_ffmpeg
def test_kenburns_real_pan(tmp_path):
    from PIL import Image

    img = tmp_path / "src.png"
    Image.new("RGB", (128, 128), (30, 90, 200)).save(img)
    out = tmp_path / "pan.mp4"
    meta = run_kenburns(str(img), str(out), "pan_right", 0.5, 8, 64, 64)
    assert out.exists() and meta["motion"] == "pan_right"


def test_run_kenburns_failure_raises(tmp_path):
    def bad_runner(argv, **kw):
        class CP:
            returncode = 1
            stderr = "boom"
            stdout = ""
        return CP()

    with pytest.raises(RuntimeError):
        run_kenburns("no.png", str(tmp_path / "x.mp4"), "zoom_in_1.06", 1, 8, 64, 64, runner=bad_runner)
