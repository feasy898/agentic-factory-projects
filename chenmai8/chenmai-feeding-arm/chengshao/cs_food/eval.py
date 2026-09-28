"""cs_food eval 入口（开发指令 §5.5）::

    python -m chengshao.cs_food.eval [--data DIR] [--report PATH]   # 仓库根运行
    # 等价：PYTHONPATH=chengshao python -m cs_food.eval ...

- 无 --data：跑合成自检集（程序化绘制的勺上帧与基准码场景），验证启发式实现、
  基准码选碗与 config 装载链路——pre-hardware 阶段判据。
- --data DIR：对目录内真实帧（脚本舀取运行采集的腕部相机帧）跑启发式，
  基线准确率仅记录不设硬线；学习型分类器 ≥90% 的硬线延后启用。

退出码 0 = pass；证据 JSON 落 --report（默认 reports/food_eval.json），
字段满足 §10.2：{module, date, cmd, metrics, thresholds, pass}。
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
from .config import DEFAULT_BOWL_CONFIG_PATH, DEFAULT_FOOD_CONFIG_PATH
from .spoons import HeuristicSpoonClassifier

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT = Path(__file__).resolve().parents[1] / "reports" / "food_eval.json"

# 合成自检集参数（固定种子，可复现）
_SIDE = 200  # 勺上裁剪边长（px）
_BLOB_RADIUS = 55  # 食物色斑块半径（px）→ 占比 ≈ 0.24，明显高于缺省阈值 0.15
_RNG = np.random.default_rng(7)

# 合成食物色（OpenCV HSV 8bit）：橙（南瓜粥类）、紫（芋泥类）、绿（菜泥类）、棕红（肉泥类）
_FOOD_HSV = [(20, 180, 200), (140, 150, 170), (60, 160, 150), (8, 170, 120)]


def _make_food_crop(hsv: tuple[int, int, int]) -> np.ndarray:
    """灰底勺面 + 食物色圆斑 + 轻噪声的合成勺上帧。"""
    bgr = cv2.cvtColor(np.uint8([[list(hsv)]]), cv2.COLOR_HSV2BGR)[0, 0]
    crop = np.full((_SIDE, _SIDE, 3), 200, np.uint8)
    crop = crop + _RNG.normal(0, 5, crop.shape).astype(np.int16)
    crop = np.clip(crop, 0, 255).astype(np.uint8)
    cv2.circle(crop, (_SIDE // 2, _SIDE // 2), _BLOB_RADIUS, bgr.tolist(), -1)
    return crop


def _make_empty_crop(background_v: int = 200) -> np.ndarray:
    """无食物合成帧：低饱和灰底（不锈钢勺/浅色瓷面近似）+ 轻噪声。"""
    crop = np.full((_SIDE, _SIDE, 3), background_v, np.uint8)
    crop = crop + _RNG.normal(0, 5, crop.shape).astype(np.int16)
    return np.clip(crop, 0, 255).astype(np.uint8)


def _make_bowl_scene(side_lengths: dict[int, int], origin_xy=(60, 60), gap=60) -> np.ndarray:
    """合成场景图：在桌面灰底上摆放若干基准码。"""
    scene = np.full((480, 640, 3), 90, np.uint8)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    x, y = origin_xy
    for marker_id, side in side_lengths.items():
        tile = cv2.aruco.generateImageMarker(dictionary, marker_id, side)
        bgr = cv2.cvtColor(tile, cv2.COLOR_GRAY2BGR)
        scene[y : y + side, x : x + side] = bgr
        x += side + gap
        if x + side > scene.shape[1]:  # 换行
            x, y = origin_xy[0], y + side + gap
    return scene


def _run_synthetic(classifier: HeuristicSpoonClassifier, selector: BowlSelector) -> dict:
    """合成自检：勺上判定应 8/8 全对；基准码应 3/3 检出且选择正确。"""
    tp = tn = 0
    food_cases = [_make_food_crop(hsv) for hsv in _FOOD_HSV]
    empty_cases = [_make_empty_crop(v) for v in (190, 200, 215, 230)]
    for crop, expect in [(c, True) for c in food_cases] + [(c, False) for c in empty_cases]:
        check = classifier.from_bgr(crop)
        if expect and check.has_food:
            tp += 1
        if (not expect) and (not check.has_food):
            tn += 1

    scene = _make_bowl_scene({0: 80, 1: 120, 2: 100})  # 1 号码最大 → 应选碗 1
    markers = selector.detect(scene)
    selected = selector.select(scene)
    empty_scene_ok = selector.select(_make_empty_crop(90)) is None
    unknown_scene_ok = selector.select(_make_bowl_scene({5: 100})) is None  # 未登记码

    return {
        "spoon_cases": len(food_cases) + len(empty_cases),
        "spoon_tp": tp,
        "spoon_tn": tn,
        "spoon_accuracy": (tp + tn) / (len(food_cases) + len(empty_cases)),
        "aruco_registered_detected": len(markers),
        "aruco_detected_bowls": sorted(m.bowl_index for m in markers),
        "aruco_selected_bowl": selected,
        "aruco_select_correct": selected == 1,
        "aruco_none_on_empty": empty_scene_ok,
        "aruco_ignore_unregistered": unknown_scene_ok,
    }


def _run_real_frames(classifier: HeuristicSpoonClassifier, data_dir: Path) -> dict:
    """真实帧基线记录：逐帧跑启发式，只记录不判准确率（无人工标签）。"""
    exts = {".png", ".jpg", ".jpeg", ".bmp"}
    files = sorted(p for p in data_dir.iterdir() if p.suffix.lower() in exts)
    if not files:
        raise ValueError(f"--data 目录中没有图像帧: {data_dir}")
    scores: list[float] = []
    latencies_ms: list[float] = []
    food_frames = 0
    for path in files:
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"帧读取失败: {path}")
        t0 = time.perf_counter_ns()
        check = classifier.from_bgr(img)
        latencies_ms.append((time.perf_counter_ns() - t0) / 1e6)
        scores.append(check.score)
        food_frames += int(check.has_food)
    return {
        "frames": len(files),
        "food_frames": food_frames,
        "food_frame_ratio": food_frames / len(files),
        "mean_score": float(np.mean(scores)),
        "mean_latency_ms": float(np.mean(latencies_ms)),
        "max_latency_ms": float(np.max(latencies_ms)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="cs_food eval（§5.5）")
    parser.add_argument("--data", type=Path, default=None, help="真实帧目录（缺省跑合成自检集）")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="报告 JSON 输出路径")
    parser.add_argument("--food-config", type=Path, default=DEFAULT_FOOD_CONFIG_PATH)
    parser.add_argument("--bowl-config", type=Path, default=DEFAULT_BOWL_CONFIG_PATH)
    args = parser.parse_args(argv)

    classifier = HeuristicSpoonClassifier(config_path=args.food_config)
    selector = BowlSelector(config_path=args.bowl_config)

    real_dir: Path | None = args.data
    metrics: dict = {}
    if real_dir is None:
        metrics = _run_synthetic(classifier, selector)
        thresholds = {
            "synthetic_spoon_accuracy_min": 1.0,
            "aruco_registered_detected_min": 3,
            "aruco_select_bowl_expected": 1,
            "aruco_none_on_empty": True,
            "aruco_ignore_unregistered": True,
        }
        passed = (
            metrics["spoon_accuracy"] >= thresholds["synthetic_spoon_accuracy_min"]
            and metrics["aruco_registered_detected"] >= thresholds["aruco_registered_detected_min"]
            and metrics["aruco_select_correct"]
            and metrics["aruco_none_on_empty"]
            and metrics["aruco_ignore_unregistered"]
        )
    else:
        if not real_dir.is_dir():
            print(f"--data 目录不存在: {real_dir}", file=sys.stderr)
            return 2
        metrics = _run_real_frames(classifier, real_dir)
        # 基线仅记录不设硬线（§5.5：启发式基线只记录；分类器 ≥90% 延后启用）
        thresholds = {"heuristic_baseline": "record-only", "classifier_accuracy_min": "deferred"}
        passed = metrics["frames"] > 0

    report = {
        "module": "cs_food",
        "date": date.today().isoformat(),
        "cmd": "python -m " + __package__ + ".eval " + " ".join(argv if argv is not None else sys.argv[1:]),
        "source": "real_frames" if real_dir is not None else "synthetic",
        "metrics": metrics,
        "thresholds": thresholds,
        "pass": bool(passed),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"cs_food eval: pass={report['pass']} report={args.report}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
