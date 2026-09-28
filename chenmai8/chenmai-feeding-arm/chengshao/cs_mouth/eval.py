"""cs_mouth eval：口部三维估计验收（开发指令 §5.3；一条命令退出码 0 即通过）。

用法（包根 chengshao/ 下执行）::

    python -m cs_mouth.eval --input assets/face_samples --report reports/mouth_eval.json

样本两种来源（真机样本到位前后同一套指标）：
- ``bundled``  seeds/ 公版真人种子的确定性变体（labels.json 人工核定标签）；
- ``synthetic`` 运行时程序合成（卡通脸→检出/时延负载，无脸场景→拒识路径），
  不入库，--skip-synth 关闭。

指标与通过线（§5.3）：
- 正面样本人脸检出率 ≥95%；
- 张嘴/闭嘴与人工标签一致率 ≥90%（或 AUC ≥0.9）；
- 转头帧 100% 触发转头标志（|head_yaw| > 25°）；
- CPU 单帧（含缩放与推理，不含文件解码）p95 ≤70ms。
附加内部门槛（报告注明）：无脸帧拒识率 ≥95%。

--static-distance：静态距离核查（§5.9 真机阶段）——读 config/static_distance.json
（卷尺实测距离表），输出 |先验-实测| 记录；文件缺失时退出码 2（未执行，非失败）。

--wrist-view（契约 v1.1，腕部双职）：对 assets/face_samples/wrist_view/ 下的
近距腕部视角样本跑 ipd 模式（Z = fx×ipd_m/ipd_px，cam_pose=缺省摆位），
输出检出率与估距误差（labels.json 每帧可带 dist_m 实测距离）；目录缺失时
退出码 2（样本可后补，接口先冻结）。真机阶段补齐样本后此入口进硬门槛。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

from ._schema import HEAD_YAW_TURN_THRESHOLD_RAD, JAW_OPEN_THRESHOLD
from .bootstrap import ensure_bundled
from .estimator import MouthEstimator
from .imgio import imread_u
from .prior import MouthPrior
from .synth import draw_cartoon_face, draw_no_face

PKG_PARENT = Path(__file__).resolve().parents[1]  # chengshao/


# ---- 工具 -------------------------------------------------------------------
def _mean_rank_auc(scores: list[float], labels: list[bool]) -> float | None:
    """平均秩 AUC（Mann-Whitney，并列取平均秩）。样本不足返回 None。"""
    pos = [s for s, y in zip(scores, labels) if y]
    neg = [s for s, y in zip(scores, labels) if not y]
    if not pos or not neg:
        return None
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    rp = sum(ranks[i] for i, y in enumerate(labels) if y)
    return (rp - len(pos) * (len(pos) + 1) / 2.0) / (len(pos) * len(neg))


def _pctl(xs: list[float], q: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    idx = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[idx]


# ---- 主流程 ------------------------------------------------------------------
def run_eval(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cs_mouth.eval", description="口部三维估计验收")
    parser.add_argument("--input", default="assets/face_samples", help="样本根目录")
    parser.add_argument("--report", default="reports/mouth_eval.json", help="报告 JSON 输出路径")
    parser.add_argument("--backend", default="mono", choices=["mono", "depth"])
    parser.add_argument("--max-frames", type=int, default=0, help=">0 时截断 bundled 帧（调试用）")
    parser.add_argument("--skip-synth", action="store_true", help="不附加程序合成帧")
    parser.add_argument("--force-bootstrap", action="store_true", help="强制重建 bundled 变体与 labels")
    parser.add_argument("--static-distance", action="store_true", help="静态距离核查模式（§5.9）")
    parser.add_argument("--wrist-view", action="store_true",
                        help="腕部双职 ipd 模式验收（契约 v1.1；样本缺失时退出码 2）")
    args = parser.parse_args(argv)

    if args.static_distance:
        return _run_static_distance(args)
    if args.wrist_view:
        return _run_wrist_view(args)

    input_dir = Path(args.input)
    report_path = Path(args.report)
    try:
        boot = ensure_bundled(input_dir, force=args.force_bootstrap)
    except FileNotFoundError as exc:
        return _fail(report_path, args, f"样本不可用：{exc}")

    labels_path = input_dir / "labels.json"
    try:
        labels = json.loads(labels_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _fail(report_path, args, f"labels.json 不可读：{exc}")
    frames = [f for f in labels.get("frames", []) if (input_dir / f["file"]).is_file()]
    missing = len(labels.get("frames", [])) - len(frames)
    if args.max_frames > 0:
        frames = frames[: args.max_frames]
    if not frames:
        return _fail(report_path, args, "无可用标注帧")

    # 合成帧（不入库）：卡通脸 12（检出/时延负载） + 无脸 4（拒识）
    synth_frames: list[dict] = []
    if not args.skip_synth:
        for k in range(12):
            synth_frames.append(
                {
                    "file": f"<synth:cartoon{k}>",
                    "face": True,
                    "jaw": None,
                    "turn": None,
                    "img": draw_cartoon_face(mouth_open=k / 11.0, shaded=k % 2 == 0),
                }
            )
        for k in range(4):
            synth_frames.append(
                {
                    "file": f"<synth:noface{k}>",
                    "face": False,
                    "jaw": None,
                    "turn": None,
                    "img": draw_no_face(seed=k),
                }
            )

    est = MouthEstimator(backend=args.backend)
    records: list[dict] = []
    lat_ms: list[float] = []
    for fr in frames + synth_frames:
        img = fr.get("img")
        if img is None:
            img = imread_u(input_dir / fr["file"])
        if img is None:
            records.append({**fr, "ok": False, "pose": None})
            continue
        t0 = time.perf_counter()
        try:
            pose = est.from_bgr(img)
        except FileNotFoundError:
            raise
        except Exception as exc:  # 单帧异常计为未检出，不中断验收
            records.append({**fr, "ok": False, "pose": None, "error": repr(exc)})
            continue
        lat_ms.append((time.perf_counter() - t0) * 1000.0)
        records.append({**fr, "ok": True, "pose": pose})

    # ---- 指标 ----
    labeled = [r for r in records if r["ok"]]
    detect_pool = [r for r in labeled if r.get("face") is True]
    reject_pool = [r for r in labeled if r.get("face") is False]
    jaw_pool = [r for r in labeled if r.get("jaw") in ("open", "closed")]
    turn_pool = [r for r in labeled if r.get("turn") is True]
    frontal_pool = [r for r in labeled if r.get("turn") is False]

    detect_rate = (
        sum(1 for r in detect_pool if r["pose"].valid) / len(detect_pool) if detect_pool else None
    )
    reject_rate = (
        sum(1 for r in reject_pool if not r["pose"].valid) / len(reject_pool) if reject_pool else None
    )
    jaw_scores = [r["pose"].jaw_open for r in jaw_pool]
    jaw_pred_open = [s > JAW_OPEN_THRESHOLD for s in jaw_scores]
    jaw_labels = [r["jaw"] == "open" for r in jaw_pool]
    jaw_acc = (
        sum(p == y for p, y in zip(jaw_pred_open, jaw_labels)) / len(jaw_pool) if jaw_pool else None
    )
    jaw_auc = _mean_rank_auc(jaw_scores, jaw_labels) if jaw_pool else None
    turn_hits = [abs(r["pose"].head_yaw) > HEAD_YAW_TURN_THRESHOLD_RAD for r in turn_pool]
    turn_rate = sum(turn_hits) / len(turn_pool) if turn_pool else None
    frontal_flag = (
        sum(1 for r in frontal_pool if abs(r["pose"].head_yaw) > HEAD_YAW_TURN_THRESHOLD_RAD)
        / len(frontal_pool)
        if frontal_pool
        else None
    )
    lat_p50 = _pctl(lat_ms, 0.50)
    lat_p95 = _pctl(lat_ms, 0.95)

    thresholds = {
        "detect_rate_min": 0.95,
        "face_false_reject_rate_min": 0.95,
        "jaw_accuracy_min": 0.90,
        "jaw_auc_min": 0.90,
        "turn_trigger_rate_min": 1.0,
        "latency_p95_ms_max": 70.0,
    }
    metrics = {
        "detect_rate": detect_rate,
        "detect_frames": len(detect_pool),
        "face_false_reject_rate": reject_rate,
        "reject_frames": len(reject_pool),
        "jaw_accuracy": jaw_acc,
        "jaw_auc": jaw_auc,
        "jaw_frames": len(jaw_pool),
        "jaw_score_closed_max": max(
            (s for s, y in zip(jaw_scores, jaw_labels) if not y), default=None
        ),
        "jaw_score_open_min": min((s for s, y in zip(jaw_scores, jaw_labels) if y), default=None),
        "turn_trigger_rate": turn_rate,
        "turn_frames": len(turn_pool),
        "frontal_turn_false_flag_rate": frontal_flag,
        "latency_ms_p50": lat_p50,
        "latency_ms_p95": lat_p95,
        "latency_frames": len(lat_ms),
        "frames_label_missing": missing,
    }
    checks = {
        "detect": detect_rate is not None and detect_rate >= thresholds["detect_rate_min"],
        "reject": reject_rate is not None and reject_rate >= thresholds["face_false_reject_rate_min"],
        "jaw": (jaw_acc is not None and jaw_acc >= thresholds["jaw_accuracy_min"])
        or (jaw_auc is not None and jaw_auc >= thresholds["jaw_auc_min"]),
        "turn": turn_rate is not None and turn_rate >= thresholds["turn_trigger_rate_min"],
        "latency": lat_p95 == lat_p95 and lat_p95 <= thresholds["latency_p95_ms_max"],
    }
    passed = all(checks.values())

    prior_info = MouthPrior.load()
    report = {
        "module": "cs_mouth",
        "date": date.today().isoformat(),
        "cmd": f"{sys.executable} -m cs_mouth.eval {' '.join(sys.argv[1:])} (cwd={os.getcwd()})",
        "metrics": metrics,
        "thresholds": thresholds,
        "checks": checks,
        "pass": passed,
        "backend": args.backend,
        "sample_mode": "bundled(确定性变体+人工核定标签)" + ("" if args.skip_synth else "+synthetic(程序合成)"),
        "bootstrap": boot,
        "error_band_note": (
            f"mono 先验尺度：距离固定 {prior_info.distance_m}m，横向/纵向误差 ±3–5cm"
            "（由勺停口前 5cm、用户前倾取食、座位定位垫设计吸收）；"
            "转头判定用 |head_yaw|>25°（双向转头均停）"
        ),
        "jaw_signal_note": (
            "jaw_open=几何口径比（上下内唇距/眼距）线性映射；静帧上 blendshape jawOpen "
            "实测不区分张闭嘴（张嘴 0.079–0.094 vs 闭嘴 0.093），故不采用；frown=mouthFrown "
            "左右均值（browDown 微笑误报 0.68，弃用）"
        ),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"cs_mouth.eval: detect={_fmt(metrics['detect_rate'])} reject={_fmt(metrics['face_false_reject_rate'])} "
        f"jaw_acc={_fmt(metrics['jaw_accuracy'])} jaw_auc={_fmt(metrics['jaw_auc'])} "
        f"turn={_fmt(metrics['turn_trigger_rate'])} lat_p95={metrics['latency_ms_p95']:.1f}ms "
        f"-> {'PASS' if passed else 'FAIL'} ({report_path})"
    )
    return 0 if passed else 1


def _fmt(x) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def _fail(report_path: Path, args, reason: str) -> int:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "module": "cs_mouth",
        "date": date.today().isoformat(),
        "cmd": f"{sys.executable} -m cs_mouth.eval {' '.join(sys.argv[1:])} (cwd={os.getcwd()})",
        "metrics": {},
        "thresholds": {},
        "pass": False,
        "error": reason,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"cs_mouth.eval: FAIL — {reason}", file=sys.stderr)
    return 1


def _run_wrist_view(args) -> int:
    """腕部双职 ipd 模式验收（契约 v1.1）：近距样本检出率 + IPD 估距误差。

    样本目录 ``assets/face_samples/wrist_view/``（labels.json 同主集格式，
    每帧可带 ``dist_m`` 实测距离用于估距误差）。目录/标签缺失时退出码 2
    （样本可后补，接口先冻结；真机阶段补齐后进硬门槛）。
    """
    input_dir = Path(args.input) / "wrist_view"
    if not input_dir.is_dir() or not (input_dir / "labels.json").is_file():
        msg = (
            f"未找到腕部视角样本 {input_dir}（含 labels.json）。"
            "样本可后补：真机阶段用腕部相机在 20/30/40/50cm 各拍近距人脸"
            "（含俯仰角变化与亮暗切换），接口已按契约 v1.1 冻结。"
        )
        print(f"cs_mouth.eval --wrist-view: {msg}", file=sys.stderr)
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(
            json.dumps({
                "module": "cs_mouth",
                "mode": "wrist_view_ipd",
                "date": date.today().isoformat(),
                "cmd": f"{sys.executable} -m cs_mouth.eval --wrist-view (cwd={os.getcwd()})",
                "metrics": {},
                "thresholds": {},
                "pass": False,
                "not_executed": True,
                "error": msg,
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return 2

    try:
        labels = json.loads((input_dir / "labels.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _fail(Path(args.report), args, f"wrist_view/labels.json 不可读：{exc}")
    frames = [f for f in labels.get("frames", []) if (input_dir / f["file"]).is_file()]
    if not frames:
        return _fail(Path(args.report), args, "wrist_view 无可用标注帧")

    # ipd 模式：cam_pose 用缺省摆位（真机阶段换 FK×腕部手眼实标定值）
    prior = MouthPrior.load().with_updates(mode="ipd")
    est = MouthEstimator(backend="mono", prior=prior)
    T_base_flange = np.eye(4)  # 离线样本无 FK；单位阵 = 相机系即基座系口径
    T_flange_cam = prior.matrix_base_cam()
    cam_pose = (T_base_flange, T_flange_cam)

    detect_hits = 0
    errs: list[float] = []
    n_dist = 0
    for fr in frames:
        img = imread_u(input_dir / fr["file"])
        if img is None:
            continue
        try:
            pose = est.from_bgr(img, cam_pose=cam_pose)
        except Exception:  # noqa: BLE001 —— 单帧异常计为未检出
            continue
        if pose.valid:
            detect_hits += 1
            if isinstance(fr.get("dist_m"), (int, float)):
                # 相机系 z（ipd 估距）= 基座系口径下的深度分量（缺省摆位下逐点对应）
                errs.append(abs(pose.z - float(fr["dist_m"])))
                n_dist += 1

    n_total = len(frames)
    detect_rate = detect_hits / n_total if n_total else None
    err_max = max(errs) if errs else None
    err_mean = float(np.mean(errs)) if errs else None
    thresholds = {
        "detect_rate_min": 0.95,
        "ipd_err_max_m_max": 0.04,
        "dist_labeled_frames_min": 8,  # 估距误差判据至少要有的带距离帧数
    }
    checks = {
        "detect": detect_rate is not None and detect_rate >= thresholds["detect_rate_min"],
        "ipd_error": (
            n_dist >= thresholds["dist_labeled_frames_min"]
            and err_max is not None
            and err_max <= thresholds["ipd_err_max_m_max"]
        ),
    }
    passed = all(checks.values())
    report = {
        "module": "cs_mouth",
        "mode": "wrist_view_ipd",
        "date": date.today().isoformat(),
        "cmd": f"{sys.executable} -m cs_mouth.eval --wrist-view (cwd={os.getcwd()})",
        "metrics": {
            "frames": n_total,
            "detect_hits": detect_hits,
            "detect_rate": detect_rate,
            "dist_labeled_frames": n_dist,
            "ipd_err_max_m": err_max,
            "ipd_err_mean_m": err_mean,
            "prior_mode": prior.mode,
            "ipd_m": prior.ipd_m,
        },
        "thresholds": thresholds,
        "checks": checks,
        "pass": passed,
        "note": (
            "腕部双职（契约 v1.1）：ipd 瞳距先验估距，预期 ±2-4cm；离线样本用缺省摆位"
            "外参，真机阶段切换 FK×腕部手眼实标定后以 --live 复测"
        ),
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"cs_mouth.eval(wrist-view): detect={_fmt(detect_rate)} "
        f"ipd_err_max={_fmt(err_max)}m (n_dist={n_dist}) -> {'PASS' if passed else 'FAIL'} ({args.report})"
    )
    return 0 if passed else 1


def _run_static_distance(args) -> int:
    """静态距离核查（§5.9，真机阶段）：卷尺实测 vs 先验，误差记录性指标。"""
    cfg = Path("config/static_distance.json")
    if not cfg.is_file():
        print(
            "cs_mouth.eval --static-distance: 未找到 config/static_distance.json "
            "（真机阶段用卷尺 0.35/0.45/0.55m 实测后填写），本模式未执行。",
            file=sys.stderr,
        )
        return 2
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        measured = [float(x) for x in data["measurements_m"]]
    except (OSError, ValueError, KeyError) as exc:
        return _fail(Path(args.report), args, f"static_distance.json 解析失败：{exc}")
    prior = MouthPrior.load()
    errs = [abs(prior.distance_m - m) for m in measured]
    report = {
        "module": "cs_mouth",
        "date": date.today().isoformat(),
        "cmd": f"{sys.executable} -m cs_mouth.eval --static-distance (cwd={os.getcwd()})",
        "metrics": {
            "prior_distance_m": prior.distance_m,
            "measured_m": measured,
            "abs_errors_m": errs,
            "max_abs_error_m": max(errs) if errs else None,
        },
        "thresholds": {"max_abs_error_m_note": 0.05, "blocking": False},
        "pass": True,  # 记录性核查：超线只修 mouth_prior.json，不阻塞（§5.9）
        "note": "超 5cm 只修 config/mouth_prior.json 的 distance_m，不阻塞",
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"cs_mouth.eval: static-distance 记录完成 -> {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_eval())
