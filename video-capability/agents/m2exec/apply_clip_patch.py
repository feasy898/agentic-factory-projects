#!/usr/bin/env python3
"""M2-EXEC patch 2: open_clip 权重本地化 — pretrained="openai" 会走 HF hub(离线/慢源不可用),
改为优先用 models/clip/ViT-L-14.pt 本地文件(M1 已验证该文件 open_clip 可加载, D-027)。"""
import sys
from pathlib import Path

REPO = Path("~/cradle").expanduser()


def patch(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    n = text.count(old)
    assert n == 1, f"[{label}] 期望命中 1 次, 实际 {n} 次: {path}"
    path.write_text(text.replace(old, new), encoding="utf-8")
    print(f"patched {label} -> {path.name}")


HELPER = '''def _openai_clip_weights() -> str:
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


'''

# g3_consistency.default_embed_fns
patch(
    REPO / "src/gates/g3_consistency.py",
    '''def default_embed_fns(device: str = "cpu"):''',
    HELPER + '''def default_embed_fns(device: str = "cpu"):''',
    "g3-clip-weights-helper",
)
patch(
    REPO / "src/gates/g3_consistency.py",
    '    model, _, preprocess = open_clip.create_model_and_transforms("ViT-L-14", pretrained="openai")',
    '    model, _, preprocess = open_clip.create_model_and_transforms("ViT-L-14", pretrained=_openai_clip_weights())',
    "g3-clip-weights-use",
)

# api/vlm._load_clip_fns
patch(
    REPO / "src/api/vlm.py",
    '''def _load_clip_fns(device: str = "cpu"):''',
    HELPER + '''def _load_clip_fns(device: str = "cpu"):''',
    "vlm-clip-weights-helper",
)
patch(
    REPO / "src/api/vlm.py",
    '    model, _, preprocess = open_clip.create_model_and_transforms("ViT-L-14", pretrained="openai")',
    '    model, _, preprocess = open_clip.create_model_and_transforms("ViT-L-14", pretrained=_openai_clip_weights())',
    "vlm-clip-weights-use",
)

print("ALL PATCHES OK")
