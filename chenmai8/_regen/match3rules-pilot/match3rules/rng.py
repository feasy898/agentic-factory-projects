# -*- coding: utf-8 -*-
"""随机流与盐值——SPEC.md §7（冻结）逐条复刻。

| 流                     | 派生式                                       | 用途 |
|------------------------|----------------------------------------------|------|
| 主流                   | mulberry32(meta.seed)                        | 盘面生成、果冻摆放 |
| 补位流（第 k 次交换）  | deriveRng(seed, SPAWN_SALT ^ k)              | 真实结算、nearWin 预估、hint 投影、生成期 simulatePlay —— 四者同流 |
| 死局重排流（第 k 步）  | deriveRng(seed, 0x5117 ^ k)                  | doReshuffle 与 simulatePlay 重排 |
| deriveRng              | mulberry32((seed ^ imul(salt, 0x9e3779b9)) >>> 0) | — |

注：卡只给出名字 "mulberry32"，未含函数体；本实现采用该名字的规范公共定义
（bryc 公版，第二乘数 = t|61——2026-09-29 属主裁决重冻 oracle 后的真源口径，规则卡 §7/§12），
并以 tests/frozen.py 内的独立转写为冻结对照（同日随 oracle 重冻同步修正，此前误按 *61 变体）。
"""

from .jsnum import to_i32, to_u32, imul32

SPAWN_SALT = 0x51ED270B          # SPEC §7 表格原值
RESHUFFLE_SALT = 0x5117          # SPEC §7 表格原值
DERIVE_GOLDEN = 0x9E3779B9       # SPEC §7 deriveRng 行原值


def mulberry32(seed: int):
    """规范 mulberry32：返回 next() -> [0,1) 浮点；内部状态为 JS int32 语义。"""
    a = to_i32(seed)

    def next() -> float:  # noqa: A001 - 与 JS rng 语义对齐
        nonlocal a
        a = to_i32(a + 0x6D2B79F5)
        t = to_u32(a)
        t = imul32(t ^ (t >> 15), t | 1)
        t = to_u32(t ^ ((t + imul32(t ^ (t >> 7), t | 61)) & 0xFFFFFFFF))
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296

    return next


def derive_seed(seed: int, salt: int) -> int:
    """`(seed ^ imul(salt, 0x9e3779b9)) >>> 0`。"""
    return to_u32(to_u32(seed) ^ imul32(salt, DERIVE_GOLDEN))


def derive_rng(seed: int, salt: int):
    """SPEC §7 deriveRng：mulberry32((seed ^ imul(salt, 0x9e3779b9)) >>> 0)。"""
    return mulberry32(derive_seed(seed, salt))


def spawn_rng(seed: int, k: int):
    """第 k 次玩家交换（k 从 1 起）的补位流。"""
    return derive_rng(seed, SPAWN_SALT ^ k)


def reshuffle_rng(seed: int, k: int):
    """第 k 步的死局重排流。"""
    return derive_rng(seed, RESHUFFLE_SALT ^ k)
