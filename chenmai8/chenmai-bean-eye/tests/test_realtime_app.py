"""实时线 eval · app 集成（GET /live/stream + demo 页实时入口）。

运行（仓库根）::

    pytest tests/test_realtime_app.py -q

覆盖（端点写法参考 tests/test_app.py 的 httpx ASGI 进程内客户端）：
1. ``GET /live/stream`` MJPEG 流（合成源）：200 + multipart/x-mixed-replace
   头、产出 ≥2 个边界完整的 JPEG part（cv2 可解码、带叠加层）、流结束后
   工作线程随引用计数归零停止；
2. 参数校验：非法 source / ip 缺 url → 400；
3. 源失败语义：USB 设备号不存在 → 503 + 可读排查提示（不 500、不挂死）；
4. 演示页：/demo 含「实时」入口（href=/live/stream）且仍零外链。

全程离线（实时源用内置合成器；不打外网、无摄像头依赖）。
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import cv2
import httpx
import numpy as np
import pytest

from beaneye.app import create_app


class _SyncASGIClient:
    """同步测试外观：内部 ``httpx.AsyncClient + ASGITransport``（tests/test_app.py 同款）。"""

    def __init__(self, app) -> None:
        import asyncio

        self._loop = asyncio.new_event_loop()
        self._app = app
        self._client: httpx.AsyncClient | None = None

    def __enter__(self) -> "_SyncASGIClient":
        transport = httpx.ASGITransport(app=self._app)
        client = httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=120.0)
        self._loop.run_until_complete(client.__aenter__())
        self._client = client
        return self

    def __exit__(self, *exc) -> None:
        assert self._client is not None
        self._loop.run_until_complete(self._client.__aexit__(*exc))
        self._loop.close()
        self._client = None

    def get(self, url: str, **kw) -> httpx.Response:
        return self._loop.run_until_complete(self._client.get(url, **kw))


@pytest.fixture()
def app(tmp_path: Path):
    return create_app(data_root=tmp_path / "data", allow_probe=False)


def _split_mjpeg(body: bytes) -> list[bytes]:
    """按 boundary 切 MJPEG body → JPEG 字节列表。"""
    parts = re.split(rb"--frame\r\n", body)
    jpegs: list[bytes] = []
    for part in parts:
        if b"Content-Type: image/jpeg" not in part:
            continue
        header, _, payload = part.partition(b"\r\n\r\n")
        payload = payload.rstrip(b"\r\n")
        if payload.startswith(b"\xff\xd8"):
            jpegs.append(payload)
    return jpegs


def test_live_stream_mjpeg_synth(app, tmp_path: Path):
    with _SyncASGIClient(app) as client:
        r = client.get(
            "/live/stream",
            params={"source": "synth", "max_frames": 2, "width": 640, "height": 480,
                    "n_beans_max": 6, "seed": 7},
        )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("multipart/x-mixed-replace")
    assert "boundary=frame" in r.headers["content-type"]

    jpegs = _split_mjpeg(r.content)
    assert len(jpegs) >= 2, f"MJPEG part 不足: {len(jpegs)}"
    for jpg in jpegs:
        img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
        assert img is not None and img.ndim == 3 and img.shape[:2] == (480, 640)
        assert len(jpg) > 4 * 1024, "JPEG 过小（可能无画面）"

    # 流结束（max_frames 用尽）→ 客户端注销 → 工作线程随之停止（不泄漏）
    hub = app.state.live_hub
    deadline = time.time() + 5.0
    while time.time() < deadline and hub.stats()["running"]:
        time.sleep(0.1)
    assert hub.stats()["running"] is False
    assert hub.stats()["clients"] == 0


def test_live_stream_param_validation(app):
    with _SyncASGIClient(app) as client:
        r = client.get("/live/stream", params={"source": "nonsense"})
        assert r.status_code == 400 and "source" in r.json()["error"]
        r = client.get("/live/stream", params={"source": "ip", "url": ""})
        assert r.status_code == 400 and "url" in r.json()["error"]


def test_live_stream_usb_failure_returns_503(app):
    with _SyncASGIClient(app) as client:
        r = client.get("/live/stream", params={"source": "usb", "index": 61})
    assert r.status_code == 503
    assert "无法打开 USB 相机" in r.json()["error"]
    # 失败后 hub 不留运行线程
    assert app.state.live_hub.stats()["running"] is False


def test_demo_page_has_live_entry(app):
    with _SyncASGIClient(app) as client:
        r = client.get("/demo")
    assert r.status_code == 200
    html = r.text
    assert "实时" in html
    assert 'href="/live/stream"' in html
    # 零外链纪律不被增量破坏（与 tests/test_app.py 同一口径）
    assert not re.search(r'(?:src|href)\s*=\s*["\']https?://', html, re.IGNORECASE)
    assert not re.search(r"url\(\s*['\"]?https?://", html, re.IGNORECASE)
