"""pfcore 命令行入口（编排 CLI）。

子命令进度：
- validate     校验 PlayableSpec JSON（schema v1 + 不变式 I1-I5 + 类型化解析）  [M1 已实现]
- build        按 spec 构建单个模板产物                           （M3/M4 占位）
- run          跑完整流水线（素材→构建→打包→质检→汇总）           （M9 占位）
- pack         全渠道打包                                          （M4 占位）
- rules-check  校验渠道规则库 channel-rules                        （M12 占位）

validate 用法：
    python -m pfcore validate <spec.json> [more.json ...]
路径参数支持 glob（如 ``specs-eval/bad/*.json``，Windows shell 不展开时由本
命令自行展开）；全部文件通过才退出 0，否则退出 1。
"""

from __future__ import annotations

import argparse
import glob as globlib
import sys
from pathlib import Path

from .validation import validate_spec_file

# Windows 控制台默认非 UTF-8 代码页，固定本进程输出编码，避免中文乱码。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    """构建 pfcore 的 argparse 解析器。"""
    parser = argparse.ArgumentParser(
        prog="pfcore",
        description="试玩广告生产线编排 CLI（validate 已实现；build/run/pack/rules-check 随里程碑落地）",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_validate = sub.add_parser(
        "validate", help="校验 PlayableSpec JSON（schema v1 + 不变式，错误定位到字段路径）"
    )
    p_validate.add_argument(
        "spec", nargs="+", help="PlayableSpec JSON 文件路径（支持 glob 模式）"
    )

    p_build = sub.add_parser("build", help="按 spec 构建模板产物（占位）")
    p_build.add_argument("spec", help="PlayableSpec JSON 文件路径")
    p_build.add_argument("--channel", default="preview", help="目标渠道（默认 preview）")
    p_build.add_argument("--locale", default="en", help="输出语言（默认 en）")
    p_build.add_argument("--out", default="artifacts", help="输出目录（默认 artifacts）")

    p_run = sub.add_parser("run", help="跑完整流水线（占位）")
    p_run.add_argument("spec", help="PlayableSpec JSON 文件路径")
    p_run.add_argument("--locales", default="en", help="逗号分隔的语言列表（默认 en）")
    p_run.add_argument(
        "--channels", default="all", help="逗号分隔的渠道列表或 all（默认 all）"
    )

    p_pack = sub.add_parser("pack", help="按渠道规则库打包产物（占位）")
    p_pack.add_argument("spec", help="PlayableSpec JSON 文件路径")
    p_pack.add_argument("--all-channels", action="store_true", help="打包规则库内全部渠道")
    p_pack.add_argument("--locale", default="en", help="输出语言（默认 en）")
    p_pack.add_argument("--out", default="artifacts", help="输出目录（默认 artifacts）")

    sub.add_parser(
        "rules-check", help="校验渠道规则库（channel-rules）的模式与渠道齐全性（占位）"
    )

    return parser


def _expand_spec_paths(patterns: list[str]) -> tuple[list[Path], list[str]]:
    """展开路径参数中的 glob；返回 (存在的文件列表, 无匹配的模式列表)。"""
    files: list[Path] = []
    unmatched: list[str] = []
    for pattern in patterns:
        hits = sorted(globlib.glob(pattern, recursive=True))
        if hits:
            files.extend(Path(h) for h in hits)
        elif Path(pattern).is_file():
            files.append(Path(pattern))
        else:
            unmatched.append(pattern)
    return files, unmatched


def cmd_validate(args: argparse.Namespace) -> int:
    """validate 子命令：任何 issue（含文件缺失/解析失败）都计入失败。"""
    files, unmatched = _expand_spec_paths(args.spec)
    failures = 0
    for pattern in unmatched:
        print(f"INVALID <pattern>: 模式无匹配文件：{pattern} [io-not-found]")
        failures += 1
    if not files and not unmatched:
        print("INVALID <args>: 未提供任何 spec 文件")
        return 1
    for file in files:
        issues = validate_spec_file(file)
        if not issues:
            print(f"OK      {file.as_posix()}")
            continue
        failures += 1
        print(f"INVALID {file.as_posix()}")
        for issue in issues:
            print(f"  {issue.render()}")
    total = len(files) + len(unmatched)
    passed = total - failures
    print(f"validate: {passed}/{total} 通过")
    return 0 if failures == 0 else 1


def main(argv: list[str] | None = None) -> int:
    """入口函数；未实现的子命令回显占位状态并返回 2。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    if args.command == "validate":
        return cmd_validate(args)
    print(f"[pfcore] 子命令 {args.command!r} 尚未实现（当前为占位）。")
    return 2


if __name__ == "__main__":
    sys.exit(main())
