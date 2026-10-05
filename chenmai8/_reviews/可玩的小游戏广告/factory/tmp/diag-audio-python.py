# 诊断脚本（factory/tmp，非 oracle、非产品）：用 repo venv 的 playwright-python
# 纯观察 pullpin.html 的 AudioContext 创建态——回答"created-running 翻转是否
# 只在 node 驱动侧出现"。repo/ 全程只读；本脚本不合成手势。
import sys
import time
import functools
import http.server
import os
import threading

sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

# 与 oracle qacore 的 ArtifactServer 同款：python http.server 挂产物目录。
class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

class _ThreadingTCPServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

def start_server(docroot):
    handler = functools.partial(_QuietHandler, directory=os.path.abspath(docroot))
    httpd = _ThreadingTCPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, httpd.server_address[1]

RECORDER = """(() => {
  window.__diag = { transitions: [], pointerAt: null };
  document.addEventListener('pointerdown', () => {
    if (window.__diag.pointerAt === null) window.__diag.pointerAt = performance.now();
  }, true);
  const wrap = (name) => {
    const Ctor = window[name];
    if (typeof Ctor !== 'function') return;
    const Wrapped = function (...args) {
      const ctx = new Ctor(...args);
      const rec = () => window.__diag.transitions.push({
        at: Math.round(performance.now()), state: ctx.state });
      rec();
      try { ctx.addEventListener('statechange', rec); } catch (e) {}
      return ctx;
    };
    Wrapped.prototype = Ctor.prototype;
    try { Object.defineProperty(window, name, { value: Wrapped, configurable: true, writable: true }); } catch (e) {}
  };
  wrap('AudioContext');
  wrap('webkitAudioContext');
})();"""

ARTIFACT_PATH = sys.argv[1]
ROUNDS = int(sys.argv[2]) if len(sys.argv) > 2 else 8
import pathlib
artifact = pathlib.Path(ARTIFACT_PATH).resolve()
httpd, port = start_server(str(artifact.parent))
URL = f"http://127.0.0.1:{port}/{artifact.name}"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for r in range(ROUNDS):
        ctx = browser.new_context(
            viewport={"width": 390, "height": 844},
            is_mobile=True, device_scale_factor=2, service_workers="block",
        )
        page = ctx.new_page()
        page.add_init_script(RECORDER)
        page.goto(URL, wait_until="load", timeout=15000)
        page.wait_for_timeout(2500)
        diag = page.evaluate("() => window.__diag")
        trs = "; ".join(f"{t['at']}ms:{t['state']}" for t in diag["transitions"])
        print(f"[py r{r}] transitions=[{trs}] pointerAt={diag['pointerAt']}")
        ctx.close()
    browser.close()
