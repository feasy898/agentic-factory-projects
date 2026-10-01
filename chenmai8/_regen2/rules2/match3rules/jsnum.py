# -*- coding: utf-8 -*-
"""JS 数值语义镜像（卡面 §1/§8）：Math.round 与 int(v, default, min, max) 宽容归一。

卡面 §8 明示：四舍五入 = JS Math.round（= floor(x+0.5)，正负数 .5 均向 +∞）——
Math.round(2.5)=3、Math.round(0.5)=1、Math.round(-2.5)=-2，与 Python 银行家舍入
（round(2.5)=2）可区分，镜像实现须显式实现 js_round 而不可直接用 Python round。
"""

import math


def js_round(x):
    """JS Math.round：floor(x + 0.5)，.5 向 +∞（可区分 Python 银行家舍入）。"""
    return math.floor(x + 0.5)


def js_int(v, default, lo, hi):
    """卡面 §1 int(v, default, min, max)——参数序 (v, default, min, max)。

    非数值 / 非有限数取缺省；否则 Math.round 后钳制到 [lo, hi]。
    """
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        return default
    f = float(v)
    if math.isnan(f) or math.isinf(f):
        return default
    return max(lo, min(hi, js_round(f)))
