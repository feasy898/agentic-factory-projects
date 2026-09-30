"""v2 三车道编排接入测试: 车道分发 / 预算守卫口径 / 确定性车道 n_best / evidence 资产检查。"""

from __future__ import annotations

import json

import pytest

from src.db import DB
from src.orchestrator import WAN_CONSUMING_LANES_SQL, Orchestrator
from src.route import check_assets, route_shot
from tests.conftest import gates_all_pass, write_json


def _card(shot_id, lane, n_best=1, retry_max=0, asset="assets/x.png", **extra):
    card = {
        "shot_id": shot_id, "narrative_slot": "n1", "lane": lane,
        "orientation": "portrait", "duration_sec": 2, "resolution": [480, 832], "fps": 16,
        "camera": {"scale": "closeup", "angle": "high_45", "motion": "slow_push_in", "depth": "shallow"},
        "subject": {"type": "object", "desc_zh": "测试主体"},
        "prompt_en": "test prompt",
        "first_frame_asset": asset,
        "negative": ["human face", "hands", "text"],
        "n_best": n_best, "retry_max": retry_max,
        "acceptance": {"clip_ref_min": 0.65, "clip_text_min": 0.22, "temporal_clip_min": 0.85,
                       "vlm_overall_min": 0.70, "vlm_defect_max": 0.2, "duration_tol": 0.5},
        "fallback": {"type": "ken_burns", "asset": asset, "motion": "zoom_in_1.06", "duration_sec": 2},
    }
    card.update(extra)
    return card


@pytest.fixture
def root(tmp_path, monkeypatch):
    (tmp_path / "workdir").mkdir()
    monkeypatch.setenv("CRADLE_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def db(root):
    d = DB(root / "workdir" / "db.sqlite3")
    d.migrate()
    yield d
    d.close()


def _ingest(db, card, template=None):
    return db.ingest_task(card["shot_id"], card["narrative_slot"], card["lane"],
                          card_json=card, template=template)


def _run_to_accept(orch, db, shot):
    for _ in range(10):
        orch.run_once()
        if db.get_task(shot)["status"] in ("accepted", "fallback", "blocked", "composed"):
            break
    return db.get_task(shot)["status"]


# ---------------- route.check_assets ----------------

def test_evidence_asset_missing_blocks(tmp_path):
    asset = str(tmp_path / "first.png")
    card = _card("SX18", "evidence_transfer", asset=asset,
                 evidence_asset=str(tmp_path / "nope.mp4"))
    reason = check_assets(card, exists=lambda p: p == asset)  # 首帧在, 证据源缺失
    assert "证据源缺失" in reason


def test_evidence_asset_present_ok(tmp_path):
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")
    asset = str(tmp_path / "first.png")
    card = _card("SX18", "evidence_transfer", asset=asset, evidence_asset=str(src))
    assert check_assets(card, exists=lambda p: True) is None


# ---------------- 车道分发 ----------------

@pytest.mark.parametrize("lane,modname,expect_tag", [
    ("pure_gen_short", "src.gen.puregen", "pure_gen_short"),
    ("compositing_2d5", "src.gen.compositing25", "compositing_2d5"),
    ("evidence_transfer", "src.gen.evidence", "evidence_transfer"),
])
def test_lane_dispatch(root, db, monkeypatch, lane, modname, expect_tag):
    captured = {}

    def fake_gen(card, seed, out_path, **kw):
        captured["card"] = card
        captured["kwargs"] = kw
        return {"path": out_path, "model": expect_tag, "steps": 1, "duration_s": 1}

    import importlib

    monkeypatch.setattr(importlib.import_module(modname), "generate", fake_gen)
    card = _card("SX1", lane, n_best=2)
    _ingest(db, card)
    orch = Orchestrator(db, settings={"debug_model": "ltx"},  # 三车道不受调试模型投影影响
                        gater=lambda p, c: gates_all_pass(), composer=lambda t, s, out: {"path": out},
                        exists=lambda p: True)
    status = _run_to_accept(orch, db, "SX1")
    assert status == "accepted"
    assert captured["card"]["lane"] == lane


def test_deterministic_lane_ignores_n_best(root, db, monkeypatch):
    """compositing_2d5 确定性渲染: n_best=3 也只产 1 条候选 (D-013 口径扩展)。"""
    calls = []

    def fake_gen(card, seed, out_path, **kw):
        calls.append(out_path)
        return {"path": out_path, "model": "compositing_2d5", "steps": 1, "duration_s": 1}

    import importlib

    monkeypatch.setattr(importlib.import_module("src.gen.compositing25"), "generate", fake_gen)
    card = _card("SX2", "compositing_2d5", n_best=3)
    _ingest(db, card)
    orch = Orchestrator(db, settings={"debug_model": "stub"},
                        gater=lambda p, c: gates_all_pass(), composer=lambda t, s, out: {"path": out},
                        exists=lambda p: True)
    _run_to_accept(orch, db, "SX2")
    assert len(calls) == 1 and len(db.get_candidates("SX2")) == 1


def test_wan_lane_honors_n_best(root, db, monkeypatch):
    """对照: first_frame_i2v 仍按卡面 n_best 生成 (v1 行为不变)。"""
    calls = []

    def fake_gen(card, seed, out_path, **kw):
        calls.append(out_path)
        return {"path": out_path, "model": "wan_fun_1.3b_inp", "steps": 1, "duration_s": 1}

    import importlib

    monkeypatch.setattr(importlib.import_module("src.gen.wan"), "generate", fake_gen)
    card = _card("SX3", "first_frame_i2v", n_best=2)
    _ingest(db, card)
    orch = Orchestrator(db, settings={"debug_model": "stub"},
                        gater=lambda p, c: gates_all_pass(), composer=lambda t, s, out: {"path": out},
                        exists=lambda p: True)
    _run_to_accept(orch, db, "SX3")
    assert len(calls) == 2


# ---------------- 预算守卫口径 (D-062) ----------------

def test_budget_guard_counts_new_wan_lanes(root, db, monkeypatch):
    """pure_gen_short/evidence_transfer 消耗 Wan → 计入守卫; compositing 不计。"""
    seen = {"n": 0}

    def fake_gen(card, seed, out_path, **kw):
        seen["n"] += 1
        return {"path": out_path, "model": "x", "steps": 1, "duration_s": 1}

    import importlib

    for mod, attr in (("src.gen.puregen", "generate"), ("src.gen.evidence", "generate")):
        monkeypatch.setattr(importlib.import_module(mod), attr, fake_gen)
    # 先造成 1 条 puregen 候选 (limit=1 已满)
    card = _card("SX4", "pure_gen_short")
    _ingest(db, card)
    orch = Orchestrator(db, settings={"debug_model": "stub", "budgets": {"wan_candidates_total": 1}},
                        gater=lambda p, c: gates_all_pass(), composer=lambda t, s, out: {"path": out})
    assert _run_to_accept(orch, db, "SX4") == "accepted"
    assert seen["n"] == 1
    # 第二条 puregen: 守卫命中 → 生成失败 → attempts+1 (不产生候选)
    card2 = _card("SX5", "pure_gen_short")
    _ingest(db, card2)
    orch2 = Orchestrator(db, settings={"debug_model": "stub", "budgets": {"wan_candidates_total": 1}},
                         gater=lambda p, c: gates_all_pass(), composer=lambda t, s, out: {"path": out},
                         exists=lambda p: True)
    for _ in range(10):
        orch2.run_once()
        if db.get_task("SX5")["attempts"] >= 1:
            break
    assert db.get_task("SX5")["attempts"] == 1
    assert db.get_task("SX5")["error"] and "守卫上限" in db.get_task("SX5")["error"]
    # compositing 不消耗 Wan: limit=1 仍可生成
    card3 = _card("SX6", "compositing_2d5")
    _ingest(db, card3)

    def fake_c25(card, seed, out_path, **kw):
        seen["n"] += 1
        return {"path": out_path, "model": "compositing_2d5", "steps": 1, "duration_s": 1}

    monkeypatch.setattr(importlib.import_module("src.gen.compositing25"), "generate", fake_c25)
    orch3 = Orchestrator(db, settings={"debug_model": "stub", "budgets": {"wan_candidates_total": 1}},
                         gater=lambda p, c: gates_all_pass(), composer=lambda t, s, out: {"path": out},
                         exists=lambda p: True)
    assert _run_to_accept(orch3, db, "SX6") == "accepted"


def test_wan_consuming_lanes_sql_constant():
    assert set(WAN_CONSUMING_LANES_SQL) == {"first_frame_i2v", "pure_gen_short",
                                            "evidence_transfer", "t2v"}


# ---------------- 路由对新车道的语义不变 ----------------

def test_route_accept_for_new_lane(tmp_path):
    card = _card("SX7", "evidence_transfer", evidence_asset="assets/evidence/x.mp4")
    cand = {"gates": {g: {"passed": True} for g in ("G1", "G2", "G3", "G4", "G5", "G6")},
            "overall_score": 0.9}
    cand["gates"]["G7"] = {"passed": True, "score": 0.95}
    decision = route_shot(card, [cand], attempts_used=0, exists=lambda p: True)
    assert decision["action"] == "accept"
