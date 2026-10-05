# -*- coding: utf-8 -*-
"""重生成试验 gate：跑冻结 eval（evals.m3_masking），透传退出码。

用法：python gate.py   -> 退出码 0 = 8/8 全过，非 0 = 失败。

冻结测试为一字不改的 ``evals/m3_masking.py``（与原 repo 字节级一致），
以 ``python -m evals.m3_masking`` 运行（eval 自身即验收入口，exit 0 = 通过）。
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        [sys.executable, "-m", "evals.m3_masking"],
        cwd=HERE,
        env=env,
    )
    if proc.returncode == 0:
        print("[gate] PASS: 冻结 eval 全过（evals.m3_masking，8/8）")
        return 0
    print("[gate] FAIL: 冻结 eval 存在失败项，退出码 %s" % proc.returncode)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
