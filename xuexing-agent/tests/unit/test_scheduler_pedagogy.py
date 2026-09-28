from datetime import date

import pytest

from xuexing.scheduler import ReviewLog, schedule
from xuexing.pedagogy import StrategyError


TODAY = date(2026, 9, 28)


def test_interval_grows_with_success():
    one = schedule("kp", [ReviewLog(2, 0)], TODAY)
    two = schedule("kp", [ReviewLog(2, 0), ReviewLog(2, one.interval_days)], TODAY)
    assert one.interval_days >= 1
    assert two.interval_days > one.interval_days


def test_lapse_resets_interval_and_lowers_ease():
    good = schedule("kp", [ReviewLog(2, 0), ReviewLog(2, 3), ReviewLog(2, 10)], TODAY)
    lapsed = schedule("kp", [ReviewLog(2, 0), ReviewLog(2, 3), ReviewLog(0, 10)], TODAY)
    assert lapsed.interval_days < good.interval_days
    assert lapsed.ease < good.ease


def test_rating_effect_on_ease():
    easy = schedule("kp", [ReviewLog(3, 0), ReviewLog(3, 5)], TODAY)
    hard = schedule("kp", [ReviewLog(1, 0), ReviewLog(1, 5)], TODAY)
    assert easy.ease > hard.ease


def test_determinism_and_due_is_future():
    a = schedule("kp", [ReviewLog(2, 0), ReviewLog(2, 2)], TODAY)
    b = schedule("kp", [ReviewLog(2, 0), ReviewLog(2, 2)], TODAY)
    assert a == b
    assert a.due > TODAY.isoformat()


def test_param_validation():
    with pytest.raises(ValueError):
        schedule("kp", [], TODAY, initial_ease=5.0)
    with pytest.raises(ValueError):
        schedule("kp", [], TODAY, initial_interval=-1)


def test_strategy_selection_bands(strategies):
    assert strategies.select(0.2, 7).id == "s_worked_example"
    assert strategies.select(0.5, 7).id == "s_retrieval"
    assert strategies.select(0.7, 7).id == "s_interleave"
    assert strategies.select(0.2, 4).id == "s_gamified"  # 低龄游戏化优先
    assert strategies.select(0.8, 4).id == "s_interleave"
    from xuexing.pedagogy import StrategyLibrary

    with pytest.raises(StrategyError):
        StrategyLibrary().select(0.5, 7)
