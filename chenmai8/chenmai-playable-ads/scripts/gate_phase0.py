#!/usr/bin/env python3
"""Phase 0（D1 骨架跑通日）验收门：把开工前五项验收固化为可重复执行的脚本。

定位：本文件是生产线的 spec+eval 资产之一——"通过线"不靠口头承诺，
而靠本脚本每次真实运行来裁定。任何一项 [FAIL] 即以退出码 1 阻塞后续里程碑。
每项门检查的注释说明它守护的是哪条底线；修复时先让门变绿，再继续开发。

用法（系统 python，工作目录任意）：

    python scripts/gate_phase0.py

约定：
- 仓库根按本文件位置自动定位（scripts/ 的上一级），不依赖当前工作目录；
- 所有 Python 子命令一律使用 python/.venv/Scripts/python.exe（虚拟环境）执行；
- 逐项打印 [PASS]/[FAIL]；全部通过打印 "GATE PHASE0: PASS" 并退出 0，
  否则打印 "GATE PHASE0: FAIL" 并退出 1。

五个门项（对应 Phase 0 / D1 的跑通标志）：
  1. pfcore 编排 CLI 骨架可加载：
     `venv python -m pfcore --help`（在 python/ 目录）exit 0。
     守住"Python 包结构与 -m 入口未被破坏"的底线。
  2. packager 打包器 CLI 骨架可加载：
     `node packages/packager/bin.mjs --help`（在仓库根）exit 0。
     守住"Node 侧入口 + 命令在仓库根执行"的约定。
  3. 上游对照 spike 工程（_vendor/spike，仅本机、不入库）六渠道产物齐全：
     解析 _vendor/NOTES.md 记录的全部产物路径逐一 exists 检查，
     并校验六个渠道代号（AL/UNITY/GOOGLE/FB/TIKTOK/MINTEGRAL）全覆盖。
     NOTES.md 是 spike 事实记录的唯一真源；对照轨产物是自研打包器的
     交叉验证基线，丢失即无法做 D6 对照，故纳入门禁。
  4. llmgw 网关离线自测全过 + 零厂商端点硬编码：
     `venv python -m llmgw.selftest`（在 python/ 目录）exit 0（6 项 mock 全过）；
     且扫描 python/llmgw/**/*.py，命中任何厂商端点/厂商名即 FAIL——
     llmgw 的设计红线是一切由环境变量注入，代码里不允许出现具体厂商。
  5. qacore 质检器雏形真实跑通：
     `venv python -m qacore run qacore/tests/fixtures/mini.html
      --channel preview --out <tmp>/qacore-report.json`（在 python/ 目录）
     exit 0，报告 JSON 存在且含非空 checks 键。
     守住"本地伺服 + 无头浏览器 + 报告结构"这条核心 eval 链路
     （报告逐项检查当前为 10 项雏形检查，门禁只断言结构与全过，不钉死数量）。

本脚本自身公开入库，注释与字符串一律使用中性名，不出现任何上游项目名；
上游对照工程的事实（渠道键名、产物清单、版本钉死）只记录在
_vendor/NOTES.md（本地文件，.gitignore 覆盖），脚本运行时读取。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Windows 控制台默认非 UTF-8 代码页，先固定本进程输出编码，避免中文乱码。
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# ------------------------------------------------------------------ 路径定位
# 仓库根 = 本文件（repo/scripts/gate_phase0.py）的上一级目录。
# 全部子命令用绝对路径 + 显式 cwd，工作目录任意都能跑。
REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIR = REPO_ROOT / "python"                # Python 模块与 venv 所在目录
VENV_PYTHON = PYTHON_DIR / ".venv" / "Scripts" / "python.exe"

VENDOR_DIR = REPO_ROOT / "_vendor"               # 上游参考 clone（不入库）
SPIKE_DIR = VENDOR_DIR / "spike"                 # 上游对照 spike 工程
SPIKE_NOTES = VENDOR_DIR / "NOTES.md"            # spike 事实记录（唯一真源）

QACORE_REPORT = REPO_ROOT / "tmp" / "gate-phase0" / "qacore-report.json"
# ^ 质检报告写到仓库 tmp/ 下（.gitignore 已覆盖 tmp/），每次门禁先删旧文件，
#   保证"报告存在"是本次运行的真事实而不是上次残留。

# 六个目标渠道在 spike 产物文件名中的代号（事实来源：_vendor/NOTES.md §3/§4）。
# 这些是广告平台渠道代号，非任何上游开源项目名，可安全出现在公开仓。
CHANNEL_CODES = ("AL", "UNITY", "GOOGLE", "FB", "TIKTOK", "MINTEGRAL")

# llmgw 厂商端点/厂商名扫描黑名单：代码中零命中才通过（一切由环境变量驱动）。
# 词表只收具体厂商标识与端点域名；扩展时注意误报（只加确定性强的词）。
VENDOR_ENDPOINT_RE = re.compile(
    r"bigmodel|openai\.com|dashscope|anthropic|deepseek|moonshot|stepfun"
    r"|generativelanguage|cohere|zhipu|mistral\.ai|minimax|baichuan",
    re.IGNORECASE,
)


# ------------------------------------------------------------------ 门禁框架
class Gate:
    """逐项登记 [PASS]/[FAIL]，最后汇总决定退出码。"""

    def __init__(self) -> None:
        self.failures = 0

    def item(self, label: str, ok: bool, details: list[str] | tuple = ()) -> bool:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
        for line in details:
            print(f"       {line}")
        if not ok:
            self.failures += 1
        return ok


def run_cmd(cmd: list[str], cwd: Path, timeout: int = 300) -> tuple[int, list[str]]:
    """跑一条子命令，返回 (退出码, 输出行)。

    统一注入 PYTHONUTF8=1，让 venv 内 Python 子进程的管道输出固定 UTF-8
    （Windows 下 Python 对管道默认用本地代码页，不注入则中文会乱码）。
    解码用 errors="replace"，保证任何字节都不至于让门禁本身崩溃。
    """
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, timeout=timeout, env=env,
    )
    text = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    return proc.returncode, [ln for ln in text.splitlines() if ln.strip()]


# ------------------------------------------------------------------ 五个门项

def check_1_pfcore(gate: Gate) -> None:
    """门项 1：pfcore `--help`（venv，在 python/ 目录）exit 0。"""
    label = "1/5 pfcore CLI 骨架：venv python -m pfcore --help -> exit 0"
    if not VENV_PYTHON.is_file():
        gate.item(label, False, [f"缺少虚拟环境解释器：{VENV_PYTHON}"])
        return
    try:
        rc, out = run_cmd([str(VENV_PYTHON), "-m", "pfcore", "--help"],
                          cwd=PYTHON_DIR, timeout=120)
    except Exception as exc:  # 子进程消失/超时等，一律按 FAIL 呈现而非崩溃
        gate.item(label, False, [f"子进程异常：{exc!r}"])
        return
    gate.item(label, rc == 0, [f"exit={rc}"] + out[:6])


def check_2_packager(gate: Gate) -> None:
    """门项 2：packager `--help`（node，在仓库根）exit 0。"""
    label = "2/5 packager CLI 骨架：node packages/packager/bin.mjs --help -> exit 0"
    bin_path = REPO_ROOT / "packages" / "packager" / "bin.mjs"
    if not bin_path.is_file():
        gate.item(label, False, [f"入口文件不存在：{bin_path}"])
        return
    try:
        rc, out = run_cmd(["node", "packages/packager/bin.mjs", "--help"],
                          cwd=REPO_ROOT, timeout=120)
    except Exception as exc:
        gate.item(label, False, [f"子进程异常：{exc!r}"])
        return
    gate.item(label, rc == 0, [f"exit={rc}"] + out[:6])


def check_3_spike_artifacts(gate: Gate) -> None:
    """门项 3：spike 六渠道产物存在（以 NOTES.md 记录的路径为准逐一检查）。"""
    label = ("3/5 上游对照 spike 六渠道产物：_vendor/NOTES.md 记录路径全部存在"
             "（含 AL/UNITY/GOOGLE/FB/TIKTOK/MINTEGRAL 全覆盖）")
    if not SPIKE_NOTES.is_file():
        gate.item(label, False, [f"事实记录文件不存在：{SPIKE_NOTES}"])
        return
    try:
        notes = SPIKE_NOTES.read_text(encoding="utf-8")
    except OSError as exc:
        gate.item(label, False, [f"读取失败：{exc}"])
        return

    # 产物路径在 NOTES.md 中一律以反引号包裹的 `dist/...` 形式记录；
    # 正锚定反引号 + dist/ 前缀，避免误抓 "find dist -type f" 之类的命令文本。
    recorded = sorted(set(re.findall(r"`(dist/[^`\s]+)`", notes)))
    details: list[str] = []
    if len(recorded) < len(CHANNEL_CODES):
        details.append(f"NOTES.md 仅解析出 {len(recorded)} 条产物路径（应≥{len(CHANNEL_CODES)}）")

    missing = [p for p in recorded if not (SPIKE_DIR / p).is_file()]
    for p in recorded:
        details.append(f"{'ok ' if p not in missing else 'MISSING '}{SPIKE_DIR / p}")

    # 渠道代号覆盖：每个渠道至少要有一件产物文件名包含其代号。
    codes_missing = [c for c in CHANNEL_CODES
                     if not any(f"_{c}." in p for p in recorded)]
    if codes_missing:
        details.append(f"渠道代号缺失：{codes_missing}")

    ok = bool(recorded) and not missing and not codes_missing \
        and len(recorded) >= len(CHANNEL_CODES)
    gate.item(label, ok, details)


def scan_vendor_endpoints() -> tuple[list[str], int]:
    """扫描 python/llmgw 下全部 .py，返回 (命中描述列表, 已扫文件数)。"""
    hits: list[str] = []
    scanned = 0
    for f in sorted((PYTHON_DIR / "llmgw").rglob("*.py")):
        scanned += 1
        for lineno, line in enumerate(
                f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            m = VENDOR_ENDPOINT_RE.search(line)
            if m:
                hits.append(f"{f.relative_to(REPO_ROOT)}:{lineno}: 命中 {m.group(0)!r}")
    return hits, scanned


def check_4_llmgw(gate: Gate) -> None:
    """门项 4：llmgw 离线自测 exit 0 + python/llmgw 零厂商端点硬编码。"""
    label = ("4/5 llmgw 网关：-m llmgw.selftest exit 0（mock 全过）"
             "且 python/llmgw 零厂商端点硬编码")
    details: list[str] = []
    ok = True

    if not VENV_PYTHON.is_file():
        ok = False
        details.append(f"缺少虚拟环境解释器：{VENV_PYTHON}")
    else:
        try:
            rc, out = run_cmd([str(VENV_PYTHON), "-m", "llmgw.selftest"],
                              cwd=PYTHON_DIR, timeout=180)
        except Exception as exc:
            rc, out = -1, [f"子进程异常：{exc!r}"]
        details.append(f"selftest exit={rc}")
        details.extend(out[-3:])
        if rc != 0:
            ok = False

    hits, scanned = scan_vendor_endpoints()
    details.append(f"厂商端点扫描：{scanned} 个 .py 文件，命中 {len(hits)} 处")
    details.extend(hits[:10])
    if hits:
        ok = False

    gate.item(label, ok, details)


def check_5_qacore(gate: Gate) -> None:
    """门项 5：qacore 真实质检一次 mini.html 夹具，报告含 checks 键且全过。"""
    label = ("5/5 qacore 质检器：-m qacore run qacore/tests/fixtures/mini.html "
             "--channel preview -> exit 0 且报告含非空 checks 键")
    if not VENV_PYTHON.is_file():
        gate.item(label, False, [f"缺少虚拟环境解释器：{VENV_PYTHON}"])
        return
    fixture = PYTHON_DIR / "qacore" / "tests" / "fixtures" / "mini.html"
    if not fixture.is_file():
        gate.item(label, False, [f"夹具不存在：{fixture}"])
        return

    # 先删旧报告再跑，"报告存在"才是本次运行的真事实。
    QACORE_REPORT.parent.mkdir(parents=True, exist_ok=True)
    if QACORE_REPORT.exists():
        QACORE_REPORT.unlink()

    try:
        rc, out = run_cmd(
            [str(VENV_PYTHON), "-m", "qacore", "run",
             "qacore/tests/fixtures/mini.html",
             "--channel", "preview", "--out", str(QACORE_REPORT)],
            cwd=PYTHON_DIR, timeout=300,
        )
    except Exception as exc:
        gate.item(label, False, [f"子进程异常：{exc!r}"])
        return

    details = [f"exit={rc}"] + out[-3:]
    ok = rc == 0
    if not QACORE_REPORT.is_file():
        ok = False
        details.append(f"报告未产出：{QACORE_REPORT}")
    else:
        try:
            report = json.loads(QACORE_REPORT.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            ok = False
            details.append(f"报告不可解析：{exc}")
        else:
            checks = report.get("checks")
            if not isinstance(checks, list) or not checks:
                ok = False
                details.append(f"报告缺非空 checks 键：{type(checks).__name__}")
            else:
                n_fail = sum(1 for c in checks
                             if isinstance(c, dict) and c.get("status") == "fail")
                details.append(f"报告 {QACORE_REPORT.name}：{len(checks)} 项检查，{n_fail} FAIL")
                if n_fail:
                    ok = False

    gate.item(label, ok, details)


# ------------------------------------------------------------------ 主流程

def main() -> int:
    print("=" * 72)
    print("Phase 0 验收门（gate_phase0）")
    print(f"仓库根     : {REPO_ROOT}")
    print(f"venv 解释器: {VENV_PYTHON}")
    print("=" * 72)

    if not REPO_ROOT.is_dir() or not PYTHON_DIR.is_dir():
        print("[FAIL] 仓库结构异常：未找到 python/ 目录（脚本被挪动了？）")
        return 1

    gate = Gate()
    t0 = time.monotonic()
    for check in (check_1_pfcore, check_2_packager, check_3_spike_artifacts,
                  check_4_llmgw, check_5_qacore):
        check(gate)
    elapsed = time.monotonic() - t0

    total = 5
    print("-" * 72)
    if gate.failures:
        print(f"GATE PHASE0: FAIL（{total - gate.failures}/{total} 项通过，"
              f"耗时 {elapsed:.1f}s）——先修复失败项，再继续推进里程碑。")
        return 1
    print(f"GATE PHASE0: PASS（{total}/{total} 项通过，耗时 {elapsed:.1f}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
