"""G2/G5 VLM 门禁: 契约解析 / 重试 / parse_failed / 阈值 / 网格 argv / CLIP 启发式。"""

from __future__ import annotations

import pytest

from src.api.vlm import clip_heuristic_review, parse_vlm_json
from src.gates.g2g5_vlm import (
    build_grid_argv,
    call_vlm_with_retry,
    g2_integrity,
    g5_aesthetic,
    load_vlm_prompt,
    parse_failed_review,
    run_g2g5,
)
from tests.conftest import make_review

ACCEPTANCE = {"vlm_overall_min": 0.70, "vlm_defect_max": 0.2}


# ---------------- 提示词全文 ----------------

def test_vlm_prompt_verbatim_from_specs():
    p = load_vlm_prompt()
    assert p.startswith("你是严格的视频质检员")
    assert p.rstrip().endswith("→ fail。")
    for token in ("deformed_object", "morphing_artifact", "garbled_text", "subject_missing",
                  "overall_defect", "aesthetic", "camera_match", "overall_score", "verdict", "main_issue",
                  "pass|borderline|fail"):
        assert token in p
    assert len(p) > 400


# ---------------- JSON 契约解析 ----------------

def test_parse_vlm_json_accepts_dict_and_json_string():
    r = make_review()
    assert parse_vlm_json(r)["overall_score"] == 0.85
    import json

    s = "```json\n" + json.dumps(r, ensure_ascii=False) + "\n```"
    assert parse_vlm_json(s)["verdict"] == "pass"
    noisy = "好的,以下是结果: " + json.dumps(r) + " 以上。"
    assert parse_vlm_json(noisy)["camera_match"] == 4


def test_parse_vlm_json_clamps_and_normalizes():
    r = make_review(overall_score=2.0, overall_defect=-1, deformed=5)
    out = parse_vlm_json(r)
    assert out["overall_score"] == 1.0
    assert out["defects"]["overall_defect"] == 0.0
    assert out["defects"]["deformed_object"] == 1.0


@pytest.mark.parametrize("mutate", [
    lambda r: r.pop("defects"),
    lambda r: r["defects"].pop("garbled_text"),
    lambda r: r.pop("aesthetic"),
    lambda r: r.update(verdict="maybe"),
    lambda r: r.update(overall_score="high"),
])
def test_parse_vlm_json_rejects_bad_contract(mutate):
    r = make_review()
    mutate(r)
    with pytest.raises(ValueError):
        parse_vlm_json(r)


def test_parse_vlm_json_rejects_garbage():
    with pytest.raises(ValueError):
        parse_vlm_json("我觉得这段视频挺好的")
    with pytest.raises(ValueError):
        parse_vlm_json("{broken json")


# ---------------- G2 完整性 ----------------

def test_g2_pass_and_fail():
    g = g2_integrity(make_review())
    assert g["passed"] is True and g["score"] == pytest.approx(0.9)
    bad = make_review(deformed=0.31)
    g2 = g2_integrity(bad)
    assert g2["passed"] is False and g2["score"] == 0.0
    edge = make_review(deformed=0.299)
    assert g2_integrity(edge)["passed"] is True


def test_g2_parse_failed_never_passes():
    r = make_review()
    r["parse_failed"] = True
    assert g2_integrity(r)["passed"] is False


# ---------------- G5 美学 ----------------

def test_g5_thresholds():
    good = g5_aesthetic(make_review(overall_score=0.85, overall_defect=0.1), **ACCEPTANCE)
    assert good["passed"] is True and good["score"] == 0.85
    low = g5_aesthetic(make_review(overall_score=0.60, overall_defect=0.1), **ACCEPTANCE)
    assert low["passed"] is False
    defect_heavy = g5_aesthetic(make_review(overall_score=0.85, overall_defect=0.3), **ACCEPTANCE)
    assert defect_heavy["passed"] is False
    failed = g5_aesthetic(make_review(overall_score=0.5, overall_defect=0.1), **ACCEPTANCE)
    assert failed["passed"] is False


# ---------------- 重试与 parse_failed 合成 ----------------

def test_call_vlm_retry_then_success():
    calls = []

    def vlm_flaky(grid, prompt):
        calls.append(1)
        if len(calls) == 1:
            return "不是JSON"
        return make_review()

    review, attempts, failed = call_vlm_with_retry(vlm_flaky, "g.png", "p")
    assert len(calls) == 2 and attempts == 2 and failed is False
    assert review["verdict"] == "pass"


def test_call_vlm_both_fail_synthetic_borderline():
    def vlm_bad(grid, prompt):
        return "还是不行"

    review, attempts, failed = call_vlm_with_retry(vlm_bad, "g.png", "p")
    assert attempts == 2 and failed is True
    assert review["verdict"] == "borderline"
    assert review["overall_score"] == 0.5
    assert review["parse_failed"] is True
    assert parse_failed_review()["overall_score"] == 0.5


def test_run_g2g5_end_to_end_with_stub():
    g2, g5, review = run_g2g5("fake.mp4", lambda grid, p: make_review(), ACCEPTANCE,
                              grid_png="precomputed.png", prompt_text="PROMPT")
    assert g2["passed"] and g5["passed"]
    assert review["parse_failed"] is False
    assert "你是严格的视频质检员" in load_vlm_prompt()  # 真提示词可加载


def test_run_g2g5_parse_failed_gates_fail():
    g2, g5, review = run_g2g5("fake.mp4", lambda grid, p: "garbage", ACCEPTANCE, grid_png="g.png")
    assert g2["passed"] is False and g5["passed"] is False
    assert review["parse_failed"] is True


# ---------------- 网格 argv ----------------

def test_build_grid_argv():
    argv = build_grid_argv("v.mp4", "g.png", duration_s=10)
    vf = argv[argv.index("-vf") + 1]
    assert vf.startswith("fps=10/10.000000")
    assert "scale=192:-2" in vf and "tile=2x5" in vf
    assert argv[argv.index("-frames:v") + 1] == "1"
    argv2 = build_grid_argv("v.mp4", "g.png", n_frames=10, cols=2, duration_s=25)
    assert "fps=10/25.000000" in argv2[argv2.index("-vf") + 1]


# ---------------- CLIP 启发式(结构+公式) ----------------

class _StubClip:
    """确定性 stub: 文本锚点 → 8维单位向量; 图像 → 可指定向量。"""

    def __init__(self, cell_vectors):
        self.names = {}
        self.cell_vectors = cell_vectors  # list of index per cell

    def text_embed(self, text):
        import numpy as np

        key = None
        for k in ("clear sharp", "deformed melted", "garbled nonsense", "pitch black",
                  "blown out", "motion blur", "beautiful appetizing"):
            if k in text:
                key = k
                break
        if key is None:
            key = "prompt"
        if key not in self.names:
            self.names[key] = len(self.names)
        v = np.zeros(16, dtype="float32")
        v[self.names[key]] = 1.0
        return v

    def image_embed(self, cell):
        import numpy as np

        idx = self.cell_vectors.pop(0) % 16
        v = np.zeros(16, dtype="float32")
        v[idx] = 1.0
        return v


def test_clip_heuristic_structure_and_formula(tmp_path):
    from PIL import Image

    grid = tmp_path / "grid.png"
    Image.new("RGB", (20, 50), "red").save(grid)  # 2x5 → 10 cells 10x10

    stub = _StubClip(cell_vectors=[0] * 10)  # 每格都命中第一个文本锚(pos)

    review = clip_heuristic_review(str(grid), prompt_text="a bowl of hotpot",
                                   image_embed=stub.image_embed, text_embed=stub.text_embed)
    assert review["model"] == "clip_heuristic"
    assert review["unreviewed_by_vlm"] is True
    assert set(review["defects"]) == {"deformed_object", "morphing_artifact", "flicker", "garbled_text",
                                      "subject_missing", "unnatural_motion", "overall_defect"}
    assert set(review["aesthetic"]) == {"composition", "lighting", "color", "appeal", "overall"}
    assert 0.0 <= review["overall_score"] <= 1.0
    expect = (0.45 * (1 - review["defects"]["overall_defect"])
              + 0.35 * (review["aesthetic"]["overall"] / 5)
              + 0.2 * (review["camera_match"] / 5))
    assert abs(review["overall_score"] - expect) < 0.02
    assert review["verdict"] in ("pass", "borderline", "fail")
