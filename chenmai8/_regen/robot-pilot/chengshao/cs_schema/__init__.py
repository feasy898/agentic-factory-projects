"""cs_schema（重生成最小切片）：仅再生成 cs_food 所需的数据契约。

完整契约层（8 模型 / 7 枚举 / 常量 / 夹具）见原 repo cs_schema 包与
docs/assets/specs/cs_schema.md；本切片只实现 cs_food 冻结测试引用的 SpoonCheck，
基类纪律（extra=forbid / allow_inf_nan=False / validate_assignment=True）与该 spec §2 一致。
本包不依赖任何其他 cs_* 包（依赖-free 硬纪律）。
"""

from .models import SpoonCheck

__all__ = ["SpoonCheck"]
