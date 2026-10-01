# -*- coding: utf-8 -*-
"""贴图外观派生（纯逻辑部分）——SPEC.md §11。

卡面事实：贴图外观由 spriteKeys 键名驱动：FNV-1a 哈希（2166136261/16777619）
-> 形状 5 选 1（圆/菱/方/三角/六边）+ 调色板 7 色 (h+i) % 7；colors 决定实际使用的键数量。
（程序化绘制本身属视图层，不在本包范围；此处只固化纯派生逻辑。）
"""

FNV_OFFSET_BASIS = 2166136261
FNV_PRIME = 16777619

SHAPES = ["circle", "diamond", "square", "triangle", "hexagon"]  # 圆/菱/方/三角/六边（按卡面列举顺序）
PALETTE_SIZE = 7


def fnv1a(s: str) -> int:
    """32 位 FNV-1a（UTF-8 字节）。"""
    h = FNV_OFFSET_BASIS
    for b in s.encode("utf-8"):
        h ^= b
        h = (h * FNV_PRIME) & 0xFFFFFFFF
    return h


def piece_style(sprite_key: str, piece_index: int) -> dict:
    """由键名哈希派生形状（h % 5）与调色板索引 ((h + i) % 7)。"""
    h = fnv1a(sprite_key)
    return {"shape": SHAPES[h % len(SHAPES)], "palette": (h + piece_index) % PALETTE_SIZE}
