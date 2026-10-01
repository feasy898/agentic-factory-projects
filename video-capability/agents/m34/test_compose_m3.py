"""M3 合成层升级的单测: tpad 补齐 / ASS 回读 / CER 归一化 / 自适应语速 / BGM 合成 / compose_group G6。"""

from __future__ import annotations

import pytest

from src.compose import (
    _int_to_zh,
    build_bgm_argv,
    build_compose_argv,
    compose_g6,
    fit_tts_to_scene,
    format_rate,
    normalize_for_cer,
    parse_ass_dialogues,
    parse_rate,
    plan_compose,
    write_ass,
)
from tests.conftest import requires_ffmpeg

REPO = __import__("pathlib").Path(__file__).resolve().parents[1]


def _template():
    from src.schema import load_template

    return load_template(REPO / "templates" / "narrative" / "product_seeding_25s.json")


# ---------------- tpad hold-last-frame (D-033) ----------------

def test_build_compose_argv_tpad_pads_short_video():
    argv = build_compose_argv(["a.mp4", "color:0x7A1F1F"], [3.0, 3.0], "v.m4a", "s.ass", "o.mp4",
                              video_durations=[1.5625, None])
    fc = argv[argv.index("-filter_complex") + 1]
    expect_pad = f"{3.0 - 1.5625:.3f}"
    assert f"tpad=stop_mode=clone:stop_duration={expect_pad}" in fc
    # tpad 后再 trim 精确对齐幕长; 色卡幕不 tpad
    assert fc.count("tpad") == 1
    assert "trim=duration=3.000,setpts=PTS-STARTPTS" in fc


def test_build_compose_argv_no_tpad_for_long_or_unknown():
    argv = build_compose_argv(["a.mp4", "b.mp4"], [3.0, 2.0], "v.m4a", "s.ass", "o.mp4",
                              video_durations=[6.0, None])
    fc = argv[argv.index("-filter_complex") + 1]
    assert "tpad" not in fc
    assert "[0:v]trim=duration=3.000" in fc and "[1:v]trim=duration=2.000" in fc


def test_build_compose_argv_duration_length_mismatch_raises():
    with pytest.raises(ValueError):
        build_compose_argv(["a.mp4"], [3.0], "v", "s", "o", video_durations=[1.0, 2.0])


# ---------------- ASS 回读 ----------------

def test_parse_ass_dialogues_roundtrip(tmp_path):
    cues = [(0.0, 3.0, "老灶火锅的手切鲜毛肚"), (3.0, 8.0, "只要 39.9元 & 一口上头")]
    p = str(tmp_path / "subs.ass")
    write_ass(cues, p, 1088, 1920)
    assert parse_ass_dialogues(p) == [t for _, _, t in cues]


# ---------------- CER 归一化 (D-034) ----------------

def test_int_to_zh():
    assert _int_to_zh(0) == "零"
    assert _int_to_zh(9) == "九"
    assert _int_to_zh(15) == "十五"
    assert _int_to_zh(39) == "三十九"
    assert _int_to_zh(100) == "一百"
    assert _int_to_zh(105) == "一百零五"
    assert _int_to_zh(1234) == "一千二百三十四"


def test_normalize_for_cer_numbers_and_punct():
    assert normalize_for_cer("今晚只要39.9一位") == "今晚只要三十九点九一位"
    assert normalize_for_cer("Hello, World! 15秒") == "helloworld十五秒"
    # 标点/空白全剥
    assert normalize_for_cer("毛肚，三秒锁鲜。一口上头!") == "毛肚三秒锁鲜一口上头"


def test_rate_parse_format_roundtrip():
    assert parse_rate("-10%") == -10.0
    assert format_rate(-10.0) == "-10%"
    assert format_rate(56.2) == "+56%"
    assert parse_rate(format_rate(7)) == 7.0


def test_normalize_makes_tts_reading_match_script():
    from src.gates.g6_business import cer

    ref = "今晚只要39.9一位，第二份半价，定位要趁早"
    hyp = "今晚只要三十九点九一位 第二份半价 定位要趁早。"  # whisper 风格: 数字转中文+标点
    assert cer(normalize_for_cer(ref), normalize_for_cer(hyp)) == 0.0


# ---------------- 自适应语速 (D-032) ----------------

def test_fit_tts_no_need_to_speed_up():
    calls = []

    def tts(text, path, rate="-10%"):
        calls.append(rate)

    def probe(path):
        return 2.0
    info = fit_tts_to_scene(tts, "短句", "/tmp/x.mp3", 3.0, probe_fn=probe)
    assert calls == ["-10%"]
    assert info["truncated"] is False and info["rate"] == "-10%"
    assert len(info["attempts"]) == 1


def test_fit_tts_speeds_up_to_fit():
    calls = []

    def tts(text, path, rate="-10%"):
        calls.append(rate)

    def probe(path):
        # 模型: normal=4.5s, dur(rate)=4.5/(1+r/100)
        return 4.5 / (1.0 + parse_rate(calls[-1]) / 100.0)

    info = fit_tts_to_scene(tts, "长句", "/tmp/x.mp3", 3.0, probe_fn=probe)
    assert info["truncated"] is False
    assert info["duration_s"] <= 3.0 - 0.10
    assert len(calls) == len(info["attempts"]) and len(calls) >= 2
    assert parse_rate(info["rate"]) > parse_rate("-10%")


def test_fit_tts_cap_reports_truncated():
    calls = []

    def tts(text, path, rate="-10%"):
        calls.append(rate)

    def probe(path):
        return 4.5 / (1.0 + parse_rate(calls[-1]) / 100.0)

    info = fit_tts_to_scene(tts, "长句", "/tmp/x.mp3", 0.5, probe_fn=probe)
    assert info["truncated"] is True
    assert parse_rate(info["rate"]) == 100.0  # 触顶


def test_fit_tts_without_rate_kwarg_single_call():
    calls = []

    def tts(text, path):  # 旧契约: 无 rate
        calls.append(text)

    info = fit_tts_to_scene(tts, "x", "/tmp/x.mp3", 3.0, probe_fn=lambda p: 9.9)
    assert len(calls) == 1
    assert info["truncated"] is True and info["duration_s"] == 9.9


# ---------------- BGM 程序合成 (D-035) ----------------

def test_build_bgm_argv_structure():
    argv = build_bgm_argv(25.0, "bgm.m4a")
    assert argv.count("-f") == 3 and argv.count("lavfi") == 3
    assert any("sine=frequency=196" in a for a in argv)
    fc = argv[argv.index("-filter_complex") + 1]
    assert "amix=inputs=3:normalize=1" in fc and "tremolo" in fc and "lowpass" in fc
    assert argv[-1] == "bgm.m4a" and "-c:a" in argv


# ---------------- compose_group: 自适应 TTS + tpad + G6 (真跑) ----------------

def _tiny_template(tmp_path, narration_a="第一幕"):
    return {
        "template_id": "t_m3",
        "orientation": "portrait",
        "variables": {},
        "numbers": {"price": "9.9"},
        "scenes": [
            {"slot": "s1", "narrative_slot": "n1", "duration_sec": 1.0, "role": "hook",
             "narration": narration_a},
            {"slot": "s2", "narrative_slot": "n2", "duration_sec": 1.0, "role": "cta",
             "background": {"type": "solid", "color": "0x123456"},
             "narration": "只要{price}"},
        ],
    }


@requires_ffmpeg
def test_compose_group_adaptive_tts_tpad_and_g6_pass(tmp_path):
    import subprocess

    import numpy as np
    from src.compose import compose_group
    from src.gen.common import write_frames_mp4

    # 0.5s 视频配 1.0s 幕 → 触发 tpad 补齐
    v1 = tmp_path / "a.mp4"
    write_frames_mp4([np.full((32, 32, 3), 200, dtype="uint8")] * 8, 16, str(v1))

    plan = plan_compose(_tiny_template(tmp_path), {"n1": str(v1)})

    calls = []

    def tts_stub(text, out_path, rate="-10%"):
        calls.append(rate)
        d = max(0.2, 1.35 / (1.0 + parse_rate(rate) / 100.0))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", f"sine=frequency=440:duration={d:.3f}",
                        "-ar", "44100", "-ac", "2", "-f", "wav", out_path],
                       check=True, capture_output=True, text=True, timeout=60)

    narration_full = "".join(plan["narration"])
    out = tmp_path / "final.mp4"
    result = compose_group(plan, str(out), str(tmp_path / "subs.ass"), tts_stub,
                           asr_fn=lambda wav: narration_full)
    assert out.exists()
    # 自适应语速生效(至少一幕加速), 且成片时长≈2.0s
    assert any(parse_rate(t["rate"]) > -10 for t in result["tts"])
    assert all(t["truncated"] is False for t in result["tts"])
    from src.gates.g1_tech import probe

    assert probe(str(out))["duration_s"] == pytest.approx(2.0, abs=0.35)
    # G6: 逐字 + CER=0
    g6 = result["g6"]
    assert g6["passed"] is True and g6["detail"]["subtitle_exact"] is True
    assert g6["detail"]["cer"] == 0.0 and g6["detail"]["asr_skipped"] is False


@requires_ffmpeg
def test_compose_group_g6_cer_fail_reported_not_raised(tmp_path):
    import subprocess

    import numpy as np
    from src.compose import compose_group
    from src.gen.common import write_frames_mp4

    v1 = tmp_path / "a.mp4"
    write_frames_mp4([np.full((32, 32, 3), 200, dtype="uint8")] * 16, 16, str(v1))
    plan = plan_compose(_tiny_template(tmp_path), {"n1": str(v1)})

    def tts_stub(text, out_path, rate="-10%"):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=0.5",
                        "-ar", "44100", "-ac", "2", "-f", "wav", out_path],
                       check=True, capture_output=True, text=True, timeout=60)

    out = tmp_path / "final.mp4"
    result = compose_group(plan, str(out), str(tmp_path / "subs.ass"), tts_stub,
                           asr_fn=lambda wav: "完全无关的转写文本")
    g6 = result["g6"]
    assert g6["passed"] is False and g6["detail"]["subtitle_exact"] is True
    assert g6["detail"]["cer"] > 0.5  # 完全无关转写: CER 可 >1(距离/len(ref))


@requires_ffmpeg
def test_compose_group_asr_error_is_skipped(tmp_path):
    import subprocess

    import numpy as np
    from src.compose import compose_group
    from src.gen.common import write_frames_mp4

    v1 = tmp_path / "a.mp4"
    write_frames_mp4([np.full((32, 32, 3), 200, dtype="uint8")] * 16, 16, str(v1))
    plan = plan_compose(_tiny_template(tmp_path), {"n1": str(v1)})

    def tts_stub(text, out_path, rate="-10%"):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=0.5",
                        "-ar", "44100", "-ac", "2", "-f", "wav", out_path],
                       check=True, capture_output=True, text=True, timeout=60)

    def broken_asr(wav):
        raise RuntimeError("whisper 不可用")

    out = tmp_path / "final.mp4"
    result = compose_group(plan, str(out), str(tmp_path / "subs.ass"), tts_stub, asr_fn=broken_asr)
    assert result["g6"]["passed"] is True  # CER 跳过不阻塞, 逐字项仍硬性通过
    assert result["g6"]["detail"]["asr_skipped"] is True
    assert "whisper 不可用" in result["g6"]["detail"]["asr_error"]


@requires_ffmpeg
def test_compose_g6_subtitle_mismatch_fails(tmp_path):
    import numpy as np
    from src.compose import compose_g6, parse_ass_dialogues, write_ass
    from src.gen.common import write_frames_mp4

    v1 = tmp_path / "a.mp4"
    write_frames_mp4([np.full((32, 32, 3), 200, dtype="uint8")] * 16, 16, str(v1))
    plan = plan_compose(_tiny_template(tmp_path, narration_a="第一幕真实"), {"n1": str(v1)})

    # 故意写入与模板渲染不一致的字幕, compose_g6 应判 fail(不依赖 ffmpeg/ASR)
    wrong_cues = [("不匹配的文案" if i == 0 else t) for i, (_, _, t) in enumerate(plan["cues"])]
    wrong = [(s, e, t) for (s, e, _), t in zip(plan["cues"], wrong_cues)]
    ass = str(tmp_path / "wrong.ass")
    write_ass(wrong, ass, 1088, 1920)
    assert parse_ass_dialogues(ass) != plan["narration"]

    g6 = compose_g6(plan, ass, str(tmp_path / "whatever.mp4"), asr_fn=None)
    assert g6["passed"] is False
    assert g6["detail"]["subtitle_exact"] is False
    diffs = g6["detail"]["subtitle_detail"]["diffs"]
    assert diffs and diffs[0]["expected"] == "第一幕真实" and diffs[0]["actual"] == "不匹配的文案"
    assert g6["detail"]["asr_skipped"] is True
