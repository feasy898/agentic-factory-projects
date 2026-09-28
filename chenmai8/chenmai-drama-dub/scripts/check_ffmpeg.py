#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ffmpeg/ffprobe 可用性检查（B1 修订 2026-09-28 起为独立脚本）。

背景：requirements.txt 曾写有 `ffmpeg==系统安装` 这类非 pip 行，导致
`pip install -r requirements.txt` 无法重放 T0；依赖清单里不再保留此类行，
ffmpeg 检查收口到本脚本（gate_b0 ① 对 pytest 子进程另有同口径的 PATH 断言）。

用法：
    python scripts/check_ffmpeg.py     # exit 0 = ffmpeg+ffprobe 均在 PATH 并打印版本
                                       # exit 1 = 缺失（打印修复指引）
"""

from __future__ import annotations

import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    missing: list[str] = []
    for exe in ("ffmpeg", "ffprobe"):
        p = shutil.which(exe)
        if p is None:
            missing.append(exe)
            print(f"MISSING {exe} 不在 PATH")
            continue
        try:
            v = subprocess.run([p, "-version"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=30)
            first = (v.stdout or "").splitlines()[0] if v.stdout else "?"
            print(f"OK {exe} @ {p} ({first})")
        except OSError as exc:
            missing.append(exe)
            print(f"MISSING {exe} @ {p} 无法执行: {exc}")
    if missing:
        print("修复指引：安装 ffmpeg（需含 ffprobe）并把其 bin 目录加入 PATH；"
              "本机已知安装位置 D:\\tools\\bin（gate_b0 ① 的 pytest 子进程会自动回退注入）。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
