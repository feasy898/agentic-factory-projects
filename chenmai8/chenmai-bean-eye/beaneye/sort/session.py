"""分拣线 · SortSession：SCAN → PLAN → PICK 循环 → 完成/急停 的作业状态机。

状态机（``phase`` 字符串常量，全事件日志携带）::

    IDLE --scan()--> PLANNED --step()/run()--> PICKING --完成--> DONE
    任意时刻 --estop()--> ESTOPPED（闩锁，不可恢复，须新建 Session）
    PICKING --ArmError--> ERROR（计划中止，异常如实上抛）

PICK 单步动作序列（简报冻结）：移到上方（巡航高度）→ 下降（慢速到抓取面）
→ 夹取（夹爪闭合）→ 抬起（回巡航高度）→ 移到分级盒上方 → 松开。

安全包络（借鉴兄弟仓 cs_arm 的「一切指令过安全层」思路，按本线 v1 简化）：

- **工作空间边界校验**：Session 侧前置校验（拒绝在指令下发之前）+ 臂实现
  内部校验（纵深防御），两级一致使用 configs/sort.yaml 同一包络；
- **限速**：任何速度请求被钳制到 speeds.max_mm_s 硬上限内；接近段用慢速；
- **软件急停**：``estop()`` 闩锁 Session 并透传 ``arm.estop()``；每条运动
  指令前检查闩锁，闩锁中不再下发任何指令；
- **事件日志**：每步写内存事件列表（含时间戳/阶段/明细），可导出 JSON
  （含计划、臂事件、轨迹）供复盘与演示。
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Sequence

from pydantic import Field

from beaneye.acquisition.base import write_json
from beaneye.sort.arm import (
    ArmEStopError,
    ArmError,
    ArmProtocol,
    ArmWorkspaceError,
)
from beaneye.sort.config import SortConfig
from beaneye.sort.planner import PickStep, SortPlan, SortPlanner, SortTarget
from beaneye.schemas import BeanEyeBaseModel

__all__ = [
    "SessionError",
    "SessionEStopError",
    "PHASE_IDLE",
    "PHASE_PLANNED",
    "PHASE_PICKING",
    "PHASE_DONE",
    "PHASE_ESTOPPED",
    "PHASE_ERROR",
    "SessionReport",
    "SortSession",
]

# 状态机阶段常量（事件日志/导出 JSON 用字符串）
PHASE_IDLE = "idle"
PHASE_PLANNED = "planned"      # SCAN+PLAN 完成，待执行
PHASE_PICKING = "picking"
PHASE_DONE = "done"
PHASE_ESTOPPED = "estopped"
PHASE_ERROR = "error"


class SessionError(RuntimeError):
    """状态机用法错误（阶段不符 / 重复 scan 等）。"""


class SessionEStopError(SessionError):
    """急停闩锁中执行作业被拒绝（Session 已冻结在 ESTOPPED）。"""


class SessionReport(BeanEyeBaseModel):
    """一次作业的结果汇报。"""

    session_id: str
    status: str                       # done | estopped | error
    executed_steps: int = Field(ge=0)
    total_steps: int = Field(ge=0)
    per_bin_counts: dict[str, int]
    skipped_count: int = Field(ge=0)
    elapsed_s: float = Field(ge=0)


class SortSession:
    """一臂一计划的分拣作业会话（状态机 + 安全包络 + 事件日志）。"""

    def __init__(
        self,
        arm: ArmProtocol,
        planner: SortPlanner,
        *,
        config: SortConfig,
        session_id: str | None = None,
        now_fn=None,
    ) -> None:
        self._arm = arm
        self._planner = planner
        self._config = config
        self._session_id = session_id or f"sort_{uuid.uuid4().hex[:12]}"
        self._now = now_fn if now_fn is not None else time.perf_counter
        self._phase = PHASE_IDLE
        self._plan: SortPlan | None = None
        self._next_step = 0
        self._estop_latched = False
        self._events: list[dict] = []
        self._t0: float | None = None

    # ---- 只读视图 ------------------------------------------------------------

    @property
    def phase(self) -> str:
        return self._phase

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def plan(self) -> SortPlan | None:
        return self._plan

    @property
    def estop_latched(self) -> bool:
        return self._estop_latched

    @property
    def events(self) -> list[dict]:
        return [dict(e) for e in self._events]

    # ---- SCAN + PLAN ----------------------------------------------------------

    def scan(self, targets: Sequence[SortTarget]) -> SortPlan:
        """SCAN：取一帧逐粒检测结果 → PLAN：severity 降序生成抓取计划。"""
        if self._phase != PHASE_IDLE:
            raise SessionError(f"scan() 只能在 idle 阶段调用，当前 {self._phase}")
        if self._estop_latched:
            raise SessionEStopError("急停闩锁中，禁止新建计划")
        self._log("scan", {"targets": len(targets)})
        plan = self._planner.plan(targets)
        self._plan = plan
        self._next_step = 0
        self._phase = PHASE_PLANNED
        self._log("plan", {
            "steps": len(plan.steps),
            "skipped": len(plan.skipped),
            "per_bin": plan.per_bin_counts(),
        })
        return plan

    # ---- PICK 执行 ------------------------------------------------------------

    def step(self) -> bool:
        """执行计划中的下一抓取步；全部完成返回 False（阶段 → done）。

        急停闩锁中调用抛 :class:`SessionEStopError`；臂侧拒绝（越界/超速等）
        阶段转 error 并原样上抛 :class:`ArmError` 子类。
        """
        if self._estop_latched:
            raise SessionEStopError("急停闩锁中，作业已冻结（须新建 Session）")
        if self._phase == PHASE_DONE:
            return False
        if self._phase not in (PHASE_PLANNED, PHASE_PICKING):
            raise SessionError(f"step() 需要先 scan() 生成计划，当前 {self._phase}")
        assert self._plan is not None
        if self._next_step >= len(self._plan.steps):
            self._phase = PHASE_DONE
            self._log("done", {"executed": self._next_step})
            return False
        if self._phase == PHASE_PLANNED:
            self._phase = PHASE_PICKING
            self._t0 = self._now()
            self._log("picking_start", {"total_steps": len(self._plan.steps)})
        plan_step = self._plan.steps[self._next_step]
        try:
            self._pick_and_place(plan_step)
        except ArmEStopError:
            self._phase = PHASE_ESTOPPED
            self._log("estop_by_arm", {"order": plan_step.order})
            raise
        except ArmError as exc:
            self._phase = PHASE_ERROR
            self._log("error", {"order": plan_step.order, "error": str(exc)})
            raise
        self._next_step += 1
        self._log("pick_done", {
            "order": plan_step.order,
            "target": plan_step.target.target_id,
            "defect": plan_step.target.defect,
            "bin": plan_step.bin_name,
        })
        if self._next_step >= len(self._plan.steps):
            self._phase = PHASE_DONE
            self._log("done", {"executed": self._next_step})
            return False
        return True

    def run(self) -> SessionReport:
        """执行完整计划直至 done（急停/错误则冻结在对应阶段并上抛）。"""
        while self.step():
            pass
        return self.report("done")

    def report(self, status: str) -> SessionReport:
        """当前作业汇报（status: done | estopped | error）。"""
        assert self._plan is not None
        elapsed = (self._now() - self._t0) if self._t0 is not None else 0.0
        return SessionReport(
            session_id=self._session_id,
            status=status,
            executed_steps=self._next_step,
            total_steps=len(self._plan.steps),
            per_bin_counts=self._plan.per_bin_counts(),
            skipped_count=len(self._plan.skipped),
            elapsed_s=round(float(elapsed), 3),
        )

    # ---- 安全：软件急停 ---------------------------------------------------------

    def estop(self) -> None:
        """软件急停：闩锁 Session + 透传臂急停（安全路径永不抛错、幂等）。"""
        self._estop_latched = True
        try:
            self._arm.estop()
        finally:
            self._phase = PHASE_ESTOPPED
            self._log("estop", {"phase_before_frozen": True})

    # ---- 导出 -------------------------------------------------------------------

    def export_json(self, path: str | Path) -> Path:
        """导出复盘 JSON：会话元数据 + 计划 + Session/臂双侧事件 + 轨迹。"""
        assert self._plan is not None
        payload = {
            "schema": "beaneye.sort.session/v1",
            "session_id": self._session_id,
            "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "phase": self._phase,
            "estop_latched": self._estop_latched,
            "plan": self._plan.model_dump(mode="json"),
            "session_events": self.events,
            "arm_events": list(getattr(self._arm, "events", [])),
            "trajectory": list(getattr(self._arm, "trajectory", [])),
        }
        return write_json(path, payload)

    # ---- 内部：PICK 单步动作序列 -------------------------------------------------

    def _pick_and_place(self, s: PickStep) -> None:
        """移到上方 → 下降 → 夹取 → 抬起 → 移到分级盒上方 → 松开。"""
        sp = self._config.speeds
        max_s = sp.max_mm_s
        # 1) 移到抓取点上方（巡航高度平移）
        self._move(s.pick_x_mm, s.pick_y_mm, s.travel_z_mm, min(sp.travel_mm_s, max_s), "approach")
        # 2) 下降到抓取面（慢速）
        self._move(s.pick_x_mm, s.pick_y_mm, s.pick_z_mm, min(sp.descend_mm_s, max_s), "descend")
        # 3) 夹取
        self._estop_check()
        self._arm.gripper(False)
        self._log("gripper_close", {"order": s.order})
        # 4) 抬起
        self._move(s.pick_x_mm, s.pick_y_mm, s.travel_z_mm, min(sp.lift_mm_s, max_s), "lift")
        # 5) 移到分级盒上方
        self._move(s.bin_x_mm, s.bin_y_mm, s.travel_z_mm, min(sp.travel_mm_s, max_s), "transfer")
        # 6) 松开
        self._estop_check()
        self._arm.gripper(True)
        self._log("gripper_open", {"order": s.order, "bin": s.bin_name})

    def _move(self, x: float, y: float, z: float, speed: float, tag: str) -> None:
        """Session 侧前置校验（工作空间 + 限速钳制 + 急停）后再下发臂。

        前置越界拒绝抛 :class:`ArmWorkspaceError`（ArmError 家族）——语义是
        「拒绝产生运动」的安全拒绝，与臂内部校验同一类别，step() 会据此把
        会话冻结进 ERROR；:class:`SessionError` 只保留给状态机用法错误。
        """
        self._estop_check()
        ws = self._planner.workspace
        if not ws.contains(x, y, z):
            raise ArmWorkspaceError(
                f"[{tag}] 目标 ({x:.1f}, {y:.1f}, {z:.1f}) 超出工作空间包络——"
                "Session 前置校验拒绝（未下发臂）"
            )
        clamped = min(float(speed), self._config.speeds.max_mm_s)
        self._log(tag, {"to_mm": [x, y, z], "speed_mm_s": clamped})
        self._arm.move_to(x, y, z, speed=clamped)

    def _estop_check(self) -> None:
        if self._estop_latched:
            raise SessionEStopError("急停闩锁中：中断当前抓取步")

    def _log(self, event: str, detail: dict) -> None:
        self._events.append({
            "t_s": round(float(self._now()), 6),
            "session_id": self._session_id,
            "phase": self._phase,
            "event": event,
            "detail": detail,
        })
