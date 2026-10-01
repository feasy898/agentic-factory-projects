#!/usr/bin/env python3
"""批量重命名：把目录下匹配 pattern 的文件改名为 <前缀><三位序号><原扩展名>。

默认 dry-run（只打印预览，不改任何文件）；--apply 才真正重命名并写出 rename-log.tsv。
冲突策略：目标名已存在一律跳过并记录，绝不覆盖。
"""
import argparse
import glob
import os
import sys

LOG_NAME = "rename-log.tsv"


def iter_matches(directory: str, pattern: str):
    """在 directory 下做非递归 glob 匹配，只保留文件，按原文件名排序。"""
    full = os.path.join(directory, pattern)
    hits = []
    for path in glob.glob(full):
        name = os.path.basename(path)
        if os.path.isfile(path):
            hits.append(name)
    return sorted(hits)


def target_name(prefix: str, index: int, original: str) -> str:
    """目标名 = 固定前缀 + 3 位序号 + 原扩展名（含大小写，原样保留）。"""
    _, ext = os.path.splitext(original)
    return f"{prefix}{index:03d}{ext}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("directory", help="目标目录（不递归子目录）")
    ap.add_argument("--pattern", required=True, help='相对 directory 的 glob 模式，如 "*.log"')
    ap.add_argument("--prefix", required=True, help="目标名固定前缀：<prefix><001><.ext>")
    ap.add_argument("--apply", action="store_true",
                    help="执行重命名并写出 rename-log.tsv（默认 dry-run 只预览）")
    args = ap.parse_args()

    if not os.path.isdir(args.directory):
        print(f"error: not a directory: {args.directory}", file=sys.stderr)
        return 2

    names = iter_matches(args.directory, args.pattern)
    rows = []  # (status, src_path, dst_path)
    skipped = 0
    for i, name in enumerate(names, start=1):
        src = os.path.join(args.directory, name)
        dst = os.path.join(args.directory, target_name(args.prefix, i, name))
        if os.path.lexists(dst):
            # 目标已存在（含目标名与原名相同的自指向）：跳过并记录，绝不覆盖
            rows.append(("skipped", src, dst))
            skipped += 1
        elif args.apply:
            os.rename(src, dst)  # 仅在 dst 不存在时才会走到这里
            rows.append(("renamed", src, dst))
        else:
            rows.append(("would-rename", src, dst))

    for status, src, dst in rows:
        print(f"{status}\t{src} -> {dst}")

    if args.apply:
        # 清单写到当前工作目录（而非目标目录），避免日志本身落入匹配范围
        with open(LOG_NAME, "w", encoding="utf-8", newline="") as fh:
            fh.write("status\tsrc\tdst\n")
            for status, src, dst in rows:
                fh.write(f"{status}\t{src}\t{dst}\n")
        print(f"log: {os.path.abspath(LOG_NAME)}")

    total = len(rows)
    print(f"summary: {total} matched, {skipped} skipped, "
          f"{total - skipped} {'renamed' if args.apply else 'would-rename'}")
    return 1 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())
