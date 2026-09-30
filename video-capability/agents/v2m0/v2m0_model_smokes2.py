#!/usr/bin/env python
"""V2-M0: fixed G7 model smokes (dtype handling + import path)."""
import json, os, time
import torch
from PIL import Image

OUT_JSON = "/root/cradle/workdir/logs/v2m0_model_smokes2.json"
LOG = "/root/cradle/workdir/logs/v2m0_model_smokes2.log"
FRAMES = "/root/cradle/workdir/v2m0_scan"
results = {}


def log(msg):
    print(msg, flush=True)
    with open(LOG, "a") as f:
        f.write(msg + "\n")


def test_image():
    return Image.open(os.path.join(FRAMES, "SB_S17_60", "first.png")).convert("RGB")


def smoke_grounding_dino():
    t0 = time.time()
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
    mp = "/root/cradle/models/grounding-dino-tiny"
    proc = AutoProcessor.from_pretrained(mp)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(mp, torch_dtype=torch.float16).cuda().eval()
    im = test_image()
    inputs = proc(images=im, text="shrimp. hot pot. bowl.", return_tensors="pt").to("cuda")
    inputs.pixel_values = inputs.pixel_values.half()
    with torch.no_grad():
        out = model(**inputs)
    res = proc.post_process_grounded_object_detection(
        out, inputs.input_ids, box_threshold=0.25, text_threshold=0.25)[0]
    boxes = res["boxes"].cpu().tolist()
    labels = res.get("text_labels", res.get("labels", []))
    scores = res["scores"].cpu().tolist()
    dt = time.time() - t0
    log("GDINO fp16 dt=%.1fs boxes=%d labels=%s scores=%s" % (dt, len(boxes), list(labels), [round(s, 3) for s in scores]))
    return {"ok": len(boxes) > 0, "n_boxes": len(boxes), "labels": [str(x) for x in labels],
            "scores": [round(s, 4) for s in scores], "dt_s": round(dt, 1), "dtype": "fp16"}


def smoke_sam():
    t0 = time.time()
    from transformers import SamModel, SamProcessor
    mp = "/root/cradle/models/sam-vit-base"
    proc = SamProcessor.from_pretrained(mp)
    model = SamModel.from_pretrained(mp, torch_dtype=torch.float16).cuda().eval()
    im = test_image()
    w, h = im.size
    pt = [[int(w * 0.5), int(h * 0.45)]]
    inputs = proc(images=im, input_points=[pt], return_tensors="pt").to("cuda")
    inputs.pixel_values = inputs.pixel_values.half()
    with torch.no_grad():
        out = model(**inputs)
    masks = proc.image_processor.post_process_masks(
        out.pred_masks.cpu(), inputs["original_sizes"].cpu(), inputs["reshaped_input_sizes"].cpu())[0]
    fm = masks[0][0].float().mean().item()
    dt = time.time() - t0
    log("SAM fp16 dt=%.1fs mask_mean=%.4f" % (dt, fm))
    return {"ok": True, "mask_mean": round(fm, 4), "dt_s": round(dt, 1), "dtype": "fp16"}


def smoke_raft():
    t0 = time.time()
    from torchvision.models.optical_flow import Raft_Small_Weights, raft_small
    import torchvision.transforms.functional as TF
    ckpt_dir = os.path.expanduser("~/.cache/torch/hub/checkpoints")
    os.makedirs(ckpt_dir, exist_ok=True)
    src = "/root/cradle/models/raft/raft_small_C_T_V2-01064c6d.pth"
    dst = os.path.join(ckpt_dir, "raft_small_C_T_V2-01064c6d.pth")
    if not os.path.exists(dst):
        os.symlink(src, dst)
    model = raft_small(weights=Raft_Small_Weights.DEFAULT).cuda().eval()
    d = os.path.join(FRAMES, "SB_S17_60")
    a = TF.to_tensor(Image.open(os.path.join(d, "first.png")).convert("RGB")).unsqueeze(0).cuda()
    b = TF.to_tensor(Image.open(os.path.join(d, "last.png")).convert("RGB")).unsqueeze(0).cuda()
    with torch.no_grad():
        flow = model(a, b)[-1]
    mag = flow.norm(dim=1)
    p95 = torch.quantile(mag.flatten().float(), 0.95).item()
    dt = time.time() - t0
    log("RAFT dt=%.1fs flow=%s mean=%.4f p95=%.4f px" % (dt, tuple(flow.shape), mag.mean().item(), p95))
    return {"ok": True, "flow_shape": list(flow.shape), "mean_mag": round(mag.mean().item(), 4),
            "p95_mag_px": round(p95, 4), "dt_s": round(dt, 1)}


for name, fn in [("grounding_dino_tiny", smoke_grounding_dino), ("sam_vit_base", smoke_sam),
                 ("raft_small", smoke_raft)]:
    try:
        results[name] = fn()
        log("SMOKE %s OK" % name)
    except Exception as e:
        import traceback
        results[name] = {"ok": False, "error": traceback.format_exc()[-500:]}
        log("SMOKE %s FAIL: %s" % (name, str(e)[:200]))

with open(OUT_JSON, "w") as f:
    json.dump(results, f, ensure_ascii=False, indent=1)
log("SMOKES2_DONE")
