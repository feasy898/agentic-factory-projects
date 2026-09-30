#!/usr/bin/env python
"""V2-M0: build labeled frame sheets for visual inspection.
Tier A/B: suspect candidates (first|mid|last triptychs).
Pass pool: selected high-DINO candidates (first|last pairs, 3 per sheet).
Outputs to /root/cradle/workdir/v2m0_sheets/."""
import json, os
from PIL import Image, ImageDraw, ImageFont

SCAN = "/root/cradle/workdir/logs/v2m0_dino_scan.json"
FRAMES = "/root/cradle/workdir/v2m0_scan"
OUT = "/root/cradle/workdir/v2m0_sheets"
os.makedirs(OUT, exist_ok=True)
FONT = None
for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
          "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
    if os.path.exists(p):
        FONT = ImageFont.truetype(p, 22)
        break

recs = {r["key"]: r for r in json.load(open(SCAN))}

def trio_sheet(key, scale, out_path):
    d = os.path.join(FRAMES, key)
    imgs = []
    for n in ("first.png", "mid.png", "last.png"):
        im = Image.open(os.path.join(d, n)).convert("RGB")
        im = im.resize((int(im.width * scale), int(im.height * scale)))
        imgs.append(im)
    W = sum(i.width for i in imgs) + 8 * 2
    H = max(i.height for i in imgs) + 34
    sheet = Image.new("RGB", (W, H), (18, 18, 18))
    x = 0
    for i in imgs:
        sheet.paste(i, (x, 34))
        x += i.width + 8
    dr = ImageDraw.Draw(sheet)
    r = recs[key]
    dr.text((6, 5), "%s  dino=%.4f  %s  score=%s sel=%s" % (key, r.get("dino_first_last", -1), r["verdict"], r["score"], r["selected"]),
            fill=(255, 220, 60), font=FONT)
    sheet.save(out_path, quality=88)

# tier A: dino < 0.80
tierA = sorted([k for k, r in recs.items() if r.get("dino_first_last", 9) < 0.80],
               key=lambda k: recs[k]["dino_first_last"])
for i, k in enumerate(tierA):
    trio_sheet(k, 0.62, os.path.join(OUT, "A%02d_%s.jpg" % (i, k)))
print("tierA", len(tierA))

# tier B: 0.80 <= dino < 0.88
tierB = sorted([k for k, r in recs.items() if 0.80 <= r.get("dino_first_last", 9) < 0.88],
               key=lambda k: recs[k]["dino_first_last"])
for i, k in enumerate(tierB):
    trio_sheet(k, 0.62, os.path.join(OUT, "B%02d_%s.jpg" % (i, k)))
print("tierB", len(tierB))

# pass pool: selected==1, verdict pass, dino >= 0.96, sorted desc, top 12
pool = sorted([k for k, r in recs.items()
               if r.get("selected") == 1 and r["verdict"] == "pass" and r.get("dino_first_last", 0) >= 0.96],
              key=lambda k: -recs[k]["dino_first_last"])[:12]
PAIRS_PER_SHEET = 3
for s in range(0, len(pool), PAIRS_PER_SHEET):
    chunk = pool[s:s + PAIRS_PER_SHEET]
    rows = []
    for k in chunk:
        d = os.path.join(FRAMES, k)
        a = Image.open(os.path.join(d, "first.png")).convert("RGB")
        b = Image.open(os.path.join(d, "last.png")).convert("RGB")
        sc = 460 / a.height
        a = a.resize((int(a.width * sc), int(a.height * sc)))
        b = b.resize((int(b.width * sc), int(b.height * sc)))
        rows.append((k, a, b))
    W = max(a.width + b.width + 8 for _, a, b in rows) + 12
    H = sum(a.height + 34 for _, a, b in rows) + 8
    sheet = Image.new("RGB", (W, H), (18, 18, 18))
    dr = ImageDraw.Draw(sheet)
    y = 0
    for k, a, b in rows:
        dr.text((8, y + 4), "%s  dino=%.4f score=%s" % (k, recs[k]["dino_first_last"], recs[k]["score"]),
                fill=(120, 255, 140), font=FONT)
        sheet.paste(a, (6, y + 34))
        sheet.paste(b, (6 + a.width + 8, y + 34))
        y += a.height + 34
    sheet.save(os.path.join(OUT, "P%02d.jpg" % (s // PAIRS_PER_SHEET)), quality=88)
print("pass pool", len(pool))
print("SHEETS_DONE")
