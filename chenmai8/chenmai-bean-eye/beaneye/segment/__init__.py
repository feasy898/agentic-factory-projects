"""M4 分割包（plan/开发指令.md §4 M4）。

当前内容：``ClassicSeg``（Otsu + 形态学 + 距离变换分水岭，本包 classic 模块）。
OracleSeg / NN 模型按同一冻结 ``SegModel`` Protocol 后续并入本包。

装配约定（``beaneye.app.components``）：本包暴露 ``build_default(**kwargs)``
工厂，应用壳探测到即可零改动接线。
"""

from __future__ import annotations

from beaneye.segment.classic import ClassicSeg
from beaneye.segment.config import SegmentConfig, SegmentConfigError, load_segment_config

__all__ = [
    "ClassicSeg",
    "SegmentConfig",
    "SegmentConfigError",
    "load_segment_config",
    "build_default",
]


def build_default(**kwargs) -> ClassicSeg:
    """M13 装配器接线约定：``<pkg>.build_default(**kwargs) -> SegModel 实现``。"""
    return ClassicSeg(**kwargs)
