#!/usr/bin/env python3
"""端到端矩阵门（e2e_matrix）：specs-eval golden spec × 语言 × 冻结渠道的
「构建→打包→逐包质检」全矩阵真实执行，0 FAIL 才放行。

对应规划 §8 与 docs/assets/specs/orchestrator.md §3/§5（实现后该节已回填实测）：

    用法：python scripts/e2e_matrix.py [--quick] [--budget-sec N]
    流程：对每个 golden spec × locale × channel：模板构建 → 渠道打包 →
          qacore run --autoplay 逐包质检
    断言：全部包质检 0 fail；总耗时打印；产物大小表输出 summary.json
    --quick：仅 golden-match3 × en × 规则库冻结投放渠道（T2.4 起六渠道，随规则库
             扩缩自动跟随），每日冒烟门，硬预算 ≤90 秒（--budget-sec 可调；超预算即
             exit 1）
    全量（T2.5 起）：specs-eval 全部 golden-*.json × {en,zh} × 冻结投放渠道。
             四模板齐后 = 4 模板 × 2 语言 × 6 渠道 = 48 包，0 FAIL 为最终验收线
             （任务口径硬预算 ≤1200s，由 gate_phase2 以 --budget-sec 1200 把关；
             裸跑不设限只打印）。zh 为中文演示语；ar 等其余 spec 声明语言仍可
             经 --locales 显式回归（RTL 用例保留此入口）。
    抖动单重试（仅全量）：首检 FAIL 的格用同一 qacore（同一冻结检查链）至多
             重跑一次，以重跑结果为最终判定——只吸收瞬态负载抖动（本机实测
             2026-09-29：与外部任务并行时 CHK09 本地加载偶发冲破 golden 冻结的
             qc.maxLoadSec=2.0s，而同格 pf.readyMs 恒 <1.5s，属噪声非产物问题）；
             两跑皆 FAIL 的持续回归仍判 FAIL，质检是唯一裁判不变。
             重跑计入总墙钟；summary 逐格记 retried/firstAttemptFails 如实留痕。
             --quick 不启用（其 90s 预算本身不容重跑，冒烟语义保持简单）。

与编排器（pfcore/make.py）同一条真实链路：模板构建器（tmpl-*/build.mjs）→
渠道打包器（packages/packager/bin.mjs）→ qacore（质检是唯一裁判）。pack 子命令
目前仍是占位，故本脚本直接调打包器与质检器原语（与 make 内部完全同源），
不绕过 qacore 直接判定任何产物合格。

质检并发：逐包 qacore 相互独立（各自临时端口、各自报告），默认并行执行
（--jobs 0=auto，上限 4）压墙钟以满足 --quick ≤90s 预算；--jobs 1 退回串行。
zip 渠道产物（如 Template.html + build.js 结构）先解包到临时目录，对规则库
声明的入口 HTML 跑质检——qacore 只收单 HTML。

产物布局（默认 --out artifacts/matrix，与 artifacts 根下 make 产物互不覆盖）：

    <out>/preview/<project>-<locale>.html      模板构建产物 + .assets.json 旁车
    <out>/<project>/dist/<locale>/index.html   打包器输入形态
    <out>/<project>/<channel>/<locale>/...     渠道包 + index.report.json（逐包质检）
    <out>/extract/<project>-<locale>-<channel>/  zip 解包目录（质检用）
    <out>/summary.json                          矩阵汇总（逐格状态/大小表/墙钟）

退出码：0 全部通过（--quick 还须在预算内）；1 有 fail/error 或超预算；
2 用法/环境错误（venv/node/规则库/spec 缺失）。

纪律（同 gate_* 系列）：本脚本自身零第三方依赖、可用任意 CPython ≥3.10 运行、
仓库根按文件位置自定位；子进程一律 python/.venv/Scripts/python.exe（qacore 依赖
playwright）与 PATH 中的 node；Windows 控制台固定 UTF-8 输出。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = REPO_ROOT / "python" / ".venv" / "Scripts" / "python.exe"
RULES_PATH = REPO_ROOT / "channel-rules" / "channel-rules.json"
PACKAGER_BIN = REPO_ROOT / "packages" / "packager" / "bin.mjs"
SPECS_DIR = REPO_ROOT / "specs-eval"
PREVIEW_CHANNEL = "preview"  # 规则库中的本地渠道，不进投放矩阵

# spec.game.template → 模板构建脚本（与 pfcore/make.py 同表；无构建器的模板
# 其格记 skip 并如实给原因，绝不算通过）。T2.5 起四模板齐，全量矩阵不再有
# 「模板无构建器」的 skip 格。
TEMPLATE_BUILDERS: dict[str, Path] = {
    "match3": REPO_ROOT / "packages" / "templates" / "tmpl-match3" / "build.mjs",
    "merge": REPO_ROOT / "packages" / "templates" / "tmpl-merge" / "build.mjs",
    "pullpin": REPO_ROOT / "packages" / "templates" / "tmpl-pullpin" / "build.mjs",
    "sort": REPO_ROOT / "packages" / "templates" / "tmpl-sort" / "build.mjs",
}

# Windows 控制台默认非 UTF-8 代码页，固定本进程输出编码（同 pfcore 入口做法）。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


class MatrixError(Exception):
    """带退出码语义的矩阵失败：1=判定失败，2=用法/环境错误。"""

    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code


def _log(msg: str) -> None:
    print(f"[matrix] {msg}", flush=True)


def _python() -> str:
    if VENV_PYTHON.is_file():
        return str(VENV_PYTHON)
    raise MatrixError(f"未找到 venv 解释器：{VENV_PYTHON}（纪律要求 python/.venv/Scripts/python.exe）", 2)


def _run(cmd: list[str], label: str, timeout_sec: float = 300) -> None:
    """跑一个子进程（cwd 钉仓库根），非零退出即抛判定失败（附输出尾部）。"""
    env = dict(os.environ, PYTHONUTF8="1")
    proc = subprocess.run(
        cmd, cwd=str(REPO_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout_sec, env=env,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-10:])
        raise MatrixError(f"{label} 失败（exit {proc.returncode}）\n{tail or '(无输出)'}", 1)


# ---------------------------------------------------------------- 矩阵展开

def load_rules() -> dict:
    try:
        return json.loads(RULES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MatrixError(f"规则库不可读：{RULES_PATH}（{exc}）", 2) from exc


def discover_channels(rules: dict) -> list[str]:
    """规则库冻结的全部投放渠道（preview 是本地渠道，排除）。"""
    channels = [c for c in (rules.get("channels") or {}) if c != PREVIEW_CHANNEL]
    if not channels:
        raise MatrixError("规则库没有任何投放渠道", 2)
    return channels


def discover_specs(quick: bool) -> list[Path]:
    """golden spec 清单：specs-eval/golden-*.json；--quick 只取 golden-match3。"""
    if quick:
        spec = SPECS_DIR / "golden-match3.json"
        if not spec.is_file():
            raise MatrixError(f"--quick 缺指定 spec：{spec}", 2)
        return [spec]
    specs = sorted(SPECS_DIR.glob("golden-*.json"))
    if not specs:
        raise MatrixError(f"{SPECS_DIR} 下无 golden-*.json", 2)
    return specs


def spec_locales(spec: dict) -> list[str]:
    """spec 声明的全部语言（i18n.locales；validator 保证每语言 strings 键全）。"""
    return [str(x) for x in (spec.get("i18n") or {}).get("locales") or []]


def matrix_cells(specs: list[Path], locales: list[str], channels: list[str]) -> list[dict]:
    """展开 (spec, locale, channel) 格；模板无构建器的 spec 整体记 skip。"""
    cells: list[dict] = []
    for spec_path in specs:
        try:
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MatrixError(f"spec 不可读：{spec_path}（{exc}）", 2) from exc
        project = str((spec.get("meta") or {}).get("projectId") or spec_path.stem)
        template = str((spec.get("game") or {}).get("template") or "")
        builder = TEMPLATE_BUILDERS.get(template)
        if builder is None or not builder.is_file():
            _log(f"SKIP {spec_path.name}：模板 {template!r} 无真实构建器"
                 f"（现有：{', '.join(sorted(TEMPLATE_BUILDERS))}）")
            cells.append({"spec": spec_path.name, "project": project, "template": template,
                          "locale": "-", "channel": "-", "skip": f"模板 {template!r} 无真实构建器"})
            continue
        declared = set(spec_locales(spec))
        for locale in locales:
            if locale not in declared:
                _log(f"SKIP {spec_path.name}×{locale}：spec 未声明该语言（{sorted(declared)}）")
                cells.append({"spec": spec_path.name, "project": project, "template": template,
                              "locale": locale, "channel": "-",
                              "skip": f"spec 未声明语言 {locale}"})
                continue
            for channel in channels:
                cells.append({"spec": spec_path, "project": project, "template": template,
                              "locale": locale, "channel": channel, "skip": None})
    return cells


# ---------------------------------------------------------------- CHK10 判定输入

def required_texts_for(spec: dict, locale: str) -> list[str]:
    """CHK10 --require-text 推导：与 pfcore/make.py 完全同源（标题/教程/胜/CTA/分）。"""
    def loc(key: str) -> str:
        table = ((spec.get("i18n") or {}).get("strings") or {}).get(locale) or {}
        v = table.get(key)
        return str(v) if isinstance(v, str) else ""

    flow = spec.get("flow") or {}
    end_screen = flow.get("endScreen") or {}
    texts = [str((spec.get("meta") or {}).get("title") or "")]
    if (flow.get("tutorial") or {}).get("enabled", True):
        texts.append(loc("tutorial"))
    texts.append(loc("win"))
    texts.append(loc(str(end_screen.get("ctaKey") or "cta")))
    if end_screen.get("showScore", True):
        texts.append(loc("score"))
    return [t for t in texts if t]


def required_sprites_for(preview_html: Path) -> list[str]:
    """CHK10 --require-sprite：构建旁车 .assets.json 里真实内联的素材键。"""
    try:
        mf = json.loads(Path(str(preview_html) + ".assets.json").read_text(encoding="utf-8"))
        return [str(s.get("spriteKey")) for s in (mf.get("sprites") or []) if s.get("spriteKey")]
    except (OSError, json.JSONDecodeError, AttributeError):
        return []  # 旁车缺失/不可读 → 不提要求（构建日志已对缺失素材告警）


# ---------------------------------------------------------------- 阶段 A-C：构建与打包

def phase_build(cells: list[dict], out_root: Path) -> dict:
    """阶段 B：按 (spec, locale) 逐格构建（同 spec×locale 只建一次），组装打包输入。"""
    builds: dict[tuple[str, str], dict] = {}
    for cell in cells:
        if cell.get("skip"):
            continue
        key = (str(cell["spec"]), cell["locale"])
        if key in builds:
            continue
        spec_path = Path(cell["spec"])
        preview_html = out_root / "preview" / f"{cell['project']}-{cell['locale']}.html"
        _run(["node", str(TEMPLATE_BUILDERS[cell["template"]]),
              "--spec", str(spec_path), "--locale", cell["locale"], "--out", str(preview_html)],
             f"模板构建 {spec_path.name}×{cell['locale']}")
        dist_locale = out_root / cell["project"] / "dist" / cell["locale"]
        dist_locale.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(preview_html, dist_locale / "index.html")
        builds[key] = {"preview": preview_html, "dist": dist_locale.parent,
                       "sprites": required_sprites_for(preview_html)}
        _log(f"构建 OK：{cell['project']}×{cell['locale']}（{preview_html.stat().st_size:,}B）")
    return builds


def phase_pack(cells: list[dict], builds: dict, out_root: Path) -> dict:
    """阶段 C：逐格打包；zip 渠道解包到 extract/ 供质检。返回每格产物信息。"""
    rules = load_rules()
    rules_channels = rules.get("channels") or {}
    packed: dict[tuple[str, str, str], dict] = {}
    for cell in cells:
        if cell.get("skip"):
            continue
        spec_path, locale, channel = Path(cell["spec"]), cell["locale"], cell["channel"]
        b = builds[(str(spec_path), locale)]
        entry_rules = (rules_channels.get(channel) or {}).get("package") or {}
        fmt = entry_rules.get("format") or "single-html"
        _run(["node", str(PACKAGER_BIN), "build",
              "--spec", str(spec_path), "--dist", str(b["dist"]),
              "--channel", channel, "--locale", locale, "--out", str(out_root)],
             f"打包 {channel}/{locale}")
        cell_dir = out_root / cell["project"] / channel / locale
        if fmt == "zip":
            artifact = next((p for p in cell_dir.glob("*.zip") if p.is_file()), None)
        else:
            artifact = cell_dir / "index.html"
        if artifact is None or not artifact.is_file():
            raise MatrixError(f"打包 {channel}/{locale} 后未找到产物（{cell_dir}）", 1)
        qa_target = artifact
        if fmt == "zip":
            entry = str(entry_rules.get("entry") or "Template.html")
            extract_dir = out_root / "extract" / f"{cell['project']}-{locale}-{channel}"
            if extract_dir.exists():
                shutil.rmtree(extract_dir)
            extract_dir.mkdir(parents=True)
            with zipfile.ZipFile(artifact) as zf:
                zf.extractall(extract_dir)
            qa_target = extract_dir / entry
            if not qa_target.is_file():
                hits = sorted(extract_dir.rglob("*.html"))
                if not hits:
                    raise MatrixError(f"zip {artifact.name} 内无 HTML 可质检", 1)
                qa_target = hits[0]
        packed[(str(spec_path), locale, channel)] = {
            "artifact": artifact, "qa_target": qa_target, "format": fmt,
            "bytes": artifact.stat().st_size,
            "maxBytes": (rules_channels.get(channel) or {}).get("maxBytes"),
            "cell_dir": cell_dir,
        }
        _log(f"打包 OK：{channel}/{locale} {artifact.name} {artifact.stat().st_size:,}B（{fmt}）")
    return packed


# ---------------------------------------------------------------- 阶段 D：逐包质检（可并行）

def qa_one(cell: dict, packed: dict, builds: dict, out_root: Path) -> dict:
    """对单格跑 qacore run --autoplay（CHK10 判定输入与 make 同源），返回结果记录。"""
    spec = json.loads(Path(cell["spec"]).read_text(encoding="utf-8"))
    qc = spec.get("qc") or {}
    locale, channel = cell["locale"], cell["channel"]
    info = packed[(str(cell["spec"]), locale, channel)]
    report_path = info["cell_dir"] / "index.report.json"
    # 纪律：qacore 依赖 venv 内的 playwright，一律用 venv 解释器（_python()）
    cmd = [_python(), "-m", "qacore", "run", str(info["qa_target"]),
           "--channel", channel, "--autoplay",
           "--max-load-sec", str(qc.get("maxLoadSec", 2.0)),
           "--autoplay-timeout", str(qc.get("autoplayTimeoutSec", 45.0)),
           "--out", str(report_path)]
    for t in required_texts_for(spec, locale):
        cmd += ["--require-text", t]
    for k in builds[(str(cell["spec"]), locale)]["sprites"]:
        cmd += ["--require-sprite", k]

    t0 = time.perf_counter()
    env = dict(os.environ, PYTHONUTF8="1")
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600, env=env)
    wall = time.perf_counter() - t0
    rec: dict = {"spec": Path(cell["spec"]).name, "project": cell["project"],
                 "locale": locale, "channel": channel, "format": info["format"],
                 "artifact": str(info["artifact"].relative_to(out_root)),
                 "bytes": info["bytes"], "maxBytes": info["maxBytes"],
                 "report": str(report_path.relative_to(out_root)), "wallSec": round(wall, 1),
                 "status": "fail", "fails": [], "pfEnd": None, "endWin": None}
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-6:])
        rec["fails"] = [f"qacore exit {proc.returncode}：{tail}"]
        return rec
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        rec["fails"] = [f"质检报告不可读：{exc}"]
        return rec
    checks = report.get("checks") or []
    rec["fails"] = [f"{c.get('id')}: {c.get('detail', '')}"
                    for c in checks if c.get("status") == "fail"]
    rec["checks"] = {
        "pass": sum(1 for c in checks if c.get("status") == "pass"),
        "fail": len(rec["fails"]),
        "skip": sum(1 for c in checks if c.get("status") == "skip"),
    }
    pf = report.get("pf") or {}
    rec["pfEnd"] = pf.get("endMs")
    rec["endWin"] = pf.get("endWin")
    rec["status"] = "pass" if not rec["fails"] else "fail"
    return rec


def phase_qa(cells: list[dict], packed: dict, builds: dict, out_root: Path, jobs: int,
             allow_retry: bool) -> list[dict]:
    """逐包质检；jobs>1 时并行（各 qacore 独立端口/报告，互不干扰）。

    allow_retry（抖动单重试，仅全量启用）：首检 FAIL 的格用同一 qacore（同一冻结
    检查链）至多重跑一次，以重跑结果为最终判定；两跑皆 FAIL 仍判 FAIL。重跑计入
    阶段墙钟，逐格以 retried/firstAttemptFails 留痕。
    """
    work = [c for c in cells if not c.get("skip")]
    jobs = max(1, min(jobs, len(work))) if work else 1
    t0 = time.perf_counter()

    def run_batch(batch: list[dict]) -> list[dict]:
        if jobs == 1 or len(batch) == 1:
            return [qa_one(c, packed, builds, out_root) for c in batch]
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            futures = [pool.submit(qa_one, c, packed, builds, out_root) for c in batch]
            return [f.result() for f in futures]

    results = run_batch(work)
    if allow_retry:
        failed_idx = [i for i, r in enumerate(results) if r["status"] == "fail"]
        if failed_idx:
            names = "、".join(f"{results[i]['spec']}×{results[i]['locale']}×"
                              f"{results[i]['channel']}" for i in failed_idx)
            _log(f"首检 {len(failed_idx)} 格 FAIL，抖动单重试：重跑同一 qacore → {names}")
            retry_recs = run_batch([work[i] for i in failed_idx])
            for i, r2 in zip(failed_idx, retry_recs):
                r2["retried"] = True
                r2["firstAttemptFails"] = results[i]["fails"]
                results[i] = r2
    n_retried = sum(1 for r in results if r.get("retried"))
    _log(f"质检完成：{len(results)} 包并行度 {jobs}（含单重试 {n_retried} 格），"
         f"阶段墙钟 {time.perf_counter() - t0:.1f}s")
    return results


# ---------------------------------------------------------------- 汇总

def write_summary(out_root: Path, mode: str, results: list[dict], skips: list[dict],
                  wall_sec: float, budget_sec: float | None) -> Path:
    summary = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "wallSec": round(wall_sec, 1),
        "budgetSec": budget_sec,
        "totals": {
            "cells": len(results) + len(skips),
            "pass": sum(1 for r in results if r["status"] == "pass"),
            "fail": sum(1 for r in results if r["status"] == "fail"),
            "skip": len(skips),
            "retried": sum(1 for r in results if r.get("retried")),
        },
        "cells": results + skips,
    }
    path = out_root / "summary.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def print_table(results: list[dict], skips: list[dict]) -> None:
    print("-" * 78)
    print(f"{'spec':<22}{'locale':<7}{'channel':<11}{'bytes':>10}{'上限':>10}  {'结果':<6}{'质检墙钟':>8}")
    for r in sorted(results, key=lambda x: (x["spec"], x["locale"], x["channel"])):
        limit = f"{r['maxBytes']:,}" if isinstance(r.get("maxBytes"), int) else "-"
        verdict = r["status"] + ("*" if r.get("retried") else "")  # * = 单重试后过
        print(f"{r['spec']:<22}{r['locale']:<7}{r['channel']:<11}"
              f"{r['bytes']:>10,}{limit:>10}  {verdict:<6}{r['wallSec']:>7.1f}s")
    for s in skips:
        print(f"{s['spec']:<22}{s['locale']:<7}{s['channel']:<11}{'-':>10}{'-':>10}"
              f"  SKIP   （{s['skip']}）")
    print("-" * 78)


# ---------------------------------------------------------------- 主流程

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="e2e_matrix",
        description="端到端矩阵门：golden spec × 语言 × 冻结渠道的构建→打包→逐包质检；"
                    "--quick 为每日冒烟门（match3×en×规则库全部投放渠道，≤90 秒硬预算）",
    )
    parser.add_argument("--quick", action="store_true",
                        help="快速门：仅 golden-match3 × en × 冻结投放渠道（T2.4 起六渠道），预算 90s")
    parser.add_argument("--locales", default=None,
                        help="逗号分隔语言（缺省：quick=en，全量=en,zh（T2.5）；"
                             "ar 等其余 spec 声明语言仍可显式给，如 --locales en,ar）")
    parser.add_argument("--channels", default=None,
                        help="逗号分隔渠道（缺省：规则库全部投放渠道，preview 除外）")
    parser.add_argument("--out", default="artifacts/matrix",
                        help="输出根（缺省 artifacts/matrix，与 make 产物互不覆盖）")
    parser.add_argument("--budget-sec", type=float, default=None,
                        help="总墙钟预算秒（缺省：quick=90 硬门，全量=0 不设限只打印）")
    parser.add_argument("--jobs", type=int, default=0,
                        help="质检并行度（0=auto：包数与 4 取小；1=串行）")
    return parser


def run_matrix(args: argparse.Namespace) -> int:
    t0 = time.perf_counter()
    quick = bool(args.quick)
    locales = ([x.strip() for x in (args.locales or "").split(",") if x.strip()]
               or (["en"] if quick else ["en", "zh"]))
    rules = load_rules()
    channels = ([x.strip() for x in (args.channels or "").split(",") if x.strip()]
                or discover_channels(rules))
    specs = discover_specs(quick)
    budget = args.budget_sec if args.budget_sec is not None else (90.0 if quick else 0.0)
    jobs = args.jobs if args.jobs and args.jobs > 0 else 4

    out_root = Path(args.out)
    if not out_root.is_absolute():
        out_root = REPO_ROOT / out_root
    out_root.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    _log(f"端到端矩阵门 mode={'quick' if quick else 'full'} "
         f"specs={[s.name for s in specs]} locales={locales} channels={channels} "
         f"budget={'<=90s' if quick else ('<=%.0fs' % budget if budget else '不限')}")
    if quick and (specs != [SPECS_DIR / "golden-match3.json"] or locales != ["en"]):
        raise MatrixError("--quick 语义冻结为 match3×en×冻结渠道，不得与 --locales/--channels 混用", 2)

    cells = matrix_cells(specs, locales, channels)
    buildable = [c for c in cells if not c.get("skip")]
    if quick and len(buildable) != len(cells):
        raise MatrixError("--quick 出现 skip 格（golden-match3 必须可构建）", 1)

    # 阶段 A：spec 校验（M1 同源，校验是流水线第一道闸）
    for spec_path in dict.fromkeys(str(c["spec"]) for c in buildable):
        _run([_python(), "-m", "pfcore", "validate", spec_path], f"校验 {Path(spec_path).name}")

    builds = phase_build(cells, out_root)
    packed = phase_pack(cells, builds, out_root)
    results = phase_qa(cells, packed, builds, out_root, jobs, allow_retry=not quick)
    skips = [c for c in cells if c.get("skip")]

    wall = time.perf_counter() - t0
    print_table(results, skips)
    summary_path = write_summary(out_root, "quick" if quick else "full",
                                 results, skips, wall, budget or None)

    n_fail = sum(1 for r in results if r["status"] == "fail")
    n_retried = sum(1 for r in results if r.get("retried"))
    over = bool(budget) and wall > budget
    _log(f"总墙钟 {wall:.1f}s（预算 {'≤%.0fs' % budget if budget else '不限'}），"
         f"包 {len(results)}：pass {len(results) - n_fail} / fail {n_fail}，skip {len(skips)}"
         + (f"（其中 {n_retried} 格为单重试后过，见表内 * 号与 summary retried 字段）" if n_retried else ""))
    _log(f"summary.json：{summary_path.relative_to(REPO_ROOT)}")

    if n_fail:
        for r in results:
            for f in r["fails"]:
                print(f"[matrix] FAIL {r['spec']}×{r['locale']}×{r['channel']}：{f}", file=sys.stderr)
        print(f"[matrix] FAIL：矩阵 {n_fail} 包质检未过（质检是唯一裁判）", file=sys.stderr)
        return 1
    if over:
        print(f"[matrix] FAIL：总墙钟 {wall:.1f}s 超预算 {budget:.0f}s", file=sys.stderr)
        return 1
    _log(f"PASS：{'冒烟门' if quick else '全矩阵'}全绿"
         + ("且在预算内" if quick else "") + f"（exit 0）")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run_matrix(args)
    except MatrixError as exc:
        print(f"[matrix] FAIL：{exc}", file=sys.stderr)
        return exc.exit_code
    except subprocess.TimeoutExpired as exc:
        print(f"[matrix] FAIL：子进程超时（{exc}）", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
