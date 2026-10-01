"""生成层封装: LTX/Wan 参数硬校验 + 可注入管线 stub + 帧序列落盘 (skipif ffmpeg)。"""

from __future__ import annotations

import numpy as np
import pytest

from src.gen.common import build_frames_to_mp4_argv, even, open_center_resize, write_frames_mp4
from src.gen.ltx import (
    LTX_MAX_DURATION_S,
    LTX_MAX_STEPS,
    LTX_RESOLUTION,
    generate as ltx_generate,
    project_card_for_debug,
    validate_ltx_params,
)
from src.gen.wan import (
    DENOISE_RANGE,
    WAN_MAX_FRAMES,
    WAN_STEPS_RANGE,
    frames_for_duration,
    generate as wan_generate,
    stylize_first_frame,
    validate_denoise,
    validate_wan_params,
)
from tests.conftest import requires_ffmpeg


# ---------------- common ----------------

def test_even():
    assert even(4) == 4 and even(5) == 6 and even(480) == 480


def test_frames_to_mp4_argv():
    argv = build_frames_to_mp4_argv(16, 480, 832, "out.mp4")
    assert "-f" in argv and "rawvideo" in argv
    assert argv[argv.index("-s") + 1] == "480x832"
    assert argv[argv.index("-r") + 1] == "16"
    assert "libx264" in argv and "yuv420p" in argv and argv[-1] == "out.mp4"


@requires_ffmpeg
def test_write_frames_mp4_roundtrip(tmp_path):
    frames = [np.full((16, 16, 3), i * 20, dtype="uint8") for i in range(8)]
    out = tmp_path / "f.mp4"
    write_frames_mp4(frames, 8, str(out))
    from src.gates.g1_tech import probe

    info = probe(str(out))
    assert info["duration_s"] == pytest.approx(1.0, abs=0.2)
    assert info["fps"] == pytest.approx(8.0)


def test_write_frames_empty_raises(tmp_path):
    with pytest.raises(ValueError):
        write_frames_mp4([], 8, str(tmp_path / "x.mp4"))


# ---------------- LTX ----------------

def test_ltx_param_validation():
    validate_ltx_params(2.0, 15, LTX_RESOLUTION)  # 边界可过
    with pytest.raises(ValueError):
        validate_ltx_params(2.1, 10, LTX_RESOLUTION)  # 超2s
    with pytest.raises(ValueError):
        validate_ltx_params(1.0, 16, LTX_RESOLUTION)  # steps>15
    with pytest.raises(ValueError):
        validate_ltx_params(1.0, 10, (480, 832))  # 分辨率不符
    assert LTX_MAX_DURATION_S == 2.0 and LTX_MAX_STEPS == 15


def _ltx_card():
    return {
        "shot_id": "SX",
        "duration_sec": 1.0,
        "resolution": [384, 512],
        "fps": 16,
        "prompt_en": "hotpot closeup",
        "first_frame_asset": None,
        "negative": [],
    }


def test_ltx_generate_with_stub_pipeline(tmp_path):
    calls = {}

    def fake_pipeline(**kw):
        calls.update(kw)
        return [np.full((16, 24, 3), 128, dtype="uint8") for _ in range(kw["num_frames"])]

    out = tmp_path / "ltx.mp4"
    meta = ltx_generate(_ltx_card(), seed=42, out_path=str(out), steps=12, pipeline=fake_pipeline)
    assert out.exists()
    assert meta["seed"] == 42 and meta["steps"] == 12 and meta["model"] == "ltx_2b"
    assert meta["duration_s"] == pytest.approx(1.0)
    assert calls["width"] == 384 and calls["height"] == 512 and calls["seed"] == 42


def test_ltx_generate_rejects_oversize_card():
    card = _ltx_card()
    card["duration_sec"] = 5.0  # 超 LTX 限制 → 拒绝(须走 Wan)
    with pytest.raises(ValueError):
        ltx_generate(card, seed=1, out_path="x.mp4", pipeline=lambda **k: [])


# ---------------- Wan ----------------

def test_wan_param_validation():
    validate_wan_params(20, 81, (480, 832))
    validate_wan_params(30, 81, (832, 480))
    with pytest.raises(ValueError):
        validate_wan_params(19, 81, (480, 832))
    with pytest.raises(ValueError):
        validate_wan_params(31, 81, (480, 832))
    with pytest.raises(ValueError):
        validate_wan_params(25, 82, (480, 832))
    with pytest.raises(ValueError):
        validate_wan_params(25, 81, (500, 800))
    assert WAN_STEPS_RANGE == (20, 30) and WAN_MAX_FRAMES == 81


def test_frames_for_duration_4k_plus_1():
    assert frames_for_duration(5.0, 16) == 81
    assert frames_for_duration(1.0, 16) == 17
    for d in (0.5, 1, 2, 3.5, 5):
        n = frames_for_duration(d, 16)
        assert (n - 1) % 4 == 0 and n <= 81


def test_denoise_bounds():
    validate_denoise(0.2)
    validate_denoise(0.35)
    with pytest.raises(ValueError):
        validate_denoise(0.1)
    with pytest.raises(ValueError):
        validate_denoise(0.5)
    assert DENOISE_RANGE == (0.2, 0.35)


def test_stylize_first_frame_validates_then_calls(tmp_path):
    calls = {}

    def fake_pipe(**kw):
        calls.update(kw)
        return {"path": kw["out_path"], "strength": kw["strength"]}

    meta = stylize_first_frame("in.png", "out.png", "hotpot", denoise=0.3, pipeline=fake_pipe)
    assert calls["strength"] == 0.3
    assert meta["path"] == "out.png"
    with pytest.raises(ValueError):
        stylize_first_frame("in.png", "out.png", "hotpot", denoise=0.5, pipeline=fake_pipe)


def _wan_card():
    return {
        "shot_id": "S01",
        "duration_sec": 5,
        "resolution": [480, 832],
        "fps": 16,
        "prompt_en": "hotpot",
        "first_frame_asset": "assets/x.png",
        "negative": ["human face", "text"],
    }


def test_wan_generate_with_stub_pipeline(tmp_path):
    calls = {}

    def fake_pipe(**kw):
        calls.update(kw)
        return [np.zeros((8, 8, 3), dtype="uint8") for _ in range(kw["num_frames"])]

    out = tmp_path / "wan.mp4"
    meta = wan_generate(_wan_card(), seed=7, out_path=str(out), steps=25, num_frames=9,
                        pipeline=fake_pipe)
    assert out.exists()
    assert meta["seed"] == 7 and meta["steps"] == 25 and meta["model"] == "wan_fun_1.3b_inp"
    assert meta["duration_s"] == pytest.approx(9 / 16)
    assert calls["negative"] == ["human face", "text"]
    assert calls["first_frame"] == "assets/x.png"

    # 重试钩子: negative 加强 + guidance 钩子透传
    meta2 = wan_generate(_wan_card(), seed=8, out_path=str(tmp_path / "w2.mp4"), steps=25,
                         num_frames=9, pipeline=fake_pipe,
                         negative_extra=["blurry", "human face"], guidance_delta=-0.5)
    assert calls["negative"] == ["human face", "text", "blurry"]  # 去重
    assert meta2["hint"]["guidance_delta"] == -0.5


def test_wan_generate_rejects_bad_steps(tmp_path):
    with pytest.raises(ValueError):
        wan_generate(_wan_card(), seed=1, out_path="x.mp4", steps=15, num_frames=9,
                     pipeline=lambda **k: [])


# ---------------- M2-EXEC wiring: 首帧预处理 / 卡片投影 / LTX 重试钩子 ----------------

def test_open_center_resize_crops_to_target_ar(tmp_path):
    from PIL import Image

    wide = Image.new("RGB", (800, 400), (200, 30, 30))
    pw = tmp_path / "wide.png"
    wide.save(pw)
    img = open_center_resize(str(pw), 384, 512)
    assert img.size == (384, 512)

    tall = Image.new("RGB", (400, 800), (30, 200, 30))
    pt = tmp_path / "tall.png"
    tall.save(pt)
    img2 = open_center_resize(str(pt), 480, 832)
    assert img2.size == (480, 832)

    same = Image.new("RGB", (384, 512), (10, 10, 250))
    ps = tmp_path / "same.png"
    same.save(ps)
    img3 = open_center_resize(str(ps), 384, 512)
    assert img3.size == (384, 512)


def test_project_card_for_debug(valid_card):
    proj = project_card_for_debug(valid_card)
    assert proj["resolution"] == [384, 512]
    assert proj["fps"] == 16
    assert proj["duration_sec"] <= LTX_MAX_DURATION_S
    n = round(proj["duration_sec"] * 16)
    assert (n - 1) % 8 == 0  # 8k+1 帧布局
    assert proj["fallback"]["duration_sec"] == proj["duration_sec"]
    assert proj["prompt_en"] == valid_card["prompt_en"]
    assert proj["negative"] == valid_card["negative"]
    assert proj["n_best"] == valid_card["n_best"] and proj["retry_max"] == valid_card["retry_max"]
    assert proj["acceptance"] == valid_card["acceptance"]
    from src.schema import validate_shotcard

    validate_shotcard(proj)  # 投影卡必须仍过 schema


def test_ltx_generate_retry_hooks(tmp_path):
    calls = {}

    def fake_pipeline(**kw):
        calls.update(kw)
        return [np.full((16, 24, 3), 128, dtype="uint8") for _ in range(kw["num_frames"])]

    out = tmp_path / "ltx_hooks.mp4"
    meta = ltx_generate(_ltx_card(), seed=5, out_path=str(out), steps=12, pipeline=fake_pipeline,
                        negative_extra=["blurry"], guidance_delta=-0.5)
    assert calls["guidance"] == 2.5  # 3.0 - 0.5
    assert "blurry" in calls["negative"]
    assert meta["hint"]["guidance_delta"] == -0.5 and meta["vae_mode"] == "fp16"
