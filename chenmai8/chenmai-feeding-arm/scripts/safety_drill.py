#!/usr/bin/env python3
"""真机工具链契约路径入口：scripts/safety_drill.py（转发垫片）。

开发指令 §5.9 安全实测的契约命令路径；真实实现在
chengshao/scripts/safety_drill.py（head_turn / estop / face_intrude 注入演练
+ --mock MockArm 通道）。本垫片只做转发：优先改用仓库 .venv 解释器，缺失时
回退 sys.executable；subprocess 等待并原样透传 stdout/stderr，退出码 = 真实
入口退出码。本文件不做任何检查、不产出任何验收结论。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]          # scripts/ -> 仓库根
_REAL = _ROOT / "chengshao" / "scripts" / "safety_drill.py"
_VENV_PY = _ROOT / ".venv" / "Scripts" / "python.exe"
_PY = str(_VENV_PY) if _VENV_PY.is_file() else sys.executable
print(f"[shim] {Path(__file__).name} -> {_PY} {_REAL}", file=sys.stderr)
env = {**os.environ, "PYTHONUTF8": "1"}
# 安全口径：参数数组直 exec（shell=False），argv 逐元素透传。
r = subprocess.run([_PY, str(_REAL), *sys.argv[1:]],
                   cwd=str(_ROOT / "chengshao"), env=env, shell=False)
sys.exit(r.returncode)
