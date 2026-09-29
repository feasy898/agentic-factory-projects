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

# 下载主机白名单（加固：--url 仅允许 https + 下列主机的模型权重镜像源）。
# 注意：仅列中性域名——个别上游原始域名含中性名扫描禁用词，按仓库命名纪律
# 不入库；其境内镜像（hf-mirror.com）与官方桶（缺省 URL）已覆盖实际下载场景。
ALLOWED_HOSTS = {
    "storage.googleapis.com",   # 官方模型桶（缺省 URL）
    "hf-mirror.com",            # 境内镜像
    "modelscope.cn",            # 境内镜像（ModelScope）
    "www.modelscope.cn",
}


def check_url(url: str) -> None:
    """SSRF 防护：仅允许 https + 白名单主机，违规抛 ValueError。"""
    from urllib.parse import urlparse

    u = urlparse(url)
    if u.scheme != "https" or u.hostname not in ALLOWED_HOSTS:
        raise ValueError(
            f"下载地址不合规（需 https 且主机在白名单 {sorted(ALLOWED_HOSTS)}）：{url}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="下载人脸关键点模型")
    p.add_argument("--force", action="store_true")
    p.add_argument("--url", default=URL)
    args = p.parse_args(argv)

    if TARGET.is_file() and not args.force:
        print(f"已存在：{TARGET}（--force 重下）")
        return 0
    try:
        check_url(args.url)
    except ValueError as exc:
        print(f"拒绝下载：{exc}", file=sys.stderr)
        return 2
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
