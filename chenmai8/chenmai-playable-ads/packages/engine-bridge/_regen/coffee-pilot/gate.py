"""重生成试验验收门：跑冻结测试 tests/test_severity.py（pytest 透传退出码）。

用法（任意 cwd）::

    python gate.py                 # 等价 pytest tests/test_severity.py -q
    python gate.py -x -k tie       # 附加参数原样透传给 pytest

解释器选择：优先本包 ``.venv``，其次同机原仓钉版环境（Python 3.12.10 /
pydantic 2.13.5 / pytest 9.1.1，与 REGENERATE §1 钉版一致），最后回退当前
解释器。子进程注入 ``PYTHONUTF8=1``（GBK 控制台中文乱码坑）。
``skip 不是 pass``：透传 pytest 退出码，由调用方按退出码裁定。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEST_REL = ["tests", "test_severity.py"]

# 同机原仓钉版环境（重生成试验复用，避免联网重建 venv）
_FALLBACK_VENVS = [
    Path(r"D:\workspace\澄迈8项目\咖啡豆质检\repo\.venv"),
]


def _candidate_pythons() -> list[Path]:
    cands = [ROOT / ".venv" / "Scripts" / "python.exe", ROOT / ".venv" / "bin" / "python"]
    for venv in _FALLBACK_VENVS:
        cands.append(venv / "Scripts" / "python.exe")
        cands.append(venv / "bin" / "python")
    cands.append(Path(sys.executable))
    return cands


def pick_python() -> Path:
    for cand in _candidate_pythons():
        if cand.is_file():
            return cand
    return Path(sys.executable)


def main(argv: list[str]) -> int:
    test_file = ROOT.joinpath(*TEST_REL)
    if not test_file.is_file():
        print(f"GATE: FAIL —— 冻结测试缺失: {test_file}")
        return 2
    python = pick_python()
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    cmd = [str(python), "-m", "pytest", "tests/test_severity.py", "-q", *argv]
    print(f"GATE: cwd={ROOT}")
    print(f"GATE: {' '.join(cmd)}")
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), env=env)
    except OSError as exc:
        print(f"GATE: FAIL —— 无法启动 pytest 子进程: {exc}")
        return 2
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
