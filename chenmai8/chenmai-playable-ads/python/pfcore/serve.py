"""pfcore serve —— 演示产物局域网静态伺服 + 二维码 + 汇总页（反馈行动 2）。

用途：对**已经生成好的**产物目录（``artifacts/demo-prebuilt/`` 或任何含
预览 HTML/渠道包/质检报告的目录，如 ``artifacts/preview/``）起一个**前台**局域网
静态伺服器；每次启动重建两件东西（都落在被伺服目录内，零外链）：
  - ``index.html`` 汇总页：手机预览链接 + **各渠道包下载链接** + **质检报告链接**
    （报告 JSON/双视口截图/检查项明细，从目录内 ``*.report.json`` 现场解析）；
  - ``qr.png`` 二维码：内容 = LAN 可达的预览 HTML 的 http URL（契约 §5，与 make 同规；
    127.0.0.1 手机扫不出；无 ``preview/*.html`` 时退化为汇总页地址并打印警告）。

与 make 伺服的差异：serve 是前台进程（Ctrl+C 停止、端口即释放），不做分离子进程、
不写 ``.demo-serve.json`` 复用状态（那是 make 编排中途需要的）；端口被占时同样向后顺延。
演示日兜底用法：手机要扫"今早 make 的预构建产物"时，一条 ``serve`` 即可，不必重跑流水线。

设计约束（与 make.py 同一套纪律）：
- 零外链：汇总页仅相对引用被伺服目录内文件；二维码为 qrcode 库本地生成的 PNG。
- 本模块**不发起任何 HTTP 请求**（防 SSRF 纪律）：端口健康检查只做 TCP connect。
- 退出码：0 = 正常伺服并被 Ctrl+C 停止；2 = 用法/环境错误（目录不存在、qrcode 库缺失、
  无可用端口、端口未进入监听）——契约 §2。
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import sys
import time
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# 复用 make 的探测函数：同一套 IP 段优先级（192.168 > 10 > 172.16-31 > 100.64/10 > …）
# 与"TCP-only 健康检查"纪律（见 make.py——本包不对 loopback/私网发起 HTTP 请求）。
from .make import _lan_ip, _port_listening

DEFAULT_ROOT = "artifacts/demo-prebuilt"
DEFAULT_PORT = 8618


def _log(msg: str) -> None:
    print(f"[serve] {msg}", flush=True)


# ---------------------------------------------------------------- 目录扫描

def _posix_rel(path: Path, root: Path) -> str:
    return os.path.relpath(path, root).replace(os.sep, "/")


def scan_previews(root: Path) -> list[Path]:
    """预览 HTML：优先 ``preview/*.html``；没有则退化为根目录散置的 ``*.html``
    （排除汇总页 index.html——这支持直接伺服 ``artifacts/preview/`` 这类裸产物目录）。"""
    preview_dir = root / "preview"
    if preview_dir.is_dir():
        return sorted(preview_dir.glob("*.html"))
    return sorted(p for p in root.glob("*.html") if p.name != "index.html")


def scan_channel_packages(root: Path) -> list[dict]:
    """扫描 ``channels/<channel>/<locale>/`` 渠道包目录（契约 §3.2 形态）。

    产物 = ``index.html``（single-html）或目录内唯一 ``*.zip``（zip 渠道）；
    字节与上限读 ``pack-manifest.json``（缺失/损坏时上限记 None、警告数记 0，
    字节一律取文件实测——清单不阻塞伺服）。
    """
    channels_dir = root / "channels"
    if not channels_dir.is_dir():
        return []
    packages: list[dict] = []
    for channel_dir in sorted(channels_dir.iterdir()):
        if not channel_dir.is_dir():
            continue
        for locale_dir in sorted(channel_dir.iterdir()):
            if not locale_dir.is_dir():
                continue
            artifact = locale_dir / "index.html"
            fmt = "single-html"
            if not artifact.is_file():
                zips = sorted(locale_dir.glob("*.zip"))
                if not zips:
                    continue
                artifact, fmt = zips[0], "zip"
            max_bytes = None
            warnings = 0
            manifest_path = locale_dir / "pack-manifest.json"
            if manifest_path.is_file():
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    max_bytes = int(manifest["maxBytes"]) if manifest.get("maxBytes") else None
                    warnings = len(manifest.get("warnings") or [])
                except (json.JSONDecodeError, OSError, ValueError, TypeError, KeyError):
                    pass
            packages.append({
                "channel": channel_dir.name, "locale": locale_dir.name,
                "format": fmt, "rel": _posix_rel(artifact, root),
                "manifest_rel": _posix_rel(manifest_path, root),
                "bytes": artifact.stat().st_size, "maxBytes": max_bytes, "warnings": warnings,
            })
    return packages


def scan_qa_reports(root: Path) -> list[dict]:
    """解析目录内全部 ``*.report.json``（qacore 报告，契约 §4 字段）+ 双视口截图。

    qacore 命名（契约 §3.3）：``<名>.report.json`` / ``<名>.report.png`` /
    ``<名>.report-landscape.png``；报告损坏只跳过不阻塞伺服。
    """
    reports: list[dict] = []
    for report_path in sorted(root.rglob("*.report.json")):
        try:
            raw = json.loads(report_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        base = report_path.name[:-len(".json")]              # "<名>.report"
        shot_png = report_path.with_name(base + ".png")
        shot_ls_png = report_path.with_name(base + "-landscape.png")
        reports.append({
            "rel": _posix_rel(report_path, root),
            "shot_rel": _posix_rel(shot_png, root) if shot_png.is_file() else None,
            "shot_ls_rel": _posix_rel(shot_ls_png, root) if shot_ls_png.is_file() else None,
            "channel": str(raw.get("channel") or report_path.parent.name),
            "pf": raw.get("pf") or {},
            "loadMs": round(float((raw.get("facts") or {}).get("load_ms") or 0)),
            "checks": raw.get("checks") or [],
        })
    return reports


# ---------------------------------------------------------------- 汇总页

def _badge(status: str) -> str:
    import html as html_mod
    color = {"pass": "#1a7f37", "fail": "#cf222e", "skip": "#9a6700"}.get(status, "#57606a")
    return f'<span style="color:{color};font-weight:600">{html_mod.escape(status)}</span>'


def _fmt_int(value: int | None) -> str:
    return f"{value:,}" if value is not None else "—"


def build_page(ctx: dict) -> str:
    """演示伺服汇总页：自包含、仅相对引用、零外链（与二维码同源伺服）。"""
    import html as html_mod

    esc = html_mod.escape
    pkg_rows = []
    for p in ctx["packages"]:
        pkg_rows.append(
            f"<tr><td>{esc(p['channel'])}</td><td>{esc(p['locale'])}</td>"
            f"<td>{esc(p['format'])}</td><td>{p['bytes']:,}</td>"
            f"<td>{_fmt_int(p['maxBytes'])}</td><td>{p['warnings']} 条</td>"
            f"<td><a href=\"{esc(p['rel'])}\">{esc(Path(p['rel']).name)}</a></td>"
            f"<td><a href=\"{esc(p['manifest_rel'])}\">manifest</a></td></tr>")
    pkg_table = ("".join(pkg_rows) or
                 '<tr><td colspan="8" class="dim">（本目录无渠道包'
                 '——可伺服裸预览目录，或先跑 make）</td></tr>')

    qa_sections = []
    for qa in ctx["qas"]:
        pf = qa.get("pf") or {}
        check_rows = "".join(
            f"<tr><td>{esc(c.get('id', ''))}</td><td>{esc(c.get('name', ''))}</td>"
            f"<td>{_badge(c.get('status', ''))}</td>"
            f"<td>{esc(str(c.get('detail', '')))}</td></tr>"
            for c in qa["checks"])
        links = f'报告 <a href="{esc(qa["rel"])}">{esc(Path(qa["rel"]).name)}</a>'
        if qa.get("shot_rel"):
            links += f' · 截图 <a href="{esc(qa["shot_rel"])}">竖屏</a>'
        if qa.get("shot_ls_rel"):
            links += f' / <a href="{esc(qa["shot_ls_rel"])}">横屏</a>'
        qa_sections.append(f"""
<div class="card">
<h2 style="margin-top:0">质检报告 · 渠道 {esc(qa["channel"])}</h2>
<p class="dim">pf:ready {pf.get("readyMs")}ms · pf:end {pf.get("endMs")}ms（win={pf.get("endWin")}）·
本地加载 {qa.get("loadMs")}ms · {links}</p>
<table><tr><th>检查</th><th>名称</th><th>状态</th><th>说明</th></tr>
{check_rows or '<tr><td colspan="4" class="dim">（报告无 checks 字段）</td></tr>'}</table>
<p class="dim">skip = 未实装/无判定前提，不算通过。报告由 qacore 生成，本页只做现场解析展示。</p>
</div>""")

    pipeline_html = ""
    if ctx.get("pipeline"):
        timings = (ctx["pipeline"].get("timings") or {})
        started_at = ctx["pipeline"].get("startedAt")
        pipeline_html = f"""
<div class="card">
<h2 style="margin-top:0">make 流水线计时（本目录由 make 产出）</h2>
<div class="kv">
  <div><b>{esc(str(timings.get("makeWallSec", "—")))}s</b><br><span class="dim">make 编排墙钟</span></div>
  <div><b>{esc(str(timings.get("specModifiedToQrScannableSec", "—")))}s</b><br><span class="dim">spec 修改完成 → 二维码可扫</span></div>
</div>
<p class="dim">运行 {esc(str(started_at))} ·
完整运行报告 <a href="pipeline-report.json">pipeline-report.json</a></p>
</div>"""

    if ctx["preview_rel"]:
        preview_html = (f'<p>预览链接（手机扫码即玩）：'
                        f'<a href="{esc(ctx["preview_rel"])}">{esc(ctx["preview_url"])}</a></p>')
    else:
        preview_html = '<p class="dim">本目录没有预览 HTML——二维码退化指向本汇总页。</p>'

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>演示伺服 · {esc(ctx["project"])}</title>
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
<h1>演示伺服 · {esc(ctx["project"])}（规格驱动试玩广告工厂）</h1>
<p class="dim">生成于 {esc(ctx["generated_at"])} · 伺服根目录 <code>{esc(ctx["root_display"])}</code> ·
命令 <code>python -m pfcore serve --root {esc(ctx["root_arg"])}</code></p>

<div class="card">
<h2 style="margin-top:0">手机预览（扫码即玩）</h2>
<img class="qr" src="qr.png" alt="预览二维码">
{preview_html}
<p class="dim">手机须与本机同一局域网（伺服 0.0.0.0:{ctx["port"]}）；打不开时放行防火墙或改用手机热点。
本页与二维码同源，仅相对引用本目录文件，零外链。</p>
</div>

<div class="card">
<h2 style="margin-top:0">渠道包下载</h2>
<table><tr><th>渠道</th><th>语言</th><th>形态</th><th>字节</th><th>上限</th><th>警告</th><th>产物</th><th>清单</th></tr>
{pkg_table}</table>
<p class="dim">包体来自 pf-packager 按渠道规则库出包；mintegral 为 zip（Template.html + build.js）。</p>
</div>
{"".join(qa_sections)}{pipeline_html}
<p class="dim">pfcore serve · Python {sys.version.split()[0]} ·
本页零外链：全部链接为相对路径，资源均在被伺服目录内。</p>
</body>
</html>
"""


# ---------------------------------------------------------------- 主流程

def _project_name(root: Path, previews: list[Path], pipeline: dict | None) -> str:
    """展示用项目名：make 目录取 spec projectId（artifact 路径倒数第 4 段）；
    裸预览目录取文件名前缀（<projectId>-<locale>.html）；再不行用目录名。"""
    if pipeline:
        pkgs = pipeline.get("packages") or []
        if pkgs:
            parts = Path(str(pkgs[0].get("artifact", ""))).parts
            if len(parts) >= 4:
                return parts[-4]
    if previews:
        stem = previews[0].stem
        if "-" in stem:
            return stem.rsplit("-", 1)[0]
    return root.name


def cmd_serve(args: argparse.Namespace) -> int:
    """serve 子命令：扫描目录 → 重建 qr.png + index.html → 前台伺服至 Ctrl+C。"""
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"[serve] FAIL：目录不存在：{root}（先跑 python -m pfcore make 产出 demo-prebuilt，"
              f"或用 --root 指向预览产物目录）", file=sys.stderr)
        return 2

    previews = scan_previews(root)
    packages = scan_channel_packages(root)
    qas = scan_qa_reports(root)
    pipeline = None
    pipeline_path = root / "pipeline-report.json"
    if pipeline_path.is_file():
        try:
            pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pipeline = None
    _log(f"根目录：{root}（渠道包 {len(packages)} · 质检报告 {len(qas)} · 预览 {len(previews)}）")

    # ---- 端口：被占向后顺延（与 make 同策略，上限 20 个） ----------------
    port = int(args.port)
    for _ in range(20):
        if not _port_listening(port):
            break
        port += 1
    else:
        print(f"[serve] FAIL：端口 {args.port}~{port} 均被占用（--port 换口）", file=sys.stderr)
        return 2
    if port != int(args.port):
        _log(f"端口 {args.port} 被占用，顺延到 {port}")

    host = args.host or _lan_ip()

    # ---- 二维码（qrcode 库，本地生成 PNG；契约 §5 内容规则与 make 相同） --
    preview_rel = _posix_rel(previews[0], root) if previews else ""
    path_part = f"/{preview_rel}" if preview_rel else "/"
    preview_url = f"http://{host}:{port}{path_part}" if port != 80 else f"http://{host}{path_part}"
    try:
        import qrcode
    except ImportError as exc:
        print(f"[serve] FAIL：qrcode 库未安装（requirements.txt 钉 qrcode==8.2，"
              f"pip install -r python/requirements.txt）：{exc}", file=sys.stderr)
        return 2
    if not previews:
        _log("警告：目录内无 preview/*.html，二维码退化指向汇总页（手机扫码只会看到本页）")
    qr = qrcode.QRCode(border=2, box_size=6,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(preview_url)
    qr.make(fit=True)
    qr_path = root / "qr.png"
    qr.make_image(fill_color="black", back_color="white").save(str(qr_path))

    # ---- 汇总页（覆盖写 index.html；每次 serve 现场重建，链接永远有效） --
    ctx = {
        "project": _project_name(root, previews, pipeline),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "root_display": str(root), "root_arg": args.root,
        "port": port, "preview_rel": preview_rel, "preview_url": preview_url,
        "packages": packages, "qas": qas, "pipeline": pipeline,
    }
    (root / "index.html").write_text(build_page(ctx), encoding="utf-8")

    # ---- 前台伺服（0.0.0.0；Ctrl+C 停止） --------------------------------
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(root))
    try:
        httpd = ThreadingHTTPServer(("0.0.0.0", port), handler)
    except OSError as exc:
        print(f"[serve] FAIL：端口 {port} 绑定失败（{exc}）", file=sys.stderr)
        return 2
    if not _port_listening(port):  # TCP 实测（"可扫"纪律：不做 HTTP fetch）
        print(f"[serve] FAIL：伺服器已绑定但端口 {port} 未进入监听", file=sys.stderr)
        return 2

    landing_url = f"http://{host}:{port}/" if port != 80 else f"http://{host}/"
    _log(f"汇总页（本页）：{landing_url}（本机 http://127.0.0.1:{port}/）")
    _log(f"LAN 预览：{preview_url}")
    _log(f"二维码：{qr_path} → {preview_url}")
    _log(f"SERVE port={port} landing_url={landing_url} preview_url={preview_url} qr={qr_path}")
    qr.print_ascii(invert=True)
    _log(f"伺服中 0.0.0.0:{port}（Ctrl+C 停止）…")
    started = time.monotonic()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    _log(f"已停止（伺服 {time.monotonic() - started:.0f}s）")
    return 0


def main(argv: list[str] | None = None) -> int:
    """serve 独立入口（python -m pfcore.serve 亦可；编码与 __main__.py 同规）。"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="pfcore serve",
        description="局域网静态伺服演示产物目录（demo-prebuilt/裸预览），重建汇总页与二维码")
    parser.add_argument("--root", default=DEFAULT_ROOT,
                        help=f"被伺服的产物目录（默认 {DEFAULT_ROOT}；也可以是裸预览目录如 artifacts/preview）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"伺服端口（默认 {DEFAULT_PORT}；被占时向后顺延）")
    parser.add_argument("--host", default=None,
                        help="二维码指向的主机 IP（默认自动探测局域网地址）")
    args = parser.parse_args(argv)
    return cmd_serve(args)


if __name__ == "__main__":
    sys.exit(main())
