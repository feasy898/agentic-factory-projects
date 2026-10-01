#!/usr/bin/env python3
"""Phase 2（矩阵日之后的全量验收门）：gate_phase2——一条命令跑完三门回归 +
全量 48 包端到端矩阵 + 中性名扫描，全过才承认「4 模板 × 6 渠道 × {en,zh}」矩阵成立。

对应任务 T2.5：e2e_matrix 全量模式升级为 4 模板 × 6 渠道 × {en,zh} = 48 包后，
把全量口径固化为可重复执行的门。任何一项 [FAIL] 即退出码 1。

用法（系统 python，工作目录任意）：

    python scripts/gate_phase2.py            # 五项门禁，全过 exit 0

约定（同 gate_phase0/phase1/mainpath）：
- 仓库根按本文件位置自动定位（scripts/ 的上一级），不依赖当前工作目录；
- 子门/矩阵脚本用运行本脚本的同一解释器（系统 python）启动；脚本内部自会用
  python/.venv/Scripts/python.exe 跑 Python 子命令、PATH 中的 node 跑 Node 子命令；
- 逐项打印 [PASS]/[FAIL]（项内子断言另起一行标注 ok/FAIL）；
  全部通过打印 "GATE PHASE2: PASS" 并退出 0，否则 "GATE PHASE2: FAIL" 退出 1；
- 门禁框架与中性名扫描直接复用同目录 gate_mainpath（import，零第三方依赖），
  避免两份词表/扫描逻辑漂移。

五个门项（任务 T2.5 口径 ①②③）：
  1. 阶段门回归：python scripts/gate_phase0.py -> exit 0。
  2. 阶段门回归：python scripts/gate_phase1.py -> exit 0。
  3. 主路径门回归：python scripts/gate_mainpath.py -> exit 0（其内部含走查重建
     artifacts/demo-prebuilt/ 与兜底目录断言，本门只看它的总 exit 0）。
  4. 全量矩阵：python scripts/e2e_matrix.py --budget-sec 1200 -> exit 0——
     4 golden × {en,zh} × 6 冻结渠道 = 48 包全部真实构建→打包→qacore 逐包质检，
     0 fail；硬预算 ≤1200s（20 分钟）由 e2e_matrix 自身超预算即 exit 1 把关，
     本门另读 artifacts/matrix/summary.json 双重断言：
     totals = {pass: 48, fail: 0, skip: 0}、mode=full、wallSec ≤ 1200。
     （不显式传 --locales/--channels：既验证全量缺省语言集 en,zh，也随规则库
     渠道集走；若未来 golden spec 或渠道数变化导致包数 ≠48，本门如实 FAIL——
     48 是 T2.5 冻结的验收口径。首检 FAIL 的格由 e2e_matrix 全量的抖动单重试
     策略用同一 qacore 重跑一次、以重跑为准——只吸收瞬态负载抖动，两跑皆 FAIL
     仍 FAIL；重跑计入其总墙钟，summary 逐格留痕。）
  5. 中性名扫描：入库树（git ls-files）路径与内容对 _vendor/neutral-words.txt
     词表大小写不敏感匹配零命中（同 gate_mainpath 门项 5；命中只报告不修改）。

耗时预期：门项 1-3 串行真实执行三套验收（约 4-5 分钟，含多轮 qacore 自动试玩
与一次 pfcore make 全流水线），门项 4 全量 48 包约 6-12 分钟（质检并行度 4，
含可能的首检 FAIL 格单重试，见门项 4 注），总计约 12-18 分钟；全部产物落在
.gitignore 覆盖的 artifacts/，本门不写任何入库文件。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Windows 控制台默认非 UTF-8 代码页，先固定本进程输出编码（同 gate_* 系列做法）。
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# ------------------------------------------------------------------ 路径定位
REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"

# 复用 gate_mainpath 的门禁框架（Gate/SubChecks/run_script/中性名扫描）。
# 同目录 import：gate_mainpath 顶层只有定义与编码固定，无副作用执行。
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
import gate_mainpath as gm  # noqa: E402

GATE_PHASE0 = SCRIPTS_DIR / "gate_phase0.py"
GATE_PHASE1 = SCRIPTS_DIR / "gate_phase1.py"
GATE_MAINPATH = SCRIPTS_DIR / "gate_mainpath.py"
E2E_MATRIX = SCRIPTS_DIR / "e2e_matrix.py"
MATRIX_SUMMARY = REPO_ROOT / "artifacts" / "matrix" / "summary.json"

# 门项 4 口径（任务 T2.5 冻结）：4 模板 × {en,zh} × 6 渠道 = 48 包，预算 20 分钟。
E2E_EXPECT_PASS = 48
E2E_BUDGET_SEC = 1200.0

# 子门超时：三门各含多轮 qacore 自动试玩；e2e 全量预算 1200s + 余量。
SUBGATE_TIMEOUT_SEC = 2400
E2E_TIMEOUT_SEC = 1800

TOTAL_ITEMS = 5


# ------------------------------------------------------------------ 门项 1-3：三门回归
def check_gate(gate: "gm.Gate", idx: int, script: Path, name: str) -> None:
    """门回归：真实执行子门脚本，退出码必须为 0（同 gate_mainpath.check_subgate）。"""
    label = f"{idx}/{TOTAL_ITEMS} 门回归：{name} exit 0"
    if not script.is_file():
        gate.item(label, False, [f"脚本不存在：{script}"])
        return
    try:
        rc, out, elapsed = gm.run_script(script, SUBGATE_TIMEOUT_SEC)
    except subprocess.TimeoutExpired as exc:
        gate.item(label, False, [f"子门超时（>{exc.timeout:.0f}s）"])
        return
    except Exception as exc:  # 子进程启动失败等
        gate.item(label, False, [f"子进程异常：{exc!r}"])
        return
    details = [f"exit={rc}（应 0），墙钟 {elapsed:.1f}s"] + gm.gate_banner_lines(out)
    if rc != 0:
        details += ["", "—— 子门输出尾部 ——"] + out[-12:]
    gate.item(label, rc == 0, details)


# ------------------------------------------------------------------ 门项 4：全量矩阵
def check_e2e_full(gate: "gm.Gate", idx: int) -> None:
    """全量 48 包 0 fail 且 ≤1200s：跑 e2e_matrix（全量缺省），再对账 summary.json。"""
    label = (f"{idx}/{TOTAL_ITEMS} 全量矩阵：e2e_matrix {E2E_EXPECT_PASS} 包 0 fail"
             f"（预算 ≤{E2E_BUDGET_SEC:.0f}s）")
    sub = gm.SubChecks()

    if not E2E_MATRIX.is_file():
        gate.item(label, False, [f"脚本不存在：{E2E_MATRIX}"])
        return
    # 不传 --locales/--channels/--jobs：验证全量缺省（golden×{en,zh}×规则库冻结渠道，
    # 质检并行度随 e2e_matrix 缺省）。--budget-sec 1200 让 e2e_matrix 自身把
    # 20 分钟预算当硬门（超即 exit 1）。CHK09 阈值（golden 冻结 qc.maxLoadSec=2.0s）
    # 在本机与外部任务并行时偶发负载抖动（实测 2026-09-29：48 包两次全量跑分别
    # 2/6 格 load 2.2-4.5ms 超阈值而同格 pf.readyMs <1.5s，降并行无法消除），由
    # e2e_matrix 全量的抖动单重试策略吸收（同链重跑一次、两跑皆 FAIL 仍 FAIL）。
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, str(E2E_MATRIX), "--budget-sec", str(int(E2E_BUDGET_SEC))],
            cwd=str(REPO_ROOT), capture_output=True, timeout=E2E_TIMEOUT_SEC, env=env,
        )
    except subprocess.TimeoutExpired as exc:
        gate.item(label, False, [f"e2e 全量超时（>{exc.timeout:.0f}s，预算 {E2E_BUDGET_SEC:.0f}s）"])
        return
    except Exception as exc:
        gate.item(label, False, [f"子进程异常：{exc!r}"])
        return
    wall = time.monotonic() - t0
    out = [ln for ln in (proc.stdout.decode("utf-8", "replace")
                         + proc.stderr.decode("utf-8", "replace")).splitlines() if ln.strip()]
    rc = proc.returncode

    ok = rc == 0
    sub.check(True, f"e2e_matrix 全量 exit={rc}（应 0），本门侧墙钟 {wall:.1f}s")
    if rc != 0:
        sub.lines += ["", "—— e2e 输出尾部 ——"] + out[-12:]

    # 双重对账：summary.json 的 totals/wallSec/mode（质检是唯一裁判，看数字不看口号）。
    summary: dict = {}
    if MATRIX_SUMMARY.is_file():
        try:
            summary = json.loads(MATRIX_SUMMARY.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            sub.check(False, f"summary.json 不可读：{exc}")
            ok = False
    else:
        sub.check(False, f"summary.json 未落盘：{MATRIX_SUMMARY}")
        ok = False

    if summary:
        totals = summary.get("totals") or {}
        n_pass, n_fail, n_skip = totals.get("pass"), totals.get("fail"), totals.get("skip")
        grid_ok = (n_pass == E2E_EXPECT_PASS and n_fail == 0 and n_skip == 0)
        sub.check(grid_ok,
                  f"summary totals：pass={n_pass}/fail={n_fail}/skip={n_skip}"
                  f"（期望 {E2E_EXPECT_PASS}/0/0 = 4 模板×{{en,zh}}×6 渠道）")
        ok = ok and grid_ok
        wall_sec = summary.get("wallSec")
        budget_ok = isinstance(wall_sec, (int, float)) and 0 < wall_sec <= E2E_BUDGET_SEC
        sub.check(budget_ok,
                  f"summary wallSec={wall_sec}s ≤ {E2E_BUDGET_SEC:.0f}s 预算"
                  + ("" if budget_ok else "（超预算）"))
        ok = ok and budget_ok
        mode_ok = summary.get("mode") == "full"
        sub.check(mode_ok, f"summary mode={summary.get('mode')!r}（应 full）")
        ok = ok and mode_ok
        pf_fails = [f"{c.get('spec')}×{c.get('locale')}×{c.get('channel')}"
                    for c in (summary.get("cells") or [])
                    if isinstance(c, dict) and c.get("status") == "fail"]
        if pf_fails:
            sub.lines.extend(f"      fail 格：{x}" for x in pf_fails[:12])

    gate.item(label, ok, sub.lines)


# ------------------------------------------------------------------ 主流程
def main() -> int:
    t0 = time.monotonic()
    print("=" * 72)
    print("Phase 2 全量验收门（gate_phase2）：三门回归 + 48 包全量矩阵 + 中性名")
    print(f"仓库根     : {REPO_ROOT}")
    print(f"解释器     : {sys.executable}")
    print(f"启动时刻   : {time.strftime('%Y-%m-%dT%H:%M:%S')}")
    print("=" * 72)

    if not REPO_ROOT.is_dir() or not SCRIPTS_DIR.is_dir():
        print("[FAIL] 仓库结构异常：未找到 scripts/ 目录（脚本被挪动了？）")
        return 1

    gate = gm.Gate()
    check_gate(gate, 1, GATE_PHASE0, "gate_phase0")
    check_gate(gate, 2, GATE_PHASE1, "gate_phase1")
    check_gate(gate, 3, GATE_MAINPATH, "gate_mainpath")
    check_e2e_full(gate, 4)
    gm.check_neutral_names(gate, 5)  # 词表 _vendor/neutral-words.txt（不入库）
    elapsed = time.monotonic() - t0

    print("-" * 72)
    if gate.failures:
        print(f"GATE PHASE2: FAIL（{TOTAL_ITEMS - gate.failures}/{TOTAL_ITEMS} 项通过，"
              f"耗时 {elapsed:.1f}s）——全量矩阵未达验收线，先修复失败项。")
        return 1
    print(f"GATE PHASE2: PASS（{TOTAL_ITEMS}/{TOTAL_ITEMS} 项通过，耗时 {elapsed:.1f}s）"
          "——三门全绿 + 48 包全量矩阵 0 fail 且在预算内 + 中性名零命中。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
