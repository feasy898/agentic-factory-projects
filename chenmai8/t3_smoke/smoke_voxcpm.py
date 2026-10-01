#!/usr/bin/env python
# T3 smoke: alt-tts-b (VoxCPM2) synthesis of 1 Chinese sentence, voice-clone from reference wav.
# Volta note: repo pins torch>=2.5 but venv has torch 2.4.1+cu118 — honest empirical test.
import json, os, sys, time

RESULT = "/data/xdng/smoke/artifacts/alt-tts-b_fp16.json"
MODELS = "/data/xdng/models/alt-tts-b"
REF = "/data/xdng/smoke/assets/ref_zh.wav"
OUT = "/data/xdng/smoke/artifacts/alt-tts-b_zh.wav"
TEXT = "你到底想怎么样？把话说清楚。"

def finish(ok, seconds, artifact=None, error=None, dtype="fp32-default"):
    with open(RESULT, "w", encoding="utf-8") as f:
        json.dump({"model": "alt-tts-b", "dtype": dtype, "ok": ok,
                   "seconds": round(seconds, 2), "artifact_path": artifact,
                   "error": (str(error)[:500] if error else None)}, f, ensure_ascii=False, indent=1)
    print("WROTE", RESULT, flush=True)
    sys.exit(0 if ok else 1)

t0 = time.time()
try:
    import numpy as np, soundfile as sf, torch
    from voxcpm import VoxCPM
    model = VoxCPM.from_pretrained(MODELS, optimize=False, load_denoiser=False, device="cuda")
    print(f"loaded load_s={time.time()-t0:.1f}", flush=True)
    t1 = time.time()
    wav = model.generate(
        text=TEXT,
        prompt_wav_path=None,
        prompt_text=None,
        reference_wav_path=REF,
        cfg_value=2.0,
        inference_timesteps=10,
        normalize=False,
    )
    seconds = time.time() - t1
    wav = np.asarray(wav).squeeze()
    sr = 16000
    sf.write(OUT, wav, sr)
    dur = len(wav) / sr
    print(f"GEN [{seconds:.1f}s] audio_dur={dur:.2f}s -> {OUT}", flush=True)
    ok = bool(dur > 0.5 and float(np.abs(wav).max()) > 1e-4)
    finish(ok, seconds, OUT, None if ok else "silent or empty output")
except Exception as e:
    import traceback; traceback.print_exc()
    finish(False, time.time() - t0, None, e)
