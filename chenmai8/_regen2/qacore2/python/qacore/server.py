"""本地 HTTP 伺服（spec §1：本地伺服是真实 HTTP，不算 mock）。

只绑 127.0.0.1；默认 port=0 由操作系统分配，qacore 以实际端口做"本地放行"判定
（spec §3：hostname ∈ {127.0.0.1, localhost} 且端口=伺服端口，其余一律 abort 记入 external）。
"""

from __future__ import annotations

import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class _QuietHandler(SimpleHTTPRequestHandler):
    """静默访问日志（路由记账在 Playwright 侧完成，避免双份事实）。"""

    def log_message(self, format, *args):  # noqa: A002 - 标准库签名
        pass


def serve_directory(directory: str, port: int = 0):
    """在 127.0.0.1:port 伺服 directory；返回 (httpd, 实际端口)。调用方负责 shutdown。"""
    handler = functools.partial(_QuietHandler, directory=directory)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, name="qacore-serve", daemon=True)
    thread.start()
    return httpd, httpd.server_address[1]
