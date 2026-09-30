"""G3 一致性门禁: 每帧 vs 首帧参考图的 CLIP 相似度最小值 ≥ clip_ref_min。

CLIP 特征提取抽象为可注入函数 image_embed(PIL.Image|path)->np向量, 便于 stub;
缺省 lazy 加载 open_clip ViT-L/14 (SPECS §3)。
"""

from __future__ import annotations

import numpy as np

from . import make_gate


def cosine(a, b) -> float:
    a = np.asarray(a, dtype="float64")
    b = np.asarray(b, dtype="float64")
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def min_similarity_vs_ref(ref_emb, embs) -> float:
    if not embs:
        return 0.0
    return min(cosine(ref_emb, e) for e in embs)


_EMBED_CACHE: dict = {}  # 进程级缓存(候选间复用, 避免逐候选重载 ViT-L/14)


def _openai_clip_weights() -> str:
    """openai 权重本地路径优先(pretrained="openai" 会走 HF hub, 离线/慢源不可用, D-027)。"""
    import os

    env_p = os.environ.get("CRADLE_CLIP_WEIGHTS", "")
    if env_p and os.path.exists(env_p):
        return env_p
    try:
        from ..config import project_root

        local = project_root() / "models" / "clip" / "ViT-L-14.pt"
        if local.exists():
            return str(local)
    except Exception:
        pass
    return "openai"


def default_embed_fns(device: str = "cpu"):
    """返回 (image_embed, text_embed); lazy import open_clip, 不可用抛 RuntimeError。"""
    if device in _EMBED_CACHE:
        return _EMBED_CACHE[device]
    try:
        import open_clip
        import torch
        from PIL import Image
    except Exception as e:  # pragma: no cover
        raise RuntimeError(f"open_clip 本地依赖不可用: {e}") from e
    model, _, preprocess = open_clip.create_model_and_transforms("ViT-L-14", pretrained=_openai_clip_weights())
    model = model.to(device).eval()
    tokenizer = open_clip.get_tokenizer("ViT-L-14")

    def image_embed(img):
        if not hasattr(img, "convert"):
            img = Image.open(img)
        with torch.no_grad():
            f = model.encode_image(preprocess(img.convert("RGB")).unsqueeze(0).to(device))
        return (f / f.norm(dim=-1, keepdim=True)).squeeze(0).cpu().numpy()

    def text_embed(text):
        with torch.no_grad():
            f = model.encode_text(tokenizer([text]).to(device))
        return (f / f.norm(dim=-1, keepdim=True)).squeeze(0).cpu().numpy()

    _EMBED_CACHE[device] = (image_embed, text_embed)
    return _EMBED_CACHE[device]


def load_image(path: str):
    from PIL import Image

    return Image.open(path).convert("RGB")


def g3_consistency(
    frame_paths: list[str],
    ref_image_path: str,
    image_embed,
    clip_ref_min: float = 0.65,
) -> dict:
    """G3: 每帧与首帧参考相似度最小值 ≥ clip_ref_min。image_embed 必须注入或由调用方给默认。"""
    if not frame_paths:
        return make_gate("G3", False, 0.0, error="无抽帧")
    ref = image_embed(load_image(ref_image_path))
    sims = [cosine(ref, image_embed(load_image(p))) for p in frame_paths]
    worst = float(min(sims))
    passed = worst >= clip_ref_min
    return make_gate(
        "G3", passed, round(worst, 4),
        min_similarity=round(worst, 4), threshold=clip_ref_min,
        n_frames=len(frame_paths),
        similarities=[round(float(s), 4) for s in sims],
    )
