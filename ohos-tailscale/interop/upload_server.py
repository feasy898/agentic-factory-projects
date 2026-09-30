#!/usr/bin/env python3
"""hk-gateway 结果回传收件箱（一次性令牌，仅写不读）。部署于 /srv/inbox/upload_server.py。"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import os
import urllib.parse

TOKEN = os.environ.get("HMTOKEN", "unset")
DST = "/srv/inbox"


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        parts = self.path.strip("/").split("/")
        if len(parts) != 3 or parts[0] != "upload" or parts[1] != TOKEN:
            self.send_error(403)
            return
        name = os.path.basename(urllib.parse.unquote(parts[2]))
        if not name:
            self.send_error(400)
            return
        n = int(self.headers.get("Content-Length", "0") or 0)
        if n > 512 * 1024 * 1024:
            self.send_error(413)
            return
        os.makedirs(DST, exist_ok=True)
        with open(os.path.join(DST, name), "wb") as f:
            while n > 0:
                chunk = self.rfile.read(min(65536, n))
                n -= len(chunk)
                if not chunk:
                    break
                f.write(chunk)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8090), H).serve_forever()
