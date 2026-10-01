#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B3 批次门禁（gate_b3）—— M8/M9/M11 收口（时长对齐 / 混音 / 字幕擦除+目标语渲染）。

用法（系统 Python，任意 cwd 均可运行；内部自动定位仓库根并使用 .venv 的解释器）：
    python D:/workspace/澄迈8项目/短剧多国出海/repo/scripts/gate_b3.py
    python D:/workspace/澄迈8项目/短剧多国出海/repo/scripts/gate_b3.py --skip-gpu

检查项（逐项打印 [PASS]/[FAIL]，任何 FAIL 退出码 1；SKIP-GPU 不计 FAIL 但输出注明）：
  ① pytest tests/ 全绿且零跳过（全量套件：B3 新增 tests/test_m11.py / tests/test_m8.py /
    tests/test_m9.py 与 B0–B2 存量全部用例同一门，含 C1–C8 契约回归
    tests/test_contracts.py、tests/test_b1_contract.py——B0 契约增补（服务响应
    时间零点/utt_id 稳定公式/原子 upsert 写盘原语）由其显式钉住）——延续 B0
    纪律：出现 skipped 即 FAIL。唯一豁免：显式 --skip-gpu 且被牵连的 GPU 服务
    确认不可达时，"服务不可达"类跳过可豁免并在输出注明（逐条归因复用 gate_b2
    同一实现：tts/9002 归 :9002、asr_align/9001 归 :9001，归因不了的跳过
    不豁免——两条隧道可能只断一条，不能以另一条的不可达代偿）；
  ② M11 eval：pytest tests/test_m11.py（§4 M11 冻结线：擦除后重跑 M2 OCR 中文
    命中=0（3 段素材各一遍）/ AI 标识区像素 diff=0（裁剪区哈希一致）/ ar 字幕
    RTL 方向与字母连接（libass+fribidi）/ 60s 素材擦除+渲染 CPU 耗时记录实测
    ——delogo 默认 + inpaint 备选双引擎各一遍 + CLI 真实子进程；全离线零 GPU）；
  ③ M8 eval：pytest tests/test_m8.py（§4 M8 冻结线：全片时长对齐率 ±10% 命中
    ≥70%（自研时长可控翻译训练前基线）/ atempo 使用占比 ≤30% / 平均语速调整
    幅度 ≤1.06（按 test_m8 口径注记：刻意超长语料上该线必然高于 1.06，故只
    复算不断言阈值）——mock 候选刻意超长（句窗按候选项估长 1.00/0.62/0.52/
    0.43 压窗）使 in-budget / df-bisect / switch-df / atempo-final /
    keep-original / no-translation / unresolved 七类路径全部真实触发，逐句
    核验落窗 + CLI exit 0 + C5 契约
    校验 + 多语种分文件与幂等；消费 C4 出口 C5，全离线零 GPU）；
  ④ M9 eval：pytest tests/test_m9.py（§4 M9 冻结线：时长差 ≤0.2s（mix/dubbed/
    成片 vs master）/ loudnorm 复测 I∈[-17,-15]（±1LU，对交付文件实测不只信
    报告）/ 人声段-bg 峰值比 ≥8dB（对白可懂度）——另覆盖 ducking 包络纯函数
    与交付文件频段对拍（关-ducking 对照混音）/ 成片 ASS + AI 隐式标识元数据位
    ffprobe 回读精确匹配 + M11 成品接入路径（-c:v copy）/ CLI 与兜底；
    全离线零 GPU）；
  ⑤ gate_b2 回归：子进程整门重跑 scripts/gate_b2.py（退出码即判定；其内部
    六项 = 全量套件 / M5 / M6 / M7 :9002 冒烟 / B1 契约回归 / 中性名，本项
    不拆条重复实现）。--skip-gpu 透传给子进程，与其自身豁免口径一致；子进程
    出现 SKIP-GPU 时本项记 SKIP-GPU（不计 FAIL，输出注明），退出码非 0 判 FAIL；
  ⑥ 中性名扫描：直接复用 gate_b0 同一实现（台账附录A 强校验 + 公开文件零命中）。

超时预算（T13 定案，单项 1800s / 整门 3600s）：每项子进程超时取
min(1800, 整门剩余预算)，整门预算耗尽后剩余项直接判 FAIL 并注明。
构成（2026-09-29 自验收实测，随共享负载浮动）：⑤=1661s（内含 gate_b2 重跑
全量套件）> ①=1221s（177 passed）> ②=498s > ④=71s > ③=4s——主项合计
3469s（占整门预算 96%，共享负载高峰时后续项可能因预算耗尽判 FAIL，如实
注明，不放松判定口径）。

环境注记（随输出尾部如实打印）：
  1) ①②⑤ 含真模型 CPU 推理（M3 分离 / M5 声纹 / M2+M11 OCR 重跑，全量套件
     实测 724~1932s 随负载浮动）——B3 全门墙钟可达 55 分钟量级，外部复核方
     超时帽需自配 ≥60 分钟；
  2) ①⑤ 依赖两条 ssh 隧道：127.0.0.1:9001（asr_align，M3/M4 服务用例）与
     127.0.0.1:9002（tts，M7 在线用例）；公网链路周期性 reset，ops/tunnel_gpu.sh
     的 keepalive 子命令秒级自愈；--skip-gpu 豁免仅覆盖"服务不可达"类跳过；
  3) M8/M9/M11 三模块 eval 全离线零 GPU（②③④ 无隧道依赖）；⑤ 中 gate_b2
     的 M7 冒烟随之整门重跑（B3 不重复实现），显存互斥（configs/models.yaml
     部署矩阵）同样只走 dub-tts 主力常驻，不触发备选引擎懒加载。
"""

from __future__ import annotations

import argparse
import re
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
import gate_b1 as b1  # noqa: E402 —— ① 跳过归因中 :9001 探测同源复用（gate_b2 内部调用）
import gate_b2 as b2  # noqa: E402 —— ⑤ 回归对象（脚本本体）+ 跳过归因/:9002 探测同源复用

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: T13 定案（不用 600s）：单项子进程超时 1800s；整门预算 3600s——每项实际超时
#: 取 min(单项帽, 整门剩余)，预算耗尽后剩余项直接 FAIL。
PER_ITEM_TIMEOUT_S = 1800
GATE_BUDGET_S = 3600

#: ⑤ 回归对象：B2 批次门禁脚本本体（子进程整门重跑，退出码即判定）
GATE_B2_SCRIPT = _SCRIPTS_DIR / "gate_b2.py"

#: gate_b2 汇总行解析（"== gate_b2: 6/6 PASS, 0 SKIP-GPU, 0 FAIL (墙钟 …) =="）
B2_SUMMARY_RE = re.compile(
    r"==\s*gate_b2:\s*(\d+)/(\d+)\s*PASS,\s*(\d+)\s*SKIP-GPU,\s*(\d+)\s*FAIL")

#: "服务不可达"类跳过的判定标记（单一来源 = gate_b2；tests/test_m3.py /
#: tests/test_m4.py / tests/test_m7_tts.py 的 skip reason 均含该词组）
GPU_SKIP_MARK = b2.GPU_SKIP_MARK

ENV_NOTES = [
    "环境注记1: ①②⑤ 含真模型 CPU 推理(M3 分离/M5 声纹/M2+M11 OCR 重跑，全量套件实测 724~1932s 随负载)，B3 全门墙钟可达 55 分钟量级，外部超时帽需自配 >=60min",
    "环境注记2: ①⑤ 依赖 ssh 隧道 127.0.0.1:9001(asr_align) 与 127.0.0.1:9002(tts)，公网链路周期性 reset，ops/tunnel_gpu.sh keepalive 秒级自愈；--skip-gpu 豁免仅覆盖'服务不可达'类跳过",
    "环境注记3: M8/M9/M11 三模块 eval 全离线零 GPU(②③④ 无隧道依赖)；⑤ 中 M7 :9002 冒烟随 gate_b2 整门重跑(B3 不重复实现)，显存互斥下只走 dub-tts 主力不触发备选引擎懒加载",
]

_T0 = time.monotonic()


class Args:
    skip_gpu: bool = False


ARGS = Args()

# ---------------------------------------------------------------------------
# pytest 运行器（①–④ 共用；结构沿用 gate_b2 的 T13 预算语义——每项子进程帽
# = min(1800s, 整门剩余)，时钟为本门 _T0。跳过归因不复制：直接复用 gate_b2
# 的逐条归因实现（单一来源防分叉），仅同步 --skip-gpu 开关位）
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
    """--skip-gpu 豁免 = 直接调用 gate_b2 的逐条归因实现（单一来源）。

    gate_b2 的判定读 gate_b2.ARGS.skip_gpu，故先把 B3 的开关位同步过去；
    归因口径：tts/9002 归 :9002（b2.tts_service_state 探测）、asr_align/9001
    归 :9001（b1.service_state 探测），对应服务确认不可达才豁免；归因不了
    的跳过不豁免（两条隧道可能只断一条）。
    """
    b2.ARGS.skip_gpu = ARGS.skip_gpu
    return b2._gpu_relief_ok(skipped)


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


def check_m11() -> tuple[bool, str]:
    return _pytest_item(["tests/test_m11.py"])


def check_m8() -> tuple[bool, str]:
    return _pytest_item(["tests/test_m8.py"])


def check_m9() -> tuple[bool, str]:
    return _pytest_item(["tests/test_m9.py"])


# ---------------------------------------------------------------------------
# ⑤ gate_b2 整门回归（子进程重跑 B2 批次门禁，退出码即判定）
# ---------------------------------------------------------------------------


def check_gate_b2() -> tuple[bool | None, str]:
    """⑤ gate_b2 回归 = 子进程整门重跑 scripts/gate_b2.py。

    返回 (True PASS | None SKIP-GPU | False FAIL, 明细)。gate_b2 内部六项
    （全量套件 / M5 / M6 / M7 :9002 冒烟 / B1 契约回归 / 中性名）由其自身
    实现，本项不拆条重复；--skip-gpu 透传（口径与其自身一致）。子进程帽
    = min(1800s, B3 整门剩余预算)——B3 预算紧张时可能先于 gate_b2 自身
    预算（其单项 1800s / 整门 3600s）被砍，此时如实判 FAIL 并注明。
    """
    timeout_s = _item_timeout()
    if timeout_s <= 0:
        return False, (f"整门预算耗尽（>{GATE_BUDGET_S}s），本项未执行: "
                       f"gate_b2 整门回归（{GATE_B2_SCRIPT.name}）")
    if not GATE_B2_SCRIPT.is_file():
        return False, f"回归对象不存在: {GATE_B2_SCRIPT}"
    vpy = b0.venv_python()
    if vpy is None:
        return False, "未找到 .venv 解释器（.venv/Scripts/python.exe 或 .venv/bin/python）"
    env, env_note = b0._pytest_env()
    if env is None:
        return False, env_note
    cmd = [str(vpy), str(GATE_B2_SCRIPT)]
    if ARGS.skip_gpu:
        cmd.append("--skip-gpu")
    try:
        r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=timeout_s, env=env)
    except subprocess.TimeoutExpired:
        return False, (f"gate_b2 子进程超时（>{timeout_s}s，B3 单项帽 "
                       f"{PER_ITEM_TIMEOUT_S}s/整门 {GATE_BUDGET_S}s 取小；gate_b2 "
                       f"自身预算为其单项 1800s/整门 3600s，此处被 B3 预算先砍）")
    out = r.stdout or ""
    lines = [ln for ln in out.splitlines() if ln.strip()]
    tail = " | ".join(lines[-2:])[:400] if lines else (r.stderr or "").strip()[:400]
    m = B2_SUMMARY_RE.search(out)
    if r.returncode != 0:
        return False, (f"gate_b2 退出码 {r.returncode}: "
                       f"{m.group(0) if m else tail}")
    if m is None:
        return False, f"gate_b2 退出码 0 但汇总行缺失/不可解析: {tail}"
    n_pass_b2, n_skip_b2, n_fail_b2 = int(m.group(1)), int(m.group(3)), int(m.group(4))
    summary = m.group(0)
    if n_fail_b2:
        return False, f"gate_b2 汇总含 FAIL（退出码却为 0，口径异常）: {summary}"
    if n_skip_b2:
        if not ARGS.skip_gpu:
            return False, (f"gate_b2 输出 SKIP-GPU 但 B3 未传 --skip-gpu（口径异常，"
                            f"gate_b2 豁免需显式开关）: {summary}")
        return None, f"[{env_note}] gate_b2 整门重跑: {summary}"
    return True, f"[{env_note}] gate_b2 整门重跑: {summary}"


# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="B3 批次门禁（M8/M9/M11 收口）")
    parser.add_argument("--skip-gpu", action="store_true",
                        help="GPU 服务不可达时豁免第①项中'服务不可达'类跳过并透传给"
                             "第⑤项 gate_b2 子进程（输出注明；其余跳过仍 FAIL）")
    ns = parser.parse_args()
    ARGS.skip_gpu = ns.skip_gpu

    checks = [
        ("① pytest tests/ 全绿且零跳过（全量套件=B3 m8/m9/m11 与 B0–B2 存量同一门，契约回归在内）",
         check_suite),
        ("② M11 eval（pytest tests/test_m11.py：OCR 中文残留=0/标识区哈希/ar RTL，离线）",
         check_m11),
        ("③ M8 eval（pytest tests/test_m8.py：±10% 落窗/七类路径/C5 契约，离线）",
         check_m8),
        ("④ M9 eval（pytest tests/test_m9.py：时长差/loudnorm 复测/可懂度，离线）",
         check_m9),
        ("⑤ gate_b2 回归（子进程整门重跑 scripts/gate_b2.py，退出码即判定）",
         check_gate_b2),
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
    print(f"== gate_b3: {n_pass}/{len(checks)} PASS, {n_skip} SKIP-GPU, {n_fail} FAIL "
          f"(墙钟 {time.monotonic() - _T0:.0f}s / 整门预算 {GATE_BUDGET_S}s) ==")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
