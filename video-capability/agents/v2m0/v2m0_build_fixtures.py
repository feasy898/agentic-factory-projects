#!/usr/bin/env python
"""V2-M0: build the regression fixture library (SPECS_V2 §2).
- fail >= 15 (four deformation categories, visual inspection confirmed)
- pass_structural >= 10 (ken_burns products: v1 S12 + 3 fallback + 11 deterministic regen)
- pass_candidate >= 10 (G1-G6 high score + G7e-style pair pre-screen by V2-M0 agent; pending human confirm)
Physical files: /root/cradle/workdir/fixtures/{fail,pass_structural,pass_candidate}/
DB: fixtures table in /root/cradle/workdir/cradle.sqlite3
Strips: /root/cradle/workdir/fixtures/strips/ (git-tracked evidence)
"""
import json, os, shutil, sqlite3, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, "/root/cradle")
from src.gen.kenburns import run_kenburns  # noqa: E402

SCAN = json.load(open("/root/cradle/workdir/logs/v2m0_dino_scan.json"))
BY_KEY = {r["key"]: r for r in SCAN}
FIX_ROOT = "/root/cradle/workdir/fixtures"
ASSETS = "/root/cradle/assets"
DB = "/root/cradle/workdir/cradle.sqlite3"
for sub in ("fail", "pass_structural", "pass_candidate", "strips"):
    os.makedirs(os.path.join(FIX_ROOT, sub), exist_ok=True)

FONT = None
for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
          "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
    if os.path.exists(p):
        FONT = ImageFont.truetype(p, 20)
        break

fixtures = []  # dicts: fixture_id, path, label, category, human_source, notes, dino, key


def src_path(key):
    return BY_KEY[key]["path"]


def add(fid, label, category, human_source, notes, path, key=None, dino=None):
    if key is not None:
        dino = BY_KEY[key].get("dino_first_last")
    fixtures.append({"fixture_id": fid, "path": path, "label": label, "category": category,
                     "human_source": human_source, "notes": notes, "dino_first_last": dino, "key": key})


# ---------------- FAIL fixtures (visual inspection confirmed) ----------------
FAILS = [
    ("FX-F001", "SB_S17_60", "fluid_melt", False,
     "虾仁约9只清晰可数→逐步融为虾味糊浆,个体形状完全消失(并发count_drift);dino全库最低0.3523"),
    ("FX-F002", "SB_S17_58", "fluid_melt", False,
     "虾仁首帧完好→中帧糊化→尾帧溶解成酱糊,仅零星残形"),
    ("FX-F003", "SB_S03_18", "fluid_melt", False,
     "整盘虾仁化为浓稠炖糊,个体边界消失,数量不可辨识"),
    ("FX-F004", "SB_ABS03P_4", "split_merge", True,
     "盘中凭空出现无定形橙色酱糊团并逐渐扩大,与虾仁融合;AB竖版selected(曾入AB成片)"),
    ("FX-F005", "SB_S15_52", "object_flow", False,
     "红油与锅内物溢出锅沿流淌到桌面成滩,固态边界破坏;原typeB画廊案例,目检确认真形变故收录"),
    ("FX-F006", "SB_S17_59", "fluid_melt", True,
     "虾仁肿胀融浆,尾帧仅2只依稀可辨;生产selected(曾入成片)"),
    ("FX-F007", "SB_ABS03L_3", "fluid_melt", True,
     "虾仁膨胀融连成糊状团块,个体形状大面积丢失;AB横版selected"),
    ("FX-F008", "SB_S02_14", "fluid_melt", False,
     "锅内红油长出凝胶状红色团块并逐帧增大,超出沸腾翻滚范畴"),
    ("FX-F009", "SB_S15_53", "fluid_melt", False,
     "锅面化为浓稠红泥浆状凝固物,周边配菜碗内容同步变形"),
    ("FX-F010", "SB_S02_16", "split_merge", True,
     "红油表面凝胶膜增厚蔓延,辣椒被裹入融合;生产selected"),
    ("FX-F011", "SB_S15_54", "split_merge", True,
     "锅内凭空隆起巨大红肉状物占据锅面,配菜碗内容变异;生产selected"),
    ("FX-F012", "SB_S03_17", "count_drift", False,
     "木勺舀虾滑入场,盘内虾仁由约9只增至15+只堆满(数量渐变)"),
    ("FX-F013", "SB_S02_15", "fluid_melt", False,
     "borderline:汤体变稠胶化+辣椒肿胀,程度轻;按不对称原则收录"),
    ("FX-F014", "SB_S03_19", "count_drift", True,
     "borderline:虾仁膨胀密堆观感数量增多,个体形状尚保持;生产selected;按不对称原则收录"),
    ("FX-F015", "SB_S04_20", "object_flow", False,
     "borderline:油瓶中尾帧呈融状黑团(主食物肥牛保持);按不对称原则收录"),
]
for fid, key, cat, sel, note in FAILS:
    dst = os.path.join(FIX_ROOT, "fail", fid + ".mp4")
    shutil.copy2(src_path(key), dst)
    add(fid, "fail", cat, "V2-M0_agent_visual(G7e对读+三联帧目检)", note + ";sel=%d" % (1 if sel else 0), dst, key=key)

# ---------------- PASS_STRUCTURAL ----------------
# 1) v1 real products: S12 ken_burns pass + 3 fallback renders (fallback lane = ken_burns, D-route)
kb_extra = [
    ("FX-S001", "MAIN_S12_35", "v1 S12 ken_burns 真管线产物(gates全绿, 480x832/5s)"),
    ("FX-S002", "MAIN_S08_56", "v1 fallback 渲染(ken_burns车道, S08资产)"),
    ("FX-S003", "MAIN_S09_57", "v1 fallback 渲染(ken_burns车道, S09资产)"),
    ("FX-S004", "MAIN_S11_62", "v1 fallback 渲染(ken_burns车道, S11资产)"),
]
for fid, key, note in kb_extra:
    dst = os.path.join(FIX_ROOT, "pass_structural", fid + ".mp4")
    shutil.copy2(src_path(key), dst)
    add(fid, "pass_structural", "ken_burns", "v1_pipeline_product", note, dst, key=key)

# 2) deterministic regeneration over the 11 v1 assets
MOTIONS = ["zoom_in_1.06", "zoom_out", "pan_left", "pan_right"]
assets = sorted(
    [os.path.join(ASSETS, "products", f) for f in os.listdir(os.path.join(ASSETS, "products")) if f.endswith(".png")]
    + [os.path.join(ASSETS, "scenes", f) for f in os.listdir(os.path.join(ASSETS, "scenes")) if f.endswith(".png")]
)
assert len(assets) == 11, "expected 11 assets, got %d" % len(assets)
kb_regen = []
for i, ap in enumerate(assets):
    motion = MOTIONS[i % len(MOTIONS)]
    stem = os.path.splitext(os.path.basename(ap))[0]
    fid = "FX-S%03d" % (5 + i)
    dst = os.path.join(FIX_ROOT, "pass_structural", "kb_%s_%s.mp4" % (stem, motion))
    meta = run_kenburns(ap, dst, motion=motion, duration_sec=5.0, fps=16, out_w=480, out_h=832)
    kb_regen.append((fid, dst, stem, motion))
    add(fid, "pass_structural", "ken_burns", "deterministic_regen(kenburns.py)",
        "对v1资产 %s 以 motion=%s 确定性再生成(zoompan, 无RNG, 480x832/5s/16fps)" % (os.path.basename(ap), motion),
        dst)

# ---------------- PASS_CANDIDATE (pending human confirmation) ----------------
PASSES = [
    ("FX-C001", "SB_S01_11", "毛肚特写,主体形状保持,汤面波动属液体豁免;sel=1"),
    ("FX-C002", "SB_S01_12", "毛肚特写,主体保持,液面高光变化"),
    ("FX-C003", "SB_S01_13", "毛肚特写,主体保持"),
    ("FX-C004", "SB_S10_39", "全景餐桌,碗碟结构保持,锅内沸腾豁免;sel=1"),
    ("FX-C005", "SB_S10_40", "全景餐桌,结构保持"),
    ("FX-C006", "SB_ABS11L_9", "走廊背影行走,人物位移为正常运动,结构保持;AB横版sel=1"),
    ("FX-C007", "SB_S14_51", "饮料杯,液体飞溅与果块滚动属液体豁免,杯体保持"),
    ("FX-C008", "SB_S05_25", "糕点盘,块形与数量保持,酱汁延展豁免"),
    ("FX-C009", "SB_S05_23", "糕点盘,块形与数量保持"),
    ("FX-C010", "SB_S08_32", "夜景店面,灯笼门脸结构保持;sel=0"),
    ("FX-C011", "SB_S06_26", "饮料杯,液体飞溅豁免,杯体与果块保持"),
    ("FX-C012", "SB_S13_47", "虾仁盘,虾形完好数量一致;sel=1"),
    ("FX-C013", "SB_ABS08P_8", "夜景店面竖版,结构保持;AB竖版sel=1"),
    ("FX-C014", "SB_ABS08L_7", "夜景店面横版,结构保持;AB横版sel=1"),
    ("FX-C015", "MAIN_S10_30", "LTX调试片,餐桌全景首尾一致"),
    ("FX-C016", "MAIN_S04_11", "LTX调试片,肥牛卷+倒油,首尾一致"),
    ("FX-C017", "MAIN_S03_7", "LTX调试片,虾仁盘首尾一致,虾形完好"),
]
for fid, key, note in PASSES:
    dst = os.path.join(FIX_ROOT, "pass_candidate", fid + ".mp4")
    shutil.copy2(src_path(key), dst)
    add(fid, "pass_candidate", "generated_high_score", "V2-M0_agent_G7e_pre-screen",
        note + ";待人工确认", dst, key=key)

# ---------------- strips (3-frame labeled evidence, git-tracked) ----------------
def strip_for(fid, mp4, out):
    tmp = "/tmp/v2m0_fx_%s" % fid
    os.makedirs(tmp, exist_ok=True)
    names = ["f0.png", "fm.png", "f1.png"]
    for n in names:
        p = os.path.join(tmp, n)
        if os.path.exists(p):
            os.remove(p)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp4, "-vf", "select=eq(n\\,0)",
                    "-vframes", "1", os.path.join(tmp, "f0.png")], check=False)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp4, "-vf", "select=eq(n\\,40)",
                    "-vframes", "1", os.path.join(tmp, "fm.png")], check=False)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.1", "-i", mp4,
                    "-vframes", "1", os.path.join(tmp, "f1.png")], check=False)
    imgs = []
    for n in names:
        p = os.path.join(tmp, n)
        im = Image.open(p).convert("RGB") if os.path.exists(p) else Image.new("RGB", (320, 480), (40, 40, 40))
        sc = 420 / im.height
        imgs.append(im.resize((int(im.width * sc), int(im.height * sc))))
    W = sum(i.width for i in imgs) + 16
    H = max(i.height for i in imgs) + 30
    sheet = Image.new("RGB", (W, H), (15, 15, 15))
    dr = ImageDraw.Draw(sheet)
    x = 0
    for i in imgs:
        sheet.paste(i, (x, 30))
        x += i.width + 8
    if FONT:
        dr.text((6, 4), "%s  %s" % (fid, "first|mid|last"), fill=(255, 215, 80), font=FONT)
    sheet.save(out, quality=85)
    shutil.rmtree(tmp, ignore_errors=True)


for fx in fixtures:
    strip_for(fx["fixture_id"], fx["path"], os.path.join(FIX_ROOT, "strips", fx["fixture_id"] + ".jpg"))

# ---------------- DB table ----------------
db = sqlite3.connect(DB)
db.execute("""CREATE TABLE IF NOT EXISTS fixtures(
    fixture_id TEXT PRIMARY KEY, path TEXT NOT NULL, label TEXT NOT NULL,
    category TEXT, human_source TEXT, notes TEXT)""")
db.execute("DELETE FROM fixtures")
for fx in fixtures:
    db.execute("INSERT INTO fixtures(fixture_id,path,label,category,human_source,notes) VALUES(?,?,?,?,?,?)",
               (fx["fixture_id"], fx["path"], fx["label"], fx["category"], fx["human_source"], fx["notes"]))
db.commit()
db.close()

# ---------------- manifest + stats ----------------
manifest = {"fixtures": fixtures,
            "stats": {
                "total": len(fixtures),
                "fail": sum(1 for f in fixtures if f["label"] == "fail"),
                "pass_structural": sum(1 for f in fixtures if f["label"] == "pass_structural"),
                "pass_candidate": sum(1 for f in fixtures if f["label"] == "pass_candidate"),
                "fail_categories": {c: sum(1 for f in fixtures if f["label"] == "fail" and f["category"] == c)
                                     for c in ("fluid_melt", "split_merge", "count_drift", "object_flow")},
            }}
with open(os.path.join(FIX_ROOT, "fixtures_manifest.json"), "w") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=1)
print(json.dumps(manifest["stats"], ensure_ascii=False))
total_mb = sum(os.path.getsize(f["path"]) for f in fixtures) / 1e6
print("media total %.1f MB; strips: %d" % (total_mb, len(os.listdir(os.path.join(FIX_ROOT, "strips")))))
print("FIXTURES_DONE")
