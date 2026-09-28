"""pipeline 命令行骨架（T1，argparse 实现）。

子命令：
  init        生成 jobs/<ep> 每集工作区目录（jobs 布局生成器）
  validate    校验契约文件（C1–C8，schema 见 pipeline/contracts.py）
  run         按依赖图运行一集（由 M14 任务队列实现，此处为占位）

用法示例：
  python -m pipeline.cli init ep01
  python -m pipeline.cli validate utterances ../../jobs/ep01/04_dial/utterances.jsonl
  python -m pipeline.cli run ep01 --langs en,es,ar --to m12

退出码：0 成功；1 校验/文件错误；2 未实现/用法错误。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import RootModel, ValidationError

from pipeline import contracts as C
from pipeline.config import load_pipeline_config
from pipeline.scaffold import LAYERS, create_workspace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.cli",
        description="短剧多国出海本地化引擎 —— 管线命令行（T1 骨架）",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="生成 jobs/<ep> 工作区目录骨架")
    p_init.add_argument("ep", help="集 ID，如 ep01")
    p_init.add_argument(
        "--jobs-dir",
        default=None,
        help="jobs 根目录（默认取 configs/pipeline.yaml paths.jobs_dir）",
    )

    p_val = sub.add_parser("validate", help="校验契约文件（C1–C8）")
    p_val.add_argument("kind", choices=sorted(C.CONTRACT_KINDS), help="契约类型")
    p_val.add_argument("path", help="契约文件路径（JSON 或 JSONL）")

    p_run = sub.add_parser("run", help="按依赖图运行一集（M14 实现前的占位）")
    p_run.add_argument("ep", help="集 ID，如 ep01")
    p_run.add_argument("--langs", default="en", help="目标语种，逗号分隔")
    p_run.add_argument("--to", default="m12", help="终止模块，如 m12")

    return parser


def cmd_init(args: argparse.Namespace) -> int:
    if args.jobs_dir:
        jobs_root = Path(args.jobs_dir)
    else:
        cfg = load_pipeline_config()
        jobs_root = Path(cfg["paths"]["jobs_dir"])
    dirs = create_workspace(args.ep, jobs_root)
    print(f"OK 已就绪 {len(dirs)} 个目录：{jobs_root / args.ep}")
    for layer in LAYERS:
        print(f"  {layer}/")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    code, cls, is_jsonl = C.CONTRACT_KINDS[args.kind]
    path = Path(args.path)
    if not path.exists():
        print(f"FAIL {code} 文件不存在: {path}")
        return 1
    try:
        if is_jsonl:
            obj = C.load_jsonl(path, cls)
            assert isinstance(obj, RootModel)
            n = len(obj.root)
            print(f"OK {code} {path}（{n} 条记录）")
        else:
            C.load_model(path, cls)
            print(f"OK {code} {path}")
    except ValidationError as exc:
        print(f"FAIL {code} {path}: {exc}")
        return 1
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    print(
        f"run {args.ep} --langs {args.langs} --to {args.to}: "
        "依赖图调度由 M14（任务队列与编排）实现，T1 骨架未实现。"
    )
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {"init": cmd_init, "validate": cmd_validate, "run": cmd_run}
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
