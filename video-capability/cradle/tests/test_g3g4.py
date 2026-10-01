"""G3 一致性 / G4 稳定性: 可注入 CLIP stub, 相似度计算与 RAFT 留桩。"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from src.gates.g3_consistency import cosine, g3_consistency, min_similarity_vs_ref
from src.gates.g4_stability import g4_stability, min_adjacent_similarity, raft_residual_p95


@pytest.fixture
def frames(tmp_path):
    paths = []
    for i in range(4):
        p = tmp_path / f"f{i}.png"
        Image.new("RGB", (8, 8), (i * 30, 0, 0)).save(p)
        paths.append(str(p))
    ref = tmp_path / "ref.png"
    Image.new("RGB", (8, 8), (10, 10, 10)).save(ref)
    return paths, str(ref)


class PixelEmbed:
    """按首像素红色通道返回指定向量, 构造可控相似度(PIL convert 后 filename 不保证保留)。"""

    def __init__(self, vec_by_red):
        self.vec_by_red = vec_by_red

    def __call__(self, img):
        key = img.getpixel((0, 0))[0]
        if key not in self.vec_by_red:
            raise KeyError(f"未配置红色通道 {key}")
        return np.asarray(self.vec_by_red[key], dtype="float64")


def test_cosine():
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine([1, 0], [-1, 0]) == pytest.approx(-1.0)
    assert cosine([0, 0], [1, 0]) == 0.0


def test_g3_pass_and_fail(frames):
    paths, ref = frames
    emb = PixelEmbed({
        10: [1.0, 0.0],      # ref (10,10,10)
        0: [0.99, 0.14],     # f0
        30: [0.98, 0.19],    # f1
        60: [0.70, 0.71],    # f2  cos≈0.834
        90: [0.66, 0.75],    # f3  cos≈0.801 ← 最小
    })
    g = g3_consistency(paths, ref, emb, clip_ref_min=0.65)
    assert g["passed"] is True and g["score"] == pytest.approx(0.661, abs=1e-2)
    assert g["detail"]["n_frames"] == 4

    g2 = g3_consistency(paths, ref, emb, clip_ref_min=0.85)
    assert g2["passed"] is False


def test_g3_no_frames():
    class Boom:
        def __call__(self, img):
            raise AssertionError("不应调用")

    g = g3_consistency([], "ref.png", Boom(), clip_ref_min=0.5)
    assert g["passed"] is False


def test_min_similarity_vs_ref():
    assert min_similarity_vs_ref([1.0, 0.0], [[1.0, 0.0], [0.7071, 0.7071]]) == pytest.approx(0.7071, abs=1e-3)
    assert min_similarity_vs_ref([1.0, 0.0], []) == 0.0


def test_g4_adjacent_pass_fail(frames):
    paths, _ = frames
    emb = PixelEmbed({
        0: [1.0, 0.0],
        30: [0.9999, 0.014],   # 相邻 sim≈1
        60: [0.99, 0.141],     # sim≈0.99
        90: [0.86, 0.51],      # sim≈0.958
    })
    g = g4_stability(paths, emb, temporal_clip_min=0.85)
    assert g["passed"] is True and g["detail"]["raft_skipped"] is True

    emb2 = PixelEmbed({
        0: [1.0, 0.0],
        30: [1.0, 0.0],
        60: [1.0, 0.0],
        90: [0.0, 1.0],        # 最后一跳 sim=0
    })
    g2 = g4_stability(paths, emb2, temporal_clip_min=0.85)
    assert g2["passed"] is False and g2["score"] == 0.0


def test_g4_insufficient_frames(frames):
    paths, _ = frames
    g = g4_stability(paths[:1], PixelEmbed({}), temporal_clip_min=0.5)
    assert g["passed"] is False and "不足" in g["detail"]["error"]


def test_g4_with_raft_fn(frames):
    paths, _ = frames
    emb = PixelEmbed({0: [1.0, 0.0], 30: [1.0, 0.0], 60: [1.0, 0.0], 90: [1.0, 0.0], 10: [1.0, 0.0]})
    g = g4_stability(paths, emb, temporal_clip_min=0.5, raft_fn=lambda ps: 0.10, raft_p95_max=0.2)
    assert g["passed"] is True and g["detail"]["raft_p95"] == 0.10
    g2 = g4_stability(paths, emb, temporal_clip_min=0.5, raft_fn=lambda ps: 0.30, raft_p95_max=0.2)
    assert g2["passed"] is False
    # RAFT 抛异常 → 视为不可用, 跳过
    def boom(ps):
        raise RuntimeError("no raft")
    g3 = g4_stability(paths, emb, temporal_clip_min=0.5, raft_fn=boom)
    assert g3["passed"] is True and g3["detail"]["raft_skipped"] is True


def test_min_adjacent_similarity():
    assert min_adjacent_similarity([]) == 0.0
    assert min_adjacent_similarity([[1.0, 0.0]]) == 0.0
    assert min_adjacent_similarity([[1.0, 0.0], [0.0, 1.0], [0.0, 1.0]]) == pytest.approx(0.0)


def test_raft_stub_returns_none():
    assert raft_residual_p95([], raft_fn=None) is None
