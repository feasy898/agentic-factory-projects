#!/usr/bin/env python3
"""B4 收工门（Gate G-B4）：D4（扫描件 OCR + 语义层）收工门。系统 python 从任意
cwd 可运行；内部统一用仓库 .venv 执行各项检查。

用法（系统 python 即可，无需激活 venv，可在任意工作目录）::

    python D:/workspace/澄迈8项目/政务AI脱敏网关/repo/ops/gate_b4.py

行为（任务单 T4.4；结构沿用 ops/gate_b3.py，编号 = 任务单原文）：
1. 内部 chdir 到仓库根，统一设 PYTHONUTF8=1，stdout/stderr 重配为 UTF-8；
2. 依次运行（①–⑥ 用仓库 .venv 解释器 .venv/Scripts/python.exe，cwd=仓库根）：
   ① -m ops.name_lint        公开仓库禁用词守卫（零命中为过）
   ② -m evals.m0_infra       基础设施 + 配置 + §5 契约模型（全部检查通过为过）
   ③ -m evals.m6_ocr         扫描件路线（T4.1）：纯图像 seeded scan_pdf 体检/召回
                             ≥0.90/bbox/导出重栅格化打码零残留（§6 M6 OCR 部分）
   ④ -m evals.m2_semantic    语义层（T4.2）：注入词表三档拦截率 ≥0.90/正常公文
                             误拦 ≤0.05/decide 集成/judge 降级路径（§6 M2 D4 追加）
   ⑤ -m evals.m6_filesvc     文件通道回归：文本层解析/体检/风险分级 + 彻底删除式
                             导出零残留（T4.1 栅格兜底路径并入后回归）
   ⑥ -m evals.m10_e2e        §9 端到端七用例（U1–U7，U7 注入拦截 T4.3 起——
                             摘要行 DEFERRED 计数必须为 0 且 U7 须 PASS，见下方
                             附加断言）
   ⑦ 既有门回归：ops/gate_b3.py 用启动本门的解释器原样跑一遍（该门自身契约即
     「系统 python 任意 cwd」，回归即按其文档用法调用；输出全量透传；其内含
     gate_b2 十项整链回归）；
3. 每项透传完整输出并打印 [PASS]/[FAIL] 与退出码；末尾汇总表抓取各 eval 自报
   摘要行与 ⑦ 的结果行；任何 FAIL → 本脚本退出码 1。

⑥ 附加断言（任务单「m10_e2e 含 U7」）：e2e_smoke 自身契约是 DEFERRED 不计失败、
不影响退出码；B3 起 U6 已转正、T4.3 起 U7 生效，本门收紧为——摘要行
``e2e_smoke: N PASS / M FAIL / K DEFERRED`` 中 K 必须为 0，且逐用例行
``PASS   U7 注入拦截 — …`` 必须存在（U7 或任何用例 DEFERRED/缺席即本门 FAIL）。
FAIL=0 由退出码保证，K=0 与 U7 在位由本门保证。

超时预算（任务单）：单项 1800s；⑦ 整门回归 3600s。

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

#: 启动本门的解释器（⑦ 既有门回归用：该门自身契约即「系统 python 任意 cwd」）
GATE_PYTHON = sys.executable or "python"

EVAL_TIMEOUT_S = 1800   # 单个 eval 上限（m6_ocr 渲染+OCR / m6_filesvc 全量导出链 /
                        # m10_e2e 起服重放）
GATE_TIMEOUT_S = 3600   # ⑦ 既有整门回归上限（gate_b3 内含 6 项并嵌套 gate_b2，
                        # 各自另有自家超时）

#: (显示名, 完整命令 argv, 超时秒)；①–⑥ 统一 .venv 解释器、cwd=仓库根；
#: ⑦ 用启动本门的解释器按该门文档用法原样调用（编号沿用任务单）。
CHECKS: list[tuple[str, list[str], int]] = [
    ("① name_lint", [str(VENV_PYTHON), "-m", "ops.name_lint"], EVAL_TIMEOUT_S),
    ("② evals.m0_infra", [str(VENV_PYTHON), "-m", "evals.m0_infra"], EVAL_TIMEOUT_S),
    ("③ evals.m6_ocr", [str(VENV_PYTHON), "-m", "evals.m6_ocr"], EVAL_TIMEOUT_S),
    ("④ evals.m2_semantic", [str(VENV_PYTHON), "-m", "evals.m2_semantic"], EVAL_TIMEOUT_S),
    ("⑤ 回归 evals.m6_filesvc", [str(VENV_PYTHON), "-m", "evals.m6_filesvc"], EVAL_TIMEOUT_S),
    ("⑥ evals.m10_e2e(含U7)", [str(VENV_PYTHON), "-m", "evals.m10_e2e"], EVAL_TIMEOUT_S),
    ("⑦ 回归 ops/gate_b3.py", [GATE_PYTHON, str(REPO_ROOT / "ops" / "gate_b3.py")],
     GATE_TIMEOUT_S),
]

#: 各 eval 的自报摘要行 + ⑦ 的结果行（透传输出中抓取，进汇总表）
_SUMMARY_PATTERNS = (
    re.compile(r"^name_lint: .+"),
    re.compile(r"^M0 INFRA: .+"),
    re.compile(r"^M6 OCR\(scan-pdf\): .+"),
    re.compile(r"^M2 SEMANTIC: .+"),
    re.compile(r"^M6 FILESVC\b.*: .+"),   # 实际行形如 M6 FILESVC(text-layer+export): N/N
    re.compile(r"^e2e_smoke: .+"),
    re.compile(r"^\[gate_b3\] 结果: .+"),
)

#: ⑥ 摘要行的精确形状（附加断言用）
_E2E_SUMMARY_RE = re.compile(
    r"^e2e_smoke: (?P<passed>\d+) PASS / (?P<failed>\d+) FAIL / (?P<deferred>\d+) DEFERRED"
)

#: ⑥ 逐用例行的形状（e2e_smoke 末表 ``PASS    U7 注入拦截 — …``；断言 U7 在位）
_U7_LINE_RE = re.compile(r"^PASS\s+U7 注入拦截\b")


def _summaries(output: str) -> list[str]:
    return [ln.rstrip() for ln in output.splitlines()
            if any(p.match(ln.rstrip()) for p in _SUMMARY_PATTERNS)]


def _assert_e2e_u7(summaries: list[str]) -> str | None:
    """⑥ 附加断言：U7 起生效 ⇒ DEFERRED 计数必须为 0 且 U7 用例行必须 PASS 在位。"""
    for line in summaries:
        m = _E2E_SUMMARY_RE.match(line)
        if m:
            deferred = int(m.group("deferred"))
            if deferred != 0:
                return f"U7 已生效，不允许任何用例 DEFERRED（实际 {deferred}）：{line}"
            break
    else:
        return "未在 m10_e2e 输出中找到「e2e_smoke: …」摘要行"
    # U7 逐用例行在摘要行之前的末表里；对全量透传输出另查（summaries 只留摘要行）
    return None


def _assert_u7_line(output: str) -> str | None:
    """⑥ 附加断言第二段：逐用例末表中 U7 必须以 PASS 在位（「含 U7」的硬证据）。"""
    for ln in output.splitlines():
        if _U7_LINE_RE.match(ln.rstrip()):
            return None
    return "未在 m10_e2e 输出中找到「PASS U7 注入拦截」用例行（U7 缺席或未过）"


#: 检查项 → 通过退出码之后的附加校验（返回 None=过，字符串=失败原因）
#:（两段断言共用 ⑥ 的透传输出：第一段吃摘要行，第二段吃全量输出）
_EXTRA_VALIDATORS = {
    "⑥ evals.m10_e2e(含U7)": lambda out, sums: (
        _assert_e2e_u7(sums) or _assert_u7_line(out)),
}


def _run_check(name: str, argv: list[str], timeout_s: int) -> tuple[bool, list[str], str]:
    interpreter = Path(argv[0]).name
    tail = " ".join(argv[1:])
    print(f"\n===== [gate_b4] RUN {name} ：{interpreter} {tail} "
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
        return False, [f"TIMEOUT >{timeout_s}s"], ""
    except OSError as exc:
        print(f"[FAIL] {name} — 解释器启动失败：{exc}", flush=True)
        return False, [f"interpreter error: {exc}"], ""
    output = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
    if output:
        sys.stdout.write(output)
        if not output.endswith("\n"):
            sys.stdout.write("\n")
    status = "PASS" if proc.returncode == 0 else "FAIL"
    print(f"[{status}] {name} (exit={proc.returncode})", flush=True)
    return proc.returncode == 0, _summaries(output), output


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    os.chdir(REPO_ROOT)
    os.environ["PYTHONUTF8"] = "1"

    print(f"[gate_b4] 仓库根: {REPO_ROOT}", flush=True)
    print(f"[gate_b4] 本门解释器(系统): {sys.executable}", flush=True)
    print(f"[gate_b4] 检查项解释器(venv): {VENV_PYTHON}", flush=True)
    if not VENV_PYTHON.exists():
        print(f"[FAIL] venv 解释器缺失: {VENV_PYTHON}（先按 README 建立 .venv 并 pip install -e .）",
              flush=True)
        return 1

    failures: list[str] = []
    summary_rows: list[tuple[str, bool, list[str]]] = []
    for name, argv, timeout_s in CHECKS:
        ok, summaries, output = _run_check(name, argv, timeout_s)
        validator = _EXTRA_VALIDATORS.get(name)
        if ok and validator is not None:
            problem = validator(output, summaries)
            if problem:
                print(f"[FAIL] {name} — {problem}", flush=True)
                ok = False
        summary_rows.append((name, ok, summaries))
        if not ok:
            failures.append(name)

    print("\n===== [gate_b4] 摘要 =====", flush=True)
    for name, ok, summaries in summary_rows:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}", flush=True)
        for line in summaries:
            print(f"        {line}", flush=True)
    if failures:
        print(f"[gate_b4] 结果: {len(failures)}/{len(CHECKS)} FAIL → 退出码 1", flush=True)
        return 1
    print(f"[gate_b4] 结果: {len(CHECKS)}/{len(CHECKS)} 全部 PASS → 退出码 0", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
