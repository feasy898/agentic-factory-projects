"""cs_food eval（spec §5 / §5.1 / §5.3）。

① 合成自检（缺省，无硬件可跑）：
    ../.venv/Scripts/python.exe -m cs_food.eval --report reports/food_eval.json   (cwd=chengshao)
   → exit 0 ⇔ self_check=true：勺检 8 例（4 食物 4 空）全对、3 码全检出、
   选碗命中、空图返回 None、未登记码忽略。

② 真实帧记录（--data DIR；启发式基线不需要人工标注）：
    扫目录内 .png/.jpg/.jpeg/.bmp 按文件名排序逐帧推理、只记录；读图一律走
    _imread_u（仓库路径含中文，cv2.imread 会静默返回空）；--data 目录不存在 →
    exit 2，存在但 0 帧 → ValueError。exit 0 ⇔ pass=true ⇔ 至少读入 1 帧。

报告字段（spec §5.1）：公共键 module/date/cmd/source/metrics/thresholds；合成集
带 self_check(bool)、真实帧带 pass(bool)——两者互斥从不同时出现。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

import cv2
import numpy as np

from .bowls import BowlSelector
from .spoons import HeuristicSpoonClassifier

MODULE = "cs_food"
DEFAULT_REPORT_PATH = Path("chengshao/reports/food_eval.json")  # 缺省落点（cwd=仓库根）
FRAME_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp"}

# 合成校验点（spec §4 表：南瓜粥/菜泥/芋泥/棕红肉泥；空勺 = 低饱和灰底近似）
_FOOD_HSV_CASES = ((20, 180, 200), (60, 160, 150), (140, 150, 170), (8, 170, 120))
_EMPTY_GRAY_V = (190, 200, 215, 230)
_CROP_SIDE = 200
_FOOD_RADIUS = 55  # 占比 ≈ 0.24 > 缺省阈值 0.15

_SYNTH_THRESHOLDS = {
    "synthetic_spoon_accuracy_min": 1.0,
    "aruco_registered_detected_min": 3,
    "aruco_select_bowl_expected": 1,
    "aruco_none_on_empty": True,
    "aruco_ignore_unregistered": True,
}
_REAL_THRESHOLDS = {  # 固定（spec §5.1）
    "heuristic_baseline": "record-only",
    "classifier_accuracy_min": "deferred",
}


def _cmd_string() -> str:
    """产生本报告的精确命令（解释器 + -m 入口 + 实参原样）。"""
    return " ".join([sys.executable, "-m", "cs_food.eval", *sys.argv[1:]])


def _hsv_to_bgr(h: int, s: int, v: int) -> tuple[int, int, int]:
    bgr = cv2.cvtColor(np.uint8([[[h, s, v]]]), cv2.COLOR_HSV2BGR)[0, 0]
    return int(bgr[0]), int(bgr[1]), int(bgr[2])


def _base_gray(v: int, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    crop = np.full((_CROP_SIDE, _CROP_SIDE, 3), v, np.uint8)
    return np.clip(crop + rng.normal(0, 5, crop.shape).astype(np.int16), 0, 255).astype(np.uint8)


def _food_crop(hsv: tuple[int, int, int]) -> np.ndarray:
    crop = _base_gray(200)
    cv2.circle(crop, (_CROP_SIDE // 2, _CROP_SIDE // 2), _FOOD_RADIUS, _hsv_to_bgr(*hsv), -1)
    return crop


def _place_marker(scene: np.ndarray, marker_id: int, side: int, x: int, y: int) -> None:
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    tile = cv2.aruco.generateImageMarker(dictionary, marker_id, side)
    scene[y : y + side, x : x + side] = cv2.cvtColor(tile, cv2.COLOR_GRAY2BGR)


def _bowl_scene() -> np.ndarray:
    """3 碗 3 码合成场景（DICT_4X4_50 码贴灰底，spec §3.1 同款构造）。"""
    scene = np.full((480, 640, 3), 90, np.uint8)
    _place_marker(scene, 0, 80, 60, 60)
    _place_marker(scene, 1, 120, 220, 200)  # 最大 → 应被选中（碗 1）
    _place_marker(scene, 2, 100, 420, 90)
    return scene


def _unregistered_scene() -> np.ndarray:
    scene = np.full((480, 640, 3), 90, np.uint8)
    _place_marker(scene, 7, 150, 100, 100)  # 登记表 {0,1,2} 之外的干扰码
    return scene


def run_synthetic(report_path: Path) -> int:
    classifier = HeuristicSpoonClassifier()
    selector = BowlSelector()

    spoon_tp = spoon_tn = 0
    for hsv in _FOOD_HSV_CASES:
        if classifier.from_bgr(_food_crop(hsv)).has_food:
            spoon_tp += 1
    for v in _EMPTY_GRAY_V:
        if not classifier.from_bgr(_base_gray(v)).has_food:
            spoon_tn += 1
    spoon_cases = len(_FOOD_HSV_CASES) + len(_EMPTY_GRAY_V)
    spoon_accuracy = (spoon_tp + spoon_tn) / spoon_cases

    scene = _bowl_scene()
    markers = selector.detect(scene)
    registered_detected = len(markers)
    detected_bowls = len({m.bowl_index for m in markers})
    selected = selector.select(scene)
    select_correct = selected == _SYNTH_THRESHOLDS["aruco_select_bowl_expected"]
    none_on_empty = selector.select(np.full((480, 640, 3), 90, np.uint8)) is None
    unreg_markers = selector.detect(_unregistered_scene())
    ignore_unregistered = not unreg_markers and selector.select(_unregistered_scene()) is None

    metrics = {
        "spoon_cases": spoon_cases,
        "spoon_tp": spoon_tp,
        "spoon_tn": spoon_tn,
        "spoon_accuracy": spoon_accuracy,
        "aruco_registered_detected": registered_detected,
        "aruco_detected_bowls": detected_bowls,
        "aruco_selected_bowl": selected,
        "aruco_select_correct": bool(select_correct),
        "aruco_none_on_empty": bool(none_on_empty),
        "aruco_ignore_unregistered": bool(ignore_unregistered),
    }
    self_check = bool(
        spoon_accuracy >= _SYNTH_THRESHOLDS["synthetic_spoon_accuracy_min"]
        and registered_detected >= _SYNTH_THRESHOLDS["aruco_registered_detected_min"]
        and select_correct
        and none_on_empty
        and ignore_unregistered
    )
    report = {
        "module": MODULE,
        "date": date.today().isoformat(),
        "cmd": _cmd_string(),
        "source": "synthetic",
        "metrics": metrics,
        "thresholds": dict(_SYNTH_THRESHOLDS),
        "self_check": self_check,
    }
    _write_report(report_path, report)
    print(f"[cs_food] synthetic self_check={self_check} metrics={metrics}")
    return 0 if self_check else 1


def _imread_u(path: Path) -> np.ndarray:
    """中文安全读图（np.fromfile + imdecode；cv2.imread 对含中文路径静默返回空）。"""
    buf = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"无法读取帧（解码失败或空文件）: {path}")
    return img


def run_real_frames(data_dir: Path, report_path: Path) -> int:
    if not data_dir.is_dir():
        print(f"[cs_food] --data 目录不存在: {data_dir}", file=sys.stderr)
        return 2
    frames = sorted(
        p for p in data_dir.iterdir() if p.is_file() and p.suffix.lower() in FRAME_SUFFIXES
    )
    if not frames:
        raise ValueError(f"--data 目录存在但 0 帧（{'+'.join(sorted(FRAME_SUFFIXES))}）: {data_dir}")

    classifier = HeuristicSpoonClassifier()
    scores: list[float] = []
    latencies_ms: list[float] = []
    food_frames = 0
    for frame_path in frames:
        img = _imread_u(frame_path)
        t0 = time.perf_counter_ns()
        check = classifier.from_bgr(img)
        latencies_ms.append((time.perf_counter_ns() - t0) / 1e6)
        scores.append(check.score)
        if check.has_food:
            food_frames += 1

    n = len(frames)
    metrics = {
        "frames": n,
        "food_frames": food_frames,
        "food_frame_ratio": food_frames / n,
        "mean_score": sum(scores) / n,
        "mean_latency_ms": sum(latencies_ms) / n,
        "max_latency_ms": max(latencies_ms),
    }
    passed = n >= 1  # 至少读入 1 帧（record-only）
    report = {
        "module": MODULE,
        "date": date.today().isoformat(),
        "cmd": _cmd_string(),
        "source": "real_frames",
        "metrics": metrics,
        "thresholds": dict(_REAL_THRESHOLDS),
        "pass": bool(passed),
    }
    _write_report(report_path, report)
    print(f"[cs_food] real_frames pass={passed} frames={n} food={food_frames}")
    return 0 if passed else 1


def _write_report(report_path: Path, report: dict) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cs_food.eval", description=__doc__)
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH), help="报告 JSON 落点")
    parser.add_argument("--data", default=None, help="真实帧目录（缺省跑合成自检）")
    args = parser.parse_args(argv)

    report_path = Path(args.report)
    if args.data is not None:
        return run_real_frames(Path(args.data), report_path)
    return run_synthetic(report_path)


if __name__ == "__main__":
    sys.exit(main())
