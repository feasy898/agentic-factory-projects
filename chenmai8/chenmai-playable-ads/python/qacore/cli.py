"""qacore run 的实现：本地伺服 → 无头打开（横竖屏双仿真）→ 记录请求 →
（--autoplay 时经 __PF_QC__ 自动试玩）→ 截屏 → 写报告。

采集结构（facts）由本模块组装，PASS/FAIL 判定统一在 checks.evaluate。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image
from playwright.sync_api import Page, sync_playwright

from . import checks
from .autoplay import (PROBE_JS, audio_running, drive_autoplay, has_pf,
                       media_sample, pf_muted, probe_installed, rtc_count)
from .server import ArtifactServer

VIEWPORT_PORTRAIT = {"width": 390, "height": 844}
VIEWPORT_LANDSCAPE = {"width": 844, "height": 390}
GOTO_TIMEOUT_MS = 15_000
SETTLE_MS = 400          # load 之后留给首帧渲染的缓冲
VARIANCE_THRESHOLD = 30.0  # 64×64 灰度方差低于此值视为空白画面
REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_PATH = REPO_ROOT / "channel-rules" / "channel-rules.json"


def load_channel_limit(channel: str) -> int | None:
    """从规则库取渠道包体上限；规则库/渠道缺失返回 None（CHK01 不判定）。"""
    try:
        rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        entry = rules.get("channels", {}).get(channel)
        if isinstance(entry, dict) and isinstance(entry.get("maxBytes"), int):
            return int(entry["maxBytes"])
    except (OSError, json.JSONDecodeError):
        pass
    return None


def load_channel_mute_required(channel: str) -> bool:
    """渠道是否要求首交互前静音：渠道级 runtime.muteBeforeFirstInteraction 优先，
    回落 defaults.muteBeforeFirstInteraction；规则库不可读时从严取 True
    （可玩广告各渠道普遍强制首交互前静音）。"""
    try:
        rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        defaults = rules.get("defaults", {})
        entry = rules.get("channels", {}).get(channel)
        if isinstance(entry, dict):
            runtime = entry.get("runtime")
            if isinstance(runtime, dict) and "muteBeforeFirstInteraction" in runtime:
                return bool(runtime["muteBeforeFirstInteraction"])
        return bool(defaults.get("muteBeforeFirstInteraction", True))
    except (OSError, json.JSONDecodeError):
        return True


def grayscale_variance(png_path: Path) -> float:
    """截图降采样到 64×64 灰度后的像素方差（空白页面接近 0）。"""
    img = Image.open(png_path).convert("L").resize((64, 64))
    px = list(img.getdata())
    mean = sum(px) / len(px)
    return sum((p - mean) ** 2 for p in px) / len(px)


def cmd_run(args) -> int:
    artifact = Path(args.artifact).resolve()
    if not artifact.is_file():
        print(f"qacore: 产物不存在或不是文件：{artifact}", file=sys.stderr)
        return 2
    if artifact.suffix.lower() != ".html":
        print(f"qacore: 当前阶段仅支持单个 HTML 产物，收到：{artifact.name}", file=sys.stderr)
        return 2

    out_path = Path(args.out).resolve() if args.out else artifact.with_suffix(".report.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    screenshot_path = out_path.with_suffix(".png")

    autoplay_enabled = bool(args.autoplay)
    autoplay_timeout = float(args.autoplay_timeout)

    external: list[str] = []
    console_errors: list[str] = []
    requests: list[dict] = []
    entries: dict[object, dict] = {}
    blocked_urls: set[str] = set()
    rtc_max = 0
    load_ms = -1.0
    pf_present = False
    probe_ok = False
    autoplay_facts: dict = {}
    mute_facts: dict = {}
    shots: dict[str, dict] = {}

    with ArtifactServer(artifact.parent, port=args.port) as server:
        url = server.url_for(artifact.name)

        def _is_local(parsed) -> bool:
            return parsed.hostname in ("127.0.0.1", "localhost") and parsed.port == server.port

        def _on_route(route) -> None:
            req = route.request
            parsed = urlparse(req.url)
            entry = {
                "url": req.url,
                "method": req.method,
                "resource_type": req.resource_type,
                "status": None,
                "blocked": False,
                "failed": False,
            }
            entries[req] = entry
            requests.append(entry)
            if not _is_local(parsed):
                entry["blocked"] = True
                if req.url not in external:
                    external.append(req.url)
                blocked_urls.add(req.url)
                route.abort()
                return
            route.continue_()

        def _on_ws(ws) -> None:
            # WebSocket 不经过 page.route，必须单独拦截。注册 route_web_socket
            # 处理器后，未调用 connect_to() 的 socket 不会向服务器发起真实连接
            # （实测 Playwright 1.63：非本机 WS 记账后即被阻于握手前，页面侧
            # readyState 永远到不了 OPEN）。
            # 注意：不要在处理器里调用 ws.close()——实测会让 page.goto 的 load
            # 事件永久挂起（sync API 死锁），因此非本机 WS 只记账不 close。
            parsed = urlparse(ws.url)
            if not _is_local(parsed):
                label = f"websocket:{ws.url}"
                if label not in external:
                    external.append(label)
            # 本地 WS 同样不 connect_to：静态产物不应依赖 WebSocket。

        def _wire(page: Page) -> None:
            def _on_response(response) -> None:
                entry = entries.get(response.request)
                if entry is not None:
                    entry["status"] = response.status

            def _on_requestfailed(request) -> None:
                entry = entries.get(request)
                if entry is not None:
                    entry["failed"] = True

            def _on_console(msg) -> None:
                if msg.type != "error":
                    return
                # 我方主动 abort 外链资源会引发浏览器自身的 "Failed to load
                # resource" 报错——该违规已归 CHK03 记账，不再计入 CHK08 重复处罚。
                try:
                    src_url = (msg.location or {}).get("url") or ""
                except Exception:
                    src_url = ""
                if src_url and src_url in blocked_urls:
                    return
                console_errors.append(f"console.error: {msg.text}")

            page.route("**/*", _on_route)
            page.route_web_socket("**/*", _on_ws)
            page.on("response", _on_response)
            page.on("requestfailed", _on_requestfailed)
            page.on("console", _on_console)
            page.on("pageerror", lambda exc: console_errors.append(f"pageerror: {exc}"))
            page.add_init_script(PROBE_JS)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:

                def run_pass(viewport: dict[str, int], label: str, shot_path: Path,
                             do_autoplay: bool) -> tuple[bool, dict]:
                    nonlocal rtc_max
                    context = browser.new_context(
                        viewport=dict(viewport),
                        is_mobile=True,
                        device_scale_factor=2,
                        # Service Worker 发出的请求不进入 page.route，必须整体禁用，
                        # 否则页面可借 SW 绕过零外网拦截。
                        service_workers="block",
                    )
                    page = context.new_page()
                    _wire(page)  # 含 PROBE_JS 注入（仅一次，勿重复包装 AudioContext）
                    nonlocal load_ms
                    t0 = time.perf_counter()
                    page.goto(url, wait_until="load", timeout=GOTO_TIMEOUT_MS)
                    pass_load_ms = (time.perf_counter() - t0) * 1000
                    if label == "portrait":
                        load_ms = pass_load_ms
                    page.wait_for_timeout(SETTLE_MS)

                    facts_pass: dict = {"probeInstalled": probe_installed(page)}
                    if do_autoplay:
                        facts_pass.update(drive_autoplay(page, autoplay_timeout))
                        page.wait_for_timeout(300)
                    else:
                        # 未驱动试玩时，加载后的静音态即"首交互前静音"事实
                        ms = media_sample(page) or {}
                        facts_pass.update({
                            "firstMutedBeforeInteraction": pf_muted(page),
                            "audioRunningBeforeInteraction": audio_running(page),
                            "mediaUnmutedBeforeInteraction": int(ms.get("unmuted") or 0),
                            "mediaPlaysBeforeInteraction": int(ms.get("playsBeforeFirst") or 0),
                        })
                    rtc = rtc_count(page)
                    if isinstance(rtc, int):
                        rtc_max = max(rtc_max, rtc)
                    page.screenshot(path=str(shot_path))
                    has_canvas = bool(page.evaluate("() => !!document.querySelector('canvas')"))
                    pf = has_pf(page)
                    context.close()
                    return pf, {
                        "has_canvas": has_canvas,
                        "variance": grayscale_variance(shot_path),
                        **facts_pass,
                    }

                # 第一趟：竖屏（可自动试玩）
                pf_present, portrait = run_pass(
                    VIEWPORT_PORTRAIT, "portrait", screenshot_path, autoplay_enabled)
                shots["portrait"] = portrait
                probe_ok = bool(portrait.get("probeInstalled"))
                if autoplay_enabled:
                    autoplay_facts = portrait
                mute_facts = portrait

                # 第二趟：横屏（仅加载与截屏）
                _, landscape = run_pass(
                    VIEWPORT_LANDSCAPE, "landscape",
                    screenshot_path.with_name(
                        screenshot_path.stem + "-landscape" + screenshot_path.suffix),
                    False)
                shots["landscape"] = landscape
            finally:
                browser.close()

    facts = {
        "artifact_bytes": artifact.stat().st_size,
        "channel": args.channel,
        "channel_max_bytes": load_channel_limit(args.channel),
        "channel_mute_required": load_channel_mute_required(args.channel),
        "external_requests": external,
        "rtc_connections": rtc_max,
        "request_count": len(requests),
        "console_errors": console_errors,
        "load_ms": load_ms,
        "max_load_sec": args.max_load_sec,
        "autoplay_enabled": autoplay_enabled,
        "autoplay_timeout_sec": autoplay_timeout,
        "autoplay": autoplay_facts,
        "muteLoadTime": mute_facts,
        "pf_present": pf_present,
        "probe_installed": probe_ok,
        "viewport_shots": shots,
        "variance_threshold": VARIANCE_THRESHOLD,
    }

    page_checks = checks.evaluate(facts)

    report = {
        "channel": args.channel,
        "url": url,
        "autoplay": autoplay_enabled,
        "pf": {
            "present": pf_present,
            "readyMs": (autoplay_facts or {}).get("pfReadyMs"),
            "endMs": (autoplay_facts or {}).get("pfEndMs"),
            "endWin": (autoplay_facts or {}).get("pfEndWin"),
        },
        "checks": [c.to_dict() for c in page_checks],
        "screenshot": os.path.relpath(screenshot_path, out_path.parent).replace(os.sep, "/"),
        "requests": requests,
        "facts": {k: v for k, v in facts.items() if k != "autoplay"},
    }
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    failed = [c for c in page_checks if c.status == "fail"]
    print(
        f"qacore: {artifact.name} @ {args.channel} -> {out_path} "
        f"({len(requests)} 请求, {len(failed)} FAIL"
        + (f", pf:end {autoplay_facts.get('pfEndMs') and round(autoplay_facts['pfEndMs'])}ms"
           if autoplay_facts else "") + ")",
    )
    return 1 if failed else 0
