#!/usr/bin/env python3
"""Build smoke-test assets on the GPU machine (pillow + ffmpeg, CPU only).
1. /data/night/golden/test_hand.jpg      cartoon hand with exactly 5 fingers
2. /data/night/clips/smoke_counter.mp4   8s clip: red ball moves left->right, frame counter bottom-left
Run with the judge venv python (has pillow). ffmpeg binary required for the video.
"""
import os
import subprocess
from PIL import Image, ImageDraw

G = "/data/night/golden"
C = "/data/night/clips"
os.makedirs(G, exist_ok=True)
os.makedirs(C, exist_ok=True)

# ---------- 1. hand image ----------
W, H = 640, 640
img = Image.new("RGB", (W, H), (245, 240, 230))
d = ImageDraw.Draw(img)
# palm
d.ellipse([220, 330, 420, 560], fill=(232, 190, 160), outline=(180, 130, 100), width=4)
# thumb
d.ellipse([150, 380, 240, 470], fill=(232, 190, 160), outline=(180, 130, 100), width=4)
# five fingers
import math
for i, ang in enumerate([-56, -28, 0, 28, 56]):
    a = math.radians(ang)
    x0 = 320 + 150 * math.sin(a) - 22
    y0 = 360 - 150 * math.cos(a)
    x1 = 320 + 150 * math.sin(a) + 22
    y1 = 360 - 150 * math.cos(a) + 150
    d.ellipse([x0, y0, x1, y1], fill=(232, 190, 160), outline=(180, 130, 100), width=4)
d.text((20, 20), "hand with five fingers", fill=(60, 60, 60))
img.save(os.path.join(G, "test_hand.jpg"), quality=92)
print("wrote", os.path.join(G, "test_hand.jpg"))

# ---------- 2. counter video ----------
FPS, SEC, VW, VH = 6, 8, 640, 360
tmp = "/data/night/clips/_smoke_frames"
os.makedirs(tmp, exist_ok=True)
n = FPS * SEC
for k in range(n):
    fr = Image.new("RGB", (VW, VH), (25, 25, 35))
    dr = ImageDraw.Draw(fr)
    x = int(60 + (VW - 120) * k / (n - 1))
    dr.ellipse([x - 28, 120, x + 28, 176], fill=(220, 40, 40))       # red ball
    dr.rectangle([500, 250, 560, 310], fill=(40, 90, 200))           # static blue square
    dr.text((20, 300), "frame %03d" % k, fill=(255, 255, 255))
    fr.save(os.path.join(tmp, "f_%03d.png" % k))
out_mp4 = os.path.join(C, "smoke_counter.mp4")
subprocess.run(["ffmpeg", "-y", "-v", "error", "-framerate", str(FPS),
                "-i", os.path.join(tmp, "f_%03d.png"),
                "-c:v", "mpeg4", "-q:v", "3", "-pix_fmt", "yuv420p", out_mp4], check=True)
print("wrote", out_mp4)
