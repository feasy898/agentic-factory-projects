"""生成层公共工具: 帧序列→mp4 (ffmpeg rawvideo 管道)、计时、显存峰值记录。

write_frames_mp4 为纯 CPU 可测(小分辨率帧 + ffmpeg), ffmpeg 缺失时由测试 skipif。
"""

from __future__ import annotations

import subprocess
import time
from contextlib import contextmanager


def even(n: int) -> int:
    n = int(n)
    return n if n % 2 == 0 else n + 1


def build_frames_to_mp4_argv(fps: float, width: int, height: int, out_mp4: str) -> list[str]:
    """rawvideo rgb24 从 stdin 读帧, 编码 H.264 yuv420p。"""
    return [
        "ffmpeg", "-y", "-hide_banner", "-nostats",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(fps), "-i", "pipe:0",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        out_mp4,
    ]


def write_frames_mp4(frames, fps: float, out_mp4: str, runner=None) -> str:
    """frames: list/array of HxWx3 uint8 (rgb24)。返回 out_mp4。"""
    import numpy as np

    runner = runner or subprocess.run
    if not frames:
        raise ValueError("帧序列为空")
    arr = np.asarray(frames[0])
    h, w = arr.shape[0], arr.shape[1]
    argv = build_frames_to_mp4_argv(fps, even(w), even(h), out_mp4)
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    for f in frames:
        a = np.asarray(f)
        if a.shape[1] % 2 or a.shape[0] % 2:  # 奇数尺寸补边
            a = np.pad(a, ((0, a.shape[0] % 2), (0, a.shape[1] % 2), (0, 0)))
        try:
            proc.stdin.write(a.astype("uint8").tobytes())
        except BrokenPipeError:
            break
    try:
        proc.stdin.close()
    except BrokenPipeError:
        pass
    stderr = proc.stderr.read().decode("utf-8", "replace")
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg 编码失败: {stderr[-300:]}")
    return out_mp4


@contextmanager
def timed():
    """记录墙钟耗时: with timed() as t: ...; t.seconds"""
    t0 = time.monotonic()

    class T:
        seconds = 0.0

    try:
        yield T
    finally:
        T.seconds = time.monotonic() - t0


def reset_vram_counter() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
    except Exception:
        pass


def vram_peak_mb() -> float:
    """当前进程 CUDA 显存峰值 MB; 无 CUDA 时 0.0。"""
    try:
        import torch

        if torch.cuda.is_available():
            return round(torch.cuda.max_memory_allocated() / (1024 * 1024), 1)
    except Exception:
        pass
    return 0.0
