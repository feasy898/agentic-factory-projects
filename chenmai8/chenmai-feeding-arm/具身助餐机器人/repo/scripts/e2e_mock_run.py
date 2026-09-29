#!/usr/bin/env python3
"""cwd 兼容垫片（untracked，非仓库内容）——e2e_mock_run.py。

背景：与同目录 check_naming.py / gate_g1.py 垫片相同——外部复核器以仓库根
为 cwd、把脚本路径按工作区相对形态 ``具身助餐机器人/repo/...`` 拼接，导致
路径翻倍（G4 复核第 1 轮失败，Errno 2）。前轮已为 check_naming/gate_g1
补垫片，本轮补 e2e_mock_run.py。

与那两个垫片的唯一差别：真实 e2e 依赖仓库 .venv 的第三方包（numpy、
fastapi/uvicorn、mujoco 等），复核器的 ``python``（daimon 捆绑解释器）不装
这些依赖（实测 import numpy 即 ModuleNotFoundError），故转发时优先改用
``<仓库根>/.venv/Scripts/python.exe``；.venv 缺失时回退 sys.executable。

本垫片只把调用原样转发到真实入口（真实入口只依赖自身 __file__ 定位仓库
根、任意 cwd 可跑），不做任何检查、不产出任何验收结论；退出码 = 真实入口
退出码，输出原样透传。
"""

from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys


def _find_repo_root(start: Path) -> Path:
    p = start
    for _ in range(8):
        if (p / "chengshao" / "cs_sim" / "adversarial.py").is_file():
            return p
        if p.parent == p:
            break
        p = p.parent
    raise SystemExit("[shim] 未能定位真实仓库根（从未跟踪垫片转发失败）")


_NAME = Path(__file__).resolve().name
_ROOT = _find_repo_root(Path(__file__).resolve().parent)
_REAL = _ROOT / "chengshao" / "scripts" / "e2e_mock_run.py"
_VENV_PY = _ROOT / ".venv" / "Scripts" / "python.exe"
_PY = str(_VENV_PY) if _VENV_PY.is_file() else sys.executable
print(f"[shim] {_NAME} -> {_PY} {_REAL}", file=sys.stderr)
env = {**os.environ, "PYTHONUTF8": "1"}
r = subprocess.run([_PY, str(_REAL), *sys.argv[1:]], cwd=str(_ROOT), env=env)
sys.exit(r.returncode)
