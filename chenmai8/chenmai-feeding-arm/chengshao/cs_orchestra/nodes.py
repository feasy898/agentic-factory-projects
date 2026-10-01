"""行为树全节点与 tick 循环（开发指令 §5.6；状态转移表见 :mod:`.core`）。

树结构（py_trees，root=Selector 无记忆，全部节点按 ctx 相位幂等——被高优先级
分支打断/复位后原地恢复，进度只存在于 TickContext）::

    root(Selector)
    ├─ SafetyGate        急停闩锁 / 禁入区违规：立即停+切回 scene+本口 aborted，
    │                    急停等复位+resume/next；禁入区复位后后撤 5cm
    ├─ InteractionGate   吃饱了(done)收尾 / pause 悬停 / 转头·人脸丢失>1s 保持+播报
    │                    / 皱眉暂停+询问 / next 跳过等待 / select 换菜
    ├─ SessionGuard      餐已结束 -> SUCCESS（root 收敛，tick 循环退出）
    └─ meal(Sequence, 无记忆)
       ├─ SelectBowl     选碗（场景基准码/点菜映射）-> 黑板 bowl_sel
       ├─ Scoop          舀取：脚本参数化轨迹+腕部闭环，空勺经 SpoonCheckGate 回流重舀
       ├─ SpoonCheckGate 勺上检查：过->DELIVER；不过且有重试->SCOOP；耗尽->本口 retry
       ├─ Deliver        送达：入场沿 camera_role scene->wrist_mouth（delivery_entry），
       │                 曝光稳定窗后采信口部帧；限速逼近包络送达停点（口前 5cm 叙事）
       ├─ WaitBite       等待咬合：WAIT_OPEN（jaw_open>0.35 张嘴）-> WAIT_BITE（jaw 回落）
       ├─ SpoonEmptyConfirm 勺空确认（复检限次）
       ├─ Retract        撤回：完成沿 camera_role wrist_mouth->scene（retract_complete）
       └─ RecordBite     写 BiteRecord（依赖注入 sink；黑板 session 同步）

行为树对舀取策略的交互（ScriptedScoop/学习型策略延后接入时对齐同一交互，
不重构契约）：``plan_round(round, bowl_pos, bite_idx)`` 给出路线项列表；
``on_round_complete(round)`` 行程结果通知（世界侧"勺上是否有食物"在 mock 由
此驱动）；``on_spoon_check(check)`` 吃进勺检结果并回答是否接受为有食物；
``retries_left()`` 剩余重舀次数。
"""

from __future__ import annotations

import numpy as np
from py_trees.behaviour import Behaviour
from py_trees.common import Status
from py_trees.composites import Selector, Sequence

try:  # 仓库根运行与包根运行双形态
    from chengshao.cs_orchestra.core import (
        BitePhase,
        RouteFollower,
        WRIST_PHASES,
        retract_route_items,
    )
    from chengshao.cs_schema import (
        DEFAULT_DISH_REGISTRY,
        BiteOutcome,
        CameraRole,
        FROWN_ASK_THRESHOLD,
        HEAD_YAW_TURN_THRESHOLD_RAD,
        JAW_OPEN_THRESHOLD,
        MealSession,
        SpoonCheck,
        ViolationKind,
    )
except ImportError:  # pragma: no cover - 包根直跑形态
    from cs_orchestra.core import (  # type: ignore[no-redef]
        BitePhase,
        RouteFollower,
        WRIST_PHASES,
        retract_route_items,
    )
    from cs_schema import (  # type: ignore[no-redef]
        DEFAULT_DISH_REGISTRY,
        BiteOutcome,
        CameraRole,
        FROWN_ASK_THRESHOLD,
        HEAD_YAW_TURN_THRESHOLD_RAD,
        JAW_OPEN_THRESHOLD,
        MealSession,
        SpoonCheck,
        ViolationKind,
    )

# 张嘴闭合判定阈值（jaw_open 回落到此以下视为咬合完成；schema 冻结常量只定义
# 张嘴阈值 0.35，闭合滞后阈值属编排层参数，此处冻结为常数并写入状态转移表）
JAW_CLOSED_THRESHOLD = 0.20

_ANNOUNCE = {
    "estop": "急停！我已停止运动。",
    "zone": "检测到禁入区侵入，已停止，请勿靠近手臂。",
    "pause": "好的，我先停住。",
    "resume": "好的，继续。",
    "turn": "您好像转开了，我在原地等您。",
    "frown": "怎么了？如果不舒服请告诉我，我先暂停。",
    "done": "好的，本次用餐到这里，我撤回手臂。祝您愉快。",
    "meal_over": "本次进餐结束啦，辛苦啦。",
}


# ---- 主序列节点基类（相位幂等） ------------------------------------------------


class _PhaseNode(Behaviour):
    """按 BitePhase 门控的节点：口外/已过/未到阶段一律 SUCCESS，活动相位走 _work。

    多相位节点（WaitBite 覆盖 WAIT_OPEN+WAIT_BITE）声明 PHASES 元组；
    相位落在此窗口内即进入 _work（_work 内自行分派具体相位）。
    """

    PHASES: tuple[BitePhase, ...] = ()

    def __init__(self, ctx) -> None:
        super().__init__(self.__class__.__name__)
        self.ctx = ctx

    def update(self) -> Status:
        b = self.ctx.bite
        if b is None or self.ctx.meal_finished:
            return Status.SUCCESS
        vals = [p.value for p in self.PHASES]
        if b.phase.value > max(vals) or b.phase.value < min(vals):
            return Status.SUCCESS
        return self._work(b)

    def _work(self, b) -> Status:  # pragma: no cover - 子类必须实现
        raise NotImplementedError

    # -- 公共小件 ---------------------------------------------------------------
    def _route_done(self, b) -> str | None:
        """推进 b.route；返回 None=在途（RUNNING），"ok"=完成，"fail"=被拒。"""
        if b.route is None:
            return "ok"
        if not b.route.tick():
            return None
        if b.route.failed is not None:
            self.ctx.unexpected_failures.append(f"{self.name}:{b.route.failed}")
            self.ctx.abort_current_bite(BiteOutcome.ABORTED, "route_rejected")
            return "fail"
        b.last_route_journal = [q.copy() for q in b.route.journal]
        b.route = None
        return "ok"


# ---- 打断分支 1：安全闸 ---------------------------------------------------------


class SafetyGate(Behaviour):
    """软件急停 / 禁入区违规（开发指令 §5.6 打断分支，最高优先级）。

    急停：闩锁即响应（停臂 + camera_role->scene(estop_abort) + 本口 aborted +
    播报），保持 RUNNING 直到包络复位且收到 resume/next；禁入区：闩锁即响应，
    复位后恢复。复位后的"后撤"= 原路退回：逆序回放被中止路线的前向关节路径
    （完整撤出送达走廊，覆盖 §5.6"后撤 5cm"的安全意图，且不进入未知位形区），
    再补一记回家笛卡尔腿。TCP 仍在禁入区内时复位会被包络如实重新闩锁
    （clear_to_move 不会变真），闸保持 RUNNING；恢复路线若被包络拒绝则如实
    记 trace 并放行恢复（不阻塞会话收敛）。
    """

    def __init__(self, ctx) -> None:
        super().__init__(self.__class__.__name__)
        self.ctx = ctx

    def update(self) -> Status:
        ctx = self.ctx
        if ctx.meal_finished:
            return Status.FAILURE  # 餐已结束：安全闸不再阻断收敛（事件照记 trace）
        safety = ctx.bb.get("safety")
        if safety is None:
            return Status.FAILURE
        estop = bool(safety.estop_latched)
        zone = (safety.violation is ViolationKind.FACE_IN_ZONE
                or bool(safety.human_zone_violation))
        # 恢复中途（闸已入场）即使包络被复位也要继续走完"后撤+回家"再收敛
        if not (estop or zone) and not (ctx.estop_entered or ctx.zone_entered):
            return Status.FAILURE

        # ---- 入场（一次性）：停臂 + 切回 scene + 本口 aborted + 播报 ----------
        entered = ctx.estop_entered or ctx.zone_entered
        reason = "estop" if estop else "zone"
        if not entered:
            ctx.trace.add(f"{reason}_detected", ts_ns=ctx.now_ns())
            ctx.abort_current_bite(BiteOutcome.ABORTED, reason)
            ctx.say(_ANNOUNCE[reason], reason)
            ctx.estop_entered = estop
            ctx.zone_entered = zone
            ctx.zone_retreat = None

        # ---- 复位：急停由操作员 reset；禁入区闸自行尝试（TCP 离区才生效） ----
        if zone and not safety.clear_to_move:
            ctx.env.reset()  # 包络 reset 自带复查：仍在区内会如实重新闩锁
        ss = ctx.env.safety_state()
        if not ss.clear_to_move:
            return Status.RUNNING  # 等 reset（操作员/侵入解除）

        # ---- 复位后后撤（§5.6：立即停+后撤）+ 沿来路原路退回家 ----------------
        # 后撤语义：原路退回（逆序回放被中止路线的前向关节路径）——完整撤出
        # 送达走廊（远超 5cm），且每一段都是去程已过包络的返向，不进入
        # 未知位形区；退回终点为走廊起点，再补一记回家笛卡尔腿。
        if ctx.zone_retreat is None:
            items: list = []
            if ctx.aborted_journal:
                items.append(("jtrack_seq",
                              [q.copy() for q in reversed(ctx.aborted_journal)],
                              ctx.params.jtrack_replay_speed_rad_s))
            items.append(("cart", np.asarray(ctx.params.home_point_m, dtype=float),
                          ctx.params.cruise_speed_mps, ctx.params.route_step_m))
            ctx.zone_retreat = RouteFollower(ctx, items, label="safety_retreat")
            ctx.trace.add("safety_retreat_start", ts_ns=ctx.now_ns(), reason=reason)
        if not ctx.zone_retreat.tick():
            return Status.RUNNING
        if ctx.zone_retreat.failed is not None:
            # 恢复路线被拒（不应发生）：如实记录，不再阻塞会话收敛
            ctx.trace.add("safety_retreat_failed", ts_ns=ctx.now_ns(),
                          reason=ctx.zone_retreat.failed)
            ctx.zone_retreat = None

        # ---- 撤回完成：等"继续/下一口"恢复下口 --------------------------------
        if ctx.take_recovering_intent() is not None:
            ctx.estop_entered = False
            ctx.zone_entered = False
            ctx.zone_retreat = None
            ctx.aborted_journal = None
            ctx.trace.add("safety_recovered", ts_ns=ctx.now_ns(), reason=reason)
            return Status.FAILURE
        return Status.RUNNING


# ---- 打断分支 2：交互闸 ---------------------------------------------------------


class InteractionGate(Behaviour):
    """语音/表情/转头交互闸（§5.6 打断分支）。

    done 收尾（terminal）：本口记 rejected -> 撤回（完成沿切回 scene，
    done_retract）-> 会话结束 -> SUCCESS（永久阻断主序列，餐收敛）。
    其余为持续型：pause 悬停 / 转头·人脸丢失>1s 保持 / 皱眉暂停询问 /
    next 跳过等待 / select 换菜——激活时 RUNNING（主序列停发新指令段，
    在途段自然完成=保持），解除后 FAILURE 原地续跑。
    """

    def __init__(self, ctx) -> None:
        super().__init__(self.__class__.__name__)
        self.ctx = ctx

    def update(self) -> Status:
        ctx = self.ctx
        # ---- done：吃饱了（任何时刻，terminal） -------------------------------
        if not ctx.done_shutdown and ctx.take_intent("done") is not None:
            ctx.done_shutdown = True
            ctx.env.halt()
            ctx.say(_ANNOUNCE["done"], "done")
            if ctx.bite is not None:
                b = ctx.bite
                b.phase = BitePhase.RETRACT
                b.route = None
                b.delivered = b.delivered or b.delivery_entered
            done_items = retract_route_items(ctx.bite, ctx.params,
                                             ctx.validator.delivery_stop_point())
            done_items.append(("grip", ctx.params.gripper_open, 0.8))
            ctx.shutdown_route = RouteFollower(ctx, done_items, label="done_retract")
            ctx.trace.add("done_shutdown", ts_ns=ctx.now_ns())
        if ctx.done_shutdown:
            r = ctx.shutdown_route
            if r is not None and not r.tick():
                return Status.RUNNING
            if r is not None and r.failed is not None:
                ctx.unexpected_failures.append(f"done_retract:{r.failed}")
            if ctx.camera_role is CameraRole.WRIST_MOUTH:
                ctx.ledger.switch(ctx, CameraRole.SCENE, "done_retract")
            if ctx.bite is not None:
                ctx.close_bite(BiteOutcome.REJECTED)
            session = ctx.session
            if session is not None and session.ended_ns is None:
                session.ended_ns = ctx.now_ns()
            if ctx.deps.sink is not None:
                ctx.deps.sink.end_session()
            ctx.meal_finished = True
            ctx.bb_set("session", session)
            ctx.trace.add("meal_ended", ts_ns=ctx.now_ns(), reason="done")
            return Status.SUCCESS

        if ctx.meal_finished:
            return Status.SUCCESS

        # ---- pause / resume ---------------------------------------------------
        if ctx.take_intent("pause") is not None:
            ctx.pause_active = True
            ctx.say(_ANNOUNCE["pause"], "pause")
        if ctx.pause_active:
            if ctx.take_intent("resume") is not None:
                ctx.pause_active = False
                ctx.say(_ANNOUNCE["resume"], "resume")
            else:
                return Status.RUNNING

        # ---- next：仅"等待咬合"两阶段生效（跳过等待，本口按拒食撤回） --------
        nxt = ctx.take_intent("next")
        if nxt is not None:
            b = ctx.bite
            if b is not None and b.phase in (BitePhase.WAIT_OPEN, BitePhase.WAIT_BITE):
                b.skip_wait = True
                b.outcome = BiteOutcome.REJECTED
                b.phase = BitePhase.RETRACT
                b.route = None
                ctx.trace.add("next_skip_wait", ts_ns=ctx.now_ns(), bite=b.idx)
            else:
                ctx.trace.add("next_ignored", ts_ns=ctx.now_ns())

        # ---- select：换菜（记录偏好，下口选碗生效） ---------------------------
        sel = ctx.take_intent("select")
        if sel is not None:
            dish = (sel.slots or {}).get("dish")
            ctx.requested_dish = dish
            ctx.trace.add("dish_selected", ts_ns=ctx.now_ns(), dish=dish)

        # 消费其余意图（greet/unknown：记录不动作）
        for kind in ("greet", "unknown"):
            if ctx.take_intent(kind) is not None:
                ctx.trace.add(f"{kind}_ignored", ts_ns=ctx.now_ns())

        # ---- 转头 / 人脸丢失 >1s（仅腕部角色的送达/等待阶段） -----------------
        status = self._turn_hold_status()
        if status is not None:
            return status

        # ---- 皱眉 > 阈值：暂停 + 询问 ----------------------------------------
        status = self._frown_status()
        if status is not None:
            return status

        return Status.FAILURE

    # -- 内部 -------------------------------------------------------------------
    def _wrist_phase(self) -> bool:
        b = self.ctx.bite
        return (b is not None and b.phase in WRIST_PHASES
                and self.ctx.camera_role is CameraRole.WRIST_MOUTH)

    def _turn_hold_status(self) -> Status | None:
        ctx = self.ctx
        if not self._wrist_phase():
            ctx.turn_since_ns = None
            if ctx.turn_hold:
                ctx.turn_hold = False
                ctx.trace.add("turn_recovered", ts_ns=ctx.now_ns())
            return None
        mouth = ctx.bb.get("mouth")
        now = ctx.now_ns()
        lost = (mouth is None or not bool(mouth.valid)
                or abs(float(mouth.head_yaw)) > HEAD_YAW_TURN_THRESHOLD_RAD)
        if lost:
            if ctx.turn_since_ns is None:
                ctx.turn_since_ns = now
            sustain_ns = int(ctx.params.turn_sustain_s * 1e9)
            if now - ctx.turn_since_ns >= sustain_ns:
                if not ctx.turn_hold:
                    ctx.turn_hold = True
                    ctx.say(_ANNOUNCE["turn"], "turn")
                return Status.RUNNING  # 保持：主序列不再下发新指令段
            return None  # 持续判定窗内：暂不打断
        ctx.turn_since_ns = None
        if ctx.turn_hold:
            ctx.turn_hold = False
            ctx.trace.add("turn_recovered", ts_ns=ctx.now_ns())
        return None

    def _frown_status(self) -> Status | None:
        ctx = self.ctx
        if not self._wrist_phase():
            if ctx.frown_hold:
                ctx.frown_hold = False
                ctx.trace.add("frown_cleared", ts_ns=ctx.now_ns())
            return None
        mouth = ctx.bb.get("mouth")
        frowning = mouth is not None and bool(mouth.valid) and \
            float(mouth.frown) > FROWN_ASK_THRESHOLD
        if frowning:
            if not ctx.frown_hold:
                ctx.frown_hold = True
                ctx.say(_ANNOUNCE["frown"], "frown")
            # resume 可解除（frown 未落也要能继续）
            if ctx.take_intent("resume") is not None:
                ctx.frown_hold = False
                ctx.say(_ANNOUNCE["resume"], "resume")
                ctx.trace.add("frown_cleared", ts_ns=ctx.now_ns())
                return None
            return Status.RUNNING
        if ctx.frown_hold:
            ctx.frown_hold = False
            ctx.trace.add("frown_cleared", ts_ns=ctx.now_ns())
        return None


# ---- 分支 3：会话收敛 -----------------------------------------------------------


class SessionGuard(Behaviour):
    """餐结束（done 收尾或到达口数上限）-> SUCCESS，root 收敛退出 tick 循环。"""

    def __init__(self, ctx) -> None:
        super().__init__(self.__class__.__name__)
        self.ctx = ctx

    def update(self) -> Status:
        return Status.SUCCESS if self.ctx.meal_finished else Status.FAILURE


# ---- 主序列 ---------------------------------------------------------------------


class SelectBowl(Behaviour):
    """选碗 + 开口：写黑板 bowl_sel；点菜偏好（select 意图）优先于场景扫描。

    本节点兼负"开新口"职责（唯一在 bite=None 时动作的节点）：
    到达额定口数则自然收尾（播报+会话结束），否则开新口再选碗。
    """

    def __init__(self, ctx) -> None:
        super().__init__(self.__class__.__name__)
        self.ctx = ctx

    def update(self) -> Status:
        ctx = self.ctx
        b = ctx.bite
        if b is None:
            if ctx.meal_finished:
                return Status.SUCCESS
            if len(ctx.bites_done) >= ctx.max_bites:
                session = ctx.session
                if session is not None and session.ended_ns is None:
                    session.ended_ns = ctx.now_ns()
                if ctx.deps.sink is not None:
                    ctx.deps.sink.end_session()
                ctx.say(_ANNOUNCE["meal_over"], "meal_over")
                ctx.meal_finished = True
                ctx.bb_set("session", session)
                ctx.trace.add("meal_ended", ts_ns=ctx.now_ns(), reason="max_bites")
                return Status.RUNNING
            b = ctx.open_bite()
        if b.phase is not BitePhase.SELECT_BOWL:
            return Status.SUCCESS  # 已选完（幂等重入）
        dish = ctx.requested_dish
        bowl: int | None = None
        if dish:
            registry = tuple(DEFAULT_DISH_REGISTRY)
            if dish in registry:
                bowl = registry.index(dish) % len(ctx.params.bowls_m())
        if bowl is None:
            bowl = ctx.deps.scene.select_bowl() if ctx.deps.scene is not None else None
        if bowl is None:
            return Status.RUNNING  # 场景未见登记码：下一 tick 重扫
        b.bowl_index = int(bowl)
        b.bowl_pos_m = ctx.params.bowls_m()[int(bowl)]
        ctx.bb_set("bowl_sel", b.bowl_index)
        ctx.trace.add("bowl_selected", ts_ns=ctx.now_ns(), bite=b.idx,
                      bowl=b.bowl_index, dish=dish)
        b.phase = BitePhase.SCOOP
        return Status.RUNNING


class Scoop(_PhaseNode):
    """舀取：脚本参数化轨迹 + 腕部检查闭环。

    发起一轮行程（首轮，或 SpoonCheckGate 重舀回流后的新一轮），行程完成后
    交棒勺上检查节点（phase=SPOON_CHECK）——重舀决策权在检查节点。
    """

    PHASES = (BitePhase.SCOOP,)

    def _work(self, b) -> Status:
        ctx = self.ctx
        if b.route is not None:
            done = self._route_done(b)
            if done == "fail":
                return Status.FAILURE
            if done is None:
                return Status.RUNNING
            b.phase = BitePhase.SPOON_CHECK  # 行程完成 -> 勺上检查
            return Status.RUNNING
        # 发起新一轮舀取行程（首轮 / 重舀回流）
        b.scoop_round += 1
        items = ctx.deps.scoop.plan_round(b.scoop_round, b.bowl_pos_m, b.idx)
        b.route = RouteFollower(ctx, items, label=f"scoop_r{b.scoop_round}")
        ctx.trace.add("scoop_round", ts_ns=ctx.now_ns(), bite=b.idx,
                      round=b.scoop_round)
        return Status.RUNNING


class SpoonCheckGate(_PhaseNode):
    """勺上检查：过 -> 送达；不过且有重试 -> 回 SCOOP；耗尽 -> 本口 retry 撤回。"""

    PHASES = (BitePhase.SPOON_CHECK,)

    def _work(self, b) -> Status:
        ctx = self.ctx
        ctx.deps.scoop.on_round_complete(b.scoop_round)  # 先通知行程结果（世界侧）
        check = ctx.deps.spoon.check()
        b.spoon_checks += 1
        ctx.bb_set("spoon", check)
        has_food = bool(check.has_food)
        accepted = ctx.deps.scoop.on_spoon_check(check)
        ctx.trace.add("spoon_check", ts_ns=int(check.ts_ns), bite=b.idx,
                      round=b.scoop_round, has_food=has_food,
                      score=round(float(check.score), 4), accepted=bool(accepted))
        if accepted and has_food:
            b.phase = BitePhase.DELIVER
            return Status.RUNNING
        if b.scoop_round - 1 < ctx.params.scoop_retries_max:
            b.phase = BitePhase.SCOOP  # 重舀回流
            return Status.RUNNING
        # 重试耗尽：本口按 retry 记录，未进送达（camera_role 保持 scene）
        b.outcome = BiteOutcome.RETRY
        b.phase = BitePhase.RETRACT
        b.route = None
        ctx.trace.add("scoop_exhausted", ts_ns=ctx.now_ns(), bite=b.idx,
                      rounds=b.scoop_round)
        return Status.RUNNING


class Deliver(_PhaseNode):
    """送达：入场沿切 wrist_mouth；曝光稳定窗后采信口部帧；限速逼近停点。"""

    PHASES = (BitePhase.DELIVER,)

    def _work(self, b) -> Status:
        ctx = self.ctx
        if not b.delivery_entered:
            b.delivery_entered = True
            b.delivered = True
            ctx.ledger.switch(ctx, CameraRole.WRIST_MOUTH, "delivery_entry")
            b.settle_until_ns = ctx.now_ns() + int(ctx.params.exposure_settle_s * 1e9)
            stop = np.asarray(ctx.validator.delivery_stop_point(), dtype=float)
            pre = stop + np.array([-float(ctx.params.stop_approach_offset_m), 0.0, 0.0])
            items = [
                ("cart", np.asarray(v, dtype=float),
                 ctx.params.cruise_speed_mps, ctx.params.route_step_m)
                for v in ctx.params.delivery_vias_for(b.bowl_index)
            ]
            items += [
                ("cart", pre, ctx.params.cruise_speed_mps, ctx.params.route_step_m),
                ("cart", stop, ctx.params.approach_speed_mps, ctx.params.final_step_m),
            ]
            b.route = RouteFollower(ctx, items, label="deliver")
            ctx.trace.add("delivery_entry", ts_ns=ctx.now_ns(), bite=b.idx,
                          settle_s=ctx.params.exposure_settle_s)
            return Status.RUNNING
        # 曝光稳定窗：切换后 <settle 的口部帧不采信（通道侧返回失效帧）
        if ctx.now_ns() < b.settle_until_ns:
            return Status.RUNNING
        done = self._route_done(b)
        if done == "fail":
            return Status.FAILURE
        if done is None:
            return Status.RUNNING
        # 到位校验
        stop = np.asarray(ctx.validator.delivery_stop_point(), dtype=float)
        tcp = np.asarray(ctx.arm_state().ee_pos, dtype=float)
        err = float(np.linalg.norm(tcp - stop))
        if err > ctx.params.arrive_tolerance_m:
            ctx.unexpected_failures.append(f"deliver_arrive:{err:.4f}")
            ctx.abort_current_bite(BiteOutcome.ABORTED, "arrive_error")
            return Status.FAILURE
        b.delivered_ns = ctx.now_ns()
        mouth = ctx.bb.get("mouth")
        if mouth is not None and bool(mouth.valid):
            face = np.asarray(ctx.validator.config.face_center, dtype=float)
            b.aim_offset_m = float(np.linalg.norm(
                np.asarray([mouth.x, mouth.y]) - face[:2]))
        ctx.trace.add("delivered", ts_ns=ctx.now_ns(), bite=b.idx,
                      err_m=round(err, 5),
                      aim_offset_m=(None if b.aim_offset_m is None
                                    else round(b.aim_offset_m, 4)))
        b.phase = BitePhase.WAIT_OPEN
        return Status.RUNNING


class WaitBite(_PhaseNode):
    """等待咬合：WAIT_OPEN 张嘴 -> WAIT_BITE 咬合（jaw 回落）。

    闭嘴等待超时 / "下一口"跳过：本口 rejected 走撤回。
    """

    PHASES = (BitePhase.WAIT_OPEN, BitePhase.WAIT_BITE)

    def _work(self, b) -> Status:
        ctx = self.ctx
        if b.phase is BitePhase.WAIT_OPEN:
            if b.skip_wait:
                return Status.RUNNING  # outcome 已置；撤回节点接管
            if ctx.now_ns() - b.delivered_ns > int(ctx.params.wait_bite_timeout_s * 1e9):
                b.outcome = BiteOutcome.REJECTED
                b.phase = BitePhase.RETRACT
                b.route = None
                ctx.trace.add("wait_bite_timeout", ts_ns=ctx.now_ns(), bite=b.idx)
                return Status.RUNNING
            mouth = ctx.bb.get("mouth")
            if (mouth is not None and bool(mouth.valid)
                    and float(mouth.jaw_open) > JAW_OPEN_THRESHOLD):
                b.open_seen = True
                b.phase = BitePhase.WAIT_BITE
                b.delivered_ns = ctx.now_ns()  # 复用为张嘴时刻（超时基准）
                ctx.trace.add("mouth_opened", ts_ns=ctx.now_ns(), bite=b.idx,
                              jaw_open=round(float(mouth.jaw_open), 3))
            return Status.RUNNING
        # WAIT_BITE
        if b.skip_wait:
            return Status.RUNNING
        if ctx.now_ns() - b.delivered_ns > int(ctx.params.wait_bite_timeout_s * 1e9):
            b.outcome = BiteOutcome.REJECTED
            b.phase = BitePhase.RETRACT
            b.route = None
            ctx.trace.add("wait_bite_timeout", ts_ns=ctx.now_ns(), bite=b.idx)
            return Status.RUNNING
        mouth = ctx.bb.get("mouth")
        if (mouth is not None and bool(mouth.valid)
                and float(mouth.jaw_open) < JAW_CLOSED_THRESHOLD):
            ctx.trace.add("jaw_closed", ts_ns=ctx.now_ns(), bite=b.idx)
            b.phase = BitePhase.SPOON_EMPTY
        return Status.RUNNING


class SpoonEmptyConfirm(_PhaseNode):
    """勺空确认：咬合后勺上无食物才撤回；仍见食物按限次复检后按拒食处理。"""

    PHASES = (BitePhase.SPOON_EMPTY,)

    def _work(self, b) -> Status:
        ctx = self.ctx
        waiting = (b.empty_rechecks > 0 and ctx.now_ns() - b.last_empty_check_ns
                   < int(ctx.params.spoon_recheck_interval_s * 1e9))
        if waiting:
            return Status.RUNNING
        check = ctx.deps.spoon.check()
        b.spoon_checks += 1
        b.empty_rechecks += 1
        b.last_empty_check_ns = ctx.now_ns()
        ctx.bb_set("spoon", check)
        ctx.trace.add("spoon_empty_check", ts_ns=int(check.ts_ns), bite=b.idx,
                      has_food=bool(check.has_food),
                      score=round(float(check.score), 4))
        if not bool(check.has_food):
            b.phase = BitePhase.RETRACT
            return Status.RUNNING
        if b.empty_rechecks >= ctx.params.spoon_empty_rechecks:
            b.outcome = BiteOutcome.REJECTED
            b.phase = BitePhase.RETRACT
            b.route = None
            ctx.trace.add("spoon_not_empty", ts_ns=ctx.now_ns(), bite=b.idx)
        return Status.RUNNING


class Retract(_PhaseNode):
    """撤回：完成沿切回 scene（retract_complete）；未进送达的口无角色切换。"""

    PHASES = (BitePhase.RETRACT,)

    def _work(self, b) -> Status:
        ctx = self.ctx
        if b.route is None:
            items = retract_route_items(b, ctx.params,
                                        ctx.validator.delivery_stop_point())
            items.append(("grip", ctx.params.gripper_open, 0.8))
            b.route = RouteFollower(ctx, items, label="retract")
            return Status.RUNNING
        done = self._route_done(b)
        if done == "fail":
            return Status.FAILURE
        if done is None:
            return Status.RUNNING
        if ctx.camera_role is CameraRole.WRIST_MOUTH:
            ctx.ledger.switch(ctx, CameraRole.SCENE, "retract_complete")
        ctx.trace.add("retracted", ts_ns=ctx.now_ns(), bite=b.idx)
        b.phase = BitePhase.RECORD
        return Status.RUNNING


class RecordBite(_PhaseNode):
    """写 BiteRecord（注入 sink）+ 黑板 session 同步；下一 tick 开新口。"""

    PHASES = (BitePhase.RECORD,)

    def _work(self, b) -> Status:
        outcome = b.outcome if b.outcome is not None else BiteOutcome.SUCCESS
        self.ctx.close_bite(outcome)
        return Status.RUNNING


# ---- 树装配与 tick 循环 ---------------------------------------------------------


def build_tree(ctx):
    """装配行为树（root=Selector：SafetyGate -> InteractionGate -> SessionGuard
    -> meal 序列）。"""
    meal = Sequence(
        name="meal",
        memory=False,
        children=[
            SelectBowl(ctx),
            Scoop(ctx),
            SpoonCheckGate(ctx),
            Deliver(ctx),
            WaitBite(ctx),
            SpoonEmptyConfirm(ctx),
            Retract(ctx),
            RecordBite(ctx),
        ],
    )
    root = Selector(
        name="root",
        memory=False,
        children=[SafetyGate(ctx), InteractionGate(ctx), SessionGuard(ctx), meal],
    )
    return root


class MealRunner:
    """50Hz tick 循环：推进虚拟时钟 -> 刷新黑板 -> tick 树，直至餐收敛/超时。"""

    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.root = build_tree(ctx)
        # 黑板冻结键初始化（§3.2/§5.6：mouth/arm_state/safety/spoon/intent/
        # session/bowl_sel/camera_role）
        ctx.bb_set("camera_role", ctx.camera_role)
        ctx.bb_set("spoon", SpoonCheck(ts_ns=ctx.now_ns(), has_food=False,
                                       score=0.0, cam_ref="wrist_cam"))
        ctx.bb_set("intent", None)
        ctx.bb_set("bowl_sel", None)
        ctx.bb_set("session", None)
        self.ticks = 0

    def _poll(self) -> None:
        ctx = self.ctx
        safety = ctx.env.poll()
        ctx.bb_set("safety", safety)
        state = ctx.arm_state()
        ctx.bb_set("arm_state", state)
        if ctx.session is None:
            session_id = ctx.user_id
            if ctx.deps.sink is not None:
                session_id = ctx.deps.sink.start_session(ctx.user_id)
            ctx.session = MealSession(
                session_id=str(session_id), user_id=ctx.user_id,
                started_ns=ctx.now_ns(), ended_ns=None, bites=[], total_grams=None)
            ctx.bb_set("session", ctx.session)
        ctx.sample_mouth()
        intent = None
        if ctx.deps.voice is not None:
            intent = ctx.deps.voice.poll()
        if intent is not None:
            ctx.bb_set("intent", intent)
            ctx.last_intent = intent
            ctx.pending_intents.append(intent)
            ctx.trace.add("voice_intent", ts_ns=int(intent.ts_ns),
                          intent=str(intent.intent),
                          slots=dict(intent.slots or {}),
                          confidence=round(float(intent.confidence), 3))

    def run(self, driver=None) -> dict:
        """跑完一餐；返回运行摘要（timeout=True 表示超出仿真时长上限）。"""
        ctx = self.ctx
        max_ticks = int(ctx.params.max_meal_sim_s / ctx.params.tick_s)
        timeout = False
        for _ in range(max_ticks):
            ctx.clock.advance_s(ctx.params.tick_s)
            self._poll()
            self.root.tick_once()
            self.ticks += 1
            if driver is not None:
                driver.on_tick(ctx, self.ticks)
            if self.root.status is Status.SUCCESS:
                break
        else:
            timeout = True
            ctx.trace.add("meal_timeout", ts_ns=ctx.now_ns())
        ctx.trace.dump()
        session = ctx.session
        return {
            "timeout": timeout,
            "ticks": self.ticks,
            "sim_s": round(ctx.now_ns() / 1e9, 3),
            "bites": len(ctx.bites_done),
            "outcomes": [str(r.outcome) for r in ctx.bites_done],
            "session_id": None if session is None else session.session_id,
            "session_ended": bool(session is not None and session.ended_ns is not None),
            "camera_role": str(ctx.camera_role),
            "unexpected_failures": list(ctx.unexpected_failures),
        }
