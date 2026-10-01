"""cs_orchestra 跨模块测试：状态转移表 / camera_role 台账 / 注入行为（§5.6）。

运行（仓库根）::

    python -m pytest tests/test_orchestra.py -q

无硬件依赖（MockArm + SafetyEnvelope + 脚本化用户/场景/勺检/语音/记录池）。
核心断言：
- 状态转移表在模块 docstring 冻结且阶段/相机角色映射一致；
- camera_role 台账：进送达的口恰 2 次切换（delivery_entry + retract/abort），
  未进送达的口 0 次，重复切换被拒；
- 急停：本口 aborted + 切回 scene + 复位后原路退回 + resume 恢复下口；
- 禁入区：同上（zone_abort），恢复后餐继续；
- 空勺重舀：重试命中则正常送达；耗尽则本口 retry、不进送达（0 次切换）；
- 吃饱了：本口 rejected + 会话收敛（done_retract 切回 scene）；
- 黑板 8 个冻结键全程可读。
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from py_trees.blackboard import Blackboard

from chengshao.cs_orchestra.core import (
    BitePhase,
    CameraRoleLedger,
    OrchestraParams,
    STATE_TRANSITION_TABLE,
    WRIST_PHASES,
)
from chengshao.cs_orchestra.mock import (
    MemorySink,
    MockScoop,
    make_mock_episode,
)
from chengshao.cs_schema import CameraRole
from chengshao.cs_sim import EnvelopeValidator, load_arm


# ---------------------------------------------------------------------------
# 夹具（模型/校验器全模块共享，降低装载开销）
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def model():
    return load_arm("auto")


@pytest.fixture(scope="module")
def validator():
    return EnvelopeValidator()


@pytest.fixture(scope="module")
def params():
    return OrchestraParams.load()


def _run(script: dict, bites: int, params, model, validator):
    ns = make_mock_episode(episode=1, script=script, bites=bites, params=params,
                           model=model, validator=validator)
    summary = ns.runner.run(ns.driver)
    return ns, summary


def _switch_reasons(ledger, bite_idx: int) -> list[str]:
    return [s["reason"] for s in ledger.for_bite(bite_idx)]


# ---------------------------------------------------------------------------
# 状态转移表（模块 docstring 冻结；开发指令 §5.6 要求 tests 断言）
# ---------------------------------------------------------------------------


def test_state_transition_table_frozen_in_docstring():
    """状态转移表必须在 core docstring 冻结，且覆盖主序列与全部打断分支。"""
    assert "SELECT_BOWL" in STATE_TRANSITION_TABLE
    for kw in ("SCOOP", "SPOON_CHECK", "DELIVER", "WAIT_OPEN", "WAIT_BITE",
               "SPOON_EMPTY", "RETRACT", "RECORD"):
        assert kw in STATE_TRANSITION_TABLE, kw
    # 打断分支触发词（§5.6 全集；表为中文语境 + 契约英文字面量混排）
    for kw in ("estop", "zone_abort", "人脸丢失", "转头", "pause", "resume",
               "done", "next", "frown", "select", "retry", "camera_role"):
        assert kw in STATE_TRANSITION_TABLE, kw


def test_bite_phase_order_matches_table():
    """阶段枚举顺序 = 主序列状态转移表；wrist 角色窗口与表一致。"""
    order = [p.name for p in BitePhase]
    assert order == ["IDLE", "SELECT_BOWL", "SCOOP", "SPOON_CHECK", "DELIVER",
                     "WAIT_OPEN", "WAIT_BITE", "SPOON_EMPTY", "RETRACT", "RECORD"]
    assert WRIST_PHASES == frozenset({
        BitePhase.DELIVER, BitePhase.WAIT_OPEN, BitePhase.WAIT_BITE,
        BitePhase.SPOON_EMPTY})


# ---------------------------------------------------------------------------
# camera_role 台账（v3.1：每口恰 2 次）
# ---------------------------------------------------------------------------


class _StubBB:
    def __init__(self):
        self.store = {}

    def set(self, k, v):
        self.store[k] = v

    def get(self, k):
        return self.store.get(k)


def _stub_ctx(camera_role=CameraRole.SCENE, bite_idx=1):
    from chengshao.cs_orchestra.core import Deps, Trace, VirtualClock

    bb = _StubBB()
    ctx = SimpleNamespace(
        clock=VirtualClock(), bb=bb, camera_role=camera_role,
        bite=SimpleNamespace(idx=bite_idx), trace=Trace(1), deps=Deps(mouth=None),
        bb_set=bb.set,
    )
    ctx.bb.set("camera_role", camera_role)
    return ctx


def test_camera_role_ledger_two_switches_per_delivered_bite():
    ledger = CameraRoleLedger()
    ctx = _stub_ctx()
    ledger.switch(ctx, CameraRole.WRIST_MOUTH, "delivery_entry")
    ledger.switch(ctx, CameraRole.SCENE, "retract_complete")
    rep = ledger.per_bite_report(1, delivered=True)
    assert rep["ok"] and rep["switches"] == 2


def test_camera_role_ledger_rejects_extra_switch():
    ledger = CameraRoleLedger()
    ctx = _stub_ctx()
    ledger.switch(ctx, CameraRole.WRIST_MOUTH, "delivery_entry")
    ledger.switch(ctx, CameraRole.SCENE, "retract_complete")
    with pytest.raises(ValueError):
        ledger.switch(ctx, CameraRole.SCENE, "estop_abort")  # 已在 scene


def test_camera_role_ledger_nondelivered_bite_needs_zero_switches():
    ledger = CameraRoleLedger()
    assert ledger.per_bite_report(1, delivered=False)["ok"]
    ctx = _stub_ctx()
    ledger.switch(ctx, CameraRole.WRIST_MOUTH, "delivery_entry")
    ledger.switch(ctx, CameraRole.SCENE, "retract_complete")
    # 有切换但未进送达 => 台账口径不通过
    assert not ledger.per_bite_report(1, delivered=False)["ok"]


# ---------------------------------------------------------------------------
# 全流程 mock 餐（小餐量快速回归）
# ---------------------------------------------------------------------------


def test_mock_meal_full_loop_with_rescoop(params, model, validator):
    """3 口闭环；第 2 口首轮舀空、闭环重舀后命中（勺空重试覆盖）。"""
    ns, summary = _run({2: {"first_scoop_empty": True}}, 3, params, model, validator)
    assert not summary["timeout"] and not summary["unexpected_failures"]
    assert [str(r.outcome) for r in ns.ctx.bites_done] == ["success"] * 3
    assert summary["session_ended"]
    # 第 2 口重舀：2 轮行程、2 次勺检，且 camera_role 仍恰 2 次切换
    rounds = [e for e in ns.ctx.trace.events
              if e["kind"] == "scoop_round" and e.get("bite") == 2]
    checks = [e for e in ns.ctx.trace.events
              if e["kind"] == "spoon_check" and e.get("bite") == 2]
    assert len(rounds) == 2 and len(checks) == 2
    for bite in (1, 2, 3):
        rep = ns.ctx.ledger.per_bite_report(bite, delivered=True)
        assert rep["ok"], (bite, rep["detail"])
    # 曝光稳定窗：scene->wrist 后 >=0.5s 才有有效口部帧
    for sw in ns.ctx.ledger.switches:
        if sw["reason"] != "delivery_entry":
            continue
        valid_after = [s[0] for s in ns.ctx.mouth_samples
                       if s[1] == "wrist_mouth" and s[2] and s[0] >= sw["ts_ns"]]
        assert valid_after
        assert (min(valid_after) - sw["ts_ns"]) / 1e9 >= 0.5 - 0.05


def test_mock_meal_estop_aborts_and_recovers(params, model, validator):
    """急停：本口 aborted + estop_abort 切回 scene + 复位后 resume 恢复下口。"""
    ns, summary = _run({1: {"estop": True}}, 2, params, model, validator)
    assert not summary["timeout"] and not summary["unexpected_failures"]
    outcomes = [str(r.outcome) for r in ns.ctx.bites_done]
    assert outcomes == ["aborted", "success"]
    assert ns.ctx.announce_counts.get("estop") == 1
    kinds = {e["kind"] for e in ns.ctx.trace.events}
    assert {"estop_detected", "safety_retreat_start",
            "safety_recovered"} <= kinds
    # 被急停口恰 2 次切换（进送达 + estop_abort）
    assert _switch_reasons(ns.ctx.ledger, 1) == ["delivery_entry", "estop_abort"]
    assert _switch_reasons(ns.ctx.ledger, 2) == ["delivery_entry", "retract_complete"]
    assert str(ns.ctx.camera_role) == "scene"


def test_mock_meal_zone_violation_aborts_and_recovers(params, model, validator):
    """禁入区侵入（mock teleport 装配）：aborted + zone_abort + 复位后恢复。"""
    ns, summary = _run({1: {"zone": True}}, 2, params, model, validator)
    assert not summary["timeout"]
    outcomes = [str(r.outcome) for r in ns.ctx.bites_done]
    assert outcomes == ["aborted", "success"]
    assert ns.ctx.announce_counts.get("zone") == 1
    kinds = {e["kind"] for e in ns.ctx.trace.events}
    assert {"zone_detected", "safety_recovered"} <= kinds
    assert _switch_reasons(ns.ctx.ledger, 1) == ["delivery_entry", "zone_abort"]


def test_mock_meal_done_graceful_shutdown(params, model, validator):
    """吃饱了：本口 rejected + 撤回（done_retract 切回 scene）+ 会话收敛。"""
    ns, summary = _run({2: {"done": True}}, 2, params, model, validator)
    assert not summary["timeout"] and not summary["unexpected_failures"]
    outcomes = [str(r.outcome) for r in ns.ctx.bites_done]
    assert outcomes == ["success", "rejected"]
    assert summary["session_ended"]
    assert ns.ctx.announce_counts.get("done") == 1
    assert _switch_reasons(ns.ctx.ledger, 2) == ["delivery_entry", "done_retract"]
    ended = [e for e in ns.ctx.trace.events if e["kind"] == "meal_ended"]
    assert ended and ended[-1]["reason"] == "done"


def test_scoop_exhausted_records_retry_without_delivery(params, model, validator):
    """重舀耗尽：本口 retry、不进送达（camera_role 全程 scene、0 次切换）。"""
    ns, summary = _run({1: {"scoop_always_empty": True}}, 1, params, model, validator)
    assert not summary["timeout"]
    outcomes = [str(r.outcome) for r in ns.ctx.bites_done]
    assert outcomes == ["retry"]
    rounds = [e for e in ns.ctx.trace.events
              if e["kind"] == "scoop_round" and e.get("bite") == 1]
    assert len(rounds) == 1 + params.scoop_retries_max  # 首轮 + 2 次重舀
    assert ns.ctx.ledger.for_bite(1) == []  # 0 次角色切换
    assert str(ns.ctx.camera_role) == "scene"


def test_turn_hold_announces_once_and_recovers(params, model, validator):
    """送达中转头：保持 + 播报一次，恢复后本口完成。"""
    ns, summary = _run({1: {"turn_s": 2.0, "turn_delay_s": 0.2}}, 1,
                       params, model, validator)
    assert not summary["timeout"] and not summary["unexpected_failures"]
    assert [str(r.outcome) for r in ns.ctx.bites_done] == ["success"]
    assert ns.ctx.announce_counts.get("turn") == 1
    kinds = {e["kind"] for e in ns.ctx.trace.events}
    assert "turn_recovered" in kinds


def test_blackboard_frozen_keys_present(params, model, validator):
    """黑板 8 个冻结键（§3.2/§5.6）在一餐可读。"""
    ns, _ = _run({}, 1, params, model, validator)
    bb = ns.ctx.bb
    for key in ("mouth", "arm_state", "safety", "spoon", "intent",
                "session", "bowl_sel", "camera_role"):
        assert bb.exists(key), key


def test_sink_records_all_bites(params, model, validator):
    """记录池（cs_dashboard 的 mock 侧）：会话与单口一一对应。"""
    ns, _ = _run({}, 2, params, model, validator)
    assert len(ns.deps.sink.bites) == len(ns.ctx.bites_done) == 2
    assert ns.deps.sink.sessions[-1]["ended"] is True


# ---------------------------------------------------------------------------
# 纯单元：舀取策略交互（ScriptedScoop/学习型策略延后接入时对齐同一交互）
# ---------------------------------------------------------------------------


def test_mock_scoop_policy_interaction(params, model, validator):
    from chengshao.cs_orchestra.core import Deps

    ns = make_mock_episode(episode=1, script={}, bites=1, params=params,
                           model=model, validator=validator)
    state = ns.state
    policy: MockScoop = ns.deps.scoop
    items = policy.plan_round(1, params.bowls_m()[0], 1)
    kinds = [it[0] for it in items]
    assert kinds[0] == "cart" and "jtrack_reverse" in kinds and kinds[-1] == "cart"
    state.new_bite(1, {})
    policy.on_round_complete(1)
    assert state.food_on_spoon
    from chengshao.cs_schema import SpoonCheck

    check = SpoonCheck(ts_ns=0, has_food=True, score=0.9, cam_ref="wrist_cam")
    assert policy.on_spoon_check(check)
    policy.on_round_complete(3)
    assert policy.retries_left() == max(0, params.scoop_retries_max - 2)


def test_orchestra_params_config_roundtrip():
    """config/orchestra.json 装载：缺省回退 + 显式覆盖生效。"""
    defaults = OrchestraParams()
    loaded = OrchestraParams.load()
    assert loaded.tick_s == defaults.tick_s == pytest.approx(0.02)
    assert loaded.exposure_settle_s == pytest.approx(0.5)
    assert loaded.delivery_via_points_by_bowl, "逐碗途经点应随 config 提供"
    assert MemorySink is not None and Blackboard is not None  # 依赖可用
