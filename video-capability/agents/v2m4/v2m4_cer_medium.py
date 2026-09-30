"""V2-M4: whisper-medium CER recheck for 9 films (D-047 protocol).

- extract 16k mono wav from each composed film
- whisper-medium transcribe(language=zh, temperature=fallback tuple,
  condition_on_previous_text=False, initial_prompt=production hotwords)
- CER vs expected_narration stored in m5_videos.g6_json (same normalize_for_cer + cer)
- output: /root/cradle_v2m4/workdir/logs/v2m4_g6_cer_medium_recheck.json
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, "/root/cradle")
import sqlite3

from src.gates.g6_business import cer
from src.compose import normalize_for_cer

SB = "/root/cradle_v2m4"
HOTWORDS = ("火锅店美食口播，词汇：老灶火锅、毛肚、锁鲜、到港、虾滑、肥牛、半价、酸梅汤、"
            "糍粑、红糖、锅底、牛油、暗号、定位、折。")

import whisper

model = whisper.load_model(os.path.expanduser("~/.cache/whisper/medium.pt"), device="cuda")

db = sqlite3.connect(os.path.join(SB, "workdir", "cradle.sqlite3"))
db.row_factory = sqlite3.Row
rows = db.execute("SELECT video_id, path, g6_json FROM m5_videos ORDER BY video_id").fetchall()

out = []
for r in rows:
    vid, path = r["video_id"], r["path"]
    g6 = json.loads(r["g6_json"])
    ref = g6["detail"]["expected_narration"]
    wav = f"/tmp/{vid}_16k.wav"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-nostats", "-loglevel", "error",
                    "-i", path, "-ar", "16000", "-ac", "1", "-vn", wav],
                   capture_output=True, text=True, timeout=300)
    res = model.transcribe(wav, language="zh",
                           temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
                           condition_on_previous_text=False,
                           initial_prompt=HOTWORDS)
    hyp_raw = str(res.get("text", "")).strip()
    c = cer(normalize_for_cer(ref), normalize_for_cer(hyp_raw))
    small_cer = g6["detail"]["cer"]
    out.append({"video_id": vid, "cer_whisper_small_production": small_cer,
                "cer_whisper_medium_recheck": round(c, 4),
                "g6_subtitle_exact": g6["detail"]["subtitle_exact"],
                "hyp_medium_raw": hyp_raw})
    print(vid, "small=%.4f medium=%.4f" % (small_cer, c))
    os.remove(wav)

dst = os.path.join(SB, "workdir", "logs", "v2m4_g6_cer_medium_recheck.json")
with open(dst, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("->", dst)
