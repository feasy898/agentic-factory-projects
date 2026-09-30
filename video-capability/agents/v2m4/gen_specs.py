import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "specs")
os.makedirs(OUT, exist_ok=True)

T1 = "product_seeding_30s_v2"
T2 = "store_ambiance_28s_v2"
T3 = "offer_lead_28s_v2"

specs = []

t1_base = {"hook": "S02", "evidence_1": "S03", "evidence_2": "S04"}
specs.append({"video_id": "v2_t1_seeding_v1", "template": T1, "slots": {
    **t1_base, "ambiance_1": "S09", "ambiance_2": "S07", "offer_1": "S13",
    "ambiance_3": "S08", "evidence_3": "S17", "evidence_demo": "S18"},
    "numbers": {"price": "42.8", "offer": "锅底免费续"}})
specs.append({"video_id": "v2_t1_seeding_v2", "template": T1, "slots": {
    **t1_base, "ambiance_1": "S16", "ambiance_2": "S10", "offer_1": "S17",
    "ambiance_3": "S08", "evidence_3": "S15", "evidence_demo": "S19"},
    "numbers": {"price": "45.9", "offer": "第二份半价"}})
specs.append({"video_id": "v2_t1_seeding_v3", "template": T1, "slots": {
    **t1_base, "ambiance_1": "S09", "ambiance_2": "S11", "offer_1": "S13",
    "ambiance_3": "S08", "evidence_3": "S17", "evidence_demo": "S18"},
    "numbers": {"price": "39.9", "offer": "凉菜免费送"}})

t2_base = {"ambiance_1": "S08", "hook": "S02", "evidence_1": "S01", "evidence_2": "S15", "offer": "S14"}
specs.append({"video_id": "v2_t2_ambiance_v1", "template": T2, "slots": {
    **t2_base, "ambiance_2": "S07", "ambiance_3": "S09", "ambiance_4": "S10", "evidence_demo": "S19"},
    "numbers": {"price": "39.9", "offer": "酸梅汤免费续杯"}})
specs.append({"video_id": "v2_t2_ambiance_v2", "template": T2, "slots": {
    **t2_base, "ambiance_2": "S11", "ambiance_3": "S16", "ambiance_4": "S07", "evidence_demo": "S18"},
    "numbers": {"price": "35.9", "offer": "酸梅汤一元续杯"}})
specs.append({"video_id": "v2_t2_ambiance_v3", "template": T2, "slots": {
    **t2_base, "ambiance_2": "S10", "ambiance_3": "S09", "ambiance_4": "S11", "evidence_demo": "S19"},
    "numbers": {"price": "36.9", "offer": "夜宵档送小食"}})

t3_base = {"hook": "S02", "storefront": "S08"}
specs.append({"video_id": "v2_t3_offer_v1", "template": T3, "slots": {
    **t3_base, "evidence_1": "S01", "ambiance_1": "S09", "offer_1": "S13",
    "ambiance_2": "S07", "evidence_2": "S03", "evidence_demo": "S18"},
    "numbers": {"price": "49.9", "offer": "前100名送毛肚", "cta_line": "点击定位，马上出发"}})
specs.append({"video_id": "v2_t3_offer_v2", "template": T3, "slots": {
    **t3_base, "evidence_1": "S04", "ambiance_1": "S16", "offer_1": "S17",
    "ambiance_2": "S10", "evidence_2": "S15", "evidence_demo": "S19"},
    "numbers": {"price": "52.9", "offer": "第二份半价", "cta_line": "今晚就来"}})
specs.append({"video_id": "v2_t3_offer_v3", "template": T3, "slots": {
    **t3_base, "evidence_1": "S03", "ambiance_1": "S09", "offer_1": "S13",
    "ambiance_2": "S11", "evidence_2": "S01", "evidence_demo": "S18"},
    "numbers": {"price": "45.9", "offer": "锅底免费续", "cta_line": "导航搜老灶"}})

for s in specs:
    ids = list(s["slots"].values())
    assert len(ids) == len(set(ids)), (s["video_id"], ids)
    assert "S18" in ids or "S19" in ids, s["video_id"]

for s in specs:
    with open(os.path.join(OUT, s["video_id"] + ".json"), "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
        f.write("\n")
print("wrote", len(specs), "specs ->", OUT)
