"""本地静态伺服（SPEC §1：本地伺服是真实 HTTP，这不算 mock）。"""

import functools
import http.server
import threading


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # 静默访问日志，避免污染 CLI 输出
        pass


class ArtifactServer:
    """对产物所在目录起 127.0.0.1 线程化静态伺服；port=0 取临时端口。"""

    def __init__(self, directory: str, port: int = 0):
        handler = functools.partial(_QuietHandler, directory=directory)
        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        try:
            self._httpd.shutdown()
            self._httpd.server_close()
        except Exception:
            pass

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
        return False
