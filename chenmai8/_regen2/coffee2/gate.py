"""C1 二轮 gate：运行冻结 eval（tests/test_severity.py），pytest 退出码透传。

用法（任意目录）::

    python gate.py [额外 pytest 参数...]

返回码 = pytest 退出码（0=全绿；非 0 原样透传，不做任何加工）。
spec 依据：docs/assets/specs/severity.md §6 eval：
    python -m pytest tests/test_severity.py -q  →  83 passed
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = "tests/test_severity.py"


def main(argv: list[str] | None = None) -> int:
    cmd = [sys.executable, "-m", "pytest", TARGET, "-q", *(argv or [])]
    completed = subprocess.run(cmd, cwd=str(ROOT))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
