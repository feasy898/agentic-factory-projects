# -*- coding: utf-8 -*-
"""素材缺失行为——纯派生部分（卡面 §11）。

spec.assets 路径不参与渲染：贴图 Boot 阶段程序化生成，外观由 spriteKeys 键名驱动：
FNV-1a 哈希（2166136261/16777619，逐字符 h ^= c; h = imul(h, 16777619)，最终 >>> 0）
-> 形状 5 选 1（h % 5）+ 调色板 7 色 PALETTE[(h + i) % 7]（i = 棋子序号 0 起）。

形状枚举序（回炉钉死）：circle(圆) -> diamond(菱) -> square(方) -> triangle(三角) -> hexagon(六边)。
"""

from .rng import imul32

FNV_OFFSET_BASIS = 2166136261
FNV_PRIME = 16777619

SHAPES = ("circle", "diamond", "square", "triangle", "hexagon")

# 调色板 7 色色值表（回炉钉死）
PALETTE = (
    0xFF5A5F,  # 0 红
    0xFFC145,  # 1 琥珀
    0x2EC4B6,  # 2 青绿
    0x4D96FF,  # 3 蓝
    0xB388EB,  # 4 紫
    0xFF8FAB,  # 5 粉
    0x9ADF5D,  # 6 绿
)


def fnv1a(text):
    """FNV-1a：已知向量 fnv1a("")=2166136261、fnv1a("a")=0xe40c292c、fnv1a("foobar")=0xbf9cf968。"""
    h = FNV_OFFSET_BASIS
    for ch in text:
        h ^= ord(ch)
        h = imul32(h, FNV_PRIME)
    return h & 0xFFFFFFFF


def piece_style(key, index):
    """§11：形状 h % 5 + 调色板 (h + i) % 7（i = 棋子序号，0 起）。"""
    h = fnv1a(key)
    palette_index = (h + index) % 7
    return {
        "shape": SHAPES[h % 5],
        "palette": palette_index,
        "color": PALETTE[palette_index],
    }
