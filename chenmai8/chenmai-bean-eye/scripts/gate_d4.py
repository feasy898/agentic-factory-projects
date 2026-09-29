#!/usr/bin/env python3
"""BeanEye D4 里程碑闸门（gate_d4）。

覆盖 D4 批次（W4c 合成盘全链一条命令 + 本闸门）的整体验收。
本脚本用**系统 Python** 运行（不要求已激活 venv、不限定 cwd），
内部自行定位仓库根；子检查统一改用项目 .venv 解释器执行（与 gate_d1/d2/d3
同约定）。

四项检查（任何一项 FAIL → 总退出码 1）：
  ① .venv python -m pytest tests/ 全绿（exit 0）——D1 契约 + D2/D3/D4 各批
     全部测试（本批次无新增测试文件，套件与 gate_d3 时点一致）；
  ② scripts/e2e_synth_run.py **缺省参数**以 .venv python 运行 exit 0——
     合成盘 → 标定 → classic 分割 → 规则分类 → 配对 → 计量 → 定级 →
     三语护照 全链真实执行（缺省 3 盘，脚本内含逐盘硬断言）；
  ③ gate_d3 回归：scripts/gate_d3.py 原样运行 exit 0（该脚本自举 .venv，
     内部重跑 doctor + 全量 pytest + W8-W11 模块 eval 入口 + 中性名扫描）；
  ④ 中性名扫描零命中：**直接复用 gate_d3 的模式表、豁免名单与扫描函数**
     （单一事实源，与 gate_d3 回归项逐字节同口径）。
     实现纪律：本脚本与 e2e_synth_run.py 均为产品面文件、零豁免——
     两个文件正文都不得出现上游名清单（本脚本经 import 复用而非复制
     模式表，e2e 脚本只写中性表述），否则 ③/④ 自身即命中失败。

用法（Git Bash / cmd / PowerShell 均可，任意 cwd）：
    python D:/workspace/澄迈8项目/咖啡豆质检/repo/scripts/gate_d4.py

输出：逐项 `[PASS]`/`[FAIL]` + 详情，结尾 `GATE D4: PASS/FAIL`。
退出码：全过 = 0；任一 FAIL = 1；前置缺失（.venv 不存在）时 ①② 判 FAIL、
③④ 照常执行（gate_d3 对 venv 缺失有同样的显式 FAIL 语义）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# 闸门自身输出统一 UTF-8（Windows 控制台/重定向默认 GBK 会乱码）
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import gate_d3  # noqa: E402  # 复用 VENV_PY/_child_env/check_venv/check_neutral_names

PYTEST_TIMEOUT_S = 2400
E2E_TIMEOUT_S = 1800
GATE_D3_TIMEOUT_S = 5400


def _run_in_venv(args: list[str], timeout_s: int) -> subprocess.CompletedProcess[str]:
    """在仓库根用 .venv python 执行 args，捕获输出（UTF-8 解码）。"""
    return subprocess.run(
        [str(gate_d3.VENV_PY), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=gate_d3._child_env(),
        timeout=timeout_s,
    )


def _tail(text: str, n: int = 3) -> str:
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return "(无输出)"
    return " | ".join(lines[-n:])


def check_pytest_all() -> tuple[bool, str]:
    """检查 ① pytest tests/ 全绿。"""
    try:
        proc = _run_in_venv(["-m", "pytest", "tests/", "-q"], PYTEST_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, f"pytest 超时（>{PYTEST_TIMEOUT_S}s）"
    return proc.returncode == 0, f"exit={proc.returncode}, {_tail(proc.stdout + proc.stderr, 2)}"


def check_e2e_synth() -> tuple[bool, str]:
    """检查 ② 合成盘全链一条命令缺省参数 exit 0。"""
    try:
        proc = _run_in_venv(["scripts/e2e_synth_run.py"], E2E_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, f"e2e_synth_run 超时（>{E2E_TIMEOUT_S}s）"
    return proc.returncode == 0, f"exit={proc.returncode}, {_tail(proc.stdout + proc.stderr)}"


def check_gate_d3_regression() -> tuple[bool, str]:
    """检查 ③ gate_d3 原样回归 exit 0（当前解释器即可，脚本内部自举 .venv）。"""
    try:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "gate_d3.py")],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=gate_d3._child_env(),
            timeout=GATE_D3_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return False, f"gate_d3 超时（>{GATE_D3_TIMEOUT_S}s）"
    return proc.returncode == 0, f"exit={proc.returncode}, {_tail(proc.stdout + proc.stderr, 6)}"


def check_neutral_names() -> tuple[bool, str]:
    """检查 ④ 中性名扫描零命中（gate_d3 同一模式表/豁免名单/扫描函数）。"""
    ok, detail = gate_d3.check_neutral_names()
    return ok, detail


def main() -> int:
    print("== BeanEye D4 闸门（gate_d4）==")
    print(f"仓库根: {ROOT}")

    venv_ok, venv_detail = gate_d3.check_venv()
    results: list[tuple[str, bool, str]] = []

    if venv_ok:
        results.append(("① pytest tests/ 全绿", *check_pytest_all()))
        results.append(("② e2e_synth_run 缺省参数 exit 0", *check_e2e_synth()))
    else:
        skip = f"跳过：{venv_detail}"
        results.append(("① pytest tests/ 全绿", False, skip))
        results.append(("② e2e_synth_run 缺省参数 exit 0", False, skip))
    results.append(("③ gate_d3 回归 exit 0", *check_gate_d3_regression()))
    results.append(("④ 中性名扫描零命中", *check_neutral_names()))

    failed = 0
    for name, ok, detail in results:
        mark = "[PASS]" if ok else "[FAIL]"
        print(f"{mark} {name}: {detail}")
        if not ok:
            failed += 1

    print("----------------------------")
    if failed == 0:
        print("GATE D4: PASS (4/4)")
        return 0
    print(f"GATE D4: FAIL ({failed}/4 项未通过)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
