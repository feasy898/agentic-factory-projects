# -*- coding: utf-8 -*-
"""随机流与盐值（卡面 §7，冻结）。

主流      mulberry32(meta.seed)                          盘面生成、果冻摆放
补位流    deriveRng(seed, SPAWN_SALT ^ k)                真实结算 / nearWin 预估 / hint 投影 /
          （k = 第 k 次玩家交换，从 1 起）                生成期 simulatePlay —— 四者同流
死局重排流 deriveRng(seed, 0x5117 ^ k)                   doReshuffle 与 simulatePlay 重排
          （k = moves - movesLeft + 1）
deriveRng mulberry32((seed ^ imul(salt, 0x9e3779b9)) >>> 0)

mulberry32 函数体按冻结 eval 的对照 oracle（tests/frozen.py:112-128，自标"mulberry32 公版
（bryc 版）冻结时刻内联转写"）逐行转写。**oracle 重冻（2026-09-29 属主裁决）：第二乘数 =
t|61 真源口径**（规则卡 §7 钉死 bryc 公版 = 模板 rng.ts 原文；§12 向量 mulberry32(1) 首抽
= 0.6270739405881613 佐证）。变体风险实录（两种转写是不同的流）：*61 误转写首抽 =
0.4286732426844537，t|61 = 0.6270739405881613，首抽即分叉。此前曾按误转写的 *61 oracle
回炉复归（2026-09-29 早间），同日属主裁决判 *61 为错转写、oracle 重冻为 t|61，本实现随
oracle 同步修正。
"""

from .constants import SPAWN_SALT

_MASK = 0xFFFFFFFF
_GOLDEN = 0x9E3779B9


def imul32(a, b):
    """Math.imul：乘积取低 32 位（位型与 JS 一致，后续均为位运算）。"""
    return (a * b) & _MASK


def mulberry32(seed):
    """冻结 eval 对照 oracle（frozen.py:112-128）的 Python 逐行镜像（t|61 真源口径）。"""
    a = seed & _MASK  # seed >>> 0

    def rnd():
        nonlocal a
        a = (a + 0x6D2B79F5) & _MASK
        t = a
        t = imul32(t ^ (t >> 15), t | 1)
        # 第二乘数是 t|61（bryc 公版，规则卡 §7；常数 61 是另一条流）
        t = (t ^ ((t + imul32(t ^ (t >> 7), t | 61)) & _MASK)) & _MASK
        return ((t ^ (t >> 14)) & _MASK) / 4294967296

    return rnd


def derive_seed(seed, salt):
    """deriveRng 的种子混合：((seed ^ imul(salt, 0x9e3779b9)) >>> 0)。"""
    return (seed ^ imul32(salt, _GOLDEN)) & _MASK


def derive_rng(seed, salt):
    """派生流：mulberry32((seed ^ imul(salt, 0x9e3779b9)) >>> 0)。"""
    return mulberry32(derive_seed(seed, salt))


def spawn_rng(seed, k):
    """补位流（第 k 次玩家交换，k 从 1 起）：deriveRng(seed, SPAWN_SALT ^ k)。"""
    return derive_rng(seed, SPAWN_SALT ^ k)
