"""契约：scheduler + pedagogy —— 间隔重复与策略选择。"""
from datetime import date

import pytest

from xuexing.pedagogy import StrategyError, StrategyLibrary
from xuexing.scheduler import ReviewLog, schedule
from xuexing.types import Strategy

TODAY = date(2026, 9, 28)


def test_interval_grows_then_lapse_resets():
    i1 = schedule("k", [ReviewLog(2, 0)], TODAY).interval_days
    i2 = schedule("k", [ReviewLog(2, 0), ReviewLog(2, i1)], TODAY).interval_days
    i3 = schedule("k", [ReviewLog(2, 0), ReviewLog(2, i1), ReviewLog(2, i2)], TODAY).interval_days
    assert 1 <= i1 < i2 < i3
    lapsed = schedule("k", [ReviewLog(2, 0), ReviewLog(2, i1), ReviewLog(0, i2)], TODAY)
    assert lapsed.interval_days < i3


def test_ease_moves_with_rating():
    easy = schedule("k", [ReviewLog(3, 0), ReviewLog(3, 4)], TODAY)
    hard = schedule("k", [ReviewLog(1, 0), ReviewLog(1, 4)], TODAY)
    assert easy.ease > hard.ease
    assert 1.3 <= hard.ease <= 3.0


def test_determinism_and_future_due():
    a = schedule("k", [ReviewLog(2, 0)], TODAY)
    b = schedule("k", [ReviewLog(2, 0)], TODAY)
    assert a == b and a.due > TODAY.isoformat() and a.interval_days >= 1


def test_bad_params_rejected():
    with pytest.raises(ValueError):
        schedule("k", [], TODAY, initial_ease=9.9)
    with pytest.raises(ValueError):
        schedule("k", [], TODAY, initial_interval=0)


def _library():
    lib = StrategyLibrary()
    lib.add(Strategy(id="low", name="L", description="", priority=10, mastery_lt=0.4))
    lib.add(Strategy(id="mid", name="M", description="", priority=8, mastery_gte=0.4, mastery_lt=0.65))
    lib.add(Strategy(id="high", name="H", description="", priority=6, mastery_gte=0.65))
    lib.add(Strategy(id="young", name="Y", description="", priority=12, mastery_lt=0.5, grade_max=6))
    lib.add(Strategy(id="fallback", name="F", description="", priority=1))
    return lib


def test_strategy_band_selection():
    lib = _library()
    assert lib.select(0.2, 7).id == "low"
    assert lib.select(0.5, 7).id == "mid"
    assert lib.select(0.8, 7).id == "high"
    assert lib.select(0.2, 4).id == "young"   # 高优先级且年级匹配
    assert lib.select(0.8, 4).id == "high"    # young 只覆盖 mastery<0.5
    assert lib.select(0.2, 9).id == "low"


def test_strategy_fallback_covers_band_holes():
    lib = StrategyLibrary()
    lib.add(Strategy(id="low", name="L", description="", priority=10, mastery_lt=0.4))
    lib.add(Strategy(id="high", name="H", description="", priority=6, mastery_gte=0.65))
    lib.add(Strategy(id="fallback", name="F", description="", priority=1))
    assert lib.select(0.5, 7).id == "fallback"  # 0.4-0.65 是空档，兜底接管
    with pytest.raises(StrategyError):
        StrategyLibrary().select(0.5, 7)


def test_strategy_priority_ordering():
    ids = [s.id for s in _library().strategies()]
    assert ids.index("young") < ids.index("low") < ids.index("mid") < ids.index("high") < ids.index("fallback")
