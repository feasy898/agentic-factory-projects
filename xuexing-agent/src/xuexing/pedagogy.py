"""教学策略注册表与策略选择（pedagogy，冻结契约 v1.0 重生成实例）。

把学习科学的循证结论编码为带优先级与适用条件的策略注册表：
StrategyLibrary 按 (-priority, id) 全序给出库内策略，select 在给定
（掌握度, 年级）时按优先级扫描选出唯一适用的策略对象；load_strategies
从 JSON 文件装载注册表。本模块不生成 LearningPlan。

约束：仅标准库 + xuexing.types；除 load_strategies 读一个 JSON 文件外
无任何文件/网络 IO；无随机源、无时钟、无全局可变状态，同输入同输出。
"""
from __future__ import annotations

import json

from xuexing.types import Strategy

__all__ = ["StrategyError", "StrategyLibrary", "load_strategies"]


class StrategyError(ValueError):
    """本模块唯一异常类型，继承 ValueError（调用方 except ValueError 亦生效）。"""


def _matches(s: Strategy, mastery: float, grade: int) -> bool:
    """I2 条件语义：None 不施加约束；不等式方向冻结——mastery_lt 严格，
    mastery_gte/grade_max/grade_min 含等号。"""
    if s.mastery_lt is not None and mastery >= s.mastery_lt:
        return False
    if s.mastery_gte is not None and mastery < s.mastery_gte:
        return False
    if s.grade_max is not None and grade > s.grade_max:
        return False
    if s.grade_min is not None and grade < s.grade_min:
        return False
    return True


class StrategyLibrary:
    """策略注册表：按 (-priority, id) 全序存储，select 选出唯一适用策略。"""

    def __init__(self) -> None:
        self._items: list[Strategy] = []
        self._by_id: dict[str, Strategy] = {}

    def add(self, s: Strategy) -> None:
        """按引用注册策略；id 重复抛 StrategyError，且库内容保持不变。"""
        if s.id in self._by_id:
            raise StrategyError(f"duplicate strategy id: {s.id}")
        self._items.append(s)
        self._by_id[s.id] = s

    def get(self, sid: str) -> Strategy | None:
        """命中返回注册时的同一对象（is 相等），未命中返回 None。"""
        return self._by_id.get(sid)

    def strategies(self) -> list[Strategy]:
        """库内全部策略各恰好一次，按 (-priority, id) 排序；每次返回新 list，
        修改返回值不影响库。"""
        return sorted(self._items, key=lambda s: (-s.priority, s.id))

    def select(self, mastery: float, grade: int) -> Strategy:
        """I1/I3/I5：按 strategies() 顺序扫描，返回第一个条件全部满足的注册
        对象本身；无任何匹配（含空库）抛 StrategyError。mastery/grade 只做
        数值比较，不做域校验、不 clamp。"""
        for s in self.strategies():
            if _matches(s, mastery, grade):
                return s
        raise StrategyError(
            f"no applicable strategy for mastery={mastery}, grade={grade}"
        )


def load_strategies(path: str) -> StrategyLibrary:
    """从 JSON 文件（UTF-8）装载策略注册表。

    期望顶层对象含键 "strategies"（条目列表，每条为对象）；按字段映射表
    逐键提取，未知键忽略。形态违规按原生异常抛出（顶层/值/条目形态错 →
    TypeError，缺 "strategies" 或缺 id/name → KeyError），禁止宽松容错、
    不跳过非法条目；文件内重复 id 经 add 抛 StrategyError。
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    lib = StrategyLibrary()
    for entry in data["strategies"]:
        lib.add(Strategy(
            id=entry["id"],
            name=entry["name"],
            description=entry.get("description", ""),
            priority=int(entry.get("priority", 0)),
            evidence=entry.get("evidence", ""),
            effect_size=entry.get("effect_size"),
            mastery_lt=entry.get("mastery_lt"),
            mastery_gte=entry.get("mastery_gte"),
            grade_max=entry.get("grade_max"),
            grade_min=entry.get("grade_min"),
        ))
    return lib
