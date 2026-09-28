#!/usr/bin/env python3
"""B2 收工门（Gate G-B2）：D2（路由 + 输出侧）收工门。系统 python 从任意 cwd 可运行；
内部统一用仓库 .venv 执行各项检查。

用法（系统 python 即可，无需激活 venv，可在任意工作目录）::

    python D:/workspace/澄迈8项目/政务AI脱敏网关/repo/ops/gate_b2.py

行为（任务单 T2.5；结构沿用 ops/gate_b1.py / ops/gate_d0.py，编号 = 任务单原文）：
1. 内部 chdir 到仓库根，统一设 PYTHONUTF8=1，stdout/stderr 重配为 UTF-8；
2. 依次运行（①–⑦ 用仓库 .venv 解释器 .venv/Scripts/python.exe，cwd=仓库根）：
   ① -m ops.name_lint        公开仓库禁用词守卫（零命中为过）
   ② -m evals.m0_infra       基础设施 + 配置 + §5 契约模型（全部检查通过为过）
   ③ -m evals.m4_routing     §5.2 决策矩阵逐格 + 优先级冲突（§6 M4）
   ⑤ -m evals.m5_outguard    输出侧标识/拦截文案/代答/复检钩子（§6 M5）
   ⑥ -m evals.m3_masking     可逆脱敏/流式还原/工具缓冲（§6 M3）
   ⑦ -m evals.m10_e2e        §9 端到端回归（U6 文件通道 DEFERRED 不计通过）
   ⑧ 既有门回归：ops/gate_d0.py 与 ops/gate_b1.py 各原样跑一遍
     （用启动本门的解释器 sys.executable——两门自身即以「系统 python 任意 cwd」
      为契约，回归即按其文档用法调用；输出全量透传）；
3. 每项透传完整输出并打印 [PASS]/[FAIL] 与退出码；末尾汇总表抓取各 eval
   自报摘要行与两门的结果行；任何 FAIL → 本脚本退出码 1。

本脚本对运行环境只依赖标准库（系统 python 无第三方依赖也能定位仓库、
启动子进程、汇总结果）。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"

#: 启动本门的解释器（⑧ 既有门回归用：两门自身契约即「系统 python 任意 cwd」）
GATE_PYTHON = sys.executable or "python"

EVAL_TIMEOUT_S = 1800   # 单个 eval 上限（m10 起服重放 / m3 全口径 fuzz）
GATE_TIMEOUT_S = 3600   # ⑧ 既有整门回归上限（gate_b1 内含 7 项，每项另有自家超时）

#: (显示名, 完整命令 argv, 超时秒)；①–⑦ 统一 .venv 解释器、cwd=仓库根；
#: ⑧ 用启动本门的解释器按两门文档用法原样调用（编号沿用任务单，无④）。
CHECKS: list[tuple[str, list[str], int]] = [
    ("① name_lint", [str(VENV_PYTHON), "-m", "ops.name_lint"], EVAL_TIMEOUT_S),
    ("② evals.m0_infra", [str(VENV_PYTHON), "-m", "evals.m0_infra"], EVAL_TIMEOUT_S),
    ("③ evals.m4_routing", [str(VENV_PYTHON), "-m", "evals.m4_routing"], EVAL_TIMEOUT_S),
    ("⑤ evals.m5_outguard", [str(VENV_PYTHON), "-m", "evals.m5_outguard"], EVAL_TIMEOUT_S),
    ("⑥ evals.m3_masking", [str(VENV_PYTHON), "-m", "evals.m3_masking"], EVAL_TIMEOUT_S),
    ("⑦ evals.m10_e2e", [str(VENV_PYTHON), "-m", "evals.m10_e2e"], EVAL_TIMEOUT_S),
    ("⑧ 回归 ops/gate_d0.py", [GATE_PYTHON, str(REPO_ROOT / "ops" / "gate_d0.py")],
     GATE_TIMEOUT_S),
    ("⑧ 回归 ops/gate_b1.py", [GATE_PYTHON, str(REPO_ROOT / "ops" / "gate_b1.py")],
     GATE_TIMEOUT_S),
]

#: 各 eval 的自报摘要行 + 两门的结果行（透传输出中抓取，进汇总表）
_SUMMARY_PATTERNS = (
    re.compile(r"^name_lint: .+"),
    re.compile(r"^M0 INFRA: .+"),
    re.compile(r"^M4 ROUTING: .+"),
    re.compile(r"^M5 OUTGUARD: .+"),
    re.compile(r"^M3 MASKING: .+"),
    re.compile(r"^e2e_smoke: .+"),
    re.compile(r"^\[gate_d0\] 结果: .+"),
    re.compile(r"^\[gate_b1\] 结果: .+"),
)


def _summaries(output: str) -> list[str]:
    return [ln.rstrip() for ln in output.splitlines()
            if any(p.match(ln.rstrip()) for p in _SUMMARY_PATTERNS)]


def _run_check(name: str, argv: list[str], timeout_s: int) -> tuple[bool, list[str]]:
    interpreter = Path(argv[0]).name
    tail = " ".join(argv[1:])
    print(f"\n===== [gate_b2] RUN {name} ：{interpreter} {tail} "
          f"(cwd={REPO_ROOT}) =====", flush=True)
    try:
        proc = subprocess.run(
            argv,
            cwd=str(REPO_ROOT),
            env={**os.environ, "PYTHONUTF8": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        print(f"[FAIL] {name} — 超时（>{timeout_s}s）", flush=True)
        return False, [f"TIMEOUT >{timeout_s}s"]
    except OSError as exc:
        print(f"[FAIL] {name} — 解释器启动失败：{exc}", flush=True)
        return False, [f"interpreter error: {exc}"]
    output = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
    if output:
        sys.stdout.write(output)
        if not output.endswith("\n"):
            sys.stdout.write("\n")
    status = "PASS" if proc.returncode == 0 else "FAIL"
    print(f"[{status}] {name} (exit={proc.returncode})", flush=True)
    return proc.returncode == 0, _summaries(output)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    os.chdir(REPO_ROOT)
    os.environ["PYTHONUTF8"] = "1"

    print(f"[gate_b2] 仓库根: {REPO_ROOT}", flush=True)
    print(f"[gate_b2] 本门解释器(系统): {sys.executable}", flush=True)
    print(f"[gate_b2] 检查项解释器(venv): {VENV_PYTHON}", flush=True)
    if not VENV_PYTHON.exists():
        print(f"[FAIL] venv 解释器缺失: {VENV_PYTHON}（先按 README 建立 .venv 并 pip install -e .）",
              flush=True)
        return 1

    failures: list[str] = []
    summary_rows: list[tuple[str, bool, list[str]]] = []
    for name, argv, timeout_s in CHECKS:
        ok, summaries = _run_check(name, argv, timeout_s)
        summary_rows.append((name, ok, summaries))
        if not ok:
            failures.append(name)

    print("\n===== [gate_b2] 摘要 =====", flush=True)
    for name, ok, summaries in summary_rows:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}", flush=True)
        for line in summaries:
            print(f"        {line}", flush=True)
    if failures:
        print(f"[gate_b2] 结果: {len(failures)}/{len(CHECKS)} FAIL → 退出码 1", flush=True)
        return 1
    print(f"[gate_b2] 结果: {len(CHECKS)}/{len(CHECKS)} 全部 PASS → 退出码 0", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
