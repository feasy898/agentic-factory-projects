"""演示走查（反馈行动 4）：把五分钟演示脚本的「改 spec → 一条命令 → 全产物落盘」自动化。

对应 _reviews/playable-ads-holistic.md §一 的五分钟脚本（0:40–2:30 段）：
  1. 打开准备好的演示 spec（--base-spec，缺省 specs-eval/demo-zh.json），
     当场只改两处：标题改成评委给的中文（--judge-title），seed 加一。
     —— 改动写入 <out>/walkthrough/spec-live.json，基线 spec 永不被改写
        （每次走查都从同一份已入库基线出发，可重复；artifacts/ 不入库）。
  2. 跑唯一统一命令 `python -m pfcore make`（流水线契约 §1 冻结名），
     输出实时透传到本控制台（演示时屏幕上就是这一屏 + 计时）。
  3. 断言落盘（契约 §3.4）：预览 HTML+素材清单、三渠道包
     （applovin/meta 单 HTML、mintegral zip，各带 pack-manifest）、qacore 报告
     （无 fail、CHK10 pass、pf:end win、双视口截图）、demo-prebuilt 兜底目录
     （汇总页/pipeline-report/二维码/预览拷贝/渠道包拷贝）、伺服端口 TCP 实测在听。
     并验证「评委输入看得见」：新标题与新 seed 确实出现在预览 HTML 与质检报告里。
  4. 打印墙钟计时：spec 改完 → 全产物断言通过的走查总墙钟，以及 make 自报的
     makeWallSec / specModifiedToQrScannableSec（契约 §5 计时口径）。
     预算：--max-wall-sec（缺省 180）超时即 exit 1；≤90s 打印「达成反馈理想值」。

用法（纪律：python 一律用 python/.venv/Scripts/python.exe，Node 22）：
    python scripts/demo_walkthrough.py                       # 全默认：演示全路径
    python scripts/demo_walkthrough.py --judge-title "消消乐大挑战" --no-serve

产物固化：以缺省 --out artifacts 跑完，make 整体重建的 artifacts/demo-prebuilt/
即为演示兜底最终版（每次运行整体重建，契约 §3.4；artifacts/ 不入库，
本脚本就是该目录的可复现生成器）。

退出码：0 全部通过；1 走查失败（make 失败 / 断言失败 / 超预算）；2 用法或环境错误。
本脚本不向 loopback/私网发起 HTTP 请求（伺服健康只做 TCP connect，同 make 纪律）。
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = REPO_ROOT / "python" / ".venv" / "Scripts" / "python.exe"
DEFAULT_BASE_SPEC = REPO_ROOT / "specs-eval" / "demo-zh.json"
DEFAULT_JUDGE_TITLE = "果冻消消乐（现场命题）"  # 模拟评委给的中文标题（≠基线标题，改动可验证）
DEFAULT_OUT = REPO_ROOT / "artifacts"
DEFAULT_CHANNELS = "applovin,meta,mintegral"  # 规则库已冻结的三投放渠道
ZIP_CHANNELS = {"mintegral"}  # zip 渠道产物名 <project>-<locale>.zip，其余 single-html

# Windows 控制台默认非 UTF-8 代码页，固定本进程输出编码（同 pfcore 入口做法）。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


class WalkError(Exception):
    """带退出码语义的走查失败：1=判定失败，2=用法/环境错误。"""

    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code


def _log(msg: str) -> None:
    print(f"[walk] {msg}", flush=True)


def _fail(msg: str, exit_code: int = 1) -> WalkError:
    return WalkError(msg, exit_code)


def _check(checks: list[str], ok: bool, label: str, detail: str = "") -> bool:
    mark = "PASS" if ok else "FAIL"
    suffix = f"（{detail}）" if detail else ""
    print(f"[walk]   [{mark}] {label}{suffix}", flush=True)
    if not ok:
        checks.append(label)
    return ok


def _read_bytes_le(path: Path, min_size: int = 1) -> bytes:
    data = path.read_bytes()
    if len(data) < min_size:
        raise _fail(f"产物为空或过小：{path}（{len(data)} 字节）")
    return data


def _python() -> str:
    """纪律：一律用仓库 venv 解释器（python/.venv/Scripts/python.exe）。"""
    if VENV_PYTHON.is_file():
        return str(VENV_PYTHON)
    raise _fail(f"未找到 venv 解释器：{VENV_PYTHON}（纪律要求 python/.venv/Scripts/python.exe）", 2)


# ---------------------------------------------------------------- 步骤 1：改 spec

def apply_judge_edits(base_spec: Path, judge_title: str, out_root: Path) -> tuple[Path, dict]:
    """模拟评委两处改动：中文标题 + seed 加一。返回 (改后 spec 路径, 改动摘要)。"""
    try:
        spec = json.loads(base_spec.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _fail(f"基线 spec 不可读：{base_spec}（{exc}）", 2) from exc
    meta = spec.get("meta") or {}
    old_title = meta.get("title")
    old_seed = meta.get("seed")
    if not isinstance(old_title, str) or not old_title:
        raise _fail(f"基线 spec 缺 meta.title：{base_spec}", 2)
    if not isinstance(old_seed, int):
        raise _fail(f"基线 spec 缺整数 meta.seed：{base_spec}", 2)

    meta["title"] = judge_title
    meta["seed"] = old_seed + 1
    spec["meta"] = meta

    spec_dir = out_root / "walkthrough"
    spec_dir.mkdir(parents=True, exist_ok=True)
    live_spec = spec_dir / f"{meta.get('projectId', 'demo')}-live.json"
    live_spec.write_text(
        json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    edits = {"old_title": old_title, "new_title": judge_title,
             "old_seed": old_seed, "new_seed": old_seed + 1, "path": live_spec}
    return live_spec, edits


# ---------------------------------------------------------------- 步骤 3：断言落盘

def assert_artifacts(out_root: Path, project: str, locale: str,
                     channels: list[str], live_spec: Path, edits: dict,
                     serve_expected: bool) -> list[str]:
    """契约 §3.4 产物逐项断言；返回失败清单（空=全过）。"""
    checks: list[str] = []
    project_dir = out_root / project
    demo_dir = out_root / "demo-prebuilt"

    # -- 预览（真实可玩单 HTML + 构建素材清单旁车） -----------------------
    preview_html = out_root / "preview" / f"{project}-{locale}.html"
    _check(checks, preview_html.is_file(), f"预览 HTML 落盘 preview/{preview_html.name}")
    if preview_html.is_file():
        html_text = _read_bytes_le(preview_html, 100_000).decode("utf-8", errors="replace")
        _check(checks, edits["new_title"] in html_text,
               "评委新标题已进预览包", edits["new_title"])
        _check(checks, str(edits["new_seed"]) in html_text,
               "seed+1 已进预览包", f"seed={edits['new_seed']}")
    manifest = Path(f"{preview_html}.assets.json")
    if _check(checks, manifest.is_file(), "构建素材清单旁车落盘（.assets.json）"):
        try:
            mf = json.loads(manifest.read_text(encoding="utf-8"))
            _check(checks, isinstance(mf.get("sprites"), list), "素材清单含 sprites 字段")
        except json.JSONDecodeError as exc:
            _check(checks, False, "素材清单可解析", str(exc))

    # -- 三渠道包（applovin/meta 单 HTML、mintegral zip，各带 pack-manifest） --
    for channel in channels:
        ch_dir = project_dir / channel / locale
        if channel in ZIP_CHANNELS:
            artifact = ch_dir / f"{project}-{locale}.zip"
        else:
            artifact = ch_dir / "index.html"
        _check(checks, artifact.is_file(),
               f"渠道包 {channel}/{locale}", f"{artifact.name}")
        if artifact.is_file():
            _read_bytes_le(artifact, 512)
        _check(checks, (ch_dir / "pack-manifest.json").is_file(),
               f"渠道包旁车 {channel}/pack-manifest.json")

    # -- qacore 报告（首个 single-html 渠道 × 首语言） ---------------------
    qa_channel = next((c for c in channels if c not in ZIP_CHANNELS), None)
    if qa_channel is None:
        _check(checks, False, "存在 single-html 质检渠道")
        return checks
    report_path = project_dir / qa_channel / locale / "index.report.json"
    if not _check(checks, report_path.is_file(), f"质检报告落盘 {qa_channel}/{locale}/index.report.json"):
        return checks
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _check(checks, False, "质检报告可解析", str(exc))
        return checks
    checks_list = report.get("checks") or []
    n_fail = sum(1 for c in checks_list if c.get("status") == "fail")
    _check(checks, n_fail == 0, "质检零 fail", f"{len(checks_list)} 项")
    chk10 = next((c for c in checks_list if c.get("id") == "CHK10"), None)
    _check(checks, chk10 is not None and chk10.get("status") == "pass",
           "CHK10（文案与素材上屏）pass")
    pf = report.get("pf") or {}
    _check(checks, pf.get("endWin") is True, "自动试玩真实玩到胜利结束页（pf.endWin）",
           f"pf:end {pf.get('endMs')}ms")
    required = (report.get("facts") or {}).get("required_texts") or []
    _check(checks, edits["new_title"] in required, "评委新标题进质检判定输入（CHK10 --require-text）")
    shots = [report_path.with_name(n) for n in
             ("index.report.png", "index.report-landscape.png")]
    _check(checks, all(s.is_file() for s in shots), "双视口截图落盘",
           "index.report.png / -landscape.png")

    # -- demo-prebuilt 兜底目录（演示日静态兜底，整体重建） ----------------
    for name in ("index.html", "pipeline-report.json", "qr.png"):
        _check(checks, (demo_dir / name).is_file(), f"demo-prebuilt/{name} 落盘")
    qr = demo_dir / "qr.png"
    if qr.is_file():
        _check(checks, _read_bytes_le(qr, 100)[:8] == b"\x89PNG\r\n\x1a\n", "qr.png 为真实 PNG")
    _check(checks, (demo_dir / "preview" / preview_html.name).is_file(),
           "demo-prebuilt/preview 预览拷贝")
    for channel in channels:
        dst = demo_dir / "channels" / channel / locale
        _check(checks, dst.is_dir() and any(dst.iterdir()),
               f"demo-prebuilt/channels/{channel}/{locale} 整目录拷贝")
    pipeline_report = demo_dir / "pipeline-report.json"
    if pipeline_report.is_file():
        try:
            pr = json.loads(pipeline_report.read_text(encoding="utf-8"))
            _check(checks, Path(pr.get("spec", "")) == live_spec,
                   "pipeline-report 指向本次改后 spec")
        except json.JSONDecodeError as exc:
            _check(checks, False, "pipeline-report.json 可解析", str(exc))

    # -- 伺服状态：二维码「可扫」的端口实测（TCP-only，同 make 纪律） -------
    if serve_expected:
        state_file = out_root / ".demo-serve.json"
        port = 0
        if state_file.is_file():
            try:
                port = int(json.loads(state_file.read_text(encoding="utf-8")).get("port", 0))
            except (json.JSONDecodeError, OSError, ValueError):
                pass
        listening = port > 0 and _port_listening(port)
        _check(checks, listening, "静态伺服端口 TCP 实测在听（二维码可扫前提）", f"port={port}")
    return checks


def _port_listening(port: int, timeout: float = 0.4) -> bool:
    """TCP connect 探测端口是否在听（不发 HTTP 请求，同 pfcore.make 纪律）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex(("127.0.0.1", port)) == 0


# ---------------------------------------------------------------- 主流程

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="demo_walkthrough",
        description="五分钟演示脚本自动化：改 spec（中文标题+seed+1）→ pfcore make → 断言全产物落盘 → 打印墙钟计时",
    )
    parser.add_argument("--base-spec", default=str(DEFAULT_BASE_SPEC),
                        help=f"基线演示 spec（缺省 {DEFAULT_BASE_SPEC.relative_to(REPO_ROOT).as_posix()}，只读不改）")
    parser.add_argument("--judge-title", default=DEFAULT_JUDGE_TITLE,
                        help=f"评委给的中文标题（缺省 {DEFAULT_JUDGE_TITLE!r}）")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="make --out 输出根（缺省 artifacts/）")
    parser.add_argument("--locales", default=None,
                        help="逗号分隔语言（缺省取 spec i18n.defaultLocale）")
    parser.add_argument("--channels", default=DEFAULT_CHANNELS,
                        help=f"逗号分隔渠道（缺省 {DEFAULT_CHANNELS}）")
    parser.add_argument("--serve-port", type=int, default=8618, help="兜底伺服端口（透传 make）")
    parser.add_argument("--serve-host", default=None, help="二维码指向 IP（透传 make，缺省自动探测）")
    parser.add_argument("--no-serve", action="store_true", help="不启动/复用伺服（透传 make）")
    parser.add_argument("--max-wall-sec", type=float, default=180.0,
                        help="走查总墙钟预算秒（缺省 180，超时 exit 1；反馈理想值 90）")
    return parser


def run_walkthrough(args: argparse.Namespace) -> int:
    t0 = time.perf_counter()
    base_spec = Path(args.base_spec)
    if not base_spec.is_absolute():
        base_spec = REPO_ROOT / base_spec
    if not base_spec.is_file():
        raise _fail(f"基线 spec 不存在：{base_spec}", 2)
    out_root = Path(args.out)
    if not out_root.is_absolute():
        out_root = REPO_ROOT / out_root
    channels = [c.strip() for c in args.channels.split(",") if c.strip()]
    if not channels:
        raise _fail("--channels 为空", 2)

    print("=" * 72)
    _log("演示走查开始（五分钟脚本 0:40–2:30 段自动化）")
    _log(f"基线 spec：{base_spec.relative_to(REPO_ROOT).as_posix()}（只读）")

    # ---- 步骤 1：当场只改两处：标题 → 评委中文，seed +1 ------------------
    t_edit0 = time.perf_counter()
    live_spec, edits = apply_judge_edits(base_spec, args.judge_title, out_root)
    edit_sec = time.perf_counter() - t_edit0
    _log(f"改动①标题：{edits['old_title']!r} → {edits['new_title']!r}")
    _log(f"改动②seed：{edits['old_seed']} → {edits['new_seed']}（+1）")
    _log(f"改后 spec：{edits['path'].relative_to(REPO_ROOT).as_posix()}（{edit_sec:.2f}s）")

    # ---- 步骤 2：唯一统一命令 pfcore make（输出实时透传） ----------------
    spec = json.loads(live_spec.read_text(encoding="utf-8"))
    project = str((spec.get("meta") or {}).get("projectId") or "playable")
    locale = (str(args.locales).split(",")[0].strip() if args.locales
              else str((spec.get("i18n") or {}).get("defaultLocale") or "en"))

    cmd = [_python(), "-m", "pfcore", "make",
           "--spec", str(live_spec), "--out", str(out_root),
           "--channels", args.channels, "--serve-port", str(args.serve_port)]
    if args.locales:
        cmd += ["--locales", args.locales]
    if args.serve_host:
        cmd += ["--serve-host", args.serve_host]
    if args.no_serve:
        cmd += ["--no-serve"]
    _log("统一命令：" + " ".join(os.path.relpath(c, REPO_ROOT) if c.startswith(str(REPO_ROOT)) else c
                                 for c in cmd))
    env = dict(os.environ, PYTHONUTF8="1")
    t_make0 = time.perf_counter()
    try:
        proc = subprocess.run(cmd, cwd=REPO_ROOT, env=env, timeout=max(args.max_wall_sec * 3, 600))
    except subprocess.TimeoutExpired as exc:
        raise _fail(f"pfcore make 超时（>{exc.timeout:.0f}s）") from exc
    make_sec = time.perf_counter() - t_make0
    if proc.returncode != 0:
        raise _fail(f"pfcore make 失败（exit {proc.returncode}）：全流水线中断，"
                    "不产出二维码与 demo-prebuilt（质检是裁判）")
    _log(f"pfcore make exit 0（子进程墙钟 {make_sec:.1f}s）")

    # ---- 步骤 3：断言全部产物落盘 + 步骤 4：计时 -------------------------
    failures = assert_artifacts(out_root, project, locale, channels, live_spec, edits,
                                serve_expected=not args.no_serve)
    total_sec = time.perf_counter() - t0

    pr_path = out_root / "demo-prebuilt" / "pipeline-report.json"
    make_wall_sec = spec_to_qr_sec = None
    if pr_path.is_file():
        try:
            timings = (json.loads(pr_path.read_text(encoding="utf-8")) or {}).get("timings") or {}
            make_wall_sec = timings.get("makeWallSec")
            spec_to_qr_sec = timings.get("specModifiedToQrScannableSec")
        except json.JSONDecodeError:
            pass

    print("-" * 72)
    _log("计时（口径见 docs/assets/specs/pipeline-contract.md §5）")
    _log(f"  spec 改动（评委两处）        ：{edit_sec:.2f}s")
    if make_wall_sec is not None:
        _log(f"  make 墙钟（入口→二维码可扫）：{make_wall_sec:.1f}s（make 自报）")
    if spec_to_qr_sec is not None:
        _log(f"  spec 改完→二维码可扫（mtime 口径）：{spec_to_qr_sec:.1f}s（make 自报）")
    _log(f"  走查总墙钟（本脚本 t0→断言全过）：{total_sec:.1f}s")
    _log(f"预算判定：≤{args.max_wall_sec:.0f}s 硬预算"
          f"{'达标' if total_sec <= args.max_wall_sec else '超时'}；"
          f"反馈理想值 90s{'达成' if total_sec <= 90 else '未达'}")
    print("=" * 72)

    if failures:
        raise _fail(f"走查断言 {len(failures)} 项失败：\n  - " + "\n  - ".join(failures))
    if total_sec > args.max_wall_sec:
        raise _fail(f"走查总墙钟 {total_sec:.1f}s 超预算 {args.max_wall_sec:.0f}s")
    _log(f"PASS：{len(channels)} 渠道包 + 预览 + 质检报告 + 二维码 + demo-prebuilt 全部落盘，"
         f"exit 0（兜底目录 {os.path.relpath(out_root / 'demo-prebuilt', REPO_ROOT)} 即演示最终版）")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run_walkthrough(args)
    except WalkError as exc:
        print(f"[walk] FAIL：{exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    sys.exit(main())
