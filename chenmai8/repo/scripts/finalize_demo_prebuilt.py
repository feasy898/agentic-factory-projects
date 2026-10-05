#!/usr/bin/env python3
"""demo-prebuilt 定稿流程：一条命令把演示兜底目录重建到「六包齐全、各自过质检」的定稿态。

对应规划 §8 演示兜底与 orchestrator.md §3：artifacts/demo-prebuilt/ 是演示日的
静态兜底（不依赖流水线现场跑通），但只有全绿产物才配进兜底目录（质检是裁判：
orchestrator.md 禁止事项——不许在质检 FAIL 时输出二维码或把包挪入交付目录）。

流程（整体重建，可重复执行；artifacts/ 不入库，本脚本就是该目录的可复现生成器）：
  1. 跑唯一统一命令 `pfcore make --spec specs-eval/golden-match3.json
     --locales en,zh --channels applovin,meta,mintegral`：validate → 模板构建
     （en+zh）→ 六渠道包 → make 自带质检（applovin/en）→ demo-prebuilt 整体
     落盘（六包拷贝 + summary/二维码/pipeline-report）。make 自身零 fail 才会
     产出兜底目录，失败即终止。
  2. 补齐其余五包的 qacore 质检（make 只质检首个 single-html 渠道 × 首语言）：
     applovin/zh、meta/{en,zh} 直接质检单 HTML；mintegral/{en,zh} 先解包 zip、
     按规则库入口（Template.html）质检。CHK10 判定输入（文案/素材）与
     pfcore/make.py 同源推导。报告落 artifacts 格子目录后拷入兜底目录对应包旁。
  3. 断言六包齐全且六份 index.report.json 零 fail；任一 fail → 整体删除
     demo-prebuilt（宁缺毋假绿）并 exit 1。
  4. 写 README.md：静态伺服命令（python -m http.server 即可扫码玩）、目录结构、
     六包质检结果表、再生成方式。

用法（纪律：python 一律 python/.venv/Scripts/python.exe，Node 22+）：
    python scripts/finalize_demo_prebuilt.py                # 全默认：定稿重建
    python scripts/finalize_demo_prebuilt.py --no-serve     # 不启动静态伺服

退出码：0 六包齐全且全绿；1 质检/断言失败（兜底目录已撤）；2 用法/环境错误。
本脚本自身零第三方依赖；子进程一律 venv 解释器与 PATH 中的 node；
不向 loopback/私网发起 HTTP 请求（伺服健康由 make 的 TCP 实测负责）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = REPO_ROOT / "python" / ".venv" / "Scripts" / "python.exe"
RULES_PATH = REPO_ROOT / "channel-rules" / "channel-rules.json"
DEFAULT_SPEC = REPO_ROOT / "specs-eval" / "golden-match3.json"
DEFAULT_OUT = REPO_ROOT / "artifacts"
DEFAULT_CHANNELS = "applovin,meta,mintegral"   # 规则库已冻结的三投放渠道
DEFAULT_LOCALES = "en,zh"                      # 演示双语言（en 主 + zh 现场）
EXTRACT_ROOT = REPO_ROOT / "tmp" / "finalize-extract"

# Windows 控制台默认非 UTF-8 代码页，固定本进程输出编码（同 pfcore 入口做法）。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


class FinalizeError(Exception):
    """带退出码语义的定稿失败：1=质检/断言失败，2=用法/环境错误。"""

    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code


def _log(msg: str) -> None:
    print(f"[finalize] {msg}", flush=True)


def _python() -> str:
    if VENV_PYTHON.is_file():
        return str(VENV_PYTHON)
    raise FinalizeError(f"未找到 venv 解释器：{VENV_PYTHON}（纪律要求 python/.venv/Scripts/python.exe）", 2)


def _sh(cmd: list[str], label: str, timeout_sec: float = 900, show: bool = False) -> str:
    """跑子进程（cwd 钉仓库根，UTF-8 环境），非零退出即抛失败；show 时实时透传。"""
    env = dict(os.environ, PYTHONUTF8="1")
    proc = subprocess.run(
        cmd, cwd=str(REPO_ROOT), encoding="utf-8", errors="replace",
        timeout=timeout_sec, env=env,
        stdout=None if show else subprocess.PIPE, stderr=None if show else subprocess.PIPE,
    )
    if proc.returncode != 0:
        tail = "\n".join(((proc.stderr or "") + (proc.stdout or "")).strip().splitlines()[-10:])
        raise FinalizeError(f"{label} 失败（exit {proc.returncode}）\n{tail or '(无输出)'}", 1)
    return proc.stdout or ""


# ---------------------------------------------------------------- CHK10 判定输入（与 pfcore/make.py 同源）

def required_texts_for(spec: dict, locale: str) -> list[str]:
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
    try:
        mf = json.loads(Path(str(preview_html) + ".assets.json").read_text(encoding="utf-8"))
        return [str(s.get("spriteKey")) for s in (mf.get("sprites") or []) if s.get("spriteKey")]
    except (OSError, json.JSONDecodeError, AttributeError):
        return []


# ---------------------------------------------------------------- 步骤 2：补齐其余五包质检

def qa_package(spec_path: Path, project: str, locale: str, channel: str,
               cell_dir: Path, artifact: Path, fmt: str, entry: str) -> Path:
    """对单包跑 qacore run --autoplay，报告写到包旁 index.report.json 并返回路径。

    zip 包先解包到 tmp/（qacore 只收单 HTML），按规则库入口质检。"""
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    qc = spec.get("qc") or {}
    qa_target = artifact
    if fmt == "zip":
        extract_dir = EXTRACT_ROOT / f"{project}-{locale}-{channel}"
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True)
        with zipfile.ZipFile(artifact) as zf:
            zf.extractall(extract_dir)
        qa_target = extract_dir / entry
        if not qa_target.is_file():
            hits = sorted(extract_dir.rglob("*.html"))
            if not hits:
                raise FinalizeError(f"zip {artifact.name} 内无 HTML 可质检", 1)
            qa_target = hits[0]

    report_path = cell_dir / "index.report.json"
    sprites = required_sprites_for(DEFAULT_OUT / "preview" / f"{project}-{locale}.html")
    cmd = [_python(), "-m", "qacore", "run", str(qa_target),
           "--channel", channel, "--autoplay",
           "--max-load-sec", str(qc.get("maxLoadSec", 2.0)),
           "--autoplay-timeout", str(qc.get("autoplayTimeoutSec", 45.0)),
           "--out", str(report_path)]
    for t in required_texts_for(spec, locale):
        cmd += ["--require-text", t]
    for k in sprites:
        cmd += ["--require-sprite", k]
    _sh(cmd, f"质检 {channel}/{locale}", timeout_sec=300)
    return report_path


def qa_fails(report_path: Path) -> list[str]:
    """读质检报告，返回 fail 检查项清单（空=零 fail）。"""
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"报告不可读：{exc}"]
    return [f"{c.get('id')}: {c.get('detail', '')}"
            for c in (report.get("checks") or []) if c.get("status") == "fail"]


# ---------------------------------------------------------------- 步骤 4：README

def render_readme(ctx: dict) -> str:
    rows = "".join(
        f"| {p['channel']} | {p['locale']} | {p['format']} | {p['artifact_name']} "
        f"| {p['bytes']:,} B / {p['maxBytes']:,} B | "
        f"[报告]({p['rel_dir']}/index.report.json)（零 fail，win={p['endWin']}） |\n"
        for p in ctx["packages"])
    return f"""# 演示兜底定稿产物（demo-prebuilt）

> 生成：{ctx["generated_at"]} · 生成器：`python scripts/finalize_demo_prebuilt.py`（整体重建，可重复）
> 来源 spec：`{ctx["spec_rel"]}`（match3）× 语言 {{{ctx["locales_str"]}}} × 渠道 {{{ctx["channels_str"]}}} = 六包
> 仓库版本：commit `{ctx["commit"]}` · 规则库 rulesVersion={ctx["rulesVersion"]}

**六包全部通过 qacore 自动质检**（`--autoplay` 真实指针事件试玩到结束页，
各包目录内 `index.report.json` 零 fail；质检是唯一裁判，任一 fail 本目录会被
生成器整体撤除）。

## 静态伺服（手机扫码即玩）

```bash
cd <仓库根>/artifacts/demo-prebuilt
python -m http.server {ctx["port"]} --bind 0.0.0.0
```

手机连**同一局域网 Wi-Fi**，扫本目录 `qr.png`（编码的是构建机局域网地址
`{ctx["preview_url"]}`），或直接打开：

- 英文预览：`http://<本机局域网IP>:{ctx["port"]}/preview/{ctx["preview_en"]}`
- 中文预览：`http://<本机局域网IP>:{ctx["port"]}/preview/{ctx["preview_zh"]}`
- 兜底汇总页（本页同级）：`http://<本机局域网IP>:{ctx["port"]}/index.html`

说明：`qr.png` 由构建时自动探测的局域网 IP 生成；换机器/换端口伺服后二维码
不再对应，直接用上面的相对路径手开即可。`python -m http.server` 缺省端口为
8000，用 8000 时把 URL 里的端口换成 8000。打不开时放行防火墙，或改用手机热点。

## 目录结构

```
demo-prebuilt/
├── index.html / summary.html      汇总页（双名同内容，相对链接零外链）
├── qr.png                         预览二维码（预览 URL）
├── pipeline-report.json           make 流水线运行报告（计时/产物清单）
├── README.md                      本文件
├── preview/                       真实可玩单 HTML（{ctx["preview_en"]} / {ctx["preview_zh"]}）
└── channels/<渠道>/<语言>/        六个渠道包 + pack-manifest.json + index.report.json
```

## 六包清单与质检结果

| 渠道 | 语言 | 形态 | 产物 | 字节 / 上限 | 质检 |
|---|---|---|---|---|---|
{rows}
渠道包形态：{ctx["single_html_channels"]} 为单 HTML 全内联（零外链）；
{ctx["zip_channels"]} 为 zip（规则库入口 `{ctx["zip_entry"]}` + build.js 空占位，
质检按解包后入口 HTML 执行）。CHK02/CHK06 为 qacore 未实装项，报告里记 skip
不算通过也不算失败；其余检查项逐包 pass。

## 再生成

```bash
python scripts/finalize_demo_prebuilt.py
```

make 整体重建本目录（先删后建）；make 自带质检（applovin/en）不过即不出目录，
其余五包由本脚本补质检，任一 fail 整体撤除。`artifacts/` 不入库（.gitignore），
演示日前跑一遍本命令即得定稿态。
"""


# ---------------------------------------------------------------- 主流程

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="finalize_demo_prebuilt",
        description="demo-prebuilt 定稿流程：make 重建六包（match3×en,zh×三渠道）+ "
                    "逐包补齐 qacore 质检 + README（静态伺服说明）；任一 fail 撤除兜底目录",
    )
    parser.add_argument("--spec", default=str(DEFAULT_SPEC), help="定稿 spec（缺省 golden-match3）")
    parser.add_argument("--locales", default=DEFAULT_LOCALES, help=f"语言（缺省 {DEFAULT_LOCALES}）")
    parser.add_argument("--channels", default=DEFAULT_CHANNELS, help=f"渠道（缺省 {DEFAULT_CHANNELS}）")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="make --out 输出根（缺省 artifacts）")
    parser.add_argument("--serve-port", type=int, default=8618, help="兜底伺服端口（透传 make）")
    parser.add_argument("--no-serve", action="store_true", help="不启动/复用静态伺服（透传 make）")
    return parser


def run_finalize(args: argparse.Namespace) -> int:
    spec_path = Path(args.spec)
    if not spec_path.is_absolute():
        spec_path = REPO_ROOT / spec_path
    if not spec_path.is_file():
        raise FinalizeError(f"spec 不存在：{spec_path}", 2)
    _python()  # 纪律：子进程一律 venv 解释器（缺失即抛用法错误）
    if shutil.which("node") is None:
        raise FinalizeError("未找到 node（模板构建/打包需要 Node.js）", 2)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    project = str((spec.get("meta") or {}).get("projectId") or "playable")
    locales = [x.strip() for x in args.locales.split(",") if x.strip()]
    channels = [x.strip() for x in args.channels.split(",") if x.strip()]
    out_root = Path(args.out)
    if not out_root.is_absolute():
        out_root = REPO_ROOT / out_root
    demo_dir = out_root / "demo-prebuilt"
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    rules_channels = rules.get("channels") or {}

    print("=" * 72)
    _log(f"demo-prebuilt 定稿开始：{spec_path.name} × {locales} × {channels}")

    # ---- 步骤 1：唯一统一命令 pfcore make（整体重建；质检不过不出兜底目录）----
    # 陈旧产物防线：先清掉本项目上一次运行的 dist/渠道包/预览（demo-prebuilt 由
    # make 自删自建），保证定稿目录里每一件都是本次 make 的新产物，杜绝拿旧包
    # 补质检的假定稿（本脚本的 zh 包曾因此踩过：make 未带 --locales 只建 en，
    # zh 质检落在上一轮残留包上）。
    project_dir = out_root / project
    if project_dir.exists():
        shutil.rmtree(project_dir)
        _log(f"已清理上次运行产物：{project_dir.relative_to(REPO_ROOT)}")
    if EXTRACT_ROOT.exists():
        shutil.rmtree(EXTRACT_ROOT)

    cmd = [_python(), "-m", "pfcore", "make",
           "--spec", str(spec_path), "--out", str(out_root),
           "--locales", ",".join(locales), "--channels", ",".join(channels),
           "--serve-port", str(args.serve_port)]
    if args.no_serve:
        cmd += ["--no-serve"]
    _log("统一命令：" + " ".join(cmd))
    _sh(cmd, "pfcore make", timeout_sec=900, show=True)

    # ---- 步骤 2：补齐其余五包质检（make 只质检首个 single-html × 首语言）----
    pkg_rows: list[dict] = []
    failures: list[str] = []
    for channel in channels:
        fmt = ((rules_channels.get(channel) or {}).get("package") or {}).get("format") \
            or "single-html"
        entry = str(((rules_channels.get(channel) or {}).get("package") or {}).get("entry")
                    or "Template.html")
        max_bytes = (rules_channels.get(channel) or {}).get("maxBytes")
        for locale in locales:
            cell_dir = out_root / project / channel / locale
            artifact = (cell_dir / f"{project}-{locale}.zip") if fmt == "zip" \
                else (cell_dir / "index.html")
            if not artifact.is_file():
                raise FinalizeError(f"make 产物缺失：{artifact}", 1)
            report_path = cell_dir / "index.report.json"
            if not report_path.is_file():  # make 已质检的包不重跑
                _log(f"补质检 {channel}/{locale}（{fmt}）…")
                report_path = qa_package(spec_path, project, locale, channel,
                                         cell_dir, artifact, fmt, entry)
            fails = qa_fails(report_path)
            end_win = None
            try:
                end_win = (json.loads(report_path.read_text(encoding="utf-8"))
                           .get("pf") or {}).get("endWin")
            except (OSError, json.JSONDecodeError):
                pass
            if fails:
                failures += [f"{channel}/{locale}: {f}" for f in fails]

            # 报告 + 双视口截图拷入兜底目录对应包旁（make 只拷了它质检的那份）
            demo_cell = demo_dir / "channels" / channel / locale
            demo_cell.mkdir(parents=True, exist_ok=True)
            for name in ("index.report.json", "index.report.png", "index.report-landscape.png"):
                src = cell_dir / name
                if src.is_file():
                    shutil.copyfile(src, demo_cell / name)

            pkg_rows.append({
                "channel": channel, "locale": locale, "format": fmt,
                "artifact_name": artifact.name, "bytes": artifact.stat().st_size,
                "maxBytes": int(max_bytes) if isinstance(max_bytes, int) else 0,
                "rel_dir": f"channels/{channel}/{locale}",
                "fails": fails, "endWin": end_win,
            })
            _log(f"{channel}/{locale}：{artifact.name} {artifact.stat().st_size:,}B，"
                 f"质检 {'零 fail' if not fails else 'FAIL ' + str(fails)}")

    # ---- 步骤 3：断言六包齐全且兜底目录内报告零 fail；否则整体撤除 ----------
    for row in pkg_rows:
        demo_cell = demo_dir / "channels" / row["channel"] / row["locale"]
        if not demo_cell.is_dir() or not any(demo_cell.iterdir()):
            failures.append(f"兜底目录缺包：channels/{row['channel']}/{row['locale']}")
            continue
        fails = qa_fails(demo_cell / "index.report.json")
        if fails:
            failures += [f"兜底 {row['channel']}/{row['locale']}: {f}" for f in fails]

    if failures:
        if demo_dir.exists():
            shutil.rmtree(demo_dir)
            _log("质检是裁判：兜底目录已整体撤除（宁缺毋假绿）")
        raise FinalizeError(f"定稿断言 {len(failures)} 项失败：\n  - "
                            + "\n  - ".join(failures))

    # ---- 步骤 4：README（静态伺服说明 + 六包结果表）-------------------------
    preview_en = f"{project}-{locales[0]}.html"
    zh_locale = "zh" if "zh" in locales else locales[-1]
    preview_zh = f"{project}-{zh_locale}.html"
    zip_entry = next(
        (((rules_channels.get(c) or {}).get("package") or {}).get("entry") or "Template.html")
        for c in channels
        if next((r for r in pkg_rows if r["channel"] == c), {}).get("format") == "zip")
    try:
        commit = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True, timeout=15).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        commit = "unknown"
    preview_url = "?"
    try:
        pr = json.loads((demo_dir / "pipeline-report.json").read_text(encoding="utf-8"))
        preview_url = (pr.get("preview") or {}).get("url") or "?"
    except (OSError, json.JSONDecodeError):
        pass
    readme = render_readme({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "spec_rel": spec_path.relative_to(REPO_ROOT).as_posix(),
        "commit": commit, "rulesVersion": rules.get("rulesVersion"),
        "locales_str": ",".join(locales), "channels_str": ",".join(channels),
        "port": args.serve_port, "preview_url": preview_url,
        "preview_en": preview_en, "preview_zh": preview_zh,
        "single_html_channels": "、".join(c for c in channels
                                          if next((r for r in pkg_rows
                                                   if r["channel"] == c), {}).get("format") == "single-html"),
        "zip_channels": "、".join(c for c in channels
                                  if next((r for r in pkg_rows
                                           if r["channel"] == c), {}).get("format") == "zip"),
        "zip_entry": zip_entry, "packages": pkg_rows,
    })
    (demo_dir / "README.md").write_text(readme, encoding="utf-8")

    print("-" * 72)
    for row in pkg_rows:
        _log(f"  {row['channel']}/{row['locale']}: {row['artifact_name']} "
             f"{row['bytes']:,}B — 零 fail（win={row['endWin']}）")
    _log(f"README：{demo_dir / 'README.md'}")
    _log(f"PASS：六包齐全且各自过 qacore（exit 0）；伺服见 README"
         f"（python -m http.server {args.serve_port} --bind 0.0.0.0）")
    print("=" * 72)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run_finalize(args)
    except FinalizeError as exc:
        print(f"[finalize] FAIL：{exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    sys.exit(main())
