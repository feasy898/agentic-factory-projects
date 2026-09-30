# M1 Smoke B step 1: SDXL (diffusers, fp16) generates the product-style first frame
# 480x832 portrait, Chongqing hotpot maodu closeup, warm light, shallow DOF, no humans/text
import os, json, time, traceback

import numpy as np
import torch

MODEL_DIR = "/root/cradle/models/sdxl-base-1.0-fp16"
OUT_DIR = "/root/cradle/reports/milestones"
PNG = os.path.join(OUT_DIR, "m1_wan_first_frame.png")
ASSET = "/root/cradle/assets/products/maodu_01.png"
JSN = os.path.join(OUT_DIR, "m1_sdxl_image.json")

RESULT = {"script": "m1_sdxl_image", "params": {
    "model": "stabilityai/stable-diffusion-xl-base-1.0 (fp16 variants)",
    "size": [480, 832], "steps": 30, "guidance_scale": 6.5, "seed": 42,
    "dtype": "float16",
}}

def main():
    from diffusers import StableDiffusionXLPipeline
    import imageio.v2 as imageio

    t0 = time.time()
    pipe = StableDiffusionXLPipeline.from_pretrained(MODEL_DIR, torch_dtype=torch.float16,
                                                     variant="fp16")
    pipe.to("cuda")
    RESULT["load_sec"] = round(time.time() - t0, 1)

    prompt = ("extreme close-up of fresh beef tripe (maodu) in boiling spicy red hotpot broth, "
              "glistening chili oil bubbles, rising steam, warm golden restaurant lighting, "
              "shallow depth of field, professional food photography, appetizing, photorealistic, "
              "high detail, 8k")
    negative = ("human face, hands, fingers, people, text, watermark, logo, signature, "
                "deformed, extra limbs, cartoon, illustration, painting, blurry, low quality")

    gen = torch.Generator("cuda").manual_seed(42)
    t1 = time.time()
    img = pipe(prompt=prompt, negative_prompt=negative, width=480, height=832,
               num_inference_steps=30, guidance_scale=6.5, generator=gen).images[0]
    torch.cuda.synchronize()
    dt = time.time() - t1

    os.makedirs(os.path.dirname(ASSET), exist_ok=True)
    img.save(PNG)
    img.save(ASSET)
    arr = np.asarray(img.convert("L"), dtype=np.float32)
    RESULT.update({"status": "PASS", "gen_sec": round(dt, 1),
                   "peak_vram_MiB": round(torch.cuda.max_memory_allocated() / 1024**2, 1),
                   "gray_mean": round(float(arr.mean()), 2), "gray_std": round(float(arr.std()), 2),
                   "image": PNG, "asset_copy": ASSET})
    with open(JSN, "w") as f:
        json.dump(RESULT, f, indent=2, ensure_ascii=False)
    print("SDXL IMAGE PASS", json.dumps({k: RESULT[k] for k in ("gen_sec", "peak_vram_MiB", "gray_mean")}))

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
