"""间隔重复调度器（SM-2 变体，行为契约：成功间隔递增、遗忘重置、确定性）。

升级路径：替换为 FSRS（pip install fsrs）时保持本契约不变。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .types import ReviewEntry


@dataclass
class ReviewLog:
    """一次复习记录。rating: 0=遗忘 1=勉强 2=良好 3=轻松。"""

    rating: int  # 0..3
    days_since_last: int  # 距上次复习的天数；首次复习填 0


def schedule(
    kp_id: str,
    history: list[ReviewLog],
    today: date,
    initial_interval: int = 1,
    initial_ease: float = 2.5,
) -> ReviewEntry:
    """根据复习历史给出下次复习日期。确定性：同输入恒等输出。"""
    if not 1 <= initial_interval <= 365:
        raise ValueError("initial_interval out of [1, 365]")
    if not 1.3 <= initial_ease <= 3.0:
        raise ValueError("initial_ease out of [1.3, 3.0]")
    ease = initial_ease
    interval = initial_interval
    for log in history:
        if log.rating == 0:
            interval = initial_interval
            ease = max(1.3, ease - 0.2)
        else:
            if log.rating == 1:
                ease = max(1.3, ease - 0.15)
                interval = max(interval, initial_interval)
            elif log.rating == 2:
                pass
            else:
                ease = min(3.0, ease + 0.15)
            interval = max(1, round(interval * ease))
    due = today.toordinal() + interval
    return ReviewEntry(
        kp_id=kp_id,
        due=date.fromordinal(due).isoformat(),
        interval_days=int(interval),
        ease=round(ease, 4),
    )
