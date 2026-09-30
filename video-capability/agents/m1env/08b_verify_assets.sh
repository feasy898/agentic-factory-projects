#!/usr/bin/env bash
set -x
~/cradle/.venv/bin/python - <<'EOF'
import torch, whisper, open_clip
from PIL import Image
import numpy as np

model, _, preprocess = open_clip.create_model_and_transforms("ViT-L-14", pretrained="/root/cradle/models/clip/ViT-L-14.pt")
img = preprocess(Image.open("/root/cradle/reports/milestones/m1_wan_first_frame.png").convert("RGB")).unsqueeze(0).cuda().half()
model = model.cuda().half().eval()
with torch.no_grad():
    feat = model.encode_image(img)
feat = feat / feat.norm(dim=-1, keepdim=True)
print("CLIP OK, feat dim:", tuple(feat.shape), "norm:", round(float(feat.norm()), 4))

w = whisper.load_model("small", device="cuda", download_root="/root/cradle/models/whisper")
arr = np.zeros((16000,), dtype=np.float32)
r = whisper.transcribe(w, arr)
print("whisper OK, n_mels:", w.dims.n_mels, "empty->", repr(r["text"][:30]))

from ultralytics import YOLO
y = YOLO("/root/cradle/models/yolo/yolov8n.pt")
res = y(Image.open("/root/cradle/reports/milestones/m1_wan_first_frame.png").convert("RGB"), verbose=False)
print("yolo OK, classes:", len(y.names), "dets:", len(res[0].boxes))
EOF
echo "STEP08B_DONE rc=$?"
