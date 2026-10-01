"""assetkit 命令行入口（python -m assetkit）。

    python -m assetkit run <输入...> --out DIR [--spec spec.json]
                          [--image-quality N] [--audio-bitrate K] [--max-edge N]
                          [--no-atlas] [--atlas-max-width N] [--extra-text S]
                          [--min-reduction F]
    python -m assetkit selftest [--keep]

run 退出码：0 成功；1 处理失败或 --min-reduction 未达；2 用法/环境错误。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import AssetkitError, __doc__ as _doc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="assetkit",
        description="素材处理流水线（M5）：压图/音频转码/字体子集/图集 + 优化映射与报告",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_run = sub.add_parser("run", help="处理素材目录/文件（可附 --spec 收集 spec 声明素材）")
    p_run.add_argument("inputs", nargs="*", help="素材文件或目录（目录递归；可与 --spec 同用）")
    p_run.add_argument("--out", required=True, help="输出目录（整体重建）")
    p_run.add_argument("--spec", default=None, help="PlayableSpec JSON：收集其 assets 声明且存在的素材")
    p_run.add_argument("--image-quality", type=int, default=75, help="有损 WebP 质量（默认 75）")
    p_run.add_argument("--audio-bitrate", type=int, default=48000, help="音频目标码率 bit/s（默认 48000）")
    p_run.add_argument("--max-edge", type=int, default=0, help="等比缩到最长边 ≤N 像素（0=不缩，默认）")
    p_run.add_argument("--no-atlas", action="store_true", help="不产出图集")
    p_run.add_argument("--atlas-max-width", type=int, default=1024, help="图集最大行宽（默认 1024）")
    p_run.add_argument("--extra-text", default="", help="字体子集追加字符（数字已内建）")
    p_run.add_argument("--min-reduction", type=float, default=None,
                       help="总降幅硬门（百分比，如 30.0）；未达 exit 1")

    p_selftest = sub.add_parser("selftest", help="合成素材端到端自测（压图/音频/字体/图集/optmap）")
    p_selftest.add_argument("--keep", action="store_true", help="保留临时目录（失败时恒保留）")

    return parser


def cmd_run(args: argparse.Namespace) -> int:
    from .pipeline import run_assetkit

    if not args.inputs and not args.spec:
        print("[assetkit] 未提供任何输入（素材路径或 --spec 至少一项）", file=sys.stderr)
        return 2
    report = run_assetkit(
        inputs=args.inputs,
        out=args.out,
        spec=args.spec,
        image_quality=args.image_quality,
        audio_bitrate=args.audio_bitrate,
        max_edge=args.max_edge,
        atlas=not args.no_atlas,
        atlas_max_width=args.atlas_max_width,
        extra_text=args.extra_text,
        min_reduction_pct=args.min_reduction,
    )
    totals = report["totals"]
    if totals.get("minReductionMet") is False:
        print(f"[assetkit] FAIL：总降幅 {totals['reductionPct']}% < 门 {totals['minReductionPct']}%",
              file=sys.stderr)
        return 1
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    from .selftest import run_selftest

    return run_selftest(keep=args.keep)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    try:
        if args.command == "run":
            return cmd_run(args)
        if args.command == "selftest":
            return cmd_selftest(args)
        parser.error(f"未知子命令 {args.command!r}")
        return 2
    except AssetkitError as exc:
        print(f"[assetkit] FAIL（exit {exc.exit_code}）：{exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    sys.exit(main())
