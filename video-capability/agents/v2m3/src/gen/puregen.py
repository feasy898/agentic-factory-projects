"""pure_gen_short 车道 (SPECS_V2 §5.2) — 环境氛围专用纯生成, 时长压缩到 1-2s。

适用范围: 雨窗/夜景街/蒸汽弥漫空镜 (assets/scenes/)。食物镜头由 schema 红线
(schema._validate_lane_rules) 硬性拒绝进入本车道。

降漂移三件套:
1. 时长 1-2s (17-33 帧 @16fps; 漂移随时间累积, 5s 是它最肥的土壤);
2. 固定机位 prompt 模板 ("fixed camera, locked tripod, only steam/light moves");
3. negative 扩充反形变词表 (melting/liquid/dissolving/fluid/morphing/splitting/
   floating debris)。

几何锁定路径 (侦察结论 D-060):
- a) 默认: Fun-InP 短 I2V + 原生 end_image 首尾帧锚定 (末帧=首帧资产, 锁定机位下
   首尾同帧是最强几何约束), 复用 wan.py 缓存管线, 零新模型;
- b) 增强可选: 分段法 — 把时长切成 ≤1s 的短段, 每段以上一段末帧为首帧锚继续
   I2V (segmented_generate, 可注入 segment_fn, 本轮不用于生产, 留作 path-a
   失效时的备份)。
"""

from __future__ import annotations

from ..schema import PUREGEN_DURATION_RANGE
from .common import concat_segments, extract_last_frame
from .wan import DENOISE_RANGE  # noqa: F401 — 重导出供校验/文档引用
from .wan import LTX_FPS, WAN_MODEL_TAG, frames_for_duration, generate as wan_generate

PUREGEN_MODEL_TAG = "pure_gen_short"
PUREGEN_MAX_FRAMES = 33  # 2s@16fps 吸附 4k+1 布局
FIXED_CAMERA_PROMPT = (
    "fixed camera, locked tripod, static composition, only steam and light moves, "
    "no camera movement, no zoom"
)
# 反形变 negative 扩充 (SPECS_V2 §5.2 指定项 + 同族补充)
PUREGEN_NEGATIVE_EXTRA = [
    "melting",
    "liquid",
    "dissolving",
    "fluid",
    "morphing",
    "splitting",
    "floating debris",
    "warping",
    "object movement",
]


def build_puregen_prompt(prompt_en: str) -> str:
    """环境空镜 prompt 模板: 固定机位约束写进正向 prompt。纯函数。"""
    base = (prompt_en or "").strip().rstrip(",")
    return f"{base}, {FIXED_CAMERA_PROMPT}"


def validate_puregen_duration(duration_sec: float) -> None:
    lo, hi = PUREGEN_DURATION_RANGE
    if not (lo <= float(duration_sec) <= hi):
        raise ValueError(
            f"pure_gen_short 时长必须 {lo}-{hi}s (SPECS_V2 §5.2), 收到 {duration_sec}"
        )


def frames_for_puregen(duration_sec: float, fps: int = LTX_FPS) -> int:
    """1-2s → 17-33 帧 (4k+1 布局, 上限 33)。纯函数。"""
    validate_puregen_duration(duration_sec)
    return min(frames_for_duration(duration_sec, fps), PUREGEN_MAX_FRAMES)


def generate(
    card: dict,
    seed: int,
    out_path: str,
    steps: int = 20,
    fps: int = LTX_FPS,
    pipeline=None,
    negative_extra: list[str] | None = None,
    guidance_delta: float = 0.0,
    device: str = "cuda",
    end_image: str | None = None,
) -> dict:
    """pure_gen_short 车道生成 (路径 a: Fun-InP 短 I2V + end_image 首尾锚定)。

    pipeline 可注入 (CPU 单测); end_image 缺省用首帧资产 (锁定机位 → 首尾同帧)。
    """
    validate_puregen_duration(card["duration_sec"])
    nf = frames_for_puregen(card["duration_sec"], fps)
    neg = list(card.get("negative", [])) + [
        n for n in PUREGEN_NEGATIVE_EXTRA if n not in card.get("negative", [])
    ]
    if negative_extra:
        neg += [n for n in negative_extra if n not in neg]
    gen_card = dict(card, prompt_en=build_puregen_prompt(card["prompt_en"]), negative=neg)
    end_img = end_image or card.get("first_frame_asset")
    meta = wan_generate(
        gen_card, seed, out_path,
        steps=int(steps),
        fps=fps,
        num_frames=nf,
        pipeline=pipeline,
        negative_extra=None,  # 已并入 gen_card.negative, 避免重复
        guidance_delta=float(guidance_delta),
        device=device,
        end_image=end_img,
    )
    meta["model"] = PUREGEN_MODEL_TAG
    meta["lane"] = "pure_gen_short"
    meta["anchor"] = {"mode": "end_image", "end_image": end_img}
    return meta


def segmented_generate(
    card: dict,
    seed: int,
    out_path: str,
    segment_fn=None,
    fps: int = LTX_FPS,
    segment_sec: float = 1.0,
) -> dict:
    """路径 b (增强可选): 分段法 — 每段 ≤1s 短 I2V, 以上一段末帧为下一段首帧锚。

    segment_fn(start_frame_path, out_path, num_frames, seed) -> meta(dict, 含 path);
    缺省用 wan 管线实现。本轮生产不使用 (path-a 原生锚定优先, D-060), 保留作备份。
    """
    import os
    import tempfile

    validate_puregen_duration(card["duration_sec"])
    total_n = frames_for_puregen(card["duration_sec"], fps)
    seg_len = min(int(round(segment_sec * fps)) // 4 * 4 + 1, total_n)

    if segment_fn is None:
        from .wan import load_wan_pipeline

        pipe_call = load_wan_pipeline(device="cuda")

        def segment_fn(start_frame_path, seg_out, n_frames, seg_seed):  # noqa: F811
            frames = pipe_call(
                prompt=build_puregen_prompt(card["prompt_en"]),
                negative=list(card.get("negative", [])) + PUREGEN_NEGATIVE_EXTRA,
                first_frame=start_frame_path,
                width=int(card["resolution"][0]),
                height=int(card["resolution"][1]),
                num_frames=n_frames,
                steps=20,
                seed=int(seg_seed),
            )
            from .common import write_frames_mp4

            write_frames_mp4(frames, fps, seg_out)
            return {"path": seg_out}

    seg_paths: list[str] = []
    produced = 0
    seg_seed = int(seed)
    with tempfile.TemporaryDirectory(prefix="puregen_seg_") as td:
        first = card["first_frame_asset"]
        while produced < total_n:
            n = min(seg_len, total_n - produced)
            n = n // 4 * 4 + 1 if n >= 5 else n
            seg_out = os.path.join(td, f"seg_{len(seg_paths)}.mp4")
            segment_fn(first, seg_out, n, seg_seed)
            seg_paths.append(seg_out)
            produced += n
            seg_seed += 1
            if produced < total_n:
                # 下一段首帧锚 = 本段末帧 (抽帧落盘)
                first = os.path.join(td, f"anchor_{len(seg_paths)}.png")
                extract_last_frame(seg_paths[-1], first)
        concat_segments(seg_paths, out_path)  # 必须在临时目录存续期内执行
    return {
        "path": out_path,
        "model": PUREGEN_MODEL_TAG,
        "lane": "pure_gen_short",
        "anchor": {"mode": "segmented", "segments": len(seg_paths)},
    }
