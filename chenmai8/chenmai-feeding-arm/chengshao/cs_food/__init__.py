"""感知包：勺上食物检查（启发式起步，接口冻结可换分类器）+ 选碗（基准码）。

冻结接口（开发指令 §3.2）：SpoonClassifier.from_bgr(crop) -> SpoonCheck。
MVP 实现 = HeuristicSpoonClassifier（HSV 食物色占比，阈值从 config/ 装载）；
选碗 = BowlSelector（场景相机基准码 3 碗 3 码 → bowl_sel）。
"""

from __future__ import annotations

from .bowls import BowlMarker, BowlSelector
from .config import (
    BowlConfig,
    CONFIG_DIR,
    DEFAULT_BOWL_CONFIG_PATH,
    DEFAULT_FOOD_CONFIG_PATH,
    FoodConfig,
    HSVRange,
    load_bowl_config,
    load_food_config,
)
from .spoons import HeuristicSpoonClassifier, SpoonClassifier

__version__ = "0.1.0"

__all__ = [
    "BowlConfig",
    "BowlMarker",
    "BowlSelector",
    "CONFIG_DIR",
    "DEFAULT_BOWL_CONFIG_PATH",
    "DEFAULT_FOOD_CONFIG_PATH",
    "FoodConfig",
    "HSVRange",
    "HeuristicSpoonClassifier",
    "SpoonClassifier",
    "load_bowl_config",
    "load_food_config",
]
