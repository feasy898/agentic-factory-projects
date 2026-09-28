#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B2 批次门禁（gate_b2）—— M5/M6/M7 收口（镜头切分+说话人+正脸近景 / 上下文翻译 mock / tts 客户端）。

用法（系统 Python，任意 cwd 均可运行；内部自动定位仓库根并使用 .venv 的解释器）：
    python D:/workspace/澄迈8项目/短剧多国出海/repo/scripts/gate_b2.py
    python D:/workspace/澄迈8项目/短剧多国出海/repo/scripts/gate_b2.py --skip-gpu

检查项（逐项打印 [PASS]/[FAIL]，任何 FAIL 退出码 1；SKIP-GPU 不计 FAIL 但输出注明）：
  ① pytest tests/ 全绿且零跳过（全量套件：B2 新增 tests/test_m5.py / tests/test_m6.py /
    tests/test_m7_tts.py 与 B1 存量全部用例同一门，含 C1–C8 契约回归
    tests/test_contracts.py、tests/test_b1_contract.py）——延续 B0 纪律：出现
    skipped 即 FAIL。唯一豁免：显式 --skip-gpu 且被牵连的 GPU 服务确认不可达时，
    "服务不可达"类跳过可豁免并在输出注明（其余任何原因的跳过一律不过）；
  ② M5 eval：pytest tests/test_m5.py（§4 M5 冻结线：diar 一致率 ≥0.85（时长加权
    最优映射）/镜头切分召回 ≥0.8（±0.4s）/正脸近景逐镜标注一致/C2 回填 + lip
    资格规则/voicebank CLI）；
  ③ M6 eval（mock 后端全离线）：pytest tests/test_m6.py（角色卡注入/预算窗=C2
    时间窗/in-budget-first 排序/术语命中/C4 TranslationTable 契约 + 复合键 upsert；
    local/api 后端的服务连通性冒烟不在本项口径——:9004 mt 服务未部署不阻塞本门）；
  ④ M7 客户端 :9002 冒烟：pytest tests/test_m7_tts.py（离线 4 条：C 出口纯函数/
    静音拒收/参数校验/桩服务 payload 契约；在线 7 条经隧道：health 路由冻结镜像/
    双参考合成+时长对账/voice-only/三语种 dry_run 路由链/未知引擎 400）——
    隧道断/服务下线（探测连接失败）时 --skip-gpu 记 SKIP-GPU 并在汇总行注明；
    服务可达但主力引擎未装载属真实故障，不提供跳过口径。
    修复: TUNNEL_LOCAL_PORT=9002 TUNNEL_REMOTE_PORT=9002 bash ops/tunnel_gpu.sh start
    （幂等；keepalive 子命令秒级自愈）；
  ⑤ gate_b1 契约回归：pytest tests/test_contracts.py + tests/test_b1_contract.py
    显式复跑（B1 冻结：C1–C8 schema/utt_id 公式/字级时间窗/upsert 原子写/diar
    段级 schema）。两文件已含于 ① 的全量套件，此处显式钉住防回归；gate_b1 整门
    （M1–M3 eval 复跑 + :9001 冒烟，单门实测墙钟 >1800s）不在本门整门预算内整门
    重跑——其检查面由 ①（同一套件）+ ⑤（契约）+ ⑥（中性名）等价覆盖；
  ⑥ 中性名扫描：直接复用 gate_b0 同一实现（台账附录A 强校验 + 公开文件零命中）。

超时预算（T13 定案，不用 600s）：单项 1800s；整门 3600s——每项子进程超时取
min(1800, 整门剩余预算)，整门预算耗尽后剩余项直接判 FAIL 并注明。

环境注记（随输出尾部如实打印）：
  1) ①② 含真模型 CPU 推理（分离/镜头切分/声纹嵌入，全量套件实测 724~1932s 随
     共享负载浮动）——外部复核方超时帽需自配 ≥60 分钟（整门 3600s）；
  2) ①④ 依赖两条 ssh 隧道：127.0.0.1:9001（asr_align，M3/M4 服务用例）与
     127.0.0.1:9002（tts，M7 在线用例）；公网链路周期性 reset，ops/tunnel_gpu.sh
     的 keepalive 子命令秒级自愈；--skip-gpu 豁免仅覆盖"服务不可达"类跳过；
  3) 显存互斥（configs/models.yaml 部署矩阵）：lip-pro 起来时 alt-tts-b 必须退出；
     本门禁只走 dub-tts 主力常驻（cuda:0），不触发备选引擎懒加载。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import gate_b0 as b0  # noqa: E402  —— ⑥/环境修复与其单一来源，禁止复制 token 表
import gate_b1 as b1  # noqa: E402  —— ⑤ 回归对象 + :9001 服务探测同源复用

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: T13 定案（不用 600s）：单项子进程超时 1800s；整门预算 3600s——每项实际超时
#: 取 min(单项帽, 整门剩余)，预算耗尽后剩余项直接 FAIL。
PER_ITEM_TIMEOUT_S = 1800
GATE_BUDGET_S = 3600

#: "服务不可达"类跳过的判定标记（tests/test_m3.py / tests/test_m4.py /
#: tests/test_m7_tts.py 的 skip reason 均含该词组；其余原因的跳过不在豁免范围）
GPU_SKIP_MARK = "服务不可达"

TUNNEL_TTS_HINT = ("修复: TUNNEL_LOCAL_PORT=9002 TUNNEL_REMOTE_PORT=9002 "
                   "bash ops/tunnel_gpu.sh start（幂等；keepalive 子命令秒级自愈）；"
                   "或本门禁加 --skip-gpu 跳过第④项")

ENV_NOTES = [
    "环境注记1: ①② 含真模型 CPU 推理(全量套件实测 724~1932s 随负载)，整门墙钟预算 3600s，外部超时帽需自配 >=60min",
    "环境注记2: ①④ 依赖 ssh 隧道 127.0.0.1:9001(asr_align) 与 127.0.0.1:9002(tts)，公网链路周期性 reset；--skip-gpu 豁免仅覆盖'服务不可达'类跳过",
    "环境注记3: 显存互斥(models.yaml 部署矩阵): lip-pro 起来时 alt-tts-b 必须退出；本门只走 dub-tts 主力常驻，不触发备选引擎懒加载",
]

_T0 = time.monotonic()


class Args:
    skip_gpu: bool = False


ARGS = Args()

# ---------------------------------------------------------------------------
# :9002 tts 服务状态（门禁内缓存，只探测一次；:9001 asr_align 探测复用 gate_b1）
# ---------------------------------------------------------------------------

#: 经 .venv 解释器执行的 :9002 探测桥（pipeline.tts_client 依赖 httpx）。
#: 输出一行 JSON：reachable=False（连接失败）或 reachable=True + ok/装载详情。
_PROBE_TTS_CODE = """\
import sys, json
sys.path.insert(0, sys.argv[1])
from pipeline.tts_client import TtsClient
try:
    c = TtsClient("http://127.0.0.1:9002", timeout=15.0, retries=0)
    h = c.health()
except Exception as exc:
    print(json.dumps({"reachable": False, "error": str(exc)[:300]}, ensure_ascii=False))
    raise SystemExit(0)
loaded = h.get("loaded") or {}
problems = []
if not loaded.get("dub-tts"):
    problems.append("主力引擎 dub-tts 未装载")
if h.get("cuda_available") is not True:
    problems.append("cuda_available 非 true")
print(json.dumps({"reachable": True, "ok": not problems, "problems": problems,
                  "base_url": c.base_url, "torch": h.get("torch"),
                  "gpu": h.get("gpu"), "loaded": loaded}, ensure_ascii=False))
"""

_TTS_CACHE: dict = {"done": False, "state": "unreachable", "detail": ""}


def tts_service_state() -> tuple[str, str]:
    """GPU tts 服务状态 → ("up"|"unreachable"|"unhealthy", 摘要)。

    "up" = 可达且 dub-tts 主力已装载且 cuda_available；"unreachable" = 连接失败
    （隧道未启动/远端下线，属 --skip-gpu 可跳过情形）；"unhealthy" = 可达但
    引擎未就绪（真实故障，不可跳过）。结果缓存，一次门禁只探测一次。
    """
    if _TTS_CACHE["done"]:
        return _TTS_CACHE["state"], _TTS_CACHE["detail"]
    state, detail = "unreachable", ""
    payload: dict = {}
    try:
        vpy = b0.venv_python()
        if vpy is None:
            raise RuntimeError("未找到 .venv 解释器")
        r = subprocess.run([str(vpy), "-c", _PROBE_TTS_CODE, str(ROOT)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=b1.SERVICE_PROBE_TIMEOUT_S)
        lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
        payload = json.loads(lines[-1]) if lines else {}
    except Exception as exc:  # noqa: BLE001 —— 桥执行失败 = 探测不到，等同不可达
        detail = f"探测桥执行失败: {exc}"
    else:
        if not payload.get("reachable"):
            detail = f"payload: {payload.get('error') or '连接失败'}"
        elif payload.get("ok"):
            state = "up"
            detail = (f"{payload.get('base_url')} dub-tts 主力已装载 "
                      f"({payload.get('torch')}; loaded={payload.get('loaded')})")
        else:
            state = "unhealthy"
            detail = (f"{payload.get('base_url')} 可达但: "
                      f"{'; '.join(payload.get('problems') or [])}")
    if not detail:
        detail = "未知探测结果"
    _TTS_CACHE.update(done=True, state=state, detail=detail)
    return state, detail


# ---------------------------------------------------------------------------
# pytest 运行器（①②③⑤ 共用；结构沿用 gate_b1，超时预算与双服务豁免为 B2 口径）
# ---------------------------------------------------------------------------


def _item_timeout() -> int:
    """本项子进程超时 = min(单项帽 1800s, 整门剩余预算 3600s)。"""
    remaining = GATE_BUDGET_S - (time.monotonic() - _T0)
    return max(0, min(PER_ITEM_TIMEOUT_S, int(remaining)))


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
    """--skip-gpu 豁免条件：显式开关 + 全部跳过均为'服务不可达'类 + 逐条归因到
    对应 GPU 服务并确认该服务探测为不可达（:9002 归 tts、:9001 归 asr_align；
    归因不了的跳过不豁免——两条隧道可能只断一条，不能以另一条的不可达代偿）。"""
    if not (ARGS.skip_gpu and skipped and all(GPU_SKIP_MARK in ln for ln in skipped)):
        return False
    for ln in skipped:
        if "tts" in ln or "9002" in ln:
            if tts_service_state()[0] != "unreachable":
                return False
        elif "asr_align" in ln or "9001" in ln:
            if b1.service_state()[0] != "unreachable":
                return False
        else:
            return False
    return True


def _pytest_item(nodes: list[str]) -> tuple[bool, str]:
    timeout_s = _item_timeout()
    if timeout_s <= 0:
        return False, (f"整门预算耗尽（>{GATE_BUDGET_S}s），本项未执行: {' '.join(nodes)}")
    try:
        rc, tail, skipped, env_note = _pytest_run(nodes, timeout_s)
    except RuntimeError as exc:
        return False, str(exc)
    except subprocess.TimeoutExpired:
        return False, (f"pytest 超时（>{timeout_s}s，单项帽 {PER_ITEM_TIMEOUT_S}s/"
                       f"整门 {GATE_BUDGET_S}s 取小）: {' '.join(nodes)}")
    if rc != 0:
        return False, f"pytest 退出码 {rc}: {tail}"
    if not skipped:
        return True, f"[{env_note}] {tail}"
    if _gpu_relief_ok(skipped):
        return True, (f"GPU 依赖 {len(skipped)} 条 SKIPPED 摘要豁免（--skip-gpu 且被牵连"
                      f"服务确认不可达，全部为'{GPU_SKIP_MARK}'类）: {skipped[0][:220]}")
    return False, ("pytest 输出含 skipped（B0 纪律：跳过不算过；GPU 服务不可达时可加 "
                   f"--skip-gpu 豁免'{GPU_SKIP_MARK}'类）: {' | '.join(skipped)[:320]}")


def check_suite() -> tuple[bool, str]:
    return _pytest_item(["tests/"])


def check_m5() -> tuple[bool, str]:
    return _pytest_item(["tests/test_m5.py"])


def check_m6() -> tuple[bool, str]:
    return _pytest_item(["tests/test_m6.py"])


def check_b1_regression() -> tuple[bool, str]:
    return _pytest_item(["tests/test_contracts.py", "tests/test_b1_contract.py"])


# ---------------------------------------------------------------------------
# ④ M7 客户端 :9002 连通冒烟
# ---------------------------------------------------------------------------


def check_m7_service() -> tuple[bool | None, str]:
    """M7 客户端（pipeline.tts_client）对 :9002 的冒烟 = tests/test_m7_tts.py 全绿。

    返回 (True PASS | None SKIP-GPU | False FAIL, 明细)；服务可达但主力引擎未装载
    是真实故障，不提供跳过口径。
    """
    state, detail = tts_service_state()
    if state == "up":
        return _pytest_item(["tests/test_m7_tts.py"])
    if state == "unreachable":
        msg = f"GPU tts 服务不可达（探测: {detail}）；{TUNNEL_TTS_HINT}"
        if ARGS.skip_gpu:
            return None, "[--skip-gpu] 已跳过本项（输出注明）—— " + msg
        return False, msg
    return False, f"服务可达但主力引擎未装载（不属 --skip-gpu 可跳过情形）: {detail}"


# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="B2 批次门禁（M5/M6/M7 收口）")
    parser.add_argument("--skip-gpu", action="store_true",
                        help="GPU 服务不可达时跳过第④项（输出注明；① 中被牵连服务的"
                             "'服务不可达'类跳过同步豁免，其余跳过仍 FAIL）")
    ns = parser.parse_args()
    ARGS.skip_gpu = ns.skip_gpu

    checks = [
        ("① pytest tests/ 全绿且零跳过（全量套件，含 B2 m5/m6/m7 与 B1 契约回归）", check_suite),
        ("② M5 eval（pytest tests/test_m5.py：diar/切分/正脸近景/C2 回填）", check_m5),
        ("③ M6 eval（pytest tests/test_m6.py，mock 后端全离线）", check_m6),
        ("④ M7 客户端 :9002 冒烟（pytest tests/test_m7_tts.py，经隧道在线+离线）", check_m7_service),
        ("⑤ gate_b1 契约回归（pytest tests/test_contracts.py + tests/test_b1_contract.py）",
         check_b1_regression),
        ("⑥ 中性名扫描（gate_b0 同源：台账附录A 强校验 + 公开文件零命中）", b0.check_neutral_names),
    ]
    n_fail = n_skip = 0
    for title, fn in checks:
        t_item = time.monotonic()
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
        print(f"       （本项耗时 {time.monotonic() - t_item:.0f}s，"
              f"整门剩余预算 {GATE_BUDGET_S - (time.monotonic() - _T0):.0f}s）")
        for ln in str(detail).splitlines():
            print(f"       {ln}")
    n_pass = len(checks) - n_fail - n_skip
    for note in ENV_NOTES:
        print(note)
    if n_skip:
        print("注: --skip-gpu 生效，第④项未执行（服务不可达）；修复后建议重跑全量门禁复核。")
    print(f"== gate_b2: {n_pass}/{len(checks)} PASS, {n_skip} SKIP-GPU, {n_fail} FAIL "
          f"(墙钟 {time.monotonic() - _T0:.0f}s / 整门预算 {GATE_BUDGET_S}s) ==")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
