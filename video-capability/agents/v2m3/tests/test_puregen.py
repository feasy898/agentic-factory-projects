"""pure_gen_short 车道测试 (SPECS_V2 §5.2): prompt 模板/帧数/反形变词表/锚定/分段法。"""

from __future__ import annotations

import numpy as np
import pytest

from src.gen.puregen import (
    FIXED_CAMERA_PROMPT,
    PUREGEN_MAX_FRAMES,
    PUREGEN_MODEL_TAG,
    PUREGEN_NEGATIVE_EXTRA,
    build_puregen_prompt,
    frames_for_puregen,
    generate as puregen_generate,
    segmented_generate,
    validate_puregen_duration,
)
from tests.conftest import requires_ffmpeg


def _card(duration=1.5):
    return {
        "shot_id": "SX09",
        "duration_sec": duration,
        "resolution": [480, 832],
        "fps": 16,
        "camera": {"scale": "wide", "angle": "eye_level", "motion": "static_hold", "depth": "medium"},
        "subject": {"type": "environment", "desc_zh": "雨窗氛围"},
        "prompt_en": "rain drops sliding down a window pane, warm bokeh",
        "first_frame_asset": "assets/scenes/rain_window_01.png",
        "negative": ["human face", "hands", "text", "watermark"],
    }


def _stub_pipeline(calls):
    def fake(**kw):
        calls.append(kw)
        return [np.full((16, 24, 3), 128, dtype="uint8") for _ in range(kw["num_frames"])]
    return fake


# ---------------- 纯函数 ----------------

def test_prompt_template_fixed_camera():
    p = build_puregen_prompt("rain window, warm bokeh")
    assert "rain window, warm bokeh" in p
    for token in ("fixed camera", "locked tripod", "steam and light moves"):
        assert token in p
    assert FIXED_CAMERA_PROMPT in p


def test_frames_for_puregen_bounds():
    assert frames_for_puregen(1.0) == 17
    assert frames_for_puregen(1.5) == 25
    assert frames_for_puregen(2.0) == 33
    assert PUREGEN_MAX_FRAMES == 33
    with pytest.raises(ValueError):
        frames_for_puregen(2.5)  # 超 1-2s
    with pytest.raises(ValueError):
        validate_puregen_duration(0.5)


def test_negative_extra_antideform_terms():
    for term in ("melting", "liquid", "dissolving", "fluid", "morphing", "splitting", "floating debris"):
        assert term in PUREGEN_NEGATIVE_EXTRA


# ---------------- 生成 (注入 stub) ----------------

def test_generate_with_stub_pipeline(tmp_path):
    calls = []
    out = tmp_path / "pg.mp4"
    meta = puregen_generate(_card(), seed=42, out_path=str(out), steps=20,
                            pipeline=_stub_pipeline(calls))
    assert out.exists()
    assert meta["model"] == PUREGEN_MODEL_TAG and meta["lane"] == "pure_gen_short"
    assert meta["num_frames"] == 25
    # 固定机位进 prompt
    assert "fixed camera" in calls[0]["prompt"]
    # 反形变 negative 合并
    joined = " | ".join(calls[0]["negative"])
    assert "melting" in joined and "morphing" in joined and "human face" in joined
    # 首尾帧锚定: end_image 缺省=首帧资产 (锁定机位 → 首尾同帧)
    assert calls[0]["end_image"] == "assets/scenes/rain_window_01.png"
    assert meta["anchor"]["mode"] == "end_image"


def test_generate_rejects_long_duration(tmp_path):
    with pytest.raises(ValueError):
        puregen_generate(_card(duration=5), seed=1, out_path=str(tmp_path / "x.mp4"),
                         pipeline=lambda **kw: [])


# ---------------- 分段法 (路径 b, 注入 segment_fn + 真实 ffmpeg 拼接) ----------------

@requires_ffmpeg
def test_segmented_generate_two_segments(tmp_path):
    def segment_fn(start_frame, seg_out, n_frames, seg_seed):
        frames = [np.full((16, 24, 3), 100, dtype="uint8") for _ in range(n_frames)]
        from src.gen.common import write_frames_mp4

        write_frames_mp4(frames, 16, seg_out)
        assert start_frame  # 每段都有首帧锚
        return {"path": seg_out}

    meta = segmented_generate(_card(duration=2.0), seed=7, out_path=str(tmp_path / "seg.mp4"),
                              segment_fn=segment_fn)
    assert meta["anchor"]["mode"] == "segmented"
    assert meta["anchor"]["segments"] == 2  # 33 帧 = 两段 17 帧 (末段 4k+1 吸附略过冲 ≤3 帧)
    from src.gates.g1_tech import probe_duration

    assert probe_duration(meta["path"]) == pytest.approx(34 / 16, abs=0.15)
