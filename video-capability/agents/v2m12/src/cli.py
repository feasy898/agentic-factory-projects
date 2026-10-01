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
            card_eff = card
            if load_settings().get("debug_model") == "ltx" and card["lane"] != "ken_burns":
                # 调试期: 卡面投影为 LTX 调试卡落库, 生成与门禁共用同一口径 (D-025)
                from .gen.ltx import project_card_for_debug

                card_eff = project_card_for_debug(card)
            tid = db.ingest_task(card_eff["shot_id"], card_eff["narrative_slot"], card_eff["lane"],
                                 card_json=card_eff, template=args.template)
            ok += 1
            print(f"ingest {card_eff['shot_id']} (task#{tid}, lane={card_eff['lane']}, "
                  f"res={card_eff['resolution'][0]}x{card_eff['resolution'][1]}, "
                  f"dur={card_eff['duration_sec']}s, template={args.template})")
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


def _default_asr_fn():
    """whisper-small(GPU) ASR 回转 (M3 同款接线, D-036 领域热词); GPU 不可用回退 CPU。"""
    import whisper

    model = None

    def asr_fn(wav_path: str) -> str:
        nonlocal model
        import torch

        if model is None:
            from .config import project_root

            w = project_root() / "models" / "whisper" / "small.pt"
            model = whisper.load_model(str(w) if w.exists() else "small",
                                       device="cuda" if torch.cuda.is_available() else "cpu")
        r = model.transcribe(wav_path, language="zh", temperature=0, initial_prompt=ASR_HOTWORDS)
        return str(r.get("text", "")).strip()

    return asr_fn


# ASR 领域热词(D-036 同机制): 只提供领域词汇表, 不提供讲稿全文; 覆盖 M5 全部模板变体词表
ASR_HOTWORDS = "火锅店美食口播，词汇：老灶火锅、毛肚、锁鲜、到港、虾滑、肥牛、半价、酸梅汤、糍粑、红糖、锅底、牛油、暗号、定位、折。"


def cmd_compose_video(args) -> int:
    """M5: compose-video — 显式「从指定候选集合」按 spec 合成成片(每条落 m5_videos 台账)。"""
    from .config import project_root
    from .orchestrator import compose_from_spec

    log = _setup_logging(getattr(args, "verbose", False))
    db = _open_db(args)
    spec_path = Path(args.spec)
    files = sorted(spec_path.glob("*.json")) if spec_path.is_dir() else [spec_path]
    if not files:
        print(f"未找到 spec: {spec_path}", file=sys.stderr)
        return 1

    asr_fn = None
    if not args.no_asr:
        try:
            asr_fn = _default_asr_fn()
        except Exception as e:  # noqa: BLE001 — whisper 缺失时跳过 CER 并记录(D-011)
            log.warning(f"ASR 不可用, CER 跳过: {e}")

    out = []
    failures = 0
    for f in files:
        spec = json.loads(f.read_text(encoding="utf-8"))
        try:
            r = compose_from_spec(db, spec, settings=load_settings(), out_dir=args.out_dir,
                                  asr_fn=asr_fn)
            g6 = (r.get("g6") or {}).get("detail", {})
            ff = _ffprobe_summary(r["path"])
            print(json.dumps({"video_id": r["video_id"], "path": r["path"],
                              "g6_passed": (r.get("g6") or {}).get("passed"),
                              "cer": g6.get("cer"), "subtitle_exact": g6.get("subtitle_exact"),
                              "total_duration": r.get("total_duration"), "ffprobe": ff},
                             ensure_ascii=False))
            out.append(r["video_id"])
        except Exception as e:  # noqa: BLE001 — 单条失败不拖垮其余成片
            failures += 1
            log.error(f"成片失败 {spec.get('video_id', f.name)}: {e}")
    db.close()
    print(json.dumps({"composed_videos": out, "failures": failures}, ensure_ascii=False))
    return 0 if failures == 0 else 2


def _ffprobe_summary(path: str) -> dict:
    import subprocess

    cp = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format",
                         "-show_streams", str(path)], capture_output=True, text=True, timeout=120)
    if cp.returncode != 0:
        return {"error": cp.stderr[-200:]}
    data = json.loads(cp.stdout)
    fmt = data.get("format", {})
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    return {"duration_s": float(fmt.get("duration", 0.0)), "width": v.get("width"),
            "height": v.get("height"), "codec": v.get("codec_name"),
            "has_audio": bool(a), "size_mb": round(int(fmt.get("size", 0)) / 1048576, 2)}


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


def cmd_g7_fixtures(args) -> int:
    """V2-M1: 夹具库全量复跑 G7(SPECS_V2 §3-6), 每子项分数落 g7_runs 表。"""
    from .gates.g7_object_persistence import run_fixtures

    db = _open_db(args)
    labels = [x for x in (args.labels or "").split(",") if x] or None
    summary = run_fixtures(
        db,
        thresholds_yaml=args.thresholds,
        terms_json=args.terms,
        out_json=args.out,
        frames_root=args.frames_root,
        labels=labels,
        limit=args.limit,
        n_samples=args.n_samples,
    )
    db.close()
    head = {k: summary[k] for k in ("n_fixtures", "n_g7_fail", "by_label")}
    print(json.dumps(head, ensure_ascii=False, indent=2))
    if args.out:
        print(f"分数快照已写入 {args.out}")
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

    s = sub.add_parser("compose-video", help="M5: 按 spec 显式从指定候选集合合成成片")
    s.add_argument("--spec", required=True, help="spec JSON 文件或目录")
    s.add_argument("--out-dir", default=None, help="输出目录(缺省 settings paths.output)")
    s.add_argument("--no-asr", action="store_true", help="跳过 TTS→ASR CER 校验")
    s.add_argument("--verbose", action="store_true")
    s.set_defaults(func=cmd_compose_video)

    s = sub.add_parser("report", help="良率统计 JSON")
    s.add_argument("--out", default=None)
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("g7-fixtures", help="V2-M1: 全部夹具过 G7, 分数落 g7_runs + JSON 快照")
    s.add_argument("--labels", default=None, help="逗号分隔过滤, 如 fail,pass_structural")
    s.add_argument("--thresholds", default=None, help="thresholds_v2.yaml 路径(缺省 config/thresholds_v2.yaml)")
    s.add_argument("--terms", default=None, help="夹具→检测词表映射 JSON(缺省 workdir/fixtures/g7_terms.json)")
    s.add_argument("--out", default=None, help="分数快照 JSON 输出路径")
    s.add_argument("--frames-root", default=None, help="抽帧缓存根目录(缺省 workdir/v2m1_frames)")
    s.add_argument("--n-samples", type=int, default=16)
    s.add_argument("--limit", type=int, default=None)
    s.set_defaults(func=cmd_g7_fixtures)
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
