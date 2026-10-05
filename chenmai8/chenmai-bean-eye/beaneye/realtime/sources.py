"""实时线 · 逐帧采集源（beaneye.realtime.sources）。

:func:`RealtimeSource` 协议（打开 / 逐帧读 / 关闭，帧为 numpy BGR）下三实现：

- :class:`USBCameraSource` —— ``cv2.VideoCapture(index)`` 单相机（Windows 缺省
  CAP_DSHOW 后端，与 :mod:`beaneye.acquisition.usb` 同款）；打不开时抛
  :class:`AcquisitionError`，报错信息给出排查与替代源提示；
- :class:`IPCameraSource` —— 手机推流 http(s) MJPEG URL 直接交给
  ``cv2.VideoCapture(url, CAP_FFMPEG)``；用「读到积压就丢帧只留最新」策略
  控延迟（:func:`drain_and_retrieve`，见函数 docstring）；
- :class:`SynthVideoSource` —— 用 :mod:`beaneye.synth` 铺盘合成器预合成
  少量托盘帧循环播放，无硬件开发与测试用（确定性种子，帧含四角 ArUco）。

读取约定：``read_frame()`` 返回 ``numpy BGR (H,W,3) uint8``；**返回 None 表示
本拍无帧**（流结束 / 读帧瞬时失败），由上层（引擎/演示循环）决定重试或退出——
与「打开失败即抛错」区分开。消费者不得修改返回的数组内容（实现可能返回内部
缓冲的拷贝/引用混合体）；实现侧保证每次返回的数组不被后续读取复用改写。

图像 IO 与错误体系沿用 :mod:`beaneye.acquisition.base`（中文路径安全的
imencode/imdecode 与 :class:`AcquisitionError`）。
"""

from __future__ import annotations

import time
from typing import Callable, Protocol, runtime_checkable

import cv2
import numpy as np

from beaneye.acquisition.base import AcquisitionError
from beaneye.synth.compose import SynthTray, compose_tray
from beaneye.synth.config import ComposeConfig

__all__ = [
    "RealtimeSource",
    "USBCameraSource",
    "IPCameraSource",
    "SynthVideoSource",
    "drain_and_retrieve",
]


# ---------------------------------------------------------------------------
# 协议
# ---------------------------------------------------------------------------


@runtime_checkable
class RealtimeSource(Protocol):
    """实时采集源协议：打开 / 逐帧读（BGR）/ 关闭。"""

    def open(self) -> None:
        """打开源；失败抛 :class:`AcquisitionError`（信息可读、可排查）。"""
        ...

    def read_frame(self) -> np.ndarray | None:
        """读一帧 BGR；本拍无帧（流结束/瞬时失败）返回 None（不抛错）。"""
        ...

    def close(self) -> None:
        """释放资源；可重复调用（幂等）。"""
        ...


# ---------------------------------------------------------------------------
# USB 相机
# ---------------------------------------------------------------------------


class USBCameraSource:
    """USB 单相机实时源（实时模式单面拍摄，只需一路画面）。

    Windows 缺省 DirectShow 后端（与 ``beaneye.acquisition.UsbSource`` 同款、
    同坑位：MSMF 后端开相机慢且部分设备黑帧）。打不开时报错信息给出：设备号
    核对、``python -m beaneye.acquisition.usb --list-cams`` 探测入口、以及
    无硬件阶段可改用的合成源。
    """

    def __init__(
        self,
        index: int = 0,
        *,
        width: int | None = None,
        height: int | None = None,
        backend: str = "dshow",
    ) -> None:
        if int(index) < 0:
            raise AcquisitionError(f"USB 相机设备号必须 >= 0，得到 {index!r}")
        if backend not in ("dshow", "any", "msmf"):
            raise AcquisitionError(
                f"backend 只能是 dshow/any/msmf，得到 {backend!r}"
            )
        self.index = int(index)
        self.width = int(width) if width else None
        self.height = int(height) if height else None
        self.backend = backend
        self._cap: cv2.VideoCapture | None = None

    # -- RealtimeSource -----------------------------------------------------
    def open(self) -> None:
        """打开相机；失败抛 :class:`AcquisitionError`（信息可读、可排查）。"""
        if self._cap is not None:
            return
        flag = {"dshow": cv2.CAP_DSHOW, "any": cv2.CAP_ANY, "msmf": cv2.CAP_MSMF}[self.backend]
        cap = cv2.VideoCapture(self.index, flag)
        if not cap.isOpened():
            cap.release()
            raise AcquisitionError(
                f"无法打开 USB 相机（设备号 {self.index}，后端 {self.backend}）。"
                "请检查：① 相机已连接且未被其他程序占用；② 设备号是否正确"
                "（可运行 python -m beaneye.acquisition.usb --list-cams 探测）；"
                "③ 无相机阶段请改用合成源 SynthVideoSource（--source synth）。"
            )
        if self.width:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(self.width))
        if self.height:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self.height))
        self._cap = cap

    def read_frame(self) -> np.ndarray | None:
        if self._cap is None:
            raise AcquisitionError("USBCameraSource 未打开；请先调用 open()（或用 with 语法）。")
        ok, frame = self._cap.read()
        if not ok or frame is None:
            return None  # 瞬时失败/流结束：交由上层决定重试或退出
        return frame

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self) -> "USBCameraSource":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# ---------------------------------------------------------------------------
# IP 相机（手机推流 MJPEG）
# ---------------------------------------------------------------------------


def drain_and_retrieve(
    cap: "cv2.VideoCapture",
    *,
    grab_slow_s: float,
    max_backlog: int,
    monotonic: "Callable[[], float] | None" = None,
) -> np.ndarray | None:
    """「读到积压就丢帧只留最新」的读帧策略（IPCameraSource 的延迟控制核心）。

    MJPEG 推流客户端侧有内核/FFMPEG 接收缓冲：消费比生产慢时缓冲积压旧帧，
    直接 ``read()`` 会拿到越来越旧的画面。策略：

    1. ``grab()``（只推进解码不取像素，代价小）一次；
    2. 若这次 grab **立即返回**（耗时 < ``grab_slow_s``，说明拿到的是缓冲里的
       积压帧）→ 该帧已过期，丢弃并继续 grab 追新；
    3. 若 grab **耗时 ≥ grab_slow_s**（在等网络新帧）→ 已追平实时，retrieve
       取这一帧；
    4. 丢弃数达 ``max_backlog`` 上限也停（防极端风暴下饿死 retrieve）。

    grab 失败（流断/结束）返回 None。该函数是纯策略（不持有源状态）；
    ``monotonic`` 时钟可注入（单测用脚本时钟替代墙钟，确定性判定快/慢 grab）。
    """
    clock = monotonic if monotonic is not None else time.perf_counter
    dropped = 0
    while True:
        t0 = clock()
        ok = cap.grab()
        took = clock() - t0
        if not ok:
            return None
        if took >= grab_slow_s or dropped >= max_backlog:
            ok, frame = cap.retrieve()
            return frame if ok and frame is not None else None
        dropped += 1


class IPCameraSource:
    """IP 相机源：手机推流 MJPEG（IP Webcam / DroidCam 等）URL 直连。

    - ``http(s)://host:port/video`` 之类的 MJPEG 流地址直接交给
      ``cv2.VideoCapture(url, cv2.CAP_FFMPEG)``（OpenCV FFMPEG 后端原生支持
      multipart/x-mixed-replace）；
    - 延迟控制：每次读帧先经 :func:`drain_and_retrieve` 丢积压只留最新
      （``grab_slow_s`` 缺省按 15fps 帧间隔的一半取，构造参数可调）；
    - 打不开（URL 不可达 / 非 MJPEG 流）抛 :class:`AcquisitionError`。
    """

    def __init__(
        self,
        url: str,
        *,
        grab_slow_s: float | None = None,
        max_backlog: int = 8,
        connect_timeout_s: float = 15.0,
    ) -> None:
        if not isinstance(url, str) or not url.strip():
            raise AcquisitionError("IP 相机 URL 不能为空（形如 http://192.168.x.x:8080/video）")
        u = url.strip()
        if not (u.startswith("http://") or u.startswith("https://")):
            raise AcquisitionError(
                f"IP 相机 URL 须以 http:// 或 https:// 开头，得到 {url!r}"
            )
        self.url = u
        self.grab_slow_s = float(grab_slow_s) if grab_slow_s is not None else (0.5 / 15.0)
        self.max_backlog = int(max_backlog)
        if self.max_backlog < 0:
            raise AcquisitionError(f"max_backlog 必须 >= 0，得到 {max_backlog!r}")
        self.connect_timeout_s = float(connect_timeout_s)
        self._cap: cv2.VideoCapture | None = None

    # -- RealtimeSource -----------------------------------------------------
    def open(self) -> None:
        if self._cap is not None:
            return
        cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            cap.release()
            raise AcquisitionError(
                f"无法打开 IP 相机流 {self.url}。请检查：① 手机推流已开启且地址/端口正确；"
                "② 本机与手机在同一网络（浏览器先能打开该地址看到画面）；"
                "③ 流格式为 MJPEG（IP Webcam/DroidCam 的 /video 地址）。"
            )
        # 尽量压小客户端缓冲（FFMPEG/驱动多不支持该属性——不支持就由
        # drain_and_retrieve 的丢帧策略兜底，此处 best-effort）。
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:  # noqa: BLE001 — 属性不支持不影响功能
            pass
        self._cap = cap

    def read_frame(self) -> np.ndarray | None:
        if self._cap is None:
            raise AcquisitionError("IPCameraSource 未打开；请先调用 open()（或用 with 语法）。")
        return drain_and_retrieve(
            self._cap, grab_slow_s=self.grab_slow_s, max_backlog=self.max_backlog
        )

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self) -> "IPCameraSource":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# ---------------------------------------------------------------------------
# 合成源（无硬件开发与测试）
# ---------------------------------------------------------------------------


class SynthVideoSource:
    """合成视频源：beaneye.synth 铺盘合成器预合成 N 盘循环播放。

    - 打开时用 :func:`beaneye.synth.compose.compose_tray` 确定性合成
      ``pool`` 盘（seed、seed+1、…，全部稀疏摆放 + 四角 ArUco，标定可用），
      ``read_frame()`` 轮流返回（拷贝，消费者可安全改写）；
    - 每帧是**完整不同布局**的托盘画面（不是静止图），能真实驱动分割/
      分类/叠加全链；盘帧同时保有逐粒真值（``trays[i].beans``），测试与
      演示可对账；
    - 全程离线、无墙钟时间依赖（同 seed 可复现）。
    """

    def __init__(
        self,
        *,
        width: int = 1280,
        height: int = 720,
        seed: int = 20261002,
        n_beans_min: int = 12,
        n_beans_max: int = 20,
        defect_rate: float = 0.45,
        pool: int = 2,
        margin_mm: float = 12.0,
    ) -> None:
        if width < 256 or height < 256:
            raise AcquisitionError(
                f"合成画布过小（{width}x{height}）：宽高至少 256px（compose 配置下限）"
            )
        if pool < 1:
            raise AcquisitionError(f"pool 必须 >= 1，得到 {pool!r}")
        self.width = int(width)
        self.height = int(height)
        self.seed = int(seed)
        self.n_beans_min = int(n_beans_min)
        self.n_beans_max = int(n_beans_max)
        self.defect_rate = float(defect_rate)
        self.pool = int(pool)
        self.margin_mm = float(margin_mm)
        self.trays: list[SynthTray] = []  # 打开后可读：逐盘真值（SynthTray）
        self._cursor = 0

    def _compose_config(self) -> ComposeConfig:
        return ComposeConfig(
            version=1,
            width_px=self.width,
            height_px=self.height,
            margin_mm=self.margin_mm,
            n_beans_min=self.n_beans_min,
            n_beans_max=self.n_beans_max,
            defect_rate=self.defect_rate,
            class_weights={
                "black": 3.0, "mold": 2.0, "sour": 2.0, "insect": 2.0, "dried": 2.0,
                "broken": 3.0, "brocade": 2.0, "shell": 1.0, "elephant": 1.0,
                "peaberry": 1.0, "immature": 1.0, "faded": 1.0,
            },
            contact_min=0,  # 稀疏盘：粘连切分是 classic 已知短板，实时演示不开
            contact_max=0,
            mirror_bottom=False,  # 实时单面语义，不出 bottom
            per_class=20,  # 素材库交付线下限（sample_library 要求 >=20）
        )

    # -- RealtimeSource -----------------------------------------------------
    def open(self) -> None:
        if self.trays:
            return
        trays: list[SynthTray] = []
        for k in range(self.pool):
            trays.append(compose_tray(self.seed + k, config=self._compose_config()))
        self.trays = trays
        self._cursor = 0

    def read_frame(self) -> np.ndarray | None:
        if not self.trays:
            raise AcquisitionError("SynthVideoSource 未打开；请先调用 open()（或用 with 语法）。")
        img = self.trays[self._cursor % len(self.trays)].top_bgr
        self._cursor += 1
        return img.copy()

    def close(self) -> None:
        self.trays = []
        self._cursor = 0

    def __enter__(self) -> "SynthVideoSource":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()
