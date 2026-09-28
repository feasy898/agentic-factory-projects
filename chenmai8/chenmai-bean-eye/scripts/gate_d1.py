#!/usr/bin/env python3
"""BeanEye D1 里程碑闸门（gate_d1）。

验收顺序对齐开发指令 §8：doctor → pytest(schemas) → oss_smoke 报告 → 数据集 README。
本脚本用**系统 Python** 运行（不要求已激活 venv、不限定 cwd），
内部自行定位仓库根，并统一改用项目 .venv 解释器执行子检查。

四项检查（任何一项 FAIL → 总退出码 1）：
  1) scripts/doctor.py 以 .venv python 运行且退出码 0
  2) .venv python -m pytest tests/test_schemas.py 全绿（退出码 0）
  3) out/oss_smoke_report.json 存在，且 aruco / qrcode 两项 ok=true
     （数据集本体允许 BLOCKED——硬项只有 aruco/qrcode，见 oss_smoke.py 的 hard_items）
  4) data/datasets/README.md 存在且含数据集"解锁步骤"

用法（Git Bash / cmd / PowerShell 均可，任意 cwd）：
    python D:/workspace/澄迈8项目/咖啡豆质检/repo/scripts/gate_d1.py

输出：逐项 `[PASS]`/`[FAIL]` + 详情，结尾 `GATE D1: PASS/FAIL`。
退出码：全过 = 0；任一 FAIL = 1；前置缺失（.venv 不存在）同样逐项判 FAIL。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# 闸门自身输出统一 UTF-8（Windows 控制台/重定向默认 GBK 会乱码）
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
SMOKE_REPORT = ROOT / "out" / "oss_smoke_report.json"
DATASETS_README = ROOT / "data" / "datasets" / "README.md"

# oss_smoke_report.json 中必须 ok 的两个硬项（与 oss_smoke.py 的 hard_items 对应）
SMOKE_HARD_ITEMS = ("aruco", "qrcode")

# data/datasets/README.md 中必须出现的"解锁步骤"关键词（数据集本体允许 BLOCKED）
README_UNLOCK_KEYWORDS = ("解锁",)

SUBPROC_TIMEOUT_S = 600


def _child_env() -> dict[str, str]:
    """子进程环境：强制 PYTHONUTF8=1（Windows 下默认跟随 GBK 代码页）。"""
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    return env


def _run_in_venv(args: list[str]) -> subprocess.CompletedProcess[str]:
    """在仓库根用 .venv python 执行 args，捕获输出（UTF-8 解码）。"""
    return subprocess.run(
        [str(VENV_PY), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_child_env(),
        timeout=SUBPROC_TIMEOUT_S,
    )


def _tail(text: str, n_lines: int = 6) -> str:
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return "\n".join(lines[-n_lines:]) if lines else "(无输出)"


def check_venv() -> tuple[bool, str]:
    """前置检查：.venv 解释器存在可用。失败时后续 1)/2) 直接判 FAIL。"""
    if not VENV_PY.is_file():
        return False, f"未找到 .venv 解释器: {VENV_PY}（先运行 scripts/setup_env.ps1）"
    return True, str(VENV_PY)


def check_doctor() -> tuple[bool, str]:
    """检查 ① doctor.py 退出码 0。"""
    try:
        proc = _run_in_venv(["scripts/doctor.py"])
    except subprocess.TimeoutExpired:
        return False, f"doctor.py 超时（>{SUBPROC_TIMEOUT_S}s）"
    ok = proc.returncode == 0
    detail = _tail(proc.stdout + proc.stderr)
    return ok, f"exit={proc.returncode}\n{detail}"


def check_pytest_schemas() -> tuple[bool, str]:
    """检查 ② pytest tests/test_schemas.py 全绿。"""
    try:
        proc = _run_in_venv(["-m", "pytest", "tests/test_schemas.py", "-q"])
    except subprocess.TimeoutExpired:
        return False, f"pytest 超时（>{SUBPROC_TIMEOUT_S}s）"
    ok = proc.returncode == 0
    detail = _tail(proc.stdout + proc.stderr, n_lines=4)
    return ok, f"exit={proc.returncode}\n{detail}"


def check_oss_smoke_report() -> tuple[bool, str]:
    """检查 ③ oss_smoke 报告存在且 aruco/qrcode 两硬项 ok。"""
    if not SMOKE_REPORT.is_file():
        return False, f"报告不存在: {SMOKE_REPORT}（先运行 scripts/oss_smoke.py）"
    try:
        report = json.loads(SMOKE_REPORT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"报告无法解析: {exc.__class__.__name__}: {exc}"

    items = {it.get("item"): it for it in report.get("items", []) if isinstance(it, dict)}
    missing = [name for name in SMOKE_HARD_ITEMS if name not in items]
    if missing:
        return False, f"报告缺少硬项条目: {missing}（现有: {sorted(items)}）"
    not_ok = [name for name in SMOKE_HARD_ITEMS if not items[name].get("ok")]
    if not_ok:
        bad = "; ".join(f"{n}: {items[n].get('error', '(无 error 字段)')}" for n in not_ok)
        return False, f"硬项未通过: {bad}"
    top_detail = report.get("detail", {}) if isinstance(report.get("detail", {}), dict) else {}
    parts = [
        f"{name}: ok ({top_detail.get(name, items[name].get('detail', '') or '')})"
        for name in SMOKE_HARD_ITEMS
    ]
    return True, "; ".join(parts)


def check_datasets_readme() -> tuple[bool, str]:
    """检查 ④ data/datasets/README.md 存在且含解锁步骤（数据集本体允许 BLOCKED）。"""
    if not DATASETS_README.is_file():
        return False, f"文件不存在: {DATASETS_README}"
    try:
        text = DATASETS_README.read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"文件无法读取: {exc}"
    missing = [kw for kw in README_UNLOCK_KEYWORDS if kw not in text]
    if missing:
        return False, f"缺少解锁步骤关键词: {missing}"
    n_unlock = text.count("解锁")
    return True, f"存在且含解锁步骤（\"解锁\"×{n_unlock} 处）；数据集本体允许 BLOCKED，不在此检查"


def main() -> int:
    print("== BeanEye D1 闸门（gate_d1）==")
    print(f"仓库根: {ROOT}")

    venv_ok, venv_detail = check_venv()
    results: list[tuple[str, bool, str]] = []

    if venv_ok:
        results.append(("① doctor.py exit 0", *check_doctor()))
        results.append(("② pytest tests/test_schemas.py 全绿", *check_pytest_schemas()))
    else:
        results.append(("① doctor.py exit 0", False, f"跳过：{venv_detail}"))
        results.append(("② pytest tests/test_schemas.py 全绿", False, f"跳过：{venv_detail}"))
    results.append(("③ oss_smoke 报告 aruco/QR ok", *check_oss_smoke_report()))
    results.append(("④ 数据集 README 解锁步骤", *check_datasets_readme()))

    failed = 0
    for name, ok, detail in results:
        mark = "[PASS]" if ok else "[FAIL]"
        print(f"{mark} {name}: {detail}")
        if not ok:
            failed += 1

    print("----------------------------")
    if failed == 0:
        print("GATE D1: PASS (4/4)")
        return 0
    print(f"GATE D1: FAIL ({failed}/4 项未通过)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
