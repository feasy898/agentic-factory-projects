"""v2 三车道资产测试: shotcards_v2 全部卡过 schema + 叙事模板 v2 校验 + 映射正确性。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.schema import load_shotcard, load_template, total_duration, validate_shotcard

REPO = Path(__file__).resolve().parents[1]
V2_CARDS = REPO / "templates" / "shotcards_v2"
NARRATIVE_V2 = REPO / "templates" / "narrative_v2"

# SPECS_V2 §5.5 映射 (M3 任务面; S15 按红线修正归 compositing, D-063)
EXPECTED_LANE = (
    {f"S{i:02d}": "compositing_2d5" for i in (1, 2, 3, 4, 5, 6, 13, 14, 15, 17)}
    | {f"S{i:02d}": "pure_gen_short" for i in (7, 8, 9, 10, 11, 16)}
    | {"S12": "ken_burns", "S18": "evidence_transfer", "S19": "evidence_transfer"}
)


def _v2_files():
    return sorted(V2_CARDS.glob("*.json"))


def test_v2_cards_exist_19():
    files = _v2_files()
    if not files:
        pytest.skip("shotcards_v2 尚未生成 (tools/m3_gen_shotcards_v2.py)")
    assert len(files) == 19  # 17 重写 + 2 evidence 演示


def test_v2_cards_valid_and_lane_mapping():
    files = _v2_files()
    if not files:
        pytest.skip("shotcards_v2 尚未生成")
    seen = {}
    for f in files:
        c = load_shotcard(f)
        seen[c["shot_id"]] = c
    assert set(seen) == set(EXPECTED_LANE)
    for sid, lane in EXPECTED_LANE.items():
        assert seen[sid]["lane"] == lane, f"{sid} 应为 {lane}"
    # pure_gen_short 时长 1-2s
    for sid in ("S07", "S08", "S09", "S10", "S11", "S16"):
        assert 1.0 <= seen[sid]["duration_sec"] <= 2.0
    # 确定性车道 n_best=1
    for sid in ("S01", "S02", "S03", "S04", "S05", "S06", "S13", "S14", "S15", "S17"):
        assert seen[sid]["n_best"] == 1
    # evidence 卡 evidence_asset 指向合成演示源
    for sid in ("S18", "S19"):
        ea = seen[sid]["evidence_asset"]
        assert ea and "synthetic_demo_source" in ea
    # v1 目录保留未删 (SPECS_V2 §5.5)
    assert len(list((REPO / "templates" / "shotcards").glob("*.json"))) == 17


def test_v2_narrative_templates():
    files = sorted(NARRATIVE_V2.glob("*.json"))
    if not files:
        pytest.skip("narrative_v2 尚未生成")
    for f in files:
        t = load_template(f)
        total = total_duration(t["scenes"])
        lo, hi = t["duration_range"]
        assert lo <= total <= hi, f"{f.name} 总时长 {total}"
        # SPECS_V2 §5.5: 25-30s 片子镜头数 8-14 (含程序渲染幕)
        n_video = sum(1 for sc in t["scenes"] if not sc.get("background"))
        assert 8 <= len(t["scenes"]) <= 14
        assert n_video >= 8
        # 1-2s 节奏幕存在
        assert any(sc["duration_sec"] <= 2.0 for sc in t["scenes"] if not sc.get("background"))
        # 数字不进 narration (D-015: 数字只在 numbers)
        for sc in t["scenes"]:
            assert not any(ch.isdigit() for ch in sc.get("narration", ""))


def test_v2_narrative_slot_coverage():
    """两个 v2 模板的非 background 槽位都有 v2 卡 (compose_from_spec 可用)。"""
    files = sorted(NARRATIVE_V2.glob("*.json"))
    if not files:
        pytest.skip("narrative_v2 尚未生成")
    cards = {c["shot_id"]: c for c in (load_shotcard(f) for f in _v2_files())}
    card_slots = {c["narrative_slot"] for c in cards.values()}
    for f in files:
        t = load_template(f)
        for sc in t["scenes"]:
            if not sc.get("background"):
                assert sc["narrative_slot"] in card_slots, f"{f.name}:{sc['slot']} 无对应卡槽位"
