"""cs_food：感知层——勺上食物检查 + 基准码选碗（cs_food spec）。

对外导出（冻结）：
- ``SpoonClassifier``：runtime_checkable Protocol（from_bgr -> SpoonCheck，签名不改）；
- ``HeuristicSpoonClassifier``：HSV 启发式 MVP 实现；
- ``BowlSelector`` / ``MarkerObservation``：ArUco 基准码选碗；
- ``load_food_config`` / ``load_bowl_config`` 与缺省路径常量；
- ``python -m cs_food.eval``：合成自检（cwd=chengshao 包根，无硬件可跑）。
"""

from .config import (
    DEFAULT_BOWL_CONFIG_PATH,
    DEFAULT_FOOD_CONFIG_PATH,
    BowlConfig,
    FoodConfig,
    HSVRange,
    load_bowl_config,
    load_food_config,
)
from .bowls import BowlSelector, MarkerObservation
from .spoons import HeuristicSpoonClassifier, SpoonClassifier

__all__ = [
    "DEFAULT_BOWL_CONFIG_PATH",
    "DEFAULT_FOOD_CONFIG_PATH",
    "BowlConfig",
    "BowlSelector",
    "FoodConfig",
    "HSVRange",
    "HeuristicSpoonClassifier",
    "MarkerObservation",
    "SpoonClassifier",
    "load_bowl_config",
    "load_food_config",
]
