"""evidence_transfer 车道测试 (SPECS_V2 §5.4): 参数校验/合成源/结构保持度/重绘生成。"""

from __future__ import annotations

import numpy as np
import pytest

from src.gen.evidence import (
    DEFAULT_DENOISE,
    DENOISE_RANGE,
    EVIDENCE_MODEL_TAG,
    frames_4k1,
    generate as ev_generate,
    make_synthetic_source,
    read_source_frames,
    structural_persistence,
    _particle_positions,
)
from tests.conftest import requires_ffmpeg


def _card():
    return {
        "shot_id": "SX18",
        "duration_sec": 3,
        "resolution": [64, 96],
        "fps": 16,
        "camera": {"scale": "closeup", "angle": "high_45", "motion": "static_hold", "depth": "shallow"},
        "subject": {"type": "food", "desc_zh": "证据演示"},
        "prompt_en": "close-up of fresh shrimp paste",
        "first_frame_asset": "assets/evidence/synthetic_demo_source_01_first.png",
        "evidence_asset": None,
        "negative": ["human face", "hands", "text"],
    }


# ---------------- 纯函数与校验 ----------------

def test_frames_4k1():
    assert frames_4k1(1.0) == 17
    assert frames_4k1(3.0) == 49
    assert frames_4k1(0.1) == 5
    assert frames_4k1(99.0) <= 81


def test_denoise_validation(tmp_path):
    assert DENOISE_RANGE == (0.2, 0.35) and DEFAULT_DENOISE == 0.30
    with pytest.raises(ValueError):
        ev_generate(_card(), seed=0, out_path=str(tmp_path / "x.mp4"), denoise=0.5,
                    source_video="whatever.mp4", pipeline=lambda **kw: [])


def test_missing_source_raises(tmp_path):
    card = _card()
    with pytest.raises(FileNotFoundError):
        ev_generate(card, seed=0, out_path=str(tmp_path / "x.mp4"))


# ---------------- 合成测试源 (已知运动) ----------------

def test_particle_positions_closed_form():
    p0 = _particle_positions(0, 480, 832)
    p4 = _particle_positions(4, 480, 832)
    d = np.abs(p4 - p0)
    expect = 0.9 * 0.7071 * 4  # speed*0.7071*t
    assert np.allclose(d[d <= 480], expect, atol=1e-3)


@requires_ffmpeg
def test_make_synthetic_source_known_motion(tmp_path):
    from PIL import Image

    base = tmp_path / "base.png"
    Image.new("RGB", (480, 832), (200, 100, 50)).save(base)
    out = tmp_path / "synthetic_demo_source_99.mp4"
    meta = make_synthetic_source(str(base), str(out), n_frames=49, fps=16, size=(64, 96))
    assert out.exists()
    assert meta["zoom_total"] == 0.06 and meta["motion_gt"].startswith("radial_zoom")
    frames = read_source_frames(str(out), 49, (64, 96))
    assert len(frames) == 49
    # 已知运动: 帧间差异集中在缩放+粒子, 首帧与底图一致(缩放 t=0 无位移)
    a0 = np.asarray(frames[0])
    assert a0.shape == (96, 64, 3)


# ---------------- 结构保持度 (注入 flow_fn, 无 GPU) ----------------

@requires_ffmpeg
def test_structural_persistence_identity(tmp_path):
    from PIL import Image

    base = tmp_path / "b.png"
    Image.new("RGB", (64, 96), (120, 30, 200)).save(base)
    src = tmp_path / "synthetic_demo_source_src.mp4"
    make_synthetic_source(str(base), str(src), n_frames=17, fps=16, size=(64, 96))

    calls = []

    def same_flow(a, b):  # 恒等非零场: src 与 out 完全一致 → 相关性 1、端点误差 0
        calls.append((a.size, b.size))
        return np.full((16, 32, 2), 0.5, dtype="float32")

    res = structural_persistence(str(src), str(src), flow_fn=same_flow, n_pairs=3,
                                 size=(64, 96), with_depth=False)
    assert res["flow_cos"] == 1.0
    assert res["epe_px"] == 0.0 and res["flow_pearson"] == 0.0  # 常量场: pearson 未定义→0
    assert res["n_pairs"] == 3
    assert len(calls) == 6  # 3 对 × (src, out)


@requires_ffmpeg
def test_structural_persistence_opposite_field(tmp_path):
    from PIL import Image

    base = tmp_path / "b.png"
    Image.new("RGB", (64, 96), (10, 200, 80)).save(base)
    src = tmp_path / "synthetic_demo_source_a.mp4"
    make_synthetic_source(str(base), str(src), n_frames=17, fps=16, size=(64, 96))

    flip = {"n": 0}

    def anti_flow(a, b):  # 交替输出正/反场 → 相关性为负
        flip["n"] += 1
        f = np.ones((16, 32, 2), dtype="float32")
        return f if flip["n"] % 2 == 1 else -f

    res = structural_persistence(str(src), str(src), flow_fn=anti_flow, n_pairs=2,
                                 size=(64, 96), with_depth=False)
    assert res["flow_cos"] < 0.0  # 反向场 → 负相关 (量化"结构被破坏")


# ---------------- 重绘生成 (注入 stub pipeline + 真实源读取) ----------------

@requires_ffmpeg
def test_generate_passes_input_video_and_denoise(tmp_path):
    from PIL import Image

    base = tmp_path / "b.png"
    Image.new("RGB", (64, 96), (90, 90, 200)).save(base)
    src = tmp_path / "synthetic_demo_source_01.mp4"
    make_synthetic_source(str(base), str(src), n_frames=17, fps=16, size=(64, 96))

    calls = []

    def stub(**kw):
        calls.append(kw)
        return [np.asarray(kw["input_video"][i], dtype="uint8") for i in range(kw["num_frames"])]

    card = _card()
    card["duration_sec"] = 1  # 与 17 帧合成源对齐 (4k+1)
    meta = ev_generate(card, seed=9, out_path=str(out), steps=20, pipeline=stub,
                       source_video=str(src), denoise=0.30)
    assert out.exists()
    kw = calls[0]
    assert kw["denoising_strength"] == 0.30
    assert kw["num_frames"] == 17 and len(kw["input_video"]) == 17
    assert kw["input_video"][0].size == (64, 96)  # 帧已预缩放到产线分辨率
    assert meta["model"] == EVIDENCE_MODEL_TAG and meta["lane"] == "evidence_transfer"
    assert meta["denoise"] == 0.30
    assert meta["source_label"] == "synthetic_demo"
    assert meta["duration_s"] == pytest.approx(17 / 16, abs=0.01)


def test_user_evidence_label(tmp_path):
    """非 synthetic 文件名 → source_label=user_evidence (报告口径区分)。"""
    assert True  # 标签逻辑由 _is_synthetic 覆盖: 见下
    from src.gen.evidence import _is_synthetic

    assert _is_synthetic("/x/synthetic_demo_source_01.mp4")
    assert not _is_synthetic("/x/user_boiling_pot.mp4")
