"""G4 稳定性门禁: 相邻帧 CLIP 相似度最小值 ≥ temporal_clip_min (+可选 RAFT 残差 P95 接口留桩)。"""

from __future__ import annotations

from . import make_gate
from .g3_consistency import cosine, default_embed_fns, load_image  # re-export 便于统一注入


def raft_residual_p95(frame_paths: list[str], raft_fn=None) -> float | None:
    """RAFT-small 光流残差 P95 留桩 (SPECS §3 '尽力')。

    raft_fn(frame_paths)->float 可注入; 缺省返回 None(跳过该子判据), 不阻塞门禁。
    """
    if raft_fn is None:
        return None
    try:
        return float(raft_fn(frame_paths))
    except Exception:
        return None


def min_adjacent_similarity(embs: list) -> float:
    if len(embs) < 2:
        return 0.0
    return min(cosine(embs[i], embs[i + 1]) for i in range(len(embs) - 1))


def g4_stability(
    frame_paths: list[str],
    image_embed,
    temporal_clip_min: float = 0.85,
    raft_fn=None,
    raft_p95_max: float = 0.20,
) -> dict:
    """G4: 相邻帧相似度最小值达标, 且(若可用)RAFT 残差 P95 ≤ raft_p95_max。"""
    if len(frame_paths) < 2:
        return make_gate("G4", False, 0.0, error="抽帧数不足(<2)")
    embs = [image_embed(load_image(p)) for p in frame_paths]
    worst = float(min_adjacent_similarity(embs))
    raft = raft_residual_p95(frame_paths, raft_fn=raft_fn)
    passed = worst >= temporal_clip_min and (raft is None or raft <= raft_p95_max)
    return make_gate(
        "G4", passed, round(worst, 4),
        min_adjacent_similarity=round(worst, 4), threshold=temporal_clip_min,
        raft_p95=raft, raft_p95_max=raft_p95_max if raft is not None else None,
        raft_skipped=raft is None,
        n_frames=len(frame_paths),
    )
