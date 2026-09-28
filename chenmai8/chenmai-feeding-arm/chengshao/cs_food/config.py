"""cs_food 配置装载与校验（开发指令 §5.5 / §10.4）。

原则：config/ 只放结构与默认值，不放密钥与机器相关路径；
勺上判定阈值可调且偏保守（宁可重舀，不空勺到口）。

两个配置文件（缺省路径如下，可由调用方传入其他路径覆盖）：
- config/food_hsv.json      勺上食物 HSV 区间与判定阈值
- config/bowl_markers.json  场景相机碗标记映射（基准码字典与编号表）

校验失败一律抛 ValueError，错误信息带字段名（eval 与测试依赖该行为）；
未声明的键视为拼写漂移，同样拒绝（与 cs_schema 的 extra="forbid" 同纪律）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
DEFAULT_FOOD_CONFIG_PATH = CONFIG_DIR / "food_hsv.json"
DEFAULT_BOWL_CONFIG_PATH = CONFIG_DIR / "bowl_markers.json"

_CAM_REF_MAX_LEN = 64
_H_MAX = 179  # 8bit OpenCV HSV：H ∈ [0,179]
_SV_MAX = 255  # S/V ∈ [0,255]


@dataclass(frozen=True)
class HSVRange:
    """一段食物色 HSV 区间（8bit OpenCV 约定：H∈[0,179]，S/V∈[0,255]）。

    h_lo > h_hi 表示跨 0 环绕（红色系），生效域为 [h_lo,179] ∪ [0,h_hi]。
    """

    h_lo: int
    h_hi: int
    s_lo: int = 0
    s_hi: int = _SV_MAX
    v_lo: int = 0
    v_hi: int = _SV_MAX

    def validate(self) -> None:
        for name in ("h_lo", "h_hi"):
            v = getattr(self, name)
            if not (0 <= v <= _H_MAX):
                raise ValueError(f"hsv_ranges.{name}={v} 超出 [0,{_H_MAX}]")
        for name in ("s_lo", "s_hi", "v_lo", "v_hi"):
            v = getattr(self, name)
            if not (0 <= v <= _SV_MAX):
                raise ValueError(f"hsv_ranges.{name}={v} 超出 [0,{_SV_MAX}]")
        if self.s_lo > self.s_hi:
            raise ValueError(f"hsv_ranges.s_lo={self.s_lo} 不得大于 s_hi={self.s_hi}")
        if self.v_lo > self.v_hi:
            raise ValueError(f"hsv_ranges.v_lo={self.v_lo} 不得大于 v_hi={self.v_hi}")


@dataclass(frozen=True)
class FoodConfig:
    """勺上检查配置：来源相机标识 + 判定阈值 + 食物色区间表。"""

    cam_ref: str
    min_food_ratio: float
    hsv_ranges: tuple[HSVRange, ...]


@dataclass(frozen=True)
class BowlConfig:
    """选碗配置：来源相机标识 + 基准码字典名 + 码→碗映射 + 最小码边长（px）。"""

    cam_ref: str
    dictionary: str
    marker_to_bowl: dict[int, int]
    min_side_px: int


def _read_json(path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f"配置文件不存在: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"配置文件不是合法 JSON: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise ValueError(f"配置文件顶层必须是对象: {path}")
    return data


def _check_keys(data: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"{where} 存在未声明字段: {unknown}")


def _check_cam_ref(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}.cam_ref 必须是非空字符串")
    if len(value) > _CAM_REF_MAX_LEN:
        raise ValueError(f"{where}.cam_ref 长度超过 {_CAM_REF_MAX_LEN}")
    return value


def load_food_config(path: str | Path | None = None) -> FoodConfig:
    """装载勺上检查配置；path=None 用缺省 config/food_hsv.json。"""
    file_path = Path(path) if path is not None else DEFAULT_FOOD_CONFIG_PATH
    data = _read_json(file_path)
    _check_keys(data, {"cam_ref", "min_food_ratio", "hsv_ranges"}, "food_hsv")

    cam_ref = _check_cam_ref(data.get("cam_ref"), "food_hsv")

    ratio = data.get("min_food_ratio")
    if not isinstance(ratio, (int, float)) or isinstance(ratio, bool):
        raise ValueError("food_hsv.min_food_ratio 必须是数值")
    ratio = float(ratio)
    if not (0.0 < ratio <= 1.0):
        raise ValueError(f"food_hsv.min_food_ratio={ratio} 必须在 (0, 1] 内（偏保守判定）")

    raw_ranges = data.get("hsv_ranges")
    if not isinstance(raw_ranges, list) or not raw_ranges:
        raise ValueError("food_hsv.hsv_ranges 必须是非空数组")
    ranges: list[HSVRange] = []
    for i, item in enumerate(raw_ranges):
        if not isinstance(item, dict):
            raise ValueError(f"hsv_ranges[{i}] 必须是对象")
        _check_keys(item, {"h_lo", "h_hi", "s_lo", "s_hi", "v_lo", "v_hi"}, f"hsv_ranges[{i}]")
        values: dict[str, int] = {}
        for key, default in (("h_lo", None), ("h_hi", None), ("s_lo", 0), ("s_hi", _SV_MAX), ("v_lo", 0), ("v_hi", _SV_MAX)):
            v = item.get(key, default)
            if not isinstance(v, int) or isinstance(v, bool):
                raise ValueError(f"hsv_ranges[{i}].{key} 必须是整数")
            values[key] = v
        if values["h_lo"] is None or values["h_hi"] is None:  # pragma: no cover - 上方已拦截
            raise ValueError(f"hsv_ranges[{i}] 缺少 h_lo/h_hi")
        rng = HSVRange(
            h_lo=values["h_lo"], h_hi=values["h_hi"],
            s_lo=values["s_lo"], s_hi=values["s_hi"],
            v_lo=values["v_lo"], v_hi=values["v_hi"],
        )
        rng.validate()
        ranges.append(rng)

    return FoodConfig(cam_ref=cam_ref, min_food_ratio=ratio, hsv_ranges=tuple(ranges))


def load_bowl_config(path: str | Path | None = None) -> BowlConfig:
    """装载选碗配置；path=None 用缺省 config/bowl_markers.json。"""
    file_path = Path(path) if path is not None else DEFAULT_BOWL_CONFIG_PATH
    data = _read_json(file_path)
    _check_keys(data, {"cam_ref", "dictionary", "marker_to_bowl", "min_side_px"}, "bowl_markers")

    cam_ref = _check_cam_ref(data.get("cam_ref"), "bowl_markers")

    dict_name = data.get("dictionary")
    if not isinstance(dict_name, str) or not hasattr(cv2.aruco, dict_name):
        raise ValueError(f"bowl_markers.dictionary={dict_name!r} 不是可用的基准码字典名")

    raw_map = data.get("marker_to_bowl")
    if not isinstance(raw_map, dict) or not raw_map:
        raise ValueError("bowl_markers.marker_to_bowl 必须是非空对象")
    mapping: dict[int, int] = {}
    for key, value in raw_map.items():
        try:
            marker_id = int(key)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"marker_to_bowl 键 {key!r} 不是整数") from exc
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"marker_to_bowl[{marker_id}]={value!r} 必须是非负整数")
        if marker_id < 0:
            raise ValueError(f"marker_to_bowl 键 {marker_id} 必须非负")
        mapping[marker_id] = value
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("marker_to_bowl 的碗序号出现重复（一码一碗）")

    min_side = data.get("min_side_px")
    if not isinstance(min_side, int) or isinstance(min_side, bool) or min_side < 1:
        raise ValueError("bowl_markers.min_side_px 必须是 ≥1 的整数")

    return BowlConfig(
        cam_ref=cam_ref, dictionary=dict_name, marker_to_bowl=mapping, min_side_px=min_side
    )


__all__ = [
    "BowlConfig",
    "CONFIG_DIR",
    "DEFAULT_BOWL_CONFIG_PATH",
    "DEFAULT_FOOD_CONFIG_PATH",
    "FoodConfig",
    "HSVRange",
    "load_bowl_config",
    "load_food_config",
]
