"""cs_food 重生成试点 gate（供工作流调用；pytest 退出码透传）。

门项依据 SPEC.md（= docs/assets/specs/cs_food.md §5 的两条精确命令与通过线）：
  FROZEN  冻结测试一字不改：tests/test_food_interface.py 与 tests/conftest.py 的
          sha256 必须等于冻结时记录值（gate 运行前后各核一次）。
  G1      eval ① 接口与配置装载（cwd=仓库根）：
          .venv/Scripts/python.exe -m pytest tests/test_food_interface.py -q
          → 退出码透传（0=全绿；非 0 原样作为 gate 退出码）；54 passed；
          conftest 钩子落盘 chengshao/reports/food_interface_eval.json 且 pass=true。
  G2      eval ② 合成自检（cwd=chengshao 包根；无硬件可跑）：
          ../.venv/Scripts/python.exe -m cs_food.eval --report reports/food_eval.json
          → exit 0、self_check=True、勺检 8/8、3 码全检出、选碗命中、
          空图 None、未登记码忽略。

用法：python gate.py   → 退出码 0 = 全绿；1 = 任一门项失败（G1 时透传 pytest 码）。
纪律：先清旧产物再跑（reports/ 下两份 eval JSON 的存在 = 本次运行的真事实）。
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
VENV_PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
FROZEN_TEST = os.path.join(ROOT, "tests", "test_food_interface.py")
FROZEN_CONFTEST = os.path.join(ROOT, "tests", "conftest.py")
# 冻结时（2026-09-29）自原 repo tests/ 逐字节复制后的 sha256
FROZEN_SHA = {
    FROZEN_TEST: "a9116e26613cb245d061ff109aaf5da21cb0ed31e6999479d6c66c11553a25b1",
    FROZEN_CONFTEST: "e2defcef042c89b9e5a9e5bbaee57fadfcb1c1b2f528692a5a19914e382cf501",
}
REPORTS = os.path.join(ROOT, "chengshao", "reports")

_failures = []


def _py():
    return VENV_PY if os.path.isfile(VENV_PY) else sys.executable


def _record(gate, ok, problems=()):
    tag = "PASS" if ok else "FAIL"
    print(f"[{gate}] {tag}" + (f" —— {'；'.join(problems)}" if problems else ""))
    if not ok:
        _failures.append(gate)


def _sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _frozen_ok():
    bad = [f"{os.path.relpath(p, ROOT)}: {_sha256(p)[:12]}…" for p, h in FROZEN_SHA.items() if _sha256(p) != h]
    return not bad, bad


def _clean_stale():
    """先清旧产物再跑：eval 报告的存在 = 本次运行的真事实。"""
    if os.path.isdir(REPORTS):
        shutil.rmtree(REPORTS)


def gate1_pytest():
    """eval ①：pytest 透传（cwd=仓库根，命令与 spec §5 逐字一致）。"""
    proc = subprocess.run(
        [_py(), "-m", "pytest", "tests/test_food_interface.py", "-q"],
        cwd=ROOT, env={**os.environ, "PYTHONUTF8": "1"},
    )
    if proc.returncode != 0:
        _record("G1 pytest(透传)", False, [f"pytest exit={proc.returncode}（预期 0），原样透传"])
        return proc.returncode
    report_path = os.path.join(REPORTS, "food_interface_eval.json")
    problems = []
    if not os.path.isfile(report_path):
        problems.append("conftest 证据报告未生成：chengshao/reports/food_interface_eval.json")
    else:
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
        metrics = report.get("metrics", {})
        if report.get("pass") is not True:
            problems.append(f"报告 pass={report.get('pass')}")
        if metrics.get("passed") != 54 or metrics.get("failed") or metrics.get("errors"):
            problems.append(
                f"passed={metrics.get('passed')} failed={metrics.get('failed')} errors={metrics.get('errors')}（预期 54/0/0）"
            )
        thresholds = report.get("thresholds", {})
        if thresholds.get("synthetic_food_cases_min") != 4 or thresholds.get("synthetic_empty_cases_min") != 4 \
                or thresholds.get("aruco_bowls_registered") != 3:
            problems.append(f"阈值口径异常：{thresholds}")
    _record("G1 pytest(透传)", not problems, problems)
    return 0


def gate2_eval():
    """eval ②：合成自检（cwd=chengshao 包根，命令与 spec §5 逐字一致）。"""
    proc = subprocess.run(
        [_py(), "-m", "cs_food.eval", "--report", "reports/food_eval.json"],
        cwd=os.path.join(ROOT, "chengshao"), env={**os.environ, "PYTHONUTF8": "1"},
    )
    if proc.returncode != 0:
        _record("G2 合成自检", False, [f"exit={proc.returncode}（预期 0）"])
        return
    with open(os.path.join(REPORTS, "food_eval.json"), encoding="utf-8") as f:
        report = json.load(f)
    m = report.get("metrics", {})
    problems = []
    if report.get("self_check") is not True:
        problems.append(f"self_check={report.get('self_check')}")
    if not (m.get("food_correct") == 4 and m.get("empty_correct") == 4 and m.get("spoon_correct") == 8):
        problems.append(f"勺检 8 例未全对：food={m.get('food_correct')}/4 empty={m.get('empty_correct')}/4")
    if m.get("aruco_registered_detected") != 3:
        problems.append(f"码检出 {m.get('aruco_registered_detected')}/3")
    for key in ("select_hit", "empty_scene_none", "unregistered_ignored", "small_marker_filtered"):
        if m.get(key) is not True:
            problems.append(f"{key}!={m.get(key)}")
    _record("G2 合成自检", not problems, problems)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ok, bad = _frozen_ok()
    if not ok:
        print(f"[FROZEN] FAIL —— 冻结测试被改动：{bad}")
        return 1
    print("[FROZEN] PASS —— test_food_interface.py / conftest.py 与冻结 sha256 一致")
    _clean_stale()
    rc = gate1_pytest()
    gate2_eval()
    ok2, bad2 = _frozen_ok()
    if not ok2:
        _failures.append("FROZEN-AFTER")
        print(f"[FROZEN-AFTER] FAIL —— gate 结束后冻结测试被改动：{bad2}")
    if rc != 0:
        return rc  # pytest 非 0 → 退出码原样透传
    total, n_bad = 2, len(_failures)
    print(f"ROBOT-PILOT(cs_food) GATE: {'PASS' if n_bad == 0 else 'FAIL'} ({total - n_bad}/{total})")
    return 0 if n_bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
