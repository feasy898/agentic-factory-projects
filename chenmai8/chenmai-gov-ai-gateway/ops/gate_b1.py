#!/usr/bin/env python3
"""B1 收工门（Gate G-B1）：系统 python 从任意 cwd 可运行；内部统一用仓库 .venv 执行各项检查。

用法（系统 python 即可，无需激活 venv，可在任意工作目录）::

    python D:/workspace/澄迈8项目/政务AI脱敏网关/repo/ops/gate_b1.py

行为（任务单 T1.5；结构沿用 ops/gate_d0.py）：
1. 内部 chdir 到仓库根，统一设 PYTHONUTF8=1，stdout/stderr 重配为 UTF-8；
2. 依次用仓库 .venv 解释器（.venv/Scripts/python.exe）运行七项（顺序 = 任务单 ①–⑦）：
   ① -m ops.name_lint        公开仓库禁用词守卫（零命中为过）
   ② -m evals.m0_infra       基础设施 + 配置 + §5 契约模型（全部检查通过为过）
   ③ -m evals.m8_generator   生成器 seed 复现/规模/数据质量/seeded 夹具
   ④ -m evals.m2_recognizers 规则层达标验收（含逐类达标线表输出，§6 M2）
   ⑤ -m evals.m7_audit       审计落库/零明文硬闸/会话存储（T1.3 覆盖部分）
   ⑥ -m evals.t0_labels      标签体系文档自验收（T1.4）
   ⑦ -m evals.m10_e2e        §9 端到端回归（U6 文件通道 DEFERRED 不计通过）
3. 每项透传完整输出并打印 [PASS]/[FAIL] 与退出码；末尾汇总表附 m2 达标线常量
   （直接 import evals.thresholds，与 eval 同源）；任何 FAIL → 本脚本退出码 1。

本脚本对运行环境只依赖标准库（evals/thresholds.py 亦为纯常量模块，系统 python 可导入）。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"

#: (编号显示名, 模块参数)；统一以仓库 .venv 解释器运行，cwd=仓库根
CHECKS: list[tuple[str, list[str]]] = [
    ("① name_lint", ["-m", "ops.name_lint"]),
    ("② evals.m0_infra", ["-m", "evals.m0_infra"]),
    ("③ evals.m8_generator", ["-m", "evals.m8_generator"]),
    ("④ evals.m2_recognizers", ["-m", "evals.m2_recognizers"]),
    ("⑤ evals.m7_audit", ["-m", "evals.m7_audit"]),
    ("⑥ evals.t0_labels", ["-m", "evals.t0_labels"]),
    ("⑦ evals.m10_e2e", ["-m", "evals.m10_e2e"]),
]

CHECK_TIMEOUT_S = 1200  # m8 双跑复现 + m10 起服重放，单项上限 20min

#: 各 eval 的自报摘要行（透传输出中抓取，进汇总表）
_SUMMARY_PATTERNS = (
    re.compile(r"^M0 INFRA: .+"), re.compile(r"^M2 RECOGNIZERS: .+"),
    re.compile(r"^M7 AUDIT.*: .+"), re.compile(r"^M8 GENERATOR: .+"),
    re.compile(r"^T0 LABELS: .+"), re.compile(r"^e2e_smoke: .+"),
    re.compile(r"^name_lint: .+"),
)


def _summaries(output: str) -> list[str]:
    return [ln.rstrip() for ln in output.splitlines()
            if any(p.match(ln.rstrip()) for p in _SUMMARY_PATTERNS)]


def _run_check(name: str, args: list[str]) -> tuple[bool, list[str]]:
    print(f"\n===== [gate_b1] RUN {name} ：{VENV_PYTHON.name} {' '.join(args)} "
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
        return False, [f"TIMEOUT >{CHECK_TIMEOUT_S}s"]
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


def _m2_threshold_lines() -> list[str]:
    """m2 达标线（§6 M2）：直接读 evals/thresholds.py 常量，与 eval 同源。"""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        from evals import thresholds as th
    except Exception as exc:  # noqa: BLE001 — 汇总阶段附注，失败不影响门结果
        return [f"(thresholds 导入失败: {exc})"]
    return [
        f"达标线(§6 M2): ID_CARD/USCC/BANK_CARD 召回={th.RECALL_STRUCTURAL:.2f}（满分线）",
        f"         PHONE/EMAIL/IP/PLATE/SECRET_KEY/词面类 召回≥{th.RECALL_PATTERN:.2f}",
        f"         结构化号码 micro≥0.995；白名单误报率≤{th.WHITELIST_FPR_MAX:.2f}；"
        f"2000字延迟<{th.RULE_LATENCY_MS_2000CH}ms（10次均值）",
        f"         规模线: cases≥{th.RULE_CASES_MIN}, 白名单负例≥{th.WHITELIST_NEGATIVES_MIN}, "
        f"密级≥{th.CLASSIFICATION_SAMPLES_MIN}, 每类≥{th.RULE_CASES_PER_CLASS_MIN}",
    ]


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    os.chdir(REPO_ROOT)
    os.environ["PYTHONUTF8"] = "1"

    print(f"[gate_b1] 仓库根: {REPO_ROOT}", flush=True)
    print(f"[gate_b1] 本门解释器(系统): {sys.executable}", flush=True)
    print(f"[gate_b1] 检查项解释器(venv): {VENV_PYTHON}", flush=True)
    if not VENV_PYTHON.exists():
        print(f"[FAIL] venv 解释器缺失: {VENV_PYTHON}（先按 README 建立 .venv 并 pip install -e .）",
              flush=True)
        return 1

    failures: list[str] = []
    summary_rows: list[tuple[str, bool, list[str]]] = []
    for name, args in CHECKS:
        ok, summaries = _run_check(name, args)
        summary_rows.append((name, ok, summaries))
        if not ok:
            failures.append(name)

    print("\n===== [gate_b1] 摘要 =====", flush=True)
    for name, ok, summaries in summary_rows:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}", flush=True)
        for line in summaries:
            print(f"        {line}", flush=True)
    for line in _m2_threshold_lines():
        print(line, flush=True)
    if failures:
        print(f"[gate_b1] 结果: {len(failures)}/{len(CHECKS)} FAIL → 退出码 1", flush=True)
        return 1
    print(f"[gate_b1] 结果: {len(CHECKS)}/{len(CHECKS)} 全部 PASS → 退出码 0", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
