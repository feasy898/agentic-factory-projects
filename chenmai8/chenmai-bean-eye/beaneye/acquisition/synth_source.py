"""SynthSource：合成引擎采集源（M2 接口占位，W12b 后接入）。

M12 合成数据引擎（beaneye.synth）就绪后，本类把「随机铺盘 → 成对渲染 →
直接产 TrayScan（source="synth"，calibration 由合成几何精确给出）」接入
Source 落盘路径。W12b 之前调用 :meth:`capture_pair` 抛
:class:`~beaneye.acquisition.base.AcquisitionError`（明确、可捕获，非裸
NotImplementedError 泄漏到用户界面）。
"""

from __future__ import annotations

from pathlib import Path

from beaneye.schemas import TrayScan

from beaneye.acquisition.base import AcquisitionError
from beaneye.acquisition.source import Source

__all__ = ["SynthSource"]


class SynthSource(Source):
    """占位实现：接口已冻结（capture_pair → TrayScan, source="synth"）。"""

    def __init__(self, out_dir: str | Path, *, scan_prefix: str = "synth") -> None:
        super().__init__(out_dir, scan_prefix=scan_prefix, source_kind="synth")

    def capture_pair(self, sample_id: str, tray_id: str) -> TrayScan:
        raise AcquisitionError(
            "SynthSource 尚未接入：等待 W12b 合成数据引擎（beaneye.synth）就绪后实现。"
            "当前请使用 MockSource（内置合成图序列，不依赖素材库）。"
        )
