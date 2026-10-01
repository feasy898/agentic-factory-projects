#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gen_report.py — 月度汇报生成器入口别名。

与 monthly_report.py 完全等价（同一实现、同一 CLI 契约）：
    python gen_report.py --input <台账.xlsx> --outdir <输出目录>

contract.md 冻结的正式入口名为 scripts/monthly_report.py；本文件只是
兼容「gen_report」调用习惯的薄别名，不包含任何业务逻辑。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from monthly_report import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
