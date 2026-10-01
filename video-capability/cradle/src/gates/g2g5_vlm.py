"""G2 完整性 / G5 美学门禁 (VLM 契约) + 抽帧网格构建。

流程: 视频 → 均匀抽10帧 → 2×5 网格拼图 → 按 vlm_prompt.txt 契约调 VLM 能力;
非法 JSON 重试1次, 再失败按 borderline + overall_score=0.5 记 parse_failed。
"""

from __future__ import annotations

import math
import os
import subprocess
from pathlib import Path

from . import make_gate
from .g1_tech import probe_duration

VLM_PROMPT_PATH = Path(__file__).parent / "vlm_prompt.txt"
GRID_COLS, GRID_ROWS, GRID_N, GRID_CELL_W = 2, 5, 10, 192


def load_vlm_prompt() -> str:
    return VLM_PROMPT_PATH.read_text(encoding="utf-8")


# ---------------- 纯函数: 抽帧网格 argv ----------------

def build_grid_argv(video_path: str, grid_png: str, n_frames: int = GRID_N, cols: int = GRID_COLS,
                    cell_w: int = GRID_CELL_W, duration_s: float | None = None) -> list[str]:
    """均匀抽 n 帧 → 缩小 → tile 拼图。fps=n/duration 实现按时间均匀抽样。"""
    if duration_s is None:
        duration_s = probe_duration(video_path)
    rows = math.ceil(n_frames / cols)
    fps_expr = f"fps={n_frames}/{max(duration_s, 1e-6):.6f}"
    vf = f"{fps_expr},scale={cell_w}:-2,tile={cols}x{rows}"
    return [
        "ffmpeg", "-y", "-hide_banner", "-nostats", "-i", video_path,
        "-vf", vf, "-frames:v", "1", "-update", "1", grid_png,
    ]


def extract_grid(video_path: str, grid_png: str, duration_s: float | None = None, runner=None) -> str:
    runner = runner or subprocess.run
    argv = build_grid_argv(video_path, grid_png, duration_s=duration_s)
    cp = runner(argv, capture_output=True, text=True, timeout=300)
    if cp.returncode != 0 or not os.path.exists(grid_png):
        raise RuntimeError(f"抽帧网格失败: {cp.stderr[-300:]}")
    return grid_png


# ---------------- 门禁本体 ----------------

def parse_failed_review() -> dict:
    """非法 JSON 两次后的合成 borderline 评分 (SPECS §5.4)。"""
    return {
        "defects": {
            "deformed_object": 0.5, "morphing_artifact": 0.5, "flicker": 0.5, "garbled_text": 0.5,
            "subject_missing": 0.5, "unnatural_motion": 0.5, "overall_defect": 0.5,
        },
        "aesthetic": {"composition": 3, "lighting": 3, "color": 3, "appeal": 3, "overall": 3},
        "camera_match": 3,
        "overall_score": 0.5,
        "verdict": "borderline",
        "main_issue": "VLM 输出无法解析",
        "parse_failed": True,
    }


def call_vlm_with_retry(vlm_fn, grid_png: str, prompt_text: str, retry: int = 1):
    """vlm_fn(grid, prompt)->dict|json-str; 解析失败重试, 再失败返回 parse_failed 合成评分。

    返回 (review_dict, attempts, parse_failed: bool)
    """
    from ..api.vlm import parse_vlm_json

    attempts = 0
    last_err = None
    for _ in range(retry + 1):
        attempts += 1
        raw = vlm_fn(grid_png, prompt_text)
        try:
            return parse_vlm_json(raw), attempts, False
        except Exception as e:  # noqa: BLE001
            last_err = e
    _ = last_err
    synth = parse_failed_review()
    synth["attempts"] = attempts
    return synth, attempts, True


def g2_integrity(review: dict) -> dict:
    """G2: deformed/morphing/garbled_text/subject_missing 各 < 0.3。"""
    d = review.get("defects", {})
    keys = ("deformed_object", "morphing_artifact", "garbled_text", "subject_missing")
    vals = [float(d.get(k, 1.0)) for k in keys]
    passed = all(v < 0.3 for v in vals) and not review.get("parse_failed")
    worst = max(zip(keys, vals), key=lambda kv: kv[1])
    score = round(1.0 - max(vals), 4) if passed else 0.0
    return make_gate("G2", passed, score, worst=worst, defects={k: d.get(k) for k in keys},
                     parse_failed=bool(review.get("parse_failed")))


def g5_aesthetic(review: dict, vlm_overall_min: float = 0.70, vlm_defect_max: float = 0.2) -> dict:
    """G5: overall_score ≥ vlm_overall_min 且 overall_defect ≤ vlm_defect_max。"""
    s = float(review.get("overall_score", 0.0))
    od = float(review.get("defects", {}).get("overall_defect", 1.0))
    passed = (s >= vlm_overall_min) and (od <= vlm_defect_max) and not review.get("parse_failed")
    return make_gate(
        "G5", passed, round(s, 4),
        overall_score=s, overall_defect=od,
        thresholds={"overall_min": vlm_overall_min, "defect_max": vlm_defect_max},
        aesthetic=review.get("aesthetic"), camera_match=review.get("camera_match"),
        verdict=review.get("verdict"), main_issue=review.get("main_issue"),
        parse_failed=bool(review.get("parse_failed")),
    )


def run_g2g5(
    video_path: str,
    vlm_fn,
    acceptance: dict,
    grid_png: str | None = None,
    prompt_text: str | None = None,
    duration_s: float | None = None,
    grid_runner=None,
) -> tuple[dict, dict, dict]:
    """返回 (g2, g5, review)。vlm_fn(grid_path, prompt)->review(dict 或 JSON 字符串), 可注入 stub。"""
    prompt_text = prompt_text if prompt_text is not None else load_vlm_prompt()
    if grid_png is None:
        base = f"{video_path}.grid.png"
        grid_png = extract_grid(video_path, base, duration_s=duration_s, runner=grid_runner)
    review, attempts, parse_failed = call_vlm_with_retry(vlm_fn, grid_png, prompt_text)
    review["parse_failed"] = parse_failed or bool(review.get("parse_failed"))
    review["vlm_attempts"] = attempts
    acc = acceptance or {}
    g2 = g2_integrity(review)
    g5 = g5_aesthetic(review, acc.get("vlm_overall_min", 0.70), acc.get("vlm_defect_max", 0.2))
    return g2, g5, review
