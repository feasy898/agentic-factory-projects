"""采集源抽象基类（M2 · Source ABC）。

与冻结契约 ``beaneye.schemas.CameraSource`` Protocol（``capture_pair``）结构兼容：
本包所有 Source 实现（Mock / USB / Synth）都继承此基类，共享统一的
「写双面图 + manifest.json + 出厂前 M1 契约自检」落盘路径，
保证任何来源产出的 :class:`~beaneye.schemas.TrayScan` 天然通过 M1 校验。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from beaneye.schemas import TrayScan

from beaneye.acquisition.base import AcquisitionError, imwrite_bgr, write_json

__all__ = ["Source"]


class Source(ABC):
    """采集源抽象：子类只需把双面 BGR 帧交给 :meth:`_finalize_pair`。

    参数
    ----
    out_dir:
        采集输出根目录。``TrayScan.top_image/bottom_image`` 按契约为相对路径
        （相对本目录），绝对路径 = ``out_dir / scan.top_image``。
    scan_prefix:
        scan_id / 子目录前缀（如 ``"mock"`` → ``scan_mock_0001``）。
    image_ext:
        落盘图像扩展名（默认 ``.png``，无损，利于下游分割/标定）。
    """

    def __init__(
        self,
        out_dir: str | Path,
        *,
        scan_prefix: str,
        image_ext: str = ".png",
        source_kind: str,
    ) -> None:
        if source_kind not in ("mock", "usb", "synth"):
            raise AcquisitionError(f"source_kind 非法: {source_kind!r}")
        self.out_dir = Path(out_dir)
        self.scan_prefix = scan_prefix
        self.image_ext = image_ext if image_ext.startswith(".") else f".{image_ext}"
        self.source_kind = source_kind
        self._frame_idx = 0  # 内置帧序列计数（每次 capture_pair 递增）

    # ------------------------------------------------------------------
    # 契约接口（CameraSource Protocol）
    # ------------------------------------------------------------------
    @abstractmethod
    def capture_pair(self, sample_id: str, tray_id: str) -> TrayScan:
        """采集一次整盘双面，返回通过 M1 校验的 TrayScan。"""

    # ------------------------------------------------------------------
    # 共享落盘路径：子类拿到双面帧后调用
    # ------------------------------------------------------------------
    def _next_scan_id(self) -> str:
        idx = self._frame_idx
        self._frame_idx += 1
        return f"scan_{self.scan_prefix}_{idx + 1:04d}"

    def _finalize_pair(
        self,
        sample_id: str,
        tray_id: str,
        top_bgr: np.ndarray,
        bottom_bgr: np.ndarray,
    ) -> TrayScan:
        """写 ``<out_dir>/<scan_id>/{top,bottom}.png`` + ``manifest.json``，
        构造并**出厂自检** TrayScan（to_json/from_json 往返，违规即抛错）。"""
        if top_bgr is None or bottom_bgr is None or top_bgr.size == 0 or bottom_bgr.size == 0:
            raise AcquisitionError("双面帧不完整（None 或空数组），拒绝落盘")
        if top_bgr.shape[:2] != bottom_bgr.shape[:2]:
            raise AcquisitionError(
                f"双面分辨率不一致: top={top_bgr.shape[:2]} vs bottom={bottom_bgr.shape[:2]}"
            )

        scan_id = self._next_scan_id()
        pair_dir = self.out_dir / scan_id
        top_rel = f"{scan_id}/top{self.image_ext}"
        bottom_rel = f"{scan_id}/bottom{self.image_ext}"
        imwrite_bgr(self.out_dir / top_rel, top_bgr)
        imwrite_bgr(self.out_dir / bottom_rel, bottom_bgr)

        scan = TrayScan(
            scan_id=scan_id,
            sample_id=sample_id,
            tray_id=tray_id,
            top_image=top_rel,
            bottom_image=bottom_rel,
            calibration=None,  # 标定是 M3 职责；采集阶段恒为空
            captured_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            source=self.source_kind,  # type: ignore[arg-type]
        )
        # 出厂自检：任何来源的产物必须通过 M1 契约往返
        scan = TrayScan.from_json(scan.to_json())
        write_json(pair_dir / "manifest.json", scan.model_dump(mode="json"))
        return scan
