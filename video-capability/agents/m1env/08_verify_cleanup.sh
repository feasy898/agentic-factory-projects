#!/usr/bin/env bash
# M1-ENV step 08: verify small assets (CLIP/whisper/yolo), cleanup, disk report
set -x
~/cradle/.venv/bin/python - <<'EOF'
import torch, whisper, open_clip
from PIL import Image
import numpy as np

# 1) CLIP ViT-L/14 openai weights load + forward
model, _, preprocess = open_clip.create_model_and_transforms("ViT-L-14", pretrained="/root/cradle/models/clip/ViT-L-14.pt")
img = preprocess(Image.open("/root/cradle/reports/milestones/m1_wan_first_frame.png").convert("RGB")).unsqueeze(0).cuda()
model = model.cuda().half().eval()
with torch.no_grad():
    feat = model.encode_image(img)
feat = feat / feat.norm(dim=-1, keepdim=True)
print("CLIP OK, feat dim:", feat.shape, "norm:", float(feat.norm()))

# 2) whisper small loads on GPU and transcribes silence without error
w = whisper.load_model("small", device="cuda", download_root="/root/cradle/models/whisper")
arr = np.zeros((16000,), dtype=np.float32)
r = whisper.transcribe(w, arr)
print("whisper OK, dims:", w.dims.n_mels, "langs:", len(w.tokenizer.langs), "empty->", repr(r["text"][:30]))

# 3) yolov8n loads and infers
from ultralytics import YOLO
y = YOLO("/root/cradle/models/yolo/yolov8n.pt")
res = y(Image.open("/root/cradle/reports/milestones/m1_wan_first_frame.png").convert("RGB"), verbose=False)
print("yolo OK, classes:", len(y.names), "dets:", len(res[0].boxes))
EOF
echo "=== cleanup ==="
rm -f ~/cradle/models/ltx-video-2b/ltx-video-2b-v0.9.1.safetensors   # unused single-file path (D-007)
rm -rf ~/downloads/wheels                                            # torch wheels already installed
rm -rf /tmp/ds119.zip /tmp/diffsynth /tmp/diffsynth-1.1.9.dist-info /tmp/pip-* /tmp/torch-2.4.1+cu121-cp312-cp312-linux_x86_64.whl /tmp/wheels /tmp/ltx_sched_probe.py /tmp/vae_probe.py /tmp/list_ltx096.py /tmp/DECISIONS_append.md /tmp/ds_check /tmp/ds216 2>/dev/null
~/cradle/.venv/bin/pip cache purge 2>/dev/null || true
df -h / | tail -1
echo "STEP08_DONE rc=$?"
