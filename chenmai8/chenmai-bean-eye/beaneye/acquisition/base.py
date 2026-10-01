"""采集公共基元（M2）：异常体系 + 中文路径安全的图像/JSON 读写。

本机工程路径含中文（如 ``澄迈8项目/咖啡豆质检``），OpenCV 的 ``imwrite/``\
``imread`` 对非 ASCII 路径会**静默失败**（不抛异常、返回 False/None），
因此本包所有图像落盘/读回一律走 ``imencode/imdecode`` 字节缓冲
（W0b 实测结论，见仓库提交记录）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import cv2
import numpy as np

from beaneye.schemas import TrayScan

__all__ = [
    "AcquisitionError",
    "imread_bgr",
    "imwrite_bgr",
    "write_json",
    "read_json",
    "scan_paths",
]


class AcquisitionError(RuntimeError):
    """采集失败（无相机 / 帧读取失败 / 图像 IO 失败）。"""


# ---------------------------------------------------------------------------
# 中文路径安全的图像 IO（imencode/imdecode 字节缓冲）
# ---------------------------------------------------------------------------

_EXT_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff")


def imwrite_bgr(path: str | Path, img_bgr: np.ndarray, *, params: list[int] | None = None) -> Path:
    """把 BGR 图像写入 ``path``（支持中文路径；失败抛 :class:`AcquisitionError`）。"""
    p = Path(path)
    suffix = p.suffix.lower() or ".png"
    if suffix not in _EXT_SUFFIXES:
        raise AcquisitionError(f"不支持的图像扩展名 {suffix!r}: {p}")
    ok, buf = cv2.imencode(suffix, img_bgr, params or [])
    if not ok:
        raise AcquisitionError(f"图像编码失败: {p}")
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_bytes(buf.tobytes())
    except OSError as exc:
        raise AcquisitionError(f"图像写入失败: {p}（{exc}）") from exc
    return p


def imread_bgr(path: str | Path) -> np.ndarray:
    """从 ``path`` 读回 BGR 图像（支持中文路径；失败/不存在抛 :class:`AcquisitionError`）。"""
    p = Path(path)
    if not p.is_file():
        raise AcquisitionError(f"图像文件不存在: {p}")
    try:
        buf = np.frombuffer(p.read_bytes(), dtype=np.uint8)
    except OSError as exc:
        raise AcquisitionError(f"图像读取失败: {p}（{exc}）") from exc
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        raise AcquisitionError(f"图像解码失败（文件损坏或非图像）: {p}")
    return img


# ---------------------------------------------------------------------------
# JSON IO（manifest 等）
# ---------------------------------------------------------------------------


def write_json(path: str | Path, obj: object) -> Path:
    """UTF-8 缩进 JSON 落盘（ensure_ascii=False，人工可读）。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def read_json(path: str | Path) -> object:
    p = Path(path)
    if not p.is_file():
        raise AcquisitionError(f"JSON 文件不存在: {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AcquisitionError(f"JSON 解析失败: {p}（{exc}）") from exc


# ---------------------------------------------------------------------------
# TrayScan 相对路径解析
# ---------------------------------------------------------------------------


def scan_paths(scan: TrayScan, root: str | Path) -> dict[Literal["top", "bottom"], Path]:
    """把 :class:`TrayScan` 里的相对路径按采集根目录 ``root`` 解析为绝对路径。

    ``top_image/bottom_image`` 契约为相对路径（相对采集源的输出根目录）。
    """
    r = Path(root)
    return {"top": r / scan.top_image, "bottom": r / scan.bottom_image}
