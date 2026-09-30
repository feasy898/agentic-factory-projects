"""CLI: python -m src.cli <子命令>。

子命令: initdb / status / ingest / run / compose / report
路径根 = 环境变量 CRADLE_ROOT, 缺省为仓库根目录。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import db as db_mod
from .config import default_db_path, load_settings, project_root


def _open_db(args) -> db_mod.DB:
    db = db_mod.DB(getattr(args, "db", None) or default_db_path())
    db.migrate()
    return db


def _setup_logging(verbose: bool = False) -> logging.Logger:
    log = logging.getLogger("cradle")
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    if not log.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
    return log


# ---------------- 子命令 ----------------

def cmd_initdb(args) -> int:
    db = _open_db(args)
    print(f"数据库就绪: {db.path} (schema v{db.schema_version()})")
    db.close()
    return 0


def cmd_status(args) -> int:
    db = _open_db(args)
    counts = db.counts_by_status()
    print("任务状态计数:")
    for k, v in counts.items():
        print(f"  {k:10s} {v}")
    total = sum(counts.values())
    print(f"  {'total':10s} {total}")
    cands = db._query("SELECT verdict, COUNT(*) AS c FROM candidates GROUP BY verdict")
    if cands:
        print("候选判定计数: " + ", ".join(f"{r['verdict']}={r['c']}" for r in cands))
    for ev in db.recent_events(limit=args.events):
        print(f"[{ev['ts']}] {ev['level']}: {ev['msg']}")
    db.close()
    return 0


def cmd_ingest(args) -> int:
    from .schema import SchemaError, load_shotcard

    db = _open_db(args)
    path = Path(args.path)
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    if not files:
        print(f"未找到镜头卡: {path}", file=sys.stderr)
        return 1
    ok = fail = 0
    for f in files:
        try:
            card = load_shotcard(f)
            tid = db.ingest_task(card["shot_id"], card["narrative_slot"], card["lane"],
                                 card_json=card, template=args.template)
            ok += 1
            print(f"ingest {card['shot_id']} (task#{tid}, lane={card['lane']}, template={args.template})")
        except (SchemaError, ValueError) as e:
            fail += 1
            print(f"拒绝 {f.name}: {e}", file=sys.stderr)
    print(f"ingest 完成: {ok} 成功, {fail} 拒绝")
    db.close()
    return 0 if fail == 0 else 2


def cmd_run(args) -> int:
    from .orchestrator import Orchestrator

    log = _setup_logging(getattr(args, "verbose", False))
    if args.task_file:
        code = cmd_ingest(argparse.Namespace(path=args.task_file, template=args.template, db=args.db))
        if code != 0:
            return code
    db = _open_db(args)
    orch = Orchestrator(db, settings=load_settings(), log=lambda lvl, msg: (db.log_event(lvl, msg),
                                                                            log.log(logging.INFO if lvl == "info" else logging.WARNING, msg)))
    if args.once:
        n = orch.run_once()
        log.info(f"run --once: 推进 {n} 个任务")
    else:
        log.info("编排主循环启动 (Ctrl-C 退出; 建议配合 nohup 使用)")
        orch.run_forever(poll_interval=args.poll)
    db.close()
    return 0


def cmd_compose(args) -> int:
    from .orchestrator import Orchestrator

    db = _open_db(args)
    orch = Orchestrator(db, settings=load_settings())
    outputs = orch.compose_ready()
    print(json.dumps({"composed": outputs}, ensure_ascii=False, indent=2))
    db.close()
    return 0


def cmd_report(args) -> int:
    db = _open_db(args)
    counts = db.counts_by_status()
    total = sum(counts.values())
    tasks = db.list_tasks()
    fallback_delivered = sum(
        1 for t in tasks
        if t["status"] in ("fallback", "composed") and (db.selected_candidate(t["shot_id"]) or {}).get("verdict") == "fallback"
    )
    accepted_delivered = sum(
        1 for t in tasks
        if t["status"] in ("accepted", "composed") and (db.selected_candidate(t["shot_id"]) or {}).get("verdict") not in (None, "fallback")
    )
    reached_delivery = sum(counts.get(s, 0) for s in ("accepted", "fallback", "composed"))
    not_finished = sum(counts.get(s, 0) for s in ("pending", "generating", "gating", "retrying"))
    report = {
        "tasks_total": total,
        "by_status": counts,
        "accepted_delivered": accepted_delivered,
        "fallback_delivered": fallback_delivered,
        "yield_accepted_rate": round(accepted_delivered / total, 4) if total else None,
        "yield_with_fallback_rate": round(reached_delivery / total, 4) if total else None,
        "unfinished_or_blocked": {"unfinished": not_finished, "blocked": counts.get("blocked", 0)},
        "candidates_by_verdict": {r["verdict"]: r["c"] for r in db._query(
            "SELECT verdict, COUNT(*) AS c FROM candidates GROUP BY verdict")},
        "api_usage": db.api_usage_summary(),
        "blocked_reasons": [
            {"shot_id": t["shot_id"], "reason": t["error"]} for t in tasks if t["status"] == "blocked"
        ],
    }
    db.close()
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"报告已写入 {args.out}")
    print(text)
    return 0


# ---------------- argparse ----------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m src.cli", description="PROJECT CRADLE 管线 CLI")
    p.add_argument("--db", help="SQLite 路径(缺省 config/settings.yaml paths.db)")
    p.add_argument("--root", help="项目根(缺省 CRADLE_ROOT 或仓库根)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("initdb", help="建库+迁移").set_defaults(func=cmd_initdb)

    s = sub.add_parser("status", help="各状态计数+最近事件")
    s.add_argument("--events", type=int, default=10)
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("ingest", help="镜头卡 JSON → 任务表")
    s.add_argument("path", help="镜头卡文件或目录")
    s.add_argument("--template", default=None, help="归属叙事模板 id")
    s.set_defaults(func=cmd_ingest)

    s = sub.add_parser("run", help="编排主循环(可 --once)")
    s.add_argument("--once", action="store_true", help="单轮推进后退出")
    s.add_argument("--task-file", default=None, help="先 ingest 该镜头卡文件/目录再运行")
    s.add_argument("--template", default=None)
    s.add_argument("--poll", type=float, default=10.0)
    s.add_argument("--verbose", action="store_true")
    s.set_defaults(func=cmd_run)

    sub.add_parser("compose", help="就绪模板组 → 合成成片").set_defaults(func=cmd_compose)

    s = sub.add_parser("report", help="良率统计 JSON")
    s.add_argument("--out", default=None)
    s.set_defaults(func=cmd_report)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "root", None):
        import os

        os.environ["CRADLE_ROOT"] = args.root
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
