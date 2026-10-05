"""cs_food 配置装载与校验（cs_food spec §4）。

两个配置文件（缺省位于仓库根 config/ 下）：
- ``config/food_hsv.json``：cam_ref / min_food_ratio / hsv_ranges（HSV 启发式区间表）；
- ``config/bowl_markers.json``：cam_ref / dictionary / marker_to_bowl / min_side_px。

校验纪律：
- 校验失败一律抛 ValueError，且错误信息带字段名；
- 未声明键视为拼写漂移同样拒绝（与 cs_schema extra="forbid" 同纪律）；
- ``min_food_ratio`` 必须 ∈ (0, 1] 数值；区间值必须整数且在域内、s_lo≤s_hi、v_lo≤v_hi；
- dictionary 必须是 ``cv2.aruco`` 可用的预定义字典名；
- marker_to_bowl 一码一碗：键为整数字符串、碗序号非负且不重复；min_side_px ≥ 1。
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# 缺省配置路径：以模块文件位置锚定仓库根（<仓库根>/config/），与 cwd 无关
DEFAULT_FOOD_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "food_hsv.json"
DEFAULT_BOWL_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "bowl_markers.json"


class HSVRange(BaseModel):
    """单段 HSV 区间（8bit OpenCV 约定：H∈[0,179]，S/V∈[0,255]）。"""

    model_config = ConfigDict(extra="forbid")

    h_lo: int = Field(ge=0, le=179)
    h_hi: int = Field(ge=0, le=179)
    s_lo: int = Field(ge=0, le=255)
    s_hi: int = Field(default=255, ge=0, le=255)
    v_lo: int = Field(ge=0, le=255)
    v_hi: int = Field(default=255, ge=0, le=255)

    @model_validator(mode="after")
    def _bounds_ordered(self) -> "HSVRange":
        if self.s_lo > self.s_hi:
            raise ValueError(f"hsv_ranges: s_lo({self.s_lo}) 必须 ≤ s_hi({self.s_hi})")
        if self.v_lo > self.v_hi:
            raise ValueError(f"hsv_ranges: v_lo({self.v_lo}) 必须 ≤ v_hi({self.v_hi})")
        return self


class FoodConfig(BaseModel):
    """config/food_hsv.json 的契约。"""

    model_config = ConfigDict(extra="forbid")

    cam_ref: str = Field(min_length=1)
    min_food_ratio: float = Field(gt=0.0, le=1.0)
    hsv_ranges: list[HSVRange] = Field(min_length=1)


class BowlConfig(BaseModel):
    """config/bowl_markers.json 的契约。"""

    model_config = ConfigDict(extra="forbid")

    cam_ref: str = Field(min_length=1)
    dictionary: str
    marker_to_bowl: dict[str, int]
    min_side_px: int = Field(default=20, ge=1)

    @field_validator("dictionary")
    @classmethod
    def _dictionary_must_exist(cls, value: str) -> str:
        marker_dict = getattr(cv2.aruco, value, None)
        if marker_dict is None:
            raise ValueError(f"dictionary: {value!r} 不是 cv2.aruco 可用的预定义字典名")
        try:
            cv2.aruco.getPredefinedDictionary(marker_dict)
        except Exception as exc:  # noqa: BLE001 —— 统一转 ValueError
            raise ValueError(f"dictionary: {value!r} 无法实例化（{exc}）") from exc
        return value

    @field_validator("marker_to_bowl")
    @classmethod
    def _one_marker_one_bowl(cls, value: dict[str, int]) -> dict[str, int]:
        if not value:
            raise ValueError("marker_to_bowl: 不能为空映射（至少登记一码一碗）")
        bowls: list[int] = []
        for key, bowl_index in value.items():
            try:
                int(str(key).strip())
            except ValueError as exc:
                raise ValueError(f"marker_to_bowl: 键 {key!r} 不是整数（码 id）") from exc
            if bowl_index < 0:
                raise ValueError(f"marker_to_bowl: 码 {key!r} 的碗序号 {bowl_index} 为负")
            bowls.append(bowl_index)
        duplicated = sorted({b for b in bowls if bowls.count(b) > 1})
        if duplicated:
            raise ValueError(f"marker_to_bowl: 一碗双码——碗序号重复 {duplicated}")
        return value


def _load_json(path: str | Path) -> dict:
    file = Path(path)
    if not file.is_file():
        raise ValueError(f"配置文件不存在：{file}")
    try:
        payload = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"配置不是合法 JSON：{file}（{exc}）") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"配置顶层必须是 JSON object：{file}")
    return payload


def load_food_config(path: str | Path | None = None) -> FoodConfig:
    """装载 food_hsv 配置；缺省 ``config/food_hsv.json``。校验失败抛 ValueError。"""
    file = DEFAULT_FOOD_CONFIG_PATH if path is None else Path(path)
    return FoodConfig.model_validate(_load_json(file))


def load_bowl_config(path: str | Path | None = None) -> BowlConfig:
    """装载 bowl_markers 配置；缺省 ``config/bowl_markers.json``。校验失败抛 ValueError。"""
    file = DEFAULT_BOWL_CONFIG_PATH if path is None else Path(path)
    return BowlConfig.model_validate(_load_json(file))
