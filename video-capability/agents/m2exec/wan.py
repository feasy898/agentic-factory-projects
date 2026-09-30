"""Wan 产出车道封装 (SPECS §3/§5.3; 实际模型=PAI/Wan2.1-Fun-1.3B-InP, D-019)。

480p(480×832 或 832×480)/81帧@16fps/steps 20-30, fp16;
首帧先经 SDXL img2img 低强度重绘统一风格(denoise 0.2-0.35, 本阶段默认关闭, D-028);
记录 seed/steps/耗时/显存峰值。lazy import + 可注入 stub。

装配 (D-028, 复用 M1 冒烟实测路径 tests/m1_wan_smoke.py):
- DiffSynth-Studio 1.1.9 ModelManager 加载 models/wan-fun-1.3b-inp 四件套
  (umt5 T5 bf16→fp16 / CLIP 图像编码器 / Fun-InP DiT / Wan2.1 VAE);
- WanVideoPipeline.from_model_manager, input_image=首帧(I2V), cfg_scale=5.0±路由钩子;
- 进程级管线缓存; fp16 黑帧守卫(SPECS §9-②)命中则 VAE 转 fp32 重试一次。
"""

from __future__ import annotations

import os
import time

from ..config import project_root
from .common import (
    open_center_resize,
    reset_vram_counter,
    timed,
    vram_peak_mb,
    write_frames_mp4,
)
from .ltx import LTX_FPS

WAN_MODEL_ID = "PAI/Wan2.1-Fun-1.3B-InP (local: models/wan-fun-1.3b-inp, D-019)"
WAN_MODEL_DIR = "models/wan-fun-1.3b-inp"
WAN_MODEL_TAG = "wan_fun_1.3b_inp"  # 候选记账用的模型标签
WAN_RESOLUTIONS = {(480, 832), (832, 480)}  # 竖版主目标 / 横版备选
WAN_MAX_FRAMES = 81
WAN_STEPS_RANGE = (20, 30)
DENOISE_RANGE = (0.2, 0.35)
WAN_CFG_SCALE = 5.0  # M1 冒烟实测值

# 进程级管线缓存: key=(model_dir, device) → {"call","pipe","load_sec"}
_CACHE: dict = {}


def validate_wan_params(steps: int, num_frames: int, resolution: tuple[int, int]) -> None:
    w, h = resolution
    if (w, h) not in WAN_RESOLUTIONS:
        raise ValueError(f"Wan 480p 分辨率只允许 {sorted(WAN_RESOLUTIONS)}, 收到 {(w, h)}")
    lo, hi = WAN_STEPS_RANGE
    if not (lo <= int(steps) <= hi):
        raise ValueError(f"Wan steps 必须 {lo}..{hi}, 收到 {steps}")
    if not (2 <= int(num_frames) <= WAN_MAX_FRAMES):
        raise ValueError(f"Wan 帧数必须 2..{WAN_MAX_FRAMES}, 收到 {num_frames}")


def frames_for_duration(duration_sec: float, fps: int = LTX_FPS) -> int:
    """时长→帧数, 向上取整到 4k+1 (Wan 要求), 上限 81。"""
    n = int(round(float(duration_sec) * fps))
    n = max(n, 2)
    frames = ((n - 1) + 3) // 4 * 4 + 1
    return min(frames, WAN_MAX_FRAMES)


def validate_denoise(strength: float) -> None:
    lo, hi = DENOISE_RANGE
    if not (lo <= float(strength) <= hi):
        raise ValueError(f"首帧风格统一 denoise 必须 {lo}..{hi}, 收到 {strength}")


def stylize_first_frame(
    image_path: str,
    out_path: str,
    prompt: str,
    denoise: float = 0.30,
    device: str = "cuda",
    seed: int = 0,
    pipeline=None,
) -> dict:
    """SDXL img2img 低强度重绘统一风格 (SPECS §5.3)。pipeline 可注入。"""
    validate_denoise(denoise)
    if pipeline is None:
        from ..api.image import local_sdxl_img2img

        return local_sdxl_img2img(image_path, prompt, out_path, strength=denoise, device=device, seed=seed)
    return pipeline(image_path=image_path, prompt=prompt, out_path=out_path, strength=denoise, seed=seed)


# ---------------- 真实管线装配 (复用 M1 冒烟代码路径) ----------------

def _cache_key(model_dir: str, device: str) -> tuple:
    return (str(model_dir), str(device))


def _tensor_to_frames(video) -> list:
    """DiffSynth 返回的视频张量/序列 → list[HxWx3 uint8] (照抄 M1 冒烟 to_pil_frames 布局处理)。"""
    import numpy as np

    try:
        import torch

        if isinstance(video, torch.Tensor):
            t = video.detach().float().clamp(0, 1).cpu()
            if t.dim() == 5:
                t = t[0]
            if t.dim() == 4 and t.shape[-1] == 3:
                pass
            elif t.dim() == 4 and t.shape[0] in (1, 3):
                t = t.permute(1, 2, 3, 0)
            elif t.dim() == 4 and t.shape[1] in (1, 3):
                t = t.permute(0, 2, 3, 1)
            return [(f.numpy() * 255).astype("uint8") for f in t]
    except Exception:
        pass
    out = []
    for f in video:
        arr = np.asarray(f.convert("RGB") if hasattr(f, "convert") else f)
        out.append(arr.astype("uint8"))
    return out


def load_wan_pipeline(model_dir: str | None = None, device: str = "cuda"):
    """lazy 加载 DiffSynth Wan2.1-Fun-1.3B-InP 管线 (fp16, D-019), 进程级缓存。

    返回可注入同款 callable:
        call(prompt, negative, first_frame, width, height, num_frames, steps,
             seed, guidance_delta, fps) -> list[HxWx3 uint8]
    """
    d = model_dir or str(project_root() / WAN_MODEL_DIR)
    key = _cache_key(d, device)
    if key in _CACHE:
        return _CACHE[key]["call"]

    try:
        import torch
        from diffsynth import ModelManager
        from diffsynth.pipelines.wan_video import WanVideoPipeline
    except Exception as e:
        raise RuntimeError(f"DiffSynth 不可用(生成框架主选, 见 SPECS §3): {e}") from e

    t0 = time.monotonic()
    model_manager = ModelManager()
    model_manager.load_models(
        [
            os.path.join(d, "models_t5_umt5-xxl-enc-bf16.pth"),
            os.path.join(d, "models_clip_open-clip-xlm-roberta-large-vit-huge-14.pth"),
            os.path.join(d, "diffusion_pytorch_model.safetensors"),
            os.path.join(d, "Wan2.1_VAE.pth"),
        ],
        torch_dtype=torch.float16,
    )
    pipe = WanVideoPipeline.from_model_manager(model_manager, torch_dtype=torch.float16, device=device)

    def call(prompt, negative=None, first_frame=None, width=480, height=832,
             num_frames=81, steps=25, seed=0, guidance_delta=0.0, fps=LTX_FPS):
        img = open_center_resize(first_frame, int(width), int(height)) if first_frame else None
        # DiffSynth 契约: negative_prompt 是逗号串(M1 冒烟同款); 传 list 会导致 batch 维错配崩溃
        neg = ", ".join(negative) if isinstance(negative, (list, tuple)) else (negative or None)
        video = pipe(
            prompt=prompt,
            negative_prompt=neg,
            input_image=img,
            height=int(height),
            width=int(width),
            num_frames=int(num_frames),
            num_inference_steps=int(steps),
            cfg_scale=max(1.0, WAN_CFG_SCALE + float(guidance_delta)),
            seed=int(seed),
        )
        return _tensor_to_frames(video)

    _CACHE[key] = {"call": call, "pipe": pipe, "load_sec": round(time.monotonic() - t0, 1)}
    return call


def _looks_black(frames) -> bool:
    """粗黑帧/花屏检测(SPECS §9-② 触发器), 任何异常一律返回 False(不误触发)。"""
    try:
        import numpy as np

        sample = list(frames)[:5]
        arrs = []
        for f in sample:
            if hasattr(f, "convert"):
                arrs.append(np.asarray(f.convert("L"), dtype="float32"))
            else:
                a = np.asarray(f, dtype="float32")
                arrs.append(a.mean(axis=2) if a.ndim == 3 else a)
        arr = np.stack(arrs)
        return bool(arr.mean() < 12 or arr.std() < 8)
    except Exception:
        return False


def generate(
    card: dict,
    seed: int,
    out_path: str,
    steps: int = 25,
    fps: int = LTX_FPS,
    num_frames: int | None = None,
    pipeline=None,
    first_frame_pipe=None,
    negative_extra: list[str] | None = None,
    guidance_delta: float = 0.0,
    device: str = "cuda",
) -> dict:
    """从镜头卡生成 Wan 候选。pipeline/first_frame_pipe 均可注入。

    negative_extra / guidance_delta 是路由重试的参数钩子 (SPECS §5.5)。
    first_frame_pipe=首帧 img2img 风格统一(SPECS §5.3); None=关闭(D-028 本阶段默认关闭)。
    返回 meta: {path, model, seed, steps, duration_s, fps, vram_peak_mb, gen_seconds,
    vae_mode, hint}。
    """
    res = (int(card["resolution"][0]), int(card["resolution"][1]))
    nf = num_frames if num_frames is not None else frames_for_duration(card["duration_sec"], fps)
    validate_wan_params(steps, nf, res)

    first_frame = card.get("first_frame_asset")
    stylized = None
    if first_frame_pipe is not None and first_frame:
        stylized = first_frame_pipe(
            image_path=first_frame, out_path=f"{out_path}.first.png",
            prompt=card["prompt_en"], strength=0.3, seed=seed,
        )

    self_built = pipeline is None
    if pipeline is None:
        pipeline = load_wan_pipeline(device=device)

    negative = list(card.get("negative", []))
    if negative_extra:
        negative += [n for n in negative_extra if n not in negative]

    ff = (stylized or {}).get("path", first_frame) if (stylized or first_frame) else None
    kw = dict(
        prompt=card["prompt_en"],
        negative=negative,
        first_frame=ff,
        width=res[0],
        height=res[1],
        num_frames=nf,
        steps=int(steps),
        seed=int(seed),
        guidance_delta=float(guidance_delta),
        fps=int(fps),
    )

    reset_vram_counter()
    with timed() as t:
        frames = pipeline(**kw)
        vae_mode = "fp16"
        if self_built and _looks_black(frames):
            # SPECS §9-②: fp16 黑帧 → VAE 转 fp32 重试一次
            entry = _CACHE.get(_cache_key(str(project_root() / WAN_MODEL_DIR), device))
            vae_pipe = (entry or {}).get("pipe")
            try:
                import torch

                if vae_pipe is not None and next(vae_pipe.vae.parameters()).dtype == torch.float16:
                    vae_pipe.vae.to(torch.float32)
                    torch.cuda.empty_cache()
                    frames = pipeline(**kw)
                    vae_mode = "fp32"
            except Exception:  # pragma: no cover — 无 CUDA 环境(CPU 单测)不触发
                pass
    write_frames_mp4(frames, fps, out_path)
    return {
        "path": out_path,
        "model": WAN_MODEL_TAG,
        "seed": int(seed),
        "steps": int(steps),
        "num_frames": nf,
        "duration_s": round(nf / fps, 4),
        "fps": int(fps),
        "vram_peak_mb": vram_peak_mb(),
        "gen_seconds": round(t.seconds, 3),
        "vae_mode": vae_mode,
        "hint": {"negative_extra": negative_extra or [], "guidance_delta": float(guidance_delta)},
    }
