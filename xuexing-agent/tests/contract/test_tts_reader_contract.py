"""契约：tts_reader —— 语音读题（题干+选项 → 确定性朗读文本 → 注入 TTS → 音频缓存）。

夹具自封闭、**全 mock 零网络**：TTS 用脚本化 MockTTS（记录调用、按调用序回字节），
MMClient 走 MockTransport。全部文本/字节/摘要条款为手算可复核的闭式值
（sha256 实测于 CPython 3.12 x64）。跨模块锁定（mm_client.TTS_VOICE/TTS_FORMAT/
MODEL_TTS / omr_sheet.parse_option 标签列）在测试内 import 对方模块断言，
被测模块间零 import。
"""
import copy
import hashlib
import json
import os
from collections import UserDict

import pytest

from xuexing.tts_reader import (
    AUDIO_FORMAT,
    DEFAULT_VOICE,
    ITEM_TYPES,
    READER_VERSION,
    ItemAudio,
    TTSError,
    build_reading_text,
    option_labels,
    read_paper,
    synthesize_item,
)
from xuexing.types import Paper


# 哨兵环境：非机密占位值，仅供 MMClient 的 mock 传输层读取，不对应任何真实凭据
_SENTINEL_ENV = {"XX_LLM_API_KEY": "sentinel-token-1"}


# ---------- 自封闭小夹具 ----------

class _DuckItem:
    def __init__(self, item_id, item_type, stem, answer="", options=None):
        self.id = item_id
        self.item_type = item_type
        self.stem = stem
        self.answer = answer
        self.options = list(options or [])
        self.solution = f"SOL-{item_id}"


class _DuckBank:
    def __init__(self, items):
        self._items = list(items)

    def items(self):
        return list(self._items)


class MockTTS:
    """脚本化 mock TTS：按调用序回默认字节（或按文本查表），记录每次调用（零网络）。"""

    def __init__(self, replies=None):
        self.replies = dict(replies or {})  # text -> bytes
        self.calls = []

    def tts(self, text, *, voice, response_format):
        self.calls.append({"text": text, "voice": voice,
                           "response_format": response_format})
        return self.replies.get(text, b"MOCKMP3-%d" % len(self.calls))


class _NoTTS:
    pass


C1 = _DuckItem("c1", "choice", "计算 1+1 等于多少？", answer="A",
               options=["A. 2", "B. 3"])
C2 = _DuckItem("c2", "choice", "比 5 小的数是哪个？", answer="a",
               options=["a. 3", "b．7"])          # 小写显式标签 -> 归一大写
C3 = _DuckItem("c3", "choice", "3 的相反数", answer="A",
               options=["A. -3", "B. 3"])          # stem 无句末标点
F1 = _DuckItem("f1", "fill", "比 -3 大的最小整数是多少", answer="-2")
F2 = _DuckItem("f2", "fill", "计算 3-5 的值", answer="-2")
S1 = _DuckItem("s1", "solve", "解方程：2x + 1 = 7，写出完整过程。", answer="x=3")
BANK = _DuckBank([C1, C2, F1, S1])

SECTIONS = [
    {"kp_id": "k1", "kp_name": "有理数", "item_ids": ["c1", "f1"]},
    {"kp_id": "k2", "kp_name": "相反数", "item_ids": ["s1", "c2"]},
]
# 卷面题序（omr_sheet/paper_layout/mm_ingest 同编号语义）：c1, f1, s1, c2

# 朗读文本闭式值（拼接规则见规格 §3：句末标点 。！？.!? 不重复，否则插「。」）
T_C1 = "计算 1+1 等于多少？选项A：2。选项B：3。"
T_C2 = "比 5 小的数是哪个？选项A：3。选项B：7。"
T_C3 = "3 的相反数。选项A：-3。选项B：3。"
T_F1 = "比 -3 大的最小整数是多少。"
T_F2 = "计算 3-5 的值。"
T_S1 = "解方程：2x + 1 = 7，写出完整过程。"
TEXTS = {"c1": T_C1, "c2": T_C2, "f1": T_F1, "s1": T_S1}

# 音频字节闭式摘要（CPython 3.12 x64 实测）
SHA_CACHED = "0557b8681c2b60b8ef055fa2ed4f0d338f6a35b2c178f52778380523d0a0d883"  # b"CACHED-AUDIO"
SHA_MOCK1 = "3717d001a8459c142e922dd83db50502df86351683e9c53c14eeec95ecebdfe0"   # b"MOCKMP3-1"
SHA_STEP = "d04611afb764444ff93fa966caf4e5b612a7f8324f28974864033095d69b4d43"    # b"ID3MOCKMP3"


def _paper(sections=SECTIONS, item_ids=None, paper_id="paper-88", title="七年级诊断卷"):
    return Paper(
        paper_id=paper_id,
        title=title,
        blueprint={},
        item_ids=item_ids if item_ids is not None else
        [iid for s in sections for iid in s["item_ids"]],
        sections=[dict(s) for s in sections],
    )


def _voice_keys(ids, voice=DEFAULT_VOICE):
    return {(iid, voice) for iid in ids}


# ---------- I1 常量冻结 + 跨模块锁定 ----------

def test_frozen_constants():
    assert READER_VERSION == "1"
    assert DEFAULT_VOICE == "linjiajiejie"
    assert AUDIO_FORMAT == "mp3"
    assert ITEM_TYPES == ("choice", "fill", "solve")
    assert issubclass(TTSError, ValueError)


def test_voice_and_format_match_mm_client():
    from xuexing.mm_client import TTS_FORMAT, TTS_VOICE

    assert DEFAULT_VOICE == TTS_VOICE
    assert AUDIO_FORMAT == TTS_FORMAT


# ---------- option_labels（与 omr_sheet.parse_option 跨模块锁定） ----------

def test_option_labels_closed_forms():
    assert option_labels(C1) == ["A", "B"]
    assert option_labels(C2) == ["A", "B"]            # 小写显式标签归一大写
    mixed = _DuckItem("m", "choice", "选哪个？",
                      options=["A. 1", "b. 2", "C）3", "d．4"])
    assert option_labels(mixed) == ["A", "B", "C", "D"]
    bare = _DuckItem("b", "choice", "选哪个？", options=["1", "2"])  # 无显式标签按位回退
    assert option_labels(bare) == ["A", "B"]


def test_option_labels_guards():
    one = _DuckItem("x", "choice", "s", options=["A. 1"])
    many = _DuckItem("x", "choice", "s",
                     options=[f"{chr(65 + i)}. v{i}" for i in range(27)])
    dup = _DuckItem("x", "choice", "s", options=["A. 1", "A. 2"])
    blank = _DuckItem("x", "choice", "s", options=["A. 1", "   "])
    nonstr = _DuckItem("x", "choice", "s", options=["A. 1", 5])
    none_opts = _DuckItem("x", "choice", "s")
    none_opts.options = None
    noattr = _DuckItem("x", "choice", "s")  # options=[] -> <2
    del noattr.options                       # 属性缺失 -> TTSError
    for item in (one, many, dup, blank, nonstr, none_opts, noattr):
        with pytest.raises(TTSError):
            option_labels(item)


def test_option_labels_matches_omr_sheet_parse_option():
    from xuexing.omr_sheet import parse_option

    for item in (C1, C2):
        assert option_labels(item) == [
            parse_option(o, i)[0] for i, o in enumerate(item.options)]


# ---------- build_reading_text（I2 闭式 + 纯度 + 拼接规则） ----------

def test_reading_text_choice_closed_forms():
    assert build_reading_text(C1) == T_C1
    assert build_reading_text(C2) == T_C2
    assert build_reading_text(C3) == T_C3
    assert build_reading_text(C1) == build_reading_text(C1)  # 同输入同字节


def test_reading_text_fill_solve_closed_forms():
    assert build_reading_text(F1) == T_F1            # 无句末标点 -> 补「。」
    assert build_reading_text(F2) == T_F2
    assert build_reading_text(S1) == T_S1            # 句末已有「。」不重复
    ascii_dot = _DuckItem("f3", "fill", "Compute 3-5.")
    assert build_reading_text(ascii_dot) == "Compute 3-5."   # ASCII . 亦算句末
    colon = _DuckItem("f4", "fill", "列式计算：")
    assert build_reading_text(colon) == "列式计算：。"        # ：非句末 -> 插入


def test_reading_text_hygiene_no_answer_material():
    for item, text in ((C1, T_C1), (C2, T_C2), (F1, T_F1), (F2, T_F2), (S1, T_S1)):
        assert f"SOL-{item.id}" not in text           # 解析绝不出现
    for item, text, leaked in ((C1, T_C1, "A. 2"), (F1, T_F1, "-2"),
                               (F2, T_F2, "-2"), (S1, T_S1, "x=3")):
        assert leaked not in text                     # fill/solve 答案绝不出现
    assert "选项A：2" in T_C1 and "选项B：3" in T_C1  # 选项正文按「选项L：」结构出现
    assert T_C1.count("？") == 1                       # 句末标点不重复


def test_reading_text_guards():
    blank_stem = _DuckItem("x", "fill", "   ")
    nonstr_stem = _DuckItem("x", "fill", 42)
    no_type = _DuckItem("x", "fill", "stem")
    no_type.item_type = None
    bad_type = _DuckItem("x", "essay", "stem")
    no_id = _DuckItem("x", "fill", "stem")
    del no_id.id
    empty_body = _DuckItem("x", "choice", "s", options=["A. 2", "B. "])  # 标签后正文空白
    for item in (blank_stem, nonstr_stem, no_type, bad_type, no_id, empty_body):
        with pytest.raises(TTSError):
            build_reading_text(item)
    one_opt = _DuckItem("x", "choice", "s", options=["A. 1"])
    with pytest.raises(TTSError):
        build_reading_text(one_opt)


# ---------- synthesize_item（I3 缓存 + I4 失败纪律） ----------

def test_synthesize_miss_calls_tts_once_exact_shape():
    tts = MockTTS()
    aud = synthesize_item(C1, tts)
    assert isinstance(aud, ItemAudio)
    assert (aud.item_id, aud.voice, aud.text, aud.from_cache) == (
        "c1", DEFAULT_VOICE, T_C1, False)
    assert aud.audio == b"MOCKMP3-1"
    assert tts.calls == [{"text": T_C1, "voice": DEFAULT_VOICE,
                          "response_format": "mp3"}]


def test_synthesize_cache_hit_zero_tts_calls():
    tts = MockTTS()
    cache = {("c1", DEFAULT_VOICE): b"CACHED-AUDIO"}
    aud = synthesize_item(C1, tts, cache=cache)
    assert aud.audio == b"CACHED-AUDIO" and aud.from_cache is True
    assert aud.text == T_C1                            # text 恒重建
    assert tts.calls == []                             # 命中零次合成


def test_synthesize_cache_key_is_item_id_plus_voice():
    tts = MockTTS()
    cache = {("c1", "other-voice"): b"OTHER"}
    aud = synthesize_item(C1, tts, cache=cache)        # 默认 voice 未命中
    assert aud.audio == b"MOCKMP3-1" and aud.from_cache is False
    assert cache == {("c1", "other-voice"): b"OTHER",
                     ("c1", DEFAULT_VOICE): b"MOCKMP3-1"}
    # voice 按原样使用（不 strip）：不同 voice 串是不同缓存键
    tts2 = MockTTS()
    cache2 = {}
    aud2 = synthesize_item(C1, tts2, voice=" vx ", cache=cache2)
    assert aud2.voice == " vx " and aud2.audio == b"MOCKMP3-1"
    assert tts2.calls[0]["voice"] == " vx "
    assert set(cache2) == {("c1", " vx ")}             # voice 串原样进键


def test_synthesize_cache_roundtrip_and_none_isolation():
    tts = MockTTS()
    cache = {}
    first = synthesize_item(C1, tts, cache=cache)
    second = synthesize_item(C1, tts, cache=cache)
    assert first.from_cache is False and second.from_cache is True
    assert second.audio == first.audio == b"MOCKMP3-1"
    assert len(tts.calls) == 1                         # 回合后零新调用
    # cache=None：两次独立调用各自未命中（无跨调用持久化）
    tts2 = MockTTS()
    assert synthesize_item(C1, tts2).from_cache is False
    assert synthesize_item(C1, tts2).from_cache is False
    assert len(tts2.calls) == 2


def test_synthesize_accepts_duck_mutable_mapping():
    tts = MockTTS()
    cache = UserDict({("c1", DEFAULT_VOICE): b"CACHED-AUDIO"})
    aud = synthesize_item(C1, tts, cache=cache)
    assert aud.from_cache is True and aud.audio == b"CACHED-AUDIO"
    assert tts.calls == []


def test_synthesize_bad_audio_not_cached():
    tts = MockTTS(replies={T_C1: b""})
    cache = {}
    with pytest.raises(TTSError):
        synthesize_item(C1, tts, cache=cache)
    assert cache == {}                                 # 空字节不回填
    tts2 = MockTTS(replies={T_C1: "not-bytes"})
    with pytest.raises(TTSError):
        synthesize_item(C1, tts2, cache=(cache2 := {}))
    assert cache2 == {}
    assert len(tts.calls) == 1 and len(tts2.calls) == 1


def test_synthesize_tts_exception_propagates_cache_untouched():
    class _Boom:
        def tts(self, text, *, voice, response_format):
            raise RuntimeError("tts down")

    cache = {}
    with pytest.raises(RuntimeError, match="tts down"):
        synthesize_item(C1, _Boom(), cache=cache)
    assert cache == {}


def test_synthesize_guards_zero_calls():
    tts = MockTTS()
    bad_calls = [
        lambda: synthesize_item(C1, tts, voice=""),
        lambda: synthesize_item(C1, tts, voice="   "),
        lambda: synthesize_item(C1, tts, voice=5),
        lambda: synthesize_item(C1, tts, voice=None),
        lambda: synthesize_item(C1, _NoTTS()),
        lambda: synthesize_item(C1, object()),
        lambda: synthesize_item(C1, "tts"),
        lambda: synthesize_item(C1, tts, cache=5),
        lambda: synthesize_item(C1, tts, cache=["x"]),   # list 非 Mapping
        lambda: synthesize_item(C1, tts, cache="x"),
    ]
    for bad in bad_calls:
        with pytest.raises(TTSError):
            bad()
    assert tts.calls == []                             # 全部守卫失败零出网


def test_item_audio_to_dict_shape():
    aud = ItemAudio(item_id="c1", voice=DEFAULT_VOICE, text=T_C1,
                    audio=b"CACHED-AUDIO", from_cache=True)
    expected = {
        "item_id": "c1", "voice": "linjiajiejie", "format": "mp3", "text": T_C1,
        "audio_size": 12, "audio_sha256": SHA_CACHED, "from_cache": True,
    }
    assert aud.to_dict() == expected
    assert list(aud.to_dict()) == list(expected)       # 键序冻结
    assert hashlib.sha256(b"CACHED-AUDIO").hexdigest() == SHA_CACHED  # 独立复核
    assert aud.audio == b"CACHED-AUDIO"                # 音频字节本身不序列化
    json.dumps(aud.to_dict(), ensure_ascii=False)      # JSON 可序列化


# ---------- read_paper（I5 卷面语义 + 共享缓存） ----------

def test_read_paper_end_to_end_order_and_calls():
    tts = MockTTS()
    audios = read_paper(_paper(), BANK, tts)
    assert [a.item_id for a in audios] == ["c1", "f1", "s1", "c2"]  # 卷面题序
    assert [a.text for a in audios] == [T_C1, T_F1, T_S1, T_C2]
    assert [a.audio for a in audios] == [
        b"MOCKMP3-1", b"MOCKMP3-2", b"MOCKMP3-3", b"MOCKMP3-4"]
    assert all(a.from_cache is False for a in audios)
    assert [c["text"] for c in tts.calls] == [T_C1, T_F1, T_S1, T_C2]
    assert all(c["voice"] == DEFAULT_VOICE and c["response_format"] == "mp3"
               for c in tts.calls)


def test_read_paper_shared_cache_duplicate_item():
    tts = MockTTS()
    sections = [{"kp_id": "a", "kp_name": "甲", "item_ids": ["c1", "f1"]},
                {"kp_id": "b", "kp_name": "乙", "item_ids": ["c1", "s1"]}]
    audios = read_paper(_paper(sections=sections), BANK, tts)
    assert [a.item_id for a in audios] == ["c1", "f1", "c1", "s1"]
    assert [a.from_cache for a in audios] == [False, False, True, False]
    assert audios[2].audio == audios[0].audio == b"MOCKMP3-1"
    assert len(tts.calls) == 3                         # 同题只合成一次


def test_read_paper_empty_sections_fallback_item_ids():
    tts = MockTTS()
    audios = read_paper(_paper(sections=[], item_ids=["f1", "c1"]), BANK, tts)
    assert [a.item_id for a in audios] == ["f1", "c1"]
    assert [a.text for a in audios] == [T_F1, T_C1]


def test_read_paper_second_pass_zero_calls_via_shared_cache():
    tts1 = MockTTS()
    cache = {}
    first = read_paper(_paper(), BANK, tts1, cache=cache)
    assert set(cache) == _voice_keys(["c1", "f1", "s1", "c2"])
    tts2 = MockTTS()
    second = read_paper(_paper(), BANK, tts2, cache=cache)
    assert tts2.calls == []                            # 二次读卷零合成
    assert [a.from_cache for a in second] == [True] * 4
    assert [(a.item_id, a.text, a.audio) for a in second] == \
           [(a.item_id, a.text, a.audio) for a in first]


def test_read_paper_guards_zero_calls():
    tts = MockTTS()
    bad_calls = [
        lambda: read_paper(_paper(), BANK, tts, voice=""),
        lambda: read_paper(_paper(), BANK, tts, voice=5),
        lambda: read_paper(_paper(), BANK, _NoTTS()),
        lambda: read_paper(_paper(), BANK, tts, cache=5),
        lambda: read_paper(_paper(), BANK, tts, cache=["x"]),
        lambda: read_paper(_NoTTS(), BANK, tts),
        lambda: read_paper(Paper(paper_id=None, title="t", blueprint={},
                                 item_ids=["c1"], sections=[]), BANK, tts),
        lambda: read_paper(Paper(paper_id="p", title=5, blueprint={},
                                 item_ids=["c1"], sections=[]), BANK, tts),
        lambda: read_paper(Paper(paper_id="p", title="t", blueprint={},
                                 item_ids=["c1"], sections="x"), BANK, tts),
        lambda: read_paper(Paper(paper_id="p", title="t", blueprint={},
                                 item_ids=None, sections=[]), BANK, tts),
        lambda: read_paper(Paper(paper_id="p", title="t", blueprint={},
                                 item_ids=[], sections=[42]), BANK, tts),
        lambda: read_paper(Paper(paper_id="p", title="t", blueprint={},
                                 item_ids=[], sections=[{"item_ids": "c1"}]),
                           BANK, tts),
        lambda: read_paper(Paper(paper_id="p", title="t", blueprint={},
                                 item_ids=[], sections=[{"item_ids": [5]}]),
                           BANK, tts),
        lambda: read_paper(_paper(sections=[{"item_ids": ["c1", "zz"]}]),
                           BANK, tts),                             # 卷内未知题
        lambda: read_paper(_paper(), _NoTTS(), tts),               # bank 无 items()
        lambda: read_paper(_paper(), _DuckBank([C1, C1]), tts),    # bank 重复 id
        lambda: read_paper(_paper(), _DuckBank(
            [_DuckItem("c1", "essay", "s"), F1]), tts),            # 未知题型
        lambda: read_paper(_paper(), _DuckBank(
            [_DuckItem("c1", "choice", "s", options=["A. 1"]), F1]), tts),  # choice 单选项
        lambda: read_paper(_paper(), _DuckBank(
            [_DuckItem("c1", "choice", "s", options=["A. 2", "B. "]), F1]), tts),  # 空正文
        lambda: read_paper(Paper(paper_id="p", title="t", blueprint={},
                                 item_ids=[], sections=[{"item_ids": []}]),
                           BANK, tts),                             # 空卷（空节）
        lambda: read_paper(_paper(sections=[], item_ids=[]), BANK, tts),  # 空卷
    ]
    for bad in bad_calls:
        with pytest.raises(TTSError):
            bad()
    assert tts.calls == []                             # 卷面守卫失败零出网


def test_read_paper_determinism_and_inputs_not_mutated():
    sections_snapshot = copy.deepcopy(SECTIONS)
    items_snapshot = [(it.id, it.item_type, it.stem, it.answer, list(it.options))
                      for it in (C1, C2, F1, S1)]
    cache = {}
    a = [x.to_dict() for x in read_paper(_paper(), BANK, MockTTS(), cache=cache)]
    b = [x.to_dict() for x in read_paper(_paper(), BANK, MockTTS())]
    assert a == b                                      # 同输入同输出
    assert SECTIONS == sections_snapshot
    assert [(it.id, it.item_type, it.stem, it.answer, list(it.options))
            for it in (C1, C2, F1, S1)] == items_snapshot
    assert set(cache) == _voice_keys(["c1", "f1", "s1", "c2"])  # cache 按设计回填


# ---------- I7 跨模块端到端（MMClient + MockTransport 全 mock） ----------

def test_end_to_end_mm_client_mock_transport():
    from xuexing.mm_client import ENDPOINTS, MODEL_TTS, MMClient, MockTransport

    mt = MockTransport(replies={"tts": (200, b"ID3MOCKMP3")})
    client = MMClient(mt, env=dict(_SENTINEL_ENV),
                      resolve=lambda host: ["93.184.216.34"])
    audios = read_paper(_paper(), BANK, client)
    assert len(mt.calls) == 4
    assert all(c["url"] == ENDPOINTS["tts"] for c in mt.calls)
    assert mt.calls[0]["headers"]["Content-Type"] == "application/json"
    expected_payload = {"model": MODEL_TTS, "input": T_C1,
                        "voice": DEFAULT_VOICE, "response_format": "mp3"}
    assert json.loads(mt.calls[0]["body"]) == expected_payload
    assert json.loads(mt.calls[3]["body"]) == dict(expected_payload, input=T_C2)
    assert [a.audio for a in audios] == [b"ID3MOCKMP3"] * 4
    assert audios[0].to_dict()["audio_sha256"] == SHA_STEP


# ---------- 冒烟门（env-gated；默认 skip，契约套件零网络） ----------

def _smoke_enabled() -> bool:
    if os.environ.get("XX_MM_SMOKE") != "1":
        return False
    try:
        from xuexing.mm_client import LLMError, api_key
        api_key()
    except Exception:
        return False
    return True


@pytest.mark.skipif(not _smoke_enabled(),
                    reason="冒烟默认关闭：需 XX_MM_SMOKE=1 且环境含 XX_LLM_API_KEY/STEPFUN_API_KEY")
def test_smoke_real_stepfun_tts():
    from xuexing.mm_client import HttpTransport

    from xuexing.mm_client import MMClient

    client = MMClient(HttpTransport())  # key/解析走真实环境（默认缺省参数）
    aud = synthesize_item(C1, client)
    assert aud.text == T_C1 and aud.from_cache is False
    assert isinstance(aud.audio, bytes) and len(aud.audio) > 0
