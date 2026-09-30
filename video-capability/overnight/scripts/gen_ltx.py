#!/usr/bin/env python3
# gen_ltx.py — Lightricks/LTX-Video 2B 冒烟/生成（V100 无 bf16 → float16；黑帧/NaN 自动检测，VAE fp32 降级重试）
import argparse, json, os, time

import numpy as np
import torch

p = argparse.ArgumentParser()
p.add_argument("--prompt", required=True)
p.add_argument("--negative", default="worst quality, inconsistent motion, blurry, jittery, distorted")
p.add_argument("--seed", type=int, default=42)
p.add_argument("--out", default="/data/night/clips/ltx_smoke.mp4")
p.add_argument("--num-frames", type=int, default=49)  # 8k+1; 49@24fps≈2s, 121@24fps≈5s
p.add_argument("--steps", type=int, default=50)
p.add_argument("--height", type=int, default=480)
p.add_argument("--width", type=int, default=704)
p.add_argument("--model", default="/data/night/models/LTX-Video")
p.add_argument("--fps", type=int, default=24)
p.add_argument("--guidance", type=float, default=3.0)
p.add_argument("--decode-timestep", type=float, default=0.05)
args = p.parse_args()

os.makedirs(os.path.dirname(args.out), exist_ok=True)
meta = {"model": "Lightricks/LTX-Video (2B)", "backend": "diffusers-LTXPipeline",
        "prompt": args.prompt, "seed": args.seed, "num_frames": args.num_frames,
        "steps": args.steps, "height": args.height, "width": args.width,
        "guidance_scale": args.guidance, "decode_timestep": args.decode_timestep,
        "fps": args.fps, "gpu": torch.cuda.get_device_name(0)}

t0 = time.time()
from diffusers import LTXPipeline, AutoencoderKLLTXVideo  # noqa: E402
load_s = time.time() - t0


def black_or_nan(frames):
    t = torch.from_numpy(np.stack([np.asarray(f, dtype="float32") for f in frames]))
    return bool(torch.isnan(t).any() or t.abs().mean() < 1e-3)


def run(vae_fp32=False):
    kwargs = {"torch_dtype": torch.float16}
    if vae_fp32:
        kwargs["vae"] = AutoencoderKLLTXVideo.from_pretrained(
            args.model, subfolder="vae", torch_dtype=torch.float32)
    pipe = LTXPipeline.from_pretrained(args.model, **kwargs)
    pipe.to("cuda")
    pipe.vae.enable_tiling()
    torch.cuda.reset_peak_memory_stats()
    gen = torch.Generator(device="cuda").manual_seed(args.seed)
    t = time.time()
    out = pipe(prompt=args.prompt, negative_prompt=args.negative,
               num_frames=args.num_frames, height=args.height, width=args.width,
               num_inference_steps=args.steps, guidance_scale=args.guidance,
               decode_timestep=args.decode_timestep, decode_noise_scale=0.025,
               generator=gen).frames[0]
    gen_s = time.time() - t
    peak = round(torch.cuda.max_memory_allocated() / 2**30, 2)
    bad = black_or_nan(out)
    del pipe
    torch.cuda.empty_cache()
    return out, gen_s, peak, bad


status = "ok"
try:
    result, gen_s, peak, bad = run(vae_fp32=False)
    if bad:
        raise RuntimeError("fp16 输出黑帧/NaN")
except Exception as e:
    meta["fp16_error"] = repr(e)[:500]
    print("LTX_FP16_FALLBACK", repr(e)[:300])
    try:
        result, gen_s, peak, bad = run(vae_fp32=True)
        status = "ok_with_vae_fp32_fallback"
    except Exception as e2:
        meta["fallback_error"] = repr(e2)[:500]
        meta["status"] = "failed"
        with open(args.out + ".meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print("LTX_SMOKE_FAILED")
        raise SystemExit(1)

from diffusers.utils import export_to_video
export_to_video(result, args.out, fps=args.fps)
meta.update({"dtype": "fp16_all" if status == "ok" else "fp16_dit_fp32_vae",
             "load_s": round(load_s, 1), "gen_s": round(gen_s, 1), "peak_vram_gb": peak,
             "output": args.out, "status": status, "frames_produced": len(result),
             "first_frame_mean": float(np.asarray(result[0], dtype="float32").mean())})
with open(args.out + ".meta.json", "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)
print("LTX_SMOKE_OK", json.dumps({k: meta[k] for k in ("gen_s", "peak_vram_gb", "output", "status")}, ensure_ascii=False))
print("META", args.out + ".meta.json")
