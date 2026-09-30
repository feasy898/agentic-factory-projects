"""Ken Burns 降级车道: ffmpeg zoompan 稳定实现 (SPECS §5.5)。

稳定公式 (SPECS §9-⑧): 先超采样 scale 到 ~4× 目标宽度的偶数尺寸, 再 zoompan;
z 线性 min(cap); x/y 居中; d=duration*fps; s=目标WxH; fps=fps。
支持 motion: zoom_in_1.06 / zoom_out / pan_left / pan_right。
命令构建全部为纯函数, 可脱离 GPU 单测。
"""

from __future__ import annotations

import re
import subprocess

from .common import even
from ..gates.g1_tech import probe_duration

DEFAULT_CAP = 1.06
PAN_ZOOM = 1.1  # pan 需 zoom>1 才有可移动余量


def parse_motion(motion: str) -> dict:
    """解析 motion 字符串 → {kind, cap}。"""
    m = re.fullmatch(r"zoom_in(?:_(\d+(?:\.\d+))?)?", motion or "")
    if m:
        return {"kind": "zoom_in", "cap": float(m.group(1)) if m.group(1) else DEFAULT_CAP}
    if motion == "zoom_out":
        return {"kind": "zoom_out", "cap": DEFAULT_CAP}
    if motion in ("pan_left", "pan_right"):
        return {"kind": motion, "cap": PAN_ZOOM}
    raise ValueError(f"未知 ken_burns motion: {motion!r} (支持: zoom_in_1.06/zoom_out/pan_left/pan_right)")


def supersample_size(out_w: int, out_h: int, oversample: int = 4) -> tuple[int, int]:
    """超采样尺寸: ~oversample× 目标宽度, 偶数; 高度按同倍率取偶。"""
    ss_w = even(out_w * oversample)
    ss_h = even(out_h * (ss_w / out_w))
    return ss_w, ss_h


def build_zoompan_filter(
    motion: str,
    duration_sec: float,
    fps: int,
    out_w: int,
    out_h: int,
    oversample: int = 4,
) -> str:
    """返回 scale→setsar→zoompan 滤镜链字符串。纯函数。"""
    spec = parse_motion(motion)
    d = max(1, int(round(float(duration_sec) * fps)))
    ss_w, ss_h = supersample_size(out_w, out_h, oversample)

    if spec["kind"] == "zoom_in":
        cap = spec["cap"]
        z = f"min(1+{cap - 1:.6f}*on/{d},{cap:.6f})"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif spec["kind"] == "zoom_out":
        cap = spec["cap"]
        z = f"max({cap:.6f}-{cap - 1:.6f}*on/{d},1.0)"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif spec["kind"] == "pan_left":
        z = f"{PAN_ZOOM:.6f}"
        x = f"(iw-iw/zoom)*(1-on/{d})"  # 相机左移: 裁剪窗从右往左
        y = "ih/2-(ih/zoom/2)"
    else:  # pan_right
        z = f"{PAN_ZOOM:.6f}"
        x = f"(iw-iw/zoom)*(on/{d})"
        y = "ih/2-(ih/zoom/2)"

    return (
        f"scale={ss_w}:{ss_h}:flags=lanczos,setsar=1,"
        f"zoompan=z='{z}':x='{x}':y='{y}':d={d}:s={out_w}x{out_h}:fps={fps}"
    )


def build_kenburns_argv(
    input_image: str,
    out_mp4: str,
    motion: str,
    duration_sec: float,
    fps: int,
    out_w: int,
    out_h: int,
    oversample: int = 4,
) -> list[str]:
    """完整 ffmpeg argv。纯函数, 单测直接断言滤镜链。"""
    d = max(1, int(round(float(duration_sec) * fps)))
    vf = build_zoompan_filter(motion, duration_sec, fps, out_w, out_h, oversample)
    return [
        "ffmpeg", "-y", "-hide_banner", "-nostats",
        "-loop", "1", "-framerate", str(fps), "-i", input_image,
        "-vf", vf,
        "-frames:v", str(d),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        out_mp4,
    ]


def run_kenburns(
    input_image: str,
    out_mp4: str,
    motion: str,
    duration_sec: float,
    fps: int,
    out_w: int,
    out_h: int,
    runner=subprocess.run,
) -> dict:
    """执行 Ken Burns 渲染, 返回 meta。"""
    argv = build_kenburns_argv(input_image, out_mp4, motion, duration_sec, fps, out_w, out_h)
    cp = runner(argv, capture_output=True, text=True, timeout=600)
    if cp.returncode != 0:
        raise RuntimeError(f"Ken Burns 渲染失败: {cp.stderr[-300:]}")
    duration = None
    try:
        duration = probe_duration(out_mp4)
    except Exception:
        pass
    return {
        "path": out_mp4,
        "model": "ken_burns",
        "motion": motion,
        "duration_s": duration,
        "fps": fps,
        "resolution": [out_w, out_h],
    }
