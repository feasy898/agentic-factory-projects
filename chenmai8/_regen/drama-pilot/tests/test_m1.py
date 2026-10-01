"""M1 摄取与预处理 eval（规划 §4 M1，冻结通过线）。

冻结 eval 命令::

    pytest tests/test_m1.py::test_ingest

断言（§4 M1 原文）：输出存在；``ffprobe`` 断言分辨率/fps/采样率；时长差 ≤0.2s。

测试素材自备（任务要求：ffmpeg 合成 3s 含音轨最小视频）：刻意采用**非标**输入
（AVI 容器 / mpeg4+mp3 编码 / 640x480@24fps 横屏）以证明规范化真实生效，
而非用已合规输入空转。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pipeline.config import REPO_ROOT
from pipeline.m1_ingest import FFMPEG, FFPROBE, ffprobe_json, main as m1_main

pytestmark = pytest.mark.skipif(
    shutil.which(FFMPEG) is None or shutil.which(FFPROBE) is None,
    reason="ffmpeg/ffprobe 不在 PATH（M1 硬依赖）",
)

MEDIA_FILES = ("video_1080x1920_25fps.mp4", "audio_48k.wav", "audio_16k.wav")
DUR_TOL_S = 0.2  # §4 M1 冻结：时长差 ≤0.2s


# ---------------------------------------------------------------------------
# 素材合成（ffmpeg lavfi，3s 含音轨）
# ---------------------------------------------------------------------------

def _ffmpeg_synth(dst: Path, *args: str, timeout_s: float = 120.0) -> Path:
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args, str(dst)]
    subprocess.run(cmd, check=True, capture_output=True, timeout=timeout_s)
    assert dst.is_file() and dst.stat().st_size > 0
    return dst


@pytest.fixture(scope="module")
def raw_clip(tmp_path_factory) -> Path:
    """3s 主测试视频：AVI 容器 + mpeg4/mp3 + 640x480@24（非标输入，验证归一）。"""
    d = tmp_path_factory.mktemp("m1_raw")
    return _ffmpeg_synth(
        d / "ep01_raw.avi",
        "-f", "lavfi", "-i", "testsrc2=size=640x480:rate=24:duration=3",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-c:v", "mpeg4", "-q:v", "5", "-c:a", "mp3", "-b:a", "96k", "-shortest",
    )


@pytest.fixture(scope="module")
def jobs(tmp_path_factory, raw_clip) -> Path:
    """对主素材执行一次 M1（in-process CLI），供 eval 断言复用。"""
    d = tmp_path_factory.mktemp("m1_jobs")
    rc = m1_main(["--ep", "ep01", "--in", str(raw_clip), "--jobs-dir", str(d)])
    assert rc == 0, "m1_ingest 主流程返回非 0"
    return d


def _dur(path: Path) -> float:
    return float(ffprobe_json(path)["format"]["duration"])


# ---------------------------------------------------------------------------
# 冻结 eval（规划 §4 M1）
# ---------------------------------------------------------------------------

def test_ingest(jobs, raw_clip):
    """§4 M1：输出存在；ffprobe 断言分辨率/fps/采样率；时长差 ≤0.2s。"""
    media = jobs / "ep01" / "01_media"
    # 1) 输出存在（三件产物 + probe.json + 00_raw 收件）
    for name in MEDIA_FILES:
        p = media / name
        assert p.is_file() and p.stat().st_size > 0, f"缺产物 {name}"
    assert (media / "probe.json").is_file()
    assert (jobs / "ep01" / "00_raw" / "input.mp4").is_file()

    # 2) ffprobe 断言分辨率/fps（视频：H.264 1080x1920 25fps）
    vprobe = ffprobe_json(media / MEDIA_FILES[0])
    vstream = next(s for s in vprobe["streams"] if s.get("codec_type") == "video")
    assert vstream["codec_name"] == "h264"
    assert int(vstream["width"]) == 1080, f"宽度 {vstream['width']} != 1080"
    assert int(vstream["height"]) == 1920, f"高度 {vstream['height']} != 1920"
    num, _, den = vstream["r_frame_rate"].partition("/")
    assert float(num) / float(den) == pytest.approx(25.0), vstream["r_frame_rate"]

    # 3) ffprobe 断言采样率/声道（48k 立体声 + 16k 单声道，均 pcm_s16le）
    a48 = ffprobe_json(media / "audio_48k.wav")["streams"][0]
    assert a48["codec_name"] == "pcm_s16le"
    assert int(a48["sample_rate"]) == 48000
    assert int(a48["channels"]) == 2
    a16 = ffprobe_json(media / "audio_16k.wav")["streams"][0]
    assert a16["codec_name"] == "pcm_s16le"
    assert int(a16["sample_rate"]) == 16000
    assert int(a16["channels"]) == 1

    # 4) 时长差 ≤0.2s（源 3s；三件产物逐一对照）
    src_dur = _dur(raw_clip)
    for name in MEDIA_FILES:
        d_out = _dur(media / name)
        assert abs(d_out - src_dur) <= DUR_TOL_S, f"{name}: |{d_out}-{src_dur}| > {DUR_TOL_S}"


# ---------------------------------------------------------------------------
# probe.json 元数据（任务要求：流/时长/分辨率/音轨）
# ---------------------------------------------------------------------------

def test_probe_json_metadata(jobs, raw_clip):
    data = json.loads((jobs / "ep01" / "01_media" / "probe.json").read_text(encoding="utf-8"))
    assert data["ep"] == "ep01" and data["module"] == "m1_ingest"
    assert data["targets"] == {"width": 1080, "height": 1920, "fps": 25,
                               "asr_sr": 16000, "mix_sr": 48000, "loudness_lufs": -16.0}

    # 源：容器/流/音轨如实记录（AVI：1 视频流 + 1 音轨）
    src = data["source"]
    assert "avi" in src["container"].lower()
    assert src["has_video"] is True and src["has_audio"] is True
    assert len(src["streams"]) == 2
    types = sorted(s["codec_type"] for s in src["streams"])
    assert types == ["audio", "video"]
    assert abs(src["duration_s"] - 3.0) <= DUR_TOL_S

    # 产物摘要：分辨率/帧率/音轨数/采样率
    v = data["outputs"]["video"]
    assert (v["width"], v["height"], v["fps"]) == (1080, 1920, 25.0)
    assert v["video_codec"] == "h264" and v["audio_tracks"] == 1
    assert v["streams"] and all("codec_name" in s for s in v["streams"])
    mix, asr = data["outputs"]["audio_mix"], data["outputs"]["audio_asr"]
    assert (mix["sample_rate"], mix["channels"]) == (48000, 2)
    assert (asr["sample_rate"], asr["channels"]) == (16000, 1)

    # 响度基础归一：目标 -16 LUFS，输入实测已记录
    assert data["loudness"]["target_lufs"] == -16.0
    assert data["loudness"]["mode"] == "loudnorm-single-pass"
    assert data["loudness"]["input_integrated_lufs"] is not None

    # 时长偏差表：全部产物 ≤0.2s
    assert data["durations"]["max_abs_delta_s"] is not None
    assert data["durations"]["max_abs_delta_s"] <= DUR_TOL_S


def test_default_jobs_dir_resolution(raw_clip, capsys):
    """默认 jobs 目录形态（不带 --jobs-dir）落盘真实共享 jobs/：用 ep02 隔离，
    验证后即清理，不污染其他集工作区。"""
    rc = m1_main(["--ep", "ep02", "--in", str(raw_clip)])
    assert rc == 0
    from pipeline.config import jobs_dir
    probe_path = jobs_dir() / "ep02" / "01_media" / "probe.json"
    try:
        assert probe_path.is_file()
        data = json.loads(probe_path.read_text(encoding="utf-8"))
        assert data["ep"] == "ep02" and data["outputs"]["video"]["width"] == 1080
    finally:
        if probe_path.exists():  # 清理默认工作区，避免污染共享 jobs/
            shutil.rmtree(probe_path.parent.parent, ignore_errors=True)


# ---------------------------------------------------------------------------
# 文档化 CLI 形态（python -m pipeline.m1_ingest ...）
# ---------------------------------------------------------------------------

def test_cli_subprocess(tmp_path, raw_clip):
    """§4 M1 CLI 冻结形态经真实子进程验证。"""
    env = {**os.environ, "PYTHONUTF8": "1"}
    r = subprocess.run(
        [sys.executable, "-m", "pipeline.m1_ingest", "--ep", "ep01",
         "--in", str(raw_clip), "--jobs-dir", str(tmp_path)],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=600, env=env,
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "OK m1_ingest ep01" in r.stdout
    assert (tmp_path / "ep01" / "01_media" / "audio_16k.wav").is_file()


def test_cli_missing_input(tmp_path, capsys):
    rc = m1_main(["--ep", "epX", "--in", str(tmp_path / "nope.avi"),
                  "--jobs-dir", str(tmp_path)])
    assert rc == 1
    assert "FAIL" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 任意输入容错（Spec："任意输入 → …"）
# ---------------------------------------------------------------------------

def test_video_only_input(tmp_path):
    """纯视频输入（无音轨）：视频照常归一，音频产物跳过且 probe.json 如实记录。"""
    src = _ffmpeg_synth(
        tmp_path / "video_only.mp4",
        "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=3",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an",
    )
    assert m1_main(["--ep", "epV", "--in", str(src), "--jobs-dir", str(tmp_path)]) == 0
    media = tmp_path / "epV" / "01_media"
    assert (media / "video_1080x1920_25fps.mp4").is_file()
    assert not (media / "audio_48k.wav").exists()
    assert not (media / "audio_16k.wav").exists()
    data = json.loads((media / "probe.json").read_text(encoding="utf-8"))
    assert data["source"]["has_audio"] is False
    assert data["outputs"]["audio_mix"] is None and data["outputs"]["audio_asr"] is None
    assert data["loudness"] is None
    assert data["durations"]["max_abs_delta_s"] <= DUR_TOL_S


def test_audio_only_input(tmp_path):
    """纯音频输入（无视频轨）：黑底补视频轨 + 双路音频，时长对齐 ≤0.2s。"""
    src = _ffmpeg_synth(
        tmp_path / "audio_only.m4a",
        "-f", "lavfi", "-i", "sine=frequency=330:duration=3",
        "-c:a", "aac", "-b:a", "96k",
    )
    assert m1_main(["--ep", "epA", "--in", str(src), "--jobs-dir", str(tmp_path)]) == 0
    media = tmp_path / "epA" / "01_media"
    for name in MEDIA_FILES:
        assert (media / name).is_file(), name
    vprobe = ffprobe_json(media / "video_1080x1920_25fps.mp4")
    vstream = next(s for s in vprobe["streams"] if s.get("codec_type") == "video")
    assert (int(vstream["width"]), int(vstream["height"])) == (1080, 1920)
    data = json.loads((media / "probe.json").read_text(encoding="utf-8"))
    assert data["source"]["has_video"] is False and data["source"]["has_audio"] is True
    assert data["durations"]["max_abs_delta_s"] <= DUR_TOL_S
