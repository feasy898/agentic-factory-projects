# -*- coding: utf-8 -*-
"""JS Number 语义（int32/uint32）——规则卡 §7 deriveRng/mulberry32 公式的位精确基础。

规则卡以 TypeScript 源为权威（SPEC.md §0 注），其 PRNG 公式全部建立在 JS 的
32 位整数溢出与无符号移位语义上。Python 需显式复刻这些语义：
  - `a |= 0`            -> to_i32
  - `>>> 0`             -> to_u32
  - `Math.imul(a, b)`   -> imul32（32 位乘法取低 32 位，位模式与符号无关）
  - `Math.round(x)`     -> js_round（四舍五入取整，+0.5 向上；非 Python 银行家舍入）
"""


U32_MASK = 0xFFFFFFFF


def to_u32(x: int) -> int:
    """`x >>> 0`：取无符号 32 位。"""
    return x & U32_MASK


def to_i32(x: int) -> int:
    """`x | 0`：取有符号 32 位。"""
    x &= U32_MASK
    return x - 0x100000000 if x >= 0x80000000 else x


def imul32(a: int, b: int) -> int:
    """`Math.imul(a, b)`：精确 32 位整数乘法，返回低 32 位位模式（此处以 u32 表示）。"""
    return ((a & U32_MASK) * (b & U32_MASK)) & U32_MASK


def js_round(x: float) -> int:
    """`Math.round(x)`：JS 四舍五入（.5 向 +inf），SPEC §8 "cellCenter 四舍五入取整"。"""
    import math
    return math.floor(x + 0.5)
