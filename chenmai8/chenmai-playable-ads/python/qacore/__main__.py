"""qacore 命令行入口：python -m qacore run <产物路径> --channel preview --autoplay。

报告默认写到产物旁（<产物名>.report.json）；--autoplay 开启自动试玩
（经 __PF_QC__.hint() 用真实 pointer 事件驱动，默认 45s 预算）。
"""
from __future__ import annotations

import argparse
import sys

from . import cli


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="qacore",
        description="无头自动质检器：本地伺服产物、双视口仿真、记录请求与截屏、"
                    "（--autoplay 时）经 __PF_QC__ 自动试玩到结束页，输出质检报告。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="对单个产物 HTML 执行质检并写出 report.json")
    p_run.add_argument("artifact", help="产物 HTML 文件路径")
    p_run.add_argument("--channel", default="preview", help="渠道 id（对照 channel-rules 判定包体上限）")
    p_run.add_argument(
        "--out", default=None,
        help="报告 JSON 输出路径（默认：产物旁 <产物名>.report.json）",
    )
    p_run.add_argument("--port", type=int, default=0, help="本地伺服端口（默认临时端口）")
    p_run.add_argument(
        "--max-load-sec", type=float, default=2.0,
        help="CHK09 本地加载时长阈值（秒），默认 2.0",
    )
    p_run.add_argument(
        "--autoplay", action="store_true",
        help="开启自动试玩：经 __PF_QC__.hint() 用真实 pointer 事件驱动到 pf:end",
    )
    p_run.add_argument(
        "--autoplay-timeout", type=float, default=45.0,
        help="自动试玩时长预算（秒），默认 45（对应 qc.autoplayTimeoutSec）",
    )

    args = parser.parse_args(argv)
    if args.command == "run":
        return cli.cmd_run(args)
    parser.error(f"未知子命令：{args.command}")  # pragma: no cover
    return 2


if __name__ == "__main__":
    sys.exit(main())
