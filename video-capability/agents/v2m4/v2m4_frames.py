"""V2-M4: per-video ffprobe + 2-frame contact sheets for visual inspection.

Usage (server): python v2m4_frames.py
For each film in /root/cradle_v2m4/output/v2_t*.mp4:
  - ffprobe summary -> workdir/logs/v2m4_ffprobe.json
  - extract frame at 1s and at duration/2 -> reports/milestones/v2m4_media/frames/
Build one 3x3 grid per template family (first+mid stacked per film) with labels.
"""
import glob
import json
import os
import subprocess

OUT = "/root/cradle_v2m4/output"
MEDIA = "/root/cradle/reports/milestones/v2m4_media"
FRAMES = os.path.join(MEDIA, "frames")
os.makedirs(FRAMES, exist_ok=True)

films = sorted(glob.glob(os.path.join(OUT, "v2_t*.mp4")))
probe = {}
jobs = []
for f in films:
    vid = os.path.basename(f)[:-4]
    cp = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format",
                         "-show_streams", f], capture_output=True, text=True, timeout=120)
    d = json.loads(cp.stdout)
    fmt = d.get("format", {})
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), {})
    probe[vid] = {"duration_s": round(float(fmt.get("duration", 0)), 3),
                  "width": v.get("width"), "height": v.get("height"),
                  "video_codec": v.get("codec_name"), "audio_codec": a.get("codec_name"),
                  "has_audio": bool(a), "size_mb": round(int(fmt.get("size", 0)) / 1048576, 2),
                  "fps": v.get("r_frame_rate")}
    dur = probe[vid]["duration_s"]
    for tag, ts in (("f1", 1.0), ("mid", max(dur / 2, 0.5))):
        dst = os.path.join(FRAMES, f"{vid}_{tag}.png")
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-nostats", "-loglevel", "error",
                        "-ss", str(ts), "-i", f, "-frames:v", "1", dst],
                       capture_output=True, text=True, timeout=120)
        jobs.append(dst)

with open("/root/cradle_v2m4/workdir/logs/v2m4_ffprobe.json", "w", encoding="utf-8") as fp:
    json.dump(probe, fp, ensure_ascii=False, indent=1)
print(json.dumps(probe, ensure_ascii=False, indent=1))

# grids: one per template family, rows=films, cols=(first, mid)
from PIL import Image, ImageDraw

fams = {"t1": [], "t2": [], "t3": []}
for vid in sorted(probe):
    fams[vid.split("_")[1]].append(vid)

LABEL_H = 22
TW, TH = 270, 468  # 480x832 scaled
for fam, vids in fams.items():
    if not vids:
        continue
    grid = Image.new("RGB", (2 * TW, len(vids) * (TH + LABEL_H)), "white")
    draw = ImageDraw.Draw(grid)
    for r, vid in enumerate(vids):
        y0 = r * (TH + LABEL_H)
        draw.text((4, y0 + 4), vid, fill="black")
        for cidx, tag in enumerate(("f1", "mid")):
            p = os.path.join(FRAMES, f"{vid}_{tag}.png")
            if os.path.exists(p):
                im = Image.open(p).resize((TW, TH))
                grid.paste(im, (cidx * TW, y0 + LABEL_H))
    dst = os.path.join(MEDIA, f"v2m4_{fam}_grid.jpg")
    grid.save(dst, quality=88)
    print("grid ->", dst)
