#!/usr/bin/env bash
# M1-ENV step 04b: install remaining pip packages
set -x
V=~/cradle/.venv/bin
$V/pip install --no-cache-dir \
  diffsynth diffusers transformers accelerate safetensors sentencepiece protobuf einops \
  open_clip_torch ultralytics edge-tts openai-whisper opencv-python-headless imageio \
  pyyaml pytest "huggingface_hub[cli]" peft \
  -i https://mirrors.aliyun.com/pypi/simple/
# ultralytics pulls opencv-python (needs libGL); force headless afterwards
$V/pip uninstall -y opencv-python || true
$V/pip install --no-cache-dir opencv-python-headless -i https://mirrors.aliyun.com/pypi/simple/
$V/python - <<'EOF'
import importlib
mods = ["torch","torchvision","diffsynth","diffusers","transformers","accelerate","safetensors",
        "sentencepiece","einops","open_clip","ultralytics","edge_tts","whisper","cv2","imageio",
        "yaml","pytest","huggingface_hub","peft","modelscope","ftfy","pandas"]
import importlib
for m in mods:
    try:
        mod = importlib.import_module(m)
        v = getattr(mod, "__version__", "?")
        print(f"OK  {m} {v}")
    except Exception as e:
        print(f"FAIL {m}: {type(e).__name__} {e}")
EOF
echo "STEP04B_DONE rc=$?"
