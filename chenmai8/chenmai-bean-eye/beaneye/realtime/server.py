"""实时线 · MJPEG 推流中枢（beaneye.realtime.server）。

:class:`LiveStreamHub` 把「源 → RealtimeEngine → overlay → JPEG」跑在**单个
后台工作线程**，多客户端共享最新标注帧（MJPEG，multipart/x-mixed-replace）：

- ``register_client()`` 打开源（失败抛 :class:`AcquisitionError`，调用方转
  503）并拉起工作线程；引用计数归零即停线程（源保持打开，下个客户端零
  重开成本；合成源也不必重新合成）；
- 工作线程：读帧 → 引擎处理 → 叠加 → JPEG 编码 → 单槽暂存 + 条件变量通知；
  连续无帧达阈值自动退出（相机拔出/流断开），客户端下次连接时重启；
- ``stream(max_frames)`` 生成器：yield 边界完整的 MJPEG part；``max_frames``
  限制产出帧数（0=不限，供测试与 curl 试流用）。

线程模型：引擎（含 RulesV0 滚动窗口）只被工作线程触碰，无需加锁；JPEG 槽
用 ``threading.Condition`` 保护。FastAPI 侧同步生成器由 Starlette 放线程池
迭代，不阻塞事件循环。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import cv2

from beaneye.acquisition.base import AcquisitionError
from beaneye.realtime.engine import RealtimeConfig, RealtimeEngine
from beaneye.realtime.overlay import draw_overlay
from beaneye.realtime.sources import IPCameraSource, RealtimeSource, SynthVideoSource, USBCameraSource

__all__ = ["LiveParams", "LiveStreamHub", "MJPEG_BOUNDARY"]

MJPEG_BOUNDARY = "frame"

_SOURCES = ("synth", "usb", "ip")
_NO_FRAME_EXIT = 90        # 连续无帧退出阈值（×50ms ≈ 4.5s）
_WORKER_TICK_S = 0.008     # 工作线程节流（防无节拍合成源占满核）
_JPEG_WAIT_S = 20.0        # 客户端等下一帧的超时（超时结束本次流）


@dataclass(frozen=True)
class LiveParams:
    """一次实时流的源与旋钮参数（同参数重启 = 复用源）。"""

    source: str = "synth"      # synth | usb | ip
    index: int = 0             # usb 设备号
    url: str = ""              # ip 流地址（http(s) MJPEG）
    width: int = 1280
    height: int = 720
    downscale: float = 1.0
    skip: int = 0
    seed: int = 20261002       # 合成源种子
    n_beans_max: int = 20      # 合成源豆数上限（下限固定 6）

    def validate(self) -> None:
        if self.source not in _SOURCES:
            raise ValueError(f"source 只能是 {'/'.join(_SOURCES)}，得到 {self.source!r}")
        if self.source == "ip" and not self.url.strip():
            raise ValueError("source=ip 需要 url（手机推流的 http(s) MJPEG 地址）")
        RealtimeConfig(downscale=self.downscale, skip=self.skip)  # 旋钮合法性复用引擎校验

    def build_source(self) -> RealtimeSource:
        """按参数构造采集源（不打开；打开在 ensure_started 中做并抛可读错误）。"""
        if self.source == "usb":
            return USBCameraSource(self.index, width=self.width, height=self.height)
        if self.source == "ip":
            return IPCameraSource(self.url.strip())
        return SynthVideoSource(
            width=int(self.width), height=int(self.height), seed=int(self.seed),
            n_beans_min=6, n_beans_max=max(6, int(self.n_beans_max)),
        )


class LiveStreamHub:
    """实时标注 MJPEG 推流中枢（单工作线程 + 最新帧单槽 + 客户端引用计数）。"""

    def __init__(self, *, jpeg_quality: int = 80) -> None:
        self.jpeg_quality = int(jpeg_quality)
        self._cond = threading.Condition()
        self._jpeg: bytes | None = None
        self._seq = 0                # 已产出标注帧序（单调增）
        self._clients = 0
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self._params: LiveParams | None = None
        self._source: RealtimeSource | None = None
        self._engine: RealtimeEngine | None = None
        self._last_error = ""

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def ensure_started(self, params: LiveParams) -> None:
        """按参数确保源已打开（失败抛 :class:`AcquisitionError` / ``ValueError``）。

        同参数已在跑 → no-op；参数变化 → 停旧起新（源重建）。
        """
        params.validate()
        with self._cond:
            if self._params == params and (self._worker is not None or self._source is not None):
                return
        # 换参数：先停旧（线程 + 源）
        self.stop()
        source = params.build_source()
        source.open()  # 打不开在这里抛（信息可读：相机号/URL 排查提示）
        engine = RealtimeEngine(
            cfg=RealtimeConfig(downscale=params.downscale, skip=params.skip),
            scan_id=f"live_{params.source}",
        )
        with self._cond:
            self._params = params
            self._source = source
            self._engine = engine
            self._stop = threading.Event()
            self._last_error = ""

    def register_client(self) -> None:
        """客户端接入（引用计数 +1；拉起工作线程）。"""
        with self._cond:
            self._clients += 1
            need_worker = self._worker is None and self._source is not None
        if need_worker:
            self._start_worker()

    def unregister_client(self) -> None:
        """客户端断开（引用计数归零即停线程，源保持打开以便下次零成本复用）。"""
        with self._cond:
            self._clients = max(0, self._clients - 1)
            last = self._clients == 0
        if last:
            self.stop_worker()

    def stop_worker(self) -> None:
        """停工作线程（源保持打开）。"""
        with self._cond:
            worker = self._worker
            self._worker = None
        if worker is not None:
            self._stop.set()
            worker.join(timeout=5.0)

    def stop(self) -> None:
        """全停：线程 + 关闭源（应用 shutdown / 换参数用）。"""
        self.stop_worker()
        with self._cond:
            source = self._source
            self._source = None
            self._engine = None
            self._params = None
        if source is not None:
            source.close()

    # ------------------------------------------------------------------
    # 状态读取
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """当前推流状态（测试与调试观测用）。"""
        with self._cond:
            return {
                "running": self._worker is not None and self._worker.is_alive(),
                "clients": self._clients,
                "seq": self._seq,
                "source": self._params.source if self._params else None,
                "last_error": self._last_error,
            }

    def latest_jpeg(self, *, after_seq: int = 0, timeout: float = _JPEG_WAIT_S) -> tuple[int, bytes] | None:
        """等一帧比 ``after_seq`` 新的标注 JPEG；超时/无源返回 None。"""
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._seq <= after_seq:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self._cond.wait(remaining):
                    return None
            return self._seq, self._jpeg  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # 工作线程
    # ------------------------------------------------------------------

    def _start_worker(self) -> None:
        with self._cond:
            if self._worker is not None or self._source is None:
                return
            self._stop = threading.Event()
            worker = threading.Thread(target=self._worker_loop, name="beaneye-live", daemon=True)
            self._worker = worker
        worker.start()

    def _worker_loop(self) -> None:
        """读帧 → 引擎 → 叠加 → JPEG 单槽更新 + 通知（持续到 stop / 源持续无帧）。"""
        stop = self._stop
        misses = 0
        while not stop.is_set():
            with self._cond:
                source, engine = self._source, self._engine
            if source is None or engine is None:
                break
            frame = source.read_frame()
            if frame is None:
                misses += 1
                if misses >= _NO_FRAME_EXIT:
                    with self._cond:
                        self._last_error = f"源连续 {_NO_FRAME_EXIT} 拍无帧，工作线程退出"
                    break
                stop.wait(0.05)
                continue
            misses = 0
            try:
                result = engine.process(frame)
                vis = draw_overlay(frame, result)
                jpeg = encode_jpeg(vis, quality=self.jpeg_quality)
            except Exception as exc:  # noqa: BLE001 — 单帧失败不拖垮推流
                with self._cond:
                    self._last_error = f"{exc.__class__.__name__}: {exc}"
                stop.wait(0.2)
                continue
            with self._cond:
                self._jpeg = jpeg
                self._seq += 1
                self._cond.notify_all()
            stop.wait(_WORKER_TICK_S)

    # ------------------------------------------------------------------
    # MJPEG 生成器
    # ------------------------------------------------------------------

    def stream(self, *, max_frames: int = 0):
        """MJPEG part 生成器（multipart/x-mixed-replace；接入 FastAPI StreamingResponse）。

        ``max_frames``：最多产出帧数（0=不限）。接入即注册客户端（拉起工作
        线程），生成器结束/断开自动注销（引用计数归零停线程）。
        """
        self.register_client()
        boundary = MJPEG_BOUNDARY.encode()
        seq = 0
        sent = 0
        try:
            while max_frames <= 0 or sent < max_frames:
                got = self.latest_jpeg(after_seq=seq)
                if got is None:
                    break  # 超时无新帧（源已停/失败）→ 结束本次流
                seq, jpeg = got
                yield (
                    b"--" + boundary + b"\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                    + jpeg + b"\r\n"
                )
                sent += 1
        finally:
            self.unregister_client()


def encode_jpeg(img_bgr: "np.ndarray", *, quality: int = 80) -> bytes:
    """BGR → JPEG 字节（imencode 字节缓冲；失败抛 :class:`AcquisitionError`）。"""
    ok, buf = cv2.imencode(".jpg", img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise AcquisitionError("JPEG 编码失败")
    return buf.tobytes()
