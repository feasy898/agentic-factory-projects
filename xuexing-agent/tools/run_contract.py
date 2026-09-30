"""契约测试运行器。

用法：
  python tools/run_contract.py                     # 契约测试跑参考实现（全部模块）
  python tools/run_contract.py --impl-dir regen/round1 --modules diagnosis,paper
                                                  # 只注入指定模块的重生成实例，只跑其契约测试
退出码：0=全部通过，非0=有失败（供工作流 world.run 门控使用）。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import pytest

MODULE_TEST_FILES = {
    "kpgraph": ["test_kpgraph_contract.py"],
    "itembank": ["test_itembank_contract.py"],
    "diagnosis": ["test_diagnosis_contract.py"],
    "paper": ["test_paper_contract.py"],
    "scheduler": ["test_scheduler_pedagogy_contract.py"],
    "pedagogy": ["test_scheduler_pedagogy_contract.py"],
    "route": ["test_route_contract.py"],
    "agent_shell": ["test_agent_shell_contract.py"],
    "kt": ["test_kt_contract.py"],
    "blueprint": ["test_blueprint_contract.py"],
    "grading": ["test_grading_contract.py"],
    "recommend": ["test_recommend_contract.py"],
    "standard_coverage": ["test_standard_coverage_contract.py"],
    "misconception_coverage": ["test_misconception_coverage_contract.py"],
    "itembank_v2": ["test_itembank_v2_contract.py"],
    "dual_verify": ["test_dual_verify_contract.py"],
    "paper_layout": ["test_paper_layout_contract.py"],
    "xapi": ["test_xapi_contract.py"],
    "omr_sheet": ["test_omr_sheet_contract.py"],
    "multitenant": ["test_multitenant_contract.py"],
    "mm_client": ["test_mm_client_contract.py"],
    # server 是薄胶水层（PM-STATE：不重生成），登记仅为让 run_contract 能按模块
    # 选择性运行其契约测试；--impl-dir 注入需目录内有 server.py（绝对导入约定，
    # 参考实现 src/xuexing/server.py 满足，regen/round* 冻结八模块目录不含）。
    "server": ["test_server_contract.py"],
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--impl-dir", default="", help="重生成实现所在目录；留空则测参考实现")
    ap.add_argument("--modules", default=",".join(MODULE_TEST_FILES))
    ap.add_argument("--suite", choices=["contract", "full"], default="contract",
                    help="contract=仅契约测试；full=契约+集成（集成也打在注入实现上）")
    args = ap.parse_args()

    mods = [m.strip() for m in args.modules.split(",") if m.strip()]
    unknown = [m for m in mods if m not in MODULE_TEST_FILES]
    if unknown:
        print(f"unknown modules: {unknown}")
        return 2

    pytest_args = []
    if args.impl_dir:
        os.environ["XX_IMPL_DIR"] = os.path.abspath(args.impl_dir)
        os.environ["XX_MODULES"] = ",".join(mods)
        if args.suite == "full":
            pytest_args = ["tests/contract", "tests/integration", "tests/data"]
        else:
            test_files = sorted({f for m in mods for f in MODULE_TEST_FILES[m]})
            pytest_args = [f"tests/contract/{f}" for f in test_files]
    else:
        os.environ.pop("XX_IMPL_DIR", None)
        os.environ.pop("XX_MODULES", None)
        pytest_args = ["tests/contract"] if args.suite == "contract" else ["tests/contract", "tests/integration", "tests/data"]

    rc = pytest.main(pytest_args + ["-q", "--disable-warnings", "-p", "no:cacheprovider"])
    return int(rc)


if __name__ == "__main__":
    sys.exit(main())
