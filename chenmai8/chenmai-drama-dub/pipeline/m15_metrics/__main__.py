"""M15 指标 CLI（规划 §4 M15 冻结形态）::

    python -m pipeline.m15_metrics --ep ep01 --lang en
    python -m pipeline.m15_metrics --ep ep01 --lang en [--jobs-dir <dir>]
        [--asr-url http://127.0.0.1:9001] [--allow-degraded]

流程：读 C2/C4/C5/08_mix/12_out → 六指标依序运行（每项独立计时/独立容错，
单项失败不出数如实记 unavailable+reason，不中断其余指标）→
``12_out/metrics.json``（原子写，工作纸非冻结契约）。

退出码：0 = 六项全部出数（或 --allow-degraded 下容忍缺项）；1 = 有缺项且
未加 --allow-degraded，或输入缺失；2 = 用法错误。

数值本身不做阈值门禁（"数值如实，无基准则记 baseline v0"）：threshold
字段随每项给出规划通过线或 null（基线 v0），判定归消费方。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pipeline.config import load_pipeline_config
from pipeline.m15_metrics import METRIC_KEYS, _common
from pipeline.m15_metrics import cost, dur_align, lip_score, speaker_sim, wer
from pipeline.m15_metrics import emotion_sim
from pipeline.m15_metrics._common import CallLedger, write_json_atomic
from pipeline.scaffold import ep_dir

#: metrics.json schema 版本（工作纸自描述；字段只增不改名）
SCHEMA_VERSION = 1


def run_metrics(
    ep: str,
    lang: str,
    *,
    jobs_dir: str | Path | None = None,
    asr_url: Optional[str] = None,
    cfg: Optional[dict[str, Any]] = None,
) -> tuple[dict[str, Any], int]:
    """六指标全量运行 → (metrics.json 载荷, 退出码)。写盘由调用方决定。"""
    cfg = cfg if cfg is not None else load_pipeline_config()
    jobs_root = Path(jobs_dir) if jobs_dir else Path(cfg["paths"]["jobs_dir"])
    ws = ep_dir(ep, jobs_root)
    if not (ws / "04_dial" / "utterances.jsonl").is_file():
        raise FileNotFoundError(
            f"C2 不存在: {ws / '04_dial' / 'utterances.jsonl'}（M15 消费 M2/M4+ 产物，"
            "至少先产出 04_dial/utterances.jsonl）")

    ledger = CallLedger()

    def _run(name: str, fn: Any) -> dict[str, Any]:
        with ledger.stage(name):
            try:
                return fn()
            except Exception as exc:  # 单指标容错：如实记 unavailable，不拖垮其余
                return _common.metric_result(
                    getattr(fn, "key", name), name, None, status="unavailable",
                    threshold=None, method="", reason=f"执行异常: {exc!r}")

    results: dict[str, dict[str, Any]] = {}
    results["speaker_similarity"] = _run(
        "speaker_similarity", lambda: speaker_sim.compute(ws, lang, ledger))
    results["emotion_similarity"] = _run(
        "emotion_similarity", lambda: emotion_sim.compute(ws, lang, ledger, url=asr_url))
    results["listen_wer"] = _run(
        "listen_wer", lambda: wer.compute(ws, lang, ledger, url=asr_url))
    results["duration_alignment_rate"] = _run(
        "duration_alignment_rate", lambda: dur_align.compute(ws, lang, ledger, cfg=cfg))
    results["lip_score"] = _run(
        "lip_score", lambda: lip_score.compute(ws, lang, ep, ledger))

    output_duration_s = _output_duration(ws, ep, lang)
    results["cost_per_minute"] = _run(
        "cost_per_minute",
        lambda: cost.compute(ws, lang, ep, ledger, output_duration_s=output_duration_s))

    ordered = [results[k] for k in METRIC_KEYS]
    n_ok = sum(1 for r in ordered if r["status"] == "ok")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "ep": ep,
        "lang": lang,
        "generated_by": "m15_metrics",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "baseline": "v0",   # 任务 T21：无历史基准，首测值即基线 v0
        "output_duration_s": output_duration_s,
        "n_metrics_ok": n_ok,
        "n_metrics_total": len(METRIC_KEYS),
        "all_measured": bool(n_ok == len(METRIC_KEYS)),
        "metrics": {r["key"]: r for r in ordered},
        "wall_clock_s": {"total": ledger.wall_total,
                         "stages": dict(sorted(ledger.stages.items()))},
        "calls": ledger.calls,
        "notes": (
            "metrics.json 为 M15 工作纸（非冻结契约）。数值如实记录、不做阈值门禁："
            "threshold=null 的指标（lip_score/cost_per_minute）为基线 v0 首测口径；"
            "status=unavailable 的指标带 reason（服务不可达/输入缺失等），不伪造数值。"
            "记账来源：本次会话账本；M14 metrics.db 未部署，全链路成本口径待其落库。"
        ),
    }
    exit_code = 0 if n_ok == len(METRIC_KEYS) else 1
    return payload, exit_code


def _output_duration(ws: Path, ep: str, lang: str) -> Optional[float]:
    p = ws / "12_out" / f"{ep}.{lang}.mp4"
    if p.is_file():
        try:
            from pipeline.m1_ingest import ffprobe_json

            dur = float(ffprobe_json(p).get("format", {}).get("duration") or 0.0)
            if dur > 0:
                return round(dur, 3)
        except Exception:
            pass
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m pipeline.m15_metrics",
        description="M15 指标体系：六项指标 → 12_out/metrics.json（数值如实，基线 v0）",
    )
    ap.add_argument("--ep", required=True, help="集 ID，如 ep01")
    ap.add_argument("--lang", default="en", choices=("en", "es", "ar"),
                    help="目标语种（冻结槽位）")
    ap.add_argument("--jobs-dir", default=None,
                    help="jobs 根目录（默认取 configs/pipeline.yaml paths.jobs_dir）")
    ap.add_argument("--asr-url", default=None,
                    help=":9001 服务地址（默认 M4_ASR_URL 或 http://127.0.0.1:9001）")
    ap.add_argument("--allow-degraded", action="store_true",
                    help="容忍缺项（unavailable 指标照常落盘）并退出 0（离线开发用）")
    args = ap.parse_args(argv)

    cfg = load_pipeline_config()
    jobs_root = Path(args.jobs_dir) if args.jobs_dir else Path(cfg["paths"]["jobs_dir"])
    try:
        payload, code = run_metrics(
            args.ep, args.lang, jobs_dir=jobs_root, asr_url=args.asr_url, cfg=cfg)
    except FileNotFoundError as exc:
        print(f"FAIL m15_metrics: {exc}")
        return 1

    out_path = write_json_atomic(
        ep_dir(args.ep, jobs_root) / "12_out" / "metrics.json", payload)
    for r in payload["metrics"].values():
        val = "—" if r["value"] is None else f"{r['value']:.4f}"
        thr = "baseline-v0" if r["threshold"] is None else f"{r['threshold']}"
        line = (f"  [{'OK' if r['status'] == 'ok' else 'UNAVAIL'}] "
                f"{r['key']:<26} {val:>10}  (线 {thr})")
        print(line)
        if r["status"] != "ok":
            print(f"        reason: {r['reason']}")
    print(f"{'OK' if code == 0 else 'FAIL'} m15_metrics ep={args.ep} lang={args.lang} "
          f"metrics {payload['n_metrics_ok']}/{payload['n_metrics_total']} 出数 "
          f"wall={payload['wall_clock_s']['total']}s → {out_path}")
    if code != 0 and args.allow_degraded:
        print("  --allow-degraded: 缺项已如实落盘，退出 0")
        return 0
    return code


if __name__ == "__main__":
    sys.exit(main())
