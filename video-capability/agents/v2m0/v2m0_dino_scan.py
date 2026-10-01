#!/usr/bin/env python
"""V2-M0: DINOv2 coarse screen of all v1 candidates (first-vs-last frame cosine).
Outputs workdir/logs/v2m0_dino_scan.json + first/mid/last frame PNGs under workdir/v2m0_scan/."""
import sqlite3, json, os, subprocess
import torch
from transformers import AutoModel, AutoImageProcessor
from PIL import Image

MP = "/root/cradle/models/dinov2-large"
OUT_FRAMES = "/root/cradle/workdir/v2m0_scan"
os.makedirs(OUT_FRAMES, exist_ok=True)

cands = []
for tag, dbp in [("MAIN", "/root/cradle/workdir/cradle.sqlite3"), ("SB", "/root/cradle_m5/workdir/cradle.sqlite3")]:
    db = sqlite3.connect(dbp)
    cur = db.cursor()
    for row in cur.execute("select id,shot_id,path,verdict,overall_score,selected from candidates"):
        cands.append({"db": tag, "cid": row[0], "shot": row[1], "path": row[2],
                      "verdict": row[3], "score": row[4], "selected": row[5]})

proc = AutoImageProcessor.from_pretrained(MP)
model = AutoModel.from_pretrained(MP, torch_dtype=torch.float16).cuda().eval()


def emb(img):
    x = proc(images=img, return_tensors="pt")
    with torch.no_grad():
        o = model(pixel_values=x.pixel_values.half().cuda())
    return o.last_hidden_state[:, 0]


def nframes(v):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=nb_frames", "-of", "csv=p=0", v],
                           capture_output=True, text=True, timeout=30)
        return int(r.stdout.strip())
    except Exception:
        return 0


results = []
for cd in cands:
    key = "%s_%s_%d" % (cd["db"], cd["shot"], cd["cid"])
    rec = dict(cd)
    rec["key"] = key
    fdir = os.path.join(OUT_FRAMES, key)
    if not os.path.exists(cd["path"]) or os.path.getsize(cd["path"]) == 0:
        rec["status"] = "missing"
        results.append(rec)
        print("MISS", key, flush=True)
        continue
    os.makedirs(fdir, exist_ok=True)
    f0 = os.path.join(fdir, "first.png")
    fmid = os.path.join(fdir, "mid.png")
    fl = os.path.join(fdir, "last.png")
    if not (os.path.exists(f0) and os.path.exists(fmid) and os.path.exists(fl)):
        nf = nframes(cd["path"])
        mid = max(nf // 2, 1)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", cd["path"],
                        "-vf", "select=eq(n\\,0)", "-vframes", "1", f0], check=False)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", cd["path"],
                        "-vf", "select=eq(n\\,%d)" % mid, "-vframes", "1", fmid], check=False)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.1", "-i", cd["path"],
                        "-vframes", "1", fl], check=False)
    if not (os.path.exists(f0) and os.path.exists(fl) and os.path.getsize(f0) > 0 and os.path.getsize(fl) > 0):
        rec["status"] = "extract_fail"
        results.append(rec)
        print("EXTF", key, flush=True)
        continue
    a = emb(Image.open(f0).convert("RGB"))
    b = emb(Image.open(fl).convert("RGB"))
    cos = torch.nn.functional.cosine_similarity(a, b).item()
    rec["status"] = "ok"
    rec["dino_first_last"] = round(cos, 4)
    results.append(rec)
    print("OK", key, round(cos, 4), cd["verdict"], flush=True)

results.sort(key=lambda r: r.get("dino_first_last", 9.9))
with open("/root/cradle/workdir/logs/v2m0_dino_scan.json", "w") as f:
    json.dump(results, f, ensure_ascii=False, indent=1)
print("SCAN_DONE", len(results))
