#!/usr/bin/env python
# T3: assemble smoke_report.json from per-item result fragments.
import json, os, subprocess, datetime

A = "/data/xdng/smoke/artifacts"
OUT = "/data/xdng/smoke/smoke_report.json"


def load(name):
    p = os.path.join(A, name)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {"ok": False, "error": f"result fragment missing: {name}", "seconds": None,
            "artifact_path": None, "dtype": None}


def meta():
    env = {}
    try:
        import torch, transformers
        env = {"python": os.sys.version.split()[0], "torch": torch.__version__,
               "torch_cuda_build": torch.version.cuda, "cuda_available": torch.cuda.is_available(),
               "gpu": torch.cuda.get_device_name(0), "transformers": transformers.__version__}
    except Exception as e:
        env = {"error": str(e)}
    try:
        drv = subprocess.run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader",
                              "-i", "1"], capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception:
        drv = "unknown"
    return env, drv


def main():
    env, drv = meta()
    notes = {
        "1-dub-tts-fp32": "engine default path (use_bf16=False); torch 2.5.1+cu118 / transformers 4.52.1; "
                          "text_normalization=False (WeTextProcessing/pynini not installable from CN pip); "
                          "bigvgan weights pre-placed at model_dir/hf_cache/bigvgan via hf-mirror; "
                          "emotion assets (conformer_shaw + qwen0.6b) auto-cached on first load; 8s mono ref wav",
        "1-dub-tts-fp16": "v2.5 constructor exposes only use_bf16 (fp32/bf16); fp16 switch does not exist -> "
                          "engine-level limitation, not a Volta failure; bf16 forbidden on Volta (sm_70)",
        "2-lip-fast": "diffusers==0.30.2 + transformers 4.52.1 + mmpose/mmcv 2.2.0 (mmdet version guard relaxed to "
                      "<2.3.0, GPU-side env only) + S3FD detector weights placed locally; v1.5 unet fp16; "
                      "input 2s 704x1216 25fps clip, output re-encoded h264 + aac",
        "3-alt-tts-b": "requires torch>=2.5 (SDPA enable_gqa) -> validated on torch 2.5.1+cu118 (sm_70 in arch list); "
                       "engine loads fp32 by default (no dtype switch surfaced); reference-only voice-clone mode",
        "4-asr-core": "validated under transformers==5.13.0 (native arch support needs >=5.13); venv later downgraded "
                      "to 4.52.1 for TTS/lip engines -> deployment must pin transformers>=5.13 for this component "
                      "(separate venv or resolver split); input sample was English speech, correctly transcribed",
    }
    items = []
    for key, frag in [("1-dub-tts-fp32", "dub-tts_fp32.json"),
                      ("1-dub-tts-fp16", "dub-tts_fp16.json"),
                      ("2-lip-fast", "lip-fast_v15.json"),
                      ("3-alt-tts-b", "alt-tts-b_fp16.json"),
                      ("4-asr-core", "asr-core_fp16.json")]:
        d = dict(item=key, **load(frag))
        d["env_note"] = notes[key]
        items.append(d)
    report = {
        "task": "T3 GPU smoke (D1)",
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "machine": "anolis-gpu-01 / 2x Tesla V100S-PCIE-32GB (Volta sm_70), GPU index 1 used",
        "driver": drv,
        "env": {**env,
                "venv": "/data/xdng/venv",
                "note_downloads": "HF_ENDPOINT=https://hf-mirror.com; pypi index switched to Aliyun mirror (Tsinghua mirror actively blocks this machine IP: 'you've been denied access')",
                "note_bf16": "Volta has no BF16; bf16 explicitly never enabled"},
        "items": items,
        "summary": {
            "all_ok": all(i.get("ok") for i in items),
            "ok_count": sum(1 for i in items if i.get("ok")),
            "total": len(items),
        },
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print("WROTE", OUT)
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
