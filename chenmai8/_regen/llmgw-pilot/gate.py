"""llmgw-pilot 门脚本：冻结自测 llmgw.selftest 的唯一入口。

- chdir 到本目录（保证 `python -m llmgw.selftest` 能定位 llmgw 包）；
- 用当前系统 Python 解释器运行；
- 子进程与父进程 stdout 全程 utf-8；
- 透传子进程退出码（0 = SELFTEST PASS）。
"""

import os
import subprocess
import sys


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    os.chdir(here)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    proc = subprocess.run([sys.executable, "-m", "llmgw.selftest"], env=env)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
