#!/usr/bin/env python
# T3 smoke: dub-tts (IndexTTS-2.5) on Volta. fp32 = use_bf16=False (default);
# fp16 = attempted via use_fp16 kwarg — v2.5 API documents only use_bf16 (no fp16 switch);
# bf16 is FORBIDDEN (Volta sm_70 has no BF16). Two result fragments are written.
import json, os, sys, time, traceback

MODELS = "/data/xdng/models/dub-tts"
REPO = "/data/xdng/smoke/repos/index-tts"
REF = "/data/xdng/smoke/assets/ref_zh.wav"
TEXT = "你到底想怎么样？把话说清楚。"
OUT32 = "/data/xdng/smoke/artifacts/dub-tts_fp32.wav"


def write(name, payload):
    path = f"/data/xdng/smoke/artifacts/{name}"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print("WROTE", path, flush=True)


def run_fp32():
    sys.path.insert(0, REPO)
    from indextts.infer_v2_5 import IndexTTS2
    t0 = time.time()
    # use_bf16=False -> fp32 (self.dtype=None); use_cuda_kernel=False -> BigVGAN pure torch
    tts = IndexTTS2(cfg_path=os.path.join(MODELS, "config.yaml"), model_dir=MODELS,
                    use_bf16=False, use_cuda_kernel=False, device="cuda:0")
    print(f"fp32 model loaded load_s={time.time()-t0:.1f}", flush=True)
    t1 = time.time()
    tts.infer(spk_audio_prompt=REF, text=TEXT, output_path=OUT32, lang="zh",
              emo_alpha=0.0, text_normalization=False, verbose=True)
    seconds = time.time() - t1
    dur = os.path.getsize(OUT32) if os.path.exists(OUT32) else 0
    ok = dur > 10000  # non-trivial wav bytes
    print(f"fp32 infer [{seconds:.1f}s] out_bytes={dur}", flush=True)
    write("dub-tts_fp32.json", {"model": "dub-tts", "dtype": "fp32", "ok": ok,
                                "seconds": round(seconds, 2),
                                "artifact_path": OUT32 if ok else None,
                                "error": None if ok else f"output too small: {dur} bytes"})


def run_fp16():
    sys.path.insert(0, REPO)
    from indextts.infer_v2_5 import IndexTTS2
    t0 = time.time()
    try:
        tts = IndexTTS2(cfg_path=os.path.join(MODELS, "config.yaml"), model_dir=MODELS,
                        use_fp16=True, use_cuda_kernel=False, device="cuda:0")
        # if constructor unexpectedly accepts fp16, do a real synthesis
        out = "/data/xdng/smoke/artifacts/dub-tts_fp16.wav"
        t1 = time.time()
        tts.infer(spk_audio_prompt=REF, text=TEXT, output_path=out, lang="zh",
                  emo_alpha=0.0, text_normalization=False, verbose=True)
        seconds = time.time() - t1
        ok = os.path.exists(out) and os.path.getsize(out) > 10000
        write("dub-tts_fp16.json", {"model": "dub-tts", "dtype": "fp16", "ok": ok,
                                    "seconds": round(seconds, 2),
                                    "artifact_path": out if ok else None, "error": None if ok else "no output"})
    except Exception as e:
        traceback.print_exc()
        write("dub-tts_fp16.json", {"model": "dub-tts", "dtype": "fp16", "ok": False,
                                    "seconds": round(time.time() - t0, 2), "artifact_path": None,
                                    "error": f"v2.5 API does not expose fp16 (use_bf16 only; bf16 forbidden on Volta): {type(e).__name__}: {str(e)[:300]}"})


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    if which in ("fp32", "both"):
        try:
            run_fp32()
        except Exception as e:
            traceback.print_exc()
            write("dub-tts_fp32.json", {"model": "dub-tts", "dtype": "fp32", "ok": False,
                                        "seconds": 0.0, "artifact_path": None,
                                        "error": f"{type(e).__name__}: {str(e)[:400]}"})
    if which in ("fp16", "both"):
        run_fp16()
