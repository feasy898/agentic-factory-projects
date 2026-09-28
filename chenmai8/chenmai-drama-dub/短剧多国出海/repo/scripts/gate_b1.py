#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""路径兼容垫片（pass-through，非门禁实现）。

背景：B1 工作流以 cwd=仓库根 执行相对路径命令
    python 短剧多国出海/repo/scripts/gate_b1.py
该相对路径被解析为 <仓库根>/短剧多国出海/repo/scripts/gate_b1.py（不存在），
导致验收门第 1 轮 Errno 2。真正的门禁是本仓库 scripts/gate_b1.py。

本文件只做转发：原样透传命令行参数（含 --skip-gpu）、stdout/stderr 与退出码，
由系统 Python 启动真门禁（真门禁自定位仓库根并使用 .venv 解释器，任意 cwd 可跑）。
不复制、不修改任何门禁逻辑与断言。工作流改为绝对路径调用后，本垫片连同
短剧多国出海/ 目录可整体删除。
"""

import subprocess
import sys
from pathlib import Path

_REAL_GATE = Path(__file__).resolve().parents[3] / "scripts" / "gate_b1.py"

if __name__ == "__main__":
    if not _REAL_GATE.is_file():
        print(f"[shim] 真门禁不存在: {_REAL_GATE}", file=sys.stderr)
        sys.exit(2)
    sys.exit(subprocess.call([sys.executable, str(_REAL_GATE), *sys.argv[1:]]))
