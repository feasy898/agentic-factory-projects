#!/usr/bin/env python3
"""G1 门禁（Gate G1）：一键复验 M1/M2 里程碑全部无硬件验收项。

用法（系统 Python、任意工作目录均可）::

    python scripts/gate_g1.py

门禁项（任一 FAIL → exit 1）：
  1. 中性命名扫描（chengshao/scripts/check_naming.py）零命中；
  2. pytest tests/ 全量用例全绿；
  3. 模块 eval 入口逐个执行：cs_sim / cs_mouth / cs_voice 的 eval，
     加 cs_food 接口测试（tests/test_food_interface.py），全部 exit 0；
  4. cs_dashboard 冒烟：后台起服务 → httpx 探活（/api/health 与首页均 200）→ 关闭。

实现约定：
  - 本脚本自身只需系统 Python（纯标准库），内部定位仓库根并统一改用
    ``.venv`` 解释器执行全部检查；所有子进程置 ``PYTHONUTF8=1``。
  - 各模块 eval 在包根 ``chengshao/`` 下执行（与各 eval 文档用法一致），
    证据 JSON 由 eval 自身落 ``chengshao/reports/``；本门禁另落
    ``chengshao/reports/gate_g1.json`` 汇总（字段遵循开发指令 §10.2）。
  - 冒烟服务使用随机空闲端口与临时数据库，不触碰 ``data/care.db``。
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG_ROOT = REPO_ROOT / "chengshao"
GATE_REPORT = PKG_ROOT / "reports" / "gate_g1.json"

STEP_TIMEOUT_S = 1800          # 单个门禁项硬超时（eval 含模型加载，给足余量）
SERVICE_READY_TIMEOUT_S = 60   # 冒烟服务就绪等待上限
TAIL_LINES = 15                # PASS 时回显的输出尾部行数
FAIL_TAIL_LINES = 60           # FAIL 时回显的输出尾部行数

HTTP_PROBE_SRC = """\
import sys
import httpx

base = sys.argv[1]
with httpx.Client(timeout=5.0) as client:
    health = client.get(base + "/api/health")
    page = client.get(base + "/")
print(f"health={health.status_code} page={page.status_code}")
sys.exit(0 if health.status_code == 200 and page.status_code == 200 else 1)
"""


# ---------------------------------------------------------------------------
# 基础设施
# ---------------------------------------------------------------------------
def _venv_python() -> Path:
    """定位仓库根下的 .venv 解释器（Windows/Linux 布局都认）。"""
    candidates = [
        REPO_ROOT / ".venv" / "Scripts" / "python.exe",
        REPO_ROOT / ".venv" / "bin" / "python",
    ]
    for cand in candidates:
        if cand.is_file():
            return cand
    found = ", ".join(str(c) for c in candidates)
    raise SystemExit(f"[FAIL] 未找到 .venv 解释器（期望其一）：{found}")


def _child_env(pkg_root_on_path: bool = False) -> dict:
    """子进程环境：强制 UTF-8；可选把包根加进 PYTHONPATH 保证 -m 可解析。"""
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env.setdefault("PYTHONIOENCODING", "utf-8")
    if pkg_root_on_path:
        existing = env.get("PYTHONPATH", "")
        parts = [str(PKG_ROOT)] + [p for p in existing.split(os.pathsep) if p]
        env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def _fmt_cmd(argv: list[str], cwd: Path) -> str:
    return f"cwd={cwd}  $ {' '.join(argv)}"


def _run_checked(argv: list[str], cwd: Path, timeout: float = STEP_TIMEOUT_S,
                 pkg_root_on_path: bool = False) -> tuple[int, float, str]:
    """执行一条检查命令，返回 (exit_code, 耗时秒, 合并输出)。"""
    env = _child_env(pkg_root_on_path=pkg_root_on_path)
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            argv, cwd=str(cwd), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
        out = proc.stdout or ""
        code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") + (exc.stderr or "")
        out += f"\n[gate] 超时（>{timeout:.0f}s），已终止"
        code = 124
    return code, time.perf_counter() - started, out


def _print_tail(out: str, lines: int) -> None:
    tail = [ln for ln in out.splitlines()]
    for ln in tail[-lines:]:
        print(f"    | {ln}")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# ---------------------------------------------------------------------------
# 门禁项
# ---------------------------------------------------------------------------
def gate_naming(venv: Path) -> tuple[bool, str, str]:
    """① 中性命名扫描零命中。"""
    argv = [str(venv), str(PKG_ROOT / "scripts" / "check_naming.py")]
    code, secs, out = _run_checked(argv, REPO_ROOT)
    label = "check_naming 中性名扫描（零命中）"
    return code == 0, label, _fmt_cmd(argv, REPO_ROOT) + f"  [exit={code}, {secs:.1f}s]\n{out}"


def gate_pytest_full(venv: Path) -> tuple[bool, str, str]:
    """② pytest tests/ 全量全绿。"""
    argv = [str(venv), "-m", "pytest", "tests/", "-q"]
    code, secs, out = _run_checked(argv, REPO_ROOT)
    label = "pytest tests/ 全量用例"
    return code == 0, label, _fmt_cmd(argv, REPO_ROOT) + f"  [exit={code}, {secs:.1f}s]\n{out}"


def _gate_module_eval(venv: Path, label: str, args: list[str],
                      cwd: Path) -> tuple[bool, str, str]:
    """执行单个模块 eval/接口测试入口，返回 (是否通过, 名称, 明细)。"""
    argv = [str(venv), *args]
    code, secs, out = _run_checked(argv, cwd, pkg_root_on_path=True)
    detail = _fmt_cmd(argv, cwd) + f"  [exit={code}, {secs:.1f}s]\n{out}"
    return code == 0, label, detail


def gate_module_evals_plan(venv: Path) -> list[tuple[str, object]]:
    """③ 逐模块 eval 入口 + cs_food 接口测试（惰性：返回待执行的 (名称, 闭包)）。"""
    plan: list[tuple[str, object]] = []
    module_evals = [
        ("③a cs_sim eval（FK/IK/可达空间/安全包络）",
         ["-m", "cs_sim.eval", "--model", "auto", "--report", "reports/sim_eval.json"],
         PKG_ROOT),
        ("③b cs_mouth eval（口部三维，mono 主路径）",
         ["-m", "cs_mouth.eval", "--input", "assets/face_samples",
          "--report", "reports/mouth_eval.json"],
         PKG_ROOT),
        ("③c cs_voice eval（离线语音链路 20 条）",
         ["-m", "cs_voice.eval", "--input", "assets/voice_samples",
          "--report", "reports/voice_eval.json"],
         PKG_ROOT),
        ("③d cs_food 接口测试（tests/test_food_interface.py）",
         ["-m", "pytest", "tests/test_food_interface.py", "-q"],
         REPO_ROOT),
    ]
    for label, args, cwd in module_evals:
        plan.append((label, lambda v=venv, lb=label, a=args, c=cwd:
                     _gate_module_eval(v, lb, a, c)))
    return plan


def gate_dashboard_smoke(venv: Path) -> tuple[bool, str, str]:
    """④ 看板冒烟：后台起服务 → httpx 探活 200 → 关闭。"""
    tmp_dir = Path(tempfile.mkdtemp(prefix="gate_g1_dash_"))
    db_path = tmp_dir / "smoke.db"
    log_path = tmp_dir / "service.log"
    port = _free_port()
    argv = [str(venv), "-m", "cs_dashboard",
            "--host", "127.0.0.1", "--port", str(port), "--db", str(db_path)]
    detail = _fmt_cmd(argv, PKG_ROOT)

    proc: subprocess.Popen | None = None
    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            proc = subprocess.Popen(
                argv, cwd=str(PKG_ROOT), env=_child_env(pkg_root_on_path=True),
                stdout=log_file, stderr=subprocess.STDOUT,
            )
            base = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + SERVICE_READY_TIMEOUT_S
            ok = False
            probe_out = ""
            while time.monotonic() < deadline:
                if proc.poll() is not None:  # 服务进程提前退出
                    break
                probe = subprocess.run(
                    [str(venv), "-c", HTTP_PROBE_SRC, base],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", timeout=15,
                )
                probe_out = probe.stdout or ""
                if probe.returncode == 0:
                    ok = True
                    break
                time.sleep(0.5)

            if ok:
                detail += f"\n[probe] {probe_out.strip()}  (就绪等待 ≤{SERVICE_READY_TIMEOUT_S}s)"
            else:
                detail += f"\n[probe] 未就绪/探活失败：{probe_out.strip()}"
                detail += "\n[service.log 尾部]"
                try:
                    detail += "\n" + log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
                except OSError:
                    pass
            return ok, "cs_dashboard 冒烟（起服务→httpx 200→关闭）", detail
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    print(f"=== G1 门禁开始  repo={REPO_ROOT} ===")
    try:
        venv = _venv_python()
    except SystemExit as exc:
        print(str(exc))
        return 1
    print(f"[INFO] 解释器：{venv}")

    steps: list[tuple[bool, str, str]] = []

    def _do(idx: int, total: int, runner, label: str) -> None:
        """执行单个门禁项并即时回显；步骤内异常按 FAIL 处理（门禁不崩溃）。"""
        print(f"---- 门禁项 {idx}/{total}：{label} ----")
        try:
            outcome = runner()
        except Exception as exc:  # noqa: BLE001
            outcome = (False, label, f"[gate] 步骤异常：{type(exc).__name__}: {exc}")
        passed, _, detail = outcome
        steps.append(outcome)
        mark = "[PASS]" if passed else "[FAIL]"
        print(f"{mark} {label}")
        if detail.strip():
            _print_tail(detail, TAIL_LINES if passed else FAIL_TAIL_LINES)

    py = venv
    _do(1, 6, lambda: gate_naming(py), "① 中性命名扫描零命中")
    _do(2, 6, lambda: gate_pytest_full(py), "② pytest tests/ 全量全绿")
    for offset, (label, runner) in enumerate(gate_module_evals_plan(py), start=3):
        _do(offset, 6, runner, label)
    _do(6, 6, lambda: gate_dashboard_smoke(py), "④ cs_dashboard 冒烟")

    n_fail = sum(1 for passed, _, _ in steps if not passed)
    step_records: list[dict] = [
        {"name": label, "detail": detail, "pass": bool(passed)}
        for passed, label, detail in steps
    ]
    overall = n_fail == 0
    report = {
        "module": "gate_g1",
        "date": date.today().isoformat(),
        "cmd": "python scripts/gate_g1.py（系统 Python，cwd 任意；内部改用 .venv 解释器）",
        "metrics": {
            "steps_total": len(steps),
            "steps_passed": len(steps) - n_fail,
            "steps_failed": n_fail,
            "steps": [{"name": r["name"], "pass": r["pass"]} for r in step_records],
        },
        "thresholds": {"all_steps_pass": True},
        "pass": overall,
        "step_details": step_records,
    }
    GATE_REPORT.parent.mkdir(parents=True, exist_ok=True)
    GATE_REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"=== G1 门禁结束：{'全部通过' if overall else f'{n_fail} 项失败'} ===")
    print(f"[INFO] 门禁汇总报告：{GATE_REPORT}")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
