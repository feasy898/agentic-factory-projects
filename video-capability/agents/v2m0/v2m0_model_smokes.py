#!/usr/bin/env python
"""V2-M0: G7 model Volta self-checks (fp16 forward smokes).
Results appended as JSON to workdir/logs/v2m0_model_smokes.json + human log."""
import json, os, subprocess, time
import torch
from PIL import Image

OUT_JSON = "/root/cradle/workdir/logs/v2m0_model_smokes.json"
LOG = "/root/cradle/workdir/logs/v2m0_model_smokes.log"
FRAMES = "/root/cradle/workdir/v2m0_scan"
results = {}


def log(msg):
    print(msg, flush=True)
    with open(LOG, "a") as f:
        f.write(msg + "\n")


def test_image():
    # a food frame (S17 shrimp candidate first frame)
    p = os.path.join(FRAMES, "SB_S17_60")
    return Image.open(os.path.join(p, "first.png")).convert("RGB")


# ---------- 1) Grounding DINO (transformers, zero-shot) ----------
def smoke_grounding_dino():
    t0 = time.time()
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
    mp = "/root/cradle/models/grounding-dino-tiny"
    proc = AutoProcessor.from_pretrained(mp)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(mp, torch_dtype=torch.float16).cuda().eval()
    im = test_image()
    inputs = proc(images=im, text="shrimp. hot pot. bowl.", return_tensors="pt").to("cuda")
    with torch.no_grad():
        out = model(**inputs)
    res = proc.post_process_grounded_object_detection(
        out, inputs.input_ids, box_threshold=0.25, text_threshold=0.25)[0]
    boxes = res["boxes"].cpu().tolist()
    labels = res["text_labels"] if "text_labels" in res else res.get("labels", [])
    scores = res["scores"].cpu().tolist()
    dt = time.time() - t0
    log("GDINO dt=%.1fs boxes=%d labels=%s scores=%s" % (dt, len(boxes), list(labels), [round(s, 3) for s in scores]))
    return {"ok": len(boxes) > 0, "n_boxes": len(boxes), "labels": [str(x) for x in labels],
            "scores": [round(s, 4) for s in scores], "load_and_infer_s": round(dt, 1), "dtype": "fp16"}


# ---------- 2) SAM ViT-B (transformers SamModel, point prompt) ----------
def smoke_sam():
    t0 = time.time()
    from transformers import SamModel, SamProcessor
    mp = "/root/cradle/models/sam-vit-base"
    proc = SamProcessor.from_pretrained(mp)
    model = SamModel.from_pretrained(mp, torch_dtype=torch.float16).cuda().eval()
    im = test_image()
    w, h = im.size
    pt = [[int(w * 0.5), int(h * 0.45)]]  # center-ish point
    inputs = proc(images=im, input_points=[pt], return_tensors="pt").to("cuda")
    with torch.no_grad():
        out = model(**inputs)
    masks = proc.image_processor.post_process_masks(
        out.pred_masks.cpu(), inputs["original_sizes"].cpu(), inputs["reshaped_input_sizes"].cpu())[0]
    m = masks[0][0].sigmoid() > 0.5 if masks.dtype.is_floating_point else masks[0][0].bool()
    frac = m.float().mean().item()
    dt = time.time() - t0
    log("SAM dt=%.1fs mask_frac=%.4f dtype=%s" % (dt, frac, masks.dtype))
    return {"ok": True, "mask_frac": round(frac, 4), "dt_s": round(dt, 1), "dtype": "fp16"}


# ---------- 3) RAFT-small (torchvision) ----------
def smoke_raft():
    t0 = time.time()
    import torchvision.models as tvm
    from torchvision.models.optical_flow import Raft_Small_Weights
    import torchvision.transforms.functional as TF
    # put weights where torchvision expects them
    ckpt_dir = os.path.expanduser("~/.cache/torch/hub/checkpoints")
    os.makedirs(ckpt_dir, exist_ok=True)
    src = "/root/cradle/models/raft/raft_small_C_T_V2-01064c6d.pth"
    dst = os.path.join(ckpt_dir, "raft_small_C_T_V2-01064c6d.pth")
    if not os.path.exists(dst):
        os.symlink(src, dst)
    model = tvm.raft_small(weights=Raft_Small_Weights.DEFAULT).cuda().eval()
    d = os.path.join(FRAMES, "SB_S17_60")
    a = TF.to_tensor(Image.open(os.path.join(d, "first.png")).convert("RGB")).unsqueeze(0).cuda()
    b = TF.to_tensor(Image.open(os.path.join(d, "last.png")).convert("RGB")).unsqueeze(0).cuda()
    with torch.no_grad():
        flow = model(a, b)[-1]
    mag = flow.norm(dim=1)
    p95 = torch.quantile(mag.flatten().float(), 0.95).item()
    dt = time.time() - t0
    log("RAFT dt=%.1fs flow_shape=%s mean_mag=%.4f p95=%.4f" % (dt, tuple(flow.shape), mag.mean().item(), p95))
    return {"ok": True, "flow_shape": list(flow.shape), "mean_mag": round(mag.mean().item(), 4),
            "p95_mag_px": round(p95, 4), "dt_s": round(dt, 1)}


# ---------- 4) Depth-Anything-V1-Small (transformers) ----------
def smoke_depth():
    t0 = time.time()
    from transformers import AutoModelForDepthEstimation, AutoImageProcessor
    mp = "/root/cradle/models/depth-anything-small-hf"
    proc = AutoImageProcessor.from_pretrained(mp)
    model = AutoModelForDepthEstimation.from_pretrained(mp, torch_dtype=torch.float16).cuda().eval()
    im = test_image()
    inputs = proc(images=im, return_tensors="pt").to("cuda")
    with torch.no_grad():
        out = model(**inputs)
    depth = out.predicted_depth
    dt = time.time() - t0
    log("DEPTH dt=%.1fs depth_shape=%s min=%.3f max=%.3f" % (dt, tuple(depth.shape), depth.min().item(), depth.max().item()))
    return {"ok": True, "shape": list(depth.shape), "min": round(depth.min().item(), 3),
            "max": round(depth.max().item(), 3), "dt_s": round(dt, 1), "dtype": "fp16"}


# ---------- 5) MobileSAM backup (file integrity) ----------
def smoke_mobilesam():
    p = "/root/cradle/models/mobile-sam/mobile_sam.pt"
    if not os.path.exists(p):
        return {"ok": False, "note": "missing"}
    size = os.path.getsize(p)
    with open(p, "rb") as f:
        head = f.read(4)
    if head[:2] != b"PK" and head != b"\x80\x02":
        return {"ok": False, "note": "not a torch file (head=%r)" % head, "size": size}
    try:
        import torch as T
        sd = T.load(p, map_location="cpu")
        return {"ok": True, "size": size, "keys": len(sd) if isinstance(sd, dict) else -1}
    except Exception as e:
        return {"ok": False, "note": str(e)[:120], "size": size}


for name, fn in [("grounding_dino_tiny", smoke_grounding_dino), ("sam_vit_base", smoke_sam),
                 ("raft_small", smoke_raft), ("depth_anything_small", smoke_depth),
                 ("mobile_sam", smoke_mobilesam)]:
    try:
        results[name] = fn()
        log("SMOKE %s OK" % name)
    except Exception as e:
        import traceback
        results[name] = {"ok": False, "error": traceback.format_exc()[-600:]}
        log("SMOKE %s FAIL: %s" % (name, str(e)[:200]))

with open(OUT_JSON, "w") as f:
    json.dump(results, f, ensure_ascii=False, indent=1)
log("ALL_SMOKES_DONE")
