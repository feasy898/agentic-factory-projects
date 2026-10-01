#!/usr/bin/env python
# T3 smoke: asr-core (Qwen3-ASR family) fp16 transcription of 1 Chinese sentence.
# Neutral internal name: asr-core. Writes JSON result fragment.
import json, os, sys, time, glob

RESULT = "/data/xdng/smoke/artifacts/asr-core_fp16.json"
MODELS = "/data/xdng/models/asr-core"
AUDIO = sys.argv[1] if len(sys.argv) > 1 else None

def finish(ok, seconds, artifact=None, error=None, dtype="fp16"):
    with open(RESULT, "w", encoding="utf-8") as f:
        json.dump({"model": "asr-core", "dtype": dtype, "ok": ok,
                   "seconds": round(seconds, 2), "artifact_path": artifact,
                   "error": (str(error)[:500] if error else None)}, f, ensure_ascii=False, indent=1)
    print("WROTE", RESULT, flush=True)
    sys.exit(0 if ok else 1)

t0 = time.time()
try:
    import torch
    from transformers import AutoProcessor, AutoModelForMultimodalLM
    import soundfile as sf
    if AUDIO is None:
        raise RuntimeError("no input audio provided")
    info = sf.info(AUDIO)
    print(f"input audio: {AUDIO} sr={info.samplerate} dur={info.duration:.2f}s", flush=True)

    processor = AutoProcessor.from_pretrained(MODELS)
    model = AutoModelForMultimodalLM.from_pretrained(
        MODELS, dtype=torch.float16, attn_implementation="sdpa")
    model = model.to("cuda").eval()
    print(f"loaded dtype={model.dtype} on {model.device} load_s={time.time()-t0:.1f}", flush=True)

    t1 = time.time()
    inputs = processor.apply_transcription_request(language="zh", audio=AUDIO)
    inputs = inputs.to(model.device, torch.float16)
    with torch.inference_mode():
        out_ids = model.generate(**inputs, max_new_tokens=256, do_sample=False)
    gen = out_ids[:, inputs["input_ids"].shape[1]:]
    text = processor.batch_decode(gen, skip_special_tokens=True)[0]
    seconds = time.time() - t1
    print(f"TRANSCRIPT [{seconds:.1f}s]: {text}", flush=True)
    artifact = "/data/xdng/smoke/artifacts/asr-core_fp16_transcript.txt"
    with open(artifact, "w", encoding="utf-8") as f:
        f.write(text)
    ok = bool(text.strip())
    finish(ok, seconds, artifact, None if ok else "empty transcript")
except Exception as e:
    import traceback; traceback.print_exc()
    finish(False, time.time() - t0, None, e)
