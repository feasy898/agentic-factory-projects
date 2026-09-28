"""BeanEye · 采集包（M2）。

Source 抽象 + 三实现，全部结构满足冻结契约 ``beaneye.schemas.CameraSource``
（``capture_pair(sample_id, tray_id) -> TrayScan``）：

- :class:`MockSource` —— 内置确定性合成图序列（无相机/无素材阶段的演示源）；
- :class:`UsbSource`  —— cv2.VideoCapture(CAP_DSHOW) 双相机，设备号/分辨率/对焦/
  曝光可配（configs/camera.yaml 或构造参数）；无设备时构造即优雅报错；
- :class:`SynthSource` —— M12 合成引擎接口占位（W12b 后接入）。

图像落盘一律经 ``imencode/imdecode`` 字节缓冲（中文路径坑），见 base.py。

导出用 PEP 562 惰性加载：避免 ``python -m beaneye.acquisition.usb`` 时
包初始化先把 usb 模块载入 sys.modules 再被 runpy 二次执行（RuntimeWarning）。
"""

from typing import TYPE_CHECKING

__all__ = [
    "Source",
    "MockSource",
    "UsbSource",
    "SynthSource",
    "AcquisitionError",
    "load_camera_config",
    "probe_cameras",
    "imread_bgr",
    "imwrite_bgr",
    "read_json",
    "write_json",
    "scan_paths",
    "TRAY_MM",
]

_LAZY = {
    "Source": ("beaneye.acquisition.source", "Source"),
    "MockSource": ("beaneye.acquisition.mock_source", "MockSource"),
    "TRAY_MM": ("beaneye.acquisition.mock_source", "TRAY_MM"),
    "UsbSource": ("beaneye.acquisition.usb", "UsbSource"),
    "load_camera_config": ("beaneye.acquisition.usb", "load_camera_config"),
    "probe_cameras": ("beaneye.acquisition.usb", "probe_cameras"),
    "SynthSource": ("beaneye.acquisition.synth_source", "SynthSource"),
    "AcquisitionError": ("beaneye.acquisition.base", "AcquisitionError"),
    "imread_bgr": ("beaneye.acquisition.base", "imread_bgr"),
    "imwrite_bgr": ("beaneye.acquisition.base", "imwrite_bgr"),
    "read_json": ("beaneye.acquisition.base", "read_json"),
    "write_json": ("beaneye.acquisition.base", "write_json"),
    "scan_paths": ("beaneye.acquisition.base", "scan_paths"),
}


def __getattr__(name: str):
    if name in _LAZY:
        import importlib

        module, attr = _LAZY[name]
        return getattr(importlib.import_module(module), attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(list(globals()) + __all__)


if TYPE_CHECKING:  # 静态类型仍可解析（IDE/mypy）
    from beaneye.acquisition.base import (
        AcquisitionError,
        imread_bgr,
        imwrite_bgr,
        read_json,
        scan_paths,
        write_json,
    )
    from beaneye.acquisition.mock_source import TRAY_MM, MockSource
    from beaneye.acquisition.source import Source
    from beaneye.acquisition.synth_source import SynthSource
    from beaneye.acquisition.usb import UsbSource, load_camera_config, probe_cameras
