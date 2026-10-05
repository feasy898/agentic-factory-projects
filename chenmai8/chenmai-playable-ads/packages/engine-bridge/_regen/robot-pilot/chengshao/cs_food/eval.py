"""cs_food 合成自检 eval（cs_food spec §5 ②；无硬件可跑）。

精确命令（cwd = chengshao 包根）::

    ../.venv/Scripts/python.exe -m cs_food.eval --report reports/food_eval.json
    → exit 0 且报告 self_check=True

自检内容：勺检 8 例（4 食物 4 空）全对、3 码全检出、选碗命中、
空图返回 None、未登记码忽略、过小码被 min_side_px 过滤。

真实帧 eval（``--data assets/spoon_frames``，脚本舀取运行采集的腕部帧）为 D4 后条目：
启发式基线准确率仅记录不设硬线。当前帧目录为空（.gitkeep 占位）→ 跳过真实帧评分，
仅统计帧数；标注格式（文件名→标签的约定）未在 spec 中定义，落地 D4 时补。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))  # 允许真实帧扩展复用仓库内资产

import cv2
import numpy as np

from .bowls import BowlSelector
from .spoons import HeuristicSpoonClassifier

# 与冻结测试同一套合成图构造（合成食物 4 正 4 负；灰底=不锈钢勺面近似）
_SIDE = 200
_FOOD_HSV = [(20, 180, 200), (140, 150, 170), (60, 160, 150), (8, 170, 120)]
_EMPTY_V = [190, 200, 215, 230]


def _hsv_to_bgr(h: int, s: int, v: int) -> tuple[int, int, int]:
    bgr = cv2.cvtColor(np.uint8([[[h, s, v]]]), cv2.COLOR_HSV2BGR)[0, 0]
    return int(bgr[0]), int(bgr[1]), int(bgr[2])


def _base_gray(v: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    crop = np.full((_SIDE, _SIDE, 3), v, np.uint8)
    return np.clip(crop + rng.normal(0, 5, crop.shape).astype(np.int16), 0, 255).astype(np.uint8)


def _food_crop(hsv: tuple[int, int, int], seed: int) -> np.ndarray:
    crop = _base_gray(200, seed)
    cv2.circle(crop, (_SIDE // 2, _SIDE // 2), 55, _hsv_to_bgr(*hsv), -1)
    return crop


def _place_marker(scene: np.ndarray, marker_id: int, side: int, x: int, y: int) -> None:
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    tile = cv2.aruco.generateImageMarker(dictionary, marker_id, side)
    scene[y : y + side, x : x + side] = cv2.cvtColor(tile, cv2.COLOR_GRAY2BGR)


def _spoon_cases() -> tuple[int, int, int, int]:
    """→ (总例数, 食物正例对数, 空勺例数, 空勺对数)。"""
    classifier = HeuristicSpoonClassifier(ts_ns_source=lambda: 1)
    food_ok = sum(
        classifier.from_bgr(_food_crop(hsv, seed=i + 1)).has_food is True
        for i, hsv in enumerate(_FOOD_HSV)
    )
    empty_ok = sum(
        classifier.from_bgr(_base_gray(v, seed=9)).has_food is False for v in _EMPTY_V
    )
    return len(_FOOD_HSV) + len(_EMPTY_V), food_ok, len(_EMPTY_V), empty_ok


def _bowl_cases() -> dict:
    selector = BowlSelector()
    scene = np.full((480, 640, 3), 90, np.uint8)
    _place_marker(scene, 0, 80, 60, 60)
    _place_marker(scene, 1, 120, 220, 200)  # 最大 → 应选中
    _place_marker(scene, 2, 100, 420, 90)
    markers = selector.detect(scene)
    ids = {m.marker_id for m in markers}

    empty_scene = np.full((480, 640, 3), 90, np.uint8)
    unregistered = np.full((480, 640, 3), 90, np.uint8)
    _place_marker(unregistered, 5, 150, 100, 100)  # 表外码（尺寸足够大，确保"被检出后被忽略"）
    tiny = np.full((480, 640, 3), 90, np.uint8)
    _place_marker(tiny, 0, 14, 100, 100)  # 14px < min_side_px=20
    return {
        "aruco_registered_detected": len(ids & {0, 1, 2}),
        "aruco_registered_total": 3,
        "select_hit": selector.select(scene) == 1,
        "select_hit_expect": 1,
        "empty_scene_none": selector.select(empty_scene) is None,
        "unregistered_ignored": selector.select(unregistered) is None,
        "small_marker_filtered": selector.detect(tiny) == [],
    }


def _count_real_frames(data_dir: Path | None) -> int:
    if data_dir is None or not data_dir.is_dir():
        return 0
    return sum(1 for p in data_dir.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cs_food.eval", description="cs_food 合成自检（无硬件）")
    parser.add_argument("--report", default="reports/food_eval.json", help="报告输出路径（相对 cwd）")
    parser.add_argument("--data", default=None, help="真实腕部帧目录（D4 后条目；空目录则跳过评分）")
    args = parser.parse_args(argv)

    total, food_ok, empty_n, empty_ok = _spoon_cases()
    bowls = _bowl_cases()
    real_frames = _count_real_frames(Path(args.data) if args.data else None)

    bowl_all_ok = (
        bowls["aruco_registered_detected"] == bowls["aruco_registered_total"]
        and bowls["select_hit"]
        and bowls["empty_scene_none"]
        and bowls["unregistered_ignored"]
        and bowls["small_marker_filtered"]
    )
    self_check = food_ok == 4 and empty_ok == empty_n and bowl_all_ok

    report = {
        "module": "cs_food",
        "date": date.today().isoformat(),
        "cmd": "python -m cs_food.eval --report reports/food_eval.json  (cwd=chengshao 包根)",
        "self_check": bool(self_check),
        "metrics": {
            "spoon_cases": total,
            "spoon_correct": food_ok + empty_ok,
            "food_cases": 4,
            "food_correct": food_ok,
            "empty_cases": empty_n,
            "empty_correct": empty_ok,
            **bowls,
            "real_frames": real_frames,
            "real_frames_note": "D4 后条目：启发式基线准确率仅记录不设硬线；帧目录空 → 未评分",
        },
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"cs_food eval: self_check={self_check} -> {report_path}")
    return 0 if self_check else 1


if __name__ == "__main__":
    sys.exit(main())
