"""间隔重复调度器（SM-2 变体）。

重放一个知识点的历史复习记录，给出下次复习日期（due）、本次成功间隔
（interval_days）与当前难度（ease）。行为契约：连续成功间隔递增、
遗忘重置、同输入恒等输出；升级为 FSRS 等其他算法时必须保持
specs/frozen/scheduler.spec.md 的行为契约不变。
"""
from dataclasses import dataclass
from datetime import date

from xuexing.types import ReviewEntry

__all__ = ["ReviewLog", "schedule"]


@dataclass
class ReviewLog:
    """一次复习记录；days_since_last 是纯记录字段，不参与任何计算。"""

    rating: int  # 0=遗忘 1=勉强 2=良好 3=轻松
    days_since_last: int  # 距上次复习的天数；首次复习填 0


def schedule(
    kp_id: str,
    history: list[ReviewLog],
    today: date,
    initial_interval: int = 1,
    initial_ease: float = 2.5,
) -> ReviewEntry:
    """根据复习历史给出下次复习日期。确定性：同输入恒等输出。"""
    # 校验先于任何重放（空 history 也执行），顺序固定为先 interval 后 ease。
    # 判定必须保持链式比较：NaN 的任何比较均为 False，由此被拒绝；
    # 改写为 x < lo or x > hi 会放行 NaN。
    if not (1 <= initial_interval <= 365):
        raise ValueError("initial_interval out of [1, 365]")
    if not (1.3 <= initial_ease <= 3.0):
        raise ValueError("initial_ease out of [1.3, 3.0]")

    ease = initial_ease
    interval = initial_interval
    for log in history:
        rating = log.rating
        if rating == 0:  # 遗忘：interval 直接重置为初始值，不做乘法
            interval = initial_interval
            ease = max(1.3, ease - 0.2)
        elif rating == 1:  # 勉强：先降 ease，再取不短于初始间隔，最后乘 ease
            ease = max(1.3, ease - 0.15)
            interval = max(interval, initial_interval)
            interval = max(1, round(interval * ease))
        elif rating == 2:  # 良好：ease 不变
            interval = max(1, round(interval * ease))
        else:  # 其余一律按"轻松"处理：无类型校验，三个相等比较全 False 即入此支
            ease = min(3.0, ease + 0.15)
            interval = max(1, round(interval * ease))

    # round 为内置银行家舍入（half-to-even）；浮点逐位一致依赖上述运算顺序。
    return ReviewEntry(
        kp_id=kp_id,
        due=date.fromordinal(today.toordinal() + interval).isoformat(),
        interval_days=int(interval),
        ease=round(ease, 4),
    )
