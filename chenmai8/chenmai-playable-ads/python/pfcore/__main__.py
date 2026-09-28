"""pfcore 命令行入口（骨架占位版）。

当前阶段只提供 argparse 骨架，各子命令的具体实现随里程碑逐个落地：
- validate     校验 PlayableSpec JSON（schema + 不变式）          （M1）
- build        按 spec 构建单个模板产物                           （M3/M4）
- run          跑完整流水线（素材→构建→打包→质检→汇总）           （M9）
- pack         全渠道打包                                          （M4）
- rules-check  校验渠道规则库 channel-rules                        （M12）
"""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    """构建 pfcore 的 argparse 解析器（骨架）。"""
    parser = argparse.ArgumentParser(
        prog="pfcore",
        description="试玩广告生产线编排 CLI（骨架版：子命令暂为占位实现）",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_validate = sub.add_parser(
        "validate", help="校验 PlayableSpec JSON（schema + 不变式）"
    )
    p_validate.add_argument("spec", help="PlayableSpec JSON 文件路径")

    p_build = sub.add_parser("build", help="按 spec 构建模板产物")
    p_build.add_argument("spec", help="PlayableSpec JSON 文件路径")
    p_build.add_argument("--channel", default="preview", help="目标渠道（默认 preview）")
    p_build.add_argument("--locale", default="en", help="输出语言（默认 en）")
    p_build.add_argument("--out", default="artifacts", help="输出目录（默认 artifacts）")

    p_run = sub.add_parser("run", help="跑完整流水线（素材→构建→打包→质检→汇总）")
    p_run.add_argument("spec", help="PlayableSpec JSON 文件路径")
    p_run.add_argument(
        "--locales", default="en", help="逗号分隔的语言列表（默认 en）"
    )
    p_run.add_argument(
        "--channels", default="all", help="逗号分隔的渠道列表或 all（默认 all）"
    )

    p_pack = sub.add_parser("pack", help="按渠道规则库打包产物")
    p_pack.add_argument("spec", help="PlayableSpec JSON 文件路径")
    p_pack.add_argument(
        "--all-channels", action="store_true", help="打包规则库内全部渠道"
    )
    p_pack.add_argument("--locale", default="en", help="输出语言（默认 en）")
    p_pack.add_argument("--out", default="artifacts", help="输出目录（默认 artifacts）")

    sub.add_parser(
        "rules-check", help="校验渠道规则库（channel-rules）的模式与渠道齐全性"
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """入口函数；骨架阶段仅回显子命令占位状态。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        # 无子命令时打印帮助，方便上手。
        parser.print_help()
        return 0
    print(f"[pfcore] 子命令 {args.command!r} 尚未实现（当前为骨架占位）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
