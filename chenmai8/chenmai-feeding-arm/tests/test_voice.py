"""cs_voice 单元测试（无硬件：ASR 模型用例需显式开启）。

运行（在仓库根执行）::

    .venv/Scripts/python.exe -m pytest tests/test_voice.py -q

覆盖面：
1) 意图解析：五类指令全命中 + 菜名槽位校验 + 干扰句/空句判 unknown；
2) VoiceLink 注入模式：inject_intent/inject_text → poll 取最近意图语义；
3) EnergyVad：静音不触发、语音段完整收口、句首预卷不丢；
4) Speaker：离线渲染 wav（有 SAPI 中文语音时验证，否则跳过）；
5) ASR 端到端冒烟：默认跳过（模型加载 ~1 分钟），设 CS_VOICE_TEST_ASR=1 开启。
"""

from __future__ import annotations

import os

import numpy as np
import pytest

import chengshao.cs_voice as cs_voice
from chengshao.cs_schema import IntentKind

# ---- 1) 意图解析 ----------------------------------------------------------


@pytest.fixture(scope="module")
def parser() -> cs_voice.IntentParser:
    return cs_voice.IntentParser()


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("下一口", "next"),
        ("请下一口。", "next"),
        ("再来一口！", "next"),
        ("等一下", "pause"),
        ("请先等一下，", "pause"),
        ("暂停一下", "pause"),
        ("吃饱了", "done"),
        ("我吃饱了！", "done"),
        ("吃不下了", "done"),
        ("继续", "resume"),
        ("接着喂", "resume"),
        ("你好", "greet"),
        ("我想吃芋泥", "select"),
        ("来点南瓜粥", "select"),
        ("换椰子冻", "select"),
        ("我想吃南瓜粥。", "select"),
    ],
)
def test_intent_hit(parser: cs_voice.IntentParser, text: str, intent: str):
    vi = parser.parse(text)
    assert vi.intent == IntentKind(intent)
    if intent == "select":
        dish = vi.slots.get("dish")
        assert dish in parser.dish_registry
    assert vi.confidence >= 0.7
    assert vi.ts_ns > 0


@pytest.mark.parametrize(
    "text",
    ["", "   ", "今天天气怎么样", "帮我查一下明天几点开会", "xyz123"],
)
def test_intent_unknown(parser: cs_voice.IntentParser, text: str):
    vi = parser.parse(text)
    assert vi.intent == IntentKind.UNKNOWN
    assert vi.slots == {}


def test_intent_priority_done_over_greet(parser: cs_voice.IntentParser):
    """同时含多类关键词时按规则优先级（done > pause > next > resume）。"""
    assert parser.parse("吃饱了先别继续").intent == IntentKind.DONE


def test_intent_select_only_registry_dish(parser: cs_voice.IntentParser):
    """注册表之外的食物词不触发 select（契约：dish ∈ 预注册表）。"""
    assert parser.parse("我想吃火锅").intent == IntentKind.UNKNOWN


def test_intent_custom_registry():
    p = cs_voice.IntentParser(dish_registry=("小米粥",))
    vi = p.parse("我想吃小米粥")
    assert vi.intent == IntentKind.SELECT and vi.slots["dish"] == "小米粥"


# ---- 2) VoiceLink 注入模式 ------------------------------------------------


def test_link_inject_intent_and_poll_latest():
    link = cs_voice.VoiceLink(mic=False)
    a = link.inject_text("下一口")
    b = link.inject_text("等一下")
    got = link.poll()
    assert got is b and got is not a
    assert link.poll() is None  # 清空后无残留


def test_link_inject_empty_poll_none():
    link = cs_voice.VoiceLink(mic=False)
    assert link.poll() is None


def test_link_say_no_crash_without_tts_block():
    link = cs_voice.VoiceLink(mic=False)
    link.say("好的")  # 无输出设备/降级路径都不得抛异常
    link.shutdown()


# ---- 3) EnergyVad ---------------------------------------------------------


def test_vad_silence_then_speech_segment():
    sr = 16000
    vad = cs_voice.EnergyVad(samplerate=sr)
    silence = np.zeros(int(sr * 0.5), dtype=np.float32)
    t = np.arange(int(sr * 0.6), dtype=np.float32) / sr
    speech = (0.3 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)  # 有声段
    tail = np.zeros(int(sr * 0.8), dtype=np.float32)  # 超过 hangover 收口

    assert not vad.feed(silence)
    assert vad.feed(speech)  # 语音中被置位
    assert not vad.feed(tail)  # hangover 后收口
    seg = vad.take_utterance()
    assert seg is not None
    # 句首预卷保证不丢首帧：段长 ≈ 语音 + hangover + 预卷
    assert seg.shape[0] >= int(sr * 0.6)


def test_vad_min_utterance_filtered():
    sr = 16000
    vad = cs_voice.EnergyVad(samplerate=sr, min_utterance_ms=300)
    t = np.arange(int(sr * 0.05), dtype=np.float32) / sr  # 50ms 短促声
    burst = (0.3 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
    vad.feed(burst)
    vad.feed(np.zeros(int(sr * 0.8), dtype=np.float32))
    assert vad.take_utterance() is None  # 不足最短语句时长


# ---- 4) Speaker（离线渲染） -----------------------------------------------

_has_sapi = os.name == "nt"


@pytest.mark.skipif(not _has_sapi, reason="仅 Windows SAPI 环境可验")
def test_tts_synth_to_wav(tmp_path):
    spk = cs_voice.Speaker()
    wav = tmp_path / "confirm.wav"
    assert spk.synth_to_wav("好的，这就为您舀一勺。", wav)
    assert wav.stat().st_size > 44
    import soundfile as sf

    data, sr = sf.read(str(wav))
    assert len(data) / sr > 0.5  # 有实际时长
    spk.shutdown()


# ---- 5) ASR 端到端冒烟（默认跳过，重资源） --------------------------------


@pytest.mark.skipif(
    os.environ.get("CS_VOICE_TEST_ASR") != "1",
    reason="需加载 ASR 模型（~1 分钟）；设 CS_VOICE_TEST_ASR=1 开启",
)
def test_asr_engine_smoke():
    import soundfile as sf
    from pathlib import Path

    wav_dir = Path(__file__).resolve().parents[1] / "chengshao" / "assets" / "voice_samples"
    engine = cs_voice.AsrEngine()
    text = engine.transcribe_file(str(wav_dir / "next_1.wav"))
    assert "下一口" in text
    wave, sr = sf.read(str(wav_dir / "done_1.wav"), dtype="float32")
    assert "吃饱" in engine.transcribe(wave, sr)
