#!/usr/bin/env python3
"""G4 闸门契约路径入口：scripts/check_naming.py（转发垫片）。

G4 硬闸门按仓库根 scripts/check_naming.py 调用命名扫描；真实扫描器在
chengshao/scripts/check_naming.py（纯标准库，任意解释器可跑；扫描根默认
git toplevel，取不到时回退自身 __file__ 上溯，与调用方 cwd 无关）。
本垫片只做转发：subprocess 等待真实扫描器结束并回传退出码（不用
os.execv，Windows 下输出继承不可靠），stdout/stderr 原样透传。
本文件不做任何检查、不产出任何验收结论，退出码 = 真实扫描器退出码。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]          # scripts/ -> 仓库根
_REAL = _ROOT / "chengshao" / "scripts" / "check_naming.py"
print(f"[shim] {Path(__file__).name} -> {sys.executable} {_REAL}", file=sys.stderr)
# 安全口径：参数数组直 exec（shell=False 显式声明），无 shell 可注入；
# argv 逐元素透传（list2cmdline 引号转义），路径全部源自 __file__ 解析。
r = subprocess.run([sys.executable, str(_REAL), *sys.argv[1:]], shell=False)
sys.exit(r.returncode)
