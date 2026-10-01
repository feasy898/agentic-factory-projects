"""qacore CLI（spec §2 命令契约冻结；§3 魔法数字表冻结；§4 探针契约；§6.1 规则库消费）。

流程：产物校验（不存在/非 .html → exit 2）→ 本地伺服 → 无头 Chromium 两趟
（竖屏 390×844 autoplay 可选 / 横屏 844×390 autoplay=off，各建新 context 隔离静音态与请求记录）
→ 探针+截屏+请求/控制台记账 → 判定 → 写 report.json + 截屏；有 fail → exit 1。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from urllib.parse import urlparse

from . import checks as checks_mod
from .autoplay import drive_autoplay
from .server import serve_directory

# ---- §3 魔法数字表（冻结——改任何一个都要回填 spec 并复跑 gate）-----------------
VIEWPORT_PORTRAIT = {"width": 390, "height": 844}
VIEWPORT_LANDSCAPE = {"width": 844, "height": 390}
DEVICE_EMULATION = {"is_mobile": True, "device_scale_factor": 2}
GOTO_TIMEOUT_MS = 15000          # wait_until="load" 上限
SETTLE_MS = 400                  # load 后留给首帧渲染
VARIANCE_THRESHOLD = 30.0        # 64×64 灰度方差 < 30.0 判空白
DEFAULT_MAX_LOAD_SEC = 2.0
DEFAULT_AUTOPLAY_TIMEOUT_SEC = 45.0  # spec qc.autoplayTimeoutSec
LOCAL_HOSTS = {"127.0.0.1", "localhost"}
# 渠道容器运行时脚本本地桩（§6.1 runtime_stubs；投放时由渠道容器提供，非包体内容）
CONTAINER_STUB_JS = (
    "/* pf-qacore: 渠道容器运行时脚本本地桩（投放时由渠道容器提供，非包体内容） */"
)


# ---- §4 探针契约（PROBE_JS，注入页面；每页面 add_init_script 一次）--------------
PROBE_JS = r"""
(() => {
  if (window.__pfprobe) return;  // 重复注入会二次包装 AudioContext 导致计数失真
  const probe = {
    ready: null, start: null, end: null, endWin: null, first: null, cta: null,
    audio: { created: 0, running: 0 },
    media: { unmuted: 0, playing: 0, playsBeforeFirst: 0 },
    rtc: 0,
  };
  window.__pfprobe = probe;
  const mark = (k) => {
    if (probe[k] === null || probe[k] === undefined) probe[k] = performance.now();
  };
  // pf:* 事件名单（冻结，各取首个时刻）
  const evmap = {
    'pf:ready': 'ready',
    'pf:start': 'start',
    'pf:first-interaction': 'first',
    'pf:cta': 'cta',
  };
  Object.keys(evmap).forEach((ev) => {
    document.addEventListener(ev, () => mark(evmap[ev]));
  });
  document.addEventListener('pf:end', (e) => {
    if (probe.end === null) {
      probe.end = performance.now();
      probe.endWin = !!(e && e.detail && e.detail.win);
    }
  });
  // 首个真实指针时刻（与 pf:first-interaction 先到者占 first）
  const onPtr = () => mark('first');
  document.addEventListener('pointerdown', onPtr, true);
  document.addEventListener('touchstart', onPtr, true);

  // 包装 AudioContext/webkitAudioContext：running 集合大小 = 正在出声的上下文数
  const live = new Set();
  const recomputeRunning = () => {
    let n = 0;
    live.forEach((c) => { try { if (c.state === 'running') n += 1; } catch (e) {} });
    probe.audio.running = n;
  };
  const wrapCtor = (Base, onNew) => {
    if (typeof Base !== 'function') return Base;
    function Wrapped(...args) {
      const inst = new Base(...args);
      onNew(inst);
      return inst;
    }
    Wrapped.prototype = Base.prototype;
    return Wrapped;
  };
  const onAudioCtx = (c) => {
    probe.audio.created += 1;
    live.add(c);
    if (typeof c.addEventListener === 'function') {
      try { c.addEventListener('statechange', recomputeRunning); } catch (e) {}
    }
    recomputeRunning();
  };
  window.AudioContext = wrapCtor(window.AudioContext, onAudioCtx);
  window.webkitAudioContext = wrapCtor(window.webkitAudioContext, onAudioCtx);

  // 包装 RTCPeerConnection/webkitRTCPeerConnection：计数 >0 → CHK03 fail
  const onRtc = () => { probe.rtc += 1; };
  window.RTCPeerConnection = wrapCtor(window.RTCPeerConnection, onRtc);
  window.webkitRTCPeerConnection = wrapCtor(window.webkitRTCPeerConnection, onRtc);

  // 包装 HTMLMediaElement.prototype.play（覆盖 <audio>/<video>/new Audio()）
  const proto = window.HTMLMediaElement && window.HTMLMediaElement.prototype;
  if (proto && typeof proto.play === 'function') {
    const origPlay = proto.play;
    proto.play = function (...args) {
      if (probe.first === null) probe.media.playsBeforeFirst += 1;
      return origPlay.apply(this, args);
    };
  }
  // Python 侧每轮调用重采样未静音媒体元素（最坏值粘住）
  window.__pfprobeSampleMedia = () => {
    let unmuted = 0;
    let playing = 0;
    document.querySelectorAll('audio,video').forEach((el) => {
      try {
        if (!el.muted) unmuted += 1;
        if (!el.paused && !el.ended) playing += 1;
      } catch (e) {}
    });
    probe.media.unmuted = Math.max(probe.media.unmuted, unmuted);
    probe.media.playing = Math.max(probe.media.playing, playing);
  };
})();
"""

_JS_PF_PRESENT = "() => !!window.PF"
_JS_PROBE_INSTALLED = "() => !!window.__pfprobe"
_JS_SAMPLE_MEDIA = "() => { if (window.__pfprobeSampleMedia) window.__pfprobeSampleMedia(); }"
_JS_PROBE_ALL = "() => window.__pfprobe || null"
_JS_HAS_CANVAS = "() => !!document.querySelector('canvas')"


# ---- §6.1 规则库判定输入 -------------------------------------------------------
def _find_rules_file():
    """规则库真源 = channel-rules/channel-rules.json（spec §6.1）。
    解析：自 cwd 与包目录向上各查 6 层（gate 以试点根为 cwd，包在 <根>/python/qacore）。"""
    bases = []
    for start in (os.getcwd(), os.path.dirname(os.path.abspath(__file__))):
        cur = start
        for _ in range(6):
            bases.append(cur)
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
    for base in bases:
        candidate = os.path.join(base, "channel-rules", "channel-rules.json")
        if os.path.isfile(candidate):
            return candidate
    return None


def _load_rules():
    path = _find_rules_file()
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _channel_entry(rules, channel):
    if isinstance(rules, dict):
        return ((rules.get("channels") or {}).get(channel) or {})
    return {}


def channel_max_bytes(rules, channel):
    """规则库无该渠道 → null → CHK01 skip（不假定）。"""
    value = _channel_entry(rules, channel).get("maxBytes")
    return int(value) if isinstance(value, (int, float)) else None


def load_channel_mute_required(rules, channel):
    """取值次序：渠道 runtime > defaults > true；规则库不可读时也从严取 true（spec §6.1）。"""
    runtime_value = (_channel_entry(rules, channel).get("runtime") or {}).get(
        "muteBeforeFirstInteraction")
    if isinstance(runtime_value, bool):
        return runtime_value
    defaults = (rules.get("defaults") or {}) if isinstance(rules, dict) else {}
    default_value = defaults.get("muteBeforeFirstInteraction")
    if isinstance(default_value, bool):
        return default_value
    return True


def load_runtime_stub_scripts(rules, channel):
    """渠道 runtime.injectRelativeScripts 声明的容器运行时相对脚本名（如 mraid.js）。"""
    scripts = (_channel_entry(rules, channel).get("runtime") or {}).get(
        "injectRelativeScripts") or []
    return {os.path.basename(s) for s in scripts if isinstance(s, str) and s}


# ---- 报告/截屏路径（pipeline-contract §3.3 stem 命名裁决，冻结）------------------
def resolve_output_paths(artifact: str, out=None):
    name = os.path.basename(artifact)
    if out:
        report_path = os.path.abspath(out)
        report_dir = os.path.dirname(report_path) or "."
        stem = os.path.splitext(os.path.basename(report_path))[0]
    else:
        stem = os.path.splitext(name)[0]
        report_dir = os.path.dirname(artifact) or "."
        report_path = os.path.join(report_dir, stem + ".report.json")
    return {
        "report": report_path,
        "portrait_png": os.path.join(report_dir, stem + ".png"),
        "landscape_png": os.path.join(report_dir, stem + "-landscape.png"),
    }


def screenshot_variance(path: str) -> float:
    """64×64 灰度方差（spec §3：截屏经 Pillow convert("L").resize((64,64))）。"""
    from PIL import Image

    with Image.open(path) as im:
        gray = im.convert("L").resize((64, 64))
        pixels = list(gray.getdata())
    n = len(pixels)
    mean = sum(pixels) / n
    return sum((p - mean) ** 2 for p in pixels) / n


def _filter_network_noise(raw_errors, blocked_urls):
    """CHK08 网络源噪声过滤（spec §4 隐含前提）：console 消息来源 URL ∈ 本次已 abort
    记账的 blocked 集合 → 剔除（该违规已由 CHK03 记账，不在 CHK08 重复处罚）。
    文本前缀 "Failed to load resource:" 与来源 URL 归属同义等效，一并按 blocked 归属剔除。"""
    kept = []
    for item in raw_errors:
        if item.get("kind") == "pageerror":
            kept.append(item)
            continue
        loc = item.get("url") or ""
        text = item.get("text") or ""
        if loc and loc in blocked_urls:
            continue
        if text.startswith("Failed to load resource:") and loc and loc in blocked_urls:
            continue
        kept.append(item)
    return kept


class _PassRecorder:
    """单趟记账：请求/wire 拦截（§3 本地放行）、WebSocket 阻断记账（§6 CHK03）、
    console/pageerror 原始采集。每趟独立实例（两趟隔离）。"""

    def __init__(self, serve_port: int, artifact_dir: str, stub_scripts):
        self.serve_port = serve_port
        self.artifact_dir = artifact_dir
        self.stub_scripts = set(stub_scripts)
        self.requests = []
        self.external = []
        self.runtime_stubs = []
        self.websocket_urls = []
        self.console_raw = []

    def on_route(self, route, request):
        url = request.url
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        entry = {
            "url": url,
            "method": request.method,
            "resource_type": request.resource_type,
            "status": None,
            "blocked": False,
            "failed": False,
        }
        is_local = host in LOCAL_HOSTS and parsed.port == self.serve_port
        if not is_local:
            entry["blocked"] = True
            entry["failed"] = True
            self.requests.append(entry)
            self.external.append(url)
            route.abort()
            return
        basename = os.path.basename(parsed.path or "")
        if basename and basename in self.stub_scripts and not os.path.isfile(
                os.path.join(self.artifact_dir, basename)):
            # 产物目录内无同名文件 → 空 JS 桩 200 应答；产物自带的同名文件照常透传
            entry["status"] = 200
            entry["stub"] = True
            self.requests.append(entry)
            self.runtime_stubs.append(url)
            route.fulfill(status=200, content_type="application/javascript",
                          body=CONTAINER_STUB_JS)
            return
        self.requests.append(entry)
        route.continue_()

    def on_web_socket(self, ws):
        # 只记账不 close：处理器内 ws.close() 会挂死 load 事件；未 connect_to 的
        # socket 不会真实连接（spec §6 CHK03 实测备注）
        self.requests.append({
            "url": "websocket:" + ws.url,
            "method": "GET",
            "resource_type": "websocket",
            "status": None,
            "blocked": True,
            "failed": False,
        })
        self.websocket_urls.append(ws.url)

    def on_console(self, msg):
        if msg.type == "error":
            try:
                location = msg.location or {}
            except Exception:
                location = {}
            self.console_raw.append({
                "kind": "console",
                "text": msg.text or "",
                "url": (location.get("url") or "") if isinstance(location, dict) else "",
            })

    def on_pageerror(self, exc):
        self.console_raw.append({"kind": "pageerror", "text": str(exc), "url": ""})

    def on_response(self, response):
        for entry in reversed(self.requests):
            if (not entry.get("blocked") and entry.get("status") is None
                    and entry.get("url") == response.url):
                entry["status"] = response.status
                return


def _run_pass(browser, url: str, viewport: dict, screenshot_path: str, *,
              autoplay: bool, autoplay_timeout_sec: float,
              serve_port: int, artifact_dir: str, stub_scripts) -> dict:
    """一趟：新 context（隔离静音态与请求记录）→ 探针注入一次 → 路由/监听 →
    goto(load, 15s) → 400ms 缓冲 → 事实采集 →（竖屏且 --autoplay）驱动试玩 → 截屏。"""
    context = browser.new_context(viewport=viewport, service_workers="block",
                                  **DEVICE_EMULATION)
    try:
        page = context.new_page()
        page.add_init_script(PROBE_JS)  # 每页面一次，防二次包装

        recorder = _PassRecorder(serve_port, artifact_dir, stub_scripts)
        page.route("**/*", recorder.on_route)
        page.route_web_socket("**/*", recorder.on_web_socket)
        page.on("console", recorder.on_console)
        page.on("pageerror", recorder.on_pageerror)
        page.on("response", recorder.on_response)

        def sample_media():
            page.evaluate(_JS_SAMPLE_MEDIA)

        started = time.perf_counter()
        page.goto(url, wait_until="load", timeout=GOTO_TIMEOUT_MS)
        load_ms = int(round((time.perf_counter() - started) * 1000))
        page.wait_for_timeout(SETTLE_MS)

        pf_present = bool(page.evaluate(_JS_PF_PRESENT))
        probe_installed = bool(page.evaluate(_JS_PROBE_INSTALLED))
        sample_media()
        has_canvas = bool(page.evaluate(_JS_HAS_CANVAS))

        autoplay_facts = None
        if autoplay:
            autoplay_facts = drive_autoplay(page, autoplay_timeout_sec, sample_media)

        probe = page.evaluate(_JS_PROBE_ALL) or {}
        page.screenshot(path=screenshot_path)
        variance = screenshot_variance(screenshot_path)

        shot = {
            "viewport": f"{viewport['width']}x{viewport['height']}",
            "load_ms": load_ms,
            "has_canvas": has_canvas,
            "variance": variance,
            "pf_present": pf_present,
            "probe_installed": probe_installed,
            "probe": probe,
        }
        if autoplay_facts is not None:
            shot.update(autoplay_facts)

        return {
            "shot": shot,
            "requests": recorder.requests,
            "external": recorder.external,
            "runtime_stubs": recorder.runtime_stubs,
            "websocket_urls": recorder.websocket_urls,
            "console_raw": recorder.console_raw,
            "pf_present": pf_present,
            "probe_installed": probe_installed,
            "load_ms": load_ms,
            "probe": probe,
        }
    finally:
        context.close()


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qacore", description="M8 质检器：单个 HTML 产物本地质检（唯一裁判）")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="质检单个 HTML 产物")
    run.add_argument("artifact", help="产物 .html 路径")
    run.add_argument("--channel", default="preview", help="渠道名（规则库键，默认 preview）")
    run.add_argument("--out", default=None, help="报告输出路径（截屏随其目录并跟随报告 stem）")
    run.add_argument("--port", type=int, default=0, help="本地伺服端口（默认 0=自动分配）")
    run.add_argument("--max-load-sec", type=float, default=DEFAULT_MAX_LOAD_SEC)
    run.add_argument("--autoplay", action="store_true", help="自动试玩驱动竖屏趟到结束页")
    run.add_argument("--autoplay-timeout", type=float, default=DEFAULT_AUTOPLAY_TIMEOUT_SEC)
    run.add_argument("--require-text", action="append", default=[], help="CHK10 要求文案（可重复）")
    run.add_argument("--require-sprite", action="append", default=[], help="CHK10 要求素材键（可重复）")
    return parser


def main(argv=None) -> int:
    args = _build_arg_parser().parse_args(argv)

    artifact = os.path.abspath(args.artifact)
    # 退出码契约（§2）：0=无 fail（skip 不算）；1=有 fail；2=产物不存在或非 .html
    if not os.path.isfile(artifact):
        print(f"qacore: 产物不存在：{artifact}", file=sys.stderr)
        return 2
    if not artifact.lower().endswith(".html"):
        print(f"qacore: 非 .html 产物（zip 渠道产物暂无法质检）：{artifact}", file=sys.stderr)
        return 2

    artifact_bytes = os.path.getsize(artifact)
    artifact_dir = os.path.dirname(artifact) or "."
    artifact_name = os.path.basename(artifact)
    paths = resolve_output_paths(artifact, args.out)
    os.makedirs(os.path.dirname(paths["report"]) or ".", exist_ok=True)

    rules = _load_rules()
    max_bytes = channel_max_bytes(rules, args.channel)
    mute_required = load_channel_mute_required(rules, args.channel)
    stub_scripts = load_runtime_stub_scripts(rules, args.channel)

    from playwright.sync_api import sync_playwright

    httpd, serve_port = serve_directory(artifact_dir, args.port)
    url = f"http://127.0.0.1:{serve_port}/{artifact_name}"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                portrait = _run_pass(
                    browser, url, VIEWPORT_PORTRAIT, paths["portrait_png"],
                    autoplay=bool(args.autoplay),
                    autoplay_timeout_sec=args.autoplay_timeout,
                    serve_port=serve_port, artifact_dir=artifact_dir,
                    stub_scripts=stub_scripts)
                # 横屏趟以 autoplay=off 运行（§5 冻结：只驱动竖屏趟）
                landscape = _run_pass(
                    browser, url, VIEWPORT_LANDSCAPE, paths["landscape_png"],
                    autoplay=False,
                    autoplay_timeout_sec=args.autoplay_timeout,
                    serve_port=serve_port, artifact_dir=artifact_dir,
                    stub_scripts=stub_scripts)
            finally:
                browser.close()
    finally:
        httpd.shutdown()

    has_autoplay_facts = "hasQcHook" in portrait["shot"]

    requests_merged = list(portrait["requests"]) + list(landscape["requests"])
    external_merged = list(portrait["external"]) + list(landscape["external"])
    runtime_stubs_merged = list(portrait["runtime_stubs"]) + list(landscape["runtime_stubs"])
    websocket_urls = list(portrait["websocket_urls"]) + list(landscape["websocket_urls"])
    blocked_urls = set(external_merged)
    console_errors = _filter_network_noise(
        list(portrait["console_raw"]) + list(landscape["console_raw"]), blocked_urls)
    rtc_total = int((portrait["probe"] or {}).get("rtc") or 0) + \
        int((landscape["probe"] or {}).get("rtc") or 0)

    report = {
        "channel": args.channel,
        "url": url,
        "autoplay": bool(args.autoplay),
        "pf": {
            "present": portrait["pf_present"],
            # 契约：readyMs 无 autoplay 时为 null（pipeline-contract §4）
            "readyMs": (portrait["probe"] or {}).get("ready") if args.autoplay else None,
            "endMs": (portrait["probe"] or {}).get("end"),
            "endWin": (portrait["probe"] or {}).get("endWin"),
        },
        "screenshot": os.path.basename(paths["portrait_png"]),
        "requests": requests_merged,
        "facts": {
            "artifact_bytes": artifact_bytes,
            "channel": args.channel,
            "channel_max_bytes": max_bytes,
            "external_requests": external_merged,
            "runtime_stubs": runtime_stubs_merged,
            "request_count": len(requests_merged),
            "console_errors": [
                f"{item.get('kind')}: {item.get('text')}" for item in console_errors],
            "load_ms": portrait["load_ms"],
            "max_load_sec": args.max_load_sec,
            "autoplay_enabled": bool(args.autoplay),
            "autoplay_timeout_sec": args.autoplay_timeout,
            "pf_present": portrait["pf_present"],
            "viewport_shots": {
                "portrait": portrait["shot"],
                "landscape": landscape["shot"],
            },
            "variance_threshold": VARIANCE_THRESHOLD,
            "required_texts": list(args.require_text),
            "required_sprites": list(args.require_sprite),
            "page_texts": (portrait["shot"].get("page_texts") or [])
            if has_autoplay_facts else [],
            "text_states": (portrait["shot"].get("text_states") or [])
            if has_autoplay_facts else [],
            "text_states_hook": bool(portrait["shot"].get("textStatesHook"))
            if has_autoplay_facts else False,
            "asset_audit": (portrait["shot"].get("asset_audit") or [])
            if has_autoplay_facts else [],
        },
    }

    judgment = dict(report["facts"])
    judgment.update({
        "mute_required": mute_required,
        "probe_installed": portrait["probe_installed"],
        "rtc_total": rtc_total,
        "websocket_urls": websocket_urls,
    })
    report["checks"] = checks_mod.build_checks(judgment)

    with open(paths["report"], "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    statuses = ", ".join(f"{c['id']}={c['status']}" for c in report["checks"])
    print(f"qacore: {artifact_name} [{args.channel}] -> {paths['report']}")
    print(f"qacore: {statuses}")
    return 1 if any(c["status"] == "fail" for c in report["checks"]) else 0
