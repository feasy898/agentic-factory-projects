"""B1 契约冻结测试（2026-09-28）：字级时间窗、utt_id 公式、替换写盘原语、diar schema。

对应 contracts.py 冻结规则 7–10 与 docs/b1_contract_notes.md；
审照 _reviews/drama-b0-review.md §B（分离/ASR/对齐/说话人四段交接未冻结）。
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from pipeline import contracts as C
from pipeline.scaffold import EXPECTED_FILES

from tests.test_contracts import C2_UTT


def _utt(**over):
    base = json.loads(C2_UTT)
    return C.Utterance.model_validate({**base, **over})


# ---------------------------------------------------------------------------
# ③ 字级时间校验：utt.start ≤ word.s ≤ word.e ≤ utt.end 且按时间排序
# ---------------------------------------------------------------------------

def test_word_outside_utterance_window_rejected():
    # 字起点早于句起点 → 拒绝
    with pytest.raises(ValidationError, match="越出句窗"):
        _utt(words=[{"w": "你", "s": 12.0, "e": 12.52}])
    # 字终点晚于句终点 → 拒绝
    with pytest.raises(ValidationError, match="越出句窗"):
        _utt(words=[{"w": "你", "s": 12.40, "e": 14.50}])
    # 字内倒挂（e < s）仍被 Word 自身校验拒绝
    with pytest.raises(ValidationError):
        _utt(words=[{"w": "你", "s": 12.52, "e": 12.40}])


def test_words_must_be_time_sorted():
    ok = [
        {"w": "你", "s": 12.40, "e": 12.52},
        {"w": "到", "s": 12.52, "e": 12.60},
    ]
    assert _utt(words=ok).words[1].s == 12.52
    # 同起点并列允许（同时发声/栅格取整）
    tied = [
        {"w": "你", "s": 12.40, "e": 12.52},
        {"w": "到", "s": 12.40, "e": 12.52},
    ]
    assert len(_utt(words=tied).words) == 2
    # 逆序 → 拒绝
    with pytest.raises(ValidationError, match="未按时间排序"):
        _utt(words=list(reversed(ok)))


def test_word_boundary_values_accepted():
    # 贴边合法：s == utt.start，e == utt.end
    u = _utt(words=[{"w": "你", "s": 12.40, "e": 14.02}])
    assert u.words[0].s == 12.40 and u.words[0].e == 14.02


# ---------------------------------------------------------------------------
# ⑦ 时间零点：片段内相对时间 + offset = 全片绝对时间
# ---------------------------------------------------------------------------

def test_to_absolute_seconds():
    assert C.to_absolute_seconds(0.08, 300.0) == 300.08
    assert C.to_absolute_seconds(12.40, 0) == 12.4
    assert C.to_absolute_seconds(1.0005, 0.0005) == 1.001  # 同契约 3 位小数口径


# ---------------------------------------------------------------------------
# ④ utt_id 稳定生成公式：<ep>-u<起始毫秒:08d>
# ---------------------------------------------------------------------------

def test_make_utt_id_formula():
    assert C.make_utt_id("ep01", 12.40) == "ep01-u00012400"
    assert C.make_utt_id("ep01", 12.4) == C.make_utt_id("ep01", 12.40004)  # 毫秒取整幂等
    assert C.make_utt_id("ep02", 0) == "ep02-u00000000"
    with pytest.raises(ValueError):
        C.make_utt_id("ep01", -0.5)
    with pytest.raises(ValueError):
        C.make_utt_id("", 1.0)


# ---------------------------------------------------------------------------
# ④ upsert_jsonl：按 id 替换后整文件重写（解决追加自锁）
# ---------------------------------------------------------------------------

def _row(utt_id: str, start: float, end: float) -> C.Utterance:
    return C.Utterance.model_validate(
        {**json.loads(C2_UTT), "utt_id": utt_id, "start": start, "end": end,
         "words": [{"w": "你", "s": start, "e": end}]}
    )


def test_upsert_replaces_same_id_keeps_order(tmp_path):
    p = tmp_path / "utterances.jsonl"
    a, b = _row("ep01-u00012000", 12.0, 12.5), _row("ep01-u00013000", 13.0, 13.5)
    assert C.upsert_jsonl(p, [a, b], container=C.UtteranceTable) == 2
    # 同 id 重跑（改字段）→ 替换而非追加；旧行次序保留，不触发唯一性自锁
    a2 = _row("ep01-u00012000", 12.0, 12.9)
    assert C.upsert_jsonl(p, [a2], container=C.UtteranceTable) == 2
    rows = C.load_jsonl(p, C.UtteranceTable).root
    assert [r.utt_id for r in rows] == ["ep01-u00012000", "ep01-u00013000"]
    assert rows[0].end == 12.9


def test_upsert_appends_new_and_validates_whole_file(tmp_path):
    p = tmp_path / "utterances.jsonl"
    C.upsert_jsonl(p, [_row("u-a", 1.0, 1.5)], container=C.UtteranceTable)
    # 新行携带非法字级时间（构造期用 model_construct 绕过校验，模拟坏生产者）
    # → upsert 落盘前整表重校验拦截，坏文件不落盘
    bad_row = C.Utterance.model_construct(
        utt_id="u-b", shot_id="s0003", start=2.0, end=2.5, lang="zh",
        words=[C.Word.model_construct(w="x", s=9.9, e=9.99)],  # 越出 [2.0, 2.5] 句窗
    )
    with pytest.raises(ValidationError):
        C.upsert_jsonl(p, [bad_row], container=C.UtteranceTable)
    # 原文件未被破坏
    assert [r.utt_id for r in C.load_jsonl(p, C.UtteranceTable).root] == ["u-a"]
    # 合法新行 → 追加尾部
    good = C.Utterance.model_validate(
        {**json.loads(C2_UTT), "utt_id": "u-b", "start": 2.0, "end": 2.5,
         "words": [{"w": "x", "s": 2.0, "e": 2.5}]}
    )
    assert C.upsert_jsonl(p, [good], container=C.UtteranceTable) == 2
    assert [r.utt_id for r in C.load_jsonl(p, C.UtteranceTable).root] == ["u-a", "u-b"]
    # 无 .tmp 残留（原子重写）
    assert not (tmp_path / "utterances.jsonl.tmp").exists()


def test_dump_jsonl_atomic_no_tmp_left(tmp_path):
    p = tmp_path / "x.jsonl"
    C.dump_jsonl(p, [_row("u1", 1.0, 1.5)])
    assert p.is_file() and not (tmp_path / "x.jsonl.tmp").exists()


# ---------------------------------------------------------------------------
# ⑤ 说话人段级 schema（C2-pre，diar.jsonl）
# ---------------------------------------------------------------------------

def test_diar_segment_schema(tmp_path):
    rows = [
        C.DiarSegment(start=0.0, end=2.4, speaker="spk0"),
        C.DiarSegment(start=2.4, end=3.1, speaker="spk1"),
        C.DiarSegment(start=3.5, end=4.0, speaker="unknown"),
    ]
    table = C.DiarTable.model_validate([r.model_dump() for r in rows])
    assert table.root[1].speaker == "spk1"
    # 倒挂段拒绝
    with pytest.raises(ValidationError):
        C.DiarSegment(start=2.0, end=2.0, speaker="spk0")
    # speaker 空 → 拒绝（未定人填 unknown，不置空）
    with pytest.raises(ValidationError):
        C.DiarSegment(start=0.0, end=1.0, speaker="")
    # 未按时间排序的表拒绝
    with pytest.raises(ValidationError, match="排序"):
        C.DiarTable.model_validate([
            {"start": 3.0, "end": 3.5, "speaker": "spk0"},
            {"start": 1.0, "end": 2.0, "speaker": "spk1"},
        ])
    # JSONL 往返
    path = tmp_path / "diar.jsonl"
    assert C.dump_jsonl(path, table) == 3
    assert len(C.load_jsonl(path, C.DiarTable).root) == 3


# ---------------------------------------------------------------------------
# ① vocals.wav 槽位冻结：M4 只读人声
# ---------------------------------------------------------------------------

def test_vocals_slot_frozen_in_04_dial():
    assert "vocals.wav" in EXPECTED_FILES["04_dial"]
    # 人声不落 01_media（M1 混音层）
    assert "vocals.wav" not in EXPECTED_FILES["01_media"]
