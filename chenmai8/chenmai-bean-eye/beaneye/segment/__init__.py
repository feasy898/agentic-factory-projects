"""M4 分割包（plan/开发指令.md §4 M4）。

内容：``ClassicSeg``（Otsu + 形态学 + 距离变换分水岭，本包 classic 模块）与
``OracleSeg``（合成 manifest 真值透传，本包 oracle 模块，W4a——合成盘黄金
分割器，端到端链路评估与 classic 上限对照用）。NN 模型按同一冻结
``SegModel`` Protocol 后续并入本包。

装配约定（``beaneye.app.components``）：本包暴露 ``build_default(**kwargs)``
工厂，应用壳探测到即可零改动接线。``build_default`` 默认接 **ClassicSeg**
（产品缺省分割器）；``OracleSeg`` 是合成盘专用评估工具，由 e2e/评测侧显式
构造注入（真值索引只对合成 scan_id 有效，见 oracle 模块 docstring）。
"""

from __future__ import annotations

from beaneye.segment.classic import ClassicSeg
from beaneye.segment.config import SegmentConfig, SegmentConfigError, load_segment_config
from beaneye.segment.oracle import SUPPORTED_LABELS_VERSION, OracleSeg, OracleSegError

__all__ = [
    "ClassicSeg",
    "OracleSeg",
    "OracleSegError",
    "SUPPORTED_LABELS_VERSION",
    "SegmentConfig",
    "SegmentConfigError",
    "load_segment_config",
    "build_default",
]


def build_default(**kwargs) -> ClassicSeg:
    """M13 装配器接线约定：``<pkg>.build_default(**kwargs) -> SegModel 实现``。"""
    return ClassicSeg(**kwargs)
