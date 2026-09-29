"""pfcore 命令行入口（编排 CLI）。

子命令进度（命令名裁决见 docs/assets/specs/pipeline-contract.md §1：全流水线冻结名为
``make``，与规划一致；占位名 ``run`` 已删除，不得再引入第三个全流水线命令名）：
- validate     校验 PlayableSpec JSON（schema v1 + 不变式 I1-I5 + 类型化解析）  [M1 已实现]
- make         全流水线编排：validate → 模板构建 → 多渠道打包 → qacore 质检 →
               summary/二维码/墙钟计时/artifacts/demo-prebuilt 兜底目录        [M9 已实现]
- serve        局域网静态伺服既有产物目录（demo-prebuilt/裸预览）+ 重建汇总页
               （渠道包下载 + 质检报告链接）与二维码                          [反馈行动 2 已实现]
- build        按 spec 构建单个模板产物                           （M3/M4 占位）
- pack         全渠道打包                                          （M4 占位）
- rules-check  校验渠道规则库 channel-rules                        （M12 占位）

用法：
    python -m pfcore validate <spec.json> [more.json ...]
    python -m pfcore make --spec <spec.json> [--locales en,ar] [--channels all]
    python -m pfcore serve [--root artifacts/demo-prebuilt] [--port 8618] [--host <ip>]
validate 路径参数支持 glob（如 ``specs-eval/bad/*.json``，Windows shell 不展开时由本
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
        description="试玩广告生产线编排 CLI（validate/make/serve 已实现；build/pack/rules-check 随里程碑落地）",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_validate = sub.add_parser(
        "validate", help="校验 PlayableSpec JSON（schema v1 + 不变式，错误定位到字段路径）"
    )
    p_validate.add_argument(
        "spec", nargs="+", help="PlayableSpec JSON 文件路径（支持 glob 模式）"
    )

    p_make = sub.add_parser(
        "make", help="全流水线：校验→模板构建→渠道打包→qacore 质检→summary+二维码+计时+demo-prebuilt"
    )
    p_make.add_argument("--spec", required=True, help="PlayableSpec JSON 文件路径（必填）")
    p_make.add_argument(
        "--locales", default=None,
        help="逗号分隔的语言列表（默认取 spec i18n.defaultLocale）",
    )
    p_make.add_argument(
        "--channels", default="applovin,meta,mintegral",
        help="逗号分隔的渠道列表或 all（默认规则库已冻结的三投放渠道；preview 为本地渠道不打包）",
    )
    p_make.add_argument(
        "--out", default="artifacts",
        help="输出根目录（默认 artifacts；渠道包/预览/demo-prebuilt 均落在其下）",
    )
    p_make.add_argument(
        "--serve-port", type=int, default=8618,
        help="兜底静态伺服端口（默认 8618；被占用时向后顺延）",
    )
    p_make.add_argument(
        "--serve-host", default=None,
        help="二维码指向的主机 IP（默认自动探测局域网地址；手机须与本机同网段可达）",
    )
    p_make.add_argument(
        "--no-serve", action="store_true",
        help="不启动/复用本地静态伺服（仍产出二维码与预览链接，自行伺服 demo-prebuilt）",
    )
    p_make.add_argument(
        "--no-assetkit", action="store_true",
        help="跳过素材管线（M5 assetkit：spec 声明素材压图/转音频/字体子集/图集，"
             "构建期经优化映射接线内联）。默认启用：声明素材存在时自动优化，"
             "无声明素材时为空跑（零开销）",
    )

    p_serve = sub.add_parser(
        "serve", help="局域网静态伺服演示产物目录（demo-prebuilt/裸预览）+ 重建汇总页与二维码"
    )
    p_serve.add_argument(
        "--root", default="artifacts/demo-prebuilt",
        help="被伺服的产物目录（默认 artifacts/demo-prebuilt；也可以是裸预览目录如 artifacts/preview）",
    )
    p_serve.add_argument(
        "--port", type=int, default=8618,
        help="伺服端口（默认 8618；被占用时向后顺延）",
    )
    p_serve.add_argument(
        "--host", default=None,
        help="二维码指向的主机 IP（默认自动探测局域网地址；手机须与本机同网段可达）",
    )

    p_build = sub.add_parser("build", help="按 spec 构建模板产物（占位）")
    p_build.add_argument("spec", help="PlayableSpec JSON 文件路径")
    p_build.add_argument("--channel", default="preview", help="目标渠道（默认 preview）")
    p_build.add_argument("--locale", default="en", help="输出语言（默认 en）")
    p_build.add_argument("--out", default="artifacts", help="输出目录（默认 artifacts）")

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
    """入口函数；仍为占位的子命令回显占位状态并返回 2。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    if args.command == "validate":
        return cmd_validate(args)
    if args.command == "make":
        # 延迟导入：validate 路径不背负 make 的依赖（qrcode 等）。
        from .make import cmd_make

        return cmd_make(args)
    if args.command == "serve":
        from .serve import cmd_serve

        return cmd_serve(args)
    print(f"[pfcore] 子命令 {args.command!r} 尚未实现（当前为占位）。")
    return 2


if __name__ == "__main__":
    sys.exit(main())
