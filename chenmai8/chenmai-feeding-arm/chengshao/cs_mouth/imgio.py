"""Windows 中文路径安全的图像/视频读写辅助。

本机仓库路径含非 ASCII 字符，cv2.imread/imwrite/VideoCapture 走 fopen 时会
静默失败（imread 返回 None、imwrite 返回 False）。一律改用字节流编解码：

- imread_u / imwrite_u：np.fromfile + cv2.imdecode / cv2.imencode + tofile；
- open_video_u：先直接开，失败则复制到 ASCII 临时文件再开（调用方负责 release）。
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import cv2
import numpy as np


def imread_u(path: str | Path, flags: int = cv2.IMREAD_COLOR) -> np.ndarray | None:
    """读图（中文路径安全）。失败返回 None。"""
    p = Path(path)
    if not p.is_file():
        return None
    try:
        buf = np.fromfile(str(p), dtype=np.uint8)
    except OSError:
        return None
    if buf.size == 0:
        return None
    return cv2.imdecode(buf, flags)


def imwrite_u(path: str | Path, img: np.ndarray, params: list[int] | None = None) -> bool:
    """写图（中文路径安全）。成功返回 True。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    ext = p.suffix or ".jpg"
    try:
        ok, buf = cv2.imencode(ext, img, params or [])
        if not ok:
            return False
        buf.tofile(str(p))
        return True
    except (cv2.error, OSError, ValueError):
        return False


def open_video_u(path: str | Path) -> "cv2.VideoCapture | None":
    """打开视频（中文路径安全：直接打开失败时复制到 ASCII 临时目录再开）。

    成功返回已打开的 VideoCapture（调用方 release()），失败返回 None。
    """
    p = Path(path)
    if not p.is_file():
        return None
    cap = cv2.VideoCapture(str(p))
    if cap.isOpened():
        return cap
    cap.release()
    tmp_dir = tempfile.mkdtemp(prefix="cs_mouth_vid_")
    tmp_path = Path(tmp_dir) / ("v" + (p.suffix or ".mp4"))
    try:
        shutil.copyfile(str(p), str(tmp_path))
    except OSError:
        os.rmdir(tmp_dir)
        return None
    cap = cv2.VideoCapture(str(tmp_path))
    if cap.isOpened():
        # 记录临时文件路径，release 时删除
        cap.set(cv2.CAP_PROP_POS_MSEC, 0)  # 无副作用，仅确保句柄就绪
        cap._cs_mouth_tmp = str(tmp_path)  # type: ignore[attr-defined]
        return cap
    cap.release()
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return None


def release_video_u(cap: "cv2.VideoCapture") -> None:
    """release 并清理 open_video_u 可能产生的临时文件。"""
    tmp = getattr(cap, "_cs_mouth_tmp", None)
    cap.release()
    if tmp:
        shutil.rmtree(str(Path(tmp).parent), ignore_errors=True)
