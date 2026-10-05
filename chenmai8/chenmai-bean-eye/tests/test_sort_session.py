"""分拣线 eval · SortSession 状态机流转与急停。

覆盖：IDLE→PLANNED→PICKING→DONE 主流程、PICK 六步动作序列、软件急停
（作业中途/空闲态/幂等）、急停后拒绝后续作业、越界前置拒绝、限速钳制、
事件日志与 JSON 导出、报告口径。

运行（仓库根）::

    .venv/Scripts/python.exe -m pytest tests/test_sort_session.py -q
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from beaneye.sort import (
    ArmEStopError,
    ArmNotConnectedError,
    ArmWorkspaceError,
    MockArm,
    PHASE_DONE,
    PHASE_ESTOPPED,
    PHASE_ERROR,
    PHASE_IDLE,
    PHASE_PICKING,
    PHASE_PLANNED,
    SessionEStopError,
    SessionError,
    SortPlanner,
    SortSession,
    SortTarget,
    WorkspaceBounds,
    load_sort_config,
)

CFG = load_sort_config()

BOUNDS = WorkspaceBounds(
    x_min_mm=0.0, x_max_mm=300.0, y_min_mm=-150.0, y_max_mm=150.0,
    z_min_mm=0.0, z_max_mm=150.0, home_mm=(150.0, 0.0, 80.0),
)

PICK_Z = CFG.pick.pick_z_mm
TRAVEL_Z = CFG.pick.travel_z_mm


def make_arm(sleeps: list | None = None, hook=None) -> MockArm:
    a = MockArm(
        BOUNDS,
        max_speed_mm_s=CFG.speeds.max_mm_s,
        gripper_travel_s=CFG.pick.gripper_travel_s,
        time_scale=1e6,                      # 仿真加速，测试零真实等待
        now_fn=lambda: 0.0,
        sleep_fn=(sleeps.append if sleeps is not None else (lambda s: None)),
        hook=hook,
    )
    a.connect()
    a.home()
    return a


def make_session(arm: MockArm, planner: SortPlanner | None = None) -> SortSession:
    return SortSession(arm, planner or SortPlanner(CFG, workspace=BOUNDS), config=CFG)


def targets():
    return [
        SortTarget(target_id="t_black", defect="black", severity_rank=12,
                   x_mm=100.0, y_mm=-20.0, area_mm2=28.0, conf=0.9),
        SortTarget(target_id="t_broken", defect="broken", severity_rank=1,
                   x_mm=140.0, y_mm=30.0, area_mm2=27.0, conf=0.8),
    ]


# ---------------------------------------------------------------------------
# 主流程与 PICK 动作序列
# ---------------------------------------------------------------------------


def test_full_run_happy_path():
    arm = make_arm()
    session = make_session(arm)
    assert session.phase == PHASE_IDLE

    plan = session.scan(targets())
    assert session.phase == PHASE_PLANNED
    assert len(plan.steps) == 2
    assert [s.target.defect for s in plan.steps] == ["black", "broken"]

    report = session.run()
    assert session.phase == PHASE_DONE
    assert report.status == "done"
    assert report.executed_steps == 2
    assert report.total_steps == 2
    assert report.per_bin_counts == {"black": 1, "broken": 1}
    assert report.skipped_count == 0


def test_pick_step_motion_sequence_and_gripper():
    """单步 = 移上方→下降→夹取→抬起→移盒→松开；事件序列完整可审计。"""
    arm = make_arm()
    session = make_session(arm)
    session.scan(targets())
    session.step()  # 第一步（black）

    moves = [e for e in arm.events if e["kind"] == "move"]
    # home(150,0,80) → 上方(100,-20,70) → 降(100,-20,8) → 抬(100,-20,70) → 盒(170,-75,70)
    assert [(round(m["detail"]["to_mm"][0], 1), round(m["detail"]["to_mm"][1], 1),
             round(m["detail"]["to_mm"][2], 1)) for m in moves] == [
        (150.0, 0.0, 80.0),        # home
        (100.0, -20.0, TRAVEL_Z),  # approach
        (100.0, -20.0, PICK_Z),    # descend
        (100.0, -20.0, TRAVEL_Z),  # lift
        (170.0, -75.0, TRAVEL_Z),  # transfer to bin
    ]
    grip = [e["kind"] for e in arm.events if e["kind"].startswith("gripper")]
    assert grip == ["gripper_close", "gripper_open"]

    sess_events = [e["event"] for e in session.events]
    assert sess_events[:4] == ["scan", "plan", "picking_start", "approach"]


def test_step_returns_done_flag_and_run_equals_step_loop():
    arm = make_arm()
    session = make_session(arm)
    session.scan(targets())
    assert session.step() is True   # 还有下一步
    assert session.phase == PHASE_PICKING
    assert session.step() is False  # 最后一步完成 → done
    assert session.phase == PHASE_DONE
    assert session.step() is False  # done 后再 step 幂等返回 False


def test_scan_only_once():
    session = make_session(make_arm())
    session.scan(targets())
    with pytest.raises(SessionError):
        session.scan(targets())


def test_step_before_scan_rejected():
    session = make_session(make_arm())
    with pytest.raises(SessionError):
        session.step()


def test_run_after_done_is_noop_report():
    session = make_session(make_arm())
    session.scan(targets())
    session.run()
    report = session.run()
    assert report.status == "done" and report.executed_steps == 2


# ---------------------------------------------------------------------------
# 急停语义
# ---------------------------------------------------------------------------


def test_estop_mid_run_freezes_session_and_arm():
    """作业中途急停：Session 冻结在 estopped、臂闩锁、后续 step 拒绝。"""
    arm = make_arm()
    session = make_session(arm)
    session.scan(targets())

    session.step()                      # 第一步完整执行
    moves_after_first = arm.moves
    session.estop()                     # 第二步前急停
    assert session.estop_latched
    assert session.phase == PHASE_ESTOPPED
    assert arm.estop_latched

    with pytest.raises(SessionEStopError):
        session.step()
    assert arm.moves == moves_after_first  # 急停后零新增运动
    # 急停后禁止新建计划（estopped 非 idle，阶段闸先拒绝；SessionEStopError ⊂ SessionError）
    with pytest.raises(SessionError):
        session.scan(targets())


def test_estop_during_step_via_arm_hook():
    """臂事件钩子中触发急停（模拟外部线程）：当前步立即中断、零运动完成。"""
    holder: dict = {}

    class HookedArm(MockArm):
        def _event(self, kind, detail):  # 在 transfer（移向分级盒）事件时急停
            super()._event(kind, detail)
            if holder.get("armed") and kind == "move" and len(
                [e for e in self.events if e["kind"] == "move"]) >= 4:
                holder["session"].estop()

    arm = HookedArm(
        BOUNDS, max_speed_mm_s=CFG.speeds.max_mm_s, time_scale=1e6,
        now_fn=lambda: 0.0, sleep_fn=lambda s: None,
    )
    arm.connect()
    arm.home()
    session = make_session(arm)
    holder["session"] = session
    holder["armed"] = True
    session.scan(targets())

    with pytest.raises(SessionEStopError):
        session.step()
    assert session.phase == PHASE_ESTOPPED
    assert arm.estop_latched
    # 中断发生后不再有新运动
    moves_at_estop = arm.moves
    with pytest.raises(SessionEStopError):
        session.step()
    assert arm.moves == moves_at_estop


def test_estop_when_idle_and_idempotent():
    session = make_session(make_arm())
    session.estop()
    assert session.phase == PHASE_ESTOPPED
    session.estop()  # 幂等
    assert session.phase == PHASE_ESTOPPED
    with pytest.raises(SessionEStopError):
        session.step()


# ---------------------------------------------------------------------------
# 安全包络：越界前置拒绝 / 限速钳制
# ---------------------------------------------------------------------------


def test_out_of_workspace_plan_target_is_skipped_not_error():
    arm = make_arm()
    session = make_session(arm)
    plan = session.scan(targets() + [
        SortTarget(target_id="t_far", defect="mold", severity_rank=11,
                   x_mm=400.0, y_mm=0.0, area_mm2=26.0),
    ])
    assert plan.skipped and plan.skipped[0].target.target_id == "t_far"
    session.run()
    assert session.phase == PHASE_DONE


def test_arm_side_workspace_error_puts_session_in_error():
    """纵深防御：绕过 planner 构造越界 step（直接改计划）→ 臂侧拒绝 → ERROR。"""
    arm = make_arm()
    session = make_session(arm)
    session.scan(targets())
    # 篡改计划：把第二步的分级盒挪出包络（模拟配置被运行时改坏）
    evil = session.plan.steps[1].model_copy(update={"bin_x_mm": 900.0, "bin_y_mm": 0.0})
    bad_plan = session.plan.model_copy(update={"steps": [session.plan.steps[0], evil]})
    session._plan = bad_plan  # noqa: SLF001 — 白盒注入验证纵深防御

    assert session.step() is True          # 第一步干净，正常完成
    with pytest.raises(ArmWorkspaceError, match="前置校验"):
        session.step()                      # 第二步：Session 前置校验先拒绝
    assert session.phase == PHASE_ERROR


def test_arm_not_connected_surfaces_as_arm_error():
    arm = make_arm()
    arm.close()
    session = make_session(arm)
    session.scan(targets())
    with pytest.raises(ArmNotConnectedError):
        session.step()
    assert session.phase == PHASE_ERROR


def test_speeds_clamped_to_config_hard_limit():
    """Session 下发速度永远 <= speeds.max_mm_s（配置即硬上限）。"""
    seen_speeds: list[float] = []

    class SpeedSpyArm(MockArm):
        def move_to(self, x, y, z, *, speed):
            seen_speeds.append(float(speed))
            super().move_to(x, y, z, speed=speed)

    arm = SpeedSpyArm(
        BOUNDS, max_speed_mm_s=CFG.speeds.max_mm_s, time_scale=1e6,
        now_fn=lambda: 0.0, sleep_fn=lambda s: None,
    )
    arm.connect()
    arm.home()
    session = SortSession(arm, SortPlanner(CFG, workspace=BOUNDS), config=CFG)
    # 用一个「限速全拉满」的配置验证钳制：descend/lift 仍受 max 限制
    session.scan(targets())
    session.run()
    assert seen_speeds, "应记录到至少一次 move"
    assert all(s <= CFG.speeds.max_mm_s for s in seen_speeds)


# ---------------------------------------------------------------------------
# 事件日志与导出
# ---------------------------------------------------------------------------


def test_events_recorded_and_export_json(tmp_path: Path):
    arm = make_arm()
    session = make_session(arm)
    session.scan(targets())
    session.run()

    kinds = [e["event"] for e in session.events]
    assert kinds[0] == "scan" and "plan" in kinds and "done" in kinds
    for e in session.events:
        assert {"t_s", "session_id", "phase", "event", "detail"} <= set(e)

    out = tmp_path / "traj.json"
    session.export_json(out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema"] == "beaneye.sort.session/v1"
    assert data["session_id"] == session.session_id
    assert data["phase"] == PHASE_DONE
    assert data["plan"]["steps"][0]["target"]["defect"] == "black"
    assert data["session_events"] == session.events
    assert data["arm_events"] == arm.events
    assert len(data["trajectory"]) == len(arm.trajectory)
    assert data["trajectory"][0]["phase"] == "init"


def test_report_counts_with_skipped():
    arm = make_arm()
    session = make_session(arm)
    session.scan(targets() + [
        # x=400 在测试包络 BOUNDS(x<=300) 与配置包络(x<=200) 之外 → skip
        SortTarget(target_id="t_out", defect="mold", severity_rank=11,
                   x_mm=400.0, y_mm=10.0, area_mm2=25.0),
    ])
    report = session.run()
    assert report.skipped_count == 1
    assert report.executed_steps == report.total_steps == 2
    assert report.per_bin_counts == {"black": 1, "broken": 1}
