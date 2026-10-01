"""pytest 根配置：把仓库根加入 sys.path，保证 `pytest` 与 `python -m pytest` 均可导入 pipeline。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
