"""pipeline 命令行骨架（T1，argparse 实现）。

子命令：
  init        生成 jobs/<ep> 每集工作区目录（jobs 布局生成器）
  validate    校验契约文件（C1–C8，schema 见 pipeline/contracts.py）
  run         按依赖图运行一集（M14 任务队列实现：enqueue + resume）
  enqueue     入队 ep×lang 作业（M14，不执行）
  status      查看作业/任务四态快照（M14）
  resume      断点续跑（done 且产物在位的步骤跳过；陈旧 running 收回重跑）

用法示例：
  python -m pipeline.cli init ep01
  python -m pipeline.cli validate utterances ../../jobs/ep01/04_dial/utterances.jsonl
  python -m pipeline.cli run ep01 --langs en,es,ar --to m15
  python -m pipeline.cli enqueue ep01 --langs en --to m15
  python -m pipeline.cli status
  python -m pipeline.cli resume --job 3

退出码：0 成功；1 校验/文件/执行失败；2 未实现/用法错误。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import RootModel, ValidationError

from pipeline import contracts as C
from pipeline.config import load_pipeline_config
from pipeline.queue import Queue, QueueUsageError, default_graph, graph_from_file
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

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--jobs-dir", default=None,
                        help="jobs 根目录（默认 configs/pipeline.yaml）")
    common.add_argument("--db", default=None,
                        help="队列库路径（默认 <jobs-dir>/jobs.db）")
    common.add_argument("--metrics-db", default=None,
                        help="记账库路径（默认 <jobs-dir>/metrics.db）")
    common.add_argument("--graph", default=None,
                        help="自定义步骤图 JSON（默认 pipeline.queue.DEFAULT_GRAPH）")

    p_run = sub.add_parser("run", parents=[common],
                           help="按依赖图运行一集（enqueue + resume）")
    p_run.add_argument("ep", help="集 ID，如 ep01")
    p_run.add_argument("--langs", default="en", help="目标语种，逗号分隔")
    p_run.add_argument("--to", default="m15",
                       help="终止模块（默认 m15=当前默认图全链；"
                            "规划示例 --to m12 待 M12 模块入库后可用）")
    p_run.add_argument("--input", default="", help="原始素材路径（m1 的 --in）")
    p_run.add_argument("--param", action="append", default=[],
                       metavar="K=V", help="附加步骤参数（可重复）")

    p_enq = sub.add_parser("enqueue", parents=[common],
                           help="入队 ep×lang 作业（不执行）")
    p_enq.add_argument("ep", help="集 ID，如 ep01")
    p_enq.add_argument("--langs", default="en", help="目标语种，逗号分隔")
    p_enq.add_argument("--to", required=True, help="终止模块，如 m15")
    p_enq.add_argument("--input", default="", help="原始素材路径（m1 的 --in）")
    p_enq.add_argument("--param", action="append", default=[],
                       metavar="K=V", help="附加步骤参数（可重复）")

    p_st = sub.add_parser("status", parents=[common],
                          help="作业/任务四态快照")
    p_st.add_argument("--job", type=int, default=None, help="只看该作业")
    p_st.add_argument("--ep", default="", help="按集过滤")
    p_st.add_argument("--lang", default="", help="按语种过滤")
    p_st.add_argument("--json", action="store_true", help="输出 JSON")

    p_res = sub.add_parser("resume", parents=[common],
                           help="断点续跑（完成且产物在位的步骤跳过）")
    p_res.add_argument("--job", type=int, action="append", default=[],
                       help="续跑该作业（可重复）")
    p_res.add_argument("--ep", default="", help="续跑该集全部作业")
    p_res.add_argument("--lang", default="", help="配合 --ep 过滤语种")
    p_res.add_argument("--all", action="store_true", help="续跑全部作业")

    return parser


def _jobs_root(args: argparse.Namespace) -> Path:
    if args.jobs_dir:
        return Path(args.jobs_dir)
    return Path(load_pipeline_config()["paths"]["jobs_dir"])


def _queue(args: argparse.Namespace, to_step: str | None = None) -> Queue:
    graph = graph_from_file(args.graph) if args.graph else default_graph()
    if to_step is not None and to_step not in graph:
        raise QueueUsageError(
            f"未知步骤 {to_step!r}（可用：{', '.join(sorted(graph))}）")
    return Queue(_jobs_root(args), db_path=args.db,
                 metrics_db_path=getattr(args, "metrics_db", None),
                 graph=graph)


def _params(args: argparse.Namespace) -> dict[str, str]:
    params: dict[str, str] = {}
    for item in getattr(args, "param", []) or []:
        key, _, value = item.partition("=")
        if not key:
            raise QueueUsageError(f"--param 需 K=V 形式: {item!r}")
        params[key] = value
    if getattr(args, "input", ""):
        params["input"] = args.input
    return params


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
    q = _queue(args, to_step=args.to)
    out = q.run(args.ep, args.langs.split(","), args.to, _params(args))
    for job in out["jobs"]:
        print(f"JOB #{job['job']} {job['ep']}/{job['lang']} → {job['to']}: "
              f"{job['state']}")
    return 0 if out["ok"] else 1


def cmd_enqueue(args: argparse.Namespace) -> int:
    q = _queue(args, to_step=args.to)
    ids = q.enqueue(args.ep, args.langs.split(","), args.to, _params(args))
    print("OK 入队作业:", ", ".join(f"#{i}" for i in ids))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    q = _queue(args)
    snap = q.status(ep=args.ep, lang=args.lang, job_id=args.job)
    if args.json:
        print(json.dumps(snap, ensure_ascii=False, indent=1))
        return 0
    for job in snap["jobs"]:
        print(f"JOB #{job['id']} {job['ep']}/{job['lang']} to={job['to_step']} "
              f"state={job['state']}")
        for t in job["tasks"]:
            print(f"  [{t['lang'] or 'ep'}] {t['module']:<6} {t['state']:<8} "
                  f"attempts={t['attempts']} {t['note']}")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    q = _queue(args)
    out = q.resume(job_ids=args.job or None, ep=args.ep, lang=args.lang,
                   all_jobs=args.all)
    print(f"resume 收回陈旧 running 任务 {out['reclaimed']} 个")
    for job in out["jobs"]:
        print(f"JOB #{job['job']} {job['ep']}/{job['lang']} → {job['to']}: "
              f"{job['state']}")
        for t in job["tasks"]:
            mark = "skip" if t.get("skipped") else (
                "refuse" if t.get("refused") else "run  ")
            print(f"  [{t['lang'] or 'ep'}] {t['module']:<6} {mark} "
                  f"{t['state']}")
    return 0 if out["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {"init": cmd_init, "validate": cmd_validate, "run": cmd_run,
                "enqueue": cmd_enqueue, "status": cmd_status,
                "resume": cmd_resume}
    try:
        return handlers[args.cmd](args)
    except QueueUsageError as exc:
        print(f"用法错误: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # 执行期失败：exit 1（不吞栈，简明一行）
        print(f"FAIL {args.cmd}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
