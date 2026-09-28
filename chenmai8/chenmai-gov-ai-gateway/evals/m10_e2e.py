"""M10 端到端验收入口（D0 收工线）：驱动 ops/e2e_smoke.py 全链路六用例。

运行::

    cd REPO_ROOT && PYTHONUTF8=1 ./.venv/Scripts/python.exe -m evals.m10_e2e

exit 0 = 通过（= ops/e2e_smoke.py 的 ACTIVE 用例全 PASS、零 FAIL）。

断言面（开发指令 §2 D0 行 + §9）：拉起 mock 上游 ×2（:8901/:8902 子进程）与网关
（:9000），断言——上游收到全占位符（bytes 级零原值）、客户端拿到还原答案、
密级样例被 403 拦截、审计入库且零明文。用例明细与拓扑见 ops/e2e_smoke.py 模块文档
（U1–U5 当天生效；U6 文件通道 D3 起生效，未上线时 DEFERRED 不计失败）。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ops.e2e_smoke import main as smoke_main  # noqa: E402


def main() -> int:
    print("== evals.m10_e2e → ops/e2e_smoke（§9 六用例，U1–U5 当天生效）==", flush=True)
    return smoke_main()


if __name__ == "__main__":
    sys.exit(main())
