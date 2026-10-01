#!/usr/bin/env python3
"""收官终检门（Gate FINAL，T8.3）：批次 0-6 七门全回归 + M11 健壮性 + 公开导出终检
+ 全项目指标终值汇总表。系统 python 从任意 cwd 可运行；内部统一用仓库 .venv 执行
各项 eval。

用法（系统 python 即可，无需激活 venv，可在任意工作目录）::

    python D:/workspace/澄迈8项目/政务AI脱敏网关/repo/ops/gate_final.py

行为（任务单 T8.3；结构沿用 ops/gate_b6.py）：
1. 内部 chdir 到仓库根，统一设 PYTHONUTF8=1，stdout/stderr 重配为 UTF-8；
2. 依次运行九项：
   ①-⑦ 七门全回归：ops/gate_d0.py / gate_b1.py / gate_b2.py / gate_b3.py /
     gate_b4.py / gate_b5.py / gate_b6.py，各用启动本门的解释器按其文档用法原样
     跑一遍（各门自身契约即「系统 python 任意 cwd」；输出全量透传。b6 内含
     b5→b4→b3→b2 整链回归、m8_quality 真实大模型面与 e2e U8）；
   ⑧ -m evals.m11_robust   批次 7 T7.2 健壮性门（畸形输入 4xx+信封 / 非法 SSE
     有界终止 / 并发 50 零串扰）；
   ⑨ ops/export_public.py  公开导出终检（T8.2：git 跟踪面导出 + 依赖清单处理 +
     严格档 name_lint 零命中）；
3. 每项透传完整输出并打印 [PASS]/[FAIL] 与退出码、单项用时；末尾两表：
   - 九项门结果汇总表（抓取各门/各 eval 自报摘要行，含嵌套整链结果行）；
   - 全项目指标终值表（识别 F1 / 延迟 / 质量比 / e2e 用例数 / 审计零明文字节数）
     ——只从本次运行的透传输出与 m8_quality 落盘报告（data/bench/quality_report.json，
     本次 ⑦ ③ 刷新）中抓取实测值，逐行注明出处，无一处手填；抓取不到的指标如实
     标「未取到」，绝不补造数；
   任何 FAIL → 本脚本退出码 1。

超时预算（任务单）：单项 1800s（⑧⑨ 与各门内部 eval）；整门 5400s（①-⑦ 各门整体，
含其内部嵌套整链回归与真实大模型面）。

环境依赖（沿用 gate_b6 口径）：m8_quality（⑦ ③）与 e2e U8（⑦ ④）为真实大模型面
= GPU 机 llm_openai 服务 :9004 经 ops/tunnel_gpu.sh 隧道（本机 127.0.0.1:9004，
keepalive 常驻）。本门启动时打印隧道健康预检（仅注记，不改口径）；隧道断时 ⑦ 按
gate_b6 自身契约注记 SKIP-GPU 计过（U8 DEFER / m8_quality DEFERRED，均 exit 0），
本门照实转记；此时质量比/F1 终值行标注「本次未出数」并拒读旧报告冒充本次实测。

本脚本对运行环境只依赖标准库（系统 python 无第三方依赖也能定位仓库、启动子进程、
汇总结果）。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"

#: 启动本门的解释器（①-⑦ 各门回归用：各门自身契约即「系统 python 任意 cwd」）
GATE_PYTHON = sys.executable or "python"

EVAL_TIMEOUT_S = 1800   # 单项上限（m11_robust 全拓扑 / export_public 导出+严格档终检）
GATE_TIMEOUT_S = 5400   # ①-⑦ 整门回归上限（b6 内含 b5→b4→b3→b2 整链与真实大模型面，
                        # 各门内部另有自家单项/整门超时）

#: (显示名, 完整命令 argv, 超时秒)；①-⑦ 各门按其文档用法原样调用（系统解释器 +
#: 脚本路径）；⑧⑨ 统一 .venv 解释器、cwd=仓库根。
CHECKS: list[tuple[str, list[str], int]] = [
    ("① 回归 ops/gate_d0.py", [GATE_PYTHON, str(REPO_ROOT / "ops" / "gate_d0.py")],
     GATE_TIMEOUT_S),
    ("② 回归 ops/gate_b1.py", [GATE_PYTHON, str(REPO_ROOT / "ops" / "gate_b1.py")],
     GATE_TIMEOUT_S),
    ("③ 回归 ops/gate_b2.py", [GATE_PYTHON, str(REPO_ROOT / "ops" / "gate_b2.py")],
     GATE_TIMEOUT_S),
    ("④ 回归 ops/gate_b3.py", [GATE_PYTHON, str(REPO_ROOT / "ops" / "gate_b3.py")],
     GATE_TIMEOUT_S),
    ("⑤ 回归 ops/gate_b4.py", [GATE_PYTHON, str(REPO_ROOT / "ops" / "gate_b4.py")],
     GATE_TIMEOUT_S),
    ("⑥ 回归 ops/gate_b5.py", [GATE_PYTHON, str(REPO_ROOT / "ops" / "gate_b5.py")],
     GATE_TIMEOUT_S),
    ("⑦ 回归 ops/gate_b6.py", [GATE_PYTHON, str(REPO_ROOT / "ops" / "gate_b6.py")],
     GATE_TIMEOUT_S),
    ("⑧ evals.m11_robust", [str(VENV_PYTHON), "-m", "evals.m11_robust"], EVAL_TIMEOUT_S),
    ("⑨ ops/export_public.py 终检",
     [str(VENV_PYTHON), str(REPO_ROOT / "ops" / "export_public.py")], EVAL_TIMEOUT_S),
]

#: 各门/各 eval 的自报摘要行（透传输出中抓取，进门结果汇总表；含嵌套整链结果行）
_SUMMARY_PATTERNS = (
    re.compile(r"^name_lint: .+"),
    re.compile(r"^M0 INFRA: .+"),
    re.compile(r"^T0 LABELS: .+"),
    re.compile(r"^M8 GENERATOR: .+"),
    re.compile(r"^M2 RECOGNIZERS: .+"),
    re.compile(r"^M7 AUDIT\(.*\): .+"),
    re.compile(r"^M3 MASKING: .+"),
    re.compile(r"^M4 ROUTING: .+"),
    re.compile(r"^M5 OUTGUARD: .+"),
    re.compile(r"^M6 FILESVC\b.*: .+"),
    re.compile(r"^M6 OCR\(scan-pdf\): .+"),
    re.compile(r"^M2 SEMANTIC: .+"),
    re.compile(r"^m9_webui: .+"),
    re.compile(r"^M8 QUALITY: .+"),
    re.compile(r"^M11 ROBUST\(.*\): .+"),
    re.compile(r"^m11_robust: .+"),
    re.compile(r"^e2e_smoke: .+"),
    re.compile(r"^m10_e2e\(.*\): .+"),
    re.compile(r"^export_public: .+"),
    re.compile(r"^\[gate_(?:d0|b[1-6])\] 结果: .+"),
)

# ── 指标终值抓取用行形（全部锚定各 eval 实际打印格式）─────────────────────
_E2E_SUMMARY_RE = re.compile(
    r"^e2e_smoke: (?P<passed>\d+) PASS / (?P<failed>\d+) FAIL / (?P<deferred>\d+) DEFERRED")
_MICRO_RE = re.compile(r"structural micro=(?P<micro>[0-9.]+) \((?P<hit>\d+)/(?P<total>\d+)\)")
_M2_LATENCY_RE = re.compile(
    r"2000ch detect ×10 mean (?P<mean>[0-9.]+)ms \(max (?P<max>[0-9.]+)ms\) < 100ms")
_M7_BYTES_RE = re.compile(
    r"db\(\+wal/shm\) bytes-scan (?P<bytes>\d+)B → 0/(?P<values>\d+) 原值命中")
_RATIO_RE = re.compile(r"^  ratio = (?P<ratio>[0-9.]+)（阈值 ≥ (?P<th>0\.95)）")
_M8_PASSED_RE = re.compile(r"^M8 QUALITY: (?P<passed>\d+)/(?P<total>\d+) checks passed")
_M8_DEFERRED_RE = re.compile(r"^M8 QUALITY: DEFERRED\b")
_U5_BYTES_RE = re.compile(r"库文件 bytes 级扫描 (?P<bytes>\d+) 字节零明文")
_SEED_BYTES_RE = re.compile(
    r"^\[seed_demo\] 库文件 bytes 级零明文复扫: (?P<bytes>\d+) 字节，0 命中")
_M11_PASSED_RE = re.compile(r"^M11 ROBUST\(.*\): (?P<passed>\d+)/(?P<total>\d+) checks passed")
_EXPORT_LINT_RE = re.compile(
    r"^export_public strict lint: scanned (?P<files>\d+) files, (?P<vio>\d+) violation\(s\)")
_EXPORT_COPIED_RE = re.compile(r"^export_public: copied (?P<files>\d+) tracked files")

#: 质量评测落盘报告（⑦ ③ m8_quality 本次刷新；F1/真实链路延迟终值出处）
QUALITY_REPORT = REPO_ROOT / "data" / "bench" / "quality_report.json"

#: 真实大模型面预检（仅注记；DOWN 时 ⑦ 按其自身口径 SKIP-GPU，本门不改口径）
GPU_TUNNEL_HEALTH_URL = "http://127.0.0.1:9004/health"
GPU_TUNNEL_HEALTH_TIMEOUT_S = 4.0

#: 门间残留监听端口（e2e :9000/:8901/:8902/:9010；m11 专用 :9012/:9013/:8911-8913）。
#: 每项开跑前收割其上的 LISTENING 残留进程（门脚本是子进程，其异常退出路径留下的
#: 子进程本门够不到——run2 实锤：e2e mock 就绪超时路径泄漏子进程 → 后续 m5 端点
#: 占用 FAIL）。只收割本门九项用到的端口，不碰其他（含 :9004 隧道）。
GATE_MANAGED_PORTS = (9000, 8901, 8902, 9010, 9012, 9013, 8911, 8912, 8913)

METRIC_MISS = "（未取到）"


def _first_match(pattern: re.Pattern[str], output: str) -> re.Match[str] | None:
    """逐行找首个命中行；带 ^ 锚的行形等价 match，行中嵌入形（PASS 明细行）用 search。"""
    return next((m for m in (pattern.search(ln.rstrip()) for ln in output.splitlines())
                 if m is not None), None)


def _summaries(output: str) -> list[str]:
    return [ln.rstrip() for ln in output.splitlines()
            if any(p.match(ln.rstrip()) for p in _SUMMARY_PATTERNS)]


def _preflight_tunnel() -> str:
    """GPU 隧道健康预检（仅注记）：UP / DOWN（含原因）。"""
    try:
        with urllib.request.urlopen(GPU_TUNNEL_HEALTH_URL,
                                    timeout=GPU_TUNNEL_HEALTH_TIMEOUT_S) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if resp.status == 200 and body.get("loaded") is True:
            return (f"UP（service={body.get('service')} model={body.get('serve_model')}）"
                    f"—— ⑦ ③④ 真实大模型面可跑")
        return f"响应异常 status={resp.status} loaded={body.get('loaded')}（按 DOWN 注记）"
    except Exception as exc:  # noqa: BLE001 — 预检注记，任何异常都归为 DOWN
        return f"DOWN（{type(exc).__name__}: {exc}）—— ⑦ 按其自身口径 SKIP-GPU 计过"


def _reap_leftover_listeners() -> list[str]:
    """收割九项检查所用端口上的残留 LISTENING 进程（返回「端口<-pid」注记列表）。

    netstat 解析失败/无残留都安静返回；只对 GATE_MANAGED_PORTS 生效。
    """
    reaped: list[str] = []
    try:
        proc = subprocess.run(["netstat", "-ano", "-p", "tcp"],
                              capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return reaped
    pid_by_port: dict[int, str] = {}
    for line in proc.stdout.decode("utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[3].upper() != "LISTENING":
            continue
        for port in GATE_MANAGED_PORTS:
            if parts[1].endswith(f":{port}"):
                pid_by_port.setdefault(port, parts[4])
                break
    for port, pid in sorted(pid_by_port.items()):
        if not pid.isdigit() or pid == "0":
            continue
        try:
            subprocess.run(["taskkill", "/F", "/PID", pid],
                           capture_output=True, timeout=60)
            reaped.append(f"{port}<-pid {pid}")
        except (OSError, subprocess.TimeoutExpired):
            reaped.append(f"{port}<-pid {pid}(kill 失败)")
    return reaped


def _run_check(name: str, argv: list[str], timeout_s: int) -> tuple[bool, list[str], str, float]:
    interpreter = Path(argv[0]).name
    tail = " ".join(argv[1:])
    t0 = time.monotonic()
    print(f"\n===== [gate_final] RUN {name} ：{interpreter} {tail} "
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
        return False, [f"TIMEOUT >{timeout_s}s"], "", time.monotonic() - t0
    except OSError as exc:
        print(f"[FAIL] {name} — 解释器启动失败：{exc}", flush=True)
        return False, [f"interpreter error: {exc}"], "", time.monotonic() - t0
    elapsed = time.monotonic() - t0
    output = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
    if output:
        sys.stdout.write(output)
        if not output.endswith("\n"):
            sys.stdout.write("\n")
    status = "PASS" if proc.returncode == 0 else "FAIL"
    print(f"[{status}] {name} (exit={proc.returncode}) 用时 {elapsed:.1f}s", flush=True)
    return proc.returncode == 0, _summaries(output), output, elapsed


# ── 全项目指标终值抓取（只认本次运行输出；抓不到=如实标未取到）─────────────

def _extract_b1_metrics(output: str) -> dict[str, str]:
    """② gate_b1 输出 → 识别 micro 召回 / 规则层延迟 / m7 全库零明文字节。"""
    out: dict[str, str] = {}
    m = _first_match(_MICRO_RE, output)
    out["识别micro"] = (f"{m.group('micro')}（{m.group('hit')}/{m.group('total')} 例）"
                       if m else METRIC_MISS)
    m = _first_match(_M2_LATENCY_RE, output)
    out["规则层延迟"] = (f"2000 字 detect ×10 mean={m.group('mean')}ms"
                       f"（max {m.group('max')}ms，线 <100ms）" if m else METRIC_MISS)
    m = _first_match(_M7_BYTES_RE, output)
    out["m7零明文"] = (f"{int(m.group('bytes')):,} B 全库 bytes 扫描 → 0/"
                      f"{m.group('values')} 原值命中" if m else METRIC_MISS)
    return out


def _extract_b6_metrics(output: str) -> dict[str, str]:
    """⑦ gate_b6 输出 → 质量比 / e2e 用例数 / e2e U5 与 seed_demo 零明文字节。

    「首次出现」即 ⑦ 自身 ③④ 项的输出（其 ⑤ 嵌套整链输出排在其后）。
    """
    out: dict[str, str] = {}
    m = _first_match(_RATIO_RE, output)
    out["质量比"] = f"{m.group('ratio')}（阈值 ≥{m.group('th')}）" if m else METRIC_MISS
    m8 = _first_match(_M8_PASSED_RE, output)
    out["m8质量态"] = (f"{m8.group('passed')}/{m8.group('total')} checks passed"
                      if m8 else ("DEFERRED（真实上游离线）"
                                  if _first_match(_M8_DEFERRED_RE, output) else METRIC_MISS))
    m = _first_match(_E2E_SUMMARY_RE, output)
    out["e2e用例"] = (f"{m.group('passed')} PASS / {m.group('failed')} FAIL / "
                     f"{m.group('deferred')} DEFERRED" if m else METRIC_MISS)
    m = _first_match(_U5_BYTES_RE, output)
    out["e2e零明文"] = f"{int(m.group('bytes')):,} 字节 0 命中" if m else METRIC_MISS
    m = _first_match(_SEED_BYTES_RE, output)
    out["seed零明文"] = f"{int(m.group('bytes')):,} 字节 0 命中" if m else METRIC_MISS
    return out


def _extract_m11_metrics(output: str) -> str:
    m = _first_match(_M11_PASSED_RE, output)
    return f"{m.group('passed')}/{m.group('total')} checks passed" if m else METRIC_MISS


def _extract_export_metrics(output: str) -> str:
    copied = _first_match(_EXPORT_COPIED_RE, output)
    lint = _first_match(_EXPORT_LINT_RE, output)
    parts = []
    if copied:
        parts.append(f"导出 {copied.group('files')} 个跟踪文件")
    if lint:
        parts.append(f"严格档 lint 扫 {lint.group('files')} 文件 "
                     f"{lint.group('vio')} 命中")
    return "；".join(parts) if parts else METRIC_MISS


def _quality_report_metrics(fresh: bool) -> dict[str, str]:
    """m8_quality 落盘报告 → F1 / 真实链路延迟 / 质量比分母。

    fresh=True 表示本次 ⑦ ③ 全过（报告即本次实测）；fresh=False 时不读旧报告
    冒充本次实测——F1/延迟行如实标「本次未出数（真实上游离线，m8_quality DEFERRED）」。
    """
    if not fresh:
        return {"f1": METRIC_MISS + "（本次 m8_quality DEFERRED，未出数）",
                "真实链路延迟": METRIC_MISS + "（本次 m8_quality DEFERRED，未出数）"}
    if not QUALITY_REPORT.exists():
        return {"f1": METRIC_MISS + f"（报告缺失 {QUALITY_REPORT.name}）",
                "真实链路延迟": METRIC_MISS + f"（报告缺失 {QUALITY_REPORT.name}）"}
    try:
        data = json.loads(QUALITY_REPORT.read_text(encoding="utf-8"))
        m = data.get("metrics", {})
        pairs = data.get("pairs")
        return {
            "f1": (f"orig={m.get('f1_orig_mean')} / masked={m.get('f1_masked_mean')}"
                   f"（字符级 F1，{pairs} 对）"),
            "真实链路延迟": (f"orig p95={m.get('latency_ms_orig_p95')}ms / "
                          f"masked p95={m.get('latency_ms_masked_p95')}ms"),
        }
    except (OSError, ValueError) as exc:
        return {"f1": METRIC_MISS + f"（报告读取失败: {exc}）",
                "真实链路延迟": METRIC_MISS + f"（报告读取失败: {exc}）"}


def build_final_metrics(items: dict[str, tuple[bool, str]]) -> list[tuple[str, str, str]]:
    """汇总全项目指标终值行：(指标, 终值, 出处)。全部取自本次运行。"""
    b1_out = items.get("② 回归 ops/gate_b1.py", (False, ""))[1]
    b6_out = items.get("⑦ 回归 ops/gate_b6.py", (False, ""))[1]
    m11_out = items.get("⑧ evals.m11_robust", (False, ""))[1]
    export_out = items.get("⑨ ops/export_public.py 终检", (False, ""))[1]

    b1 = _extract_b1_metrics(b1_out)
    b6 = _extract_b6_metrics(b6_out)
    quality_fresh = b6.get("m8质量态", "").endswith("checks passed")
    qr = _quality_report_metrics(fresh=quality_fresh)

    rows: list[tuple[str, str, str]] = [
        ("识别 F1（字符级保真，本项目唯一 F1 口径）", qr["f1"],
         "⑦ ③ evals.m8_quality 落盘 data/bench/quality_report.json"
         "（识别本身按召回线口径，见下一行）"),
        ("识别·规则层 micro 召回（结构化号码 10 类）", b1["识别micro"],
         "② ④ evals.m2_recognizers（逐类召回全达标为前提）"),
        ("延迟·规则层", b1["规则层延迟"],
         "② ④ evals.m2_recognizers（§6 M2 延迟线）"),
        ("延迟·真实大模型链路", qr["真实链路延迟"],
         "⑦ ③ evals.m8_quality（脱敏前直连 vs 脱敏后网关链，p95）"),
        ("质量比（脱敏前后回答 LLM-judge）", b6["质量比"],
         f"⑦ ③ evals.m8_quality（{b6['m8质量态']}）"),
        ("e2e 用例数", b6["e2e用例"], "⑦ ④ evals.m10_e2e（§9 U1–U8 八用例）"),
        ("审计零明文·m7 全库 bytes 扫描", b1["m7零明文"],
         "② ⑤ evals.m7_audit（库文件+wal/shm，bytes 级 grep）"),
        ("审计零明文·e2e U5 库文件扫描", b6["e2e零明文"],
         "⑦ ④ ops/e2e_smoke U5（本批全部 normalized 原值）"),
        ("审计零明文·seed_demo 演示库复扫", b6["seed零明文"],
         "⑦ ④ m10_e2e/T5.3（种子值+密级词+注入语句全清单）"),
        ("M11 健壮性", _extract_m11_metrics(m11_out),
         "⑧ evals.m11_robust（畸形输入/非法 SSE/并发 50）"),
        ("公开导出终检", _extract_export_metrics(export_out),
         "⑨ ops/export_public.py（git 跟踪面导出+严格档 lint）"),
    ]
    return rows


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    os.chdir(REPO_ROOT)
    os.environ["PYTHONUTF8"] = "1"
    t_start = time.monotonic()

    print(f"[gate_final] 仓库根: {REPO_ROOT}", flush=True)
    print(f"[gate_final] 本门解释器(系统): {sys.executable}", flush=True)
    print(f"[gate_final] 检查项解释器(venv): {VENV_PYTHON}", flush=True)
    if not VENV_PYTHON.exists():
        print(f"[FAIL] venv 解释器缺失: {VENV_PYTHON}（先按 README 建立 .venv 并 pip install -e .）",
              flush=True)
        return 1
    print(f"[gate_final] 预检 GPU 隧道 :9004 → {_preflight_tunnel()}", flush=True)

    failures: list[str] = []
    items: dict[str, tuple[bool, str]] = {}
    summary_rows: list[tuple[str, bool, list[str], float]] = []
    for name, argv, timeout_s in CHECKS:
        reaped = _reap_leftover_listeners()
        if reaped:
            print(f"[gate_final] 项前端口清理: {'；'.join(reaped)}", flush=True)
        ok, summaries, output, elapsed = _run_check(name, argv, timeout_s)
        items[name] = (ok, output)
        summary_rows.append((name, ok, summaries, elapsed))
        if not ok:
            failures.append(name)

    # ── 门结果汇总表 ──────────────────────────────────────────────────
    print("\n===== [gate_final] 九项门结果汇总 =====", flush=True)
    for name, ok, summaries, elapsed in summary_rows:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}（用时 {elapsed:.0f}s）", flush=True)
        for line in summaries:
            print(f"        {line}", flush=True)

    # ── 全项目指标终值表（只取本次运行实测值）─────────────────────────
    print("\n===== [gate_final] 全项目指标终值表（全部取自本次运行实测；括注出处）=====",
          flush=True)
    for label, value, provenance in build_final_metrics(items):
        print(f"  {label}: {value}", flush=True)
        print(f"      （出处: {provenance}）", flush=True)

    total_min = (time.monotonic() - t_start) / 60
    if failures:
        print(f"\n[gate_final] 结果: {len(failures)}/{len(CHECKS)} FAIL"
              f"（{'；'.join(failures)}）→ 退出码 1（总用时 {total_min:.0f} 分钟）",
              flush=True)
        return 1
    print(f"\n[gate_final] 结果: {len(CHECKS)}/{len(CHECKS)} 全部 PASS → 退出码 0"
          f"（总用时 {total_min:.0f} 分钟）", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
