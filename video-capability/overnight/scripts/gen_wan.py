#!/usr/bin/env python3
# gen_wan.py — Wan2.1-T2V-1.3B fp16 冒烟/生成（V100 无 bf16, 强制 float16）
# 记录: 耗时 / 显存峰值 / 元数据 JSON
import argparse, json, os, time

import numpy as np
import torch

p = argparse.ArgumentParser()
p.add_argument("--prompt", required=True)
p.add_argument("--negative", default="色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走")
p.add_argument("--seed", type=int, default=42)
p.add_argument("--out", default="/data/night/clips/wan_smoke.mp4")
p.add_argument("--num-frames", type=int, default=81)  # 4k+1; 81帧@16fps≈5s, 49帧≈3s
p.add_argument("--steps", type=int, default=50)
p.add_argument("--height", type=int, default=480)
p.add_argument("--width", type=int, default=832)
p.add_argument("--model", default="/data/night/models/Wan2.1-T2V-1.3B-Diffusers")
p.add_argument("--fps", type=int, default=16)
p.add_argument("--guidance", type=float, default=5.0)
args = p.parse_args()

os.makedirs(os.path.dirname(args.out), exist_ok=True)
meta = {"model": "Wan-AI/Wan2.1-T2V-1.3B-Diffusers", "backend": "diffusers-WanPipeline",
        "prompt": args.prompt, "negative_prompt": args.negative[:80] + "...", "seed": args.seed,
        "num_frames": args.num_frames, "steps": args.steps, "height": args.height,
        "width": args.width, "guidance_scale": args.guidance, "fps": args.fps,
        "dtype": "float16", "gpu": torch.cuda.get_device_name(0)}

t0 = time.time()
from diffusers import WanPipeline  # noqa: E402
pipe = WanPipeline.from_pretrained(args.model, torch_dtype=torch.float16)
load_s = time.time() - t0
pipe.to("cuda")
pipe.vae.enable_tiling()
torch.cuda.reset_peak_memory_stats()

gen = torch.Generator(device="cuda").manual_seed(args.seed)
t1 = time.time()
video = pipe(prompt=args.prompt, negative_prompt=args.negative,
             num_frames=args.num_frames, height=args.height, width=args.width,
             num_inference_steps=args.steps, guidance_scale=args.guidance,
             generator=gen).frames[0]
gen_s = time.time() - t1
from diffusers.utils import export_to_video
export_to_video(video, args.out, fps=args.fps)

meta.update({"load_s": round(load_s, 1), "gen_s": round(gen_s, 1),
             "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2),
             "output": args.out, "status": "ok",
             "frames_produced": len(video),
             "first_frame_mean": float(np.asarray(video[0], dtype="float32").mean())})
mp = args.out + ".meta.json"
with open(mp, "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)
print("WAN_SMOKE_OK", json.dumps({k: meta[k] for k in ("gen_s", "peak_vram_gb", "output")}, ensure_ascii=False))
print("META", mp)
