#!/usr/bin/env python3
"""G4 闸门契约路径入口：scripts/e2e_mock_run.py（转发垫片）。

开发指令任务 T9 的契约自验收路径是仓库根 scripts/e2e_mock_run.py
（G4 硬闸门按此路径调用）；真实实现在 chengshao/scripts/e2e_mock_run.py
（820 行全链路 mock 端到端，仅依赖自身 __file__ 定位仓库根，任意 cwd 可跑，
报告落 chengshao/reports/）。本垫片只做转发：

- 真实 e2e 依赖仓库 .venv 的第三方包（numpy、fastapi/uvicorn、mediapipe、
  py_trees 等），外部复核器的 ``python``（系统解释器）不装这些依赖
  （实测 import py_trees 即 ModuleNotFoundError），故转发时优先改用
  ``<仓库根>/.venv/Scripts/python.exe``；.venv 缺失时回退 sys.executable。
- subprocess 等待真实入口结束并回传退出码（不用 os.execv，Windows 下
  输出继承不可靠）；stdout/stderr 原样透传。
- 本文件不做任何检查、不产出任何验收结论，退出码 = 真实入口退出码。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]          # scripts/ -> 仓库根
_REAL = _ROOT / "chengshao" / "scripts" / "e2e_mock_run.py"
_VENV_PY = _ROOT / ".venv" / "Scripts" / "python.exe"
_PY = str(_VENV_PY) if _VENV_PY.is_file() else sys.executable
print(f"[shim] {Path(__file__).name} -> {_PY} {_REAL}", file=sys.stderr)
env = {**os.environ, "PYTHONUTF8": "1"}
# 安全口径：参数数组直 exec（shell=False 显式声明），无 shell 可注入；
# argv 逐元素透传（list2cmdline 引号转义），路径全部源自 __file__ 解析。
r = subprocess.run([_PY, str(_REAL), *sys.argv[1:]],
                   cwd=str(_ROOT), env=env, shell=False)
sys.exit(r.returncode)
