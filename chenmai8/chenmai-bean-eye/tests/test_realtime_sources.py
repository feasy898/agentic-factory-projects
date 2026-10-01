"""实时线 eval · 采集源（beaneye.realtime.sources）。

运行（仓库根）::

    pytest tests/test_realtime_sources.py -q

覆盖：
1. 协议一致性：三实现 + 鸭子类型替身都满足 :class:`RealtimeSource`
   （runtime_checkable）；
2. USB 源：打不开时抛 :class:`AcquisitionError` 且报错信息给出排查入口与
   合成源替代提示（无相机阶段优雅报错，非 traceback）；
3. IP 源：URL 校验（空/非 http(s) 即拒）；本地临时 MJPEG 服务端到端——
   打开、连续解码、帧序号前进且出现「跳帧」（丢积压只留最新的可观测证据），
   全程 127.0.0.1 不打外网；丢帧策略本身用假 cap 确定性单测；
4. 合成源：打开→循环帧（pool 周期性重复）→真值随帧可得→关闭后读取报错。

全部离线：无摄像头、无外网（IP 源测试用进程内 MJPEG 服务器）。
"""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import cv2
import numpy as np
import pytest

from beaneye.acquisition.base import AcquisitionError
from beaneye.realtime.sources import (
    IPCameraSource,
    RealtimeSource,
    SynthVideoSource,
    USBCameraSource,
    drain_and_retrieve,
)


# ---------------------------------------------------------------------------
# 1. 协议一致性
# ---------------------------------------------------------------------------


class _DuckSource:
    """满足协议的最小鸭子实现（不继承任何基类）。"""

    def open(self) -> None: ...
    def read_frame(self) -> np.ndarray | None:
        return None

    def close(self) -> None: ...


def test_protocol_conformance():
    for src in (
        _DuckSource(),
        USBCameraSource(0),
        IPCameraSource("http://example.invalid/video"),
        SynthVideoSource(width=320, height=256, pool=1),
    ):
        assert isinstance(src, RealtimeSource)


# ---------------------------------------------------------------------------
# 2. USB 源失败语义
# ---------------------------------------------------------------------------


def test_usb_open_failure_clear_message():
    src = USBCameraSource(61, width=640, height=480)  # 构造不打开
    with pytest.raises(AcquisitionError) as ei:
        src.open()
    msg = str(ei.value)
    assert "无法打开 USB 相机" in msg
    assert "61" in msg  # 报错带设备号
    assert "SynthVideoSource" in msg  # 给出无硬件替代源提示
    src.close()  # 幂等：失败后 close 不抛


def test_usb_rejects_negative_index():
    with pytest.raises(AcquisitionError):
        USBCameraSource(-1)


# ---------------------------------------------------------------------------
# 3a. IP 源：URL 校验 + 丢帧策略（假 cap 确定性单测）
# ---------------------------------------------------------------------------


def test_ip_source_rejects_bad_url():
    with pytest.raises(AcquisitionError):
        IPCameraSource("")
    with pytest.raises(AcquisitionError):
        IPCameraSource("ftp://x/video")
    src = IPCameraSource("http://127.0.0.1:9/video")  # discard 端口：连接拒绝
    with pytest.raises(AcquisitionError) as ei:
        src.open()
    assert "无法打开 IP 相机流" in str(ei.value)
    assert "MJPEG" in str(ei.value)


class _FakeCap:
    """假 VideoCapture：预置积压帧队列 + 一次「等新帧」的慢 grab。

    grab()/retrieve() 语义与 cv2 一致：grab() 只推进（积压帧立即返回；
    只剩「实时帧」时 sleep ``live_delay`` 模拟等新帧），retrieve() 取回
    **最近一次 grab 到的那帧**（cv2 的 grab→retrieve 配对语义）。供
    :func:`drain_and_retrieve` 的确定性单测。
    """

    def __init__(self, frames: list[np.ndarray], live_delay: float = 0.06) -> None:
        self.frames = list(frames)
        self.live_delay = float(live_delay)
        self.n_grabs = 0
        self._last: np.ndarray | None = None  # 最近一次 grab 的帧

    def grab(self) -> bool:
        self.n_grabs += 1
        if len(self.frames) > 1:
            self._last = self.frames.pop(0)  # 积压帧：立即推进（存为待取帧）
            return True
        if len(self.frames) == 1:
            time.sleep(self.live_delay)  # 等新帧：慢返回
            self._last = self.frames[0]
            return True
        return False

    def retrieve(self) -> tuple[bool, np.ndarray | None]:
        if self._last is None:
            return False, None
        return True, self._last


class _ScriptedClock:
    """脚本时钟：每次调用返回「上次 + 下一份增量」（注入 drain 策略，确定性）。"""

    def __init__(self, deltas) -> None:
        self._deltas = list(deltas)
        self._i = 0
        self.now = 0.0

    def __call__(self) -> float:
        self.now += self._deltas[min(self._i, len(self._deltas) - 1)]
        self._i += 1
        return self.now


def test_drain_policy_drops_backlog_keeps_latest():
    # 脚本时钟：前 9 次 grab「瞬时」（积压帧），第 10 次「慢」（等新帧）。
    # 每次 grab 迭代消耗两次读钟（t0 与 took 各一次），9 次瞬时迭代需 18 份快增量。
    clock = _ScriptedClock([0.001] * 18 + [0.5] * 4)
    frames = [np.full((4, 4, 3), k, dtype=np.uint8) for k in range(10)]
    cap = _FakeCap(frames, live_delay=0.0)
    out = drain_and_retrieve(cap, grab_slow_s=0.02, max_backlog=100, monotonic=clock)
    assert out is not None and int(out[0, 0, 0]) == 9  # 丢 9 帧积压，只留最新
    assert cap.n_grabs == 10  # 9 次积压丢弃 + 1 次慢取

    clock2 = _ScriptedClock([0.001] * 8)  # 全部「瞬时」grab
    cap2 = _FakeCap([np.full((4, 4, 3), k, dtype=np.uint8) for k in range(10)], live_delay=0.0)
    out2 = drain_and_retrieve(cap2, grab_slow_s=0.02, max_backlog=3, monotonic=clock2)
    assert out2 is not None and int(out2[0, 0, 0]) == 3  # 丢帧上限 3 生效（丢 f0-f2，取回最新 f3）
    assert cap2.n_grabs == 4  # 3 次积压丢弃 + 第 4 次 grab 后触发上限、retrieve 取回


def test_drain_policy_returns_none_on_stream_end():
    cap = _FakeCap([], live_delay=0.0)
    assert drain_and_retrieve(cap, grab_slow_s=0.02, max_backlog=4) is None


# ---------------------------------------------------------------------------
# 3b. IP 源端到端：本地临时 MJPEG 服务器（127.0.0.1，不打外网）
# ---------------------------------------------------------------------------


class _MJPEGServer(HTTPServer):
    """进程内 MJPEG 推流服务器：帧计数编码进 B 通道（k mod 256）。"""

    def __init__(self, n_frames: int = 4096) -> None:
        self.frames: list[bytes] = []
        for k in range(64):  # 64 帧循环；B 通道编码帧号（k*4 mod 256）
            img = np.zeros((120, 160, 3), dtype=np.uint8)
            img[:, :, 0] = (k * 4) % 256  # B
            img[:, :, 1] = 40
            img[:, :, 2] = 90
            ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
            assert ok
            self.frames.append(buf.tobytes())
        self.running = True
        super().__init__(("127.0.0.1", 0), _MJPEGHandler)


class _MJPEGHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 — http.server 约定
        server: _MJPEGServer = self.server  # type: ignore[assignment]
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        k = 0
        try:
            while server.running:
                jpg = server.frames[k % len(server.frames)]
                self.wfile.write(
                    b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
                )
                self.wfile.flush()
                k += 1
                time.sleep(0.001)  # ~1000fps 洪泛：客户端必积压 → 必跳帧
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass

    def log_message(self, *args) -> None:  # 静默
        pass


@pytest.fixture()
def mjpeg_server():
    server = _MJPEGServer()
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield server
    server.running = False
    server.shutdown()
    server.server_close()


def test_ip_source_local_mjpeg_stream_and_frame_skip(mjpeg_server):
    host, port = mjpeg_server.server_address
    src = IPCameraSource(f"http://{host}:{port}/video", max_backlog=8)
    src.open()
    try:
        nums: list[int] = []
        for _ in range(8):
            frame = src.read_frame()
            assert frame is not None and frame.shape == (120, 160, 3)
            nums.append(int(frame[0, 0, 0]) // 4)  # 解码帧号（k*4 mod 256 → k mod 64）
        # 帧序号单调前进（mod 64 环上不断推进，绝不回退/重复停滞）
        for a, b in zip(nums, nums[1:]):
            assert (b - a) % 64 >= 1
        # 洪泛推流 + 丢积压策略：8 拍内至少出现一次 ≥2 的跳帧（留最新的证据）
        assert max((b - a) % 64 for a, b in zip(nums, nums[1:])) >= 2, nums
    finally:
        src.close()


# ---------------------------------------------------------------------------
# 4. 合成源
# ---------------------------------------------------------------------------


def test_synth_source_cycles_with_truth(tmp_path=None):
    src = SynthVideoSource(width=480, height=360, n_beans_min=4, n_beans_max=6, pool=2, seed=41)
    with src:
        assert len(src.trays) == 2 and src.trays[0].beans  # 真值随帧可得
        f0 = src.read_frame()
        f1 = src.read_frame()
        f2 = src.read_frame()
        assert f0.shape == (360, 480, 3) and f0.dtype == np.uint8
        assert not np.array_equal(f0, f1)  # 换盘 → 画面不同
        assert np.array_equal(f0, f2)  # pool 周期循环（确定性种子）
        f0[0, 0] = 9  # 消费者可安全改写（返回拷贝）
        assert src.trays[0].top_bgr[0, 0, 0] != 9
    with pytest.raises(AcquisitionError):  # 关闭后读取报错（而非静默）
        src.read_frame()
    src.close()  # 幂等


def test_synth_source_rejects_tiny_canvas():
    with pytest.raises(AcquisitionError):
        SynthVideoSource(width=100, height=100)
