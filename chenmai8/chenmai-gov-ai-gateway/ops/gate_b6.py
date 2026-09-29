#!/usr/bin/env python3
"""B6 收工门（Gate G-B6）：批次6（上游 mock → 本地真实大模型）收工门。系统 python
从任意 cwd 可运行；内部统一用仓库 .venv 执行各项检查。

用法（系统 python 即可，无需激活 venv，可在任意工作目录）::

    python D:/workspace/澄迈8项目/政务AI脱敏网关/repo/ops/gate_b6.py

行为（任务单 T6.3；结构沿用 ops/gate_b5.py，编号 = 任务单原文）：
1. 内部 chdir 到仓库根，统一设 PYTHONUTF8=1，stdout/stderr 重配为 UTF-8；
2. 依次运行（①–④ 用仓库 .venv 解释器 .venv/Scripts/python.exe，cwd=仓库根）：
   ① -m ops.name_lint        公开仓库禁用词守卫（零命中为过）
   ② -m evals.m0_infra       基础设施 + 配置 + §5 契约模型（全部检查通过为过）
   ③ -m evals.m8_quality     回答质量评测（批次6 核心交付）：50 问答对脱敏前后
                             双答 × LLM-judge 对比，质量比值 ≥ 0.95（真实大模型面）
   ④ -m evals.m10_e2e        §9 八用例 U1–U8（U8 真实大模型全链）+ T5.3 演示数据
                             收尾——附加断言见下
   ⑤ 既有门回归：ops/gate_b5.py 用启动本门的解释器原样跑一遍（该门自身契约即
     「系统 python 任意 cwd」；输出全量透传；其内含 gate_b4 → gate_b3 → gate_b2
     整链回归与其自身全部检查项——含它自己的 m10_e2e 八用例）；
3. 每项透传完整输出并打印 [PASS]/[FAIL] 与退出码；末尾汇总表抓取各 eval 自报
   摘要行与 ⑤ 的结果行；任何 FAIL → 本脚本退出码 1。

真实大模型面（③ 全部推理用例 + ④ 的 U8）= 环境依赖项：GPU 机 llm_openai 服务
:9004 经 ops/tunnel_gpu.sh 隧道（本机 127.0.0.1:9004）供 config/app.yaml 的
internet_real / govcloud_real 两真实 profiles 使用。隧道断/服务未装载时的如实
降级口径（任务单：「隧道断则 U8 标 SKIP-GPU 注明」）：
- ④ U8：e2e_smoke 自身契约 = DEFERRED 不计失败；本门核查 U8 行的 DEFER 详情必须
  以「DEFERRED: 真实上游」开头（仅限服务不可达/未装载两种环境态），且摘要行
  DEFERRED 计数恰为 1（U1–U7 出现任何 DEFERRED 即 FAIL）→ 汇总注记 SKIP-GPU；
  U8 PASS 时 DEFERRED 计数必须为 0（沿 gate_b4/b5 收紧口径）。
- ③ m8_quality 自身契约 = 真实上游离线打印「M8 QUALITY: DEFERRED — …」exit 0；
  本门同样注记 SKIP-GPU 计过；正常态则要求「M8 QUALITY: N/N checks passed」
  全过、且全量输出含「PASS  quality-ratio」行（比值 ≥ 阈值的硬证据）。
- ⑤ 为既有门原样回归：gate_b5 对其 e2e 步的「DEFERRED==0」收紧在 U8 在库后隐含
  要求真实上游在线——隧道断时 ⑤ 将 FAIL，属如实反映；SKIP-GPU 阀只作用于本门
  ③④，不修改既有门。

超时预算（任务单）：单项 1800s；⑤ 整门回归 3600s。

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

#: 启动本门的解释器（⑤ 既有门回归用：该门自身契约即「系统 python 任意 cwd」）
GATE_PYTHON = sys.executable or "python"

EVAL_TIMEOUT_S = 1800   # 单个 eval 上限（m8_quality 50 对×双腿+100 次评分真实推理 /
                        # m10_e2e 八用例起服重放含 U8 双腿真实推理）
GATE_TIMEOUT_S = 3600   # ⑤ 既有整门回归上限（gate_b5 内含 6 项并嵌套 gate_b4
                        # → gate_b3 → gate_b2，各自另有自家超时）

#: (显示名, 完整命令 argv, 超时秒)；①–④ 统一 .venv 解释器、cwd=仓库根；
#: ⑤ 用启动本门的解释器按该门文档用法原样调用（编号沿用任务单）。
CHECKS: list[tuple[str, list[str], int]] = [
    ("① name_lint", [str(VENV_PYTHON), "-m", "ops.name_lint"], EVAL_TIMEOUT_S),
    ("② evals.m0_infra", [str(VENV_PYTHON), "-m", "evals.m0_infra"], EVAL_TIMEOUT_S),
    ("③ evals.m8_quality", [str(VENV_PYTHON), "-m", "evals.m8_quality"], EVAL_TIMEOUT_S),
    ("④ evals.m10_e2e", [str(VENV_PYTHON), "-m", "evals.m10_e2e"], EVAL_TIMEOUT_S),
    ("⑤ 回归 ops/gate_b5.py", [GATE_PYTHON, str(REPO_ROOT / "ops" / "gate_b5.py")],
     GATE_TIMEOUT_S),
]

#: 各 eval 的自报摘要行 + ⑤ 的结果行（透传输出中抓取，进汇总表）
_SUMMARY_PATTERNS = (
    re.compile(r"^name_lint: .+"),
    re.compile(r"^M0 INFRA: .+"),
    re.compile(r"^M8 QUALITY: .+"),          # 全过态「N/N checks passed」或
                                            # 离线态「DEFERRED — …」（→ SKIP-GPU 注记）
    re.compile(r"^PASS  quality-ratio.+"),   # 比值 ≥ 阈值的检查行（③ 正常态硬证据）
    re.compile(r"^  ratio = .+"),            # 质量比值数值行（m8_quality 缩进两格打印）
    re.compile(r"^e2e_smoke: .+"),
    re.compile(r"^m10_e2e\(.*\): .+"),       # 实际行形如 m10_e2e(+T5.3 演示数据): …
    re.compile(r"^\[gate_b5\] 结果: .+"),
)

#: ④ 摘要行的精确形状（附加断言用）
_E2E_SUMMARY_RE = re.compile(
    r"^e2e_smoke: (?P<passed>\d+) PASS / (?P<failed>\d+) FAIL / (?P<deferred>\d+) DEFERRED"
)

#: ④ 逐用例行（e2e_smoke 末表）：U7 必须以 PASS 在位（既有收紧）；U8 允许 PASS
#: 或环境态 DEFER（详情以「DEFERRED: 真实上游」开头 → SKIP-GPU 注记）
_U7_LINE_RE = re.compile(r"^PASS\s+U7 注入拦截\b")
_U8_LINE_RE = re.compile(
    r"^(?P<status>PASS|DEFER)\s+U8 真实大模型全链 — (?P<detail>.*)$")
_U8_DEFER_ENV_PREFIX = "DEFERRED: 真实上游"   # 不可达 / 未装载 两种环境态的公共前缀

#: ③ 摘要行的两种形态
_M8_PASSED_RE = re.compile(r"^M8 QUALITY: (?P<passed>\d+)/(?P<total>\d+) checks passed")
_M8_DEFERRED_RE = re.compile(r"^M8 QUALITY: DEFERRED\b")


def _summaries(output: str) -> list[str]:
    return [ln.rstrip() for ln in output.splitlines()
            if any(p.match(ln.rstrip()) for p in _SUMMARY_PATTERNS)]


def _validate_m8(output: str, summaries: list[str]) -> tuple[str | None, str]:
    """③ 附加断言（返回 (失败原因|None, 汇总注记)）。

    - 正常态：摘要行「M8 QUALITY: N/N checks passed」且 N==total，且全量输出含
      「PASS  quality-ratio」行（比值 ≥ 阈值检查确实在位并通过）；
    - 离线态：「M8 QUALITY: DEFERRED — …」（真实上游不可达/未装载，eval 自身契约
      exit 0）→ 注记 SKIP-GPU 计过（与 ④ U8 同一环境依赖口径）；
    - 两种形态都找不到 → FAIL。
    """
    for line in summaries:
        m = _M8_PASSED_RE.match(line)
        if m:
            if m.group("passed") != m.group("total"):
                return (f"m8_quality 摘要非全过: {line}"
                        f"（全量输出含 FAIL 检查行，见透传）"), ""
            for ln in output.splitlines():
                if ln.startswith("PASS  quality-ratio"):
                    return None, ""
            return "未找到「PASS  quality-ratio」检查行（质量比值检查缺席）", ""
        if _M8_DEFERRED_RE.match(line):
            return None, "SKIP-GPU（真实上游离线，m8_quality 按自身契约 DEFERRED exit 0）"
    return "未在 m8_quality 输出中找到「M8 QUALITY: …」摘要行", ""


def _validate_e2e(output: str, summaries: list[str]) -> tuple[str | None, str]:
    """④ 附加断言（返回 (失败原因|None, 汇总注记)）。

    - 摘要行「e2e_smoke: N PASS / M FAIL / K DEFERRED」必须在位且 M==0；
    - U7 逐用例行必须以 PASS 在位（沿 gate_b4/b5 收紧口径）；
    - U8 逐用例行必须在位：
      * PASS → K 必须为 0（U1–U7 不允许任何 DEFERRED）；
      * DEFER → 详情以「DEFERRED: 真实上游」开头（仅限环境态）且 K 恰为 1
        → 注记 SKIP-GPU 计过；
      * 缺席或 FAIL → FAIL（U8 FAIL 已由 e2e 退出码 1 保证本项红，此处兜底）。
    """
    for line in summaries:
        m = _E2E_SUMMARY_RE.match(line)
        if m:
            if int(m.group("failed")) != 0:
                return f"e2e 存在 FAIL（{line}）", ""
            deferred = int(m.group("deferred"))
            break
    else:
        return "未在 m10_e2e 输出中找到「e2e_smoke: …」摘要行", ""

    u7_ok = any(_U7_LINE_RE.match(ln.rstrip()) for ln in output.splitlines())
    if not u7_ok:
        return "未找到「PASS U7 注入拦截」用例行（U7 缺席或未过）", ""

    u8 = next((_U8_LINE_RE.match(ln.rstrip()) for ln in output.splitlines()
               if _U8_LINE_RE.match(ln.rstrip())), None)
    if u8 is None:
        return "未找到「U8 真实大模型全链」用例行（U8 缺席）", ""
    if u8.group("status") == "PASS":
        if deferred != 0:
            return (f"U8 PASS 但摘要行 DEFERRED={deferred} ≠ 0"
                    "（U1–U7 不允许任何 DEFERRED）"), ""
        return None, ""
    # U8 = DEFER：仅接受两种环境态，且全门只允许这 1 个 DEFER
    detail = u8.group("detail").strip()
    if not detail.startswith(_U8_DEFER_ENV_PREFIX):
        return (f"U8 DEFER 详情非环境态（须以「{_U8_DEFER_ENV_PREFIX}」开头）: "
                f"{detail[:120]!r}"), ""
    if deferred != 1:
        return (f"U8 DEFER 但摘要行 DEFERRED={deferred} ≠ 1"
                "（除 U8 外不允许任何 DEFERRED）"), ""
    return None, f"SKIP-GPU（U8 真实上游离线，DEFER 不计失败）: {detail[:100]}"


#: 检查项 → 通过退出码之后的附加校验（返回 (失败原因|None, 注记)）
_EXTRA_VALIDATORS = {
    "③ evals.m8_quality": _validate_m8,
    "④ evals.m10_e2e": _validate_e2e,
}


def _run_check(name: str, argv: list[str], timeout_s: int) -> tuple[bool, list[str], str]:
    interpreter = Path(argv[0]).name
    tail = " ".join(argv[1:])
    print(f"\n===== [gate_b6] RUN {name} ：{interpreter} {tail} "
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

    print(f"[gate_b6] 仓库根: {REPO_ROOT}", flush=True)
    print(f"[gate_b6] 本门解释器(系统): {sys.executable}", flush=True)
    print(f"[gate_b6] 检查项解释器(venv): {VENV_PYTHON}", flush=True)
    if not VENV_PYTHON.exists():
        print(f"[FAIL] venv 解释器缺失: {VENV_PYTHON}（先按 README 建立 .venv 并 pip install -e .）",
              flush=True)
        return 1

    failures: list[str] = []
    skips: list[str] = []
    summary_rows: list[tuple[str, bool, list[str], str]] = []
    for name, argv, timeout_s in CHECKS:
        ok, summaries, output = _run_check(name, argv, timeout_s)
        note = ""
        validator = _EXTRA_VALIDATORS.get(name)
        if validator is not None:
            problem, note = validator(output, summaries)
            if ok and problem:
                print(f"[FAIL] {name} — {problem}", flush=True)
                ok = False
        summary_rows.append((name, ok, summaries, note))
        if not ok:
            failures.append(name)
        elif note.startswith("SKIP-GPU"):
            skips.append(name)

    print("\n===== [gate_b6] 摘要 =====", flush=True)
    for name, ok, summaries, note in summary_rows:
        print(f"[{'PASS' if ok else 'FAIL'}]{(' ' + note) if note else ''} {name}", flush=True)
        for line in summaries:
            print(f"        {line}", flush=True)
    if skips:
        print(f"[gate_b6] SKIP-GPU 注记 {len(skips)} 项（真实大模型面=环境依赖，"
              f"如实降级非失败）: {'; '.join(skips)}", flush=True)
    if failures:
        print(f"[gate_b6] 结果: {len(failures)}/{len(CHECKS)} FAIL → 退出码 1", flush=True)
        return 1
    print(f"[gate_b6] 结果: {len(CHECKS)}/{len(CHECKS)} 全部 PASS → 退出码 0", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
