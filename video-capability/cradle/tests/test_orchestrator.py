"""编排器: 状态推进全链路 / 崩溃恢复 / 重试与降级 / 合成组触发 (全部 CPU stub)。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src.db import DB
from src.orchestrator import Orchestrator, stable_seed
from tests.conftest import gates_all_fail, gates_all_pass, write_json

TEMPLATE_ID = "t_mini"
TEMPLATE = {
    "template_id": TEMPLATE_ID,
    "name_zh": "迷你模板",
    "duration_range": [2, 10],
    "orientation": "portrait",
    "variables": {"p": "毛肚"},
    "numbers": {"price": "39.9"},
    "scenes": [
        {"slot": "a", "narrative_slot": "n1", "duration_sec": 2, "role": "hook", "narration": "{p}来了"},
        {"slot": "b", "narrative_slot": "n2", "duration_sec": 2, "role": "cta",
         "background": {"type": "solid", "color": "0x000000"}, "narration": "只要{price}"},
    ],
}


def _card(shot_id, slot, lane="first_frame_i2v", n_best=3, retry_max=2, asset="assets/x.png"):
    return {
        "shot_id": shot_id, "narrative_slot": slot, "lane": lane,
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


@pytest.fixture
def root(tmp_path, monkeypatch):
    """隔离的 CRADLE_ROOT, 带迷你叙事模板。"""
    (tmp_path / "config").mkdir()
    (tmp_path / "templates" / "narrative").mkdir(parents=True)
    write_json(tmp_path / "templates" / "narrative" / f"{TEMPLATE_ID}.json", TEMPLATE)
    (tmp_path / "workdir").mkdir()
    monkeypatch.setenv("CRADLE_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def db(root):
    d = DB(root / "workdir" / "db.sqlite3")
    d.migrate()
    yield d
    d.close()


def _make_orch(db, generator=None, gater=None, composer=None, kenburns_fn=None, exists=lambda p: True):
    return Orchestrator(
        db, settings={"paths": {}, "budgets": {"wan_candidates_total": 200}, "debug_model": "stub"},
        generator=generator, gater=gater, composer=composer, kenburns_fn=kenburns_fn, exists=exists,
    )


def _ingest(db, shot_id, slot, **kw):
    card = _card(shot_id, slot, **kw)
    db.ingest_task(shot_id, slot, card["lane"], card, template=TEMPLATE_ID)
    return card


def _touching_generator(root):
    """生成假候选文件并记账。"""
    calls = []

    def gen(card, seed, out_path, hint=None):
        calls.append({"shot": card["shot_id"], "seed": seed, "hint": hint})
        Path(out_path).write_bytes(b"fake mp4")
        return {"path": out_path, "steps": 25, "duration_s": 2.0, "seed": seed}

    return gen, calls


def test_stable_seed_deterministic():
    assert stable_seed("S01") == stable_seed("S01")
    assert stable_seed("S01") != stable_seed("S02")


def test_happy_path_accept_and_compose(db, root):
    gen, calls = _touching_generator(root)
    _ingest(db, "S01", "n1")
    _ingest(db, "S02", "n2")
    orch = _make_orch(db, generator=gen, gater=lambda p, c: gates_all_pass(),
                      composer=lambda t, slots, out: {"path": out})

    assert orch.run_once() >= 2
    assert db.get_task("S01")["status"] == "composed"
    assert db.get_task("S02")["status"] == "composed"
    sel = db.selected_candidate("S01")
    assert sel and sel["verdict"] == "pass"
    # 候选文件与 n_best 个数
    assert len(db.get_candidates("S01")) == 3
    # n_best 种子互不相同
    seeds = {c["seed"] for c in calls if c["shot"] == "S01"}
    assert len(seeds) == 3


def test_accept_selects_best_candidate(db, root):
    gen, _ = _touching_generator(root)
    _ingest(db, "S01", "n1", n_best=2, retry_max=0)

    def gater(path, card):
        return gates_all_pass() if path.endswith("_1.mp4") else gates_all_fail()

    orch = _make_orch(db, generator=gen, gater=gater, composer=lambda t, s, out: {"path": out})
    orch.run_once()
    sel = db.selected_candidate("S01")
    assert sel["path"].endswith("_1.mp4") and sel["overall_score"] > 0.5
    assert db.get_task("S01")["status"] == "composed"


def test_blocked_when_source_asset_missing(db, root):
    def exists(p):
        return p != "assets/missing.png"

    _ingest(db, "S01", "n1", asset="assets/missing.png")
    orch = _make_orch(db, generator=lambda *a, **k: pytest.fail("不应生成"), exists=exists)
    orch.run_once()
    t = db.get_task("S01")
    assert t["status"] == "blocked" and "源图缺失" in t["error"]


def test_retry_then_fallback_then_composed(db, root):
    gen, calls = _touching_generator(root)
    _ingest(db, "S01", "n1", retry_max=2)
    kb_calls = []

    def kb(img, out, motion, dur, fps, w, h):
        kb_calls.append(motion)
        Path(out).write_bytes(b"kb")
        return {"path": out, "motion": motion}

    orch = _make_orch(db, generator=gen, gater=lambda p, c: gates_all_fail(),
                      composer=lambda t, s, out: {"path": out}, kenburns_fn=kb)

    orch.run_once()  # 不动点: 全 fail → 重试×2 → fallback → composed
    t = db.get_task("S01")
    assert t["status"] == "composed"
    assert t["attempts"] == 2
    hint = json.loads(t["hint_json"])
    assert hint["round"] == 2 and hint["guidance_delta"] == -0.5 and hint["negative_extra"]
    assert len(kb_calls) == 1
    cands = db.get_candidates("S01")
    assert len(cands) == 3 * 3 + 1  # 3轮生成 × n_best=3 + 1 个 fallback
    fallback_rows = [c for c in cands if c["verdict"] == "fallback"]
    assert len(fallback_rows) == 1 and fallback_rows[0]["selected"] is True
    gen_candidates = [c for c in cands if c["verdict"] == "fail"]
    assert len(gen_candidates) == 9  # 失败候选保留作失败画廊素材


def test_generation_exception_counts_attempt_then_blocks(db, root):
    def bad_gen(card, seed, out_path, hint=None):
        raise RuntimeError("GPU 掉线")

    _ingest(db, "S01", "n1", retry_max=0)
    orch = _make_orch(db, generator=bad_gen)
    for _ in range(10):
        if db.get_task("S01")["status"] == "blocked":
            break
        orch.run_once()
    t = db.get_task("S01")
    assert t["status"] == "blocked" and t["attempts"] >= 1


def test_wan_total_guard_blocks_generation(db, root):
    """Wan 候选守卫: 预算 0 时默认生成器直接拒绝。"""
    _ingest(db, "S01", "n1", retry_max=0)
    orch = Orchestrator(db, settings={"paths": {}, "budgets": {"wan_candidates_total": 0},
                                      "debug_model": "wan"},
                        gater=lambda p, c: gates_all_pass(), composer=lambda t, s, out: {"path": out})
    for _ in range(10):
        if db.get_task("S01")["status"] == "blocked":
            break
        orch.run_once()
    assert db.get_task("S01")["status"] == "blocked"


def test_recover_resets_orphan_generating(db, root):
    _ingest(db, "S01", "n1")
    db.force_status("S01", "generating", "simulate crash")
    orch = _make_orch(db, generator=lambda *a, **k: {"path": "x", "steps": 1, "duration_s": 1},
                      gater=lambda p, c: gates_all_pass(), composer=lambda t, s, out: {"path": out})
    assert orch.recover() == 1
    assert db.get_task("S01")["status"] == "pending"
    # 恢复后可继续推进
    gen, _ = _touching_generator(root)
    orch._generator = gen
    orch.run_once()
    assert db.get_task("S01")["status"] == "composed"


def test_recover_resets_gating_without_candidates(db, root):
    _ingest(db, "S01", "n1")
    db.force_status("S01", "gating", "simulate crash before candidates")
    orch = _make_orch(db, generator=lambda *a, **k: {"path": "x", "steps": 1, "duration_s": 1})
    assert orch.recover() == 1
    assert db.get_task("S01")["status"] == "pending"


def test_events_recorded(db, root):
    gen, _ = _touching_generator(root)
    _ingest(db, "S01", "n1")
    orch = _make_orch(db, generator=gen, gater=lambda p, c: gates_all_pass(),
                      composer=lambda t, s, out: {"path": out})
    orch.run_once()
    msgs = [e["msg"] for e in db.recent_events(limit=50)]
    assert any("pending -> generating" in m for m in msgs)
    assert any("gating -> accepted" in m for m in msgs)
    assert any("accepted -> composed" in m for m in msgs)


def test_run_forever_exits_when_all_terminal(db, root):
    gen, _ = _touching_generator(root)
    _ingest(db, "S01", "n1")
    orch = _make_orch(db, generator=gen, gater=lambda p, c: gates_all_pass(),
                      composer=lambda t, s, out: {"path": out})
    orch.run_forever(poll_interval=0.01)  # 全部终态后应立即退出(不挂起)
    assert db.get_task("S01")["status"] == "composed"
