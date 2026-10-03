#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_docx.py — minutes.py 的等价别名入口

CLI 与产物和契约入口 minutes.py 完全相同（--input <txt> --outdir <dir>，
产出 纪要.docx + summary.json），实现委托给同目录 minutes.main。

命名说明：contract.md §2 冻结的入口名是 scripts/minutes.py；本轮生成任务指令
点名 scripts/gen_docx.py。两者并存、行为一致，以 minutes.py 为权威入口。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from minutes import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
