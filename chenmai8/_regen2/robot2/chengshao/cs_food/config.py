"""cs_food 配置装载与校验（spec §4）。

- config/food_hsv.json：cam_ref / min_food_ratio / 6 段 HSV 区间
  （JSON 每段只写 h_lo/h_hi/s_lo/v_lo，s_hi/v_hi 缺省补 255）。
- config/bowl_markers.json：cam_ref / dictionary / marker_to_bowl / min_side_px。
- 校验失败一律抛 ValueError 且错误信息带字段名；未声明键视为拼写漂移同样拒绝
  （与 cs_schema extra="forbid" 同纪律）；min_food_ratio ∈ (0,1] 数值；
  区间值必须整数且在域内（H∈[0,179]、S/V∈[0,255]）、s_lo≤s_hi、v_lo≤v_hi；
  dictionary 必须是 cv2.aruco 可用名。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2

# config.py 位于 <仓库根>/chengshao/cs_food/ 下
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FOOD_CONFIG_PATH = REPO_ROOT / "config" / "food_hsv.json"
DEFAULT_BOWL_CONFIG_PATH = REPO_ROOT / "config" / "bowl_markers.json"

_H_MAX = 179  # 8bit OpenCV HSV：H∈[0,179]、S/V∈[0,255]
_SV_MAX = 255

_FOOD_KEYS = {"cam_ref", "min_food_ratio", "hsv_ranges"}
_RANGE_KEYS = {"h_lo", "h_hi", "s_lo", "s_hi", "v_lo", "v_hi"}
_BOWL_KEYS = {"cam_ref", "dictionary", "marker_to_bowl", "min_side_px"}


@dataclass(frozen=True)
class HsvRange:
    """单段 HSV 闭区间端点。"""

    h_lo: int
    h_hi: int
    s_lo: int
    s_hi: int
    v_lo: int
    v_hi: int

    @property
    def wraps_around(self) -> bool:
        """h_lo > h_hi 表示跨 0 环绕（红色系）。"""
        return self.h_lo > self.h_hi


@dataclass(frozen=True)
class FoodConfig:
    cam_ref: str
    min_food_ratio: float
    hsv_ranges: tuple[HsvRange, ...]


@dataclass(frozen=True)
class BowlConfig:
    cam_ref: str
    dictionary: str
    marker_to_bowl: dict[int, int]
    min_side_px: float


def _load_json(path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f"配置文件不存在: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"配置文件不可读或非法 JSON: {path} ({exc})") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"配置顶层必须是 JSON 对象: {path}")
    return payload


def _reject_unknown(payload: dict, allowed: set[str], where: str) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"{where}: 未声明字段（拼写漂移拒绝）: {', '.join(unknown)}")


def _require(payload: dict, key: str, where: str) -> object:
    if key not in payload:
        raise ValueError(f"{where}: 缺少必填字段 {key}")
    return payload[key]


def _as_int(value: object, field: str, where: str) -> int:
    # bool 是 int 子类，显式排除
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{where}: {field} 必须是整数，得到 {value!r}")
    return value


def load_food_config(path: str | Path | None = None) -> FoodConfig:
    """装载并校验 food_hsv 配置（缺省 config/food_hsv.json）。"""
    where = "food_hsv"
    payload = _load_json(Path(path) if path is not None else DEFAULT_FOOD_CONFIG_PATH)
    _reject_unknown(payload, _FOOD_KEYS, where)

    cam_ref = _require(payload, "cam_ref", where)
    if not isinstance(cam_ref, str) or not cam_ref:
        raise ValueError(f"{where}: cam_ref 必须是非空字符串，得到 {cam_ref!r}")

    min_food_ratio = _require(payload, "min_food_ratio", where)
    if isinstance(min_food_ratio, bool) or not isinstance(min_food_ratio, (int, float)):
        raise ValueError(f"{where}: min_food_ratio 必须是数值，得到 {min_food_ratio!r}")
    if not 0.0 < float(min_food_ratio) <= 1.0:
        raise ValueError(f"{where}: min_food_ratio 必须 ∈(0,1]，得到 {min_food_ratio!r}")

    ranges_raw = _require(payload, "hsv_ranges", where)
    if not isinstance(ranges_raw, list) or not ranges_raw:
        raise ValueError(f"{where}: hsv_ranges 必须是非空区间表")
    ranges: list[HsvRange] = []
    for i, raw in enumerate(ranges_raw):
        ranges.append(_parse_range(raw, f"{where}.hsv_ranges[{i}]"))
    return FoodConfig(cam_ref=cam_ref, min_food_ratio=float(min_food_ratio),
                      hsv_ranges=tuple(ranges))


def _parse_range(raw: object, where: str) -> HsvRange:
    if not isinstance(raw, dict):
        raise ValueError(f"{where}: 区间必须是对象，得到 {raw!r}")
    _reject_unknown(raw, _RANGE_KEYS, where)

    h_lo = _as_int(_require(raw, "h_lo", where), "h_lo", where)
    h_hi = _as_int(_require(raw, "h_hi", where), "h_hi", where)
    # s_hi/v_hi 未写时缺省补 255（spec §4，代码为权威）；s_lo/v_lo 未写取域下界 0
    s_lo = _as_int(raw.get("s_lo", 0), "s_lo", where)
    s_hi = _as_int(raw.get("s_hi", _SV_MAX), "s_hi", where)
    v_lo = _as_int(raw.get("v_lo", 0), "v_lo", where)
    v_hi = _as_int(raw.get("v_hi", _SV_MAX), "v_hi", where)

    for name, value, lo, hi in (
        ("h_lo", h_lo, 0, _H_MAX), ("h_hi", h_hi, 0, _H_MAX),
        ("s_lo", s_lo, 0, _SV_MAX), ("s_hi", s_hi, 0, _SV_MAX),
        ("v_lo", v_lo, 0, _SV_MAX), ("v_hi", v_hi, 0, _SV_MAX),
    ):
        if not lo <= value <= hi:
            raise ValueError(f"{where}: {name}={value} 超出域 [{lo},{hi}]")
    if s_lo > s_hi:
        raise ValueError(f"{where}: s_lo({s_lo}) > s_hi({s_hi})")
    if v_lo > v_hi:
        raise ValueError(f"{where}: v_lo({v_lo}) > v_hi({v_hi})")
    return HsvRange(h_lo=h_lo, h_hi=h_hi, s_lo=s_lo, s_hi=s_hi, v_lo=v_lo, v_hi=v_hi)


def _resolve_dictionary(name: object, where: str) -> None:
    if not isinstance(name, str) or not name:
        raise ValueError(f"{where}: dictionary 必须是非空字符串，得到 {name!r}")
    constant = getattr(cv2.aruco, name, None)
    if not isinstance(constant, int):
        raise ValueError(f"{where}: dictionary {name!r} 不是 cv2.aruco 可用名")
    try:
        cv2.aruco.getPredefinedDictionary(constant)
    except Exception as exc:  # cv2 对非法字典 id 抛 cv2.error
        raise ValueError(f"{where}: dictionary {name!r} 不可用 ({exc})") from exc


def load_bowl_config(path: str | Path | None = None) -> BowlConfig:
    """装载并校验 bowl_markers 配置（缺省 config/bowl_markers.json）。"""
    where = "bowl_markers"
    payload = _load_json(Path(path) if path is not None else DEFAULT_BOWL_CONFIG_PATH)
    _reject_unknown(payload, _BOWL_KEYS, where)

    cam_ref = _require(payload, "cam_ref", where)
    if not isinstance(cam_ref, str) or not cam_ref:
        raise ValueError(f"{where}: cam_ref 必须是非空字符串，得到 {cam_ref!r}")

    dictionary = _require(payload, "dictionary", where)
    _resolve_dictionary(dictionary, where)

    mapping_raw = _require(payload, "marker_to_bowl", where)
    if not isinstance(mapping_raw, dict) or not mapping_raw:
        raise ValueError(f"{where}: marker_to_bowl 必须是非空映射")
    marker_to_bowl: dict[int, int] = {}
    for key, value in mapping_raw.items():
        if not isinstance(key, str) or not key.lstrip("+-").isdigit():
            raise ValueError(f"{where}: marker_to_bowl 键必须是整数字符串，得到 {key!r}")
        marker_id = int(key)
        if marker_id < 0:
            raise ValueError(f"{where}: marker_to_bowl 键（码 id）必须 ≥0，得到 {key!r}")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{where}: marker_to_bowl[{key!r}] 碗序号必须是整数，得到 {value!r}")
        if value < 0:
            raise ValueError(f"{where}: marker_to_bowl[{key!r}] 碗序号必须 ≥0，得到 {value}")
        marker_to_bowl[marker_id] = value
    bowls = list(marker_to_bowl.values())
    if len(set(bowls)) != len(bowls):
        raise ValueError(f"{where}: 一碗双码（碗序号重复）: {bowls}")

    min_side_px = payload.get("min_side_px", 20)
    if isinstance(min_side_px, bool) or not isinstance(min_side_px, (int, float)):
        raise ValueError(f"{where}: min_side_px 必须是数值，得到 {min_side_px!r}")
    if min_side_px < 1:
        raise ValueError(f"{where}: min_side_px 必须 ≥1，得到 {min_side_px}")

    return BowlConfig(cam_ref=cam_ref, dictionary=dictionary,
                      marker_to_bowl=marker_to_bowl, min_side_px=min_side_px)
