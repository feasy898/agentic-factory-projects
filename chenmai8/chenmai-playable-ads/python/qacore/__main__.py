"""qacore 命令行入口：python -m qacore run <产物路径> --channel preview --out <报告路径>。"""
from __future__ import annotations

import argparse
import sys

from . import cli


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="qacore",
        description="无头自动质检器：本地伺服产物、无头浏览器打开、记录请求与截屏、输出质检报告。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="对单个产物 HTML 执行质检并写出 report.json")
    p_run.add_argument("artifact", help="产物 HTML 文件路径")
    p_run.add_argument("--channel", default="preview", help="渠道 id（写入报告；雏形阶段仅透传）")
    p_run.add_argument("--out", required=True, help="报告 JSON 输出路径")
    p_run.add_argument("--port", type=int, default=0, help="本地伺服端口（默认临时端口）")
    p_run.add_argument(
        "--max-load-sec",
        type=float,
        default=2.0,
        help="CHK09 本地加载时长阈值（秒），默认 2.0",
    )

    args = parser.parse_args(argv)
    if args.command == "run":
        return cli.cmd_run(args)
    parser.error(f"未知子命令：{args.command}")  # pragma: no cover
    return 2


if __name__ == "__main__":
    sys.exit(main())
