#!/usr/bin/env python3
"""SO-101 分拣线仿真演示（Mock 臂全链一条命令）。

运行（仓库根）::

    .venv/Scripts/python.exe scripts/demo_sort_sim.py                 # 缺省 1 盘
    .venv/Scripts/python.exe scripts/demo_sort_sim.py --seed 410002 --out out/sort_sim

链路（全部真实执行，Mock 的只有「臂」）::

    合成整盘图（beaneye.synth compose_tray，含四角 ArUco）
      → ArUco 标定 calibrate（beaneye.calibration，px → 托盘 mm）
      → 正射网格 warp_to_tray + ClassicSeg 逐粒分割（既有管线真实接线）
      → RulesV0 逐粒分类（缺陷 key + 置信度 + severity_rank）
      → FrameToTable 像素→桌面毫米（H + configs/sort.yaml 外参）
      → SortPlanner 严重度降序抓取队列 + 分级盒映射
      → MockArm 执行 SortSession（SCAN→PLAN→PICK 循环）
      → 前后对比 PNG + 轨迹 JSON 落盘 out/sort_sim/

诚实口径：识别结果来自真实 classic/rules 管线（合成盘上的已知精度有限，
标签仅供演示链路）；臂为 MockArm 内存仿真（time_scale 加速），不接任何硬件；
「after」帧中被抓走的豆是渲染抹除示意，非像素级真值。缺省用放大包络跑满
全盘（Mock 仿真语义），--strict-envelope 切回 configs/sort.yaml 真机包络
（超界目标显式 skipped）。

产物（out/sort_sim/）：frame_top.png（原帧）、before_after.png（对比图）、
trajectory.json（计划 + Session/臂事件 + 轨迹）、summary.json。
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from beaneye.acquisition.base import imwrite_bgr, write_json  # noqa: E402
from beaneye.app.components import build_components, normalize_seg_result  # noqa: E402
from beaneye.app.pipeline import extract_mask_crop_rgba  # noqa: E402
from beaneye.calibration import calibrate, load_tray_config, warp_to_tray  # noqa: E402
from beaneye.schemas import TrayScan  # noqa: E402
from beaneye.sort import (  # noqa: E402
    MockArm,
    SortPlanner,
    SortSession,
    WorkspaceBounds,
    before_after_panel,
    draw_plan,
    draw_trajectory,
    erase_targets,
    frame_to_table_from_calib,
    load_sort_config,
    targets_from_observations,
)
from beaneye.synth import ComposeConfig, compose_tray, sample_library  # noqa: E402
from beaneye.taxonomy import load_taxonomy  # noqa: E402

__all__ = ["main"]


def build_compose_config(args: argparse.Namespace) -> ComposeConfig:
    """合成配置：程序化默认（与 scripts/e2e_synth_run.py 同 schema，稀疏盘）。"""
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
        contact_min=0,
        contact_max=0,   # 稀疏盘：零接触/零重叠（分割已知短板是粘连切分）
        overlap_depth=0.8,
        free_factor=1.06,
        scale_jitter=0.10,
        angle_jitter=180.0,
        pair_jitter_mm=0.6,
        mirror_bottom=True,
        per_class=20,
        library_seed=args.seed,
    )


def detect_frame(tray, components) -> tuple[list, object]:
    """既有管线真实检测：ArUco 标定 → 正射 → ClassicSeg → RulesV0（top 面）。"""
    top_bgr = tray.top_bgr
    calib = calibrate(top_bgr)  # 四角 ArUco：px → 托盘 mm
    tray_cfg = load_tray_config()
    mm_per_px = tray_cfg.tray_mm / tray_cfg.grid_px
    warped = warp_to_tray(top_bgr, np.asarray(calib.H, dtype=np.float64), tray_cfg)

    scan = TrayScan(
        scan_id=tray.scan_id,
        sample_id="sort_sim",
        tray_id="tray_synth_01",
        top_image="top.png",
        bottom_image="bottom.png",
        calibration=None,
        captured_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        source="synth",
    )
    img_rgb = cv2.cvtColor(warped, cv2.COLOR_BGR2RGB)
    seg = normalize_seg_result(
        components.segment.impl.predict(img_rgb, scan), side="top", scan_id=scan.scan_id
    )
    observations = []
    for m in seg.masks:
        crop = extract_mask_crop_rgba(warped, m, mm_per_px)
        defect, conf, rank = components.classify.impl.classify(crop, m)
        observations.append(
            {
                "obs_id": m.mask_id,
                "defect": defect,
                "conf": float(conf),
                "severity_rank": int(rank),
                "mask": m,
            }
        )
    return observations, calib


def main() -> int:
    ap = argparse.ArgumentParser(description="SO-101 分拣线仿真演示（Mock 臂全链）")
    ap.add_argument("--seed", type=int, default=410001)
    ap.add_argument("--canvas", type=int, default=2048)
    ap.add_argument("--min-beans", type=int, default=40)
    ap.add_argument("--max-beans", type=int, default=70)
    ap.add_argument("--defect-rate", type=float, default=0.35, help="缺陷豆比例（演示调高于实盘）")
    ap.add_argument("--time-scale", type=float, default=1000.0, help="Mock 臂运动加速倍率")
    ap.add_argument("--strict-envelope", action="store_true",
                    help="用 configs/sort.yaml 真机包络（超界目标显式 skipped）；缺省放大包络跑满全盘")
    ap.add_argument("--out", default="out/sort_sim")
    args = ap.parse_args()

    t_all = time.perf_counter()
    cfg = load_sort_config()
    tax = load_taxonomy()

    print(f"[1/6] 合成整盘（seed={args.seed}, canvas={args.canvas}）...")
    compose_cfg = build_compose_config(args)
    library = sample_library(compose_cfg.library_seed, compose_cfg.per_class)
    tray = compose_tray(seed=args.seed, config=compose_cfg, library=library)

    print("[2/6] 既有管线检测（ArUco 标定 → ClassicSeg → RulesV0）...")
    components = build_components()
    degraded = components.degraded_stages()
    assert not degraded, f"识别组件降级 {degraded}（{components.degraded_reasons()}）——演示要求真实接线"
    observations, calib = detect_frame(tray, components)
    print(f"      检出 {len(observations)} 粒（reproj={calib.reproj_err_px:.2f}px, "
          f"px_per_mm={calib.px_per_mm:.3f}）")

    print("[3/6] 像素 → 桌面毫米（H + 外参）...")
    mapper = frame_to_table_from_calib(calib, cfg.extrinsic, side="top")

    # 检测字典 → SortTarget（桌面 mm）：直接复用 BeanObservation 语义字段
    from beaneye.schemas import BeanObservation  # 观测模型（crop_path 仅占位记录）
    obs_models = []
    for o in observations:
        obs_models.append(
            BeanObservation(
                obs_id=o["obs_id"],
                side="top",
                defect=o["defect"],
                defect_conf=o["conf"],
                severity_rank=o["severity_rank"],
                crop_path=f"crops/{o['obs_id']}.png",
                mask=o["mask"],
                color_lab=(120.0, 128.0, 128.0),
                eq_diameter_mm=6.0,
            )
        )
    targets = targets_from_observations(obs_models, mapper, taxonomy=tax)

    print("[4/6] 规划（severity 降序 + 分级盒映射）...")
    if args.strict_envelope:
        workspace = cfg.workspace
        print("      包络 = configs/sort.yaml 真机包络（超界目标将显式 skipped）")
    else:
        # Mock 仿真放大包络覆盖全盘 + configs/sort.yaml 分级盒排位
        # （真机请用 --strict-envelope，或实测后回填配置包络）
        workspace = WorkspaceBounds(
            x_min_mm=-50.0, x_max_mm=350.0, y_min_mm=-150.0, y_max_mm=350.0,
            z_min_mm=0.0, z_max_mm=cfg.workspace.z_max_mm,
            home_mm=(150.0, 100.0, cfg.pick.travel_z_mm),
        )
        print("      包络 = 仿真放大包络（覆盖全盘；--strict-envelope 切回真机口径）")
    planner = SortPlanner(cfg, taxonomy=tax, workspace=workspace)
    arm = MockArm(
        workspace,
        max_speed_mm_s=cfg.speeds.max_mm_s,
        gripper_travel_s=cfg.pick.gripper_travel_s,
        time_scale=args.time_scale,
    )
    session = SortSession(arm, planner, config=cfg)
    plan = session.scan(targets)
    per_bin = plan.per_bin_counts()
    print(f"      计划 {len(plan.steps)} 步 / 跳过 {len(plan.skipped)} 粒；分盒：{per_bin}")

    print("[5/6] MockArm 执行（SCAN→PLAN→PICK 循环，%dx 加速）..." % int(args.time_scale))
    arm.connect()
    arm.home()
    t_run = time.perf_counter()
    report = session.run()
    run_s = time.perf_counter() - t_run
    print(f"      执行 {report.executed_steps}/{report.total_steps} 步"
          f"（臂行程 {arm.travel_mm:.0f}mm，仿真 {run_s:.2f}s），status={report.status}")

    print("[6/6] 渲染前后对比与轨迹导出...")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    frame_path = imwrite_bgr(out / "frame_top.png", tray.top_bgr)

    picked_ids = {s.target.target_id for s in plan.steps}  # 全部计划步都会被抓走
    plan_img = draw_plan(tray.top_bgr, mapper, plan)
    traj_img = draw_trajectory(plan_img, mapper, arm.trajectory)
    picked_xy = [[s.pick_x_mm, s.pick_y_mm] for s in plan.steps if s.target.target_id in picked_ids]
    picked_area = [s.target.area_mm2 for s in plan.steps if s.target.target_id in picked_ids]
    after_img = erase_targets(traj_img, mapper, picked_xy, picked_area)
    panel = before_after_panel(tray.top_bgr, after_img)
    panel_path = imwrite_bgr(out / "before_after.png", panel)

    traj_path = session.export_json(out / "trajectory.json")
    elapsed = time.perf_counter() - t_all
    summary = {
        "demo": "sort_sim (synth frame -> calibration -> classic seg -> rules cls -> "
                "frame->table -> planner -> MockArm session)",
        "seed": args.seed,
        "canvas_px": args.canvas,
        "beans_truth": len(tray.beans),
        "beans_detected": len(observations),
        "plan_steps": len(plan.steps),
        "plan_skipped": len(plan.skipped),
        "skipped_reasons": [s.reason for s in plan.skipped][:10],
        "per_bin_counts": per_bin,
        "defect_hist_detected": {
            k: sum(1 for t in targets if t.defect == k) for k in sorted({t.defect for t in targets})
        },
        "arm_travel_mm": round(arm.travel_mm, 1),
        "run_s": round(run_s, 3),
        "total_s": round(elapsed, 3),
        "envelope": "strict(config)" if args.strict_envelope else "sim-wide(mock only)",
        "reproj_err_px": round(calib.reproj_err_px, 3),
        "outputs": {
            "frame": frame_path.name,
            "before_after": panel_path.name,
            "trajectory": traj_path.name,
        },
    }
    write_json(out / "summary.json", summary)
    print(
        f"\nSORT SIM PASS: 检出 {len(observations)} 粒 → 计划 {len(plan.steps)} 步 → "
        f"Mock 执行 {report.executed_steps} 步（分盒 {per_bin}）；产物 {out}/"
        f"（before_after.png / trajectory.json / summary.json），总耗时 {elapsed:.1f}s"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
