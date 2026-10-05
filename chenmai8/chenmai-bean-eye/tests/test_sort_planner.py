"""分拣线 eval · SortPlanner 排序与分盒正确性（真实 taxonomy key）。

覆盖：severity 降序、平级确定性次序、normal 排除、缺陷→分级盒映射
（含 default 兜底）、severity_rank 与 taxonomy 一致性校验、工作空间
前置校验跳过、BeanObservation → SortTarget 转换（托盘 mm → 桌面 mm）。

运行（仓库根）::

    .venv/Scripts/python.exe -m pytest tests/test_sort_planner.py -q
"""

from __future__ import annotations

import pytest

from beaneye.schemas import BeanMask, BeanObservation
from beaneye.sort import (
    FrameToTable,
    PlannerError,
    SortConfigError,
    SortPlanner,
    SortTarget,
    Extrinsic2D,
    load_sort_config,
    solve_affine,
    targets_from_observations,
)
from beaneye.taxonomy import load_taxonomy

TAX = load_taxonomy()
# taxonomy 默认序位次：normal=0 broken=1 faded=2 brocade=3 immature=4 peaberry=5
# shell=6 elephant=7 insect=8 dried=9 sour=10 mold=11 black=12
RANK = {k: TAX.severity_rank(k) for k in TAX.keys()}

CFG = load_sort_config()


def target(tid: str, defect: str, x: float = 120.0, y: float = 0.0, area: float = 28.0, conf: float = 0.9) -> SortTarget:
    return SortTarget(
        target_id=tid,
        defect=defect,
        severity_rank=RANK[defect],
        x_mm=x,
        y_mm=y,
        area_mm2=area,
        conf=conf,
    )


@pytest.fixture()
def planner():
    return SortPlanner(CFG)


# ---------------------------------------------------------------------------
# 排序契约
# ---------------------------------------------------------------------------


def test_severity_descending_order(planner):
    """最严重（black=12）先抓，依次 mold(11) → sour(10) → insect(8) → broken(1)。"""
    targets = [
        target("t_broken", "broken"),
        target("t_black", "black"),
        target("t_insect", "insect"),
        target("t_mold", "mold"),
        target("t_sour", "sour"),
    ]
    plan = planner.plan(targets)
    assert [s.target.defect for s in plan.steps] == ["black", "mold", "sour", "insect", "broken"]
    assert [s.order for s in plan.steps] == [1, 2, 3, 4, 5]


def test_normal_excluded_but_peaberry_kept(planner):
    """normal 不入队；peaberry（counts_as_defect=false 的标注类）仍按位次入队。"""
    plan = planner.plan([
        target("t_norm", "normal"),
        target("t_pea", "peaberry", x=100.0),
        target("t_black", "black", x=110.0),
    ])
    assert [s.target.defect for s in plan.steps] == ["black", "peaberry"]
    assert all("t_norm" != s.target.target_id for s in plan.steps)


def test_tie_break_area_desc_then_id(planner):
    """同级：面积大者先；再平则 target_id 字典序（确定性、可复现）。"""
    targets = [
        target("t_b", "broken", area=25.0),
        target("t_c", "broken", area=30.0),
        target("t_a", "broken", area=30.0),
    ]
    plan = planner.plan(targets)
    assert [s.target.target_id for s in plan.steps] == ["t_a", "t_c", "t_b"]


def test_empty_plan(planner):
    plan = planner.plan([target("t_norm", "normal")])
    assert plan.steps == [] and plan.skipped == []


# ---------------------------------------------------------------------------
# 分级盒映射
# ---------------------------------------------------------------------------


def test_bin_mapping_uses_config(planner):
    """缺陷 → 分级盒坐标取自 configs/sort.yaml bins 节。"""
    plan = planner.plan([target("t_black", "black", x=100.0, y=-10.0)])
    step = plan.steps[0]
    assert step.bin_name == "black"
    assert (step.bin_x_mm, step.bin_y_mm) == CFG.bins_mm["black"]
    # 抓取坐标 = 目标坐标 + 配置抓取面/巡航高度
    assert (step.pick_x_mm, step.pick_y_mm) == (100.0, -10.0)
    assert step.pick_z_mm == CFG.pick.pick_z_mm
    assert step.travel_z_mm == CFG.pick.travel_z_mm


def test_unknown_defect_class_falls_back_to_default_bin(planner):
    """taxonomy 内但未登记 bins 的类别走 default 兜底盒（taxonomy 13 类全覆盖
    bins 时该路径仅在配置裁剪后触发——这里直接构造裁剪配置验证）。"""
    from dataclasses import replace
    trimmed = replace(CFG, bins_mm={"default": CFG.bins_mm["default"]})
    plan = SortPlanner(trimmed).plan([target("t_shell", "shell")])
    assert plan.steps[0].bin_name == "default"
    assert (plan.steps[0].bin_x_mm, plan.steps[0].bin_y_mm) == CFG.bins_mm["default"]


def test_severity_rank_must_match_taxonomy(planner):
    """rank 与 taxonomy 不一致 = 上游谎报，拒绝（排序契约唯一依据是 taxonomy）。"""
    bad = SortTarget(
        target_id="t_liar", defect="broken", severity_rank=12,
        x_mm=100.0, y_mm=0.0, area_mm2=28.0,
    )
    with pytest.raises(PlannerError, match="taxonomy"):
        planner.plan([bad])


def test_unknown_defect_key_rejected(planner):
    bad = SortTarget(
        target_id="t_x", defect="not_a_key", severity_rank=3,
        x_mm=100.0, y_mm=0.0, area_mm2=28.0,
    )
    with pytest.raises(PlannerError, match="not_a_key"):
        planner.plan([bad])


# ---------------------------------------------------------------------------
# 工作空间前置校验
# ---------------------------------------------------------------------------


def test_out_of_workspace_target_skipped_with_reason(planner):
    """越界目标不阻塞全盘：进 skipped（含原因），其余照常入队。"""
    plan = planner.plan([
        target("t_out", "mold", x=20.0, y=0.0),      # 越界（x<x_min=55）
        target("t_in", "black", x=100.0, y=0.0),
    ])
    assert [s.target.target_id for s in plan.steps] == ["t_in"]
    assert len(plan.skipped) == 1
    assert plan.skipped[0].target.target_id == "t_out"
    assert "工作空间" in plan.skipped[0].reason


def test_skipped_severity_still_sorted_before_in_workspace(planner):
    """越界的最严重目标进 skipped；入队次序在可达目标中仍按 severity 降序。"""
    plan = planner.plan([
        target("t_broken", "broken", x=120.0),
        target("t_black_out", "black", x=10.0),  # 越界
        target("t_mold", "mold", x=130.0),
    ])
    assert [s.target.defect for s in plan.steps] == ["mold", "broken"]
    assert plan.skipped[0].target.defect == "black"


def test_bin_outside_workspace_skips_target(planner):
    """分级盒在包络外（如仿真放大包络未盖住配置盒位）→ 目标显式 skipped，
    而不是执行中 transfer 段才被 Session 拒绝。"""
    from beaneye.sort import WorkspaceBounds
    narrow = WorkspaceBounds(
        x_min_mm=55.0, x_max_mm=200.0, y_min_mm=-80.0, y_max_mm=80.0,  # 盖不住 y=±90 的盒
        z_min_mm=0.0, z_max_mm=140.0, home_mm=(120.0, 0.0, 70.0),
    )
    p = SortPlanner(CFG, workspace=narrow)
    plan = p.plan([
        target("t_ok", "sour", x=120.0, y=0.0),      # sour 盒 y=-15，在窄包络内
        target("t_bin_far", "peaberry", x=120.0, y=0.0),  # peaberry 盒 (80,-90)，盒在包络外
    ])
    assert [s.target.target_id for s in plan.steps] == ["t_ok"]
    assert [s.target.target_id for s in plan.skipped] == ["t_bin_far"]
    assert "分级盒" in plan.skipped[0].reason


def test_plan_per_bin_counts(planner):
    plan = planner.plan([
        target("a", "black", x=100.0, y=-10.0),
        target("b", "black", x=105.0, y=-12.0),
        target("c", "mold", x=110.0, y=-14.0),
    ])
    assert plan.per_bin_counts() == {"black": 2, "mold": 1}


# ---------------------------------------------------------------------------
# 观测转换（BeanObservation 托盘 mm → SortTarget 桌面 mm）
# ---------------------------------------------------------------------------


def _observation(obs_id: str, defect: str, cx_mm: float, cy_mm: float, area_mm2: float = 28.0) -> BeanObservation:
    mask = BeanMask(
        mask_id=obs_id,
        side="top",
        polygon=[[cx_mm - 3, cy_mm - 3], [cx_mm + 3, cy_mm - 3], [cx_mm + 3, cy_mm + 3]],
        bbox_mm=(cx_mm - 3, cy_mm - 3, cx_mm + 3, cy_mm + 3),
        area_mm2=area_mm2,
        centroid_mm=(cx_mm, cy_mm),
        source="classic",
        conf=0.9,
    )
    return BeanObservation(
        obs_id=obs_id,
        side="top",
        defect=defect,
        defect_conf=0.9,
        severity_rank=RANK[defect],
        crop_path=f"out/crops/{obs_id}.png",
        mask=mask,
        color_lab=(120.0, 128.0, 128.0),
        eq_diameter_mm=6.0,
    )


def test_targets_from_observations_applies_extrinsic():
    """托盘 mm → 桌面 mm：外参平移 + 旋转作用在质心上（与 frame.py 同一实现）。"""
    H = [[6.8267, 0.0, 0.0], [0.0, 6.8267, 0.0], [0.0, 0.0, 1.0]]  # px↔mm 恒等比例（不影响本用例）
    mapper = FrameToTable(H=H, extrinsic=Extrinsic2D(yaw_deg=90.0, offset_mm=(100.0, 0.0)))
    obs = [_observation("o1", "black", cx_mm=10.0, cy_mm=0.0)]
    targets = targets_from_observations(obs, mapper)
    # 托盘 (10,0) → 旋转 90°：(0,10) → 平移 (100,0) → (100, 10)
    assert targets[0].x_mm == pytest.approx(100.0, abs=1e-9)
    assert targets[0].y_mm == pytest.approx(10.0, abs=1e-9)
    assert targets[0].defect == "black"
    assert targets[0].severity_rank == RANK["black"]


def test_solve_affine_recovers_known_affine():
    """三点标定：精确恢复已知仿射（平移+旋转+缩放），并给出小残差。"""
    from beaneye.sort import fit_residual
    import math
    theta = math.radians(30.0)
    a_true = 2.0 * math.cos(theta)
    b_true = -2.0 * math.sin(theta)
    src = [[0.0, 0.0], [10.0, 0.0], [0.0, 10.0], [7.0, -3.0]]
    dst = [
        [a_true * p[0] + b_true * p[1] + 5.0, -b_true * p[0] + a_true * p[1] - 2.0]
        for p in src
    ]
    aff = solve_affine(src, dst)
    for p, q in zip(src, dst):
        got = aff.apply(p)
        assert got[0] == pytest.approx(q[0], abs=1e-9)
        assert got[1] == pytest.approx(q[1], abs=1e-9)
    assert fit_residual(aff, src, dst) < 1e-9


def test_solve_affine_rejects_collinear_and_short_input():
    with pytest.raises(Exception):  # FrameMappingError
        solve_affine([[0, 0], [1, 1], [2, 2]], [[0, 0], [1, 1], [2, 2]])
    with pytest.raises(Exception):  # 点数不足
        solve_affine([[0, 0], [1, 0]], [[0, 0], [1, 0]])


def test_planner_workspace_override_for_sim():
    """仿真可注入放大包络（demo 用）；默认用 config.workspace。"""
    from beaneye.sort import WorkspaceBounds
    big = WorkspaceBounds(
        x_min_mm=-200.0, x_max_mm=200.0, y_min_mm=-200.0, y_max_mm=200.0,
        z_min_mm=0.0, z_max_mm=200.0, home_mm=(0.0, 0.0, 120.0),
    )
    p = SortPlanner(CFG, workspace=big)
    assert p.workspace is big
    plan = p.plan([target("t_out_normally", "mold", x=20.0)])
    assert len(plan.steps) == 1 and plan.skipped == []


def test_config_rejects_bin_outside_workspace():
    """分级盒在包络外 = 配置自相矛盾，加载期即拒绝。"""
    import yaml
    from pathlib import Path
    raw = {
        "workspace": {
            "x_min_mm": 55.0, "x_max_mm": 200.0, "y_min_mm": -100.0, "y_max_mm": 100.0,
            "z_min_mm": 0.0, "z_max_mm": 140.0, "home_mm": [120.0, 0.0, 100.0],
        },
        "speeds": {
            "max_mm_s": 120.0, "default_mm_s": 80.0, "travel_mm_s": 80.0,
            "descend_mm_s": 25.0, "lift_mm_s": 50.0,
        },
        "pick": {"pick_z_mm": 8.0, "travel_z_mm": 70.0, "gripper_travel_s": 0.3},
        "extrinsic": {"yaw_deg": 0.0, "offset_mm": [0.0, 0.0]},
        "bins": {"default": [500.0, 0.0]},  # 远超包络
        "estop": {"torque_off": True, "require_home_after_resume": True},
        "so101": {
            "port": "COM3", "baudrate": 1000000,
            "base_offset_mm": 22.0, "shoulder_z_mm": 45.0, "l1_mm": 103.0,
            "l2_mm": 112.0, "speed_scaling": 1.0, "move_timeout_s": 10.0,
            "poll_interval_s": 0.02, "arrival_tol_deg": 3.0,
            "gripper_open_deg": 60.0, "gripper_closed_deg": 18.0,
            "motors": {
                "base": {"id": 1, "min_deg": -170.0, "max_deg": 170.0,
                         "center_raw": 2048.0, "raw_per_deg": 11.3778},
            },
        },
    }
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True)
        path = f.name
    try:
        with pytest.raises(SortConfigError, match="bins.default"):
            load_sort_config(path)
    finally:
        Path(path).unlink(missing_ok=True)
