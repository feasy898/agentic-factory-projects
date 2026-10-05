"""cs_food 接口测试（合成图；开发指令 §5.5 pre-hardware eval）。

覆盖：冻结接口（SpoonClassifier Protocol / from_bgr -> SpoonCheck）、
HSV 启发式判定、config 阈值装载与校验、基准码选碗。
全部使用合成图，无相机/硬件依赖。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from chengshao.cs_food import (
    DEFAULT_BOWL_CONFIG_PATH,
    DEFAULT_FOOD_CONFIG_PATH,
    BowlSelector,
    HeuristicSpoonClassifier,
    SpoonClassifier,
    load_bowl_config,
    load_food_config,
)
from chengshao.cs_schema import SpoonCheck

_SIDE = 200  # 合成勺上裁剪边长（px）


def _hsv_to_bgr(h: int, s: int, v: int) -> tuple[int, int, int]:
    bgr = cv2.cvtColor(np.uint8([[[h, s, v]]]), cv2.COLOR_HSV2BGR)[0, 0]
    return int(bgr[0]), int(bgr[1]), int(bgr[2])


def _base_gray(v: int = 200, seed: int = 1) -> np.ndarray:
    """低饱和灰底 + 轻噪声（不锈钢勺面近似）。"""
    rng = np.random.default_rng(seed)
    crop = np.full((_SIDE, _SIDE, 3), v, np.uint8)
    return np.clip(crop + rng.normal(0, 5, crop.shape).astype(np.int16), 0, 255).astype(np.uint8)


def _make_food_crop(hsv: tuple[int, int, int], radius: int = 55, seed: int = 1) -> np.ndarray:
    """灰底 + 圆形食物色斑块（半径 55 → 占比 ≈ 0.24 > 缺省阈值 0.15）。"""
    crop = _base_gray(seed=seed)
    cv2.circle(crop, (_SIDE // 2, _SIDE // 2), radius, _hsv_to_bgr(*hsv), -1)
    return crop


def _write_food_config(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "food_hsv_custom.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_bowl_config(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "bowl_markers_custom.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _place_marker(scene: np.ndarray, marker_id: int, side: int, x: int, y: int) -> None:
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    tile = cv2.aruco.generateImageMarker(dictionary, marker_id, side)
    scene[y : y + side, x : x + side] = cv2.cvtColor(tile, cv2.COLOR_GRAY2BGR)


# ---------------------------------------------------------------------------
# 接口冻结：SpoonClassifier Protocol
# ---------------------------------------------------------------------------


def test_heuristic_satisfies_frozen_protocol() -> None:
    classifier = HeuristicSpoonClassifier()
    assert isinstance(classifier, SpoonClassifier)  # runtime_checkable Protocol
    assert callable(getattr(classifier, "from_bgr"))


def test_output_is_valid_spooncheck() -> None:
    check = HeuristicSpoonClassifier().from_bgr(_make_food_crop((20, 180, 200)))
    assert isinstance(check, SpoonCheck)
    assert isinstance(check.ts_ns, int) and check.ts_ns > 0
    assert isinstance(check.has_food, bool)
    assert 0.0 <= check.score <= 1.0
    assert check.cam_ref == "wrist_cam"  # 来自缺省 config/food_hsv.json


def test_output_json_roundtrip() -> None:
    classifier = HeuristicSpoonClassifier(ts_ns_source=lambda: 42)
    check = classifier.from_bgr(_make_food_crop((140, 150, 170)))
    restored = SpoonCheck.model_validate_json(check.model_dump_json())
    assert restored == check


# ---------------------------------------------------------------------------
# HSV 启发式判定
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("hsv", [(20, 180, 200), (140, 150, 170), (60, 160, 150), (8, 170, 120)])
def test_food_crop_detected(hsv: tuple[int, int, int]) -> None:
    check = HeuristicSpoonClassifier().from_bgr(_make_food_crop(hsv))
    assert check.has_food is True
    assert check.score >= 0.15
    assert check.score == pytest.approx(0.24, abs=0.05)


@pytest.mark.parametrize("background_v", [190, 200, 215, 230])
def test_empty_spoon_not_food(background_v: int) -> None:
    check = HeuristicSpoonClassifier().from_bgr(_base_gray(background_v, seed=2))
    assert check.has_food is False
    assert check.score < 0.05  # 低饱和灰底不应落入任何食物色区间


def test_threshold_flip_via_custom_config(tmp_path: Path) -> None:
    crop = _make_food_crop((20, 180, 200), radius=40)  # 占比 ≈ 0.126
    base = {"cam_ref": "wrist_cam", "min_food_ratio": 0.15,
            "hsv_ranges": [{"h_lo": 5, "h_hi": 35, "s_lo": 60, "v_lo": 60}]}
    strict = HeuristicSpoonClassifier(config_path=_write_food_config(tmp_path, base | {"min_food_ratio": 0.5}))
    lenient = HeuristicSpoonClassifier(config_path=_write_food_config(tmp_path, base | {"min_food_ratio": 0.10}))
    assert strict.from_bgr(crop).has_food is False  # 阈值之上不判有食物 → 宁可重舀
    assert lenient.from_bgr(crop).has_food is True


def test_score_monotone_in_food_area() -> None:
    classifier = HeuristicSpoonClassifier()
    small = classifier.from_bgr(_make_food_crop((20, 180, 200), radius=35, seed=3)).score
    large = classifier.from_bgr(_make_food_crop((20, 180, 200), radius=60, seed=3)).score
    assert large > small >= 0.0


def test_wrap_around_red_range(tmp_path: Path) -> None:
    """h_lo > h_hi 的跨 0 环绕区间生效（红色系食物）。"""
    cfg = {"cam_ref": "wrist_cam", "min_food_ratio": 0.15,
           "hsv_ranges": [{"h_lo": 175, "h_hi": 8, "s_lo": 60, "v_lo": 40}]}
    classifier = HeuristicSpoonClassifier(config_path=_write_food_config(tmp_path, cfg))
    red = _make_food_crop((2, 180, 160))
    assert classifier.from_bgr(red).has_food is True
    assert classifier.from_bgr(_base_gray(seed=4)).has_food is False


def test_deterministic_with_injected_clock() -> None:
    classifier = HeuristicSpoonClassifier(ts_ns_source=lambda: 1234567890)
    crop = _make_food_crop((140, 150, 170))
    a = classifier.from_bgr(crop)
    b = classifier.from_bgr(crop)
    assert a.model_dump() == b.model_dump()
    assert a.ts_ns == 1234567890


def test_ts_ns_is_current_wall_clock_by_default() -> None:
    before = time.time_ns()
    check = HeuristicSpoonClassifier().from_bgr(_base_gray(seed=5))
    assert before <= check.ts_ns <= time.time_ns()


@pytest.mark.parametrize(
    "bad",
    [
        None,
        np.zeros((10, 10), dtype=np.uint8),  # 2D
        np.zeros((10, 10, 4), dtype=np.uint8),  # 4 通道
        np.zeros((0, 10, 3), dtype=np.uint8),  # 空图
        np.zeros((10, 10, 3), dtype=np.float32),  # 非 uint8
        "not-an-image",
    ],
)
def test_invalid_crop_raises(bad: object) -> None:
    with pytest.raises(ValueError):
        HeuristicSpoonClassifier().from_bgr(bad)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# config 阈值装载与校验
# ---------------------------------------------------------------------------


def test_default_configs_exist_and_load() -> None:
    food = load_food_config()  # 缺省路径 config/food_hsv.json
    assert 0.0 < food.min_food_ratio <= 1.0
    assert len(food.hsv_ranges) >= 1
    bowls = load_bowl_config()  # 缺省路径 config/bowl_markers.json
    assert set(bowls.marker_to_bowl.values()) == {0, 1, 2}  # 3 碗 3 码
    assert bowls.min_side_px >= 1
    assert DEFAULT_FOOD_CONFIG_PATH.is_file() and DEFAULT_BOWL_CONFIG_PATH.is_file()


def test_custom_config_full_roundtrip(tmp_path: Path) -> None:
    cfg = {
        "cam_ref": "cam_wrist_x",
        "min_food_ratio": 0.3,
        "hsv_ranges": [{"h_lo": 10, "h_hi": 20, "s_lo": 5, "v_lo": 6}],
    }
    classifier = HeuristicSpoonClassifier(config_path=_write_food_config(tmp_path, cfg))
    assert classifier.cam_ref == "cam_wrist_x"
    assert classifier.min_food_ratio == 0.3


@pytest.mark.parametrize(
    "payload",
    [
        {"min_food_ratio": 0.15, "hsv_ranges": [{"h_lo": 0, "h_hi": 10}]},  # 缺 cam_ref
        {"cam_ref": "c", "hsv_ranges": [{"h_lo": 0, "h_hi": 10}]},  # 缺 min_food_ratio
        {"cam_ref": "c", "min_food_ratio": 0.15, "hsv_ranges": []},  # 空区间表
        {"cam_ref": "c", "min_food_ratio": 0, "hsv_ranges": [{"h_lo": 0, "h_hi": 10}]},  # 阈值 0
        {"cam_ref": "c", "min_food_ratio": 1.5, "hsv_ranges": [{"h_lo": 0, "h_hi": 10}]},  # 阈值 >1
        {"cam_ref": "", "min_food_ratio": 0.15, "hsv_ranges": [{"h_lo": 0, "h_hi": 10}]},  # 空 cam_ref
        {"cam_ref": "c", "min_food_ratio": 0.15, "hsv_ranges": [{"h_lo": 200, "h_hi": 10}]},  # H 超域
        {"cam_ref": "c", "min_food_ratio": 0.15, "hsv_ranges": [{"h_lo": 0, "h_hi": 10, "s_lo": 200, "s_hi": 100}]},  # s_lo>s_hi
        {"cam_ref": "c", "min_food_ratio": 0.15, "hsv_ranges": [{"h_lo": 0, "h_hi": 10}], "extra": 1},  # 未声明字段
    ],
)
def test_invalid_food_config_raises(tmp_path: Path, payload: dict) -> None:
    with pytest.raises(ValueError):
        load_food_config(_write_food_config(tmp_path, payload))


@pytest.mark.parametrize(
    "payload",
    [
        {"dictionary": "DICT_4X4_50", "marker_to_bowl": {"0": 0}},  # 缺 cam_ref
        {"cam_ref": "c", "marker_to_bowl": {"0": 0}},  # 缺 dictionary
        {"cam_ref": "c", "dictionary": "NOT_A_DICT"},  # 字典名不存在
        {"cam_ref": "c", "dictionary": "DICT_4X4_50"},  # 缺 marker_to_bowl
        {"cam_ref": "c", "dictionary": "DICT_4X4_50", "marker_to_bowl": {}},  # 空映射
        {"cam_ref": "c", "dictionary": "DICT_4X4_50", "marker_to_bowl": {"0": 0}, "min_side_px": 0},  # 边长 0
        {"cam_ref": "c", "dictionary": "DICT_4X4_50", "marker_to_bowl": {"0": -1}},  # 碗序号负
        {"cam_ref": "c", "dictionary": "DICT_4X4_50", "marker_to_bowl": {"0": 0, "1": 0}},  # 一碗双码
        {"cam_ref": "c", "dictionary": "DICT_4X4_50", "marker_to_bowl": {"x": 0}},  # 键非整数
    ],
)
def test_invalid_bowl_config_raises(tmp_path: Path, payload: dict) -> None:
    with pytest.raises(ValueError):
        load_bowl_config(_write_bowl_config(tmp_path, payload))


def test_missing_config_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        load_food_config(tmp_path / "nope.json")


# ---------------------------------------------------------------------------
# 基准码选碗（ArUco，3 碗 3 码）
# ---------------------------------------------------------------------------


def _scene_with_three_bowls() -> np.ndarray:
    scene = np.full((480, 640, 3), 90, np.uint8)
    _place_marker(scene, 0, 80, 60, 60)
    _place_marker(scene, 1, 120, 220, 200)  # 最大 → 应被选中
    _place_marker(scene, 2, 100, 420, 90)
    return scene


def test_three_bowls_detected() -> None:
    selector = BowlSelector()
    markers = selector.detect(_scene_with_three_bowls())
    assert {m.marker_id for m in markers} == {0, 1, 2}
    assert {m.bowl_index for m in markers} == {0, 1, 2}
    assert selector.cam_ref == "scene_cam"  # 来自缺省 config/bowl_markers.json


def test_select_largest_marker() -> None:
    selector = BowlSelector()
    assert selector.select(_scene_with_three_bowls()) == 1  # 边长最大者（离得最近）
    markers = selector.detect(_scene_with_three_bowls())
    assert markers[0].marker_id == 1  # detect 按边长降序


def test_select_none_on_empty_scene() -> None:
    selector = BowlSelector()
    assert selector.detect(np.full((480, 640, 3), 90, np.uint8)) == []
    assert selector.select(np.full((480, 640, 3), 90, np.uint8)) is None


def test_unregistered_marker_ignored() -> None:
    scene = np.full((480, 640, 3), 90, np.uint8)
    _place_marker(scene, 5, 150, 100, 100)  # 已登记表外的码
    selector = BowlSelector()
    assert selector.detect(scene) == []
    assert selector.select(scene) is None


def test_small_marker_filtered_by_min_side() -> None:
    scene = np.full((480, 640, 3), 90, np.uint8)
    _place_marker(scene, 0, 14, 100, 100)  # 14px < min_side_px=20
    selector = BowlSelector()
    assert selector.detect(scene) == []


def test_gray_input_supported() -> None:
    selector = BowlSelector()
    gray = cv2.cvtColor(_scene_with_three_bowls(), cv2.COLOR_BGR2GRAY)
    assert len(selector.detect(gray)) == 3


@pytest.mark.parametrize(
    "bad",
    [
        None,
        np.zeros((10, 10), dtype=np.float32),
        np.zeros((10, 10, 2), dtype=np.uint8),
        np.zeros((0, 10), dtype=np.uint8),
    ],
)
def test_invalid_scene_raises(bad: object) -> None:
    with pytest.raises(ValueError):
        BowlSelector().detect(bad)  # type: ignore[arg-type]


def test_marker_centers_are_pixel_coords() -> None:
    selector = BowlSelector()
    for m in selector.detect(_scene_with_three_bowls()):
        x, y = m.center_px
        assert 0 <= x < 640 and 0 <= y < 480
        assert m.side_px >= 20.0
