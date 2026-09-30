"""路由与降级: 全分支单测 (SPECS §5.5)。"""

from __future__ import annotations

import pytest

from src.route import RETRY_GUIDANCE_DELTA, check_assets, candidate_passed, pick_best, retry_hint, route_shot
from src.gates import GATE_IDS


def cand(score=0.8, passed=True):
    return {"candidate_id": 1, "seed": 1, "gates": {g: {"passed": passed, "score": score} for g in GATE_IDS},
            "overall_score": score}


@pytest.fixture
def card(valid_card):
    return valid_card


def test_accept_picks_best_overall_score(card):
    cands = [cand(score=0.70), cand(score=0.95), cand(score=0.80)]
    cands[1]["candidate_id"] = 2
    d = route_shot(card, cands, attempts_used=0, exists=lambda p: True)
    assert d["action"] == "accept" and d["candidate"]["overall_score"] == 0.95


def test_partial_pass_counts_as_accept(card):
    cands = [cand(score=0.4, passed=False), cand(score=0.6, passed=True)]
    d = route_shot(card, cands, attempts_used=0, exists=lambda p: True)
    assert d["action"] == "accept" and d["candidate"]["overall_score"] == 0.6


def test_all_fail_with_retries_left(card):
    cands = [cand(score=0.3, passed=False)]
    d = route_shot(card, cands, attempts_used=0, exists=lambda p: True)
    assert d["action"] == "retry"
    assert d["round"] == 1
    assert d["hint"]["guidance_delta"] == RETRY_GUIDANCE_DELTA == -0.5
    assert d["hint"]["negative_extra"]  # 加强 negative


def test_retry_hint_rounds_strengthen(card):
    h1 = retry_hint(1)
    h2 = retry_hint(2)
    assert set(h1["negative_extra"]) != set(h2["negative_extra"])
    assert route_shot(card, [cand(0.1, False)], attempts_used=1, exists=lambda p: True)["round"] == 2


def test_exhausted_retries_fallback(card):
    d = route_shot(card, [cand(0.2, False)], attempts_used=card["retry_max"], exists=lambda p: True)
    assert d["action"] == "fallback"


def test_fallback_asset_missing_blocks(card):
    fb = dict(card["fallback"], asset="assets/fallback_only.png")
    card = dict(card, fallback=fb)

    def exists(p):
        return p != fb["asset"]
    d = route_shot(card, [cand(0.2, False)], attempts_used=card["retry_max"], exists=exists)
    assert d["action"] == "blocked" and "fallback" in d["reason"]


def test_source_image_missing_blocks(card):
    def exists(p):
        return p != card["first_frame_asset"]
    d = route_shot(card, [], attempts_used=0, exists=exists)
    assert d["action"] == "blocked" and "源图缺失" in d["reason"]
    # blocked 优先于其他分支(即便候选全过)
    d2 = route_shot(card, [cand(0.99)], attempts_used=0, exists=exists)
    assert d2["action"] == "blocked"


def test_retry_max_zero_goes_fallback(card):
    card["retry_max"] = 0
    d = route_shot(card, [cand(0.2, False)], attempts_used=0, exists=lambda p: True)
    assert d["action"] == "fallback"


def test_candidate_passed_requires_all_six(card):
    c = cand()
    c["gates"].pop("G6")
    assert candidate_passed(c) is False
    c2 = cand()
    assert candidate_passed(c2) is True


def test_pick_best_tie_stable():
    a, b = cand(0.8), cand(0.8)
    assert pick_best([a, b]) is a


def test_retry_hint_shape():
    h = retry_hint(3)  # 超出预设轮次回退到最后一档
    assert h["round"] == 3 and isinstance(h["negative_extra"], list)


def test_check_assets_reports_fallback_missing(card):
    assert check_assets(card, exists=lambda p: True) is None
    assert "first_frame_asset" in check_assets(card, exists=lambda p: False)
    fb = dict(card["fallback"], asset="assets/fallback_only.png")
    c = dict(card, fallback=fb)
    reason = check_assets(c, exists=lambda p: p != fb["asset"])
    assert "fallback.asset" in reason


def _with(card, **kw):
    d = {**card}
    d.update(kw)
    return d


# ---------------- V2-M1: gate_json 携带 G7 增补键时的路由兼容 ----------------

def test_candidate_passed_ignores_g7_key_but_requires_passed(card):
    c = cand()
    c["gates"]["G7"] = {"passed": True, "score": 0.9}
    assert candidate_passed(c) is True  # 七键不破坏六门禁数量判定
    c["gates"]["G7"] = {"passed": False, "score": 0.3}
    assert candidate_passed(c) is False  # G7 触发 → 不视为 pass


def test_candidate_passed_legacy_six_key_dict(card):
    c = cand()  # v1 历史候选: 恰好六键
    assert candidate_passed(c) is True
