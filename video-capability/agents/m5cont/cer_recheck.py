import json
import sys

sys.path.insert(0, "/root/cradle")
from src.compose import normalize_for_cer  # noqa: E402
from src.gates.g6_business import cer as cer_fn  # noqa: E402

import sqlite3  # noqa: E402
import whisper  # noqa: E402

HOTWORDS = ("火锅店美食口播，词汇：老灶火锅、毛肚、锁鲜、到港、虾滑、肥牛、半价、酸梅汤、糍粑、红糖、锅底、牛油、暗号、定位、折。")

db = sqlite3.connect("/root/cradle_m5/workdir/cradle.sqlite3")
db.row_factory = sqlite3.Row
model = whisper.load_model("medium", device="cuda")

out = []
for r in db.execute("select video_id, path, g6_json from m5_videos order by id"):
    g6 = json.loads(r["g6_json"])
    d = g6.get("detail") or {}
    ref = "".join(d.get("expected_narration") or [])
    wav = "/root/cradle_m5/workdir/m5_intermediate/" + r["video_id"] + ".mp4.g6audio.wav"
    res = model.transcribe(wav, language="zh", temperature=0, initial_prompt=HOTWORDS)
    hyp_raw = str(res.get("text", "")).strip()
    ref_norm = normalize_for_cer(ref)
    hyp_norm = normalize_for_cer(hyp_raw)
    cer_val = cer_fn(ref_norm, hyp_norm)
    out.append({
        "video_id": r["video_id"],
        "asr_model": "whisper-medium",
        "cer_medium": round(cer_val, 4),
        "cer_small_db": d.get("cer"),
        "subtitle_exact": d.get("subtitle_exact"),
        "hyp_raw": hyp_raw,
        "hyp_norm": hyp_norm,
        "ref_norm": ref_norm,
    })
    print(r["video_id"], "cer_medium=", round(cer_val, 4), "cer_small=", d.get("cer"))

with open("/root/cradle_m5/workdir/logs/m5_g6_cer_medium_recheck.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("saved: /root/cradle_m5/workdir/logs/m5_g6_cer_medium_recheck.json")
