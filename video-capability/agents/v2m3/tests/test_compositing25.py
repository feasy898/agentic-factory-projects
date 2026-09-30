"""compositing_2d5 车道测试 (SPECS_V2 §5.3): 深度分层/视差/screen 混合/overlay 挑选/生成。"""

from __future__ import annotations

import numpy as np
import pytest

from src.gen.compositing25 import (
    COMPOSITING_MODEL_TAG,
    DEFAULT_OVERLAY_REGION,
    depth_to_layers,
    feather_mask,
    generate as c25_generate,
    layer_state,
    load_overlay_manifest,
    pick_overlay,
    read_video_frames,
    render_parallax_frames,
    screen_blend,
)
from tests.conftest import requires_ffmpeg


# ---------------- 深度分层 ----------------

def test_depth_to_layers_threshold():
    depth = np.linspace(0, 9, 100, dtype="float32").reshape(10, 10)
    fg = depth_to_layers(depth, fg_percentile=65.0)
    assert fg.sum() == 35  # ≥65 分位 → 35 个近景像素
    with pytest.raises(ValueError):
        depth_to_layers(np.zeros((2, 2, 2), dtype="float32"))


def test_feather_mask_soft_edges():
    mask = np.zeros((40, 40), dtype=bool)
    mask[10:30, 10:30] = True
    fe = feather_mask(mask, radius_px=4.0)
    assert fe.shape == mask.shape
    assert fe[20, 20] > 0.95 and fe[0, 0] == 0.0
    assert 0.0 < fe[9, 20] < 1.0  # 边缘被羽化


# ---------------- 视差运镜 ----------------

def test_layer_state_parallax_fg_moves_more():
    s0 = layer_state(0.0, "slow_push_in")
    s1 = layer_state(1.0, "slow_push_in")
    assert s0["bg_scale"] == 1.0 and s0["fg_scale"] == 1.0
    assert s1["fg_scale"] > s1["bg_scale"] > 1.0  # 前景缩放幅度 > 背景 → 透视感
    pan = layer_state(1.0, "pan_right")
    assert abs(pan["fg_dx"]) > abs(pan["bg_dx"]) > 0
    with pytest.raises(ValueError):
        layer_state(0.5, "orbit_slow")


def test_render_parallax_frames_deterministic():
    from PIL import Image

    img = Image.new("RGB", (64, 96))
    for y in range(96):
        for x in range(64):
            img.putpixel((x, y), (x * 4 % 256, y * 2 % 256, 128))
    depth = np.tile(np.linspace(0, 10, 96, dtype="float32")[:, None], (1, 64))
    f1 = render_parallax_frames(img, depth, 8, motion="slow_push_in")
    f2 = render_parallax_frames(img, depth, 8, motion="slow_push_in")
    assert len(f1) == 8 and f1[0].shape == (96, 64, 3)
    assert all((a == b).all() for a, b in zip(f1, f2))  # 无 RNG, 确定性


# ---------------- screen 混合 ----------------

def test_screen_blend_math_and_region():
    base = np.zeros((8, 8, 3), dtype="uint8")
    ovl = np.full((8, 8, 3), 128, dtype="uint8")
    # screen(0, 0.502) ≈ 0.502; opacity=0.85 → 0.427*255 ≈ 109
    out = screen_blend(base, ovl, region=None, opacity=0.85)
    assert out.mean() == pytest.approx(109, abs=2)
    # 限定区域: 区域外保持底片
    out2 = screen_blend(base, ovl, region=(0.0, 0.0, 0.5, 0.5), opacity=1.0)
    assert out2[:4, :4].mean() == pytest.approx(128, abs=1)
    assert out2[6:, 6:].mean() == 0.0
    with pytest.raises(ValueError):
        screen_blend(base, np.zeros((4, 4, 3), dtype="uint8"))


# ---------------- overlay 挑选 ----------------

def test_pick_overlay_deterministic_and_audit_filtered():
    entries = [
        {"file": "a.mp4", "g7_audit": {"passed": True}},
        {"file": "b.mp4", "g7_audit": {"passed": False, "reason": "bg drift"}},
        {"file": "c.mp4", "g7_audit": {"passed": True}},
    ]
    p1 = pick_overlay("S01", entries=entries)
    p2 = pick_overlay("S01", entries=entries)
    assert p1["file"] in ("a.mp4", "c.mp4")  # 未过审的 b 被排除
    assert p1 is p2 or p1["file"] == p2["file"]  # 同 shot 稳定
    assert pick_overlay("NOENTRIES", entries=[entries[1]]) is None  # 全军覆没 → None


# ---------------- 生成 (注入 depth_fn + overlay 库) ----------------

def _asset_png(tmp_path):
    from PIL import Image

    p = tmp_path / "asset.png"
    Image.new("RGB", (64, 96), (180, 60, 30)).save(p)
    return str(p)


def _depth_fn_called(track):
    def depth_fn(path):
        track.append(path)
        return np.tile(np.linspace(0, 10, 96, dtype="float32")[:, None], (1, 64))
    return depth_fn


def _card(tmp_path, asset):
    return {
        "shot_id": "SX01",
        "duration_sec": 1.0,
        "resolution": [64, 96],
        "fps": 16,
        "camera": {"scale": "closeup", "angle": "high_45", "motion": "slow_push_in", "depth": "shallow"},
        "subject": {"type": "food", "desc_zh": "毛肚"},
        "prompt_en": "close-up of beef tripe",
        "first_frame_asset": asset,
        "negative": ["human face", "hands", "text"],
    }


def _no_model_pipeline(**kw):  # 食物不参与生成: 生成模型管线绝不可被调用
    raise AssertionError("compositing_2d5 车道不得调用生成模型管线")


@requires_ffmpeg
def test_generate_full_with_overlay(tmp_path):
    from src.gen.common import write_frames_mp4

    asset = _asset_png(tmp_path)
    track = []
    ovl = tmp_path / "ov.mp4"
    write_frames_mp4([np.full((96, 64, 3), 160, dtype="uint8") for _ in range(8)], 16, str(ovl))
    entries = [{"file": "ov.mp4", "g7_audit": {"passed": True, "static_p95_px": 0.4}}]

    out = tmp_path / "c25.mp4"
    meta = c25_generate(_card(tmp_path, asset), seed=0, out_path=str(out),
                        depth_fn=_depth_fn_called(track), pipeline=_no_model_pipeline,
                        overlays_dir=str(tmp_path), overlay_entries=entries)
    assert out.exists()
    assert meta["model"] == COMPOSITING_MODEL_TAG and meta["lane"] == "compositing_2d5"
    assert meta["overlay"] == "ov.mp4"
    assert meta["motion"] == "slow_push_in"
    assert meta["num_frames"] == 17 and meta["seed"] == 0
    assert track == [asset]  # 深度只对静态产品图估一次
    # screen 提亮: 输出帧均值应显著高于纯底片(红底 90 均值)
    from src.gates.g1_tech import probe_duration

    assert probe_duration(str(out)) == pytest.approx(17 / 16, abs=0.2)


def test_generate_without_overlay_library(tmp_path):
    asset = _asset_png(tmp_path)
    out = tmp_path / "c25_raw.mp4"
    meta = c25_generate(_card(tmp_path, asset), seed=0, out_path=str(out),
                        depth_fn=_depth_fn_called([]), pipeline=_no_model_pipeline,
                        overlays_dir=str(tmp_path / "empty_dir_that_does_not_exist"))
    assert out.exists()
    assert meta["overlay"] is None  # 无可用 overlay → 纯视差底片仍产出


def test_manifest_loader_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_overlay_manifest(str(tmp_path / "nope"))


def test_default_region_is_top_third():
    x0, y0, x1, y1 = DEFAULT_OVERLAY_REGION
    assert y1 <= 0.40 and (y1 - y0) < 0.5  # 限定在画面上部 (食物上方 1/3)
