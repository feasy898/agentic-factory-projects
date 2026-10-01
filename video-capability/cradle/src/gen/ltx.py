"""LTX-Video 2B 调试车道封装 (迭代期唯一允许; SPECS §3/§5.3)。

硬性校验: 384×512 / ≤2s / steps≤15, fp16, 记录 seed/steps/耗时/显存峰值。
lazy import diffsynth; pipeline 可注入(测试 stub), 本阶段不真正跑 GPU。
"""

from __future__ import annotations

from .common import timed, reset_vram_counter, vram_peak_mb, write_frames_mp4

LTX_MODEL_ID = "Lightricks/LTX-Video"
LTX_RESOLUTION = (384, 512)  # (宽, 高)
LTX_MAX_DURATION_S = 2.0
LTX_MAX_STEPS = 15
LTX_FPS = 16


def validate_ltx_params(duration_sec: float, steps: int, resolution: tuple[int, int]) -> None:
    """违反 LTX 调试约束即抛 ValueError(中文)。"""
    w, h = resolution
    if (w, h) != LTX_RESOLUTION:
        raise ValueError(f"LTX 调试车道分辨率强制 {LTX_RESOLUTION}, 收到 {(w, h)}")
    if not (0 < float(duration_sec) <= LTX_MAX_DURATION_S):
        raise ValueError(f"LTX 调试车道时长必须 ≤{LTX_MAX_DURATION_S}s, 收到 {duration_sec}")
    if not (1 <= int(steps) <= LTX_MAX_STEPS):
        raise ValueError(f"LTX 调试车道 steps 必须 1..{LTX_MAX_STEPS}, 收到 {steps}")


def load_ltx_pipeline(model_id: str = LTX_MODEL_ID, device: str = "cuda"):
    """lazy 加载 DiffSynth LTX 管线 (fp16, Volta 纪律)。仅由真实生成调用。"""
    try:
        from diffsynth import ModelManager  # noqa: F401 — DiffSynth-Studio 顶层接口以实测为准
    except Exception as e:  # pragma: no cover
        raise RuntimeError(f"DiffSynth 不可用(生成框架主选, 见 SPECS §3): {e}") from e
    raise NotImplementedError(
        "LTX 管线装配由 M1-ENV 的 DiffSynth 实测接口补齐; M2 只锁定参数校验/记账/落盘契约。"
    )


def generate(
    card: dict,
    seed: int,
    out_path: str,
    steps: int = 12,
    fps: int = LTX_FPS,
    pipeline=None,
    device: str = "cuda",
) -> dict:
    """从镜头卡生成 LTX 候选。pipeline 可注入: callable(prompt, first_frame, w, h, frames, steps, seed, fps)->frames。

    返回 meta: {path, seed, steps, duration_s, fps, vram_peak_mb, gen_seconds, model}。
    """
    num_frames = int(round(float(card["duration_sec"]) * fps))
    duration = num_frames / fps
    validate_ltx_params(duration, steps, (int(card["resolution"][0]), int(card["resolution"][1])))

    if pipeline is None:
        pipeline = load_ltx_pipeline(device=device)

    reset_vram_counter()
    with timed() as t:
        frames = pipeline(
            prompt=card["prompt_en"],
            first_frame=card.get("first_frame_asset"),
            width=int(card["resolution"][0]),
            height=int(card["resolution"][1]),
            num_frames=num_frames,
            steps=int(steps),
            seed=int(seed),
            fps=fps,
        )
    write_frames_mp4(frames, fps, out_path)
    return {
        "path": out_path,
        "model": "ltx_2b",
        "seed": int(seed),
        "steps": int(steps),
        "num_frames": num_frames,
        "duration_s": round(duration, 4),
        "fps": fps,
        "vram_peak_mb": vram_peak_mb(),
        "gen_seconds": round(t.seconds, 3),
    }
