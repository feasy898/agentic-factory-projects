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
row = db.execute("select path, g6_json from m5_videos where video_id=?", ("t3_offer_v1",)).fetchone()
g6 = json.loads(row["g6_json"])
d = g6.get("detail") or {}
ref = "".join(d.get("expected_narration") or [])
wav = "/root/cradle_m5/workdir/m5_intermediate/t3_offer_v1.mp4.g6audio.wav"

model = whisper.load_model("medium", device="cuda")
variants = {
    "medium_tfallback_nocond": dict(temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0], condition_on_previous_text=False),
    "medium_beam_nocond": dict(temperature=[0.0, 0.2, 0.4], beam_size=5, condition_on_previous_text=False),
    "medium_noprompt": dict(temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0], condition_on_previous_text=False, initial_prompt=None),
}
ref_norm = normalize_for_cer(ref)
for name, kw in variants.items():
    params = dict(language="zh", initial_prompt=HOTWORDS)
    params.update(kw)
    if params.get("initial_prompt") is None:
        params.pop("initial_prompt")
    res = model.transcribe(wav, **params)
    hyp_raw = str(res.get("text", "")).strip()
    hyp_norm = normalize_for_cer(hyp_raw)
    print(name, "cer=", round(cer_fn(ref_norm, hyp_norm), 4), "hyp=", hyp_norm[:120])
