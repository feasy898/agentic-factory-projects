#!/usr/bin/env python3
"""M2 任务2: SDXL 生成 11 张 832×1216 竖版火锅测试资产 (§5.1 十类 + S11 背景图) + manifest。

- 主图 = 卡面引用路径本身 (assets/products|scenes/*.png), 832×1216 SDXL 标准 portrait 桶 (D-026);
- LTX/Wan 生成时按需 center-crop+resize (D-026, src/gen/common.open_center_resize);
- 每张记录 prompt/negative/seed/耗时/显存 → assets/products/manifest.json;
- 风格统一: 暖色/食欲感/浅景深/无人物无文字 (negative 含 human face/hands/text/watermark/logo)。
"""
import json
import os
import sys
import time

import numpy as np

os.chdir(os.path.expanduser("~/cradle"))
sys.path.insert(0, os.getcwd())

MODEL_DIR = "models/sdxl-base-1.0-fp16"
SIZE = (832, 1216)  # (w, h) SDXL 标准 portrait 桶
STEPS, CFG = 30, 6.5
STYLE = ("professional food photography style, warm amber tones, appetizing, shallow depth of field, "
         "rich color grading, photorealistic, high detail")
NEGATIVE = ("human face, hands, fingers, people, person, text, watermark, logo, signature, "
            "deformed, extra limbs, cartoon, illustration, painting, blurry, low quality")

ASSETS = [
    ("assets/products/maodu_01.png", "S01",
     "extreme close-up of fresh beef tripe (maodu) dipped in boiling spicy red hotpot broth, "
     "glistening chili oil bubbles, rising steam"),
    ("assets/products/soup_01.png", "S02",
     "rolling boiling spicy red hotpot soup base in a large pot, dried chilies and sichuan peppercorns "
     "swirling in red chili oil, dramatic steam rising"),
    ("assets/products/shrimp_01.png", "S03",
     "glossy fresh shrimp paste on a porcelain spoon, translucent bouncy texture, fresh and plump, "
     "delicate presentation"),
    ("assets/products/beef_01.png", "S04",
     "marbled fatty beef rolls fanned on a ceramic plate beside a steaming hotpot, glistening oil sheen, "
     "beautiful marbling texture"),
    ("assets/products/dessert_01.png", "S05",
     "sweet fried glutinous rice cake dessert drizzled with brown sugar syrup and dusted with soybean "
     "powder, elegant plating on a ceramic plate"),
    ("assets/products/drink_01.png", "S06",
     "iced sour plum drink in a tall glass, condensation droplets on the glass wall, fine sparkling "
     "bubbles rising, dried plums at the bottom"),
    ("assets/scenes/interior_01.png", "S07",
     "cozy hotpot restaurant interior at dinner time, warm red lantern light, steam drifting over "
     "wooden tables, bokeh lights in the background"),
    ("assets/scenes/storefront_01.png", "S08",
     "chinese restaurant storefront at night, glowing warm red lanterns, wet stone street reflections "
     "after rain, inviting warm light from the doorway"),
    ("assets/scenes/rain_window_01.png", "S09",
     "rain drops sliding down a window pane at night, warm restaurant interior lights as soft bokeh "
     "behind the wet glass, moody cozy atmosphere"),
    ("assets/scenes/table_01.png", "S10",
     "neatly set empty hotpot table, a centered steaming broth pot, polished tableware and small dishes "
     "arranged symmetrically, warm inviting light"),
    ("assets/scenes/back_view_01.png", "S11",
     "a single diner seen from behind walking toward a table in a warm lantern-lit restaurant corridor, "
     "back view only, silhouette against warm light"),
]

out = {"script": "m2_sdxl_assets", "size": SIZE, "steps": STEPS, "cfg": CFG,
       "style_suffix": STYLE, "negative": NEGATIVE, "items": []}


def main():
    import torch
    from diffusers import StableDiffusionXLPipeline

    t0 = time.time()
    pipe = StableDiffusionXLPipeline.from_pretrained(MODEL_DIR, torch_dtype=torch.float16, variant="fp16")
    pipe.to("cuda")
    out["load_sec"] = round(time.time() - t0, 1)
    print(f"SDXL loaded in {out['load_sec']}s")

    for i, (path, shot, body) in enumerate(ASSETS):
        seed = 1001 + i
        prompt = f"{body}, {STYLE}"
        gen = torch.Generator("cuda").manual_seed(seed)
        t1 = time.time()
        img = pipe(prompt=prompt, negative_prompt=NEGATIVE, width=SIZE[0], height=SIZE[1],
                   num_inference_steps=STEPS, guidance_scale=CFG, generator=gen).images[0]
        torch.cuda.synchronize()
        dt = round(time.time() - t1, 1)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        img.save(path)
        arr = np.asarray(img.convert("L"), dtype="float32")
        item = {
            "asset": path, "shot_id": shot, "seed": seed, "steps": STEPS, "guidance": CFG,
            "size": SIZE, "prompt": prompt, "negative": NEGATIVE,
            "gen_seconds": dt, "vram_peak_mb": round(torch.cuda.max_memory_allocated() / 1024**2, 1),
            "gray_mean": round(float(arr.mean()), 2), "gray_std": round(float(arr.std()), 2),
        }
        out["items"].append(item)
        print(f"ok {path} seed={seed} {dt}s vram={item['vram_peak_mb']}MB "
              f"gray=({item['gray_mean']},{item['gray_std']})")

    with open("assets/products/manifest.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    with open("workdir/logs/m2_sdxl_assets.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"ASSETS DONE: {len(out['items'])} images, manifest -> assets/products/manifest.json")


if __name__ == "__main__":
    main()
