#!/usr/bin/env python3
"""B3 收工门（Gate G-B3）：D3（文件通道 + WebUI 骨架）收工门。系统 python 从任意
cwd 可运行；内部统一用仓库 .venv 执行各项检查。

用法（系统 python 即可，无需激活 venv，可在任意工作目录）::

    python D:/workspace/澄迈8项目/政务AI脱敏网关/repo/ops/gate_b3.py

行为（任务单 T3.4；结构沿用 ops/gate_b2.py，编号 = 任务单原文）：
1. 内部 chdir 到仓库根，统一设 PYTHONUTF8=1，stdout/stderr 重配为 UTF-8；
2. 依次运行（①–⑤ 用仓库 .venv 解释器 .venv/Scripts/python.exe，cwd=仓库根）：
   ① -m ops.name_lint        公开仓库禁用词守卫（零命中为过）
   ② -m evals.m0_infra       基础设施 + 配置 + §5 契约模型（全部检查通过为过）
   ③ -m evals.m6_filesvc     文件通道全量：文本层解析/体检/风险分级 + 彻底删除式
                             导出零残留（§6 M6；导出物 re-ingest 零命中铁律）
   ④ -m evals.m9_webui       WebUI 部分口径：体检页骨架 + /v1/files/* 端点契约
                             （聊天/看板/演示控制页四页全量验收待 T5.2）
   ⑤ -m evals.m10_e2e        §9 端到端六用例（U6 文件通道本批转正计入 PASS——
                             摘要行 DEFERRED 计数必须为 0，见下方附加断言）
   ⑥ 既有门回归：ops/gate_b2.py 用启动本门的解释器原样跑一遍（该门自身契约即
     「系统 python 任意 cwd」，回归即按其文档用法调用；输出全量透传）；
3. 每项透传完整输出并打印 [PASS]/[FAIL] 与退出码；末尾汇总表抓取各 eval 自报
   摘要行与 ⑥ 的结果行；任何 FAIL → 本脚本退出码 1。

⑤ 附加断言（任务单「U6 本批转正计入 PASS」）：e2e_smoke 自身契约是 DEFERRED
不计失败、不影响退出码；U6 转正后本门收紧为——摘要行
``e2e_smoke: N PASS / M FAIL / K DEFERRED`` 中 K 必须为 0（U6 或任何用例退回
DEFERRED 即本门 FAIL）。FAIL=0 由退出码保证，K=0 由本门保证。

超时预算（任务单）：单项 1800s；⑥ 整门回归 3600s。

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

#: 启动本门的解释器（⑥ 既有门回归用：该门自身契约即「系统 python 任意 cwd」）
GATE_PYTHON = sys.executable or "python"

EVAL_TIMEOUT_S = 1800   # 单个 eval 上限（m6 全量导出链 / m10 起服重放）
GATE_TIMEOUT_S = 3600   # ⑥ 既有整门回归上限（gate_b2 内含 8 项，每项另有自家超时）

#: (显示名, 完整命令 argv, 超时秒)；①–⑤ 统一 .venv 解释器、cwd=仓库根；
#: ⑥ 用启动本门的解释器按该门文档用法原样调用（编号沿用任务单）。
CHECKS: list[tuple[str, list[str], int]] = [
    ("① name_lint", [str(VENV_PYTHON), "-m", "ops.name_lint"], EVAL_TIMEOUT_S),
    ("② evals.m0_infra", [str(VENV_PYTHON), "-m", "evals.m0_infra"], EVAL_TIMEOUT_S),
    ("③ evals.m6_filesvc", [str(VENV_PYTHON), "-m", "evals.m6_filesvc"], EVAL_TIMEOUT_S),
    ("④ evals.m9_webui", [str(VENV_PYTHON), "-m", "evals.m9_webui"], EVAL_TIMEOUT_S),
    ("⑤ evals.m10_e2e", [str(VENV_PYTHON), "-m", "evals.m10_e2e"], EVAL_TIMEOUT_S),
    ("⑥ 回归 ops/gate_b2.py", [GATE_PYTHON, str(REPO_ROOT / "ops" / "gate_b2.py")],
     GATE_TIMEOUT_S),
]

#: 各 eval 的自报摘要行 + ⑥ 的结果行（透传输出中抓取，进汇总表）
_SUMMARY_PATTERNS = (
    re.compile(r"^name_lint: .+"),
    re.compile(r"^M0 INFRA: .+"),
    re.compile(r"^M6 FILESVC: .+"),
    re.compile(r"^m9_webui: .+"),
    re.compile(r"^e2e_smoke: .+"),
    re.compile(r"^\[gate_b2\] 结果: .+"),
)

#: ⑤ 摘要行的精确形状（附加断言用）
_E2E_SUMMARY_RE = re.compile(
    r"^e2e_smoke: (?P<passed>\d+) PASS / (?P<failed>\d+) FAIL / (?P<deferred>\d+) DEFERRED"
)


def _summaries(output: str) -> list[str]:
    return [ln.rstrip() for ln in output.splitlines()
            if any(p.match(ln.rstrip()) for p in _SUMMARY_PATTERNS)]


def _assert_e2e_promoted(summaries: list[str]) -> str | None:
    """⑤ 附加断言：U6 本批转正计入 PASS ⇒ DEFERRED 计数必须为 0。"""
    for line in summaries:
        m = _E2E_SUMMARY_RE.match(line)
        if m:
            deferred = int(m.group("deferred"))
            if deferred != 0:
                return f"U6 已转正，不允许任何用例 DEFERRED（实际 {deferred}）：{line}"
            return None
    return "未在 m10_e2e 输出中找到「e2e_smoke: …」摘要行"


#: 检查项 → 通过退出码之后的附加校验（返回 None=过，字符串=失败原因）
_EXTRA_VALIDATORS = {
    "⑤ evals.m10_e2e": _assert_e2e_promoted,
}


def _run_check(name: str, argv: list[str], timeout_s: int) -> tuple[bool, list[str]]:
    interpreter = Path(argv[0]).name
    tail = " ".join(argv[1:])
    print(f"\n===== [gate_b3] RUN {name} ：{interpreter} {tail} "
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

    print(f"[gate_b3] 仓库根: {REPO_ROOT}", flush=True)
    print(f"[gate_b3] 本门解释器(系统): {sys.executable}", flush=True)
    print(f"[gate_b3] 检查项解释器(venv): {VENV_PYTHON}", flush=True)
    if not VENV_PYTHON.exists():
        print(f"[FAIL] venv 解释器缺失: {VENV_PYTHON}（先按 README 建立 .venv 并 pip install -e .）",
              flush=True)
        return 1

    failures: list[str] = []
    summary_rows: list[tuple[str, bool, list[str]]] = []
    for name, argv, timeout_s in CHECKS:
        ok, summaries = _run_check(name, argv, timeout_s)
        validator = _EXTRA_VALIDATORS.get(name)
        if ok and validator is not None:
            problem = validator(summaries)
            if problem:
                print(f"[FAIL] {name} — {problem}", flush=True)
                ok = False
        summary_rows.append((name, ok, summaries))
        if not ok:
            failures.append(name)

    print("\n===== [gate_b3] 摘要 =====", flush=True)
    for name, ok, summaries in summary_rows:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}", flush=True)
        for line in summaries:
            print(f"        {line}", flush=True)
    if failures:
        print(f"[gate_b3] 结果: {len(failures)}/{len(CHECKS)} FAIL → 退出码 1", flush=True)
        return 1
    print(f"[gate_b3] 结果: {len(CHECKS)}/{len(CHECKS)} 全部 PASS → 退出码 0", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
