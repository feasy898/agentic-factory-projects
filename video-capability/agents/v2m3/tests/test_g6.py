"""G6 业务门禁: 字幕逐字比对 / CER 编辑距离 / ASR 回转可选。"""

from __future__ import annotations

import pytest

from src.gates.g6_business import cer, check_subtitle_exact, edit_distance, g6_business


def test_edit_distance_basic():
    assert edit_distance("", "") == 0
    assert edit_distance("abc", "abc") == 0
    assert edit_distance("", "abc") == 3
    assert edit_distance("abc", "") == 3
    assert edit_distance("kitten", "sitting") == 3
    assert edit_distance("毛肚真好吃", "毛肚真不脆") == 2


def test_cer():
    assert cer("你好世界", "你好世界") == 0.0
    assert cer("你好世界", "你好世x") == pytest.approx(0.25)
    assert cer("", "") == 0.0
    assert cer("", "abc") == 1.0
    assert cer("abcd", "") == 1.0
    assert cer("12345", "1234567890") == pytest.approx(1.0)


def test_subtitle_exact():
    ok, detail = check_subtitle_exact(["毛肚来了", "只要39.9"], ["毛肚来了", "只要39.9"])
    assert ok is True and detail["diffs"] == []
    bad, d2 = check_subtitle_exact(["毛肚来了", "只要39.9"], ["毛肚来了", "只要39.8"])
    assert bad is False and len(d2["diffs"]) == 1
    short, d3 = check_subtitle_exact(["a", "b"], ["a"])
    assert short is False and d3["diffs"][0]["expected"] == "b" and d3["diffs"][0]["actual"] is None


def test_g6_exact_pass_without_asr():
    g = g6_business(["一条", "两条"], ["一条", "两条"], asr_fn=None)
    assert g["passed"] is True and g["score"] == 1.0
    assert g["detail"]["asr_skipped"] is True


def test_g6_subtitle_mismatch_fails():
    g = g6_business(["一条"], ["一条半"], asr_fn=lambda: "无所谓")
    assert g["passed"] is False and g["score"] == 0.0
    assert g["detail"]["subtitle_exact"] is False


def test_g6_asr_roundtrip_cer_pass():
    g = g6_business(["今晚三十九块九"], ["今晚三十九块九"],
                    asr_fn=lambda: "今晚三十九块九", expected_narration="今晚三十九块九")
    assert g["passed"] is True and g["detail"]["cer"] == 0.0


def test_g6_asr_cer_over_threshold_fails():
    narration = "今晚只要三十九块九"
    g = g6_business([narration], [narration],
                    asr_fn=lambda: "明晚只要八十八块", expected_narration=narration, cer_max=0.05)
    assert g["passed"] is False
    assert g["detail"]["cer"] > 0.05
    assert 0 < g["score"] < 1  # 字幕过但 CER 未过


def test_g6_asr_error_is_skipped_not_failed():
    def boom():
        raise RuntimeError("asr down")

    g = g6_business(["一条"], ["一条"], asr_fn=boom, expected_narration="一条")
    assert g["passed"] is True
    assert g["detail"]["asr_skipped"] is True and g["detail"]["asr_error"]


def test_g6_asr_without_narration_skips():
    g = g6_business(["一条"], ["一条"], asr_fn=lambda: "xx")
    assert g["passed"] is True and g["detail"]["asr_skipped"] is True
