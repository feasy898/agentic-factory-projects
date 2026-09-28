"""qacore run 的实现：本地伺服 → 无头打开（手机视口）→ 记录请求 → 截屏 → 写报告。"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from . import checks
from .server import ArtifactServer

VIEWPORT = {"width": 390, "height": 844}  # 手机竖屏视口（规格要求）
GOTO_TIMEOUT_MS = 15_000
SETTLE_MS = 300  # load 之后留给首帧渲染的缓冲


def cmd_run(args) -> int:
    artifact = Path(args.artifact).resolve()
    if not artifact.is_file():
        print(f"qacore: 产物不存在或不是文件：{artifact}", file=sys.stderr)
        return 2
    if artifact.suffix.lower() != ".html":
        print(f"qacore: 雏形阶段仅支持单个 HTML 产物，收到：{artifact.name}", file=sys.stderr)
        return 2

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    screenshot_path = out_path.with_suffix(".png")

    artifact_bytes = artifact.stat().st_size
    external: list[str] = []
    console_errors: list[str] = []
    requests: list[dict] = []
    entries: dict[object, dict] = {}  # playwright Request 对象 -> 记录条目

    with ArtifactServer(artifact.parent, port=args.port) as server:
        url = server.url_for(artifact.name)

        def _on_route(route) -> None:
            req = route.request
            parsed = urlparse(req.url)
            is_local = parsed.hostname in ("127.0.0.1", "localhost") and parsed.port == server.port
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
            if not is_local:
                entry["blocked"] = True
                external.append(req.url)
                route.abort()
                return
            route.continue_()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    viewport=dict(VIEWPORT),
                    is_mobile=True,
                    device_scale_factor=2,
                )
                page = context.new_page()

                def _on_response(response) -> None:
                    entry = entries.get(response.request)
                    if entry is not None:
                        entry["status"] = response.status

                def _on_requestfailed(request) -> None:
                    entry = entries.get(request)
                    if entry is not None:
                        entry["failed"] = True

                def _on_console(msg) -> None:
                    if msg.type == "error":
                        console_errors.append(f"console.error: {msg.text}")

                page.route("**/*", _on_route)
                page.on("response", _on_response)
                page.on("requestfailed", _on_requestfailed)
                page.on("console", _on_console)
                page.on("pageerror", lambda exc: console_errors.append(f"pageerror: {exc}"))

                t0 = time.perf_counter()
                page.goto(url, wait_until="load", timeout=GOTO_TIMEOUT_MS)
                load_ms = (time.perf_counter() - t0) * 1000
                page.wait_for_timeout(SETTLE_MS)
                page.screenshot(path=str(screenshot_path))
            finally:
                browser.close()

    page_checks = checks.evaluate(
        artifact_bytes=artifact_bytes,
        channel=args.channel,
        external_requests=external,
        console_errors=console_errors,
        load_ms=load_ms,
        max_load_sec=args.max_load_sec,
    )

    report = {
        "channel": args.channel,
        "url": url,
        "checks": [c.to_dict() for c in page_checks],
        "screenshot": os.path.relpath(screenshot_path, out_path.parent).replace(os.sep, "/"),
        "requests": requests,
    }
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    failed = [c for c in page_checks if c.status == "fail"]
    print(
        f"qacore: {artifact.name} @ {args.channel} -> {out_path} "
        f"({len(requests)} 请求, {len(failed)} FAIL)",
    )
    return 1 if failed else 0
