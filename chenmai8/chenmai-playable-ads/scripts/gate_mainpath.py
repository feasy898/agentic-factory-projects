#!/usr/bin/env python3
"""演示主路径总验收门（gate_mainpath）：把「能上台」的五件事固化为一条命令。

对应整体反馈（_reviews/playable-ads-holistic.md §一 演示日缺口清单与五分钟脚本）
的第 1/2/5 条：一条命令串起校验→构建→打包→质检→二维码（行动 1）、真机可扫的
预构建兜底（行动 2）、以及公开仓中性名红线。前两个阶段门（gate_phase0/phase1）
管模块验收，本门管演示主路径整体可用性；任何一项 [FAIL] 即退出码 1 阻塞上台。

用法（系统 python，工作目录任意）：

    python scripts/gate_mainpath.py           # 五项门禁，全过 exit 0

约定（同 gate_phase0/phase1）：
- 仓库根按本文件位置自动定位（scripts/ 的上一级），不依赖当前工作目录；
- 子门/走查用运行本脚本的同一解释器（系统 python）启动；脚本内部自会用
  python/.venv/Scripts/python.exe 跑 Python 子命令、PATH 中的 node 跑 Node 子命令；
- 逐项打印 [PASS]/[FAIL]（项内子断言另起一行标注 ok/FAIL）；
  全部通过打印 "GATE MAINPATH: PASS" 并退出 0，否则 "GATE MAINPATH: FAIL" 退出 1。

五个门项（对应演示主路径缺口 1/2/5 + 两个阶段门回归）：
  1. Phase 0 门回归：python scripts/gate_phase0.py -> exit 0（6 项模块门全绿，
     _vendor/spike 缺席时其门项按 SKIP-ENV 记，不算失败——阶段门自身语义）。
  2. Phase 1 门回归：python scripts/gate_phase1.py -> exit 0（4 项链路门全绿）。
  3. 演示走查：python scripts/demo_walkthrough.py -> exit 0，且计时输出在位——
     走查尾部必须打印契约 §5 计时口径的三行（make 墙钟（入口→二维码可扫）、
     spec 改完→二维码可扫、走查总墙钟）；本门解析并展示总墙钟秒数。
     走查每次整体重建 artifacts/demo-prebuilt/（契约 §3.4），为门项 4 供鲜产物。
  4. 演示兜底目录：artifacts/demo-prebuilt/ 存在且含——
     汇总页 index.html、真实 PNG 二维码 qr.png（魔数校验）、pipeline-report.json
     （timings.makeWallSec / specModifiedToQrScannableSec 为正数，且 finishedAt
     不早于本门启动时刻——证明是本次走查重建而非残留）、preview/ 预览 HTML、
     三渠道目录（applovin/meta 单 HTML、mintegral zip，各带 pack-manifest）与
     质检报告拷贝（零 fail）。质检是裁判：任一 fail 就不该有兜底目录。
  5. 中性名扫描：入库树（git ls-files；git 不可用时退化目录枚举）的路径与
     文件内容对词表做大小写不敏感子串匹配，必须零命中。词表=本机
     _vendor/neutral-words.txt（含上游名，故不入库——同 _vendor/NOTES.md 的
     "上游事实只记本机"红线；缺失或为空即 FAIL，按文件内注释自行补建）。
     本脚本公开入库，自身不得出现任何上游名；发现命中只报告不修改
     （改名/声明问题不碰——法务裁定）。

耗时预期：门项 1-3 串行真实执行三套验收（含两轮 qacore 自动试玩与一次
pfcore make 全流水线），全程约 5-10 分钟；二进制产物目录与 tmp/ 均被
.gitignore 覆盖，本门不写任何入库文件。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Windows 控制台默认非 UTF-8 代码页，先固定本进程输出编码，避免中文乱码。
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# ------------------------------------------------------------------ 路径定位
# 仓库根 = 本文件（repo/scripts/gate_mainpath.py）的上一级目录。
# 子进程一律绝对路径 + 显式 cwd=REPO_ROOT，工作目录任意都能跑。
REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
GATE_PHASE0 = SCRIPTS_DIR / "gate_phase0.py"
GATE_PHASE1 = SCRIPTS_DIR / "gate_phase1.py"
DEMO_WALKTHROUGH = SCRIPTS_DIR / "demo_walkthrough.py"

DEMO_DIR = REPO_ROOT / "artifacts" / "demo-prebuilt"
PIPELINE_REPORT = DEMO_DIR / "pipeline-report.json"

NEUTRAL_WORDLIST = REPO_ROOT / "_vendor" / "neutral-words.txt"

# 三投放渠道（channel-rules.json 冻结集合；zip 渠道产物 <project>-<locale>.zip）。
SINGLE_HTML_CHANNELS = ("applovin", "meta")
ZIP_CHANNELS = ("mintegral",)
MANIFEST_NAME = "pack-manifest.json"

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# 门项 3 计时行标记（demo_walkthrough.py 打印的契约 §5 计时口径三行）。
TIMING_MARKERS = (
    "make 墙钟（入口→二维码可扫）",
    "spec 改完→二维码可扫",
    "走查总墙钟",
)
# 走查行形如「走查总墙钟（本脚本 t0→断言全过）：34.9s」——注意字面 t0，不能假设
# 标记与数字之间无数字，用非贪婪跳到第一个紧邻 s 的数。
WALK_TOTAL_RE = re.compile(r"走查总墙钟.*?([0-9]+(?:\.[0-9]+)?)s")

# 子门/走查超时：阶段门各含 qacore 自动试玩与多轮打包，给足余量。
SUBGATE_TIMEOUT_SEC = 1500
WALKTHROUGH_TIMEOUT_SEC = 900


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


def mark(ok: bool, text: str) -> str:
    """子断言行前缀：ok / FAIL，让项内失败一眼可见。"""
    return f"{'ok  ' if ok else 'FAIL'} {text}"


def run_script(script: Path, timeout: int) -> tuple[int, list[str], float]:
    """以本脚本同一解释器跑一个仓库内门/走查脚本，返回 (退出码, 输出行, 墙钟秒)。

    用 sys.executable 而非 venv 解释器：三个脚本自身按纪律内部改用
    python/.venv/Scripts/python.exe 与 node；cwd 钉在仓库根（工作目录任意性
    由脚本内 REPO_ROOT 自定位保证）。
    """
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    t0 = time.monotonic()
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(REPO_ROOT), capture_output=True, timeout=timeout, env=env,
    )
    elapsed = time.monotonic() - t0
    text = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    return proc.returncode, [ln for ln in text.splitlines() if ln.strip()], elapsed


def gate_banner_lines(out: list[str]) -> list[str]:
    """摘出子门输出里的 GATE ...: PASS/FAIL 汇总行（含各项 [PASS]/[FAIL] 摘要）。"""
    return [ln for ln in out if ln.startswith(("GATE ", "[PASS]", "[FAIL]"))][-8:]


# ------------------------------------------------------------------ 门项 1/2：阶段门回归
def check_subgate(gate: Gate, idx: int, script: Path, name: str) -> None:
    """阶段门回归：真实执行子门脚本，退出码必须为 0。"""
    label = f"{idx}/5 阶段门回归：{name} exit 0"
    if not script.is_file():
        gate.item(label, False, [f"脚本不存在：{script}"])
        return
    try:
        rc, out, elapsed = run_script(script, SUBGATE_TIMEOUT_SEC)
    except subprocess.TimeoutExpired as exc:
        gate.item(label, False, [f"子门超时（>{exc.timeout:.0f}s）"])
        return
    except Exception as exc:  # 子进程启动失败等
        gate.item(label, False, [f"子进程异常：{exc!r}"])
        return
    details = [f"exit={rc}（应 0），墙钟 {elapsed:.1f}s"] + gate_banner_lines(out)
    if rc != 0:
        details += ["", "—— 子门输出尾部 ——"] + out[-12:]
    gate.item(label, rc == 0, details)


# ------------------------------------------------------------------ 门项 3：演示走查
def check_walkthrough(gate: Gate, idx: int) -> None:
    """演示走查：exit 0 且契约 §5 计时输出三行在位；解析展示走查总墙钟。"""
    label = "3/5 演示走查：demo_walkthrough exit 0 且计时输出在位（契约 §5 口径三行）"
    if not DEMO_WALKTHROUGH.is_file():
        gate.item(label, False, [f"脚本不存在：{DEMO_WALKTHROUGH}"])
        return
    try:
        rc, out, elapsed = run_script(DEMO_WALKTHROUGH, WALKTHROUGH_TIMEOUT_SEC)
    except subprocess.TimeoutExpired as exc:
        gate.item(label, False, [f"走查超时（>{exc.timeout:.0f}s）"])
        return
    except Exception as exc:
        gate.item(label, False, [f"子进程异常：{exc!r}"])
        return

    sub_lines = [f"exit={rc}（应 0），本门侧墙钟 {elapsed:.1f}s"]
    ok = rc == 0

    joined = "\n".join(out)
    for marker in TIMING_MARKERS:
        hit = marker in joined
        sub_lines.append(mark(hit, f"计时输出含「{marker}」"))
        ok = ok and hit
    m = WALK_TOTAL_RE.search(joined)
    if m:
        total_sec = float(m.group(1))
        sub_lines.append(mark(True, f"走查总墙钟 {total_sec:.1f}s（走查自报，预算 180s/理想 90s）"))
    else:
        sub_lines.append(mark(False, "未能从走查输出解析走查总墙钟秒数"))
        ok = False
    if rc != 0:
        sub_lines += ["", "—— 走查输出尾部 ——"] + out[-12:]
    gate.item(label, ok, sub_lines)


# ------------------------------------------------------------------ 门项 4：兜底目录
def check_demo_prebuilt(gate: Gate, idx: int, gate_t0: datetime) -> None:
    """演示兜底目录：预览 HTML + 三渠道目录 + 报告 + 二维码，且是本次走查重建。"""
    label = ("4/5 演示兜底目录：demo-prebuilt 含预览 HTML+三渠道目录+报告+二维码"
             "（本次走查重建）")
    sub = SubChecks()

    if not DEMO_DIR.is_dir():
        gate.item(label, False, [f"目录不存在：{DEMO_DIR}（先让门项 3 走查跑绿）"])
        return
    sub.check(True, f"目录存在：{DEMO_DIR}")

    # -- 汇总页 -------------------------------------------------------------
    index_html = DEMO_DIR / "index.html"
    ok_index = index_html.is_file() and index_html.stat().st_size > 0
    sub.check(ok_index,
              f"汇总页 index.html（{index_html.stat().st_size if index_html.is_file() else -1} B）")

    # -- 二维码：真实 PNG（魔数），非占位 -----------------------------------
    qr = DEMO_DIR / "qr.png"
    if not qr.is_file():
        sub.check(False, "qr.png 落盘")
    else:
        head = qr.read_bytes()[:8]
        sub.check(head == PNG_MAGIC and qr.stat().st_size >= 100,
                  f"qr.png 为真实 PNG（{qr.stat().st_size} B，魔数={'匹配' if head == PNG_MAGIC else '不符'}）")

    # -- 运行报告：计时字段 + 本次重建证据 -----------------------------------
    report: dict = {}
    if not PIPELINE_REPORT.is_file():
        sub.check(False, f"pipeline-report.json 落盘（{PIPELINE_REPORT}）")
    else:
        try:
            report = json.loads(PIPELINE_REPORT.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            sub.check(False, f"pipeline-report.json 可解析：{exc}")
    if report:
        timings = report.get("timings") or {}
        make_wall = timings.get("makeWallSec")
        spec_to_qr = timings.get("specModifiedToQrScannableSec")
        sub.check(isinstance(make_wall, (int, float)) and make_wall > 0,
                  f"timings.makeWallSec={make_wall}（正数，契约 §5 口径 1）")
        sub.check(isinstance(spec_to_qr, (int, float)) and spec_to_qr > 0,
                  f"timings.specModifiedToQrScannableSec={spec_to_qr}（正数，契约 §5 口径 2）")
        finished = _parse_local_ts(report.get("finishedAt"))
        sub.check(finished is not None and finished >= gate_t0,
                  f"finishedAt={report.get('finishedAt')} ≥ 本门启动 {gate_t0.isoformat(timespec='seconds')}"
                  "（本次走查整体重建，非残留）")

    # -- 预览 HTML ----------------------------------------------------------
    previews = sorted((DEMO_DIR / "preview").glob("*.html")) if (DEMO_DIR / "preview").is_dir() else []
    sub.check(bool(previews), f"preview/ 预览 HTML（{len(previews)} 个）")
    if previews:
        size = previews[0].stat().st_size
        sub.check(size >= 100_000, f"预览 {previews[0].name} {size} B ≥ 100KB（真实可玩包，非占位）")

    # -- 三渠道目录（applovin/meta 单 HTML、mintegral zip，各带 pack-manifest）-
    for ch in SINGLE_HTML_CHANNELS:
        pkgs = sorted((DEMO_DIR / "channels" / ch).glob("*/index.html")) \
            if (DEMO_DIR / "channels" / ch).is_dir() else []
        manifests = sorted((DEMO_DIR / "channels" / ch).glob(f"*/{MANIFEST_NAME}")) \
            if (DEMO_DIR / "channels" / ch).is_dir() else []
        sub.check(bool(pkgs) and bool(manifests),
                  f"channels/{ch}/<locale>/index.html + {MANIFEST_NAME}（{len(pkgs)} 包）")
    for ch in ZIP_CHANNELS:
        zips = sorted((DEMO_DIR / "channels" / ch).glob("*/*.zip")) \
            if (DEMO_DIR / "channels" / ch).is_dir() else []
        manifests = sorted((DEMO_DIR / "channels" / ch).glob(f"*/{MANIFEST_NAME}")) \
            if (DEMO_DIR / "channels" / ch).is_dir() else []
        sub.check(bool(zips) and bool(manifests),
                  f"channels/{ch}/<locale>/*.zip + {MANIFEST_NAME}（{len(zips)} 包）")

    # -- 质检报告拷贝：质检是裁判，任一 fail 就不该进兜底目录 -----------------
    qa_reports = sorted((DEMO_DIR / "channels").glob("*/*/index.report.json")) \
        if (DEMO_DIR / "channels").is_dir() else []
    sub.check(bool(qa_reports), f"渠道目录内质检报告拷贝（{len(qa_reports)} 份 index.report.json）")
    for rp in qa_reports:
        try:
            qa = json.loads(rp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            sub.check(False, f"{rp.relative_to(DEMO_DIR).as_posix()} 可解析：{exc}")
            continue
        failed = [c.get("id") for c in qa.get("checks", [])
                  if isinstance(c, dict) and c.get("status") == "fail"]
        sub.check(not failed,
                  f"{rp.relative_to(DEMO_DIR).as_posix()} 零 fail"
                  + (f"（命中 {failed}）" if failed else ""))

    gate.item(label, sub.ok, sub.lines)


def _parse_local_ts(value) -> datetime | None:
    """解析 pipeline-report 的本地时间戳（ISO 无时区，如 2026-09-29T03:37:53）。"""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


# ------------------------------------------------------------------ 门项 5：中性名扫描
def check_neutral_names(gate: Gate, idx: int) -> None:
    """中性名扫描：入库树（路径+内容）对词表大小写不敏感匹配，零命中。"""
    try:
        wl_disp = NEUTRAL_WORDLIST.relative_to(REPO_ROOT).as_posix()
    except ValueError:  # 词表在仓库外（仅测试注入会出现）：直接显示绝对路径
        wl_disp = str(NEUTRAL_WORDLIST)
    label = (f"5/5 中性名扫描：入库树零上游名命中（词表 {wl_disp}，不入库）")
    sub = SubChecks()

    # 词表：上游名不能进公开仓，故只存本机 _vendor/（.gitignore 覆盖）。
    if not NEUTRAL_WORDLIST.is_file():
        gate.item(label, False, [
            f"词表不存在：{NEUTRAL_WORDLIST}",
            "词表含上游名、不能入库（法务红线），需在本机按 _vendor/neutral-words.txt"
            " 头部注释格式补建后再跑本门。",
        ])
        return
    try:
        raw_lines = NEUTRAL_WORDLIST.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        gate.item(label, False, [f"词表不可读：{exc}"])
        return
    words = [ln.strip().lower() for ln in raw_lines
             if ln.strip() and not ln.strip().startswith("#")]
    sub.check(bool(words), f"词表非空：{len(words)} 个词")
    if not words:
        gate.item(label, False, sub.lines)
        return

    files = _tracked_repo_files()
    if files is None:
        gate.item(label, False, ["无法枚举入库树（git 不可用且目录枚举失败）"])
        return

    hits: list[str] = []
    scanned = 0
    for f in files:
        rel = f.relative_to(REPO_ROOT).as_posix()
        rel_low = rel.lower()
        path_hits = [w for w in words if w in rel_low]
        if path_hits:
            hits.append(f"{rel}: 路径命中 {path_hits}")
            continue  # 路径已命中，内容不必再扫
        try:
            if not f.is_file():
                continue
            scanned += 1
            for lineno, line in enumerate(
                    f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                line_low = line.lower()
                hit_words = [w for w in words if w in line_low]
                if hit_words:
                    hits.append(f"{rel}:{lineno}: 命中 {hit_words}：{line.strip()[:80]}")
        except OSError:
            continue

    sub.check(not hits,
              f"扫描 {scanned} 个入库文件（git ls-files）× {len(words)} 词：命中 {len(hits)} 处")
    sub.lines.extend(f"      {h}" for h in hits[:10])
    if hits:
        sub.lines.append("      （命中只报告不修改——改名/声明问题不碰，法务裁定）")
    gate.item(label, sub.ok, sub.lines)


def _tracked_repo_files() -> list[Path] | None:
    """入库树文件清单：git ls-files 为准；git 不可用时退化为目录枚举
    （跳过依赖/产物目录，仅作兜底）——同 gate_phase0 做法。"""
    try:
        proc = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
                              capture_output=True, timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode("utf-8", "replace")[:200])
        names = proc.stdout.decode("utf-8", "replace").split("\0")
        return [REPO_ROOT.joinpath(*n.split("/")) for n in names if n]
    except Exception:
        try:
            skip_dirs = {".git", "node_modules", ".venv", "__pycache__", "_vendor",
                         "tmp", "artifacts", "coverage"}
            return [p for p in REPO_ROOT.rglob("*")
                    if p.is_file() and not (set(p.parts) & skip_dirs)]
        except OSError:
            return None


class SubChecks:
    """门项内的子断言收集器：逐条记 ok/FAIL 行，任一 FAIL 拖垮整项。"""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.ok = True

    def check(self, ok: bool, text: str) -> None:
        self.lines.append(mark(ok, text))
        if not ok:
            self.ok = False


# ------------------------------------------------------------------ 主流程
def main() -> int:
    t0_dt = datetime.now()
    print("=" * 72)
    print("演示主路径总验收门（gate_mainpath）")
    print(f"仓库根     : {REPO_ROOT}")
    print(f"解释器     : {sys.executable}")
    print(f"启动时刻   : {t0_dt.isoformat(timespec='seconds')}")
    print("=" * 72)

    if not REPO_ROOT.is_dir() or not SCRIPTS_DIR.is_dir():
        print("[FAIL] 仓库结构异常：未找到 scripts/ 目录（脚本被挪动了？）")
        return 1

    gate = Gate()
    t0 = time.monotonic()
    check_subgate(gate, 1, GATE_PHASE0, "gate_phase0")
    check_subgate(gate, 2, GATE_PHASE1, "gate_phase1")
    check_walkthrough(gate, 3)
    check_demo_prebuilt(gate, 4, t0_dt)
    check_neutral_names(gate, 5)
    elapsed = time.monotonic() - t0

    total = 5
    print("-" * 72)
    if gate.failures:
        print(f"GATE MAINPATH: FAIL（{total - gate.failures}/{total} 项通过，"
              f"耗时 {elapsed:.1f}s）——主路径未达上台线，先修复失败项。")
        return 1
    print(f"GATE MAINPATH: PASS（{total}/{total} 项通过，耗时 {elapsed:.1f}s）"
          "——演示主路径可用：阶段门全绿 + 走查绿 + 兜底在位 + 中性名零命中。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
