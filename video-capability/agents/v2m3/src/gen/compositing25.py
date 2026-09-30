"""compositing_2d5 车道 (SPECS_V2 §5.3) — 食物/产品镜头默认车道。

核心逻辑: 生成的循环素材只负责"氛围粒子"(蒸汽/雾/光斑 overlay), 物体的形与
运动全部来自程序 (深度分层视差运镜)。食物永远不会变形, 因为它根本不参与生成
——物体形变被物理性消灭。

管线 (全纯代码, 可单测):
  静态产品图 → Depth-Anything-V1-Small 深度图 (可注入 depth_fn)
  → 深度分层 (前景=近景高分位, 背景=其余) + 羽化
  → 视差运镜 (前景/背景两层差异位移+缩放, 近景移动幅度大于远景 → 透视感)
  → 底片序列
  → overlay 循环素材 (assets/overlays/, Wan 生成后过 G7 审计) 以 screen 混合
    限定区域 (默认画面上方 1/3) 合成 → 输出 mp4。
"""

from __future__ import annotations

import json
import os
import subprocess
import zlib
from pathlib import Path

import numpy as np
from PIL import Image

from ..config import project_root
from .common import even, timed, write_frames_mp4
from .wan import LTX_FPS, frames_for_duration

COMPOSITING_MODEL_TAG = "compositing_2d5"
OVERLAYS_DIR = "assets/overlays"
OVERLAYS_MANIFEST = "manifest.json"
# screen 混合默认限定区域 (归一化 x0,y0,x1,y1): 食物上方 1/3 (SPECS_V2 §5.3)
DEFAULT_OVERLAY_REGION = (0.06, 0.03, 0.94, 0.36)
# 视差幅度: 背景缩放小/位移小, 前景大 → 透视感 (近景视差 > 远景)。
# pan 单位=可用平移余量的占比 (-1..1, 1=吃满裁剪余量), 前景位移幅度 > 背景。
PARALLAX_PRESETS: dict[str, dict] = {
    "slow_push_in": {"bg_zoom": 0.04, "fg_zoom": 0.11, "bg_pan": 0.0, "fg_pan": 0.0},
    "zoom_in_1.06": {"bg_zoom": 0.045, "fg_zoom": 0.12, "bg_pan": 0.0, "fg_pan": 0.0},
    "pan_left": {"bg_zoom": 0.02, "fg_zoom": 0.05, "bg_pan": -0.35, "fg_pan": -1.0},
    "pan_right": {"bg_zoom": 0.02, "fg_zoom": 0.05, "bg_pan": 0.35, "fg_pan": 1.0},
    "zoom_out": {"bg_zoom": 0.03, "fg_zoom": 0.09, "bg_pan": 0.0, "fg_pan": 0.0},
}
DEFAULT_MOTION = "slow_push_in"

# 进程级深度管线缓存
_DEPTH_CACHE: dict = {}


# ---------------- 深度估计 ----------------

def get_depth_pipeline():
    """Depth-Anything-V1-Small 管线 (models/depth-anything-small-hf, D-054), 进程级缓存。

    返回可调用 fn(PIL.Image) -> {"depth": PIL.Image, ...} (transformers depth-estimation)。
    """
    key = "depth_anything_small"
    if key not in _DEPTH_CACHE:
        import torch
        from transformers import pipeline as hf_pipeline

        model_dir = project_root() / "models" / "depth-anything-small-hf"
        _DEPTH_CACHE[key] = hf_pipeline(
            "depth-estimation", model=str(model_dir),
            device="cuda" if torch.cuda.is_available() else "cpu",
        )
    return _DEPTH_CACHE[key]


def default_depth_fn(image_path: str) -> np.ndarray:
    """图像路径 → HxW float 深度图 (值大=近)。"""
    out = get_depth_pipeline()(Image.open(image_path).convert("RGB"))
    return np.asarray(out["depth"], dtype="float32")


# ---------------- 深度分层与视差运镜 (纯函数) ----------------

def depth_to_layers(depth: np.ndarray, fg_percentile: float = 65.0) -> np.ndarray:
    """深度图 → 前景掩码 (深度 ≥ fg_percentile 分位 = 近景层)。纯函数。"""
    d = np.asarray(depth, dtype="float32")
    if d.ndim != 2 or d.size == 0:
        raise ValueError("深度图必须为非空二维数组")
    tau = float(np.percentile(d, fg_percentile))
    return d >= tau


def feather_mask(mask: np.ndarray, radius_px: float = 12.0) -> np.ndarray:
    """布尔掩码 → 羽化 float 掩码 [0,1] (PIL 高斯模糊, 边缘平滑防硬边)。"""
    from PIL import ImageFilter

    m = Image.fromarray((np.asarray(mask) * 255).astype("uint8"), mode="L")
    if radius_px > 0:
        m = m.filter(ImageFilter.GaussianBlur(radius=float(radius_px)))
    return np.asarray(m, dtype="float32") / 255.0


def layer_state(t_norm: float, motion: str) -> dict:
    """归一化时间 t_norm∈[0,1] + motion → 层变换参数 (纯函数, 帧间线性)。"""
    preset = PARALLAX_PRESETS.get(motion)
    if preset is None:
        raise ValueError(f"未知视差 motion: {motion!r} (支持: {sorted(PARALLAX_PRESETS)})")
    t = max(0.0, min(1.0, float(t_norm)))
    zoom_out = motion == "zoom_out"
    zf = (1.0 - t) if zoom_out else t
    return {
        "bg_scale": 1.0 + preset["bg_zoom"] * zf,
        "fg_scale": 1.0 + preset["fg_zoom"] * zf,
        "bg_dx": preset["bg_pan"] * t,   # 归一化位移 (相对宽)
        "fg_dx": preset["fg_pan"] * t,
        "bg_dy": 0.0,
        "fg_dy": 0.0,
    }


def _crop_resize(img: Image.Image, scale: float, dx_norm: float, out_w: int, out_h: int) -> Image.Image:
    """以中心为锚按 scale 裁剪 + 按 dx_norm∈[-1,1] 吃裁剪余量平移, resize 到输出尺寸。"""
    W, H = img.size
    cw, ch = W / scale, H / scale
    margin = (W - cw) / 2.0
    cx = W / 2 + float(dx_norm) * margin
    cy = H / 2
    box = (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
    return img.resize((out_w, out_h), Image.BILINEAR, box=box)


def render_parallax_frames(
    image: Image.Image,
    depth: np.ndarray,
    n_frames: int,
    motion: str = DEFAULT_MOTION,
    fg_percentile: float = 65.0,
    feather_radius_frac: float = 0.018,
) -> list[np.ndarray]:
    """底片序列渲染: 前景/背景两层差异缩放+位移 → 2.5D 视差。确定性 (无 RNG)。

    image: 原图 (任意尺寸, 内部统一到目标); depth: 与 image 同分辨率 HxW。
    """
    W, H = even(image.width), even(image.height)
    img = image.resize((W, H), Image.LANCZOS)
    depth_full = np.asarray(
        Image.fromarray(_normalize_depth(depth)).resize((W, H), Image.BILINEAR)
    )
    fg_mask = depth_to_layers(depth_full, fg_percentile)
    radius = max(2.0, feather_radius_frac * min(W, H))
    fg_alpha = feather_mask(fg_mask, radius)
    fg_layer = img.copy()
    fg_layer.putalpha(Image.fromarray((fg_alpha * 255).astype("uint8"), mode="L"))

    frames: list[np.ndarray] = []
    for i in range(int(n_frames)):
        st = layer_state(i / max(1, n_frames - 1), motion)
        bg = _crop_resize(img, st["bg_scale"], st["bg_dx"], W, H)
        fg = _crop_resize(fg_layer, st["fg_scale"], st["fg_dx"], W, H)
        frame = Image.alpha_composite(bg.convert("RGBA"), fg).convert("RGB")
        frames.append(np.asarray(frame, dtype="uint8"))
    return frames


def _normalize_depth(depth: np.ndarray) -> np.ndarray:
    d = np.asarray(depth, dtype="float32")
    lo, hi = float(d.min()), float(d.max())
    if hi - lo < 1e-6:
        return np.zeros_like(d, dtype="uint8")
    return ((d - lo) / (hi - lo) * 255.0).astype("uint8")


# ---------------- overlay 素材库与 screen 合成 ----------------

def screen_blend(base: np.ndarray, overlay: np.ndarray, region=None, opacity: float = 0.85) -> np.ndarray:
    """screen 混合 (黑=不变, 越亮越提亮), 可限定归一化区域。纯函数。

    region=(x0,y0,x1,y1) 归一化; None=全帧。opacity 控制混合强度。
    """
    a = np.asarray(base, dtype="float32") / 255.0
    b = np.asarray(overlay, dtype="float32") / 255.0
    if a.shape != b.shape:
        raise ValueError(f"base/overlay 形状不一致: {a.shape} vs {b.shape}")
    blended = 1.0 - (1.0 - a) * (1.0 - b)
    out = a * (1.0 - opacity) + blended * opacity
    if region is not None:
        H, W = a.shape[:2]
        x0, y0, x1, y1 = region
        rect = (
            max(0, int(round(y0 * H))),
            min(H, int(round(y1 * H))),
            max(0, int(round(x0 * W))),
            min(W, int(round(x1 * W))),
        )
        keep = a.copy()
        keep[rect[0]:rect[1], rect[2]:rect[3]] = out[rect[0]:rect[1], rect[2]:rect[3]]
        out = keep
    return (np.clip(out, 0.0, 1.0) * 255.0).astype("uint8")


def read_video_frames(video_path: str, n_frames: int, size: tuple[int, int], fps: float) -> list[np.ndarray]:
    """读视频并循环/截断到恰好 n_frames (overlay 循环素材对齐底片时长)。"""
    w, h = size
    argv = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", video_path,
        "-vf", f"scale={even(w)}:{even(h)}:flags=lanczos",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ]
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    raw: list[np.ndarray] = []
    frame_bytes = even(w) * even(h) * 3
    while True:
        buf = proc.stdout.read(frame_bytes)
        if len(buf) < frame_bytes:
            break
        raw.append(np.frombuffer(buf, dtype="uint8").reshape(even(h), even(w), 3))
    proc.stdout.close()
    proc.wait()
    if not raw:
        raise RuntimeError(f"overlay 视频读取失败(空): {video_path}")
    return [raw[i % len(raw)] for i in range(int(n_frames))]  # 循环补齐


def load_overlay_manifest(overlays_dir: str | None = None) -> list[dict]:
    """读 overlay 素材库 manifest (条目含 G7 审计字段)。"""
    d = Path(overlays_dir) if overlays_dir else project_root() / OVERLAYS_DIR
    with open(d / OVERLAYS_MANIFEST, "r", encoding="utf-8") as f:
        return json.load(f)


def pick_overlay(shot_id: str, overlays_dir: str | None = None, entries: list[dict] | None = None) -> dict | None:
    """按 shot_id 稳定散列挑选一条已过审 overlay (无库/无可用条目 → None)。"""
    if entries is None:
        try:
            entries = load_overlay_manifest(overlays_dir)
        except FileNotFoundError:
            return None
    ok = [e for e in entries if e.get("g7_audit", {}).get("passed")]
    if not ok:
        return None
    return ok[zlib.crc32(shot_id.encode("utf-8")) % len(ok)]


def resolve_overlay_path(entry: dict, overlays_dir: str | None = None) -> str:
    d = Path(overlays_dir) if overlays_dir else project_root() / OVERLAYS_DIR
    return str(d / entry["file"])


# ---------------- 车道入口 ----------------

def generate(
    card: dict,
    seed: int,
    out_path: str,
    fps: int = LTX_FPS,
    depth_fn=None,
    pipeline=None,  # noqa: ARG001 — 契约占位: 本车道不消耗生成模型 (食物不参与生成)
    overlay_path: str | None = None,
    overlays_dir: str | None = None,
    overlay_entries: list[dict] | None = None,
    overlay_region=DEFAULT_OVERLAY_REGION,
    overlay_opacity: float = 0.85,
    motion: str | None = None,
) -> dict:
    """compositing_2d5 车道生成。确定性渲染 (同卡同资产同 overlay → 同输出)。

    depth_fn 可注入 (CPU 单测); overlay_path 显式指定优先, 缺省按 shot_id 稳定
    挑选已过 G7 审计的库内素材; 库缺失 → 纯底片 (视差运镜) 仍可产出。
    """
    res = (int(card["resolution"][0]), int(card["resolution"][1]))
    n = frames_for_duration(card["duration_sec"], fps)
    motion_eff = motion or (card.get("camera") or {}).get("motion") or DEFAULT_MOTION
    if motion_eff not in PARALLAX_PRESETS:
        motion_eff = DEFAULT_MOTION

    asset = card["first_frame_asset"]
    d_fn = depth_fn or default_depth_fn
    depth = d_fn(asset)

    with timed() as t:
        frames = render_parallax_frames(
            Image.open(asset).convert("RGB"), depth, n, motion=motion_eff,
        )
        overlay_entry = None
        ovl_path = overlay_path
        if ovl_path is None:
            overlay_entry = pick_overlay(card["shot_id"], overlays_dir, overlay_entries)
            if overlay_entry is not None:
                ovl_path = resolve_overlay_path(overlay_entry, overlays_dir)
        overlay_used = None
        if ovl_path and os.path.exists(ovl_path):
            oframes = read_video_frames(ovl_path, n, res, fps)
            frames = [
                screen_blend(f, of, region=overlay_region, opacity=overlay_opacity)
                for f, of in zip(frames, oframes)
            ]
            overlay_used = os.path.basename(ovl_path)
        write_frames_mp4(frames, fps, out_path)

    return {
        "path": out_path,
        "model": COMPOSITING_MODEL_TAG,
        "lane": "compositing_2d5",
        "seed": int(seed),  # 确定性渲染, seed 仅记账 (D-013 同口径)
        "num_frames": n,
        "duration_s": round(n / fps, 4),
        "fps": int(fps),
        "motion": motion_eff,
        "overlay": overlay_used,
        "overlay_region": list(overlay_region),
        "gen_seconds": round(t.seconds, 3),
    }
