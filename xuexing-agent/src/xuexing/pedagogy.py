"""教学策略库：把学习科学的循证结论编码为可执行的选择规则。

来源：Visible Learning MetaX（提取练习 d≈0.49）、Mayer CTML、
expertise reversal（Tetzlaff 2025）、Rohrer 交错练习、FSRS/Anki、DragonBox RCT。
"""
from __future__ import annotations

import json

from .types import Strategy


class StrategyError(ValueError):
    pass


class StrategyLibrary:
    def __init__(self) -> None:
        self._strategies: dict[str, Strategy] = {}

    def add(self, s: Strategy) -> None:
        if s.id in self._strategies:
            raise StrategyError(f"duplicate strategy id: {s.id}")
        self._strategies[s.id] = s

    def get(self, sid: str) -> Strategy | None:
        return self._strategies.get(sid)

    def strategies(self) -> list[Strategy]:
        return sorted(self._strategies.values(), key=lambda s: (-s.priority, s.id))

    def select(self, mastery: float, grade: int) -> Strategy:
        """按适用条件选策略：priority 降序，第一个条件匹配者胜出。

        无任何匹配时必须抛 StrategyError（调用方应保证库里有兜底策略）。
        """
        for s in self.strategies():
            if s.mastery_lt is not None and not mastery < s.mastery_lt:
                continue
            if s.mastery_gte is not None and not mastery >= s.mastery_gte:
                continue
            if s.grade_max is not None and not grade <= s.grade_max:
                continue
            if s.grade_min is not None and not grade >= s.grade_min:
                continue
            return s
        raise StrategyError(f"no strategy matches mastery={mastery}, grade={grade}")


def load_strategies(path: str) -> StrategyLibrary:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    lib = StrategyLibrary()
    for s in data["strategies"]:
        lib.add(
            Strategy(
                id=s["id"],
                name=s["name"],
                description=s.get("description", ""),
                priority=int(s.get("priority", 0)),
                evidence=s.get("evidence", ""),
                effect_size=s.get("effect_size"),
                mastery_lt=s.get("mastery_lt"),
                mastery_gte=s.get("mastery_gte"),
                grade_max=s.get("grade_max"),
                grade_min=s.get("grade_min"),
            )
        )
    return lib
