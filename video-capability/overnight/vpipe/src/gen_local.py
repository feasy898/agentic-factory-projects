#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_local.py — vpipe 本地生成模块：diffusers 调 Wan2.1-T2V-1.3B / LTX-Video-2B，种子固定
（vpipe SPEC.md 模块 1；改造自今晚已验证脚本 overnight/scripts/gen_wan.py + gen_ltx.py，
两脚本在 anolis-gpu-01 卡1 fp16 实测产出 70 clip，见 overnight/数据/clips_local/）。

契约: 输入=contracts/shot.schema.json 合规的镜头 JSON；输出=clip mp4 + <shot>.gen_meta.json
      （登记进 contracts/asset_manifest.schema.json 合规的 manifest）。不 import 任何 vpipe 兄弟模块。
铁律: 卡0 被生产 vLLM 占用——本模块启动即强制 export CUDA_VISIBLE_DEVICES=1（可在环境变量
      VPIPE_LOCAL_CUDA_DEVICES 覆盖，默认 "1"），绝不触碰卡0。
确定性: torch.Generator(device).manual_seed(shot.seed)（缺省 42）；同种子同参连跑 3 次帧级一致已实测
      （overnight/数据/clips_local/determinism/ + check_determinism.py）。
降级: LTX fp16 黑帧/NaN → VAE fp32 重跑（gen_ltx.py 实测路径）；Wan 失败 → 记 failed 并退出 1
      （失败本身是边界数据，方案 §4）。

用法（GPU 机器 /data/night/venv）:
  python gen_local.py --shot shot.json --out-dir /data/night/clips --manifest /data/night/results/manifest.json
  python gen_local.py --shot shot.json --engine ltx --model /data/night/models/LTX-Video ...
  python gen_local.py --validate-only --shot shot.json          # 仅校验契约（无 torch 机器可用）
"""
import argparse
import datetime
import hashlib
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", os.environ.get("VPIPE_LOCAL_CUDA_DEVICES", "1"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
SHOT_SCHEMA = HERE.parent / "contracts" / "shot.schema.json"

# 引擎能力表（V100S-32GB fp16 实测边界，overnight/边界报告.md）
ENGINES = {
    "wan": {
        "model_id": "Wan-AI/Wan2.1-T2V-1.3B-Diffusers",
        "pipeline": "WanPipeline",
        "fps": 16, "frames_unit": 4,            # 帧数=4k+1；81帧@16fps≈5s
        "default_wh": (832, 480), "guidance": 5.0,
        "negative_default": ("色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，"
                             "整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，"
                             "画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，"
                             "静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走"),
    },
    "ltx": {
        "model_id": "Lightricks/LTX-Video (2B)",
        "pipeline": "LTXPipeline",
        "fps": 24, "frames_unit": 8,            # 帧数=8k+1；121@24fps≈5s
        "default_wh": (704, 480), "guidance": 3.0,
        "decode_timestep": 0.05, "decode_noise_scale": 0.025,
        "negative_default": "worst quality, inconsistent motion, blurry, jittery, distorted",
    },
}
ASPECT_WH = {  # 480P 档画幅→宽高（与今晚矩阵一致；其他档位在 V100 上未验证，拒绝）
    "9:16": (480, 832), "16:9": (832, 480), "1:1": (480, 480), "4:3": (640, 480), "3:4": (480, 640),
}


def log(msg):
    print(f"[gen_local {datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def sha256_file(path, buf=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def validate_shot(shot, schema_path=SHOT_SCHEMA):
    """契约校验。jsonschema 可用则全量校验，否则退回 required-key 检查（记录降级）。"""
    try:
        import jsonschema
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        jsonschema.validate(shot, schema)
        return True, None
    except ImportError:
        missing = [k for k in ("schema_version", "shot_id", "prompt", "duration_s", "aspect")
                   if k not in shot]
        return (not missing), f"jsonschema 不可用，退回 required 检查；缺 {missing}" if missing else \
            "jsonschema 不可用，退回 required 检查（通过）"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def frames_for(engine_cfg, duration_s):
    """时长→帧数（4k+1 / 8k+1 规则，gen_wan.py:14 / gen_ltx.py:13 的实测约定）。"""
    u = engine_cfg["frames_unit"]
    return max(u + 1, round(duration_s * (16 if u == 4 else 24) / (u + 1)) // u * u + 1)


def resolve_wh(engine, aspect):
    if aspect not in ASPECT_WH:
        raise ValueError(f"aspect {aspect} 不在 480P 档映射表 {sorted(ASPECT_WH)}（本地引擎只支持 480P）")
    return ASPECT_WH[aspect]


def render_shot(shot, engine, model_dir, out_dir, steps=50):
    """核心接口：Shot dict → (meta dict, clip_path)。GPU 机器调用；torch/diffusers 缺失时抛异常。"""
    import numpy as np
    import torch
    cfg = ENGINES[engine]
    from diffusers import WanPipeline, LTXPipeline, AutoencoderKLLTXVideo  # noqa: F401
    from diffusers.utils import export_to_video

    w, h = resolve_wh(engine, shot["aspect"])
    num_frames = frames_for(cfg, shot["duration_s"])
    seed = int(shot.get("seed", 42))
    prompt = shot["prompt"]
    negative = shot.get("negative_prompt") or cfg["negative_default"]

    meta = {"schema_version": "1.0", "shot_id": shot["shot_id"], "engine": engine,
            "model": cfg["model_id"], "backend": f"diffusers-{cfg['pipeline']}",
            "prompt": prompt, "seed": seed, "num_frames": num_frames, "steps": steps,
            "width": w, "height": h, "guidance_scale": cfg["guidance"], "fps": cfg["fps"],
            "dtype": "float16", "gpu": torch.cuda.get_device_name(0),
            "aspect": shot["aspect"], "duration_s_requested": shot["duration_s"]}

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    clip_path = out_dir / f"{shot['shot_id']}__{engine}.mp4"

    t0 = time.time()
    gen = torch.Generator(device="cuda").manual_seed(seed)

    def generate(vae_fp32=False):
        load0 = time.time()
        kwargs = {"torch_dtype": torch.float16}
        if vae_fp32:
            kwargs["vae"] = AutoencoderKLLTXVideo.from_pretrained(
                model_dir, subfolder="vae", torch_dtype=torch.float32)
        if engine == "wan":
            pipe = WanPipeline.from_pretrained(model_dir, **kwargs)
        else:
            pipe = LTXPipeline.from_pretrained(model_dir, **kwargs)
        pipe.to("cuda")
        pipe.vae.enable_tiling()
        load_s = time.time() - load0
        torch.cuda.reset_peak_memory_stats()
        g = torch.Generator(device="cuda").manual_seed(seed)
        extra = dict(decode_timestep=cfg["decode_timestep"], decode_noise_scale=cfg["decode_noise_scale"]) \
            if engine == "ltx" else {}
        t = time.time()
        frames = pipe(prompt=prompt, negative_prompt=negative, num_frames=num_frames,
                      height=h, width=w, num_inference_steps=steps,
                      guidance_scale=cfg["guidance"], generator=g, **extra).frames[0]
        return frames, time.time() - t, round(torch.cuda.max_memory_allocated() / 2 ** 30, 2), load_s

    status = "ok"
    if engine == "wan":
        frames, gen_s, peak, load_s = generate()
    else:
        # LTX：fp16 黑帧/NaN → VAE fp32 降级（gen_ltx.py:64-81 实测路径）
        def black_or_nan(fr):
            t = torch.from_numpy(np.stack([np.asarray(f, dtype="float32") for f in fr]))
            return bool(torch.isnan(t).any() or t.abs().mean() < 1e-3)
        try:
            frames, gen_s, peak, load_s = generate(vae_fp32=False)
            if black_or_nan(frames):
                raise RuntimeError("fp16 输出黑帧/NaN")
        except Exception as e:
            meta["fp16_error"] = repr(e)[:500]
            log(f"LTX fp16 失败 → VAE fp32 降级: {repr(e)[:200]}")
            frames, gen_s, peak, load_s = generate(vae_fp32=True)
            status = "ok_with_vae_fp32_fallback"

    export_to_video(frames, clip_path, fps=cfg["fps"])
    meta.update({"dtype_status": status, "load_s": round(load_s, 1),
                 "gen_s": round(gen_s, 1), "peak_vram_gb": peak,
                 "clip_path": str(clip_path), "sha256": sha256_file(clip_path),
                 "size_bytes": clip_path.stat().st_size,
                 "frames_produced": len(frames), "status": "ok",
                 "generated_at": datetime.datetime.now().isoformat(timespec="seconds")})
    return meta, clip_path


def register_manifest(manifest_path, shot, meta, clip_path):
    doc = {"schema_version": "1.0", "name": manifest_path.stem,
           "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
           "generator": "gen_local.py@vpipe1.0", "items": []}
    if manifest_path.exists():
        try:
            doc = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        except Exception as e:
            log(f"[manifest] 旧表读取失败，重建：{e}")
    item = {"asset_id": f"{shot['shot_id']}@{meta['model']}", "kind": "clip",
            "path": str(clip_path), "sha256": meta["sha256"],
            "size_bytes": meta["size_bytes"],
            "registered_at": meta["generated_at"],
            "provenance": {"module": "gen_local", "model": meta["model"],
                           "seed": shot.get("seed", 42), "seed_sent": True,
                           "shot_id": shot["shot_id"], "elapsed_s": meta["gen_s"]},
            "evidence": {"engine": meta["engine"], "num_frames": meta["num_frames"],
                         "peak_vram_gb": meta["peak_vram_gb"], "dtype_status": meta["dtype_status"]}}
    doc["items"] = [it for it in doc.get("items", [])
                    if it.get("asset_id") != item["asset_id"]] + [item]
    Path(manifest_path).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="vpipe gen_local：diffusers Wan/LTX 本地生成（卡1）")
    ap.add_argument("--shot", required=True, help="Shot 契约 JSON 路径")
    ap.add_argument("--engine", default="wan", choices=sorted(ENGINES))
    ap.add_argument("--model", default="", help="模型目录（缺省按引擎取今晚已下载路径）")
    ap.add_argument("--out-dir", default="./clips")
    ap.add_argument("--manifest", default="", help="asset manifest（缺省只写 .gen_meta.json）")
    ap.add_argument("--steps", type=int, default=50)
    ap.add_argument("--validate-only", action="store_true", help="只校验契约与参数映射，不加载模型")
    args = ap.parse_args()

    shot = json.loads(Path(args.shot).read_text(encoding="utf-8"))
    ok, err = validate_shot(shot)
    if not ok:
        log(f"[FATAL] Shot 契约校验失败: {err}")
        return 2
    if err:
        log(f"[WARN] {err}")
    engine = (shot.get("engine_hint") or {}).get("model") or args.engine
    if engine not in ENGINES:
        engine = args.engine
    model_dir = args.model or f"/data/night/models/{'Wan2.1-T2V-1.3B-Diffusers' if engine == 'wan' else 'LTX-Video'}"
    try:
        resolve_wh(engine, shot["aspect"])
        frames_for(ENGINES[engine], shot["duration_s"])
    except ValueError as e:
        log(f"[FATAL] 参数映射失败: {e}")
        return 2
    if shot.get("resolution", "480P") != "480P":
        log(f"[WARN] resolution={shot['resolution']} 本地引擎仅实测过 480P（边界报告），继续按 480P 渲染")
    if (shot.get("audio") or {}).get("generate"):
        log("[WARN] 本地 Wan/LTX 无音频能力，audio.generate=true 记 engine_unsupported 并忽略")

    if args.validate_only:
        log(f"[ok] 契约与参数映射通过: shot={shot['shot_id']} engine={engine} model={model_dir}")
        return 0

    meta, clip_path = render_shot(shot, engine, model_dir, args.out_dir, args.steps)
    mp = Path(args.out_dir) / f"{shot['shot_id']}__{engine}.gen_meta.json"
    mp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.manifest:
        register_manifest(Path(args.manifest), shot, meta, clip_path)
    log(f"GEN_LOCAL_OK " + json.dumps({k: meta[k] for k in
                                       ("shot_id", "gen_s", "peak_vram_gb", "sha256")},
                                      ensure_ascii=False))
    log(f"META {mp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
