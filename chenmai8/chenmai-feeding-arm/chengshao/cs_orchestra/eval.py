"""cs_orchestra eval：行为树 mock 验收（开发指令 §5.6 + v3.1 相机角色断言）。

用法（包根 chengshao/ 下，仓库根亦可）::

    python -m cs_orchestra.eval --mock --episodes 30 --report reports/orchestra_eval.json
    python -m chengshao.cs_orchestra.eval --mock 30        # 等价（位置参数回合数）

通过线（§5.6 + 任务 T8 验收口径，全部满足才 exit 0）：
  1) 每回合为完整注餐闭环（15 口额定，第 15 口"吃饱了"收尾）；
  2) 注入"第 7 口转头 / 第 12 口 estop / 第 15 口'吃饱了'"，行为响应 100%
     符合模块 docstring 状态转移表（含第 3 口勺空重舀、第 9 口闭嘴等待）；
  3) v3.1：进入送达的口 camera_role 恰好切换 2 次（进送达 1 次
     delivery_entry、撤回/中止 1 次），且 scene->wrist_mouth 后先等曝光
     稳定（>=0.5s）再采信口部帧——30/30 回合全部达标；
  4) 单口仿真时延中位数 <= 20s；
  5) 0 安全违规、0 意外指令拒绝、0 意外失败；
  6) trace（reports/orchestra_trace.jsonl）含全部切换事件供审计。

报告 JSON 遵循开发指令 §10.2：{module, date, cmd, metrics, thresholds, pass}。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

import numpy as np

try:  # 仓库根运行与包根运行双形态
    from chengshao.cs_orchestra.core import (
        PKG_ROOT,
        OrchestraParams,
    )
    from chengshao.cs_orchestra.mock import (
        SPEC_MEAL_BITES,
        SPEC_MEAL_EXPECTED_OUTCOMES,
        SPEC_MEAL_SCRIPT,
        make_mock_episode,
    )
except ImportError:  # pragma: no cover - 包根直跑形态
    from cs_orchestra.core import (  # type: ignore[no-redef]
        PKG_ROOT,
        OrchestraParams,
    )
    from cs_orchestra.mock import (  # type: ignore[no-redef]
        SPEC_MEAL_BITES,
        SPEC_MEAL_EXPECTED_OUTCOMES,
        SPEC_MEAL_SCRIPT,
        make_mock_episode,
    )

DEFAULT_REPORT = PKG_ROOT / "reports" / "orchestra_eval.json"
DEFAULT_TRACE = PKG_ROOT / "reports" / "orchestra_trace.jsonl"

THRESHOLDS: dict = {
    "episodes_min": 30,
    "episodes_pass_required": 30,
    "bites_per_episode": SPEC_MEAL_BITES,
    "camera_switches_per_delivered_bite": 2,
    "exposure_settle_min_s": 0.5,
    "median_bite_sim_s_max": 20.0,
    "zone_violation_latches_max": 0,
    "unexpected_failures_max": 0,
    "envelope_rejections_max": 0,
    "estop_bite_outcome": "aborted",
    "done_bite_outcome": "rejected",
}

TICK_EPS_S = 0.05  # 曝光稳定窗断言的 tick 粒度余量（s）


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="python -m cs_orchestra.eval",
        description="cs_orchestra eval: 行为树 mock 验收（30 回合 + camera_role 时序断言）")
    ap.add_argument("episodes_pos", nargs="?", type=int, default=None,
                    help="回合数（位置参数；等价 --episodes）")
    ap.add_argument("--mock", action="store_true", default=False,
                    help="mock 模式开关（当前实现仅 mock 模式，全 Mock 零硬件）")
    ap.add_argument("--episodes", type=int, default=None, help="回合数（默认 30）")
    ap.add_argument("--report", default=str(DEFAULT_REPORT), help="报告 JSON 输出路径")
    ap.add_argument("--trace", default=str(DEFAULT_TRACE), help="trace JSONL 输出路径")
    ap.add_argument("--seed", type=int, default=20260929, help="随机种子（回合噪声）")
    return ap.parse_args(argv)


# ---- 单回合断言 ----------------------------------------------------------------


def verify_episode(ns, summary: dict, expected_outcomes: dict[int, str]) -> tuple[dict, dict]:
    """对一回合做全部断言；返回 (checks, extra_metrics)。checks 全 True 才算过。"""
    ctx = ns.ctx
    checks: dict[str, bool] = {}
    m: dict = {}

    checks["no_timeout"] = not summary["timeout"]
    checks["no_unexpected"] = len(summary["unexpected_failures"]) == 0

    # ---- 口数与结局表 ----------------------------------------------------------
    bites = ctx.bites_done
    checks["bite_count"] = len(bites) == len(expected_outcomes)
    outcomes_ok = all(
        i <= len(bites) and str(rec.outcome) == expected_outcomes[i]
        for i, rec in enumerate(bites, start=1))
    checks["outcomes_match_table"] = outcomes_ok
    checks["bite_ids_sequential"] = [r.bite_id for r in bites] == list(range(len(bites)))
    m["outcomes"] = dict(Counter(str(r.outcome) for r in bites))

    # ---- 会话与记录池 ----------------------------------------------------------
    session = ctx.session
    checks["session_ended"] = bool(session is not None and session.ended_ns is not None)
    sink_bites = list(ns.deps.sink.bites)
    checks["sink_bites_all"] = len(sink_bites) == len(bites)

    # ---- camera_role 台账（v3.1 核心断言） --------------------------------------
    # 本脚本所有口都进入送达（第 3 口首轮舀空、闭环重舀后命中；重舀耗尽 0 切换
    # 的路径由 tests/test_orchestra.py 单测覆盖）。
    ledger_ok = True
    switches_per_bite: dict[int, int] = {}
    for i in range(1, len(expected_outcomes) + 1):
        rep = ctx.ledger.per_bite_report(i, delivered=True)
        switches_per_bite[i] = rep["switches"]
        ledger_ok = ledger_ok and rep["ok"]
    checks["camera_switch_2_per_bite"] = ledger_ok
    m["switches_total"] = len(ctx.ledger.switches)
    m["switches_per_bite"] = switches_per_bite

    # ---- 曝光稳定窗时序（scene->wrist 后 >=0.5s 才有有效口部帧） ----------------
    settle_ok = True
    settle_min = None
    for sw in ctx.ledger.switches:
        if sw["reason"] != "delivery_entry":
            continue
        bite_idx = sw["bite"]
        valid_ts = [s[0] for s in ctx.mouth_samples
                    if s[1] == "wrist_mouth" and s[2]
                    and bite_idx is not None]
        # 仅取该口切换之后的采样（采样时间戳 > 切换时间戳）
        after = [t for t in valid_ts if t >= sw["ts_ns"]]
        if not after:
            settle_ok = False
            continue
        gap = (min(after) - sw["ts_ns"]) / 1e9
        settle_min = gap if settle_min is None else min(settle_min, gap)
        if gap < THRESHOLDS["exposure_settle_min_s"] - TICK_EPS_S:
            settle_ok = False
    checks["exposure_settle_before_first_frame"] = settle_ok
    m["settle_gap_min_s"] = None if settle_min is None else round(settle_min, 3)

    # ---- cam_pose=FK×手眼 审计：腕部通道收到的 T_base_flange 与黑板同源，
    # 且相机光心（FK×名义手眼合成）在腕部角色下被带到用户面部近旁 -------------
    cam_ok = True
    cam_dists = []
    face = np.asarray(ctx.validator.config.face_center, dtype=float)
    for t in ns.deps.mouth.cam_positions[-64:]:
        cam_dists.append(float(np.linalg.norm(np.asarray(t) - face)))
    if cam_dists:
        # 名义停点距面心 0.17m，相机光心略偏仍应近距（<0.45m）
        cam_ok = min(cam_dists) < 0.45
    checks["wrist_cam_fk_reaches_face"] = cam_ok
    recv = ns.deps.mouth.received_t_flange
    samples_t = [s[3] for s in ctx.mouth_samples]
    # 两侧审计列表各有裁剪阈值，比较对齐的尾部（逐 tick 同源成对追加）
    n = min(len(recv), len(samples_t))
    checks["t_flange_records_present"] = (
        n > 0 and all(np.allclose(recv[-n + i], samples_t[-n + i], atol=0.0)
                      for i in range(n)))

    # ---- 播报与意图 -------------------------------------------------------------
    ann = ctx.announce_counts
    checks["announces"] = (
        ann.get("estop", 0) == 1 and ann.get("turn", 0) == 1
        and ann.get("done", 0) == 1 and ann.get("pause", 0) == 0
        and ann.get("frown", 0) == 0 and ann.get("zone", 0) == 0)
    m["announces"] = dict(ann)
    checks["pending_intents_drained"] = len(ctx.pending_intents) == 0

    # ---- 安全与执行 -------------------------------------------------------------
    env_stats = ns.env.stats
    checks["no_zone_latch"] = env_stats.get("zone_latches", 0) == \
        THRESHOLDS["zone_violation_latches_max"]
    checks["no_envelope_rejection"] = (
        env_stats.get("rejected", 0) <= THRESHOLDS["envelope_rejections_max"])
    m["env_written"] = env_stats.get("written", 0)
    m["env_rejected"] = env_stats.get("rejected", 0)

    # ---- 单口时延（仿真秒，中位数阈值） -----------------------------------------
    durations = [(r.ts_end_ns - r.ts_start_ns) / 1e9 for r in bites]
    med = float(np.median(durations)) if durations else float("inf")
    checks["median_bite_sim_s"] = med <= THRESHOLDS["median_bite_sim_s_max"]
    m["median_bite_sim_s"] = round(med, 2)
    m["max_bite_sim_s"] = round(max(durations), 2) if durations else None

    # ---- 黑板冻结键 --------------------------------------------------------------
    have = {k for k in ("mouth", "arm_state", "safety", "spoon", "intent",
                        "session", "bowl_sel", "camera_role")
            if ctx.bb.exists(k)}
    checks["blackboard_frozen_keys"] = len(have) == 8
    checks["camera_role_back_to_scene"] = str(ctx.camera_role) == "scene"

    # ---- trace -------------------------------------------------------------------
    kinds = {ev["kind"] for ev in ctx.trace.events}
    checks["trace_role_switch_events"] = ctx.ledger.switches and all(
        any(ev["kind"] == "role_switch" and ev["ts_ns"] == sw["ts_ns"]
            for ev in ctx.trace.events) for sw in ctx.ledger.switches)
    _ = kinds

    # 汇总
    m["bites"] = len(bites)
    return checks, m


# ---- 主流程 --------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    episodes = args.episodes_pos or args.episodes or THRESHOLDS["episodes_min"]
    episodes = max(1, int(episodes))
    report_path = Path(args.report)
    trace_path = Path(args.trace)

    params = OrchestraParams.load()
    t_all = time.perf_counter()

    # trace 文件截断（本轮全量重写）
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text("", encoding="utf-8")

    model = None  # 各回合共用（惰性装载一次）
    validator = None
    episode_rows: list[dict] = []
    total_outcomes: Counter = Counter()
    all_durations: list[float] = []
    hard_fail: list[str] = []

    for ep in range(1, episodes + 1):
        ns = make_mock_episode(episode=ep, script=SPEC_MEAL_SCRIPT,
                               bites=SPEC_MEAL_BITES, params=params,
                               model=model, validator=validator,
                               seed=args.seed, trace_path=trace_path)
        model, validator = ns.model, ns.validator
        t0 = time.perf_counter()
        summary = ns.runner.run(ns.driver)
        wall_s = time.perf_counter() - t0

        checks, extra = verify_episode(ns, summary, SPEC_MEAL_EXPECTED_OUTCOMES)
        ep_pass = all(checks.values())
        if not ep_pass:
            hard_fail.append(
                f"ep{ep}: " + ",".join(k for k, v in checks.items() if not v))
        total_outcomes.update(extra["outcomes"])
        for r in ns.ctx.bites_done:
            all_durations.append((r.ts_end_ns - r.ts_start_ns) / 1e9)
        episode_rows.append({
            "episode": ep,
            "pass": bool(ep_pass),
            "bites": summary["bites"],
            "sim_s": summary["sim_s"],
            "wall_s": round(wall_s, 2),
            "switches": extra["switches_total"],
            "median_bite_sim_s": extra["median_bite_sim_s"],
            "failed_checks": [k for k, v in checks.items() if not v],
        })

    wall_all = time.perf_counter() - t_all
    median_all = float(np.median(all_durations)) if all_durations else None
    passed = not hard_fail

    metrics = {
        "episodes": episodes,
        "episodes_passed": sum(1 for r in episode_rows if r["pass"]),
        "bites_total": sum(r["bites"] for r in episode_rows),
        "outcomes_total": dict(total_outcomes),
        "median_bite_sim_s": None if median_all is None else round(median_all, 2),
        "max_bite_sim_s": round(max(all_durations), 2) if all_durations else None,
        "sim_s_total": round(sum(r["sim_s"] for r in episode_rows), 1),
        "wall_s_total": round(wall_all, 1),
        "switches_total": sum(r["switches"] for r in episode_rows),
        "episodes": _rows_compact(episode_rows),
    }
    report = {
        "module": "cs_orchestra",
        "date": date.today().isoformat(),
        "cmd": (f"python -m chengshao.cs_orchestra.eval --mock {episodes} "
                f"--report {report_path}"),
        "mode": "mock（全 Mock 零硬件；MockArm+SafetyEnvelope+脚本化用户）",
        "script": {"bites_per_episode": SPEC_MEAL_BITES,
                   "injections": {str(k): v for k, v in SPEC_MEAL_SCRIPT.items()}},
        "metrics": metrics,
        "thresholds": THRESHOLDS,
        "pass": bool(passed),
        "failures": hard_fail,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"cs_orchestra.eval: episodes={episodes} "
          f"passed={metrics['episodes_passed']}/{episodes} "
          f"bites={metrics['bites_total']} "
          f"median_bite_sim_s={metrics['median_bite_sim_s']} "
          f"switches={metrics['switches_total']} wall_s={metrics['wall_s_total']}")
    print(f"report -> {report_path}")
    print(f"trace  -> {trace_path}")
    if hard_fail:
        for line in hard_fail[:10]:
            print("FAIL", line, file=sys.stderr)
        return 1
    return 0


def _rows_compact(rows: list[dict]) -> list[dict]:
    keep = ("episode", "pass", "bites", "sim_s", "wall_s", "switches",
            "median_bite_sim_s", "failed_checks")
    return [{k: r[k] for k in keep} for r in rows]


if __name__ == "__main__":
    raise SystemExit(main())
