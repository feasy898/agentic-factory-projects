#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B1 批次门禁（gate_b1）—— 模块 eval 收口（M1 预处理 / M2 硬字幕 OCR / M3 分离 / M4 服务连通）。

用法（系统 Python，任意 cwd 均可运行；内部自动定位仓库根并使用 .venv 的解释器）：
    python D:/workspace/澄迈8项目/短剧多国出海/repo/scripts/gate_b1.py
    python D:/workspace/澄迈8项目/短剧多国出海/repo/scripts/gate_b1.py --skip-gpu

检查项（逐项打印 [PASS]/[FAIL]，任何 FAIL 退出码 1；SKIP-GPU 不计 FAIL 但输出注明）：
  ① pytest tests/ 全绿且零跳过（含 C1–C8 契约回归：tests/test_contracts.py、
    tests/test_b1_contract.py）——延续 B0 纪律：出现 skipped 即 FAIL。
    唯一豁免：显式 --skip-gpu 且 GPU 服务确认不可达时，"服务不可达"类跳过
    可豁免并在输出注明（其余任何原因的跳过一律不过）；
  ② M1 预处理 eval：pytest tests/test_m1.py（§4 M1 冻结入口 test_ingest 在内：
    输出存在 + ffprobe 分辨率/fps/采样率断言 + 时长差 ≤0.2s）；
  ③ M2 硬字幕 OCR eval：pytest tests/test_m2.py（冻结线：语料级 CER ≤5%、
    字幕起止时间误差 ≤0.3s 且 ≥90% 命中；与 scripts/eval_m2.sh 同口径）；
  ④ M3 人声/背景分离 eval：pytest tests/test_m3.py（冻结线：输出时长=输入、
    RMS 判据、60s 素材 CPU 预算——含真模型 CPU 推理，全门禁最慢项）；
  ⑤ M4 客户端对 :9001 连通冒烟：经 pipeline.gpu_client（M4 同款客户端）请求
    /health，断言 asr-core/align-core/emo-tag 三模型 loaded 且 cuda_available；
    隧道不在时给出 ops/tunnel_gpu.sh 修复提示；--skip-gpu 记 SKIP-GPU 并在
    汇总行注明（服务可达但模型未就绪属真实故障，不属可跳过情形）；
  ⑥ 中性名扫描：直接复用 gate_b0 同一实现（内部台账附录A 强校验 + 公开文件
    零命中），token 表单一来源，避免两处分叉漂移。

环境注记（随输出尾部如实打印）：
  1) 全量套件与第④项均含真模型 CPU 推理（单次 724~1932s 随共享负载浮动），
     本门禁全程墙钟可达 45 分钟量级——外部复核方超时帽需自配 ≥45 分钟；
  2) GPU 服务经 ssh 隧道（ops/tunnel_gpu.sh）访问，公网链路周期性 reset；
     --skip-gpu 豁免仅覆盖"服务不可达"类跳过，其余跳过仍判 FAIL。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import gate_b0 as b0  # noqa: E402  —— ⑥/环境修复/超时基线与其单一来源，禁止复制 token 表

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: 各 pytest 项超时：①=全量套件（与 gate_b0 同值）；④ 含真模型 CPU 推理，
#: 其自身冻结预算一项即可达 1800s，给足 3600s；②③ 按模块规模给余量。
PYTEST_TIMEOUT_S = {"suite": b0.PYTEST_TIMEOUT_S, "m1": 900, "m2": 1800, "m3": 3600}

#: "服务不可达"类跳过的判定标记（tests/test_m3.py / tests/test_m4.py 的 skip
#: reason 均含该词组；其余原因的跳过不在豁免范围）
GPU_SKIP_MARK = "服务不可达"

#: ⑤ 服务探测桥的超时（首连若撞上隧道半开，15s HTTP 超时 + 进程余量）
SERVICE_PROBE_TIMEOUT_S = 60

TUNNEL_HINT = ("修复: bash ops/tunnel_gpu.sh start"
               "（ssh -L 127.0.0.1:9001 → GPU 机 asr_align :9001，幂等可重跑）；"
               "或本门禁加 --skip-gpu 跳过第⑤项")

ENV_NOTES = [
    "环境注记1: ①④ 均含真模型 CPU 推理(单次 724~1932s 随负载)，本门禁全程墙钟可达 45 分钟量级，外部超时帽需自配 >=45min",
    "环境注记2: GPU 服务经 ssh 隧道访问，公网链路周期性 reset；--skip-gpu 豁免仅覆盖'服务不可达'类跳过，其余跳过仍判 FAIL",
]

# ---------------------------------------------------------------------------
# 参数与 GPU 服务状态（门禁内缓存，只探测一次）
# ---------------------------------------------------------------------------


class Args:
    skip_gpu: bool = False


ARGS = Args()

_SERVICE_CACHE: dict = {"done": False, "state": "unreachable", "detail": ""}

#: 经 .venv 解释器执行的探测桥（pipeline.gpu_client 依赖 httpx，系统解释器不保证有）。
#: 输出一行 JSON：reachable=False（连接失败）或 reachable=True + ok/missing/装载详情。
_PROBE_CODE = """\
import sys, json
sys.path.insert(0, sys.argv[1])
from pipeline.gpu_client import GpuClient
try:
    c = GpuClient(timeout=15.0, retries=0)
    h = c.health()
except Exception as exc:
    print(json.dumps({"reachable": False, "error": str(exc)[:300]}, ensure_ascii=False))
    raise SystemExit(0)
loaded = h.get("loaded") or {}
problems = [k for k in ("asr-core", "align-core", "emo-tag") if not loaded.get(k)]
if h.get("cuda_available") is not True:
    problems.append("cuda_available 非 true")
print(json.dumps({"reachable": True, "ok": not problems, "problems": problems,
                  "base_url": c.base_url, "torch": h.get("torch"),
                  "gpu": h.get("gpu"), "loaded": loaded}, ensure_ascii=False))
"""


def service_state(refresh: bool = False) -> tuple[str, str]:
    """GPU asr_align 服务状态 → ("up"|"unreachable"|"unhealthy", 摘要)。

    "up" = 可达且三模型 loaded 且 cuda_available；"unreachable" = 连接失败
    （隧道未启动/远端下线，属 --skip-gpu 可跳过情形）；"unhealthy" = 可达但
    模型未就绪（真实故障，不可跳过）。结果缓存，一次门禁只探测一次。
    """
    if _SERVICE_CACHE["done"] and not refresh:
        return _SERVICE_CACHE["state"], _SERVICE_CACHE["detail"]
    state, detail = "unreachable", ""
    try:
        vpy = b0.venv_python()
        if vpy is None:
            raise RuntimeError("未找到 .venv 解释器")
        r = subprocess.run([str(vpy), "-c", _PROBE_CODE, str(ROOT)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=SERVICE_PROBE_TIMEOUT_S)
        lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
        payload = json.loads(lines[-1]) if lines else {}
    except Exception as exc:  # noqa: BLE001 —— 桥执行失败 = 探测不到，等同不可达
        detail = f"探测桥执行失败: {exc}"
    else:
        if not payload.get("reachable"):
            detail = f"payload: {payload.get('error') or '连接失败'}"
        elif payload.get("ok"):
            state = "up"
            detail = (f"{payload.get('base_url')} 三模型 loaded 全就绪 "
                      f"({payload.get('torch')} / {payload.get('gpu')})")
        else:
            state = "unhealthy"
            detail = (f"{payload.get('base_url')} 可达但: "
                      f"{'; '.join(payload.get('problems') or [])}")
    if not detail:
        detail = "未知探测结果"
    _SERVICE_CACHE.update(done=True, state=state, detail=detail)
    return state, detail


# ---------------------------------------------------------------------------
# pytest 运行器（①–④ 共用）
# ---------------------------------------------------------------------------


def _pytest_run(nodes: list[str], timeout_s: int) -> tuple[int, str, list[str], str]:
    """跑 pytest（-q -rs）→ (退出码, 结果尾行, SKIPPED 摘要行, 环境说明)。"""
    vpy = b0.venv_python()
    if vpy is None:
        raise RuntimeError("未找到 .venv 解释器（.venv/Scripts/python.exe 或 .venv/bin/python）")
    env, env_note = b0._pytest_env()
    if env is None:
        raise RuntimeError(env_note)
    r = subprocess.run([str(vpy), "-m", "pytest", *nodes, "-q", "-rs"],
                       cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       timeout=timeout_s, env=env)
    out = r.stdout or ""
    lines = [ln for ln in out.splitlines() if ln.strip()]
    tail = " | ".join(lines[-2:])[:400] if lines else (r.stderr or "").strip()[:400]
    skipped = [ln.strip() for ln in lines if ln.strip().startswith("SKIPPED")]
    return r.returncode, tail, skipped, env_note


def _gpu_relief_ok(skipped: list[str]) -> bool:
    """--skip-gpu 豁免条件：显式开关 + 服务确认不可达 + 全部跳过均为'服务不可达'类。"""
    return (ARGS.skip_gpu
            and service_state()[0] == "unreachable"
            and bool(skipped)
            and all(GPU_SKIP_MARK in ln for ln in skipped))


def _pytest_item(nodes: list[str], timeout_s: int) -> tuple[bool, str]:
    try:
        rc, tail, skipped, env_note = _pytest_run(nodes, timeout_s)
    except RuntimeError as exc:
        return False, str(exc)
    except subprocess.TimeoutExpired:
        return False, f"pytest 超时（>{timeout_s}s）: {' '.join(nodes)}"
    if rc != 0:
        return False, f"pytest 退出码 {rc}: {tail}"
    if not skipped:
        return True, f"[{env_note}] {tail}"
    if _gpu_relief_ok(skipped):
        return True, (f"GPU 依赖 {len(skipped)} 条 SKIPPED 摘要豁免（--skip-gpu 且服务不可达，"
                      f"全部为'{GPU_SKIP_MARK}'类）: {skipped[0][:220]}")
    return False, ("pytest 输出含 skipped（B0 纪律：跳过不算过；GPU 服务不可达时可加 "
                   f"--skip-gpu 豁免'{GPU_SKIP_MARK}'类）: {' | '.join(skipped)[:320]}")


def check_suite() -> tuple[bool, str]:
    return _pytest_item(["tests/"], PYTEST_TIMEOUT_S["suite"])


def check_m1() -> tuple[bool, str]:
    return _pytest_item(["tests/test_m1.py"], PYTEST_TIMEOUT_S["m1"])


def check_m2() -> tuple[bool, str]:
    return _pytest_item(["tests/test_m2.py"], PYTEST_TIMEOUT_S["m2"])


def check_m3() -> tuple[bool, str]:
    return _pytest_item(["tests/test_m3.py"], PYTEST_TIMEOUT_S["m3"])


# ---------------------------------------------------------------------------
# ⑤ M4 客户端连通冒烟
# ---------------------------------------------------------------------------


def check_m4_service() -> tuple[bool | None, str]:
    """M4 客户端（pipeline.gpu_client）对 :9001 的连通冒烟。

    返回 (True PASS | None SKIP-GPU | False FAIL, 明细)；服务可达但模型未就绪
    是真实故障，不提供跳过口径。
    """
    state, detail = service_state()
    if state == "up":
        return True, f"M4 客户端 /health 连通冒烟通过: {detail}"
    if state == "unreachable":
        msg = f"GPU asr_align 服务不可达（探测: {detail}）；{TUNNEL_HINT}"
        if ARGS.skip_gpu:
            return None, "[--skip-gpu] 已跳过本项（输出注明）—— " + msg
        return False, msg
    return False, f"服务可达但模型未就绪（不属 --skip-gpu 可跳过情形）: {detail}"


# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="B1 批次门禁（模块 eval 收口）")
    parser.add_argument("--skip-gpu", action="store_true",
                        help="GPU 服务不可达时跳过第⑤项（输出注明；①–④ 中仅'服务不可达'"
                             "类跳过同步豁免，其余跳过仍 FAIL）")
    ns = parser.parse_args()
    ARGS.skip_gpu = ns.skip_gpu

    checks = [
        ("① pytest tests/ 全绿且零跳过（含契约回归 test_contracts/test_b1_contract）", check_suite),
        ("② M1 预处理 eval（pytest tests/test_m1.py，含 §4 冻结入口 test_ingest）", check_m1),
        ("③ M2 硬字幕 OCR eval（pytest tests/test_m2.py，冻结线 CER≤5%/时间误差≤0.3s）", check_m2),
        ("④ M3 人声/背景分离 eval（pytest tests/test_m3.py，含真模型 CPU 推理）", check_m3),
        ("⑤ M4 客户端 :9001 连通冒烟（pipeline.gpu_client /health）", check_m4_service),
        ("⑥ 中性名扫描（gate_b0 同源：台账附录A 强校验 + 公开文件零命中）", b0.check_neutral_names),
    ]
    n_fail = n_skip = 0
    for title, fn in checks:
        try:
            ok, detail = fn()
        except Exception as exc:  # noqa: BLE001 —— 检查本身抛错 = 该项 FAIL
            ok, detail = False, f"检查执行异常: {exc}"
        if ok is None:
            n_skip += 1
            print(f"[SKIP-GPU] {title}")
        else:
            if not ok:
                n_fail += 1
            print(f"[{'PASS' if ok else 'FAIL'}] {title}")
        for ln in str(detail).splitlines():
            print(f"       {ln}")
    n_pass = len(checks) - n_fail - n_skip
    for note in ENV_NOTES:
        print(note)
    if n_skip:
        print(f"注: --skip-gpu 生效，第⑤项未执行（服务不可达）；修复后建议重跑全量门禁复核。")
    print(f"== gate_b1: {n_pass}/{len(checks)} PASS, {n_skip} SKIP-GPU, {n_fail} FAIL ==")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
