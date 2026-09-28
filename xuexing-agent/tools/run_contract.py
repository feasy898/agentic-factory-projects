"""契约测试运行器。

用法：
  python tools/run_contract.py                     # 契约测试跑参考实现
  python tools/run_contract.py --impl-dir regen/round1 [--modules diagnosis,paper]
                                                  # 契约测试跑重生成实例
退出码：0=全部通过，1=有失败（供工作流 world.run 门控使用）。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import pytest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--impl-dir", default="", help="重生成实现所在目录；留空则测参考实现")
    ap.add_argument("--modules", default="kpgraph,itembank,diagnosis,paper,scheduler,pedagogy,route,agent_shell")
    args = ap.parse_args()

    if args.impl_dir:
        os.environ["XX_IMPL_DIR"] = os.path.abspath(args.impl_dir)
        os.environ["XX_MODULES"] = args.modules
    else:
        os.environ.pop("XX_IMPL_DIR", None)
        os.environ.pop("XX_MODULES", None)

    rc = pytest.main(["tests/contract", "-q", "--disable-warnings", "-p", "no:cacheprovider"])
    return int(rc)


if __name__ == "__main__":
    sys.exit(main())
