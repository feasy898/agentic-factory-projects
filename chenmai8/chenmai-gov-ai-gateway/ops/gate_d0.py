#!/usr/bin/env python3
"""D0 收工门（Gate G0）：从任意 cwd、用系统 python 可运行的门脚本。

用法（系统 python 即可，无需激活 venv）::

    python D:/workspace/澄迈8项目/政务AI脱敏网关/repo/ops/gate_d0.py

行为（任务单 T0.6）：
1. 内部 chdir 到仓库根，统一设 PYTHONUTF8=1，stdout/stderr 重配为 UTF-8；
2. 依次用仓库 .venv 的解释器（.venv/Scripts/python.exe）运行：
   ① -m ops.name_lint    公开仓库禁用词守卫（零命中为过）
   ② -m evals.m0_infra   基础设施验收（安装/配置/契约模型）
   ③ -m evals.m10_e2e    端到端六用例（§9，U1–U5 当天生效）
3. 每项检查透传其完整输出并打印 [PASS]/[FAIL] 与退出码；任何 FAIL → 本脚本退出码 1。

本脚本只用标准库：系统 python 无第三方依赖也能定位仓库、启动子进程、汇总结果。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"

#: (显示名, 模块参数)；统一以仓库 .venv 解释器运行，cwd=仓库根
CHECKS: list[tuple[str, list[str]]] = [
    ("name_lint", ["-m", "ops.name_lint"]),
    ("evals.m0_infra", ["-m", "evals.m0_infra"]),
    ("evals.m10_e2e", ["-m", "evals.m10_e2e"]),
]

CHECK_TIMEOUT_S = 900


def _run_check(name: str, args: list[str]) -> bool:
    print(f"\n===== [gate_d0] RUN {name} ：{VENV_PYTHON.name} {' '.join(args)} "
          f"(cwd={REPO_ROOT}) =====", flush=True)
    try:
        proc = subprocess.run(
            [str(VENV_PYTHON), *args],
            cwd=str(REPO_ROOT),
            env={**os.environ, "PYTHONUTF8": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=CHECK_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        print(f"[FAIL] {name} — 超时（>{CHECK_TIMEOUT_S}s）", flush=True)
        return False
    except OSError as exc:
        print(f"[FAIL] {name} — 解释器启动失败：{exc}", flush=True)
        return False
    output = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
    if output:
        sys.stdout.write(output)
        if not output.endswith("\n"):
            sys.stdout.write("\n")
    status = "PASS" if proc.returncode == 0 else "FAIL"
    print(f"[{status}] {name} (exit={proc.returncode})", flush=True)
    return proc.returncode == 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    os.chdir(REPO_ROOT)
    os.environ["PYTHONUTF8"] = "1"

    print(f"[gate_d0] 仓库根: {REPO_ROOT}", flush=True)
    if not VENV_PYTHON.exists():
        print(f"[FAIL] venv 解释器缺失: {VENV_PYTHON}（先按 README 建立 .venv 并 pip install -e .）",
              flush=True)
        return 1

    failures: list[str] = []
    for name, args in CHECKS:
        if not _run_check(name, args):
            failures.append(name)

    print("\n===== [gate_d0] 摘要 =====", flush=True)
    for name, _ in CHECKS:
        print(f"[{'PASS' if name not in failures else 'FAIL'}] {name}", flush=True)
    if failures:
        print(f"[gate_d0] 结果: {len(failures)}/{len(CHECKS)} FAIL → 退出码 1", flush=True)
        return 1
    print("[gate_d0] 结果: 全部 PASS → 退出码 0", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
