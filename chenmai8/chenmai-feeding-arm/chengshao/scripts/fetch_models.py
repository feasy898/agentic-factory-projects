"""模型权重下载（一次性，D1 环境步骤；权重不入库——.gitignore 含 *.task 与 models/）。

用法（任意目录）::

    python chengshao/scripts/fetch_models.py           # 已存在则跳过
    python chengshao/scripts/fetch_models.py --force   # 强制重下
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PKG_PARENT = Path(__file__).resolve().parents[1]
TARGET = PKG_PARENT / "models" / "face_landmarker.task"
URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="下载人脸关键点模型")
    p.add_argument("--force", action="store_true")
    p.add_argument("--url", default=URL)
    args = p.parse_args(argv)

    if TARGET.is_file() and not args.force:
        print(f"已存在：{TARGET}（--force 重下）")
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    print(f"下载 {args.url} -> {TARGET}")
    import urllib.request

    try:
        with urllib.request.urlopen(args.url, timeout=120) as resp:
            data = resp.read()
    except OSError as exc:
        print(f"下载失败：{exc}\n可经境外出口代理下载后手动放到 {TARGET}", file=sys.stderr)
        return 1
    if len(data) < 1_000_000:
        print(f"文件过小（{len(data)}B），疑似错误响应", file=sys.stderr)
        return 1
    TARGET.write_bytes(data)
    print(f"完成：{len(data)} 字节")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
