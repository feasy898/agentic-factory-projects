# M1 Smoke A: LTX-Video 2B via diffusers on V100 (fp16)
# 384x512 portrait, 33 frames @24fps (~1.4s), 15 steps, seed 42
import os, json, time, traceback

import numpy as np
import torch

OUT_DIR = "/root/cradle/reports/milestones"
MODEL_DIR = "/root/cradle/models/ltx-video-2b"
MP4 = os.path.join(OUT_DIR, "m1_ltx_smoke.mp4")
PNG = os.path.join(OUT_DIR, "m1_ltx_smoke.png")
JSN = os.path.join(OUT_DIR, "m1_ltx_smoke.json")

RESULT = {"script": "m1_ltx_smoke", "params": {
    "model": "Lightricks LTX-Video 2B v0.9.x diffusers layout (AI-ModelScope/LTX-Video transformer+vae fp32, cast fp16 at load)",
    "text_encoder": "google/t5-v1_1-xxl fp16 from AI-ModelScope/FLUX.1-dev text_encoder_2",
    "height": 512, "width": 384, "num_frames": 33, "fps": 24, "steps": 15,
    "guidance_scale": 3.0, "seed": 42, "dtype": "float16",
}, "attempts": []}

def frame_stats(frames):
    arr = np.stack([np.asarray(f.convert("L"), dtype=np.float32) for f in frames])
    return {"n_frames": int(arr.shape[0]), "gray_mean": round(float(arr.mean()), 2),
            "gray_std": round(float(arr.std()), 2), "gray_min": round(float(arr.min()), 2),
            "gray_max": round(float(arr.max()), 2)}

def looks_black(stats):
    return stats["gray_mean"] < 12 or stats["gray_std"] < 8

def save_video(frames, path, fps=24):
    import imageio.v2 as imageio
    w = imageio.get_writer(path, fps=fps, codec="libx264", quality=8,
                           macro_block_size=None, ffmpeg_params=["-pix_fmt", "yuv420p"])
    for f in frames:
        w.append_data(np.asarray(f.convert("RGB")))
    w.close()

def main():
    import diffusers
    from diffusers import LTXPipeline, AutoencoderKLLTXVideo
    try:
        from diffusers import LTXTransformer3DModel
    except ImportError:
        from diffusers.models.transformers.transformer_ltx import LTXVideoTransformer3DModel as LTXTransformer3DModel
    from transformers import T5EncoderModel, AutoTokenizer
    import imageio.v2 as imageio

    sched_cls = None
    for name in dir(diffusers):
        if "LTX" in name and "Scheduler" in name:
            sched_cls = getattr(diffusers, name)
            break
    from diffusers import FlowMatchEulerDiscreteScheduler
    # LTX-Video 0.9.x uses FlowMatchEulerDiscreteScheduler with dynamic shifting
    # (repo scheduler_config: base_shift 0.95 / max_shift 2.05 / seq len 256-4096)
    sched = FlowMatchEulerDiscreteScheduler.from_config({
        "num_train_timesteps": 1000, "base_image_seq_len": 256, "max_image_seq_len": 4096,
        "base_shift": 0.95, "max_shift": 2.05, "use_dynamic_shifting": True,
    })
    RESULT["scheduler_class"] = "FlowMatchEulerDiscreteScheduler(dynamic shifting; LTX-specific classes present: %s)" % (sched_cls or "none in diffusers 0.33")

    t0 = time.time()
    dtype = torch.float16
    te = T5EncoderModel.from_pretrained(f"{MODEL_DIR}/flux_t5", torch_dtype=dtype)
    tok = AutoTokenizer.from_pretrained(f"{MODEL_DIR}/tokenizer")
    transformer = LTXTransformer3DModel.from_pretrained(
        f"{MODEL_DIR}/transformer", torch_dtype=dtype)
    vae = AutoencoderKLLTXVideo.from_pretrained(
        f"{MODEL_DIR}/vae", torch_dtype=dtype)
    pipe = LTXPipeline(tokenizer=tok, text_encoder=te, transformer=transformer,
                       vae=vae, scheduler=sched)
    pipe.to("cuda")
    RESULT["load_sec"] = round(time.time() - t0, 1)
    RESULT["attempts"].append("pipeline loaded fp16")

    prompt = ("close-up of fresh beef tripe dipped into boiling spicy red hotpot broth, "
              "glistening oil bubbles, rising steam, warm restaurant lighting, shallow depth of field, "
              "appetizing food commercial, photorealistic")
    negative = ("human face, hands, fingers, text, watermark, logo, deformed, extra limbs, "
                "cartoon, illustration, blurry, low quality")
    seed, steps, g = 42, 15, 3.0

    def generate():
        gen = torch.Generator("cuda").manual_seed(seed)
        t1 = time.time()
        out = pipe(prompt=prompt, negative_prompt=negative, width=384, height=512,
                   num_frames=33, num_inference_steps=steps, guidance_scale=g,
                   generator=gen)
        torch.cuda.synchronize()
        return out.frames[0], time.time() - t1

    # attempt 1: full fp16
    vae_mode = "fp16"
    frames, dt = generate()
    stats = frame_stats(frames)
    RESULT["attempts"].append({"vae": vae_mode, "gen_sec": round(dt, 1), "stats": stats})
    if looks_black(stats):
        # attempt 2: VAE in fp32 (SPECS section 9 playbook)
        RESULT["attempts"].append("fp16 output black/broken -> VAE to fp32, retry (D-007 if used)")
        torch.cuda.empty_cache()
        pipe.vae.to(torch.float32)
        vae_mode = "fp32"
        frames, dt = generate()
        stats = frame_stats(frames)
        RESULT["attempts"].append({"vae": vae_mode, "gen_sec": round(dt, 1), "stats": stats})
        if looks_black(stats):
            raise RuntimeError(f"video still black/broken after VAE fp32: {stats}")

    save_video(frames, MP4, fps=24)
    imageio.imwrite(PNG, np.asarray(frames[0].convert("RGB")))

    RESULT.update({"status": "PASS", "vae_mode": vae_mode, "gen_sec": round(dt, 1),
                   "peak_vram_MiB": round(torch.cuda.max_memory_allocated() / 1024**2, 1),
                   "video": MP4, "first_frame": PNG, "frame_stats": stats})
    with open(JSN, "w") as f:
        json.dump(RESULT, f, indent=2, ensure_ascii=False)
    print("LTX SMOKE PASS", json.dumps({k: RESULT[k] for k in ("gen_sec", "peak_vram_MiB", "vae_mode")}))

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        traceback.print_exc()
        RESULT["status"] = "FAIL"
        RESULT["error"] = f"{type(e).__name__}: {e}"
        RESULT["traceback"] = traceback.format_exc()
        with open(JSN, "w") as f:
            json.dump(RESULT, f, indent=2, ensure_ascii=False)
        raise SystemExit(1)
