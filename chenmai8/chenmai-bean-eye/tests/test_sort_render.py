"""分拣线 eval · 计划/轨迹可视化与前后对比图（离线纯渲染）。

覆盖：draw_plan 标注不改入参、draw_trajectory 折线、erase_targets 抹除、
before_after_panel 拼接，全部用确定性帧与 MockArm 轨迹。

运行（仓库根）::

    .venv/Scripts/python.exe -m pytest tests/test_sort_render.py -q
"""

from __future__ import annotations

import numpy as np
import pytest

from beaneye.sort import (
    Extrinsic2D,
    FrameToTable,
    MockArm,
    SortPlanner,
    SortTarget,
    WorkspaceBounds,
    draw_plan,
    draw_trajectory,
    erase_targets,
    before_after_panel,
    area_mm_to_r,
    load_sort_config,
)

CFG = load_sort_config()

BOUNDS = WorkspaceBounds(
    x_min_mm=0.0, x_max_mm=300.0, y_min_mm=-150.0, y_max_mm=150.0,
    z_min_mm=0.0, z_max_mm=150.0, home_mm=(150.0, 0.0, 80.0),
)


@pytest.fixture()
def mapper():
    # px==mm 恒等映射 + 外参恒等：桌面 mm 坐标即像素坐标，断言直观
    return FrameToTable(H=np.eye(3), extrinsic=Extrinsic2D())


@pytest.fixture()
def frame():
    img = np.full((300, 300, 3), 235, dtype=np.uint8)  # 浅灰背景
    img[40:60, 40:60] = (30, 30, 160)                  # 一块深色「豆」
    return img


@pytest.fixture()
def plan():
    targets = [
        SortTarget(target_id="t1", defect="black", severity_rank=12,
                   x_mm=50.0, y_mm=50.0, area_mm2=28.0, conf=0.9),
        SortTarget(target_id="t2", defect="broken", severity_rank=1,
                   x_mm=100.0, y_mm=120.0, area_mm2=27.0, conf=0.8),
        SortTarget(target_id="t3", defect="mold", severity_rank=11,
                   x_mm=500.0, y_mm=10.0, area_mm2=26.0),  # 越界 → skipped
    ]
    return SortPlanner(CFG, workspace=BOUNDS).plan(targets)


def test_area_mm_to_r():
    assert area_mm_to_r(float(np.pi * 10 * 10)) == pytest.approx(10.0)


def test_draw_plan_annotates_and_preserves_input(frame, mapper, plan):
    snapshot = frame.copy()
    out = draw_plan(frame, mapper, plan)
    assert out.shape == frame.shape
    assert out is not frame
    # 入参不被修改
    assert np.array_equal(frame, snapshot)
    # 拾取点被画上非背景色（黑豆拾取点 (50,50) 处有标注环）
    assert not np.array_equal(out[50, 50], snapshot[50, 50])
    # 分级盒框（black 盒中心 ~(170,-75) 落在图外 → 框被裁剪不崩溃即可）
    assert out.dtype == np.uint8


def test_draw_plan_includes_skipped_marker(frame, mapper, plan):
    out = draw_plan(frame, mapper, plan, draw_skipped=True)
    assert out is not None and out.shape == frame.shape


def test_draw_trajectory_line_and_start_marker(mapper):
    arm = MockArm(BOUNDS, time_scale=1e6, now_fn=lambda: 0.0, sleep_fn=lambda s: None)
    arm.connect()
    arm.home()
    arm.move_to(100.0, 40.0, 30.0, speed=100.0)
    frame = np.full((300, 300, 3), 235, dtype=np.uint8)
    snapshot = frame.copy()
    out = draw_trajectory(frame, mapper, arm.trajectory)
    assert out.shape == frame.shape
    assert np.array_equal(frame, snapshot)  # 入参不被修改
    # 轨迹线中点（home(150,0) → (100,40) 的中点 ≈ (125,20)）被画上非背景色
    assert not np.array_equal(out[20, 125], snapshot[20, 125])
    empty = draw_trajectory(frame, mapper, [])
    assert np.array_equal(empty, frame)  # 空轨迹返回原图拷贝


def test_erase_targets_fills_background(frame, mapper):
    """等效半径圆域被背景色覆盖：豆中心像素变成周边背景色。"""
    before = frame.copy()
    out = erase_targets(frame, mapper, [[50.0, 50.0]], [400.0])  # r≈11.3mm
    assert not np.array_equal(out[50, 50], before[50, 50])  # 豆被抹掉
    assert abs(int(out[50, 50, 0]) - 235) < 30              # 变成背景灰附近


def test_before_after_panel_labels_and_shape(frame, mapper, plan):
    before = draw_plan(frame, mapper, plan)
    after = erase_targets(frame, mapper, [[50.0, 50.0]], [400.0])
    panel = before_after_panel(before, after)
    assert panel.shape[0] == before.shape[0]
    assert panel.shape[1] == before.shape[1] + after.shape[1] + 6
    # 顶部条带内有标签文字（"BEFORE" 基线在 (12,26)，其上游区域应出现非背景像素）
    top_left = panel[5:28, 5:110].reshape(-1, 3)
    assert int((np.abs(top_left.astype(int) - 235).sum(axis=1) > 30).sum()) > 20
