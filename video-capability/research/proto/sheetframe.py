#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sheetframe.py — 纯代码视频帧差时间线 + 变化感知关键帧 + 模型可读总览图。

思想出处：GitHub ztough926/video-understanding（GPL-3.0）——本文件是**思想的独立实现**
（cleanroom，未复制其代码），只借用三条公开文档化的设计：
  1) 双角度帧差：全局平均差异 + 8x8 分块最剧烈块差异，取较大值；
  2) 自适应阈值：差异中位数(≈底噪) x 灵敏度 k，夹在 [abs_floor, abs_ceil]；
  3) 模型可读分张纪律：每张 <=max_cells 格、列数<=4、图宽 ~1600px、4:4:4 JPEG、格下 #序号 时间戳。
依赖：ffmpeg/ffprobe 在 PATH，numpy、Pillow。
用途：video-capability research 原型——为 G7e/J1 评测面提供确定性帧采样与定格检测信号。
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ANALYZE_WIDTH = 200
BLOCK_GRID = 8
ABS_FLOOR = 0.008
ABS_CEIL = 0.080
LABEL_RATIO = 0.14  # 每格下方标签条占格高的比例（沿用"元数据不占格"思想：只有 #n + 时间戳）


# ---------- probe ----------

def probe(path: str | Path) -> dict:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height,r_frame_rate,nb_frames,duration",
           "-of", "json", str(path)]
    res = subprocess.run(cmd, capture_output=True, timeout=120)
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {path}: {res.stderr.decode('utf-8', 'replace')[:200]}")
    st = json.loads(res.stdout.decode("utf-8"))["streams"][0]
    num, _, den = st["r_frame_rate"].partition("/")
    fps = float(num) / float(den or 1)
    n = st.get("nb_frames")
    n = int(n) if n not in (None, "N/A") else None
    dur = float(st["duration"]) if st.get("duration") not in (None, "N/A") else None
    return {"width": int(st["width"]), "height": int(st["height"]), "fps": fps,
            "nb_frames": n, "duration": dur}


# ---------- 帧差时间线 ----------

def diff_timeline(path: str | Path, analyze_width: int = ANALYZE_WIDTH) -> dict:
    """单遍解码：逐帧 200px 灰度，相邻帧双角度差异（全局均值 vs 8x8 块最大均值），取 max。

    返回 {"fps","n","times":[..],"scores":[..]}；scores[0]=0（无前帧）。
    """
    p = probe(path)
    ah = max(2, int(round(p["height"] * analyze_width / p["width"] / 2)) * 2)
    aw = analyze_width
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo",
           "-pix_fmt", "gray", "-vf", f"scale={aw}:{ah}", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    frame_bytes = aw * ah
    times, scores = [], []
    prev = None
    fps = p["fps"] or 25.0
    n = 0
    try:
        while True:
            buf = proc.stdout.read(frame_bytes)
            if not buf or len(buf) < frame_bytes:
                break
            cur = np.frombuffer(buf, dtype=np.uint8).reshape(ah, aw).astype(np.int16)
            if prev is None:
                scores.append(0.0)
            else:
                d = np.abs(cur - prev)
                glob = float(d.mean()) / 255.0
                bh = ah // BLOCK_GRID
                bw = aw // BLOCK_GRID
                blocks = d[: bh * BLOCK_GRID, : bw * BLOCK_GRID].reshape(
                    bh, BLOCK_GRID, bw, BLOCK_GRID).mean(axis=(1, 3))
                local = float(blocks.max()) / 255.0
                scores.append(max(glob, local))
            times.append(n / fps)
            prev = cur
            n += 1
    finally:
        # 先关 stdout 让 ffmpeg 在 write 上吃到 EPIPE 立即退出；
        # 否则 ffmpeg 阻塞在写满的管道上时 SIGTERM 无法生效 -> wait() 永久挂起。
        if proc.stdout:
            proc.stdout.close()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    return {"fps": fps, "n": n, "times": times, "scores": scores}


def adaptive_threshold(scores: list[float], noise_k: float = 4.0,
                       lo: float = ABS_FLOOR, hi: float = ABS_CEIL) -> float:
    """阈值 = 差异中位数(≈底噪) x k，夹在 [lo, hi]。scores[0] 不参与（恒 0）。"""
    body = [s for s in scores[1:]]
    if not body:
        return lo
    noise = float(np.median(body))
    return float(min(hi, max(lo, noise * noise_k)))


# ---------- 变化感知选帧（等它变完） ----------

def select_keyframes(times: list[float], scores: list[float], thr: float,
                     min_time: float = 0.30, motion_time: float = 1.5) -> list[int]:
    """首帧必留；diff>thr 后等变完（diff 回落 <=thr）选稳定帧；持续变化每 motion_time 补一张；
    相邻关键帧至少隔 min_time；到尾帧仍在变补尾帧。返回帧号列表。"""
    n = len(scores)
    if n == 0:
        return []
    if n <= 8:  # 短片段全留（沿用上游对 <=8 帧 GIF 的口径）
        return list(range(n))
    picked: list[int] = [0]
    last_t = 0.0
    changing_since = None
    last_motion_pick = 0.0
    for i in range(1, n):
        t = times[i]
        s = scores[i]
        if s > thr:
            if changing_since is None:
                changing_since = t
            if t - last_motion_pick >= motion_time:  # 长动效中途补一张
                picked.append(i)
                last_t, last_motion_pick = t, t
                changing_since = None
        else:
            if changing_since is not None and (t - last_t) >= min_time:
                picked.append(i)  # 变化结束后的第一个稳定帧
                last_t = t
            changing_since = None
            last_motion_pick = t
    if changing_since is not None and (times[-1] - last_t) >= min_time:
        picked.append(n - 1)  # 到片尾还在变，补结尾
    if picked[-1] != n - 1 and times[-1] - times[picked[-1]] >= motion_time:
        picked.append(n - 1)
    return picked


# ---------- 定格（frame freeze）检测：纯代码，零模型 ----------

def detect_freeze(times: list[float], scores: list[float], thr: float,
                  eps: float | None = None, min_freeze_s: float = 1.0) -> dict:
    """内嵌静止段检测：相邻帧差异 < eps 的连续 run，时长 >= min_freeze_s，
    且 run 之外存在运动（任一 diff > thr）——区分"定格缺陷"与"整片静止镜头"。

    eps 缺省取 min(0.004, thr/2)：低于上游底噪夹底下限 0.008 的量级，即"近似零差"。
    """
    if eps is None:
        eps = min(0.004, thr / 2)
    n = len(scores)
    runs = []
    i = 1
    while i < n:
        if scores[i] < eps:
            j = i
            while j + 1 < n and scores[j + 1] < eps:
                j += 1
            span_s = times[j] - times[i - 1]
            interior = i > 1 and j < n - 1
            if span_s >= min_freeze_s:
                runs.append({"start_s": round(times[i - 1], 3), "end_s": round(times[j], 3),
                             "duration_s": round(span_s, 3), "interior": interior,
                             "max_score_in_run": round(max(scores[i:j + 1]), 6)})
            i = j + 1
        else:
            i += 1
    # run 区间之外存在 >thr 的帧 = 全片并非静止镜头（区分"定格缺陷"与"整片静止"）
    outside_motion = False
    for idx in range(1, n):
        t = times[idx]
        in_any_run = any(r["start_s"] - 1e-6 <= times[idx - 1] and t <= r["end_s"] + 1e-6 for r in runs)
        if not in_any_run and scores[idx] > thr:
            outside_motion = True
            break
    detected = [r for r in runs if r["interior"]] if outside_motion else []
    return {"eps": round(eps, 6), "runs": runs, "outside_motion": outside_motion,
            "freeze_detected": bool(detected),
            "spans": [{"start_s": r["start_s"], "end_s": r["end_s"],
                       "duration_s": r["duration_s"]} for r in detected]}


# ---------- 帧导出与总览图 ----------

def export_frames(path: str | Path, indices: list[int], out_dir: str | Path,
                  times: list[float], quality: int = 92) -> list[dict]:
    """第二遍解码（RGB 全尺寸），按帧号存 JPEG。返回 [{n,time,path}]。"""
    p = probe(path)
    w, h = p["width"], p["height"]
    out = Path(out_dir)
    (out / "frames").mkdir(parents=True, exist_ok=True)
    want = set(indices)
    last = max(indices) if indices else -1
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    fb = w * h * 3
    metas = []
    i = 0
    try:
        while i <= last:
            buf = proc.stdout.read(fb)
            if not buf or len(buf) < fb:
                break
            if i in want:
                img = Image.frombytes("RGB", (w, h), buf)
                fp = out / "frames" / f"kf_{i + 1:03d}_{times[i]:.3f}s.jpg"
                img.save(fp, "JPEG", quality=quality)
                metas.append({"n": i, "time": round(times[i], 3), "path": str(fp)})
            i += 1
    finally:
        if proc.stdout:
            proc.stdout.close()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    return metas


def _font(size: int):
    for name in ("msyh.ttc", "simhei.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def build_sheet(frames: list[dict], out_path: str | Path, cols: int = 3,
                target_width: int = 1600, cell_gap: int | None = None) -> dict:
    """把帧按时间顺序拼成总览图：LANCZOS 重采样、格下 #n 时间戳标签、4:4:4 JPEG。
    frames: export_frames 的返回（含 path）。单张 <=12 格由调用方分张。"""
    if not frames:
        raise ValueError("no frames")
    cell_w = (target_width - (cols - 1) * (cell_gap or max(8, target_width // 500))) // cols
    imgs = [Image.open(f["path"]) for f in frames]
    cell_h = int(round(cell_w * imgs[0].height / imgs[0].width))
    label_h = max(12, int(cell_h * LABEL_RATIO))
    gap = cell_gap or max(8, target_width // 500)
    rows = (len(imgs) + cols - 1) // cols
    W = cols * cell_w + (cols - 1) * gap
    H = rows * (cell_h + label_h) + (rows - 1) * gap
    sheet = Image.new("RGB", (W, H), (16, 16, 16))
    draw = ImageDraw.Draw(sheet)
    font = _font(max(11, label_h * 2 // 3))
    for k, (im, f) in enumerate(zip(imgs, frames)):
        r, c = divmod(k, cols)
        x = c * (cell_w + gap)
        y = r * (cell_h + label_h + gap)
        sheet.paste(im.resize((cell_w, cell_h), Image.LANCZOS), (x, y))
        draw.text((x + 4, y + cell_h + 2), f"#{f['n'] + 1:03d}  {f['time']:.2f}s",
                  fill=(240, 240, 240), font=font)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, "JPEG", quality=95, subsampling=0)  # 4:4:4
    return {"path": str(out_path), "width": W, "height": H, "cells": len(imgs)}


def split_sheets(frames: list[dict], out_dir: str | Path, max_cells: int = 12,
                 cols: int = 3, target_width: int = 1600) -> list[dict]:
    """自动分张：按时间顺序切片，每张 <=max_cells 格，返回张列表。"""
    out = []
    for si in range(0, len(frames), max_cells):
        chunk = frames[si:si + max_cells]
        name = "overview.jpg" if len(frames) <= max_cells else f"overview_{si // max_cells + 1:02d}.jpg"
        out.append(build_sheet(chunk, Path(out_dir) / name, cols=cols, target_width=target_width))
    return out


def analyze_video(path: str | Path, out_dir: str | Path, noise_k: float = 4.0,
                  max_cells: int = 12, cols: int = 3, sheet_width: int = 1600,
                  min_freeze_s: float = 1.0) -> dict:
    """一站式：时间线 -> 阈值 -> 选帧 -> 导出 -> 总览图 -> freeze 检测。"""
    tl = diff_timeline(path)
    thr = adaptive_threshold(tl["scores"], noise_k=noise_k)
    idx = select_keyframes(tl["times"], tl["scores"], thr)
    out_dir = Path(out_dir)
    frames = export_frames(path, idx, out_dir, tl["times"])
    sheets = split_sheets(frames, out_dir, max_cells=max_cells, cols=cols, target_width=sheet_width)
    fz = detect_freeze(tl["times"], tl["scores"], thr, min_freeze_s=min_freeze_s)
    meta = {"source": str(path), "probe": probe(path), "threshold": round(thr, 6),
            "keyframe_indices": idx, "keyframe_count": len(idx),
            "keyframes": frames, "overviews": sheets, "freeze": fz,
            "score_stats": {
                "max": round(max(tl["scores"]), 6),
                "median": round(float(np.median(tl["scores"][1:])), 6) if len(tl) > 1 else 0.0,
                "p95": round(float(np.percentile(tl["scores"][1:], 95)), 6) if len(tl) > 1 else 0.0,
            }}
    (out_dir / "keyframes.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta
