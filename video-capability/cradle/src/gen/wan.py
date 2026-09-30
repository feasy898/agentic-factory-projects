"""Wan2.1-I2V-1.3B 产出车道封装 (SPECS §3/§5.3)。

480p(480×832 或 832×480)/81帧@16fps/steps 20-30, fp16;
首帧先经 SDXL img2img 低强度重绘(denoise 0.2-0.35)统一风格;
记录 seed/steps/耗时/显存峰值。lazy import + 可注入 stub。
"""

from __future__ import annotations

from .common import reset_vram_counter, timed, vram_peak_mb, write_frames_mp4
from .ltx import LTX_FPS

WAN_MODEL_ID = "Wan-AI/Wan2.1-I2V-1.3B-480P"
WAN_RESOLUTIONS = {(480, 832), (832, 480)}  # 竖版主目标 / 横版备选
WAN_MAX_FRAMES = 81
WAN_STEPS_RANGE = (20, 30)
DENOISE_RANGE = (0.2, 0.35)


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


def load_wan_pipeline(model_id: str = WAN_MODEL_ID, device: str = "cuda"):
    """lazy 加载 DiffSynth Wan2.1-I2V-1.3B 管线 (fp16)。仅由真实生成调用。"""
    try:
        from diffsynth import ModelManager  # noqa: F401
    except Exception as e:  # pragma: no cover
        raise RuntimeError(f"DiffSynth 不可用(生成框架主选, 见 SPECS §3): {e}") from e
    raise NotImplementedError(
        "Wan 管线装配由 M1-ENV 的 DiffSynth 实测接口补齐; M2 只锁定参数校验/记账/落盘契约。"
    )


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
    返回 meta: {path, seed, steps, duration_s, fps, vram_peak_mb, gen_seconds, model, hint}。
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

    if pipeline is None:
        pipeline = load_wan_pipeline(device=device)

    negative = list(card.get("negative", []))
    if negative_extra:
        negative += [n for n in negative_extra if n not in negative]

    reset_vram_counter()
    with timed() as t:
        frames = pipeline(
            prompt=card["prompt_en"],
            negative=negative,
            first_frame=(stylized or {}).get("path", first_frame) if (stylized or first_frame) else None,
            width=res[0],
            height=res[1],
            num_frames=nf,
            steps=int(steps),
            seed=int(seed),
            guidance_delta=float(guidance_delta),
            fps=fps,
        )
    write_frames_mp4(frames, fps, out_path)
    return {
        "path": out_path,
        "model": "wan_i2v_13b",
        "seed": int(seed),
        "steps": int(steps),
        "num_frames": nf,
        "duration_s": round(nf / fps, 4),
        "fps": fps,
        "vram_peak_mb": vram_peak_mb(),
        "gen_seconds": round(t.seconds, 3),
        "hint": {"negative_extra": negative_extra or [], "guidance_delta": guidance_delta},
    }
