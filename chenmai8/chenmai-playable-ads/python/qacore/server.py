"""本地静态伺服器：把产物所在目录挂到 127.0.0.1 的临时端口上，供无头浏览器访问。"""
from __future__ import annotations

import functools
import http.server
import os
import socketserver
import threading


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """不向 stderr 打访问日志的静态文件处理器。"""

    def log_message(self, fmt: str, *args) -> None:  # noqa: A002 - 标准库签名
        pass


class _ThreadingTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class ArtifactServer:
    """以产物所在目录为文档根，伺服在 127.0.0.1 上（默认端口 0 = 系统分配）。"""

    def __init__(self, docroot: str, port: int = 0):
        self._docroot = os.path.abspath(docroot)
        handler = functools.partial(_QuietHandler, directory=self._docroot)
        self._httpd = _ThreadingTCPServer(("127.0.0.1", port), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self.port = int(self._httpd.server_address[1])

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def url_for(self, filename: str) -> str:
        return f"{self.base_url}/{filename.replace(os.sep, '/')}"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    def __enter__(self) -> "ArtifactServer":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
