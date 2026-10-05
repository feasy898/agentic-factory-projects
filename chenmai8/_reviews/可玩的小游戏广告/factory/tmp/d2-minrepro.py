# python 侧对照：route_web_socket 注册与产物页 AudioContext 初始态。
import sys, threading, http.server, functools, json
from playwright.sync_api import sync_playwright

ART = r"tmp/diff/oracle-matrix/golden-match3/applovin/en/index.html"
html = open(ART, "rb").read().decode("utf-8")

RECORDER = """(() => {
  window.__diag = [];
  const wrap = (name) => {
    const Ctor = window[name];
    if (typeof Ctor !== 'function') return;
    const Wrapped = function (...args) {
      const ctx = new Ctor(...args);
      window.__diag.push({ at: Math.round(performance.now()), state: ctx.state });
      return ctx;
    };
    Wrapped.prototype = Ctor.prototype;
    try { Object.defineProperty(window, name, { value: Wrapped, configurable: true, writable: true }); } catch (e) {}
  };
  wrap('AudioContext');
})();"""

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html.encode("utf-8")))); self.end_headers()
        self.wfile.write(html.encode("utf-8"))
    def log_message(self, *a): pass

srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{port}/index.html"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for variant in ["bare", "ws"]:
        for i in range(2):
            ctx = browser.new_context(viewport={"width":390,"height":844}, is_mobile=True, device_scale_factor=2, service_workers="block")
            page = ctx.new_page()
            page.add_init_script(RECORDER)
            if variant == "ws":
                page.route_web_socket("**/*", lambda ws: None)
            page.goto(url, wait_until="load", timeout=15000)
            page.wait_for_timeout(600)
            diag = page.evaluate("() => window.__diag")
            print(f"py {variant} r{i}: ctxCreations={json.dumps(diag)}")
            ctx.close()
    browser.close()
srv.shutdown()
