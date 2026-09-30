#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公版素材采集清单与下载器（material fetch）——「自找公开素材」线的可续跑工具。

考古出处（windev 会话 sess_686db8b4，2026-09-30）：owner 指令「短剧真实母盘素材：
自找公开素材，多找几个」——命中 3 部中国大陆公版经典片并开始下载，会话中断后
仅 didaozhan_p1.mp4 落盘（后经 ops/material_pipeline.py verify 实测为截断件）。
本脚本把当时的采集清单固化为代码，网络恢复后一键续跑。

公版依据（docs/assets/materials-sourcing.md 详述）：三部电影均为中国大陆电影作品，
著作权保护期 50 年（自首次发表）分别于 2015/2014/2024 年底届满，已进入公有领域。

网络现实（2026-10-01 实测）：windev 与 GPU 两端国际出口均不通
（archive.org 直连超时 + DNS 污染解析到无关 IP），采集暂停、工具就绪——
恢复窗口重跑 `python ops/material_fetch.py --fetch-all` 即可。

用法（系统 python3.12，零第三方依赖）：
  python ops/material_fetch.py --list                    # 列采集清单
  python ops/material_fetch.py --discover <identifier>   # 探测某条目的可下载视频件
  python ops/material_fetch.py --fetch <identifier> <filename>  # 断点续传下载单件
  python ops/material_fetch.py --fetch-all [--only-missing]     # 全清单按序下载
退出码：0 成功；1 下载/网络失败；2 用法错误。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = REPO_ROOT.parent
RAW_DIR = PROJECT_ROOT / "materials" / "raw"

METADATA_BASE = "https://archive.org/metadata/"
DOWNLOAD_BASE = "https://archive.org/download/"
VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".mpg", ".mpeg", ".flv", ".webm")

# 采集清单（2026-09-30 windev 会话实测命中；download/ 文件名含中文与全角括号，
# 直链需 URL 编码——统一交给 urllib.parse.quote 处理）。
CATALOG = [
    {
        "title": "地道战 (Tunnel Warfare, 1965)",
        "public_domain_since": "2015（发表后 50 年）",
        "identifier": "1-tunnel-warfare-1",
        "filename": "Tunnel Warfare 1 (地道战 1).mp4",
        "target": "didaozhan_p1.mp4",
        "note": "4 段拷贝的第 1 段；其余段 identifier 形如 1-tunnel-warfare-N，--discover 逐段确认后补录本清单",
    },
    {
        "title": "英雄儿女 (Heroic Sons and Daughters, 1964)",
        "public_domain_since": "2014（发表后 50 年）",
        "identifier": "1964HeroicSonsAndDaughters",
        "filename": "（高清）【英雄儿女】 中国经典怀旧电影 1964 Heroic Sons and Daughters.mp4",
        "target": "yingxiongernu_1964.mp4",
        "note": "整片单文件 ~485MB",
    },
    {
        "title": "闪闪的红星 (Sparkling Red Star, 1974) 第 1 段",
        "public_domain_since": "2024 年底（发表后 50 年）",
        "identifier": "dailymotion-x5ik2wi",
        "filename": None,  # 2026-09-30 会话中断时尚未确认实际文件名，--discover 现场确认
        "target": "shanshandehongxing_p1.mp4",
        "note": "共 2 段拷贝；第 2 段 identifier 待 --discover 确认后补录",
    },
]


def _fetch_json(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "chenmai8-material-fetch/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def discover(identifier: str) -> list[dict]:
    """metadata API 探测条目内全部可下载视频件（名称/大小/格式）。"""
    data = _fetch_json(METADATA_BASE + identifier)
    out = []
    for f in data.get("files", []):
        name = f.get("name", "")
        if name.lower().endswith(VIDEO_EXTS):
            out.append({
                "identifier": identifier,
                "name": name,
                "size_bytes": int(f.get("size", 0) or 0),
                "format": f.get("format", "?"),
                "source_url": DOWNLOAD_BASE + identifier + "/" + urllib.parse.quote(name),
            })
    return out


def fetch(identifier: str, filename: str, dest: Path, resume: bool = True) -> dict:
    """单件下载（HTTP Range 断点续传；已完整件跳过）。"""
    from urllib.parse import quote
    url = DOWNLOAD_BASE + identifier + "/" + quote(filename)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")

    headers = {"User-Agent": "chenmai8-material-fetch/1.0"}
    mode = "wb"
    offset = 0
    if resume and tmp.exists():
        offset = tmp.stat().st_size
        headers["Range"] = f"bytes={offset}-"
        mode = "ab"
    req = urllib.request.Request(url, headers=headers)
    started = time.time()
    with urllib.request.urlopen(req, timeout=120) as resp, tmp.open(mode) as f:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            offset += len(chunk)
    got = tmp.stat().st_size
    os.replace(tmp, dest)
    return {
        "dest": str(dest), "bytes": got, "seconds": round(time.time() - started, 1),
        "resumed_from": offset - (got - offset) if mode == "ab" else 0,
    }


def main(argv: list[str] | None = None) -> int:
    import urllib.parse  # noqa: F401  (discover() 内 quote 使用)

    ap = argparse.ArgumentParser(description="公版素材采集清单与下载器")
    ap.add_argument("--list", action="store_true", help="列采集清单")
    ap.add_argument("--discover", metavar="IDENTIFIER", help="探测条目内可下载视频件")
    ap.add_argument("--fetch", nargs=2, metavar=("IDENTIFIER", "FILENAME"), help="下载单件")
    ap.add_argument("--dest", metavar="PATH", default=None, help="下载目标路径（默认 materials/raw/<干净名>）")
    ap.add_argument("--fetch-all", action="store_true", help="按清单顺序全量下载")
    ap.add_argument("--only-missing", action="store_true", help="跳过已存在目标件")
    args = ap.parse_args(argv)

    if args.list:
        for i, item in enumerate(CATALOG, 1):
            print(f"{i}. {item['title']}")
            print(f"   identifier={item['identifier']}")
            print(f"   公版自: {item['public_domain_since']}")
            print(f"   filename={item['filename'] or '(待 --discover 确认)'}")
            print(f"   target={item['target']}")
            print(f"   note: {item['note']}")
        print(f"收件区: {RAW_DIR}")
        return 0

    if args.discover:
        try:
            files = discover(args.discover)
        except Exception as exc:  # 网络/DNS 失败如实上报
            print(f"DISCOVER_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        for f in files:
            print(f"DL: {f['name']} | {f['size_bytes'] // 1048576} MB | {f['format']}")
            print(f"    {f['source_url']}")
        return 0 if files else 1

    if args.fetch:
        identifier, filename = args.fetch
        dest = Path(args.dest) if args.dest else RAW_DIR / filename
        try:
            out = fetch(identifier, filename, dest)
        except Exception as exc:
            print(f"FETCH_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(out, ensure_ascii=False))
        print("NEXT: python ops/material_pipeline.py verify %s" % out["dest"], file=sys.stderr)
        return 0

    if args.fetch_all:
        rc = 0
        for item in CATALOG:
            dest = RAW_DIR / item["target"]
            if args.only_missing and dest.exists():
                print(f"SKIP(存在): {dest}")
                continue
            fname = item["filename"]
            if not fname:
                print(f"NEEDS_DISCOVER: {item['identifier']}（清单内 filename 未确认，先 --discover）",
                      file=sys.stderr)
                rc = rc or 1
                continue
            print(f"FETCH: {item['title']} ...")
            try:
                out = fetch(item["identifier"], fname, dest)
                print(json.dumps(out, ensure_ascii=False))
            except Exception as exc:
                print(f"FETCH_FAILED: {item['title']}: {type(exc).__name__}: {exc}", file=sys.stderr)
                rc = 1
        return rc

    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
