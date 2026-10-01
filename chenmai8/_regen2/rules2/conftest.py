# -*- coding: utf-8 -*-
"""pytest 路径前置：把包根加入 sys.path（等价 pip install -e 的兜底，二选一即可）。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
