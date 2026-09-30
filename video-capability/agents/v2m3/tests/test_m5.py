"""M5 校准与量产增量的单测: G5 分锚 / stable-borderline 短路 / 风格化钩子 / m5_videos / compose_from_spec。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.gates import GATE_IDS, make_gate
from src.route import (
    BORDERLINE_MIN_CANDIDATES,
    BORDERLINE_SPREAD,
    is_stable_borderline,
    route_shot,
)
from tests.conftest import requires_ffmpeg, write_json

REPO = Path(__file__).resolve().parents[1]


def _card(asset="assets/products/maodu_01.png", retry_max=2, **over):
    base = {
        "shot_id": "S01", "narrative_slot": "evidence_product", "lane": "first_frame_i2v",
        "orientation": "portrait", "duration_sec": 5, "resolution": [480, 832], "fps": 16,
        "camera": {"scale": "closeup", "angle": "high_45", "motion": "slow_push_in", "depth": "shallow"},
        "subject": {"type": "object", "desc_zh": "毛肚"},
        "prompt_en": "hotpot tripe close-up",
        "first_frame_asset": asset,
        "negative": ["human face", "hands", "text"],
        "n_best": 3, "retry_max": retry_max,
        "acceptance": {"clip_ref_min": 0.65, "clip_text_min": 0.22, "temporal_clip_min": 0.85,
                       "vlm_overall_min": 0.70, "vlm_defect_max": 0.2, "duration_tol": 0.5},
        "fallback": {"type": "ken_burns", "asset": asset, "motion": "zoom_in_1.06", "duration_sec": 5},
    }
    base.update(over)
    return base


def _cand(score, passed=False, cid=1):
    return {"candidate_id": cid, "seed": 1,
            "gates": {g: make_gate(g, passed, score) for g in GATE_IDS},
            "overall_score": score}


# ---------------- stable-borderline 短路 (阶段0.3) ----------------

def test_is_stable_borderline_true_when_flat_and_all_fail():
    cands = [_cand(0.63, cid=1), _cand(0.635, cid=2), _cand(0.632, cid=3)]
    assert is_stable_borderline(cands) is True


def test_is_stable_borderline_false_when_single_candidate():
    assert is_stable_borderline([_cand(0.63)]) is False


def test_is_stable_borderline_false_when_any_pass():
    cands = [_cand(0.63, passed=False), _cand(0.9, passed=True)]
    assert is_stable_borderline(cands) is False


def test_is_stable_borderline_false_when_spread_ge_threshold():
    cands = [_cand(0.60), _cand(0.60 + BORDERLINE_SPREAD)]
    assert is_stable_borderline(cands) is False


def test_route_short_circuits_to_fallback_without_retries():
    card = _card(retry_max=2)
    cands = [_cand(0.63, cid=1), _cand(0.634, cid=2), _cand(0.628, cid=3)]
    d = route_shot(card, cands, attempts_used=0, exists=lambda p: True)
    assert d["action"] == "fallback"
    assert d["short_circuit"] == "stable_borderline"
    assert d["retry_rounds_saved"] == 2
    assert d["n_candidates"] == 3


def test_route_short_circuit_blocked_when_fallback_missing():
    """fallback 资产缺失: check_assets 在入口即 blocked(既有行为), 短路分支不改变该语义。"""
    card = _card(asset="assets/gone.png")
    cands = [_cand(0.63, cid=1), _cand(0.631, cid=2)]
    d = route_shot(card, cands, attempts_used=0, exists=lambda p: False)
    assert d["action"] == "blocked"


def test_route_still_retries_when_scores_vary():
    card = _card(retry_max=2)
    cands = [_cand(0.55, cid=1), _cand(0.65, cid=2)]
    d = route_shot(card, cands, attempts_used=0, exists=lambda p: True)
    assert d["action"] == "retry" and d["round"] == 1


# ---------------- G5 分锚: asset_type 推导与启发式行为 (阶段0.1) ----------------

def test_asset_type_of_products_vs_scenes():
    from src.orchestrator import asset_type_of

    assert asset_type_of(_card("assets/products/maodu_01.png")) == "food"
    assert asset_type_of(_card("assets/scenes/storefront_01.png")) == "scene"
    assert asset_type_of(_card("assets/scenes/back_view_01.png")) == "scene"
    assert asset_type_of(_card("")) == "food"  # 缺省安全


def test_clip_heuristic_dual_anchor_best_of(tmp_path):
    """双锚取最优: food/scene 两锚都算, appeal01 取两域映射 max; 美食帧与 D-026 行为一致。

    clip_heuristic_review 会真实开图并切格(2×5), embed 全部注入 stub。
    """
    from PIL import Image

    from src.api.vlm import APPEAL_ANCHORS, APPEAL_DOMAINS, clip_heuristic_review

    grid = str(tmp_path / "grid.png")
    Image.new("RGB", (64, 160), (120, 30, 30)).save(grid)
    import zlib

    def text_embed(text: str):
        import numpy as np

        v = np.zeros(64, dtype="float32")
        i = zlib.crc32(text.encode()) % 64
        v[i] = 1.0
        return v

    anchor_idx = {k: zlib.crc32(v.encode()) % 64 for k, v in APPEAL_ANCHORS.items()}

    def image_embed(img):
        import numpy as np

        v = np.zeros(64, dtype="float32")
        # 图像向量与两个 appeal 锚都有固定相似度 0.2 → food 域(0.145,0.28)映射 0.407,
        # scene 域(0.18,0.25)映射 0.286 → 取 max=0.407(basis=food)
        for i in anchor_idx.values():
            v[i] = 0.2
        return v

    r_food = clip_heuristic_review(grid, None, image_embed=image_embed, text_embed=text_embed,
                                   asset_type="food")
    r_scene = clip_heuristic_review(grid, None, image_embed=image_embed, text_embed=text_embed,
                                    asset_type="scene")
    # asset_type 只是标签, 分数与标签无关(双锚都算)
    assert r_food["overall_score"] == r_scene["overall_score"]
    assert r_food["asset_type"] == "food" and r_scene["asset_type"] == "scene"
    assert r_food["calibration"] == "D-026+M5-dual-anchor"
    assert r_food["appeal_basis"] == "food"  # 0.2 在 food 域中部 > scene 域上部
    assert r_food["appeal01_food"] > r_food["appeal01_scene"]
    assert APPEAL_DOMAINS["food"] == (0.145, 0.28)  # food 域不回退(D-026 原值)
    # 场景帧形态: scene 锚相似度高、food 锚相似度低 → basis 应为 scene
    def image_embed_scene_like(img):
        import numpy as np

        v = np.zeros(64, dtype="float32")
        v[anchor_idx["scene"]] = 0.24
        v[anchor_idx["food"]] = 0.15
        return v

    r_scene_frame = clip_heuristic_review(grid, None, image_embed=image_embed_scene_like,
                                          text_embed=text_embed, asset_type="scene")
    assert r_scene_frame["appeal_basis"] == "scene"
    assert r_scene_frame["appeal01_scene"] > r_scene_frame["appeal01_food"]


def test_run_g2g5_passes_asset_type_only_when_given():
    from src.gates.g2g5_vlm import run_g2g5

    received = []

    def vlm_kw(grid, prompt, **kw):
        received.append(kw.get("asset_type"))
        return json.dumps({
            "defects": {k: 0.05 for k in ("deformed_object", "morphing_artifact", "flicker",
                                          "garbled_text", "subject_missing", "unnatural_motion",
                                          "overall_defect")},
            "aesthetic": {k: 4 for k in ("composition", "lighting", "color", "appeal", "overall")},
            "camera_match": 4, "overall_score": 0.85, "verdict": "pass", "main_issue": "ok",
        })

    # grid_png 显式给出时不做任何抽帧, video 路径不触碰
    acc = {"vlm_overall_min": 0.70, "vlm_defect_max": 0.2}
    g2, g5, _ = run_g2g5("/tmp/none.mp4", vlm_kw, acc, grid_png="/tmp/grid.png")
    assert received == [None]  # 不传 asset_type 时保持两参契约
    g2, g5, _ = run_g2g5("/tmp/none.mp4", vlm_kw, acc, grid_png="/tmp/grid.png",
                         asset_type="scene")
    assert received[-1] == "scene"


# ---------------- 首帧风格统一钩子 (阶段0.4) ----------------

@requires_ffmpeg
def test_wan_generate_uses_precomputed_stylized_frame(tmp_path):
    from src.gen.wan import generate

    seen = {}

    def fake_pipeline(**kw):
        seen.update(kw)
        import numpy as np

        return [np.full((16, 16, 3), 180, dtype="uint8")] * 4

    card = _card()
    meta = generate(card, 42, str(tmp_path / "c.mp4"), steps=20, pipeline=fake_pipeline,
                    stylized_first_frame="/tmp/stylized.png")
    assert seen["first_frame"] == "/tmp/stylized.png"
    assert meta["path"] == str(tmp_path / "c.mp4") and meta["model"] == "wan_fun_1.3b_inp"


@pytest.fixture
def orch_root(tmp_path, monkeypatch):
    """编排器测试隔离根(等价 test_orchestrator.root)。"""
    (tmp_path / "workdir").mkdir()
    monkeypatch.setenv("CRADLE_ROOT", str(tmp_path))
    return tmp_path


def test_orchestrator_stylizes_once_per_task_shared_by_n_best(db, orch_root, monkeypatch):
    import src.gen.wan as wan_mod
    from src.orchestrator import Orchestrator

    stylize_calls = []

    def fake_stylize(image_path, out_path, prompt, denoise=0.3, device="cuda", seed=0, pipeline=None):
        stylize_calls.append(out_path)
        Path(out_path).write_bytes(b"png")
        return {"path": out_path}

    monkeypatch.setattr(wan_mod, "stylize_first_frame", fake_stylize)

    card = _card()
    card["n_best"] = 3
    (orch_root / "assets" / "products").mkdir(parents=True, exist_ok=True)
    Path(orch_root / card["first_frame_asset"]).write_bytes(b"png")
    db.ingest_task("S01", "n1", card["lane"], card)

    gen_calls = []

    def gen(c, seed, out_path, hint=None):
        gen_calls.append({"hint": hint})
        Path(out_path).write_bytes(b"mp4")
        return {"path": out_path, "steps": 20, "duration_s": 5.0, "seed": seed}

    settings = {"paths": {}, "budgets": {"wan_candidates_total": 200},
                "debug_model": "stub", "prod_stylize_denoise": 0.3}
    orch = Orchestrator(db, settings=settings, generator=gen,
                        gater=lambda p, c: {g: make_gate(g, True, 0.9) for g in GATE_IDS})
    task = db.get_task("S01")
    db.set_status("S01", "generating")
    orch._generate(task, card, None)
    assert len(stylize_calls) == 1  # 每任务一次
    assert len(gen_calls) == 3  # n_best 候选
    assert all(h["hint"]["stylized_first_frame"] == stylize_calls[0] for h in gen_calls)


def test_orchestrator_skips_stylize_for_ltx_debug(db, orch_root, monkeypatch):
    from src.orchestrator import Orchestrator

    card = _card()
    card["n_best"] = 1
    (orch_root / "assets" / "products").mkdir(parents=True, exist_ok=True)
    Path(orch_root / card["first_frame_asset"]).write_bytes(b"png")
    db.ingest_task("S01", "n1", card["lane"], card)

    gen_calls = []

    def gen(c, seed, out_path, hint=None):
        gen_calls.append({"hint": hint})
        Path(out_path).write_bytes(b"mp4")
        return {"path": out_path, "steps": 12, "duration_s": 1.56, "seed": seed}

    settings = {"paths": {}, "budgets": {"wan_candidates_total": 200},
                "debug_model": "ltx", "prod_stylize_denoise": 0.3}
    orch = Orchestrator(db, settings=settings, generator=gen,
                        gater=lambda p, c: {g: make_gate(g, True, 0.9) for g in GATE_IDS})
    task = db.get_task("S01")
    db.set_status("S01", "generating")
    orch._generate(task, card, None)
    assert gen_calls and "stylized_first_frame" not in gen_calls[0]["hint"]


# ---------------- m5_videos 迁移与台账 (阶段2.4) ----------------

def test_migration_v2_creates_m5_videos(db):
    db.migrate()
    assert db.schema_version() >= 2
    vid = db.record_m5_video("t1_v1", "tpl", {"video_id": "t1_v1"},
                             [{"shot_id": "S01", "candidate_id": 3}],
                             "/x/t1_v1.mp4", {"passed": True})
    rows = db.list_m5_videos()
    assert vid >= 1 and len(rows) == 1
    assert rows[0]["video_id"] == "t1_v1" and rows[0]["shots_json"][0]["shot_id"] == "S01"
    # 幂等覆盖
    db.record_m5_video("t1_v1", "tpl", {"video_id": "t1_v1"}, [], "/x/t1_v1.mp4", {"passed": False})
    assert len(db.list_m5_videos()) == 1
    assert db.list_m5_videos()[0]["g6_json"] == {"passed": False}


# ---------------- compose_from_spec 端到端 (阶段2.3, 真跑 ffmpeg, stub TTS/ASR) ----------------

MINI_TEMPLATE = {
    "template_id": "t_m5",
    "name_zh": "迷你",
    "duration_range": [2, 10],
    "orientation": "portrait",
    "variables": {"p": "毛肚"},
    "numbers": {"price": "39.9"},
    "scenes": [
        {"slot": "a", "narrative_slot": "n1", "duration_sec": 2.0, "role": "hook",
         "narration": "{p}来了"},
        {"slot": "b", "narrative_slot": "cta", "duration_sec": 2.0, "role": "cta",
         "background": {"type": "solid", "color": "0x123456"}, "narration": "只要{price}"},
    ],
}


@pytest.fixture
def m5_root(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "templates" / "narrative").mkdir(parents=True)
    (tmp_path / "workdir").mkdir()
    (tmp_path / "models" / "whisper").mkdir(parents=True)
    write_json(tmp_path / "templates" / "narrative" / "t_m5.json", MINI_TEMPLATE)
    monkeypatch.setenv("CRADLE_ROOT", str(tmp_path))
    return tmp_path


@requires_ffmpeg
def test_compose_from_spec_e2e_records_ledger(m5_root, db):
    import subprocess

    import numpy as np
    from src.compose import parse_rate
    from src.gen.common import write_frames_mp4
    from src.orchestrator import compose_from_spec

    v1 = m5_root / "cand.mp4"
    write_frames_mp4([np.full((32, 32, 3), 200, dtype="uint8")] * 32, 16, str(v1))
    db.ingest_task("S01", "n1", "first_frame_i2v", _card())
    db.add_candidate("S01", str(v1), gate_json={g: make_gate(g, True, 0.9) for g in GATE_IDS},
                     verdict="pass", overall_score=0.9)
    db.update_candidate(1, selected=True)

    def tts_stub(text, out_path, rate="-10%"):
        d = max(0.2, 1.3 / (1.0 + parse_rate(rate) / 100.0))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", f"sine=frequency=440:duration={d:.3f}", "-ar", "44100", "-ac", "2",
                        "-f", "wav", out_path], check=True, capture_output=True, text=True, timeout=60)

    spec = {"video_id": "t1_seeding_v1", "template": "t_m5", "slots": {"a": "S01"},
            "variables": {"p": "虾滑"}, "numbers": {"price": "45.9"}, "bgm": False}
    r = compose_from_spec(db, spec, tts_fn=tts_stub, asr_fn=lambda wav: "虾滑来了只要四十五点九")
    assert Path(r["path"]).exists()
    assert (r["g6"] or {}).get("passed") is True  # 逐字+CER 双过
    assert r["shots"][0]["shot_id"] == "S01" and r["shots"][0]["gates"]["G3"]["passed"]
    # 台账落库
    rows = db.list_m5_videos()
    assert len(rows) == 1 and rows[0]["video_id"] == "t1_seeding_v1"
    assert rows[0]["spec_json"]["variables"]["p"] == "虾滑"
    # 中间件归置: output 只留成片与 ass
    out_dir = m5_root / "output"
    stray = [p.name for p in out_dir.glob("t1_seeding_v1.mp4.*")
             if p.suffix in (".mp3", ".m4a", ".wav")]
    assert stray == []
    assert (m5_root / "workdir" / "m5_intermediate").exists()


def test_compose_from_spec_missing_slot_raises(m5_root, db):
    from src.orchestrator import compose_from_spec

    spec = {"video_id": "x1", "template": "t_m5", "slots": {}}
    with pytest.raises(ValueError):
        compose_from_spec(db, spec, tts_fn=lambda t, p, rate="-10%": None)
