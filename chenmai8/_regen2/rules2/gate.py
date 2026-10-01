# -*- coding: utf-8 -*-
"""重生成试验 gate（第二轮，_regen2/rules2）——供工作流调用。

用法：python gate.py  -> 退出码 0 = 全过，非 0 = 失败。
门项：
  1. 冻结 eval（tests/frozen.py，一字不改）全绿；
  2. §12 数值算例逐值比对（gate_examples.py，本轮核心断言）全符。
两门项任一不过即 FAIL（退出码 1），并以 JSON 输出精确诊断。
依赖自装：环境中缺 pytest 时自动 pip 安装。
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _ensure_pytest():
    try:
        import pytest  # noqa: F401
    except ImportError:
        print("[gate] pytest 缺失，自动安装 ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pytest"])


def _run_frozen():
    """门项 1：冻结 eval 全量真跑（不跳过、不豁免），回收逐项结果。"""
    os.chdir(HERE)
    sys.path.insert(0, HERE)
    import pytest

    class Collector:
        def __init__(self):
            self.passed, self.failed, self.skipped = 0, 0, 0
            self.failures = []

        def pytest_runtest_logreport(self, report):
            if report.when != "call":
                if report.failed and report.nodeid not in self.failures:
                    pass
                return
            if report.passed:
                self.passed += 1
            elif report.failed:
                self.failed += 1
                longrepr = str(report.longrepr).splitlines()
                self.failures.append({"nodeid": report.nodeid,
                                      "error": longrepr[-3:] if len(longrepr) >= 3 else longrepr})

    col = Collector()
    rc = pytest.main(["-q", "--tb=short", "-p", "no:cacheprovider",
                      "-c", os.path.join(HERE, "pytest.ini"),
                      os.path.join(HERE, "tests", "frozen.py")],
                     plugins=[col])
    return {"exit_code": int(rc), "passed": col.passed, "failed": col.failed,
            "skipped": col.skipped, "failures": col.failures}


def _run_examples():
    """门项 2：§12 算例逐值比对（子进程隔离跑，解析 JSON 报告）。"""
    env = dict(os.environ, PYTHONUTF8="1")
    proc = subprocess.run([sys.executable, os.path.join(HERE, "gate_examples.py")],
                          capture_output=True, text=True, encoding="utf-8", env=env, cwd=HERE)
    if proc.returncode not in (0, 1):
        return {"exit_code": proc.returncode, "all_ok": False,
                "error": (proc.stderr or proc.stdout)[-2000:]}
    try:
        report = json.loads(proc.stdout[proc.stdout.index("{"):])
    except Exception as exc:  # 解析失败即 FAIL
        return {"exit_code": proc.returncode, "all_ok": False, "error": "%s: %s" % (exc, proc.stdout[-800:])}
    report["exit_code"] = proc.returncode
    return report


def main() -> int:
    _ensure_pytest()
    frozen = _run_frozen()
    examples = _run_examples()
    all_ok = frozen["failed"] == 0 and frozen["exit_code"] == 0 and bool(examples.get("all_ok"))
    summary = {
        "gate": "_regen2/rules2（重生成试验第二轮）",
        "pass": all_ok,
        "step1_frozen_eval": frozen,
        "step2_examples_s12": {k: v for k, v in examples.items() if k != "examples"},
        "known_conflict": None,
    }
    if examples.get("examples"):
        a = examples["examples"].get("A_seed_first5", {}).get("checks", {})
        summary["step2_examples_s12"]["A_first5_got"] = a.get("A1_mulberry32(1)_first5@6dp", {}).get("got")
    if frozen["failures"]:
        f0 = frozen["failures"][0]
        summary["known_conflict"] = (
            "冻结 eval 存在红项 = %s：诊断以测试输出为准。口径注（2026-09-29 属主裁决重冻）："
            "mulberry32 以冻结 oracle（frozen.py:112-128，已重冻为 t|61 真源口径 = 规则卡 §7 "
            "= 模板 rng.ts）为唯一权威，常数 *61 转写是首抽即分叉的另一流（mulberry32(1) 首抽 "
            "0.6270739405881613 vs *61 误转写 0.4286732426844537）；实现/卡面 §7/§12 算例三方须同口径。" % f0["nodeid"])
    print("[gate] " + json.dumps(summary, ensure_ascii=False))
    if all_ok:
        print("[gate] PASS: 冻结 eval 全绿 + §12 算例逐值全符")
        return 0
    print("[gate] FAIL: 见上方 JSON 诊断（step1/step2 与 known_conflict 字段）")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
