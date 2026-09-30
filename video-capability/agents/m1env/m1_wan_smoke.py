# M1 Smoke B step 2: Wan2.1-Fun-1.3B-InP I2V via DiffSynth-Studio 1.1.9 on V100 (fp16)
# first frame = SDXL product image, 480x832 portrait, 81 frames @16fps, steps 20, seed 42
import os, json, time, traceback

import numpy as np
import torch

OUT_DIR = "/root/cradle/reports/milestones"
MODEL_DIR = "/root/cradle/models/wan-fun-1.3b-inp"
FIRST_FRAME = os.path.join(OUT_DIR, "m1_wan_first_frame.png")
MP4 = os.path.join(OUT_DIR, "m1_wan_smoke.mp4")
PNG = os.path.join(OUT_DIR, "m1_wan_smoke.png")
JSN = os.path.join(OUT_DIR, "m1_wan_smoke.json")

RESULT = {"script": "m1_wan_smoke", "params": {
    "model": "PAI/Wan2.1-Fun-1.3B-InP (Wan2.1 lineage I2V; SPECS primary Wan2.1-I2V-1.3B does not exist, see D-006)",
    "framework": "DiffSynth-Studio 1.1.9 (ModelManager API)",
    "height": 832, "width": 480, "num_frames": 81, "fps": 16, "steps": 20,
    "cfg_scale": 5.0, "sigma_shift": 5.0, "seed": 42, "dtype": "float16",
    "first_frame": FIRST_FRAME,
}, "attempts": []}

def frame_stats(frames):
    arr = np.stack([np.asarray(f.convert("L"), dtype=np.float32) for f in frames])
    return {"n_frames": int(arr.shape[0]), "gray_mean": round(float(arr.mean()), 2),
            "gray_std": round(float(arr.std()), 2), "gray_min": round(float(arr.min()), 2),
            "gray_max": round(float(arr.max()), 2)}

def looks_black(stats):
    return stats["gray_mean"] < 12 or stats["gray_std"] < 8

def to_pil_frames(video):
    from PIL import Image
    if isinstance(video, torch.Tensor):
        t = video.detach().float().clamp(0, 1).cpu()
        if t.dim() == 5:
            t = t[0]
        if t.dim() == 4 and t.shape[-1] in (3,):
            pass
        elif t.dim() == 4 and t.shape[0] in (1, 3):
            t = t.permute(1, 2, 3, 0)
        elif t.dim() == 4 and t.shape[1] in (1, 3):
            t = t.permute(0, 2, 3, 1)
        return [Image.fromarray((f.numpy() * 255).astype(np.uint8)) for f in t]
    return list(video)

def save_video(frames, path, fps=16):
    import imageio.v2 as imageio
    w = imageio.get_writer(path, fps=fps, codec="libx264", quality=8,
                           macro_block_size=None, ffmpeg_params=["-pix_fmt", "yuv420p"])
    for f in frames:
        w.append_data(np.asarray(f.convert("RGB")))
    w.close()

def main():
    from PIL import Image
    from diffsynth import ModelManager
    from diffsynth.pipelines.wan_video import WanVideoPipeline
    import imageio.v2 as imageio

    t0 = time.time()
    model_manager = ModelManager()
    model_manager.load_models(
        [
            f"{MODEL_DIR}/models_t5_umt5-xxl-enc-bf16.pth",
            f"{MODEL_DIR}/models_clip_open-clip-xlm-roberta-large-vit-huge-14.pth",
            f"{MODEL_DIR}/diffusion_pytorch_model.safetensors",
            f"{MODEL_DIR}/Wan2.1_VAE.pth",
        ],
        torch_dtype=torch.float16,
    )
    pipe = WanVideoPipeline.from_model_manager(model_manager, torch_dtype=torch.float16, device="cuda")
    RESULT["load_sec"] = round(time.time() - t0, 1)
    RESULT["attempts"].append("pipeline loaded fp16 (T5 stored bf16 -> cast fp16)")

    first = Image.open(FIRST_FRAME).convert("RGB")
    prompt = ("fresh beef tripe (maodu) close-up in boiling spicy hotpot broth, oil bubbles simmering, "
              "steam rising, warm restaurant light, slow gentle camera push-in, appetizing food commercial")
    negative = ("human face, hands, fingers, people, text, watermark, logo, "
                "deformed, morphing, extra limbs, flicker, cartoon, low quality")
    seed, steps, cfg = 42, 20, 5.0

    def generate():
        t1 = time.time()
        video = pipe(prompt=prompt, negative_prompt=negative, input_image=first,
                     height=832, width=480, num_frames=81,
                     num_inference_steps=steps, cfg_scale=cfg, seed=seed)
        torch.cuda.synchronize()
        return to_pil_frames(video), time.time() - t1

    vae_mode = "fp16"
    frames, dt = generate()
    stats = frame_stats(frames)
    RESULT["attempts"].append({"vae": vae_mode, "gen_sec": round(dt, 1), "stats": stats})

    if looks_black(stats):
        RESULT["attempts"].append("fp16 output black/broken -> VAE to fp32, retry")
        torch.cuda.empty_cache()
        pipe.vae.to(torch.float32)
        vae_mode = "fp32"
        frames, dt = generate()
        stats = frame_stats(frames)
        RESULT["attempts"].append({"vae": vae_mode, "gen_sec": round(dt, 1), "stats": stats})
        if looks_black(stats):
            raise RuntimeError(f"video still black/broken after VAE fp32: {stats}")

    save_video(frames, MP4, fps=16)
    imageio.imwrite(PNG, np.asarray(frames[0].convert("RGB")))

    RESULT.update({"status": "PASS", "vae_mode": vae_mode, "gen_sec": round(dt, 1),
                   "peak_vram_MiB": round(torch.cuda.max_memory_allocated() / 1024**2, 1),
                   "video": MP4, "first_frame": PNG, "frame_stats": stats})
    with open(JSN, "w") as f:
        json.dump(RESULT, f, indent=2, ensure_ascii=False)
    print("WAN SMOKE PASS", json.dumps({k: RESULT[k] for k in ("gen_sec", "peak_vram_MiB", "vae_mode")}))

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
