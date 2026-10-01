#!/usr/bin/env python3
"""B2 收工门（Gate G-B2）：D2（路由 + 输出侧）收工门。系统 python 从任意 cwd 可运行；
内部统一用仓库 .venv 执行各项检查。

用法（系统 python 即可，无需激活 venv，可在任意工作目录）::

    python D:/workspace/澄迈8项目/政务AI脱敏网关/repo/ops/gate_b2.py

行为（任务单 T2.5；结构沿用 ops/gate_b1.py / ops/gate_d0.py，编号 = 任务单原文）：
1. 内部 chdir 到仓库根，统一设 PYTHONUTF8=1，stdout/stderr 重配为 UTF-8；
2. 依次用仓库 .venv 解释器（.venv/Scripts/python.exe，cwd=仓库根）运行十项：
   ①    -m ops.name_lint        公开仓库禁用词守卫（零命中为过）
   ②-1  -m evals.m0_infra       基础设施 + 配置 + §5 契约模型（批次0/1 回归）
   ②-2  -m evals.m10_e2e        §9 端到端回归（U6 文件通道 DEFERRED 不计通过）
   ②-3  -m evals.m8_generator   生成器 seed 复现/规模/数据质量/seeded 夹具（回归）
   ②-4  -m evals.m2_recognizers 规则层达标验收（含逐类达标线表，§6 M2；回归）
   ②-5  -m evals.m7_audit       审计落库/零明文硬闸/会话存储（回归）
   ②-6  -m evals.t0_labels      标签体系文档自验收（回归）
   ③-1  -m evals.m4_routing     §5.2 决策矩阵逐格 + 优先级冲突（本批新 eval）
   ③-2  -m evals.m5_outguard    输出侧标识/拦截文案/代答/复检钩子（本批新 eval）
   ③-3  -m evals.m3_masking     可逆脱敏/流式还原/工具缓冲（本批新 eval）
3. 每项透传完整输出并打印 [PASS]/[FAIL] 与退出码；末尾汇总表抓取各 eval
   自报摘要行；任何 FAIL → 本脚本退出码 1。

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

EVAL_TIMEOUT_S = 1800  # 单项上限（m8 双跑复现 / m10 起服重放 / m3 全口径 fuzz）

#: (显示名, 完整命令 argv, 超时秒)；十项统一 .venv 解释器、cwd=仓库根
#: （顺序 = 任务单原文：① → ② 六项回归 → ③ 三项新 eval）。
CHECKS: list[tuple[str, list[str], int]] = [
    ("① name_lint", [str(VENV_PYTHON), "-m", "ops.name_lint"], EVAL_TIMEOUT_S),
    ("②-1 回归 evals.m0_infra", [str(VENV_PYTHON), "-m", "evals.m0_infra"],
     EVAL_TIMEOUT_S),
    ("②-2 回归 evals.m10_e2e", [str(VENV_PYTHON), "-m", "evals.m10_e2e"],
     EVAL_TIMEOUT_S),
    ("②-3 回归 evals.m8_generator", [str(VENV_PYTHON), "-m", "evals.m8_generator"],
     EVAL_TIMEOUT_S),
    ("②-4 回归 evals.m2_recognizers", [str(VENV_PYTHON), "-m", "evals.m2_recognizers"],
     EVAL_TIMEOUT_S),
    ("②-5 回归 evals.m7_audit", [str(VENV_PYTHON), "-m", "evals.m7_audit"],
     EVAL_TIMEOUT_S),
    ("②-6 回归 evals.t0_labels", [str(VENV_PYTHON), "-m", "evals.t0_labels"],
     EVAL_TIMEOUT_S),
    ("③-1 新 evals.m4_routing", [str(VENV_PYTHON), "-m", "evals.m4_routing"],
     EVAL_TIMEOUT_S),
    ("③-2 新 evals.m5_outguard", [str(VENV_PYTHON), "-m", "evals.m5_outguard"],
     EVAL_TIMEOUT_S),
    ("③-3 新 evals.m3_masking", [str(VENV_PYTHON), "-m", "evals.m3_masking"],
     EVAL_TIMEOUT_S),
]

#: 各 eval 的自报摘要行（透传输出中抓取，进汇总表）
_SUMMARY_PATTERNS = (
    re.compile(r"^name_lint: .+"),
    re.compile(r"^M0 INFRA: .+"),
    re.compile(r"^e2e_smoke: .+"),
    re.compile(r"^M8 GENERATOR: .+"),
    re.compile(r"^M2 RECOGNIZERS: .+"),
    re.compile(r"^M7 AUDIT.*: .+"),
    re.compile(r"^T0 LABELS: .+"),
    re.compile(r"^M4 ROUTING: .+"),
    re.compile(r"^M5 OUTGUARD: .+"),
    re.compile(r"^M3 MASKING: .+"),
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
