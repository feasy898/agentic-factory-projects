"""合成层: 渲染/时间轴/ASS/argv 纯函数 + 小规模真跑(skipif ffmpeg)。"""

from __future__ import annotations

import pytest

from src.compose import (
    ass_time,
    build_ass_lines,
    build_compose_argv,
    build_cues,
    build_scale_chain,
    build_voice_concat_argv,
    escape_ass_filter_path,
    out_size,
    plan_compose,
    render_narration,
)
from src.schema import load_template
from tests.conftest import requires_ffmpeg

REPO = __import__("pathlib").Path(__file__).resolve().parents[1]


def _template():
    return load_template(REPO / "templates" / "narrative" / "product_seeding_25s.json")


# ---------------- 文本与数字纪律 ----------------

def test_render_narration_uses_variables_and_numbers():
    scenes = [{"narration": "{store}的{p} 只要{price}"}]
    out = render_narration(scenes, {"store": "老灶", "p": "毛肚"}, {"price": "39.9"})
    assert out == ["老灶的毛肚 只要39.9"]


def test_render_narration_undefined_var_raises():
    with pytest.raises(KeyError):
        render_narration([{"narration": "{price}元"}], {}, {})


def test_numbers_are_strings_in_render():
    out = render_narration([{"narration": "价{price}"}], {}, {"price": 39.9})
    assert out == ["价39.9"]


# ---------------- 时间轴与 ASS ----------------

def test_build_cues_cumulative():
    cues = build_cues([3, 5, 4], ["a", "b", "c"])
    assert cues == [(0.0, 3.0, "a"), (3.0, 8.0, "b"), (8.0, 12.0, "c")]


def test_ass_time_format():
    assert ass_time(0) == "0:00:00.00"
    assert ass_time(65.5) == "0:01:05.50"
    assert ass_time(3661.25) == "1:01:01.25"
    assert ass_time(3.999) == "0:00:04.00"


def test_build_ass_lines_structure():
    cues = [(0.0, 3.0, "毛肚来了"), (3.0, 8.0, "只要 39.9")]
    lines = build_ass_lines(cues, 1088, 1920)
    assert "PlayResX: 1088" in lines and "PlayResY: 1920" in lines
    assert any("Noto Sans CJK SC" in l for l in lines)
    dialogues = [l for l in lines if l.startswith("Dialogue:")]
    assert len(dialogues) == 2
    assert dialogues[0].startswith("Dialogue: 0,0:00:00.00,0:00:03.00,Default,")
    assert "毛肚来了" in dialogues[0]
    assert "只要 39.9" in dialogues[1]


def test_ass_font_default():
    lines = build_ass_lines([(0, 1, "x")], 1088, 1920)
    style = next(l for l in lines if l.startswith("Style:"))
    assert style.startswith("Style: Default,Noto Sans CJK SC,64,")


def test_escape_ass_filter_path():
    assert escape_ass_filter_path("/tmp/a.ass") == "/tmp/a.ass"
    assert escape_ass_filter_path("a:1.ass") == "a\\:1.ass"
    assert escape_ass_filter_path("C:\\x\\a.ass") == "C\\:/x/a.ass"


# ---------------- 画幅与 scale 链 ----------------

def test_out_size():
    assert out_size("portrait") == (1088, 1920)
    assert out_size("landscape") == (1920, 1088)
    with pytest.raises(ValueError):
        out_size("square")


def test_scale_chain():
    c = build_scale_chain(1088, 1920)
    assert c.startswith("scale=1088:1920:force_original_aspect_ratio=decrease")
    assert "pad=1088:1920" in c and "setsar=1" in c


# ---------------- 终混 argv ----------------

def test_build_compose_argv_hard_cut_and_burn():
    argv = build_compose_argv(["a.mp4", "b.mp4"], [3.0, 5.0], "voice.m4a", "subs.ass", "out.mp4")
    fc = argv[argv.index("-filter_complex") + 1]
    assert "[0:v]trim=duration=3.000" in fc and "[1:v]trim=duration=5.000" in fc
    assert "concat=n=2:v=1:a=0[vcat]" in fc
    assert "ass=subs.ass[vout]" in fc
    assert fc.count("force_original_aspect_ratio=decrease") == 2
    assert argv[argv.index("-map") + 1] == "[vout]"
    assert "libx264" in argv and argv[argv.index("-r") + 1] == "16"
    assert argv[-1] == "out.mp4"
    # 无 BGM: 音频直通
    assert "sidechaincompress" not in fc


def test_build_compose_argv_bgm_ducking():
    argv = build_compose_argv(["a.mp4"], [3.0], "voice.m4a", "s.ass", "o.mp4", bgm_path="bgm.m4a")
    fc = argv[argv.index("-filter_complex") + 1]
    assert "sidechaincompress" in fc and "amix" in fc
    assert f"volume={10 ** (-12 / 20):.4f}" in fc  # ≈0.2512 (-12dB)


def test_build_compose_argv_color_sentinel_for_cta():
    argv = build_compose_argv(["a.mp4", "color:0x7A1F1F"], [3.0, 3.0], "v.m4a", "s.ass", "o.mp4")
    i = argv.index("-f")
    assert argv[i + 1] == "lavfi"
    assert "-i" == argv[i + 2]
    assert "color=c=0x7A1F1F:s=1088x1920:r=16:d=3.000" in argv[i + 3]


def test_build_compose_argv_landscape():
    argv = build_compose_argv(["a.mp4"], [2.0], "v.m4a", "s.ass", "o.mp4", orientation="landscape")
    fc = argv[argv.index("-filter_complex") + 1]
    assert "scale=1920:1088" in fc


def test_build_compose_argv_mismatch_raises():
    with pytest.raises(ValueError):
        build_compose_argv(["a.mp4"], [1.0, 2.0], "v", "s", "o")
    with pytest.raises(ValueError):
        build_compose_argv([], [], "v", "s", "o")


def test_build_voice_concat_argv():
    argv = build_voice_concat_argv(["v0.mp3", "v1.mp3"], "voice.m4a", [3.0, 4.0])
    fc = argv[argv.index("-filter_complex") + 1]
    assert "atrim=duration=3.000" in fc and "apad=whole_dur=4.000" in fc
    assert "concat=n=2:v=0:a=1[aout]" in fc
    assert argv[-1] == "voice.m4a"
    with pytest.raises(ValueError):
        build_voice_concat_argv(["a.mp3"], "o.m4a", [1.0, 2.0])


# ---------------- 合成计划(真实模板) ----------------

def test_plan_compose_with_real_template():
    t = _template()
    plan = plan_compose(t, {
        "hook_product": "h.mp4",
        "evidence_product": "e.mp4",
        "ambiance_scene": "a.mp4",
    })
    assert plan["total_duration"] == 25.0
    assert plan["video_paths"][0] == "h.mp4"
    assert plan["video_paths"][1] == "e.mp4" == plan["video_paths"][2] == plan["video_paths"][3]
    assert plan["video_paths"][-1] == "color:0x7A1F1F"  # CTA 贴片程序渲染
    assert len(plan["cues"]) == 6
    assert plan["numbers_used"]["price"] == "39.9"
    # 数字只出现在字幕文本, 不进入任何视频路径
    assert all("39.9" not in p for p in plan["video_paths"])
    assert any("39.9" in text for _, _, text in plan["cues"])


def test_plan_compose_scene_slot_overrides_narrative_slot():
    t = _template()
    plan = plan_compose(t, {
        "hook": "by_slot.mp4",          # scene.slot 优先
        "evidence_product": "e.mp4",
        "ambiance_scene": "a.mp4",
    })
    assert plan["video_paths"][0] == "by_slot.mp4"


def test_plan_compose_missing_slot_raises():
    t = _template()
    with pytest.raises(ValueError) as e:
        plan_compose(t, {"hook_product": "h.mp4"})
    assert "evidence_1" in str(e.value)


# ---------------- 口播时间轴与 TTS 对齐 ----------------

def test_cues_match_voice_concat_durations():
    t = _template()
    plan = plan_compose(t, {"hook_product": "h.mp4", "evidence_product": "e.mp4", "ambiance_scene": "a.mp4"})
    assert [round(c[1] - c[0], 3) for c in plan["cues"]] == [round(d, 3) for d in plan["scene_durations"]]
    assert abs(sum(plan["scene_durations"]) - plan["total_duration"]) < 1e-6


# ---------------- compose_group 端到端(小样本真跑) ----------------

@requires_ffmpeg
def test_compose_group_end_to_end_tiny(tmp_path):
    import subprocess

    import numpy as np
    from src.gates.g1_tech import probe
    from src.compose import compose_group
    from src.gen.common import write_frames_mp4

    v1 = tmp_path / "a.mp4"
    write_frames_mp4([np.full((32, 32, 3), 200, dtype="uint8")] * 16, 16, str(v1))

    template = {
        "template_id": "t_test",
        "orientation": "portrait",
        "variables": {},
        "numbers": {"price": "9.9"},
        "scenes": [
            {"slot": "s1", "narrative_slot": "n1", "duration_sec": 1.0, "role": "hook",
             "narration": "第一幕"},
            {"slot": "s2", "narrative_slot": "n2", "duration_sec": 1.0, "role": "cta",
             "background": {"type": "solid", "color": "0x123456"},
             "narration": "只要{price}"},
        ],
    }
    plan = plan_compose(template, {"n1": str(v1)})

    def tts_stub(text, out_path):
        argv = ["ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5",
                "-ar", "44100", "-ac", "2", "-f", "wav", out_path]
        subprocess.run(argv, check=True, capture_output=True, text=True, timeout=60)

    out = tmp_path / "final.mp4"
    result = compose_group(plan, str(out), str(tmp_path / "subs.ass"), tts_stub)
    assert out.exists() and result["path"] == str(out)
    info = probe(str(out))
    assert info["duration_s"] == pytest.approx(2.0, abs=0.3)
    assert (out.with_name("subs.ass")).exists()
