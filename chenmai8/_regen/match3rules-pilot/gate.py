# -*- coding: utf-8 -*-
"""重生成试验 gate：跑冻结 eval（tests/frozen.py）。

用法：python gate.py   -> 退出码 0 = 全过，非 0 = 失败。
依赖自装：环境中缺 pytest 时自动 pip 安装。
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _ensure_pytest():
    try:
        import pytest  # noqa: F401
    except ImportError:
        print("[gate] pytest 缺失，自动安装 ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pytest"])


def main() -> int:
    _ensure_pytest()
    os.chdir(HERE)
    sys.path.insert(0, HERE)
    import pytest

    rc = pytest.main(["-q", "--tb=short", "-c", os.path.join(HERE, "pytest.ini"),
                      os.path.join(HERE, "tests", "frozen.py")])
    if rc == 0:
        print("[gate] PASS: 冻结 eval 全过（tests/frozen.py）")
        return 0
    print("[gate] FAIL: 冻结 eval 存在失败项，退出码 %s" % rc)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
