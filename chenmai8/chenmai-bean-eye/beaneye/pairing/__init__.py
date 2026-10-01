"""BeanEye · M6 上下配对（beaneye.pairing）。

公开入口：``pair_observations``（匈牙利 + 门限 + 单面保留）、``summarize``
（成对/单面统计）。实现见 ``beaneye.pairing.hungarian``。
"""

from beaneye.pairing.hungarian import (
    DEFAULT_GATE_MM,
    PairingConfig,
    PairingError,
    PairingSummary,
    pair_observations,
    robust_shift_mm,
    summarize,
)

__all__ = [
    "DEFAULT_GATE_MM",
    "PairingConfig",
    "PairingError",
    "PairingSummary",
    "pair_observations",
    "robust_shift_mm",
    "summarize",
]
