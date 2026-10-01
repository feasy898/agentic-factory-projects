"""cs_food —— 感知层：勺上食物检查 + 选碗（spec：docs/assets/specs/cs_food.md）。"""

from __future__ import annotations

import sys
from pathlib import Path

# 双模式导入兜底：本包既可作 chengshao.cs_food（cwd=仓库根，pytest）也可作
# 顶层 cs_food（spec §5 eval ②：cwd=chengshao，python -m cs_food.eval）导入。
# 后者 sys.path 只有 chengshao/，包内对 chengshao.cs_schema 的绝对导入需要
# 仓库根在 sys.path 上——统一在此补齐（幂等）。
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from .bowls import BowlMarker, BowlSelector
from .config import (
    DEFAULT_BOWL_CONFIG_PATH,
    DEFAULT_FOOD_CONFIG_PATH,
    BowlConfig,
    FoodConfig,
    HsvRange,
    load_bowl_config,
    load_food_config,
)
from .spoons import HeuristicSpoonClassifier, SpoonClassifier

__all__ = [
    "DEFAULT_BOWL_CONFIG_PATH",
    "DEFAULT_FOOD_CONFIG_PATH",
    "BowlConfig",
    "BowlMarker",
    "BowlSelector",
    "FoodConfig",
    "HeuristicSpoonClassifier",
    "HsvRange",
    "SpoonClassifier",
    "load_bowl_config",
    "load_food_config",
]
