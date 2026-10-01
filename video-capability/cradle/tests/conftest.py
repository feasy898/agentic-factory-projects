"""pytest 全局: 仓库根加入 sys.path + 公共夹具。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.gates.g1_tech import has_ffmpeg  # noqa: E402

requires_ffmpeg = pytest.mark.skipif(not has_ffmpeg(), reason="ffmpeg/ffprobe 不可用")


@pytest.fixture
def valid_card() -> dict:
    """§5.2 示例镜头卡(合法)。"""
    return {
        "shot_id": "S03",
        "narrative_slot": "evidence_product",
        "lane": "first_frame_i2v",
        "orientation": "portrait",
        "duration_sec": 5,
        "resolution": [480, 832],
        "fps": 16,
        "camera": {"scale": "closeup", "angle": "high_45", "motion": "slow_push_in", "depth": "shallow"},
        "subject": {"type": "object", "desc_zh": "毛肚浸入沸腾红汤,油花翻涌,蒸汽升腾"},
        "prompt_en": "extreme close-up of beef tripe in boiling red broth, professional food photography",
        "first_frame_asset": "assets/products/maodu_01.png",
        "negative": ["human face", "hands", "fingers", "text", "watermark", "logo", "deformed", "extra limbs"],
        "n_best": 3,
        "retry_max": 2,
        "acceptance": {
            "clip_ref_min": 0.65,
            "clip_text_min": 0.22,
            "temporal_clip_min": 0.85,
            "vlm_overall_min": 0.70,
            "vlm_defect_max": 0.2,
            "duration_tol": 0.5,
        },
        "fallback": {"type": "ken_burns", "asset": "assets/products/maodu_01.png",
                     "motion": "zoom_in_1.06", "duration_sec": 5},
    }


@pytest.fixture
def db(tmp_path):
    from src.db import DB

    d = DB(tmp_path / "test.sqlite3")
    d.migrate()
    yield d
    d.close()


def make_review(overall_score=0.85, overall_defect=0.1, deformed=0.1, garbled=0.05,
                subject_missing=0.05, verdict="pass") -> dict:
    """构造符合 §5.4 契约的 VLM 评分 dict。"""
    return {
        "defects": {
            "deformed_object": deformed,
            "morphing_artifact": 0.08,
            "flicker": 0.06,
            "garbled_text": garbled,
            "subject_missing": subject_missing,
            "unnatural_motion": 0.07,
            "overall_defect": overall_defect,
        },
        "aesthetic": {"composition": 4, "lighting": 4, "color": 4, "appeal": 4, "overall": 4},
        "camera_match": 4,
        "overall_score": overall_score,
        "verdict": verdict,
        "main_issue": "无明显问题",
    }


def gates_all_pass() -> dict:
    from src.gates import make_gate

    return {g: make_gate(g, True, 0.9) for g in ("G1", "G2", "G3", "G4", "G5", "G6")}


def gates_all_fail() -> dict:
    from src.gates import make_gate

    return {g: make_gate(g, False, 0.1, why="stub fail") for g in ("G1", "G2", "G3", "G4", "G5", "G6")}


def write_json(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
