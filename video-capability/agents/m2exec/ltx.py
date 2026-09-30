"""LTX-Video 2B 调试车道封装 (迭代期唯一允许; SPECS §3/§5.3)。

硬性校验: 384×512 / ≤2s / steps≤15, fp16, 记录 seed/steps/耗时/显存峰值。

装配 (D-024, 复用 M1 冒烟实测路径 tests/m1_ltx_smoke.py):
- diffusers 0.33.1 `LTXPipeline`(T2V) / `LTXImageToVideoPipeline`(首帧 I2V 条件);
- transformer+vae: models/ltx-video-2b (AI-ModelScope/LTX-Video fp32 布局, 加载转 fp16);
- 文本编码器: FLUX.1-dev T5-XXL fp16 (models/ltx-video-2b/flux_t5);
- scheduler: FlowMatchEulerDiscreteScheduler (dynamic shifting, base 0.95 / max 2.05)。

pipeline 可注入(测试 stub); 真实管线进程级缓存(候选间复用, 避免逐候选 ~17s 重载)。
卡面投影: project_card_for_debug() 把生产卡(480×832/5s)投影为调试卡(D-025),
ingest 时落库, 生成与门禁共用同一卡面。
fp16 黑帧守卫: SPECS §9-②, 命中则 VAE 转 fp32 重试一次。
"""

from __future__ import annotations

import copy
import os
import time

from .common import open_center_resize, reset_vram_counter, timed, vram_peak_mb, write_frames_mp4

LTX_MODEL_ID = "Lightricks/LTX-Video 2B v0.9.x (local: models/ltx-video-2b, D-020)"
LTX_MODEL_DIR = "models/ltx-video-2b"
LTX_RESOLUTION = (384, 512)  # (宽, 高)
LTX_MAX_DURATION_S = 2.0
LTX_MAX_STEPS = 15
LTX_FPS = 16
LTX_GUIDANCE = 3.0  # M1 冒烟实测值

# 进程级管线缓存: key=(model_dir, device) → {"call": callable, "vae": AutoencoderKL, "load_sec": float}
_CACHE: dict = {}


def validate_ltx_params(duration_sec: float, steps: int, resolution: tuple[int, int]) -> None:
    """违反 LTX 调试约束即抛 ValueError(中文)。"""
    w, h = resolution
    if (w, h) != LTX_RESOLUTION:
        raise ValueError(f"LTX 调试车道分辨率强制 {LTX_RESOLUTION}, 收到 {(w, h)}")
    if not (0 < float(duration_sec) <= LTX_MAX_DURATION_S):
        raise ValueError(f"LTX 调试车道时长必须 ≤{LTX_MAX_DURATION_S}s, 收到 {duration_sec}")
    if not (1 <= int(steps) <= LTX_MAX_STEPS):
        raise ValueError(f"LTX 调试车道 steps 必须 1..{LTX_MAX_STEPS}, 收到 {steps}")


def snap_frames_for_duration(duration_sec: float, fps: int = LTX_FPS) -> int:
    """时长 → LTX 帧数(8k+1, LTX v0.9 推荐布局), 夹紧到 ≤LTX_MAX_DURATION_S、下限 9。"""
    n = int(round(float(duration_sec) * int(fps)))
    n = max(9, n)
    n = ((n - 1) + 7) // 8 * 8 + 1  # 8k+1
    while n / float(fps) > LTX_MAX_DURATION_S and n > 9:
        n -= 8
    return n


def project_card_for_debug(card: dict) -> dict:
    """生产镜头卡 → LTX 调试投影卡 (D-025)。

    分辨率强制 384×512, fps=LTX_FPS, 时长吸附到 8k+1 帧布局且 ≤2s;
    fallback.duration_sec 同步投影(Ken Burns 降级与门禁口径一致);
    prompt/negative/n_best/retry_max/acceptance/风险字段原样保留, 冷启动阈值不动。
    投影结果重新过 schema 校验, 保证落库卡面永远合法。
    """
    from ..schema import validate_shotcard

    c = copy.deepcopy(card)
    c["resolution"] = list(LTX_RESOLUTION)
    c["fps"] = LTX_FPS
    n = snap_frames_for_duration(c.get("duration_sec", 1.5), LTX_FPS)
    c["duration_sec"] = round(n / LTX_FPS, 4)
    if isinstance(c.get("fallback"), dict):
        c["fallback"]["duration_sec"] = c["duration_sec"]
    return validate_shotcard(c)


# ---------------- 真实管线装配 (复用 M1 冒烟代码路径) ----------------

def _cache_key(model_dir: str, device: str) -> tuple:
    return (str(model_dir), str(device))


def load_ltx_pipeline(model_dir: str | None = None, device: str = "cuda"):
    """lazy 装配 diffusers LTXPipeline/LTXImageToVideoPipeline (fp16), 进程级缓存。

    返回可注入同款 callable:
        call(prompt, first_frame, width, height, num_frames, steps, seed, fps,
             negative=None, guidance=LTX_GUIDANCE) -> list[frames]
    """
    from ..config import project_root

    d = model_dir or str(project_root() / LTX_MODEL_DIR)
    key = _cache_key(d, device)
    if key in _CACHE:
        return _CACHE[key]["call"]

    import torch
    from diffusers import AutoencoderKLLTXVideo, FlowMatchEulerDiscreteScheduler, LTXPipeline

    try:
        from diffusers import LTXImageToVideoPipeline
    except Exception as e:  # pragma: no cover — diffusers <0.32 无 I2V 管线
        raise RuntimeError(f"diffusers 缺少 LTXImageToVideoPipeline(需 ≥0.32): {e}") from e
    try:
        from diffusers import LTXTransformer3DModel
    except ImportError:  # diffusers 0.33.x 的实际类名
        from diffusers.models.transformers.transformer_ltx import LTXVideoTransformer3DModel as LTXTransformer3DModel
    from transformers import AutoTokenizer, T5EncoderModel

    t0 = time.monotonic()
    dtype = torch.float16
    sched = FlowMatchEulerDiscreteScheduler.from_config({
        "num_train_timesteps": 1000, "base_image_seq_len": 256, "max_image_seq_len": 4096,
        "base_shift": 0.95, "max_shift": 2.05, "use_dynamic_shifting": True,
    })
    te = T5EncoderModel.from_pretrained(os.path.join(d, "flux_t5"), torch_dtype=dtype)
    tok = AutoTokenizer.from_pretrained(os.path.join(d, "tokenizer"))
    transformer = LTXTransformer3DModel.from_pretrained(
        os.path.join(d, "transformer"), torch_dtype=dtype)
    vae = AutoencoderKLLTXVideo.from_pretrained(os.path.join(d, "vae"), torch_dtype=dtype)

    def build(cls):
        return cls(tokenizer=tok, text_encoder=te, transformer=transformer,
                   vae=vae, scheduler=sched.from_config(sched.config))

    pipe_t2v = build(LTXPipeline).to(device)
    pipe_i2v = build(LTXImageToVideoPipeline).to(device)

    def call(prompt, first_frame, width, height, num_frames, steps, seed, fps,
             negative=None, guidance=LTX_GUIDANCE):
        gen = torch.Generator(device).manual_seed(int(seed))
        kw = dict(prompt=prompt,
                  negative_prompt=negative,
                  width=int(width), height=int(height),
                  num_frames=int(num_frames),
                  num_inference_steps=int(steps),
                  guidance_scale=float(guidance),
                  generator=gen)
        if first_frame is not None:
            kw["image"] = first_frame
            return pipe_i2v(**kw).frames[0]
        return pipe_t2v(**kw).frames[0]

    _CACHE[key] = {"call": call, "vae": vae, "load_sec": round(time.monotonic() - t0, 1)}
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
    steps: int = 12,
    fps: int = LTX_FPS,
    pipeline=None,
    negative_extra: list[str] | None = None,
    guidance_delta: float = 0.0,
    device: str = "cuda",
) -> dict:
    """从镜头卡生成 LTX 候选。pipeline 可注入: callable(prompt, first_frame, w, h,
    frames, steps, seed, fps, negative, guidance)->frames。

    negative_extra / guidance_delta 是路由重试的参数钩子 (SPECS §5.5, 基准 guidance=LTX_GUIDANCE)。
    返回 meta: {path, model, seed, steps, num_frames, duration_s, fps, vram_peak_mb,
    gen_seconds, vae_mode, hint}。
    """
    res = (int(card["resolution"][0]), int(card["resolution"][1]))
    num_frames = int(round(float(card["duration_sec"]) * fps))
    duration = num_frames / fps
    validate_ltx_params(duration, steps, res)

    negative = [str(x) for x in (card.get("negative") or [])]
    if negative_extra:
        negative += [n for n in negative_extra if n not in negative]
    guidance = LTX_GUIDANCE + float(guidance_delta)

    first_asset = card.get("first_frame_asset")
    if first_asset and not os.path.exists(first_asset):
        raise FileNotFoundError(f"I2V 首帧资产不存在: {first_asset}")
    first_frame = open_center_resize(first_asset, res[0], res[1]) if first_asset else None

    self_built = pipeline is None
    if pipeline is None:
        from ..config import project_root

        pipeline = load_ltx_pipeline(device=device)
        cache_key = _cache_key(str(project_root() / LTX_MODEL_DIR), device)
    else:
        cache_key = None

    kw = dict(
        prompt=card["prompt_en"],
        first_frame=first_frame,
        width=res[0],
        height=res[1],
        num_frames=num_frames,
        steps=int(steps),
        seed=int(seed),
        fps=int(fps),
        negative=", ".join(negative) if negative else None,
        guidance=float(guidance),
    )

    reset_vram_counter()
    with timed() as t:
        frames = pipeline(**kw)
        vae_mode = "fp16"
        if self_built and _looks_black(frames):
            # SPECS §9-②: fp16 黑帧 → VAE 转 fp32 重试一次
            vae = (_CACHE.get(cache_key) or {}).get("vae")
            try:
                import torch

                if vae is not None and next(vae.parameters()).dtype == torch.float16:
                    vae.to(torch.float32)
                    torch.cuda.empty_cache()
                    frames = pipeline(**kw)
                    vae_mode = "fp32"
            except Exception:  # pragma: no cover — 无 CUDA 环境(CPU 单测)不触发
                pass
    write_frames_mp4(frames, fps, out_path)
    return {
        "path": out_path,
        "model": "ltx_2b",
        "seed": int(seed),
        "steps": int(steps),
        "num_frames": num_frames,
        "duration_s": round(duration, 4),
        "fps": int(fps),
        "vram_peak_mb": vram_peak_mb(),
        "gen_seconds": round(t.seconds, 3),
        "vae_mode": vae_mode,
        "hint": {"negative_extra": negative_extra or [], "guidance_delta": float(guidance_delta)},
    }
