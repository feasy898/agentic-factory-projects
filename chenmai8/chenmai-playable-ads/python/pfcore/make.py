"""pfcore make —— 全流水线编排（M9，反馈行动 1）。

流程（pipeline-contract.md §1 冻结名 ``make``；墙钟口径 §5）：
  validate → 模板构建（真实可玩单 HTML）→ 用该 HTML 打渠道包（applovin/meta/mintegral）
  → 对首个 single-html 渠道跑 qacore（--autoplay，质检是裁判）
  → summary.html + 二维码 + 预览链接 + 墙钟计时 → artifacts/demo-prebuilt/ 兜底目录

设计约束：
- 质检不过就没有二维码、没有兜底目录（演示红线：宁可失败不可假绿）。
- 二维码内容 = LAN 可达的预览 HTML http URL（127.0.0.1 手机扫不出，契约 §5）。
- 本模块不发起任何对 loopback/私网地址的 HTTP 请求（防 SSRF 纪律）：伺服器健康
  检查只做 TCP connect，不 fetch URL。
- 计时打印两个口径：make 墙钟（编排入口→二维码可扫）与 spec 修改完成→二维码可扫
  （以 spec 文件 mtime 为"改完 spec"的客观代理，契约 §5 计时口径）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_PATH = REPO_ROOT / "channel-rules" / "channel-rules.json"
PACKAGER_BIN = REPO_ROOT / "packages" / "packager" / "bin.mjs"

# spec.game.template → 模板构建脚本（能产出"真实可玩 HTML"的模板才可入表）
TEMPLATE_BUILDERS: dict[str, Path] = {
    "match3": REPO_ROOT / "packages" / "templates" / "tmpl-match3" / "build.mjs",
}

DEFAULT_SERVE_PORT = 8618
SERVE_STATE_NAME = ".demo-serve.json"  # 伺服状态存 <out>/ 下（demo-prebuilt 每次重建）
_WIN_DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


class MakeError(Exception):
    """带退出码语义的编排失败：exit_code ∈ {1 判定失败, 2 用法/环境错误}。"""

    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code


def _log(msg: str) -> None:
    print(f"[make] {msg}", flush=True)


def _run(cmd: list[str], label: str, timeout_sec: float = 600) -> str:
    """跑子进程，失败时抛 MakeError（exit 1，附 stderr 尾部）。"""
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout_sec,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-8:])
        raise MakeError(f"{label} 失败（exit {proc.returncode}）：\n{tail or '(无输出)'}")
    return proc.stdout


def _load_rules() -> dict:
    try:
        return json.loads(RULES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MakeError(f"规则库不可读：{RULES_PATH}（{exc}）", 2) from exc


# ---------------------------------------------------------------- 伺服（TCP-only 健康检查）

def _port_listening(port: int, timeout: float = 0.4) -> bool:
    """TCP connect 探测本机端口是否在听（不发 HTTP 请求）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _spawn_static_server(root: Path, port: int) -> int:
    """以分离子进程启动 `python -m http.server`（0.0.0.0，随本进程退出存活）。"""
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = _WIN_DETACHED
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port),
         "--bind", "0.0.0.0", "--directory", str(root)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        close_fds=True, **kwargs,
    )
    return proc.pid


def ensure_server(out_root: Path, demo_dir: Path, preferred_port: int) -> tuple[int, bool]:
    """确保 demo_dir 正被静态伺服，返回 (port, reused)。

    复用判定依据 <out>/.demo-serve.json：端口 TCP 可连即视为上次由 make 启动的
    伺服器仍在（同一 root，http.server 按请求读盘，直接吃到本次重建后的文件）。
    该假设写入状态文件注释并在输出中显式提示；端口被未知进程占用时不复用，
    向后顺延找空闲口。
    """
    state_file = out_root / SERVE_STATE_NAME
    if state_file.is_file():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            port = int(state.get("port", 0))
            if port > 0 and _port_listening(port):
                return port, True
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    port = preferred_port
    for _ in range(20):
        if not _port_listening(port):
            break
        port += 1
    else:
        raise MakeError(f"端口 {preferred_port}~{port} 均被占用，无法启动静态伺服（--serve-port 换口）", 2)
    pid = _spawn_static_server(demo_dir, port)
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if _port_listening(port):
            state_file.write_text(json.dumps(
                {"port": port, "pid": pid, "root": str(demo_dir),
                 "started": datetime.now().isoformat(timespec="seconds")},
                ensure_ascii=False) + "\n", encoding="utf-8")
            return port, False
        time.sleep(0.25)
    raise MakeError(f"静态伺服器启动后端口 {port} 未进入监听（防火墙或权限问题？）", 1)


def _addr_tier(ip: str) -> int:
    """地址段优先级：手机大概率直达的段在前。数值越小越优先。

    0=192.168 典型局域网；1=10/8；2=172.16-31；3=100.64/10（CGNAT/tailnet，
    装 tailnet 的设备可达）；5=其他；9=198.18.0.0/15（RFC2544 基准段，
    常见于 Clash/VPN TUN 虚拟网卡，局域网手机不可达）。"""
    if ip.startswith("192.168."):
        return 0
    if ip.startswith("10."):
        return 1
    if ip.startswith("172."):
        try:
            second = int(ip.split(".")[1])
        except ValueError:
            return 8
        return 2 if 16 <= second <= 31 else 8
    if ip.startswith("100."):
        try:
            second = int(ip.split(".")[1])
        except ValueError:
            return 8
        return 3 if 64 <= second <= 127 else 8
    if ip.startswith("198.18.") or ip.startswith("198.19."):
        return 9
    return 5


def _lan_ip() -> str:
    """探测局域网可达地址：本机全部 IPv4 候选按段优先级排序（127.* 永不入选）。

    UDP connect（8.8.8.8:80，不发包）所得地址参与排序而非直接采信——默认路由
    可能落在 TUN 虚拟网卡（198.18.x）上，该地址局域网手机不可达（本机实测）。
    探不准时用 --serve-host 显式指定。
    """
    candidates: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))  # 不发出任何包，仅让内核选一次路由
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                candidates.append(ip)
    except OSError:
        pass
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        candidates.extend(i[4][0] for i in infos)
    except OSError:
        pass
    unique = [ip for i, ip in enumerate(candidates)
              if ip and not ip.startswith("127.") and ip not in candidates[:i]]
    if not unique:
        return "127.0.0.1"
    return min(unique, key=_addr_tier)


# ---------------------------------------------------------------- 汇总页

def _check_badge(status: str) -> str:
    color = {"pass": "#1a7f37", "fail": "#cf222e", "skip": "#9a6700"}.get(status, "#57606a")
    return f'<span style="color:{color};font-weight:600">{status}</span>'


def build_summary_html(ctx: dict) -> str:
    """演示兜底汇总页（自包含：仅相对引用，零外链；与二维码同源伺服）。"""
    import html as html_mod

    esc = html_mod.escape
    qa = ctx.get("qa") or {}
    checks_rows = "".join(
        f"<tr><td>{esc(c.get('id', ''))}</td><td>{esc(c.get('name', ''))}</td>"
        f"<td>{_check_badge(c.get('status', ''))}</td>"
        f"<td>{esc(str(c.get('detail', '')))}</td></tr>"
        for c in qa.get("checks", [])
    )
    chan_rows = "".join(
        f"<tr><td>{esc(p['channel'])}</td><td>{esc(p['locale'])}</td>"
        f"<td>{esc(p['format'])}</td><td>{p['bytes']:,}</td><td>{p['maxBytes']:,}</td>"
        f"<td>{len(p['warnings'])} 条</td>"
        f"<td><a href=\"{esc(p['rel'])}\">{esc(Path(p['rel']).name)}</a></td></tr>"
        for p in ctx["packages"]
    )
    preview_rel = ctx["preview_rel"]
    qr_rel = "qr.png"
    pf = qa.get("pf") or {}
    serve = ctx["serve"]
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>演示兜底 · {esc(ctx["project"])}</title>
<style>
  body {{ font-family: system-ui, "Segoe UI", "Microsoft YaHei", sans-serif;
         margin: 24px auto; max-width: 960px; color: #1f2328; line-height: 1.55; }}
  h1 {{ font-size: 22px; }} h2 {{ font-size: 17px; margin-top: 28px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th, td {{ border: 1px solid #d0d7de; padding: 5px 9px; text-align: left; }}
  th {{ background: #f6f8fa; }}
  .card {{ border: 1px solid #d0d7de; border-radius: 8px; padding: 14px 18px; margin: 14px 0; }}
  .kv {{ display: flex; gap: 28px; flex-wrap: wrap; }}
  .kv b {{ font-size: 21px; }}
  .dim {{ color: #57606a; font-size: 12.5px; }}
  img.qr {{ width: 180px; height: 180px; image-rendering: pixelated; }}
  a {{ color: #0969da; }}
</style>
</head>
<body>
<h1>演示兜底 · {esc(ctx["project"])}（规格驱动试玩广告工厂）</h1>
<p class="dim">生成于 {esc(ctx["finished_at"])} · spec <code>{esc(ctx["spec_rel"])}</code> ·
命令 <code>python -m pfcore make --spec {esc(ctx["spec_arg"])}</code></p>

<div class="card">
<h2 style="margin-top:0">墙钟计时</h2>
<div class="kv">
  <div><b>{ctx["make_wall_sec"]:.1f}s</b><br><span class="dim">make 编排墙钟（入口 → 二维码可扫）</span></div>
  <div><b>{ctx["spec_to_qr_sec"]:.1f}s</b><br><span class="dim">spec 修改完成 → 二维码可扫（spec mtime 口径）</span></div>
</div>
<p class="dim">"可扫" = 二维码落盘且本机静态伺服端口 {serve["port"]} 已在监听（TCP 实测）。目标 ≤90s。</p>
</div>

<div class="card">
<h2 style="margin-top:0">手机预览（扫码即玩）</h2>
<img class="qr" src="{qr_rel}" alt="预览二维码">
<p>预览链接：<a href="{esc(preview_rel)}">{esc(ctx["preview_url"])}</a></p>
<p class="dim">伺服根目录 <code>{esc(ctx["demo_rel"])}</code>（本机 {"复用上次会话" if serve["reused"] else "本次启动"}的静态伺服器，0.0.0.0:{serve["port"]}）。
手机须与本机同一局域网；打不开时放行防火墙或改用手机热点，兜底本页即静态件。</p>
</div>

<div class="card">
<h2 style="margin-top:0">渠道包（{esc(ctx["spec_rel"])} → 三渠道）</h2>
<table><tr><th>渠道</th><th>语言</th><th>形态</th><th>字节</th><th>上限</th><th>警告</th><th>产物</th></tr>
{chan_rows}</table>
<p class="dim">来源：同一份真实可玩 match3 HTML（{esc(preview_rel)}）经 pf-packager 按渠道规则库出包；
mintegral 为 zip（Template.html + build.js）。unity/google/tiktok 未在规则库冻结，不在本阶段范围。</p>
</div>

<div class="card">
<h2 style="margin-top:0">质检（qacore --autoplay · 渠道 {esc(str(qa.get("channel")))})</h2>
<p class="dim">自动试玩以真实指针事件驱动到结束页：pf:ready {pf.get("readyMs")}ms ·
pf:end {pf.get("endMs")}ms（win={pf.get("endWin")}）· 本地加载 {qa.get("loadMs")}ms ·
报告 <a href="{esc(qa.get("report_rel", ""))}">{esc(qa.get("report_rel", ""))}</a>
（截图 <a href="{esc(qa.get("shot_rel", ""))}">竖屏</a> /
<a href="{esc(qa.get("shot_ls_rel", ""))}">横屏</a>）</p>
<table><tr><th>检查</th><th>名称</th><th>状态</th><th>说明</th></tr>
{checks_rows}</table>
<p class="dim">skip = 未实装/无判定前提，不算通过。质检不过时 make 不产出二维码与兜底目录。</p>
</div>

<p class="dim">{esc(ctx["footer"])}</p>
</body>
</html>
"""


# ---------------------------------------------------------------- 主流程

def cmd_make(args: argparse.Namespace) -> int:
    started_epoch = time.time()
    t0 = time.perf_counter()
    try:
        return _make_impl(args, started_epoch, t0)
    except MakeError as exc:
        print(f"[make] FAIL：{exc}", file=sys.stderr)
        return exc.exit_code


def _make_impl(args: argparse.Namespace, started_epoch: float, t0: float) -> int:
    from .validation import validate_spec_file  # 复用 M1 校验（与 validate 子命令同源）

    # ---- 0) 定位 spec / 模板 / 渠道集合 --------------------------------
    spec_path = Path(args.spec).resolve()
    if not spec_path.is_file():
        raise MakeError(f"spec 不存在：{spec_path}", 2)
    spec_mtime = spec_path.stat().st_mtime

    issues = validate_spec_file(spec_path)
    if issues:
        print(f"[make] validate FAIL {spec_path.name}")
        for issue in issues:
            print(f"  {issue.render()}")
        raise MakeError("spec 校验未通过（校验是流水线第一道闸）", 1)
    _log(f"validate OK：{spec_path.name}")

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    project = str((spec.get("meta") or {}).get("projectId") or "playable").strip()
    template = str((spec.get("game") or {}).get("template") or "").strip()
    builder = TEMPLATE_BUILDERS.get(template)
    if builder is None or not builder.is_file():
        raise MakeError(
            f"模板 {template!r} 没有可用的真实构建器（支持：{', '.join(TEMPLATE_BUILDERS)}）", 2)
    if shutil.which("node") is None:
        raise MakeError("未找到 node（模板构建/打包需要 Node.js）", 2)

    locales = [x.strip() for x in (args.locales or "").split(",") if x.strip()]
    if not locales:
        locales = [str((spec.get("i18n") or {}).get("defaultLocale") or "en")]

    rules = _load_rules()
    known = list((rules.get("channels") or {}).keys())
    if args.channels == "all":
        channels = [c for c in known if c != "preview"]  # preview 是本地渠道，不打包
    else:
        channels = [x.strip() for x in args.channels.split(",") if x.strip()]
    unknown = [c for c in channels if c not in known]
    if unknown:
        raise MakeError(f"渠道不在规则库：{', '.join(unknown)}（现有：{', '.join(known)}）", 2)
    if not channels:
        raise MakeError("渠道列表为空", 2)

    out_root = Path(args.out).resolve()
    preview_dir = out_root / "preview"
    dist_dir = out_root / project / "dist"
    demo_dir = out_root / "demo-prebuilt"
    out_root.mkdir(parents=True, exist_ok=True)

    qc = spec.get("qc") or {}

    # ---- 1) 模板构建（真实可玩 HTML）+ 组装打包器输入 dist ----------------
    previews: dict[str, Path] = {}
    for locale in locales:
        out_html = preview_dir / f"{project}-{locale}.html"
        _run(["node", str(builder), "--spec", str(spec_path),
              "--locale", locale, "--out", str(out_html)], f"模板构建（{locale}）")
        previews[locale] = out_html
        loc_dir = dist_dir / locale
        loc_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out_html, loc_dir / "index.html")  # 打包器输入形态（契约 §3.1 路径 B）
    _log(f"构建完成：{', '.join(str(p.name) for p in previews.values())}（dist={dist_dir.name}/）")

    # ---- 2) 渠道打包（同一份 HTML × 每渠道规则） ------------------------
    rules_channels = rules.get("channels") or {}
    packages: list[dict] = []
    for channel in channels:
        fmt = ((rules_channels.get(channel) or {}).get("package") or {}).get("format") \
            or "single-html"
        for locale in locales:
            stdout = _run(
                ["node", str(PACKAGER_BIN), "build",
                 "--spec", str(spec_path), "--dist", str(dist_dir),
                 "--channel", channel, "--locale", locale, "--out", str(out_root)],
                f"打包 {channel}/{locale}")
            info = json.loads(stdout.strip().splitlines()[-1])  # bin.mjs 末行 JSON 摘要
            artifact = Path(info["artifact"])
            warnings = [ln for ln in stdout.splitlines() if "警告:" in ln]
            rel = os.path.relpath(artifact, demo_dir).replace(os.sep, "/")
            packages.append({
                "channel": channel, "locale": locale, "format": fmt,
                "artifact": artifact,  # Path（报告序列化时转 str）
                "rel": rel,
                "bytes": int(info["totalBytes"]), "maxBytes": int(info["maxBytes"]),
                "warnings": warnings,
            })
            _log(f"打包 {channel}/{locale}：{artifact.name} {info['totalBytes']:,}B "
                 f"/ 上限 {info['maxBytes']:,}B（警告 {len(warnings)}）")

    # ---- 3) 质检（首个 single-html 渠道 × 首语言，--autoplay） ----------
    qa_pkg = next((p for p in packages
                   if p["locale"] == locales[0] and p["format"] == "single-html"), None)
    if qa_pkg is None:
        raise MakeError("渠道列表中没有 single-html 渠道，qacore 当前仅支持单 HTML 产物", 2)
    qa_report = qa_pkg["artifact"].with_name("index.report.json")
    _run([sys.executable, "-m", "qacore", "run", str(qa_pkg["artifact"]),
          "--channel", qa_pkg["channel"], "--autoplay",
          "--max-load-sec", str(qc.get("maxLoadSec", 2.0)),
          "--autoplay-timeout", str(qc.get("autoplayTimeoutSec", 45.0)),
          "--out", str(qa_report)],
         f"qacore 质检（{qa_pkg['channel']}）", timeout_sec=300)
    qa_raw = json.loads(qa_report.read_text(encoding="utf-8"))
    qa = {
        "channel": qa_pkg["channel"], "locale": qa_pkg["locale"],
        "report": str(qa_report),
        "report_rel": os.path.relpath(qa_report, demo_dir).replace(os.sep, "/"),
        "shot_rel": os.path.relpath(
            qa_report.with_name("index.report.png"), demo_dir).replace(os.sep, "/"),
        "shot_ls_rel": os.path.relpath(
            qa_report.with_name("index.report-landscape.png"), demo_dir).replace(os.sep, "/"),
        "pf": qa_raw.get("pf") or {},
        "loadMs": round(float((qa_raw.get("facts") or {}).get("load_ms") or 0)),
        "checks": qa_raw.get("checks") or [],
    }
    n_fail = sum(1 for c in qa["checks"] if c.get("status") == "fail")
    _log(f"qacore {qa_pkg['channel']}：{len(qa['checks'])} 项（fail {n_fail}，"
         f"pf:end {qa['pf'].get('endMs')}ms win={qa['pf'].get('endWin')}）")
    if n_fail:
        raise MakeError(f"质检存在 {n_fail} 项 fail：不产出二维码与兜底目录（质检是裁判）", 1)

    # ---- 4) demo-prebuilt 兜底目录（静态可伺服） ------------------------
    if demo_dir.exists():
        shutil.rmtree(demo_dir)
    (demo_dir / "preview").mkdir(parents=True)
    for locale, html_path in previews.items():
        shutil.copyfile(html_path, demo_dir / "preview" / html_path.name)
    for p in packages:
        src_dir = p["artifact"].parent
        dst = demo_dir / "channels" / p["channel"] / p["locale"]
        shutil.copytree(src_dir, dst, dirs_exist_ok=True)
        p["rel"] = os.path.relpath(dst / p["artifact"].name, demo_dir).replace(os.sep, "/")
        if p is qa_pkg:
            qa["report_rel"] = os.path.relpath(dst / qa_report.name, demo_dir).replace(os.sep, "/")
            qa["shot_rel"] = os.path.relpath(
                dst / qa_report.with_name("index.report.png").name, demo_dir).replace(os.sep, "/")
            qa["shot_ls_rel"] = os.path.relpath(
                dst / qa_report.with_name("index.report-landscape.png").name,
                demo_dir).replace(os.sep, "/")

    # ---- 5) 二维码 + 静态伺服 + 计时 ------------------------------------
    preview_html = previews[locales[0]]
    preview_rel = f"preview/{preview_html.name}"
    if args.serve_host:
        host = args.serve_host
    else:
        host = _lan_ip()
    serve = {"port": int(args.serve_port), "reused": False}
    if not args.no_serve:
        port, reused = ensure_server(out_root, demo_dir, int(args.serve_port))
        serve = {"port": port, "reused": reused}
    else:
        _log("--no-serve：不启动伺服器；二维码指向默认端口，请自行伺服 demo-prebuilt 目录")
    preview_url = f"http://{host}:{serve['port']}/{preview_rel}" if serve["port"] != 80 \
        else f"http://{host}/{preview_rel}"

    import qrcode  # 延迟导入：仅在真正出二维码时需要

    qr = qrcode.QRCode(border=2, box_size=6,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(preview_url)
    qr.make(fit=True)
    qr.make_image(fill_color="black", back_color="white").save(str(demo_dir / "qr.png"))

    t_qr = time.perf_counter()
    make_wall_sec = t_qr - t0
    spec_to_qr_sec = max(0.0, time.time() - spec_mtime)

    finished_at = datetime.now().isoformat(timespec="seconds")
    ctx = {
        "project": project, "spec_rel": os.path.relpath(spec_path, REPO_ROOT).replace(os.sep, "/"),
        "spec_arg": str(args.spec), "finished_at": finished_at,
        "make_wall_sec": make_wall_sec, "spec_to_qr_sec": spec_to_qr_sec,
        "preview_rel": preview_rel, "preview_url": preview_url,
        "demo_rel": os.path.relpath(demo_dir, REPO_ROOT).replace(os.sep, "/"),
        "packages": packages, "qa": qa, "serve": serve,
        "footer": (f"pfcore make（M9 编排）· Node {_node_version()} · "
                   f"Python {sys.version.split()[0]} · "
                   f"规则库 rulesVersion={rules.get('rulesVersion')} · "
                   "本页与二维码同源（demo-prebuilt 静态目录），零外链"),
    }
    (demo_dir / "index.html").write_text(build_summary_html(ctx), encoding="utf-8")

    report = {
        "command": "pfcore make", "spec": str(spec_path),
        "specMtime": spec_mtime, "startedAt": datetime.fromtimestamp(started_epoch).isoformat(timespec="seconds"),
        "finishedAt": finished_at,
        "timings": {
            "makeWallSec": round(make_wall_sec, 2),
            "specModifiedToQrScannableSec": round(spec_to_qr_sec, 2),
            "note": "二维码可扫 = qr.png 落盘且静态伺服端口 TCP 监听实测通过",
        },
        "locales": locales, "channels": channels,
        "preview": {"html": str(preview_html), "url": preview_url},
        "serve": {"host": host, **serve, "root": str(demo_dir),
                  "stateFile": str(out_root / SERVE_STATE_NAME)},
        "packages": [{**{k: v for k, v in p.items() if k != "artifact"},
                      "artifact": str(p["artifact"])} for p in packages],
        "qa": qa,
        "demoPrebuilt": {"root": str(demo_dir), "index": str(demo_dir / "index.html"),
                         "qr": str(demo_dir / "qr.png")},
    }
    (demo_dir / "pipeline-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ---- 6) 收尾输出 -----------------------------------------------------
    _log(f"预览链接（手机同一局域网可开）：{preview_url}")
    _log(f"汇总页：{demo_dir / 'index.html'}")
    _log(f"兜底目录：{demo_dir}（静态可伺服；渠道包/报告/二维码/汇总页已整体复制）")
    _log(f"计时：make 墙钟 {make_wall_sec:.1f}s；spec 修改完成→二维码可扫 {spec_to_qr_sec:.1f}s"
         f"（spec mtime 口径，目标 ≤90s）")
    if serve["reused"]:
        _log(f"静态伺服：复用端口 {serve['port']} 的上次会话伺服器（.demo-serve.json）")
    else:
        _log(f"静态伺服：已在 0.0.0.0:{serve['port']} 启动（本进程退出后仍存活；"
             f"手机打不开时放行防火墙或改用手机热点）")
    qr.print_ascii(invert=True)
    print(f"[make] PASS：{len(packages)} 个渠道包 + 质检报告 + 二维码 + demo-prebuilt 兜底，exit 0")
    return 0


def _node_version() -> str:
    try:
        proc = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=10)
        return (proc.stdout or "").strip() or "?"
    except (OSError, subprocess.SubprocessError):
        return "?"
