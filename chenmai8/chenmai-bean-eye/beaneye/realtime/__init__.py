"""BeanEye · 实时线（beaneye.realtime）。

摄像头实时逐帧着色标注：不同品级/缺陷的豆子实时用不同颜色标出。

- :mod:`beaneye.realtime.sources` —— RealtimeSource 协议 + 三实现
  （USB 相机 / 手机推流 IP MJPEG / beaneye.synth 合成源）；
- :mod:`beaneye.realtime.engine` —— RealtimeEngine 逐帧管线（可选降采样 →
  ClassicSeg 分割 → RulesV0 分类 → BeanSpot/FrameResult 契约输出）与
  ArUco 毫米标定刷新（HUD 毫米尺寸）；
- :mod:`beaneye.realtime.overlay` —— taxonomy key 稳定配色表 + 轮廓/质心/
  HUD/图例条绘制（中文标签，PIL 字体渲染）；
- :mod:`beaneye.realtime.server` —— MJPEG 推流中枢（app 的
  ``GET /live/stream`` 背后）。

实时模式单面拍摄：不做双面配对/计量/定级（那是 beaneye.app.pipeline 批处理
链的职责）。演示入口：``python scripts/demo_realtime.py --source synth``；
Web 演示：``python -m beaneye.app`` 后打开 /demo 的「实时」入口。

导出用 PEP 562 惰性加载（与 beaneye.acquisition 同风格：包导入不拉起
OpenCV/合成器重依赖，按需装载）。
"""

from typing import TYPE_CHECKING

__all__ = [
    "RealtimeSource",
    "USBCameraSource",
    "IPCameraSource",
    "SynthVideoSource",
    "drain_and_retrieve",
    "RealtimeConfig",
    "BeanSpot",
    "FrameResult",
    "RealtimeEngine",
    "CLASS_COLORS_BGR",
    "color_for",
    "class_label_zh",
    "draw_overlay",
    "LiveParams",
    "LiveStreamHub",
    "CLASSIFIER_CHOICES",
    "ClassifierUsageError",
    "build_classifier",
]

_LAZY = {
    "RealtimeSource": ("beaneye.realtime.sources", "RealtimeSource"),
    "USBCameraSource": ("beaneye.realtime.sources", "USBCameraSource"),
    "IPCameraSource": ("beaneye.realtime.sources", "IPCameraSource"),
    "SynthVideoSource": ("beaneye.realtime.sources", "SynthVideoSource"),
    "drain_and_retrieve": ("beaneye.realtime.sources", "drain_and_retrieve"),
    "RealtimeConfig": ("beaneye.realtime.engine", "RealtimeConfig"),
    "BeanSpot": ("beaneye.realtime.engine", "BeanSpot"),
    "FrameResult": ("beaneye.realtime.engine", "FrameResult"),
    "RealtimeEngine": ("beaneye.realtime.engine", "RealtimeEngine"),
    "CLASS_COLORS_BGR": ("beaneye.realtime.overlay", "CLASS_COLORS_BGR"),
    "color_for": ("beaneye.realtime.overlay", "color_for"),
    "class_label_zh": ("beaneye.realtime.overlay", "class_label_zh"),
    "draw_overlay": ("beaneye.realtime.overlay", "draw_overlay"),
    "LiveParams": ("beaneye.realtime.server", "LiveParams"),
    "LiveStreamHub": ("beaneye.realtime.server", "LiveStreamHub"),
    "CLASSIFIER_CHOICES": ("beaneye.realtime.engine", "CLASSIFIER_CHOICES"),
    "ClassifierUsageError": ("beaneye.realtime.engine", "ClassifierUsageError"),
    "build_classifier": ("beaneye.realtime.engine", "build_classifier"),
}


def __getattr__(name: str):
    if name in _LAZY:
        import importlib

        module, attr = _LAZY[name]
        return getattr(importlib.import_module(module), attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if TYPE_CHECKING:  # 仅供类型标注
    from beaneye.realtime.engine import BeanSpot, FrameResult, RealtimeConfig, RealtimeEngine
    from beaneye.realtime.overlay import CLASS_COLORS_BGR, class_label_zh, color_for, draw_overlay
    from beaneye.realtime.server import LiveParams, LiveStreamHub
    from beaneye.realtime.sources import (
        IPCameraSource,
        RealtimeSource,
        SynthVideoSource,
        USBCameraSource,
        drain_and_retrieve,
    )
