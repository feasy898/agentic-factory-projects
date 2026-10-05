"""qacore CLI（SPEC qacore.md §2 命令契约 + §3 魔法数字表 + §4 探针契约）。

用法：python -m qacore run <artifact.html> [--channel preview] [--out <report.json>]
                      [--port 0] [--max-load-sec 2.0] [--autoplay] [--autoplay-timeout 45.0]
                      [--require-text <str> ...] [--require-sprite <key> ...]
退出码：0 = 无 fail（skip 不算）；1 = 有 fail；2 = 产物不存在或非 .html。
"""

import argparse
import io
import json
import os
import sys
import time
import urllib.parse

from PIL import Image

from . import autoplay as autoplay_mod
from .checks import evaluate
from .rules import channel_rules, mute_required, runtime_stubs
from .server import ArtifactServer

# ---- 魔法数字表（SPEC §3，冻结——改任何一个都要回填 SPEC §3 并复跑 gate） ----
VIEWPORT_PORTRAIT = {"width": 390, "height": 844}
VIEWPORT_LANDSCAPE = {"width": 844, "height": 390}
DEVICE_EMULATION = {"is_mobile": True, "device_scale_factor": 2}
GOTO_TIMEOUT_MS = 15000   # wait_until="load" 上限
SETTLE_MS = 400           # load 后首帧缓冲
VARIANCE_THRESHOLD = 30.0  # 64×64 灰度方差 < 30.0 判空白
LOCAL_HOSTS = ("127.0.0.1", "localhost")
_JS_IS_MUTED = "(window.PF && typeof window.PF.isMuted === 'function') ? !!window.PF.isMuted() : null"

# 探针（SPEC §4 PROBE_JS）：add_init_script 每页面一次——重复注入会二次包装
# AudioContext 导致 running 计数失真。包装 AudioContext/HTMLMediaElement.play/
# RTCPeerConnection 构造器，监听 5 个 pf:* 事件（首个时刻；pf:end 记 detail.win）。
PROBE_JS = r"""
(() => {
  if (window.__pfprobe) return;
  const probe = {
    ready: null, start: null, end: null, endWin: null, first: null, cta: null,
    audio: { created: 0 },
    media: { unmuted: 0, playing: 0, playsBeforeFirst: 0 },
    rtc: 0,
  };
  const audioCtxs = new Set();
  const runningCount = () => {
    let n = 0;
    audioCtxs.forEach((c) => { try { if (c.state === "running") n += 1; } catch (e) {} });
    return n;
  };
  Object.defineProperty(probe.audio, "running", { get: runningCount, enumerable: true });
  const now = () => (window.performance && typeof performance.now === "function") ? performance.now() : Date.now();
  [["pf:ready", "ready"], ["pf:start", "start"], ["pf:first-interaction", "first"],
   ["pf:cta", "cta"], ["pf:end", "end"]].forEach(([name, key]) => {
    document.addEventListener(name, (ev) => {
      if (probe[key] == null) probe[key] = now();
      if (name === "pf:end") {
        try { probe.endWin = !!(ev.detail && ev.detail.win); } catch (e) { probe.endWin = false; }
      }
    });
  });
  let firstPointerSeen = false;
  const markFirstPointer = () => {
    if (!firstPointerSeen) {
      firstPointerSeen = true;
      if (probe.first == null) probe.first = now();
    }
  };
  window.addEventListener("pointerdown", markFirstPointer, true);
  window.addEventListener("touchstart", markFirstPointer, true);
  const wrapAudioCtor = (Original) => {
    if (typeof Original !== "function") return null;
    function Wrapped(...args) {
      const inst = Reflect.construct(Original, args, new.target || Wrapped);
      probe.audio.created += 1;
      audioCtxs.add(inst);
      try { inst.addEventListener("statechange", () => {}); } catch (e) {}
      return inst;
    }
    Wrapped.prototype = Original.prototype;
    return Wrapped;
  };
  const wa = wrapAudioCtor(window.AudioContext); if (wa) window.AudioContext = wa;
  const ww = wrapAudioCtor(window.webkitAudioContext); if (ww) window.webkitAudioContext = ww;
  const wrapRtcCtor = (Original) => {
    if (typeof Original !== "function") return null;
    function Wrapped(...args) {
      probe.rtc += 1;
      return Reflect.construct(Original, args, new.target || Wrapped);
    }
    Wrapped.prototype = Original.prototype;
    return Wrapped;
  };
  const wr = wrapRtcCtor(window.RTCPeerConnection); if (wr) window.RTCPeerConnection = wr;
  const wrw = wrapRtcCtor(window.webkitRTCPeerConnection); if (wrw) window.webkitRTCPeerConnection = wrw;
  const mediaSeen = new Set();
  const origPlay = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function (...args) {
    try { mediaSeen.add(this); } catch (e) {}
    if (!firstPointerSeen) probe.media.playsBeforeFirst += 1;
    return origPlay.apply(this, args);
  };
  probe.sampleMedia = () => {
    const els = new Set();
    try { document.querySelectorAll("audio,video").forEach((m) => els.add(m)); } catch (e) {}
    mediaSeen.forEach((m) => els.add(m));
    let unmuted = 0, playing = 0;
    els.forEach((m) => {
      try { if (!m.muted) unmuted += 1; } catch (e) {}
      try { if (!m.paused && !m.ended) playing += 1; } catch (e) {}
    });
    return { unmuted, playing, playsBeforeFirst: probe.media.playsBeforeFirst, created: probe.audio.created };
  };
  window.__pfprobe = probe;
})();
"""


def _gray_variance(png_bytes: bytes) -> float:
    """64×64 灰度方差（SPEC §3：Pillow convert("L").resize((64,64))）。"""
    img = Image.open(io.BytesIO(png_bytes)).convert("L").resize((64, 64))
    px = list(img.getdata())
    n = len(px)
    mean = sum(px) / n
    return sum((p - mean) ** 2 for p in px) / n


def _is_network_log_noise(text: str) -> bool:
    """Chromium 把被拦截/失败的资源加载写进 DevTools Log（Log.entryAdded），Playwright 将其
    透传为 console 事件。CHK08 的判定语义是 console.error()/pageerror（SPEC §6 CHK08），
    且 SPEC §8 要求 MUT-01 外链被 route.abort 后 CHK08 不受扰——故网络源日志噪声不计入。"""
    return text.startswith("Failed to load resource:")


def _make_route_handler(server_port, ledger, pending, external, stub_names, stubs_served):
    def _on_route(route, request):
        url = request.url
        parts = urllib.parse.urlsplit(url)
        scheme = (parts.scheme or "").lower()
        host = (parts.hostname or "").lower()
        entry = {
            "url": url,
            "method": request.method,
            "resource_type": request.resource_type,
            "status": None,
            "blocked": False,
            "failed": False,
        }
        ledger.append(entry)
        pending[request] = entry
        if scheme == "http" and host in LOCAL_HOSTS and parts.port == server_port:
            name = os.path.basename(parts.path or "")
            if name in stub_names:
                # 渠道容器运行时脚本本地桩：以空 JS 应答，模拟容器注入
                entry["status"] = 200
                stubs_served.add(name)
                route.fulfill(status=200, content_type="application/javascript",
                              body="/* qacore runtime stub */")
                return
            route.continue_()
            return
        entry["blocked"] = True
        external.append(url)
        try:
            route.abort()
        except Exception:
            pass
    return _on_route


def _run_pass(browser, url, server_port, viewport, ledger, external,
              autoplay_on, autoplay_timeout, stub_names, stubs_served):
    """单趟（一个视口 = 一个新 context：隔离静音态与请求记录）。"""
    context = browser.new_context(viewport=viewport, service_workers="block", **DEVICE_EMULATION)
    try:
        pending = {}
        context.route("**/*", _make_route_handler(server_port, ledger, pending,
                                                  external, stub_names, stubs_served))
        try:
            # WebSocket 阻断记账：处理器内 ws.close() 会挂死 load 事件，只记账不 close
            context.route_web_socket("**/*", lambda ws: external.append("websocket:" + ws.url))
        except Exception:
            pass
        context.add_init_script(PROBE_JS)
        page = context.new_page()
        console_errors = []
        page.on("console", lambda m: console_errors.append(m.text)
                if m.type == "error" and not _is_network_log_noise(m.text) else None)
        page_errors = []
        page.on("pageerror", lambda e: page_errors.append(str(e)))

        def _on_response(resp):
            e = pending.get(resp.request)
            if e is not None:
                e["status"] = resp.status

        def _on_request_failed(req):
            e = pending.get(req)
            if e is not None:
                e["failed"] = True

        page.on("response", _on_response)
        page.on("requestfailed", _on_request_failed)

        t0 = time.monotonic()
        page.goto(url, wait_until="load", timeout=GOTO_TIMEOUT_MS)
        load_ms = (time.monotonic() - t0) * 1000.0
        page.wait_for_timeout(SETTLE_MS)

        av = None
        if autoplay_on:
            av = {}
            autoplay_mod.drive(page, autoplay_timeout, av)

        shot = page.screenshot()
        probe = page.evaluate("window.__pfprobe ? JSON.parse(JSON.stringify(window.__pfprobe)) : null")
        pf_present = bool(page.evaluate(
            "typeof window.PF === 'object' && window.PF !== null && typeof window.PF.isMuted === 'function'"))
        muted_now = page.evaluate(_JS_IS_MUTED) if pf_present else None
        has_canvas = bool(page.evaluate("!!document.querySelector('canvas')"))
        sample = page.evaluate(
            "window.__pfprobe && window.__pfprobe.sampleMedia ? window.__pfprobe.sampleMedia() : null") or {}
        return {
            "load_ms": load_ms,
            "shot": shot,
            "probe": probe,
            "pf_present": pf_present,
            "muted_now": muted_now,
            "has_canvas": has_canvas,
            "console_errors": console_errors,
            "page_errors": page_errors,
            "autoplay": av,
            "sample": sample,
        }
    finally:
        context.close()


def _parse(argv):
    p = argparse.ArgumentParser(prog="qacore", description="M8 质检器")
    sub = p.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="质检单个 HTML 产物")
    run.add_argument("artifact", help="产物 .html 路径")
    run.add_argument("--channel", default="preview")
    run.add_argument("--out", default=None, help="报告路径（默认产物旁 <名>.report.json；截屏随报告目录）")
    run.add_argument("--port", type=int, default=0)
    run.add_argument("--max-load-sec", type=float, default=2.0)
    run.add_argument("--autoplay", action="store_true")
    run.add_argument("--autoplay-timeout", type=float, default=45.0)
    run.add_argument("--require-text", action="append", default=[], metavar="STR")
    run.add_argument("--require-sprite", action="append", default=[], metavar="KEY")
    return p.parse_args(argv)


def _cmd_run(args) -> int:
    artifact = os.path.abspath(args.artifact)
    if not os.path.isfile(artifact) or os.path.splitext(artifact)[1].lower() != ".html":
        print(f"qacore: 产物不存在或非 .html：{artifact}", file=sys.stderr)
        return 2

    ch = channel_rules(args.channel)
    channel_max_bytes = ch.get("maxBytes") if ch else None  # 规则库缺失 → null → CHK01 skip
    stub_names = set(runtime_stubs(args.channel))

    stem = os.path.splitext(os.path.basename(artifact))[0]
    if args.out:
        report_path = os.path.abspath(args.out)
        report_dir = os.path.dirname(report_path)
    else:
        report_dir = os.path.dirname(artifact)
        report_path = os.path.join(report_dir, f"{stem}.report.json")
    os.makedirs(report_dir, exist_ok=True)
    portrait_png = os.path.join(report_dir, f"{stem}.png")
    landscape_png = os.path.join(report_dir, f"{stem}-landscape.png")

    ledger, external, stubs_served = [], [], set()
    with ArtifactServer(os.path.dirname(artifact), port=args.port) as srv:
        url = f"http://127.0.0.1:{srv.port}/{os.path.basename(artifact)}"
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                portrait = _run_pass(browser, url, srv.port, VIEWPORT_PORTRAIT, ledger, external,
                                     args.autoplay, args.autoplay_timeout, stub_names, stubs_served)
                landscape = _run_pass(browser, url, srv.port, VIEWPORT_LANDSCAPE, ledger, external,
                                      False, args.autoplay_timeout, stub_names, stubs_served)
            finally:
                browser.close()

    av = portrait["autoplay"] or {}
    probe = portrait["probe"] or {}
    muted_before = av.get("firstMutedBeforeInteraction") if args.autoplay else portrait["muted_now"]
    audio_running_before = (av.get("audioRunningBeforeInteraction") if args.autoplay
                            else (probe.get("audio") or {}).get("running"))
    media_unmuted_before = (av.get("mediaUnmutedBeforeMax") if args.autoplay
                            else portrait["sample"].get("unmuted", 0))
    shots = {
        "portrait": {
            "has_canvas": portrait["has_canvas"],
            "variance": _gray_variance(portrait["shot"]),
            "muted_before_first_interaction": muted_before,
            "muted_after_first_gesture": av.get("mutedAfterFirstGesture") if args.autoplay else None,
            "audio_running_before_interaction": audio_running_before,
            "media_unmuted_before_first": media_unmuted_before,
            "plays_before_first": (probe.get("media") or {}).get("playsBeforeFirst", 0),
        },
        "landscape": {
            "has_canvas": landscape["has_canvas"],
            "variance": _gray_variance(landscape["shot"]),
        },
    }

    facts = {
        "artifact_bytes": os.path.getsize(artifact),
        "channel": args.channel,
        "channel_max_bytes": channel_max_bytes,
        "external_requests": external,
        "runtime_stubs": sorted(stubs_served),
        "request_count": len(ledger),
        "console_errors": portrait["console_errors"] + portrait["page_errors"]
                          + landscape["console_errors"] + landscape["page_errors"],
        "load_ms": portrait["load_ms"],
        "max_load_sec": args.max_load_sec,
        "autoplay_enabled": bool(args.autoplay),
        "autoplay_timeout_sec": args.autoplay_timeout,
        "pf_present": portrait["pf_present"],
        "viewport_shots": shots,
        "variance_threshold": VARIANCE_THRESHOLD,
        "required_texts": list(args.require_text),
        "required_sprites": list(args.require_sprite),
        "page_texts": av.get("page_texts") or [],
        "text_states": av.get("text_states") or [],
        "text_states_hook": bool(av.get("textStatesHook")),
        "asset_audit": av.get("asset_audit") or [],
    }

    ev = dict(facts)
    ev["mute_required"] = mute_required(args.channel)
    ev["probe_present"] = portrait["probe"] is not None
    ev["has_qc_hook"] = bool(av.get("hasQcHook"))
    ev["pf_end_fired"] = bool(av.get("pfEndFired"))
    ev["pf_end_ms"] = av.get("pfEndMs")
    ev["pf_end_win"] = av.get("pfEndWin")
    ev["reached_state"] = av.get("reachedState")
    ev["end_screen_visible"] = av.get("endScreenVisible")
    ev["rtc_count"] = max(
        ((portrait["probe"] or {}).get("rtc") or 0),
        ((landscape["probe"] or {}).get("rtc") or 0),
    )
    pshot = shots["portrait"]  # CHK04 证据取竖屏趟静音事实
    ev["muted_before_first_interaction"] = pshot.get("muted_before_first_interaction")
    ev["muted_after_first_gesture"] = pshot.get("muted_after_first_gesture")
    ev["audio_running_before_interaction"] = pshot.get("audio_running_before_interaction")
    ev["media_unmuted_before_first"] = pshot.get("media_unmuted_before_first")
    ev["plays_before_first"] = pshot.get("plays_before_first")

    checks = evaluate(ev)
    fail_count = sum(1 for c in checks if c["status"] == "fail")

    with open(portrait_png, "wb") as f:
        f.write(portrait["shot"])
    with open(landscape_png, "wb") as f:
        f.write(landscape["shot"])
    report = {
        "channel": args.channel,
        "url": url,
        "autoplay": bool(args.autoplay),
        "pf": {
            "present": portrait["pf_present"],
            "readyMs": probe.get("ready") if args.autoplay else None,
            "endMs": probe.get("end") if args.autoplay else None,
            "endWin": probe.get("endWin") if args.autoplay else None,
        },
        "checks": checks,
        "screenshot": os.path.basename(portrait_png),
        "requests": ledger,
        "facts": facts,
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    skip_count = sum(1 for c in checks if c["status"] == "skip")
    print(f"qacore: checks={len(checks)} fail={fail_count} skip={skip_count} -> {report_path}")
    return 1 if fail_count else 0


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")  # Windows GBK 控制台中文乱码坑
        except Exception:
            pass
    args = _parse(argv)
    if args.cmd == "run":
        try:
            return _cmd_run(args)
        except OSError as e:  # 端口占用等环境错误 → 用法/环境错误
            print(f"qacore: 环境错误：{e}", file=sys.stderr)
            return 2
    return 2
