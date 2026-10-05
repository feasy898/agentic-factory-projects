# python 侧同形抓取（--ws 拦截 + 产物页）
import threading, http.server, json
from playwright.sync_api import sync_playwright
html = open("tmp/diff/oracle-matrix/golden-match3/applovin/en/index.html", "rb").read().decode("utf-8")
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
    ctx = browser.new_context(viewport={"width":390,"height":844}, is_mobile=True, device_scale_factor=2, service_workers="block")
    page = ctx.new_page()
    page.route_web_socket("**/*", lambda ws: None)
    page.goto(url, wait_until="load", timeout=15000)
    page.wait_for_timeout(600)
    probe = page.evaluate("() => ({ wsMocked: typeof window.__pwWebSocketDispatch, binding: typeof window.__pwWebSocketBinding })")
    print("probe:", json.dumps(probe))
    browser.close()
srv.shutdown()
