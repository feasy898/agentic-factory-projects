#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B4 批次门禁（gate_b4）—— M10/M15/e2e 收口（口型分流 / 指标体系 / 端到端冒烟）。

用法（系统 Python，任意 cwd 均可运行；内部自动定位仓库根并使用 .venv 的解释器）：
    python D:/workspace/澄迈8项目/短剧多国出海/repo/scripts/gate_b4.py
    python D:/workspace/澄迈8项目/短剧多国出海/repo/scripts/gate_b4.py --skip-gpu

检查项（逐项打印 [PASS]/[FAIL]，任何 FAIL 退出码 1；SKIP-GPU 不计 FAIL 但输出注明）：
  ① pytest tests/ 全绿且零跳过（全量套件：M10/M15 验收用例与 B0–B3 存量全部用例
    同一门，含 C1–C8 契约回归 tests/test_contracts.py、tests/test_b1_contract.py）
    ——延续 B0 纪律：出现 skipped 即 FAIL。唯一豁免：显式 --skip-gpu 且被牵连的
    GPU 服务确认不可达时，"服务不可达"类跳过可豁免并在输出注明（逐条归因在
    gate_b2 口径 tts/9002、asr_align/9001 上增补 lip/9003——B4 新依赖；归因不了
    的跳过不豁免——三条隧道可能只断一条，不能以另一条的不可达代偿）；
  ② M10 eval：pytest tests/test_m10_lipsync.py（§4 M10 冻结线：C6 分流纯逻辑
    ——正脸近景镜头表硬门槛 + face.frontal/closeup/!overlap + 台词最长前 10% 与
    --pro-shots 升 lip-pro、执行降级链落到 lip-fast；回贴合成位精确性——零替换
    输出逐帧字节等同源、窗外改动/窗内漏替换两类缺陷可检出；服务真跑——4s 正脸
    近景样本非口型帧字节级不变 + 口型窗帧全异 + 嘴区变化达标；CLI 真实子进程
    exit 0。:9003 服务不可达时服务组整组 skip，--skip-gpu 豁免口径同 ①（含
    :9003 归因）；服务可达但主力引擎未装载属真实故障，不提供跳过口径）；
  ③ M15 eval：pytest tests/test_m15_metrics.py（T21 定案：六指标"出数与口径
    正确"即过，数值不做阈值门禁、如实报告——离线 15 条 + 在线组（SAPI zh 声库
    + :9002 真配音 + :9001 真回判）六项全出数 exit 0；在线组任一前置不可达整组
    skip，--skip-gpu 豁免口径同 ①）；
  ④ e2e 至少单语全过：子进程 bash scripts/e2e_smoke.sh --langs en（T22 交付物，
    退出码即判定；"至少单语"= 门禁取单语最小收敛面）：合成素材（SAPI zh 对白
    + 硬字幕 + 公版人像）→ M1→M3→M4(:9001)→M2→M5→音色库→逐语种[M6(mock)→M8→
    M7(:9002)→M11→M9→显式标识→M10(:9003)→封元数据→M15] → tests/check_e2e.py
    断言集（成片时长 ±5% / 字幕带重跑 OCR 中文命中=0 且目标语在位 / AI 标识
    元数据精确一致 + 片头 3s 墨迹在位且片尾消失 / metrics 六项出数 / 非口型帧
    不变 / 配音轨句窗铺满）。:9001/:9002 不可达时脚本自身 FAIL（配音与识别是
    e2e 的被测对象，不伪造结果）——--skip-gpu 且被牵连服务确认不可达时本项记
    SKIP-GPU；:9003 不可达时脚本内 SKIP-LIP 继续链路（成片=12_out 成片，断言集
    自动切换容差口径），PASS 明细注明 SKIP-LIP；
  ⑤ gate_b3 回归：**等价覆盖口径**（gate_b2 对 gate_b1 的同一先例：被回归门
    整门墙钟超本门单项帽时不整门重跑，显式复跑其独有 eval 面防回归）——B3 独有
    新增面 = tests/test_m8.py + tests/test_m9.py + tests/test_m11.py 三件一次
    子进程复跑；B3 其余检查面与本门的覆盖映射：B3①全量套件→本门①（同一套件）；
    B3⑤gate_b2 整门→其面拆解为 全量套件（本门①）+ M5/M6/M7 eval 与 :9002
    冒烟（同在套件内）+ 契约回归（本门①）+ 中性名（本门⑥），全部同源等价；
    B3⑥中性名→本门⑥。整门重跑不可行的实测依据：gate_b3 自验收整门 3469s
    （其 docstring 构成记录：⑤gate_b2 整门重跑 1661s + ①全量套件 1221s + 其余
    各项），超单项帽 1800s 近一倍、也必然耗尽整门剩余预算——如实注明，不放松
    判定口径；
  ⑥ 中性名扫描：直接复用 gate_b0 同一实现（台账附录A 强校验 + 公开文件零命中）。

超时预算（T13 定案，单项 1800s / 整门 3600s）：每项子进程超时取
min(本项帽, 整门剩余预算)，整门预算耗尽后剩余项直接判 FAIL 并注明。唯一例外：
① 全量套件的项帽取 b0.PYTEST_TIMEOUT_S=3600s（gate_b0/gate_b1 先例——套件
实测墙钟超 1800s 后，1800s 帽会误杀全绿套件；B4 首跑实测复现：208 用例
1847s（2026-09-30 探针）撞 1800s 帽被杀，其余五项全过），仍受整门剩余约束。

构成（2026-09-30 自验收，三跑如实记录：run1 ① 全量套件在 1800s 旧项帽处被杀
（208 passed 探针实测 1847s）→ 套件帽改 b0 的 3600s；run2 与另一项目门禁
（90 分钟）共享负载窗口，①1919+②140+③135+④704 耗尽 3600s 致 ⑤ 被剩余帽
精确卡死（5/6）；run3 对方门禁收口后的空窗整门 6/6，墙钟 3104s/3600s）：
①=1553s（208 passed）> ⑤=704s（m8/m9/m11 合计 51 passed）> ④=539s（exit=0，
单语 en）> ③=155s（16 passed）> ②=151s（15 passed）> ⑥≈2s——主项合计
3104s（占整门预算 86%；共享负载高峰实测可把 ①③④ 抬 ~20-30%（run2），
后续项可能因预算耗尽判 FAIL，如实注明，不放松判定口径）。

环境注记（随输出尾部如实打印）：
  1) ①②③④ 均含真模型推理（M2/M11 OCR、M3 分离、M5 声纹为 CPU 真模型；全量
     套件实测 724~1932s 随共享负载浮动）——B4 全门墙钟可达 55 分钟量级，外部
     复核方超时帽需自配 ≥60 分钟；
  2) ①②③④ 依赖三条 ssh 隧道：127.0.0.1:9001（asr_align）、127.0.0.1:9002
     （tts）、127.0.0.1:9003（lip，B4 新增）；公网链路周期性 reset，
     ops/tunnel_gpu.sh 的 keepalive 子命令秒级自愈；--skip-gpu 豁免仅覆盖
     "服务不可达"类跳过；
  3) ④ 依赖 Git Bash（bash/curl）与 ffmpeg/ffprobe 在 PATH（gate_b0 的
     _pytest_env 同源修复后传入子进程）及本机 SAPI zh 声库（素材合成）；
  4) 显存互斥（configs/models.yaml 部署矩阵）：lip-fast 常驻物理 cuda:1 与
     :9002 备选合成引擎同卡互斥；本门只走常驻服务，不触发备选引擎懒加载。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import gate_b0 as b0  # noqa: E402 —— ⑥/venv 定位/环境修复与其单一来源，禁止复制 token 表
import gate_b1 as b1  # noqa: E402 —— ①④ 跳过归因中 :9001 探测同源复用
import gate_b2 as b2  # noqa: E402 —— ①④ 跳过归因中 :9002 探测/豁免标记同源复用

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: T13 定案（不用 600s）：单项子进程超时 1800s；整门预算 3600s——每项实际超时
#: 取 min(单项帽, 整门剩余)，预算耗尽后剩余项直接 FAIL。
PER_ITEM_TIMEOUT_S = 1800
GATE_BUDGET_S = 3600

#: ② ③ ⑤ 的 pytest 节点（⑤ = gate_b3 独有新增面一次子进程复跑，见模块 docstring ⑤）
M10_TEST_FILE = "tests/test_m10_lipsync.py"
M15_TEST_FILE = "tests/test_m15_metrics.py"
B3_EVAL_FILES = ["tests/test_m8.py", "tests/test_m9.py", "tests/test_m11.py"]

#: ④ e2e 冒烟脚本（T22 交付物；单语最小收敛面 --langs en）
E2E_SCRIPT = _SCRIPTS_DIR / "e2e_smoke.sh"

#: e2e 汇总行解析（"======== e2e_smoke 结束: exit=0（langs=en lip=on）========"）
E2E_SUMMARY_RE = re.compile(r"e2e_smoke 结束:\s*exit=(\d+)（langs=(\S+) lip=(\S+)）")

#: ④ bash 解析候选顺序（which 之后的回退）：PATH 首个 bash 可能是 WSL 入口
#: （System32\bash.exe，不认 D:/ 盘符路径），故对每个候选做一次"脚本可执行"
#: 功能实测（未知参数探针：脚本参数校验路径，rc=2 + 提示语，不做任何实际工作）；
#: 且必须以相对路径 + repo cwd 调用——仓库路径含非 ASCII 段，Windows 绝对路径
#: 作 argv 传 Git Bash 实测会 "No such file or directory"（2026-09-30 实测）。
_BASH_CANDIDATES = (
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files\Git\usr\bin\bash.exe",
    r"C:\Program Files (x86)\Git\bin\bash.exe",
)
_BASH_CACHE: dict = {"done": False, "bash": None, "detail": ""}

#: "服务不可达"类跳过的判定标记（单一来源 = gate_b2；tests/test_m3.py /
#: tests/test_m4.py / tests/test_m7_tts.py / tests/test_m10_lipsync.py /
#: tests/test_m15_metrics.py 的服务类 skip reason 均含该词组或归因词）
GPU_SKIP_MARK = b2.GPU_SKIP_MARK

TUNNEL_HINT = ("修复: TUNNEL_LOCAL_PORT=<port> TUNNEL_REMOTE_PORT=<port> "
               "bash ops/tunnel_gpu.sh start（:9001/:9002/:9003 幂等；keepalive "
               "子命令秒级自愈）；或本门禁加 --skip-gpu")

ENV_NOTES = [
    "环境注记1: ①②③④ 含真模型推理(OCR/分离/声纹 CPU 真模型，全量套件 208 用例实测 1548~1920s 随共享负载)，整门墙钟预算 3600s（实测 3104~3600s），外部超时帽需自配 >=60min",
    "环境注记2: ①②③④ 依赖 ssh 隧道 127.0.0.1:9001(asr_align)/9002(tts)/9003(lip)，公网链路周期性 reset，ops/tunnel_gpu.sh keepalive 秒级自愈；--skip-gpu 豁免仅覆盖'服务不可达'类跳过",
    "环境注记3: ④ 依赖 Git Bash(bash/curl)+ffmpeg 在 PATH 与本机 SAPI zh 声库；:9003 不可达时 e2e 内部 SKIP-LIP 继续（成片=12_out，断言集容差口径）",
    "环境注记4: 显存互斥(models.yaml 部署矩阵): lip-fast 常驻 cuda:1 与 :9002 备选引擎同卡互斥；本门只走常驻服务，不触发备选引擎懒加载",
]

_T0 = time.monotonic()


class Args:
    skip_gpu: bool = False


ARGS = Args()

# ---------------------------------------------------------------------------
# :9003 lip 服务状态（B4 新依赖；门禁内缓存，只探测一次。:9001 复用 gate_b1
# service_state、:9002 复用 gate_b2 tts_service_state——单一来源不复制）
# ---------------------------------------------------------------------------

#: 经 .venv 解释器执行的 :9003 探测桥（pipeline.m10_lipsync 依赖 httpx）。
#: 输出一行 JSON：reachable=False（连接失败）或 reachable=True + 装载详情。
_PROBE_LIP_CODE = """\
import sys, json
sys.path.insert(0, sys.argv[1])
from pipeline.m10_lipsync import LipClient
try:
    c = LipClient("http://127.0.0.1:9003", timeout=15.0, retries=0)
    h = c.health()
except Exception as exc:
    print(json.dumps({"reachable": False, "error": str(exc)[:300]}, ensure_ascii=False))
    raise SystemExit(0)
loaded = h.get("loaded") or {}
problems = []
if not loaded.get("lip-fast"):
    problems.append("主力引擎 lip-fast 未装载")
print(json.dumps({"reachable": True, "ok": not problems, "problems": problems,
                  "base_url": c.base_url, "physical": h.get("physical_device"),
                  "engine": h.get("engine")}, ensure_ascii=False))
"""

_LIP_CACHE: dict = {"done": False, "state": "unreachable", "detail": ""}


def lip_service_state() -> tuple[str, str]:
    """GPU lip 服务状态 → ("up"|"unreachable"|"unhealthy", 摘要)。

    "up" = 可达且 lip-fast 主力已装载；"unreachable" = 连接失败（隧道未启动/
    远端下线，属 --skip-gpu 可跳过情形）；"unhealthy" = 可达但引擎未就绪（真实
    故障，不可跳过）。结果缓存，一次门禁只探测一次。
    """
    if _LIP_CACHE["done"]:
        return _LIP_CACHE["state"], _LIP_CACHE["detail"]
    state, detail = "unreachable", ""
    payload: dict = {}
    try:
        vpy = b0.venv_python()
        if vpy is None:
            raise RuntimeError("未找到 .venv 解释器")
        r = subprocess.run([str(vpy), "-c", _PROBE_LIP_CODE, str(ROOT)],
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
            detail = (f"{payload.get('base_url')} lip-fast 主力已装载 "
                      f"({payload.get('physical')}; engine={payload.get('engine')})")
        else:
            state = "unhealthy"
            detail = (f"{payload.get('base_url')} 可达但: "
                      f"{'; '.join(payload.get('problems') or [])}")
    if not detail:
        detail = "未知探测结果"
    _LIP_CACHE.update(done=True, state=state, detail=detail)
    return state, detail


# ---------------------------------------------------------------------------
# pytest 运行器（①②③⑤ 共用；结构沿用 gate_b3 的 T13 预算语义——每项子进程帽
# = min(1800s, 整门剩余)，时钟为本门 _T0。跳过归因在 gate_b2 口径上增补 :9003）
# ---------------------------------------------------------------------------


def _item_timeout(cap_s: int = PER_ITEM_TIMEOUT_S) -> int:
    """本项子进程超时 = min(本项帽, 整门剩余预算)。

    默认帽 = T13 定案单项帽 1800s；唯一例外是 ① 全量套件取 b0.PYTEST_TIMEOUT_S
    = 3600s（gate_b0/gate_b1 先例：套件实测墙钟超 1800s 后，1800s 帽会误杀全绿
    套件——B4 首跑实测复现：208 用例 1847s 撞帽 FAIL），仍受整门预算约束。
    """
    remaining = GATE_BUDGET_S - (time.monotonic() - _T0)
    return max(0, min(cap_s, int(remaining)))


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
    """--skip-gpu 豁免：显式开关 + 全部跳过均为'服务不可达'类 + 逐条归因到对应
    GPU 服务并确认该服务探测为不可达（lip/9003 → 本门 lip_service_state、
    tts/9002 → gate_b2.tts_service_state、asr_align/9001 → gate_b1.service_state；
    归因不了的跳过不豁免——三条隧道可能只断一条，不能以另一条的不可达代偿）。"""
    if not (ARGS.skip_gpu and skipped and all(GPU_SKIP_MARK in ln for ln in skipped)):
        return False
    for ln in skipped:
        if "lip" in ln or "9003" in ln:
            if lip_service_state()[0] != "unreachable":
                return False
        elif "tts" in ln or "9002" in ln:
            if b2.tts_service_state()[0] != "unreachable":
                return False
        elif "asr_align" in ln or "9001" in ln:
            if b1.service_state()[0] != "unreachable":
                return False
        else:
            return False
    return True


def _pytest_item(nodes: list[str], cap_s: int = PER_ITEM_TIMEOUT_S) -> tuple[bool, str]:
    timeout_s = _item_timeout(cap_s)
    if timeout_s <= 0:
        return False, (f"整门预算耗尽（>{GATE_BUDGET_S}s），本项未执行: {' '.join(nodes)}")
    try:
        rc, tail, skipped, env_note = _pytest_run(nodes, timeout_s)
    except RuntimeError as exc:
        return False, str(exc)
    except subprocess.TimeoutExpired:
        return False, (f"pytest 超时（>{timeout_s}s，本项帽 {cap_s}s/"
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
    # ① 套件帽 = b0.PYTEST_TIMEOUT_S（3600s，gate_b0/gate_b1 先例），仍受整门剩余约束
    return _pytest_item(["tests/"], cap_s=b0.PYTEST_TIMEOUT_S)


def check_m10() -> tuple[bool, str]:
    return _pytest_item([M10_TEST_FILE])


def check_m15() -> tuple[bool, str]:
    return _pytest_item([M15_TEST_FILE])


def check_b3_regression() -> tuple[bool, str]:
    """⑤ gate_b3 回归 = 等价覆盖（详见模块 docstring ⑤：整门重跑实测 3469s，
    超单项帽 1800s 近一倍，gate_b2 对 gate_b1 同一先例改显式复跑独有 eval 面）。"""
    return _pytest_item(B3_EVAL_FILES)


def _find_bash() -> tuple[str | None, str]:
    """定位能以「相对路径 + repo cwd」形态运行 e2e 脚本的 bash（结果缓存）。

    判定 = 功能实测：`bash scripts/e2e_smoke.sh --probe-only` 必须命中脚本自身
    的参数校验出口（rc=2 + "未知参数"提示）——这同时验证了 ①可执行、②脚本路径
    解析、③非 ASCII cwd 下的相对定位，排除 WSL bash（不认 Windows 盘符 cwd）。
    """
    if _BASH_CACHE["done"]:
        return _BASH_CACHE["bash"], _BASH_CACHE["detail"]
    cands: list[str] = []
    w = shutil.which("bash")
    if w:
        cands.append(w)
    cands.extend(p for p in _BASH_CANDIDATES if p not in cands)
    tried: list[str] = []
    for b in cands:
        if not b or not Path(b).is_file():
            continue
        tried.append(b)
        try:
            r = subprocess.run([b, "scripts/e2e_smoke.sh", "--probe-only"],
                               cwd=str(ROOT), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=60)
        except Exception:  # noqa: BLE001 —— 该候选不可用，试下一个
            continue
        if r.returncode == 2 and "未知参数" in (r.stdout or ""):
            _BASH_CACHE.update(done=True, bash=b,
                               detail=f"bash={b}（探针实测：脚本相对路径可解析）")
            return _BASH_CACHE["bash"], _BASH_CACHE["detail"]
    detail = ("未找到可运行 scripts/e2e_smoke.sh 的 Git Bash（实测候选: "
              + "; ".join(tried or ["<无>"]) + "；④ 需 Git Bash——WSL bash 不认 "
              "Windows 盘符 cwd，不适用）")
    _BASH_CACHE.update(done=True, bash=None, detail=detail)
    return None, detail


# ---------------------------------------------------------------------------
# ④ e2e 至少单语全过（子进程 bash scripts/e2e_smoke.sh --langs en）
# ---------------------------------------------------------------------------


def check_e2e() -> tuple[bool | None, str]:
    """④ e2e 至少单语全过 = scripts/e2e_smoke.sh --langs en 退出码 0。

    返回 (True PASS | None SKIP-GPU | False FAIL, 明细)。:9001/:9002 是 e2e 的
    被测对象，不可达时脚本自身 FAIL 不伪造结果——仅 --skip-gpu 且被牵连服务确认
    不可达时记 SKIP-GPU；:9003 不可达不阻塞（脚本内 SKIP-LIP 继续，明细注明）。
    """
    asr_state = b1.service_state()[0]
    tts_state = b2.tts_service_state()[0]
    if "unreachable" in (asr_state, tts_state):
        msg = (f"e2e 必需服务不可达（asr_align={asr_state}, tts={tts_state}）；"
               f"{TUNNEL_HINT}")
        if ARGS.skip_gpu:
            return None, "[--skip-gpu] 已跳过本项（输出注明）—— " + msg
        return False, msg
    timeout_s = _item_timeout()
    if timeout_s <= 0:
        return False, (f"整门预算耗尽（>{GATE_BUDGET_S}s），本项未执行: "
                       f"e2e_smoke --langs en（{E2E_SCRIPT.name}）")
    if not E2E_SCRIPT.is_file():
        return False, f"e2e 脚本不存在: {E2E_SCRIPT}"
    bash, bash_detail = _find_bash()
    if bash is None:
        return False, bash_detail
    env, env_note = b0._pytest_env()
    if env is None:
        return False, env_note
    lip_note = ("；SKIP-LIP（:9003 不可达，m10 仅出空计划，成片=12_out 成片，"
                "断言集容差口径）") if lip_service_state()[0] == "unreachable" else ""
    try:
        r = subprocess.run([bash, "scripts/e2e_smoke.sh", "--langs", "en"],
                           cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=timeout_s, env=env)
    except subprocess.TimeoutExpired:
        return False, (f"e2e 子进程超时（>{timeout_s}s，单项帽 {PER_ITEM_TIMEOUT_S}s/"
                       f"整门 {GATE_BUDGET_S}s 取小）")
    out = r.stdout or ""
    lines = [ln for ln in out.splitlines() if ln.strip()]
    tail = " | ".join(lines[-2:])[:400] if lines else (r.stderr or "").strip()[-400:]
    m = E2E_SUMMARY_RE.search(out)
    if r.returncode != 0:
        return False, (f"e2e_smoke 退出码 {r.returncode}（日志: tmp/e2e_smoke.log）: "
                       f"{m.group(0) if m else tail}")
    if m is None:
        return False, f"e2e_smoke 退出码 0 但汇总行缺失/不可解析: {tail}"
    if m.group(1) != "0":
        return False, f"e2e_smoke 汇总行 exit={m.group(1)} 非零（进程退出码却为 0，口径异常）"
    return True, f"[{env_note}]{lip_note} e2e 单语 en: {m.group(0)}（T22 定案口径）"


# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="B4 批次门禁（M10/M15/e2e 收口）")
    parser.add_argument("--skip-gpu", action="store_true",
                        help="GPU 服务不可达时豁免 ①②③ 中'服务不可达'类跳过并跳过"
                             "第④项（输出注明；归因不到的服务跳过仍 FAIL）")
    ns = parser.parse_args()
    ARGS.skip_gpu = ns.skip_gpu

    checks = [
        ("① pytest tests/ 全绿且零跳过（全量套件=M10/M15 与 B0–B3 存量同一门，契约回归在内）",
         check_suite),
        ("② M10 eval（pytest tests/test_m10_lipsync.py：C6 分流/回贴精确性/服务真跑，:9003）",
         check_m10),
        ("③ M15 eval（pytest tests/test_m15_metrics.py：六指标出数与口径，数值如实）",
         check_m15),
        ("④ e2e 至少单语全过（bash scripts/e2e_smoke.sh --langs en，退出码即判定）",
         check_e2e),
        ("⑤ gate_b3 回归（等价覆盖：B3 独有 eval 面 m8/m9/m11 显式复跑；映射见 docstring）",
         check_b3_regression),
        ("⑥ 中性名扫描（gate_b0 同源：台账附录A 强校验 + 公开文件零命中）",
         b0.check_neutral_names),
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
        print("注: --skip-gpu 生效，存在 SKIP-GPU 项（GPU 服务不可达）；"
              "修复后建议重跑全量门禁复核。")
    print(f"== gate_b4: {n_pass}/{len(checks)} PASS, {n_skip} SKIP-GPU, {n_fail} FAIL "
          f"(墙钟 {time.monotonic() - _T0:.0f}s / 整门预算 {GATE_BUDGET_S}s) ==")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
