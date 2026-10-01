"""cs_schema 数据契约层。

本轮（robot2 重生成）按 docs/assets/specs/cs_schema.md §2 实现冻结测试所需的最小切片：
`_ContractModel` 基类纪律 + `SpoonCheck`。其余 7 个模型 / 枚举 / 常量 / 夹具
不属于 cs_food 重生成范围，未在此实现。
"""

from __future__ import annotations

from .models import SpoonCheck

__all__ = ["SpoonCheck"]
