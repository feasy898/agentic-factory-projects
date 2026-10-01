#!/usr/bin/env bash
# smoke_prep.sh — 冒烟素材准备：测试 clip / 抽帧 / OCR 测试图 / 人像图
set -x
export TMPDIR=/data/night/tmp
PY=/data/night/venv-qc/bin/python3
mkdir -p /data/night/clips /data/night/frames/smoke_clip /data/night/frames/smoke_ocr /data/night/frames/smoke_faces /data/night/results

# 1. 测试 clip：testsrc2 10s 640x360@25
ffmpeg -y -loglevel error -f lavfi -i "testsrc2=duration=10:size=640x360:rate=25" \
  -pix_fmt yuv420p -c:v libx264 /data/night/clips/smoke_clip.mp4 || echo CLIP_FAIL

# 2. 均匀抽 8 帧
ffmpeg -y -loglevel error -i /data/night/clips/smoke_clip.mp4 \
  -vf "fps=8/10" -q:v 2 /data/night/frames/smoke_clip/f%02d.jpg || echo FRAMES_FAIL

# 3. OCR 测试图（黑字白底大号文字）
$PY - <<'EOF'
from PIL import Image, ImageDraw, ImageFont
import glob
img = Image.new("RGB", (800, 400), "white")
d = ImageDraw.Draw(img)
font = None
for pat in ["/usr/share/fonts/**/*Noto*CJK*", "/usr/share/fonts/**/*wqy*", "/usr/share/fonts/**/DejaVuSans.ttf"]:
    hits = glob.glob(pat, recursive=True)
    if hits:
        font = ImageFont.truetype(hits[0], 64); break
if font is None:
    font = ImageFont.load_default(size=72)  # Pillow>=10.1 内置可缩放字体
d.text((40, 60), "MENU OPEN 24 HRS", fill="black", font=font)
d.text((40, 200), "EXIT NO 7", fill="black", font=font)
img.save("/data/night/frames/smoke_ocr/ocr_test.png")
print("OCR_IMG_OK")
EOF

# 4. 人像测试图（opencv 官方样例，经 gh-proxy）
curl -sSL --connect-timeout 20 -o /data/night/frames/smoke_faces/messi5.jpg \
  https://gh-proxy.com/https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/messi5.jpg || echo MESSI_FAIL
curl -sSL --connect-timeout 20 -o /data/night/frames/smoke_faces/solvay.jpg \
  https://gh-proxy.com/https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/solvay.jpg || echo SOLVAY_FAIL
ls -la /data/night/clips/smoke_clip.mp4 /data/night/frames/smoke_clip/ /data/night/frames/smoke_ocr/ /data/night/frames/smoke_faces/
echo SMOKE_PREP_DONE
