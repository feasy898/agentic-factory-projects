"""生成层公共工具: 帧序列→mp4 (ffmpeg rawvideo 管道)、计时、显存峰值记录、首帧预处理。

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


def build_concat_argv(segment_paths: list[str], out_mp4: str) -> list[str]:
    """ffmpeg filter_complex concat 拼接同参数视频段 (纯函数, 单测断言结构)。"""
    if not segment_paths:
        raise ValueError("段序列为空")
    n = len(segment_paths)
    argv = ["ffmpeg", "-y", "-hide_banner", "-nostats"]
    for p in segment_paths:
        argv += ["-i", p]
    ins = "".join(f"[{i}:v]" for i in range(n))
    argv += [
        "-filter_complex", f"{ins}concat=n={n}:v=1:a=0[out]",
        "-map", "[out]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        out_mp4,
    ]
    return argv


def concat_segments(segment_paths: list[str], out_mp4: str) -> str:
    """执行拼接, 返回 out_mp4。"""
    cp = subprocess.run(build_concat_argv(segment_paths, out_mp4),
                        capture_output=True, text=True, timeout=600)
    if cp.returncode != 0:
        raise RuntimeError(f"段拼接失败: {cp.stderr[-300:]}")
    return out_mp4


def extract_last_frame(video_path: str, out_png: str) -> str:
    """抽视频最后一帧落 PNG (分段法的段间锚)。"""
    argv = [
        "ffmpeg", "-y", "-hide_banner", "-nostats",
        "-sseof", "-0.05", "-i", video_path,
        "-frames:v", "1", "-update", "1", out_png,
    ]
    cp = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    if cp.returncode != 0:
        raise RuntimeError(f"末帧抽取失败: {cp.stderr[-300:]}")
    return out_png


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


def open_center_resize(path: str, width: int, height: int):
    """读图 → 中心裁剪到目标宽高比 → resize 到 (width, height)。

    用途: I2V 首帧条件(任意来源图 → 生成分辨率), 资产主图与生成解耦(D-026 按需缩放)。
    返回 PIL.Image; 路径不存在抛 FileNotFoundError。
    """
    from PIL import Image

    img = Image.open(path).convert("RGB")
    target_ar = float(width) / float(height)
    src_ar = img.width / img.height
    if abs(src_ar - target_ar) > 1e-6:
        if src_ar > target_ar:  # 过宽 → 裁宽
            nw = max(1, int(round(img.height * target_ar)))
            x = (img.width - nw) // 2
            img = img.crop((x, 0, x + nw, img.height))
        else:  # 过高 → 裁高
            nh = max(1, int(round(img.width / target_ar)))
            y = (img.height - nh) // 2
            img = img.crop((0, y, img.width, y + nh))
    if (img.width, img.height) != (width, height):
        img = img.resize((int(width), int(height)), Image.LANCZOS)
    return img
