#!/usr/bin/env python3
"""kfextract —— 纯代码关键帧提取与"模型可读"总览图（本仓原创实现）。

思想来源（算法思想层，非代码）：GitHub ztough926/video-understanding（GPL-3.0）公开文档
描述的行为口径 —— 双角度差异检测（全局均值 + 分块最剧烈块）、"中位数=底噪"自适应阈值、
"等它变完"稳定帧选择、按多模态模型读图分辨率预算分张（每张≤12格、宽1600px）。
授权隔离：上游为 GPL-3.0，本仓为私有商业仓，**本文件为独立原创实现，未复制上游源码**；
依据与边界见 ../ADAPTATION-PLAN.md §授权风险。

依赖：numpy、Pillow、系统 ffmpeg/ffprobe。零模型调用。
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

# 算法常量（档位口径与上游公开文档一致，数值为通用安全档）
NOISE_K_DEFAULT = 4.0
THR_FLOOR, THR_CAP = 0.008, 0.08
MIN_TIME_DEFAULT = 0.30
MOTION_TIME_DEFAULT = 1.5
MAX_FRAMES_DEFAULT = 200
ANALYZE_WIDTH = 160
BLOCK_GRID = 8  # 差异分块网格：8x8


# ---------------------------------------------------------------- 探测与解码

def probe_video(src: Path) -> dict:
    """ffprobe 取宽高/帧率/时长。"""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate",
        "-show_entries", "format=duration", "-of", "json", str(src),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=120)
    data = json.loads(out.stdout)
    st = data["streams"][0]
    num, _, den = st["r_frame_rate"].partition("/")
    fps = float(num) / float(den or 1)
    return {
        "width": int(st["width"]),
        "height": int(st["height"]),
        "fps": fps,
        "duration": float(data["format"]["duration"]),
    }


def _analysis_size(width: int, height: int, target_w: int = ANALYZE_WIDTH) -> tuple[int, int]:
    tw = min(target_w, width) if width > target_w else width
    tw = max(2, int(tw) // 2 * 2)
    th = max(2, int(round(height * tw / width)) // 2 * 2)
    return tw, th


def iter_gray_frames(src: Path, size: tuple[int, int]):
    """顺序产出灰度 uint8 帧（ffmpeg rawvideo 管道，单遍解码）。"""
    w, h = size
    cmd = [
        "ffmpeg", "-v", "error", "-i", str(src),
        "-vf", f"scale={w}:{h}", "-pix_fmt", "gray",
        "-f", "rawvideo", "pipe:1",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    frame_bytes = w * h
    assert proc.stdout is not None
    try:
        while True:
            buf = proc.stdout.read(frame_bytes)
            if not buf:
                break
            if len(buf) < frame_bytes:
                break
            yield np.frombuffer(buf, dtype=np.uint8).reshape(h, w)
    finally:
        proc.stdout.close()
        proc.wait(timeout=60)


# ---------------------------------------------------------------- 差异与选帧

def diff_score(a: np.ndarray, b: np.ndarray) -> float:
    """双角度差异分：全局平均 |diff| 与 8x8 分块最剧烈块的平均 |diff|，取较大者（0~1）。"""
    d = np.abs(a.astype(np.int16) - b.astype(np.int16))
    global_mean = float(d.mean()) / 255.0
    h, w = d.shape
    gh, gw = h // BLOCK_GRID, w // BLOCK_GRID
    if gh < 1 or gw < 1:
        return global_mean
    d = d[: gh * BLOCK_GRID, : gw * BLOCK_GRID]
    blocks = d.reshape(gh, BLOCK_GRID, gw, BLOCK_GRID).mean(axis=(1, 3))
    block_max = float(blocks.max()) / 255.0
    return max(global_mean, block_max)


def auto_threshold(diffs: list[float], noise_k: float = NOISE_K_DEFAULT) -> float:
    """阈值 = 底噪(差异中位数) × noise_k，夹在 [THR_FLOOR, THR_CAP]。"""
    if not diffs:
        return THR_FLOOR
    median = float(np.median(np.asarray(diffs, dtype=np.float64)))
    return float(min(max(median * noise_k, THR_FLOOR), THR_CAP))


def select_frames(
    diffs: list[float],
    fps: float,
    threshold: float,
    min_time: float = MIN_TIME_DEFAULT,
    motion_time: float = MOTION_TIME_DEFAULT,
) -> list[int]:
    """按差异序列选关键帧号。

    规则：首帧必留；变化开始不选、等变化结束取稳定帧（"等它变完"）；
    持续变化每 motion_time 秒补一张；相邻关键帧至少 min_time 秒；
    片尾仍在变化则补最后一帧。diffs[i] = frame(i-1) 与 frame(i) 之差，i>=1。
    """
    n_total = len(diffs) + 1
    selected: list[int] = [0]
    if n_total <= 1:
        return selected

    def t_of(i: int) -> float:
        return i / fps

    in_change = False
    last_motion_pick = -1.0e9
    for i in range(1, n_total):
        t = t_of(i)
        d = diffs[i - 1]
        if d > threshold:
            if not in_change:
                in_change = True
                last_motion_pick = t
            if t - last_motion_pick >= motion_time and t - t_of(selected[-1]) >= min_time:
                selected.append(i)
                last_motion_pick = t
        elif in_change:
            # 变化刚结束：当前帧即稳定呈现帧
            if t - t_of(selected[-1]) >= min_time:
                selected.append(i)
            in_change = False
            last_motion_pick = -1.0e9
    if in_change:
        selected.append(n_total - 1)
    return selected


def downsample_indices(selected: list[int], cap: int) -> list[int]:
    """超上限时按时间均匀抽稀（在已选好的帧里挑，不调阈值）。"""
    if cap <= 0 or len(selected) <= cap:
        return selected
    pos = np.linspace(0, len(selected) - 1, num=cap)
    keep, last = [], -1
    for p in pos:
        i = int(round(p))
        if i != last:
            keep.append(selected[i])
            last = i
    return keep


# ---------------------------------------------------------------- 导出与拼图

def export_frames(
    src: Path, indices: list[int], out_dir: Path,
    max_width: int = 720, quality: int = 90,
) -> dict[int, Path]:
    """第二遍解码，按帧号命中导出 JPEG（Python 侧筛选，不用 ffmpeg select 表达式）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    want = set(indices)
    picked: dict[int, Path] = {}
    with tempfile.TemporaryDirectory() as td:
        probe_first = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", str(src)],
            capture_output=True, text=True, check=True)
        w, h = (int(x) for x in probe_first.stdout.strip().split(","))
        ew = min(w, max_width) if max_width > 0 else w
        eh = int(round(h * ew / w))
        ew, eh = max(2, ew // 2 * 2), max(2, eh // 2 * 2)
        cmd = ["ffmpeg", "-v", "error", "-i", str(src), "-vf", f"scale={ew}:{eh}",
               "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        fbytes = ew * eh * 3
        assert proc.stdout is not None
        idx = 0
        try:
            while True:
                buf = proc.stdout.read(fbytes)
                if not buf or len(buf) < fbytes:
                    break
                if idx in want:
                    img = Image.frombytes("RGB", (ew, eh), buf)
                    p = out_dir / f"kf_{idx:06d}.jpg"  # 时间戳不进文件名，进 keyframes.json
                    img.save(p, "JPEG", quality=quality)
                    picked[idx] = p
                idx += 1
        finally:
            proc.stdout.close()
            proc.wait(timeout=120)
    return picked


def _auto_cols(n: int, cell_aspect: float) -> int:
    """列数取「整图最接近正方形」且 ≤4 的网格。cell_aspect = 宽/高。"""
    best, best_score = 1, None
    for cols in range(1, 5):
        rows = -(-n // cols)
        w = cols * 1.0
        hgt = rows / max(cell_aspect, 1e-6)
        score = abs(w / max(hgt, 1e-6) - 1.0)
        if best_score is None or score < best_score:
            best, best_score = cols, score
    return best


def build_sheets(
    frames: dict[int, Path], ordered: list[int], times: dict[int, float],
    out_dir: Path, *, cols: int = 0, sheet_max_cells: int = 12,
    sheet_width: int = 1600, quality: int = 85,
) -> list[Path]:
    """按时间顺序拼总览图：每张 ≤sheet_max_cells 格，超了自动分张（清晰度一致）。"""
    if not ordered:
        return []
    first = Image.open(frames[ordered[0]])
    aspect = first.width / first.height
    if cols <= 0:
        cols = _auto_cols(min(len(ordered), sheet_max_cells), aspect)
    cell_w = sheet_width // cols
    cell_h = int(round(cell_w / aspect))
    label_h = 18

    sheets: list[Path] = []
    n_sheets = -(-len(ordered) // sheet_max_cells)
    for s in range(n_sheets):
        chunk = ordered[s * sheet_max_cells: (s + 1) * sheet_max_cells]
        rows = -(-len(chunk) // cols)
        sheet = Image.new("RGB", (cols * cell_w, rows * (cell_h + label_h)), (16, 16, 16))
        draw = ImageDraw.Draw(sheet)
        for k, fi in enumerate(chunk):
            img = Image.open(frames[fi]).resize((cell_w, cell_h), Image.LANCZOS)
            r, c = divmod(k, cols)
            x, y = c * cell_w, r * (cell_h + label_h)
            sheet.paste(img, (x, y))
            draw.text((x + 4, y + cell_h + 2), f"#{fi:03d} t={times[fi]:.2f}s", fill=(240, 240, 240))
        p = out_dir / (f"overview_{s + 1:02d}.jpg" if n_sheets > 1 else "overview.jpg")
        sheet.save(p, "JPEG", quality=quality, subsampling=0)
        sheets.append(p)
    return sheets


# ---------------------------------------------------------------- 主入口

def coverage_ok(n_frames: int, fps: float, container_dur: float, min_ratio: float = 0.5) -> bool:
    """解码覆盖守卫：实际解码时长 ≥ 容器时长 × min_ratio 才可信（元数据可骗，解不出来的不算）。"""
    if container_dur <= 0 or fps <= 0:
        return True
    return (n_frames / fps) >= min_ratio * container_dur


class DecodeCoverageError(RuntimeError):
    """实际解码覆盖时长不足容器时长一半——源文件损坏（如实 BLOCKED，不静默出垃圾）。"""

    def __init__(self, decoded_frames: int, fps: float, container_dur: float):
        self.decoded_frames = decoded_frames
        self.fps = fps
        self.container_dur = container_dur
        super().__init__(
            f"decode coverage too low: decoded {decoded_frames} frames "
            f"({decoded_frames / fps if fps else 0:.2f}s) of container {container_dur:.2f}s "
            f"({(decoded_frames / fps / container_dur * 100) if container_dur and fps else 0:.1f}%) "
            f"— source likely corrupt")


def extract(
    src: str | Path,
    out_dir: str | Path,
    *,
    noise_k: float = NOISE_K_DEFAULT,
    min_time: float = MIN_TIME_DEFAULT,
    motion_time: float = MOTION_TIME_DEFAULT,
    max_frames: int = MAX_FRAMES_DEFAULT,
    keep_frames: bool = True,
    cols: int = 0,
    sheet_max_cells: int = 12,
    sheet_max_sheets: int = 6,
    sheet_width: int = 1600,
    max_width: int = 720,
) -> dict:
    """抽帧 + 拼总览图，返回 keyframes.json 同构 dict（不含 path 时段外字段省略）。"""
    src = Path(src)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    info = probe_video(src)
    fps = info["fps"]

    asize = _analysis_size(info["width"], info["height"])
    prev: np.ndarray | None = None
    diffs: list[float] = []
    for fr in iter_gray_frames(src, asize):
        if prev is not None:
            diffs.append(diff_score(prev, fr))
        prev = fr
    n_frames = len(diffs) + 1
    # 解码覆盖率守卫：ffmpeg 对损坏流可能静默早停，若实际解码时长 < 容器时长一半，
    # 判定源损坏 → 显式报错（UNKNOWN≠PASS，绝不拿残缺帧序列当全片结论）
    decoded_dur = n_frames / fps if fps else 0.0
    if not coverage_ok(n_frames, fps, info["duration"]):
        raise DecodeCoverageError(n_frames, fps, info["duration"])
    threshold = auto_threshold(diffs, noise_k)

    selected = select_frames(diffs, fps, threshold, min_time, motion_time)
    cap = max_frames
    if sheet_max_sheets > 0 and sheet_max_cells > 0:
        cap = min(cap or 10 ** 9, sheet_max_sheets * sheet_max_cells)
    selected = downsample_indices(selected, cap)

    times = {i: i / fps for i in selected}
    if keep_frames:
        frames = export_frames(src, selected, out_dir / "frames", max_width=max_width)
        sheets = build_sheets(frames, selected, times, out_dir, cols=cols,
                              sheet_max_cells=sheet_max_cells, sheet_width=sheet_width)
        frame_paths = {i: str(frames[i]) for i in selected if i in frames}
    else:
        with tempfile.TemporaryDirectory() as td:
            frames = export_frames(src, selected, Path(td), max_width=max_width)
            sheets = build_sheets(frames, selected, times, out_dir, cols=cols,
                                  sheet_max_cells=sheet_max_cells, sheet_width=sheet_width)
        frame_paths = {}

    meta = {
        "video": str(src),
        "width": info["width"],
        "height": info["height"],
        "fps": fps,
        "duration": info["duration"],
        "n_frames_decoded": n_frames,
        "decoded_coverage": round(decoded_dur / info["duration"], 4) if info["duration"] > 0 else None,
        "threshold": round(threshold, 6),
        "noise_median": round(float(np.median(diffs)) if diffs else 0.0, 6),
        "noise_k": noise_k,
        "keyframe_count": len(selected),
        "overview_count": len(sheets),
        "overviews": [str(p) for p in sheets],
        "keyframes": [
            {"n": i, "time": round(times[i], 3),
             "diff": round(float(diffs[i - 1]), 6) if i >= 1 else 0.0,
             "path": frame_paths.get(i)}
            for i in selected
        ],
    }
    (out_dir / "keyframes.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="纯代码关键帧提取 + 模型可读总览图")
    ap.add_argument("video")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--noise-k", type=float, default=NOISE_K_DEFAULT)
    ap.add_argument("--min-time", type=float, default=MIN_TIME_DEFAULT)
    ap.add_argument("--motion-time", type=float, default=MOTION_TIME_DEFAULT)
    ap.add_argument("--max-frames", type=int, default=MAX_FRAMES_DEFAULT)
    ap.add_argument("--cols", type=int, default=0)
    ap.add_argument("--sheet-width", type=int, default=1600)
    ap.add_argument("--sheet-max-cells", type=int, default=12)
    ap.add_argument("--no-frames", action="store_true", help="不留单帧（总览图+JSON）")
    a = ap.parse_args()
    m = extract(a.video, a.out, noise_k=a.noise_k, min_time=a.min_time,
                motion_time=a.motion_time, max_frames=a.max_frames,
                keep_frames=not a.no_frames, cols=a.cols,
                sheet_width=a.sheet_width, sheet_max_cells=a.sheet_max_cells)
    print(json.dumps({k: m[k] for k in (
        "video", "width", "height", "fps", "duration", "keyframe_count",
        "overview_count", "threshold")}, ensure_ascii=False))
