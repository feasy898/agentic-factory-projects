"""契约 C1–C8 冻结测试：规划 §3 示例样例解析 + 往返序列化 + 冻结规则。

验收口径（T1）：规划 §3 的 8 个示例 JSON 必须逐字可解析，且
`json.loads(model.model_dump_json()) == 示例`（严格往返，字段集一一对应）。
"""

from __future__ import annotations

import json

import pytest
from pydantic import RootModel, ValidationError

from pipeline import contracts as C


# ---------------------------------------------------------------------------
# 规划 §3 的 8 个示例（逐字拷贝，含中文/阿文原文）
# ---------------------------------------------------------------------------

C1_SHOTS = """{"ep":"ep01","fps":25,"dur":92.4,"shots":[
 {"shot_id":"s0003","start":12.0,"end":15.6,"cut":"hard","faces":1}]}"""

C2_UTT = """{"utt_id":"u0007","shot_id":"s0003","start":12.40,"end":14.02,"lang":"zh",
 "speaker":"spk0","char_id":"char_nan","text":"你到底想怎么样？",
 "ocr":{"text":"你到底想怎么样","conf":0.93,"agree":true},
 "words":[{"w":"你","s":12.40,"e":12.52}],
 "emo":{"label":"angry","score":0.81},
 "events":[],"overlap":false,"nonverbal":false,
 "face":{"frontal":true,"closeup":true,"bbox":[120,300,480,760]}}"""

C3_CAST = """{"char_nan":{"name":"程总","aliases":["总裁","他"],"gender":"m",
 "voice_ref":"05_cast/voicebank/char_nan_ref.wav","ref_dur_s":12.0,
 "desc":"男主，世家出身，语气克制但压迫感强",
 "terms":{"en":"Master Cheng","es":"Sr. Cheng","ar":"السيد تشنغ"},
 "consent":{"subject":"团队成员A","form":"05_cast/consent/char_nan.pdf","scope":"比赛演示","date":"2026-09-29"}}}"""

C4_TRANS = """{"utt_id":"u0007","tgt":"en","context":["前两句译文","本句前文"],
 "budget":{"orig_dur":1.62,"lo":1.46,"hi":1.78},
 "candidates":[
  {"text":"What do you actually want?","syl":7,"est_dur":1.51,"src":"mt-core","q":0.88},
  {"text":"What is it that you want?","syl":6,"est_dur":1.38,"src":"mt-core","q":0.86}],
 "chosen":0,"policy":"in-budget-first"}"""

C5_SYNTH = """{"utt_id":"u0007","engine":"dub-tts","voice_ref":"05_cast/voicebank/char_nan_ref.wav",
 "emo_ref":"04_dial/emo_refs/u0007.wav","emo_alpha":0.7,"duration_factor":1.0,
 "text":"What do you actually want?","out":"07_synth/wavs/u0007.wav","expect_dur":1.62,
 "keep_original":false}"""

C6_LIP = """{"utt_id":"u0007","shot_id":"s0003","engine":"lip-fast","priority":"normal",
 "window":[12.40,14.02],"face_track":0}"""

C7_LABELS = """{"service_provider":"<申报主体名称>","content_id":"ep01-en","standard":"GB45438-2025",
 "explicit":{"text":"本内容由AI生成","video":"片头提示字幕≥3s","audio_announce":false},
 "implicit":{"metadata_field":"XMP:aiGeneratedContent","value":"ep01-en|<服务提供者>"},
 "c2pa":"11_labels/c2pa_manifest.json",
 "audio_wm":{"engine":"audmark","payload":"ep01-en","bits":16}}"""

C8_COMPLIANCE = """{"market":"ar-SA","ep":"ep01","findings":[
 {"utt_id":"u0013","rule":"intimacy.visual","sev":"high","t":[61.2,64.0],
  "suggest":"建议淡出或剪短","auto":"flag"}],
 "label_status":{"explicit":"ok","implicit":"ok","c2pa":"ok","audio_wm":"ok"},
 "human_review":["u0013"],"generator":"rule-yaml+LLM"}"""


def assert_roundtrip(model, example_raw: str) -> None:
    """严格往返：模型 → JSON → 模型 恒等，且 JSON 与规划示例逐字段一致。"""
    reparsed = type(model).model_validate_json(model.model_dump_json())
    assert reparsed == model
    assert json.loads(model.model_dump_json()) == json.loads(example_raw)


# ---------------------------------------------------------------------------
# C1 镜头表
# ---------------------------------------------------------------------------

def test_c1_shots_roundtrip():
    sheet = C.ShotSheet.model_validate_json(C1_SHOTS)
    assert sheet.ep == "ep01" and sheet.fps == 25 and sheet.dur == 92.4
    shot = sheet.shots[0]
    assert shot.shot_id == "s0003" and shot.start == 12.0 and shot.end == 15.6
    assert shot.cut == "hard" and shot.faces == 1
    assert_roundtrip(sheet, C1_SHOTS)


def test_c1_duplicate_shot_id_rejected():
    with pytest.raises(ValidationError, match="shot_id 重复"):
        C.ShotSheet.model_validate(
            {"ep": "ep01", "fps": 25, "dur": 10.0,
             "shots": [{"shot_id": "s0", "start": 0.0, "end": 1.0},
                        {"shot_id": "s0", "start": 2.0, "end": 3.0}]}
        )


def test_c1_shot_end_before_start_rejected():
    with pytest.raises(ValidationError):
        C.Shot(start=5.0, end=4.0, cut="hard")


# ---------------------------------------------------------------------------
# C2 核心契约
# ---------------------------------------------------------------------------

def test_c2_utterance_roundtrip():
    utt = C.Utterance.model_validate_json(C2_UTT)
    assert utt.utt_id == "u0007" and utt.shot_id == "s0003"
    assert utt.text == "你到底想怎么样？"          # OCR↔ASR 校对结果（产出口径）
    assert utt.ocr is not None and utt.ocr.conf == 0.93 and utt.ocr.agree is True
    assert utt.words[0].w == "你" and utt.words[0].s == 12.40 and utt.words[0].e == 12.52
    assert utt.emo is not None and utt.emo.label == "angry" and utt.emo.score == 0.81
    assert utt.face is not None and utt.face.frontal and utt.face.closeup
    assert utt.face.bbox == [120, 300, 480, 760]
    assert utt.overlap is False and utt.nonverbal is False and utt.events == []
    assert_roundtrip(utt, C2_UTT)


def test_c2_table_unique_utt_id():
    rows = [json.loads(C2_UTT)]
    C.UtteranceTable.model_validate(rows)  # 单条 OK
    rows.append(dict(rows[0]))
    with pytest.raises(ValidationError, match="utt_id 重复"):
        C.UtteranceTable.model_validate(rows)


def test_c2_time_rounding_3_decimals():
    utt = C.Utterance.model_validate(
        {"utt_id": "u1", "shot_id": "s1", "start": 1.00004, "end": 2.01234, "lang": "zh"}
    )
    assert utt.start == 1.0 and utt.end == 2.012  # 秒值统一 3 位小数


# ---------------------------------------------------------------------------
# C3 角色表
# ---------------------------------------------------------------------------

def test_c3_castbook_roundtrip():
    book = C.CastBook.model_validate_json(C3_CAST)
    ch = book.root["char_nan"]
    assert ch.name == "程总" and ch.gender == "m"
    assert ch.voice_ref == "05_cast/voicebank/char_nan_ref.wav" and ch.ref_dur_s == 12.0
    assert ch.terms["en"] == "Master Cheng" and ch.terms["ar"] == "السيد تشنغ"
    assert ch.consent is not None and ch.consent.subject == "团队成员A"
    assert str(ch.consent.date) == "2026-09-29"
    assert_roundtrip(book, C3_CAST)


def test_c3_gender_enum_rejected():
    with pytest.raises(ValidationError):
        C.Character(name="x", gender="robot", voice_ref="a.wav", ref_dur_s=1.0)


# ---------------------------------------------------------------------------
# C4 翻译
# ---------------------------------------------------------------------------

def test_c4_translation_roundtrip():
    tr = C.Translation.model_validate_json(C4_TRANS)
    assert tr.utt_id == "u0007" and tr.tgt == "en"
    assert tr.budget.orig_dur == 1.62 and tr.budget.lo == 1.46 and tr.budget.hi == 1.78
    assert len(tr.candidates) == 2 and tr.chosen == 0
    assert tr.candidates[0].src == "mt-core" and tr.candidates[0].q == 0.88
    assert tr.policy == "in-budget-first"
    assert_roundtrip(tr, C4_TRANS)


def test_c4_budget_lo_gt_hi_rejected():
    with pytest.raises(ValidationError, match="下界"):
        C.Budget(orig_dur=1.6, lo=1.8, hi=1.7)


def test_c4_chosen_out_of_range_rejected():
    data = json.loads(C4_TRANS)
    data["chosen"] = 5
    with pytest.raises(ValidationError, match="越界"):
        C.Translation.model_validate(data)


def test_c4_table_unique_pair():
    tr = json.loads(C4_TRANS)
    C.TranslationTable.model_validate([tr, {**tr, "tgt": "es"}])  # 同句不同语 OK
    with pytest.raises(ValidationError, match="utt_id, tgt"):
        C.TranslationTable.model_validate([tr, tr])


# ---------------------------------------------------------------------------
# C5 合成计划
# ---------------------------------------------------------------------------

def test_c5_synth_plan_roundtrip():
    item = C.SynthPlanItem.model_validate_json(C5_SYNTH)
    assert item.engine == "dub-tts"
    assert item.voice_ref.endswith("char_nan_ref.wav")
    assert item.emo_ref == "04_dial/emo_refs/u0007.wav"  # 音色/情绪参考分离
    assert item.emo_alpha == 0.7 and item.duration_factor == 1.0
    assert item.expect_dur == 1.62 and item.keep_original is False
    assert_roundtrip(item, C5_SYNTH)


def test_c5_ranges():
    base = json.loads(C5_SYNTH)
    with pytest.raises(ValidationError):
        C.SynthPlanItem.model_validate({**base, "emo_alpha": 1.5})
    with pytest.raises(ValidationError):
        C.SynthPlanItem.model_validate({**base, "duration_factor": 0.3})
    ok = C.SynthPlanItem.model_validate({**base, "emo_alpha": 0.85, "duration_factor": 0.9})
    assert ok.emo_alpha == 0.85 and ok.duration_factor == 0.9


def test_c5_nonverbal_rule_documented():
    # 冻结规则 4：nonverbal 句 keep_original=true 不合成 —— 生产规则由 M7 保证，
    # schema 侧约束 keep_original 显式声明（默认 False）。
    item = C.SynthPlanItem.model_validate({**json.loads(C5_SYNTH), "keep_original": True})
    assert item.keep_original is True


# ---------------------------------------------------------------------------
# C6 口型分流
# ---------------------------------------------------------------------------

def test_c6_lip_plan_roundtrip():
    item = C.LipPlanItem.model_validate_json(C6_LIP)
    assert item.engine == "lip-fast" and item.priority == "normal"
    assert item.window == [12.40, 14.02] and item.face_track == 0
    assert_roundtrip(item, C6_LIP)


def test_c6_engine_enum_and_window_order():
    with pytest.raises(ValidationError):
        C.LipPlanItem.model_validate({**json.loads(C6_LIP), "engine": "lip-xxx"})
    with pytest.raises(ValidationError):
        C.LipPlanItem.model_validate({**json.loads(C6_LIP), "window": [14.0, 12.0]})


def test_c6_lip_eligible_rule():
    """冻结规则 5：正脸 + 近景 + 非重叠 才入口型。"""
    base = json.loads(C2_UTT)
    utt = C.Utterance.model_validate(base)
    assert C.lip_eligible(utt) is True
    assert C.lip_eligible(C.Utterance.model_validate({**base, "overlap": True})) is False
    no_face = {**base, "face": None}
    assert C.lip_eligible(C.Utterance.model_validate(no_face)) is False
    side = {**base, "face": {"frontal": False, "closeup": True, "bbox": [1, 2, 3, 4]}}
    assert C.lip_eligible(C.Utterance.model_validate(side)) is False


# ---------------------------------------------------------------------------
# C7 标识
# ---------------------------------------------------------------------------

def test_c7_labels_roundtrip():
    labels = C.Labels.model_validate_json(C7_LABELS)
    assert labels.standard == "GB45438-2025"
    assert labels.explicit.text == "本内容由AI生成" and labels.explicit.audio_announce is False
    assert labels.implicit.metadata_field == "XMP:aiGeneratedContent"
    assert labels.audio_wm.engine == "audmark" and labels.audio_wm.bits == 16
    assert_roundtrip(labels, C7_LABELS)


def test_c7_bits_frozen_at_16():
    data = json.loads(C7_LABELS)
    data["audio_wm"]["bits"] = 32
    with pytest.raises(ValidationError):
        C.Labels.model_validate(data)


# ---------------------------------------------------------------------------
# C8 合规报告
# ---------------------------------------------------------------------------

def test_c8_compliance_roundtrip():
    rep = C.ComplianceReport.model_validate_json(C8_COMPLIANCE)
    assert rep.market == "ar-SA" and rep.ep == "ep01"
    f = rep.findings[0]
    assert f.utt_id == "u0013" and f.rule == "intimacy.visual"
    assert f.sev == "high" and f.t == [61.2, 64.0] and f.auto == "flag"
    assert rep.label_status.explicit == "ok" and rep.label_status.audio_wm == "ok"
    assert rep.human_review == ["u0013"] and rep.generator == "rule-yaml+LLM"
    assert_roundtrip(rep, C8_COMPLIANCE)


def test_c8_sev_enum_rejected():
    data = json.loads(C8_COMPLIANCE)
    data["findings"][0]["sev"] = "critical"
    with pytest.raises(ValidationError):
        C.ComplianceReport.model_validate(data)


def test_c8_default_label_status_pending():
    rep = C.ComplianceReport(market="en-US", ep="ep01")
    assert rep.label_status.explicit == "pending"
    assert rep.findings == [] and rep.human_review == []


# ---------------------------------------------------------------------------
# 通用冻结行为
# ---------------------------------------------------------------------------

def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        C.ShotSheet.model_validate(
            {"ep": "ep01", "fps": 25, "dur": 1.0, "rogue_field": 1}
        )


def test_utt_end_before_start_rejected():
    with pytest.raises(ValidationError):
        C.Utterance(utt_id="u1", shot_id="s1", start=3.0, end=2.0, lang="zh")


def test_jsonl_io_roundtrip(tmp_path):
    table = C.UtteranceTable.model_validate([json.loads(C2_UTT)])
    path = tmp_path / "04_dial" / "utterances.jsonl"
    assert C.dump_jsonl(path, table) == 1
    back = C.load_jsonl(path, C.UtteranceTable)
    assert isinstance(back, RootModel)
    assert back == table
    utts = C.load_jsonl(path, C.Utterance)
    assert len(utts) == 1 and utts[0] == table.root[0]


def test_load_model_json_roundtrip(tmp_path):
    labels = C.Labels.model_validate_json(C7_LABELS)
    path = tmp_path / "labels.json"
    path.write_text(labels.model_dump_json(), encoding="utf-8")
    assert C.load_model(path, C.Labels) == labels


def test_contract_kinds_registry_complete():
    assert set(C.CONTRACT_KINDS) == {
        "shots", "utterances", "diar", "characters", "translations",
        "synth-plan", "lip-plan", "labels", "compliance",
    }
    codes = {kind: code for kind, (code, _, _) in C.CONTRACT_KINDS.items()}
    assert codes == {
        "shots": "C1", "utterances": "C2", "diar": "C2-pre", "characters": "C3",
        "translations": "C4", "synth-plan": "C5", "lip-plan": "C6",
        "labels": "C7", "compliance": "C8",
    }
