"""UsbSource：USB 双相机采集源（M2）+ 相机枚举 CLI。

- ``cv2.VideoCapture(index, cv2.CAP_DSHOW)``（Windows DirectShow 后端）；
- 设备号 / 分辨率 / 对焦 / 曝光 / 预热帧全部可配（默认读 ``configs/camera.yaml``，
  构造参数可覆盖）；
- **无相机时构造即抛 :class:`AcquisitionError`**，报错信息明确提示改用
  ``MockSource``（开发指令 §4 M2 通过线：优雅报错而非 traceback）；
- 逐帧走 ``imencode`` 字节缓冲落盘（中文路径坑，见 base.py）。

CLI（真机冒烟，开发指令 §4 M2）::

    python -m beaneye.acquisition.usb --list-cams [--max-index 9] [--config PATH]

    退出码：发现 ≥1 台相机 = 0；一台都没有 = 2（打印清晰提示，非 traceback）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

from beaneye.schemas import TrayScan

from beaneye.acquisition.base import AcquisitionError
from beaneye.acquisition.source import Source

__all__ = ["UsbSource", "load_camera_config", "probe_cameras", "main"]

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "configs" / "camera.yaml"

_REQUIRED_KEYS = ("top_index", "bottom_index", "width", "height")


def load_camera_config(path: str | Path | None = None) -> dict[str, Any]:
    """加载 camera.yaml 并做最小校验（缺键/非正分辨率即抛错）。"""
    p = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not p.is_file():
        raise AcquisitionError(
            f"相机配置不存在: {p}（真机接入前先用 MockSource；或新建该文件）"
        )
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise AcquisitionError(f"相机配置解析失败: {p}（{exc}）") from exc
    if not isinstance(raw, dict):
        raise AcquisitionError(f"相机配置顶层必须是映射: {p}")
    cfg = {
        "top_index": raw.get("top", {}).get("index") if isinstance(raw.get("top"), dict) else raw.get("top_index"),
        "bottom_index": raw.get("bottom", {}).get("index") if isinstance(raw.get("bottom"), dict) else raw.get("bottom_index"),
        "width": raw.get("resolution", [None, None])[0] if isinstance(raw.get("resolution"), list) else raw.get("width"),
        "height": raw.get("resolution", [None, None])[1] if isinstance(raw.get("resolution"), list) else raw.get("height"),
        "focus": raw.get("focus"),
        "exposure": raw.get("exposure"),
        "warmup_frames": int(raw.get("warmup_frames", 3)),
        "fourcc": raw.get("fourcc"),
    }
    missing = [k for k in _REQUIRED_KEYS if cfg.get(k) is None]
    if missing:
        raise AcquisitionError(f"相机配置缺少必需键: {missing}（文件: {p}）")
    for k in ("width", "height"):
        if not isinstance(cfg[k], int) or cfg[k] <= 0:
            raise AcquisitionError(f"相机配置 {k} 必须是正整数，得到 {cfg[k]!r}（文件: {p}）")
    return cfg


class UsbSource(Source):
    """USB 双相机源：构造时打开两台相机，任一失败即报错并提示 Mock。"""

    def __init__(
        self,
        out_dir: str | Path,
        *,
        top_index: int | None = None,
        bottom_index: int | None = None,
        width: int | None = None,
        height: int | None = None,
        focus: float | None = None,
        exposure: float | None = None,
        warmup_frames: int | None = None,
        fourcc: str | None = None,
        config_path: str | Path | None = None,
        scan_prefix: str = "usb",
    ) -> None:
        cfg = load_camera_config(config_path)
        self.top_index = int(top_index if top_index is not None else cfg["top_index"])
        self.bottom_index = int(bottom_index if bottom_index is not None else cfg["bottom_index"])
        self.width = int(width if width is not None else cfg["width"])
        self.height = int(height if height is not None else cfg["height"])
        self.focus = cfg["focus"] if focus is None else focus
        self.exposure = cfg["exposure"] if exposure is None else exposure
        self.warmup_frames = int(
            warmup_frames if warmup_frames is not None else cfg["warmup_frames"]
        )
        self.fourcc = cfg["fourcc"] if fourcc is None else fourcc
        super().__init__(out_dir, scan_prefix=scan_prefix, source_kind="usb")
        self._caps: dict[str, cv2.VideoCapture] = {}
        self._open()

    # ------------------------------------------------------------------
    def _open(self) -> None:
        for side, index in (("top", self.top_index), ("bottom", self.bottom_index)):
            cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap.release()
                self.close()
                raise AcquisitionError(
                    f"无法打开{ '上' if side == 'top' else '下' }相机（设备号 {index}, "
                    f"CAP_DSHOW）。当前机器没有可用 USB 相机或设备号不对；"
                    f"开发/演示请改用 beaneye.acquisition.MockSource（内置合成图序列），"
                    f"或运行  python -m beaneye.acquisition.usb --list-cams  探测设备号。"
                )
            self._apply_props(cap)
            self._caps[side] = cap
        self._warmup()

    def _apply_props(self, cap: cv2.VideoCapture) -> None:
        """分辨率 / fourcc / 对焦 / 曝光（可配，设置失败不致命只记警告）。"""
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(self.width))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self.height))
        if self.fourcc:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.fourcc))
        if self.focus is not None:
            cap.set(cv2.CAP_PROP_FOCUS, float(self.focus))
        if self.exposure is not None:
            cap.set(cv2.CAP_PROP_EXPOSURE, float(self.exposure))

    def _warmup(self) -> None:
        for _ in range(self.warmup_frames):
            for cap in self._caps.values():
                cap.grab()

    # ------------------------------------------------------------------
    def _read(self, side: str) -> np.ndarray:
        cap = self._caps[side]
        ok, frame = cap.read()
        if not ok or frame is None:
            raise AcquisitionError(f"{side} 相机读帧失败（设备号 {self.top_index if side == 'top' else self.bottom_index}）")
        return frame

    def capture_pair(self, sample_id: str, tray_id: str) -> TrayScan:
        if not self._caps:
            raise AcquisitionError("UsbSource 已关闭；请重新构造")
        return self._finalize_pair(sample_id, tray_id, self._read("top"), self._read("bottom"))

    def resolutions(self) -> dict[str, tuple[int, int]]:
        out: dict[str, tuple[int, int]] = {}
        for side, cap in self._caps.items():
            out[side] = (
                int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            )
        return out

    def close(self) -> None:
        for cap in self._caps.values():
            cap.release()
        self._caps.clear()

    def __enter__(self) -> UsbSource:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# ---------------------------------------------------------------------------
# 相机枚举（CLI 用；独立函数便于测试注入）
# ---------------------------------------------------------------------------


def probe_cameras(indices: range | list[int], *, width: int, height: int) -> list[tuple[int, tuple[int, int]]]:
    """逐个尝试打开设备号，返回 ``[(index, (w, h)), ...]``。只探测，不保温。"""
    found: list[tuple[int, tuple[int, int]]] = []
    for index in indices:
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))
            found.append(
                (int(index), (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))))
            )
        cap.release()
    return found


def _reconfigure_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    import argparse

    _reconfigure_utf8()
    parser = argparse.ArgumentParser(
        prog="python -m beaneye.acquisition.usb",
        description="USB 相机枚举/冒烟（BeanEye M2 采集）",
    )
    parser.add_argument("--list-cams", action="store_true", help="枚举 DirectShow 相机设备号")
    parser.add_argument("--max-index", type=int, default=9, help="探测的最大设备号（默认 9）")
    parser.add_argument("--config", default=None, help="camera.yaml 路径（默认 configs/camera.yaml）")
    args = parser.parse_args(argv)

    if not args.list_cams:
        parser.print_help()
        return 0

    try:
        cfg = load_camera_config(args.config)
    except AcquisitionError as exc:
        # 无配置也要能枚举：退回规划默认 3840x2160
        print(f"[WARN] {exc}；--list-cams 退回默认探测分辨率 3840x2160")
        cfg = {"width": 3840, "height": 2160}

    width, height = int(cfg["width"]), int(cfg["height"])
    print(f"[USB] 探测设备号 0..{args.max_index}（CAP_DSHOW，请求分辨率 {width}x{height}）...")
    found = probe_cameras(range(0, args.max_index + 1), width=width, height=height)
    if not found:
        print(
            "[USB] 未发现任何相机。请检查：① USB 相机已连接且被 Windows 识别；"
            "② 设备号是否在探测范围内（--max-index 调大）；"
            "③ 无相机阶段请使用 MockSource（beaneye.acquisition.MockSource）。"
        )
        return 2
    for index, (w, h) in found:
        print(f"[USB] 发现相机 index={index} 实际分辨率 {w}x{h}")
    print(f"[USB] 共 {len(found)} 台可用。")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
