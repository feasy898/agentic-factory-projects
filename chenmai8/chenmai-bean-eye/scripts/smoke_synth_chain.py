"""W12 全链冒烟：合成盘 → 标定 → 配对 → 严重度 → 计量 → 定级 → 护照。

运行（仓库根）::

    python scripts/smoke_synth_chain.py --trays 50

任务书自验收线：合成盘 N 张（默认 50）逐盘跑通「标定→配对→严重度→
计量→定级→护照」，全部断言通过 → 打印 SMOKE PASS 摘要并 exit 0。

链路口径（任务书点名六个阶段；分割/分类在 M4/M5 落地前由合成真值直出，
与 M4 OracleSeg 的语义一致——逐粒掩码/类别取自 compose manifest）：

1. compose_tray 合成整盘对（四角码布局与打印板/标定同源 configs/tray.yaml）；
2. **标定**：beaneye.calibration.calibrate_pair 真实检测四角 ArUco →
   CalibResult；warp_to_tray 得正射 mm 网格；
3. 逐粒观测：真值多边形 → 契约 BeanMask(oracle, conf=1.0) + 类别真值 →
   BeanObservation；color_lab 在 warp 网格上按真值掩码实测（lab8 标度）；
4. **配对**：beaneye.pairing.pair_observations（匈牙利 + 门限）；
5. **严重度**：beaneye.severity 与配对产物逐粒交叉核对，且与合成真值
   （上下同类 → final_defect=该类）核对；
6. **计量**：beaneye.metrology.measure（筛目/色差/估重）；
7. **定级**：beaneye.standards 引擎 evaluate；oracle 自洽断言：
   defect_counts/主次分计与真值直方完全一致；
8. **护照**：三语 HTML + 二维码；QR 解码回读 report_id/sha256 与
   BatchResult 一致（证据 crop 未落盘 → 护照走确定性占位图路径）。

第 1 盘额外 write_batch 落盘（双面图 + labels JSON + manifest.yaml）作产物
抽样；其余盘内存中跑完即弃。全程离线（不依赖网络/权重）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from beaneye.acquisition.base import write_json  # noqa: E402
from beaneye.agent import make_agent  # noqa: E402
from beaneye.calibration import calibrate_pair, warp_to_tray  # noqa: E402
from beaneye.metrology import measure  # noqa: E402
from beaneye.pairing import pair_observations  # noqa: E402
from beaneye.report import build_passport, canonical_sha256, parse_qr_payload  # noqa: E402
from beaneye.schemas import (  # noqa: E402
    BatchResult,
    BeanMask,
    BeanObservation,
    PairedBean,
)
from beaneye.severity import SeverityAdjudicator, default_severity_order  # noqa: E402
from beaneye.standards import load_engine  # noqa: E402
from beaneye.synth import compose_tray, write_batch  # noqa: E402
from beaneye.synth.config import ComposeConfig  # noqa: E402
from beaneye.taxonomy import load_taxonomy  # noqa: E402


def build_smoke_config(args: argparse.Namespace) -> ComposeConfig:
    return ComposeConfig(
        version=1,
        width_px=args.canvas,
        height_px=args.canvas,
        margin_mm=20.0,
        n_beans_min=args.min_beans,
        n_beans_max=args.max_beans,
        defect_rate=args.defect_rate,
        class_weights={
            "black": 3.0, "mold": 2.0, "sour": 2.0, "insect": 2.0, "dried": 2.0,
            "broken": 3.0, "brocade": 2.0, "shell": 1.0, "elephant": 1.0,
            "peaberry": 1.0, "immature": 1.0, "faded": 1.0,
        },
        contact_min=2,
        contact_max=6,
        overlap_depth=0.8,
        free_factor=1.06,
        scale_jitter=0.10,
        angle_jitter=180.0,
        pair_jitter_mm=0.6,
        mirror_bottom=True,
        per_class=20,
        library_seed=20260929,
    )


def lab8_within_mask(
    lab_grid: np.ndarray, poly_mm, tray_mm: float, grid_px: int, buf
) -> tuple[float, float, float]:
    """正射网格上按真值掩码实测 lab8 均值（与 M13 管线 _masked_lab8 同口径）。

    ``lab_grid`` 为整面一次转换好的 Lab 网格（避免逐豆全图 cvtColor）；
    统计只扫多边形外接框邻域（避免逐豆 2048² 全图布尔索引）。
    """
    pts = np.round(np.asarray(poly_mm, dtype=np.float64) * (grid_px / tray_mm)).astype(np.int32)
    x0, y0 = pts.min(axis=0)
    x1, y1 = pts.max(axis=0)
    px0, py0 = max(0, int(x0)), max(0, int(y0))
    px1, py1 = min(grid_px, int(x1) + 1), min(grid_px, int(y1) + 1)
    sub = lab_grid[py0:py1, px0:px1]
    pts = pts - np.asarray([px0, py0])
    patch = np.zeros((py1 - py0, px1 - px0), dtype=np.uint8)
    cv2.fillPoly(patch, [pts], 1)
    n = int(patch.sum())
    if n == 0:
        return (0.0, 128.0, 128.0)
    vals = sub[patch > 0].astype(np.float64).mean(axis=0)
    return (float(vals[0]), float(vals[1]), float(vals[2]))


def run_tray(idx: int, seed: int, cfg: ComposeConfig, library, args, tax, engine, agent, std_path: str, adj: SeverityAdjudicator) -> dict:
    t = {"compose": 0.0, "calibration": 0.0, "observe": 0.0, "pairing": 0.0,
         "severity": 0.0, "metrology": 0.0, "grading": 0.0, "agent": 0.0, "passport": 0.0}

    t0 = time.perf_counter()
    tray = compose_tray(seed=seed, config=cfg, library=library)
    t["compose"] = time.perf_counter() - t0

    # ---- 标定（真实 ArUco 检测 + 单应求解） ------------------------------
    t0 = time.perf_counter()
    calib = calibrate_pair(tray.top_bgr, tray.bottom_bgr)
    t["calibration"] = time.perf_counter() - t0
    ppm_err = abs(calib.px_per_mm - tray.px_per_mm) / tray.px_per_mm
    assert ppm_err <= 0.02, f"盘 {idx}: px_per_mm 相对误差 {ppm_err:.3%} > 2%"
    assert calib.reproj_err_px <= 1.5, f"盘 {idx}: 重投影误差 {calib.reproj_err_px:.2f}px"

    grid_px = tray.rle_grid_px
    warped = {
        "top": warp_to_tray(tray.top_bgr, np.asarray(calib.H_top), None),
        "bottom": warp_to_tray(tray.bottom_bgr, np.asarray(calib.H_bottom), None),
    }
    lab_grids = {s: cv2.cvtColor(warped[s], cv2.COLOR_BGR2Lab) for s in warped}

    # ---- 逐粒观测（真值直出 + 网格实测 LAB） -----------------------------
    t0 = time.perf_counter()
    buf = np.zeros((grid_px, grid_px), dtype=np.uint8)
    mm_per_px = tray.tray_mm / grid_px
    observations: dict[str, list[BeanObservation]] = {"top": [], "bottom": []}
    for i, bean in enumerate(tray.beans):
        for side in ("top", "bottom"):
            poly = bean.poly_mm_top if side == "top" else bean.poly_mm_bottom
            poly_r = [[round(float(x), 3) for x in p] for p in poly]
            x0, y0 = poly_r[0][0], poly_r[0][1]
            xs = [p[0] for p in poly_r]
            ys = [p[1] for p in poly_r]
            bbox = (min(xs), min(ys), max(xs), max(ys))
            area = bean.area_mm2 if side == "top" else _shoelace(poly_r)
            centroid = bean.centroid_mm if side == "top" else _centroid(poly_r)
            mask = BeanMask(
                mask_id=f"{side}_{i:04d}",
                side=side,
                polygon=poly_r,
                bbox_mm=bbox,
                area_mm2=area,
                centroid_mm=centroid,
                source="oracle",
                conf=1.0,
            )
            lab = lab8_within_mask(lab_grids[side], poly_r, tray.tray_mm, grid_px, buf)
            observations[side].append(
                BeanObservation(
                    obs_id=mask.mask_id,
                    side=side,
                    defect=bean.cls,
                    defect_conf=1.0,
                    severity_rank=tax.severity_rank(bean.cls),
                    crop_path=f"crops/{tray.scan_id}/{mask.mask_id}.png",
                    mask=mask,
                    color_lab=lab,
                    eq_diameter_mm=2.0 * (area / np.pi) ** 0.5,
                )
            )
    t["observe"] = time.perf_counter() - t0

    # ---- 配对（匈牙利 + 门限） -------------------------------------------
    t0 = time.perf_counter()
    beans: list[PairedBean] = pair_observations(observations["top"], observations["bottom"])
    t["pairing"] = time.perf_counter() - t0
    assert len(beans) == len(tray.beans), f"盘 {idx}: 配对粒数 {len(beans)} != {len(tray.beans)}"
    assert all(b.top is not None and b.bottom is not None for b in beans), f"盘 {idx}: 出现单面豆"
    # 弦切（破碎）豆翻面后弓形段质心天然横移（实测 ≤4.2mm，理论 ≤2δ≈0.6·a），
    # 加抖动/波纹残差取 6mm 界——远小于配对门限 12mm，误配不可能胜出
    assert max(b.pairing_cost for b in beans) <= 6.0, (
        f"盘 {idx}: 配对代价过大（标定/抖动残差超界）"
    )

    # ---- 严重度（与配对产物 + 合成真值双核对） ----------------------------
    t0 = time.perf_counter()
    # 配对产物按 (x,y) 锚定排序，与 compose 布局序不同——用 mask_id 编码的
    # 合成下标（top_{i:04d}）回查真值，与排序无关
    truth_by_mask = {
        f"top_{i:04d}": bean.cls for i, bean in enumerate(tray.beans)
    }
    for paired in beans:
        fd, ws = adj.worst(paired.top, paired.bottom)
        assert (fd, ws) == (paired.final_defect, paired.worst_side), (
            f"盘 {idx}: 严重度裁决与配对产物不一致 @ {paired.bean_id}"
        )
        truth_cls = truth_by_mask[paired.top.obs_id]
        assert paired.final_defect == truth_cls, (
            f"盘 {idx}: {paired.bean_id} final={paired.final_defect} != 真值 {truth_cls}"
        )
    t["severity"] = time.perf_counter() - t0

    # ---- 计量 -------------------------------------------------------------
    t0 = time.perf_counter()
    measurements = measure(beans, calib, std_path)
    t["metrology"] = time.perf_counter() - t0
    assert measurements.bean_count == len(beans)

    # ---- 定级（oracle 自洽：defect_counts 与真值直方完全一致） -------------
    t0 = time.perf_counter()
    grading = engine.evaluate(beans, measurements)
    t["grading"] = time.perf_counter() - t0
    # oracle 自洽真值口径（与 W7/W9 引擎一致）：defect_counts = 逐粒
    # final_defect 直方（normal 不计，peaberry 标注保留照记）；主/次分计
    # 只数 counts_as_defect=true（peaberry 不入主次）。
    truth_hist = Counter(b.cls for b in tray.beans if b.cls != "normal")
    got_hist = {k: v for k, v in grading.defect_counts.items() if v > 0}
    assert got_hist == dict(truth_hist), f"盘 {idx}: defect_counts {got_hist} != 真值 {dict(truth_hist)}"
    n_primary = sum(
        n for c, n in truth_hist.items()
        if tax.get(c).counts_as_defect and tax.get(c).kind == "primary"
    )
    n_secondary = sum(
        n for c, n in truth_hist.items()
        if tax.get(c).counts_as_defect and tax.get(c).kind == "secondary"
    )
    assert grading.primary_count == n_primary and grading.secondary_count == n_secondary

    # ---- 溯因（模板保底） + 护照 -------------------------------------------
    t0 = time.perf_counter()
    result = BatchResult(
        result_id=f"smoke-{idx:04d}-{seed}",
        sample_id=f"sample_synth_{idx:04d}",
        scan_ids=[tray.scan_id],
        beans=beans,
        measurements=measurements,
        grading=grading,
        agent_report=None,
        timings_s={k: round(v, 4) for k, v in t.items()},
        pipeline_versions={"segment": "synth_oracle", "classify": "synth_truth", "standard": args.standard},
    )
    report = agent.explain(result, "zh")
    t["agent"] = time.perf_counter() - t0
    result = result.model_copy(update={"agent_report": report, "pipeline_versions": {**result.pipeline_versions, "agent": report.backend}})

    t0 = time.perf_counter()
    passport = build_passport(
        result,
        Path(args.out) / "reports" / result.result_id,
        langs=tuple(args.langs),
        crop_root=Path(args.out),
    )
    t["passport"] = time.perf_counter() - t0
    rid, sha = parse_qr_payload(passport.qr_payload)
    assert rid == result.result_id and sha == canonical_sha256(result)
    for lang in args.langs:
        html = Path(passport.html_paths[lang])
        assert html.is_file() and html.stat().st_size > 20_000, f"盘 {idx}: {lang} 护照过小/缺失"

    return {
        "scan_id": tray.scan_id,
        "n_beans": len(tray.beans),
        "n_defect": int(sum(truth_hist.values())),
        "grade": grading.grade,
        "passed": grading.passed,
        "ppm_err_pct": round(ppm_err * 100, 3),
        "max_pair_cost_mm": round(max(b.pairing_cost for b in beans), 3),
        "px_per_mm": round(calib.px_per_mm, 4),
        "seconds": {k: round(v, 3) for k, v in t.items()},
    }


def _shoelace(poly: list[list[float]]) -> float:
    arr = np.asarray(poly, dtype=np.float64)
    x, y = arr[:, 0], arr[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2.0)


def _centroid(poly: list[list[float]]) -> tuple[float, float]:
    m = cv2.moments(np.asarray(poly, dtype=np.float32))
    return (float(m["m10"] / m["m00"]), float(m["m01"] / m["m00"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trays", type=int, default=50)
    ap.add_argument("--canvas", type=int, default=2048)
    ap.add_argument("--min-beans", type=int, default=60)
    ap.add_argument("--max-beans", type=int, default=110)
    ap.add_argument("--defect-rate", type=float, default=0.05)
    ap.add_argument("--standard", default="cqi_fine_robusta")
    ap.add_argument("--langs", default="zh,en,vi")
    ap.add_argument("--seed0", type=int, default=860001)
    ap.add_argument("--out", default="out/synth_chain_smoke")
    args = ap.parse_args()
    args.langs = [s.strip() for s in args.langs.split(",") if s.strip()]

    t_all = time.perf_counter()
    tax = load_taxonomy()
    engine = load_engine(args.standard)
    agent = make_agent(backend="template")
    adj = SeverityAdjudicator(default_severity_order())  # 复用（taxonomy 只读一次）
    std_path = str(Path(ROOT) / "configs" / "standards" / f"{args.standard}.yaml")
    cfg = build_smoke_config(args)
    library = None  # 首盘按配置种子构建后复用（同素材库跨盘）

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for k in range(args.trays):
        seed = args.seed0 + k
        if library is None:
            from beaneye.synth import sample_library

            library = sample_library(cfg.library_seed, cfg.per_class)
        row = run_tray(k + 1, seed, cfg, library, args, tax, engine, agent, std_path, adj)
        if k == 0:
            # 第 1 盘落盘产物抽样（含 RLE 标注 + manifest.yaml）
            tray = compose_tray(seed=seed, config=cfg, library=library)
            paths = write_batch(tray, out / "batch_sample", index=1, with_rle=True)
            row["batch_files"] = {kk: Path(vv).name for kk, vv in paths.items()}
        rows.append(row)
        print(
            f"[{k + 1}/{args.trays}] {row['scan_id']} beans={row['n_beans']} "
            f"defect={row['n_defect']} grade={row['grade']} ppm_err={row['ppm_err_pct']}% "
            f"pair_cost<={row['max_pair_cost_mm']}mm t={sum(row['seconds'].values()):.1f}s",
            flush=True,
        )

    total_s = time.perf_counter() - t_all
    stage_mean = {
        s: round(sum(r["seconds"][s] for r in rows) / len(rows), 3)
        for s in rows[0]["seconds"]
    }
    summary = {
        "smoke": "synth_chain (compose→calibration→pairing→severity→metrology→grading→passport)",
        "trays": args.trays,
        "standard": args.standard,
        "langs": args.langs,
        "total_s": round(total_s, 1),
        "mean_s_per_tray": round(total_s / args.trays, 2),
        "stage_mean_s": stage_mean,
        "beans_total": sum(r["n_beans"] for r in rows),
        "defects_total": sum(r["n_defect"] for r in rows),
        "grades": dict(Counter(r["grade"] for r in rows)),
        "rows": rows,
    }
    write_json(out / "summary.json", summary)
    print(
        f"\nSMOKE PASS: {args.trays} 盘全链（标定→配对→严重度→计量→定级→护照）全断言通过；"
        f"总时长 {total_s:.0f}s（{summary['mean_s_per_tray']}s/盘）；"
        f"阶段均值 {stage_mean}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
