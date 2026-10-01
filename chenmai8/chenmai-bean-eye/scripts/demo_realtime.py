#!/usr/bin/env python3
"""实时逐帧着色标注演示（beaneye.realtime 一条命令入口）。

运行（仓库根）::

    python scripts/demo_realtime.py --source synth                # 合成源（无硬件）
    python scripts/demo_realtime.py --source usb --index 0        # USB 相机
    python scripts/demo_realtime.py --source ip --url http://192.168.x.x:8080/video

链路：RealtimeSource 逐帧 → RealtimeEngine（可选降采样 → ClassicSeg 分割 →
RulesV0 分类 → ArUco 毫米标定）→ draw_overlay（类别配色轮廓/质心/HUD/图例，
中文标签）→ cv2 窗口预览。按 q 或 Ctrl-C 优雅退出并打印统计
（帧数/处理帧/跳过帧/实测 FPS/逐类累计计数/存图清单）。

旋钮：``--downscale``（工作图缩放 0.1-1.0）与 ``--skip``（每 skip+1 帧处理
一次）。无摄像头环境一切可离线演示（--source synth）。

存图：``--save-dir``（缺省 out/realtime_demo，out/ 不入库）配合
``--save-frames`` 把标注帧存 PNG（演示产物）。
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from beaneye.acquisition.base import AcquisitionError, imwrite_bgr  # noqa: E402
from beaneye.realtime import (  # noqa: E402
    IPCameraSource,
    RealtimeConfig,
    RealtimeEngine,
    SynthVideoSource,
    USBCameraSource,
    draw_overlay,
)
from beaneye.realtime.sources import RealtimeSource  # noqa: E402

DEFAULT_SAVE_DIR = ROOT / "out" / "realtime_demo"
_WARMUP_PROCESSED = 5  # 前 N 处理帧为热身（首帧冷启动），存图从热身后开始


def _reconfigure_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def build_source(args: argparse.Namespace) -> RealtimeSource:
    """按参数构造采集源（不打开；open 失败的报错在主流程统一打印）。"""
    if args.source == "usb":
        return USBCameraSource(args.index, width=args.width, height=args.height)
    if args.source == "ip":
        if not args.url:
            raise SystemExit("source=ip 需要 --url（手机推流的 http(s) MJPEG 地址）")
        return IPCameraSource(args.url)
    return SynthVideoSource(
        width=args.width,
        height=args.height,
        seed=args.seed,
        n_beans_min=max(6, args.beans // 2),
        n_beans_max=max(6, args.beans),
        pool=args.pool,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python scripts/demo_realtime.py",
        description="啡眼 · 摄像头实时逐帧着色标注演示（usb/ip/synth 三源）",
    )
    p.add_argument("--source", choices=("usb", "ip", "synth"), default="synth", help="采集源（默认 synth）")
    p.add_argument("--index", type=int, default=0, help="USB 相机设备号（默认 0）")
    p.add_argument("--url", default="", help="IP 相机 MJPEG 流地址（source=ip 必填）")
    p.add_argument("--width", type=int, default=1280, help="源宽（USB 请求分辨率 / 合成画布宽，默认 1280）")
    p.add_argument("--height", type=int, default=720, help="源高（默认 720，合成源 720p 口径）")
    p.add_argument("--downscale", type=float, default=1.0, help="工作图缩放 0.1-1.0（降耗旋钮，默认 1.0）")
    p.add_argument("--skip", type=int, default=0, help="每 skip+1 帧处理一次（降耗旋钮，默认 0）")
    p.add_argument("--max-seconds", type=float, default=0.0, help="最长运行秒数（0=直到按 q，默认 0）")
    p.add_argument("--max-frames", type=int, default=0, help="最长读取帧数（0=不限，默认 0）")
    p.add_argument("--save-dir", default=str(DEFAULT_SAVE_DIR), help=f"标注帧保存目录（默认 {DEFAULT_SAVE_DIR}）")
    p.add_argument("--save-frames", type=int, default=3, help="保存标注帧张数（默认 3；0=不存）")
    p.add_argument("--no-show", action="store_true", help="不开预览窗口（无人值守/出图用）")
    p.add_argument("--no-calib", action="store_true", help="关闭 ArUco 毫米标定（默认开）")
    p.add_argument("--seed", type=int, default=20261002, help="合成源种子（默认 20261002）")
    p.add_argument("--beans", type=int, default=20, help="合成源豆数上限（默认 20）")
    p.add_argument("--pool", type=int, default=2, help="合成源预合成盘数（循环播放，默认 2）")
    return p


def _print_stats(args, *, frames, processed, skipped, dropped, elapsed, engine_fps,
                 total_counts, saved_files, calibrated) -> None:
    """退出统计（实测值如实打印，不作任何放大）。"""
    loop_fps = frames / elapsed if elapsed > 1e-6 else 0.0
    print("-" * 64)
    print("[实时演示] 统计")
    print(f"  源            : {args.source}" + (f" (index={args.index})" if args.source == "usb" else "") + (f" ({args.url})" if args.source == "ip" else ""))
    print(f"  旋钮          : downscale={args.downscale} skip={args.skip}")
    print(f"  读取帧        : {frames}（其中处理 {processed}、跳过 {skipped}、无帧 {dropped}）")
    print(f"  运行时长      : {elapsed:.1f}s")
    print(f"  实测 FPS      : 消费循环 {loop_fps:.2f}（引擎处理帧 EMA {engine_fps:.2f}）")
    print(f"  毫米标定      : {'有效（ArUco）' if calibrated else '未标定（伪毫米，HUD 已注明）'}")
    if total_counts:
        print("  逐类累计检出  : " + ", ".join(f"{k}={n}" for k, n in sorted(total_counts.items())))
    if saved_files:
        print("  存图          :")
        for f in saved_files:
            print(f"    {f}")
    print("-" * 64)


def main(argv: list[str] | None = None) -> int:
    _reconfigure_utf8()
    args = build_parser().parse_args(argv)

    if args.no_show and args.max_seconds <= 0 and args.max_frames <= 0:
        print("[实时演示] --no-show 模式必须给 --max-seconds 或 --max-frames（否则无人能停）")
        return 2
    if not 0.1 <= args.downscale <= 1.0:
        print(f"[实时演示] --downscale 必须在 [0.1, 1.0]，得到 {args.downscale}")
        return 2

    engine = RealtimeEngine(
        cfg=RealtimeConfig(
            downscale=args.downscale,
            skip=args.skip,
            calibrate=not args.no_calib,
        ),
        scan_id=f"demo_{args.source}",
    )

    frames = processed = skipped = dropped = 0
    total_counts: Counter[str] = Counter()
    saved_files: list[Path] = []
    save_dir = Path(args.save_dir)
    next_save_at = _WARMUP_PROCESSED
    engine_fps = 0.0
    calibrated_last = False
    t_start = time.perf_counter()

    try:
        source = build_source(args)
        source.open()
        print(f"[实时演示] 源就绪：{args.source}（q 退出 / Ctrl-C 优雅停止）")
        show = not args.no_show
        if show:
            cv2.namedWindow("BeanEye realtime (q to quit)", cv2.WINDOW_NORMAL)
        try:
            while True:
                if args.max_seconds > 0 and time.perf_counter() - t_start >= args.max_seconds:
                    break
                if args.max_frames > 0 and frames >= args.max_frames:
                    break
                frame = source.read_frame()
                if frame is None:
                    dropped += 1
                    if dropped > 90:
                        print("[实时演示] 连续无帧（源断开/结束），退出")
                        break
                    time.sleep(0.02)
                    continue
                frames += 1
                result = engine.process(frame)
                vis = draw_overlay(frame, result)  # 一帧只画一次（存图/预览共用）
                if result.skipped:
                    skipped += 1
                else:
                    processed += 1
                    engine_fps = result.fps
                    calibrated_last = result.calibrated
                    total_counts.update(result.counts)
                    if (
                        args.save_frames > 0
                        and len(saved_files) < args.save_frames
                        and processed >= next_save_at
                    ):
                        save_dir.mkdir(parents=True, exist_ok=True)
                        out = save_dir / f"frame_{result.frame_index:06d}"
                        imwrite_bgr(out.with_suffix(".png"), frame)  # 原始帧
                        imwrite_bgr(out.with_name(out.stem + "_anno.png"), vis)  # 标注帧
                        saved_files.extend([out.with_suffix(".png"), out.with_name(out.stem + "_anno.png")])
                        next_save_at += max(_WARMUP_PROCESSED, processed // 2)
                if show:
                    cv2.imshow("BeanEye realtime (q to quit)", vis)
                    if (cv2.waitKey(1) & 0xFF) == ord("q"):
                        break
        except KeyboardInterrupt:
            print("[实时演示] Ctrl-C，优雅退出")
        finally:
            source.close()
            if show:
                cv2.destroyAllWindows()
    except AcquisitionError as exc:
        print(f"[实时演示] 源打开失败：{exc}")
        return 2
    except KeyboardInterrupt:
        print("[实时演示] Ctrl-C（打开阶段），退出")

    elapsed = time.perf_counter() - t_start
    _print_stats(
        args,
        frames=frames, processed=processed, skipped=skipped, dropped=dropped,
        elapsed=elapsed, engine_fps=engine_fps, total_counts=total_counts,
        saved_files=saved_files, calibrated=calibrated_last,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
