#!/usr/bin/env bash
# M1-ENV step 04c: pin 2025-era compatible stack (torch 2.4.1 friendly)
set -x
V=~/cradle/.venv/bin
$V/pip install --no-cache-dir \
  "diffsynth==1.1.9" "transformers==4.49.0" "diffusers==0.33.1" "peft==0.14.0" \
  "huggingface_hub<1.0" \
  -i https://mirrors.aliyun.com/pypi/simple/

$V/pip uninstall -y opencv-python-headless || true
$V/pip install --no-cache-dir "opencv-python-headless==4.10.0.84" -i https://mirrors.aliyun.com/pypi/simple/

$V/python - <<'EOF'
import importlib, traceback
mods = ["torch","torchvision","diffsynth","diffusers","transformers","accelerate","peft","cv2","whisper","open_clip","ultralytics","modelscope"]
for m in mods:
    try:
        mod = importlib.import_module(m)
        print(f"OK  {m} {getattr(mod,'__version__','?')}")
    except Exception as e:
        print(f"FAIL {m}: {type(e).__name__} {e}")
        traceback.print_exc()
import torch
from diffsynth import ModelManager
from diffsynth.pipelines.wan_video import WanVideoPipeline
print("diffsynth ModelManager + WanVideoPipeline OK")
from diffusers import LTXPipeline, LTXTransformer3DModel, AutoencoderKLLTXVideo, StableDiffusionXLPipeline
print("diffusers LTX/SDXL classes OK")
print("LTXTransformer3DModel.from_single_file:", hasattr(LTXTransformer3DModel, "from_single_file"))
print("AutoencoderKLLTXVideo.from_single_file:", hasattr(AutoencoderKLLTXVideo, "from_single_file"))
from transformers import T5EncoderModel, AutoTokenizer, UMT5EncoderModel, WhisperForConditionalGeneration, CLIPModel
print("transformers model classes OK")
EOF
echo "STEP04C_DONE rc=$?"
