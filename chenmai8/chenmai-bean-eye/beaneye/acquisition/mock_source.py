"""MockSource：内置合成图序列的采集源（M2）。

不依赖任何外部素材（W12b 合成引擎与 DCV 数据集均未就绪时的演示/开发源）：
- 纯 numpy/OpenCV 程序化生成「亚克力浅底 + 撒豆 + 四角 ArUco」整盘图；
- 每次调用 :meth:`capture_pair` 产出序列中的下一帧（确定性：同种子同帧序
  → 像素级一致）；
- top/bottom 共享同一布局坐标（bottom = 逐豆微抖动 + 亮度扰动 + 镜像不翻转），
  与 M12 成对真值约定一致；
- 产物走 :class:`~beaneye.acquisition.source.Source` 统一落盘路径，
  TrayScan 出厂即过 M1 契约校验。

ArUco 四角码用与 scripts/oss_smoke.py 相同的已验证 API
（getPredefinedDictionary(DICT_4X4_50) + generateImageMarker），
使 Mock 帧未来可直接喂给 M3 标定。
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from beaneye.schemas import TrayScan

from beaneye.acquisition.source import Source

__all__ = ["MockSource", "TRAY_MM"]

TRAY_MM = 300.0  # 盘面边长（mm），与 configs/tray.yaml 的规划一致

# 罗布斯塔生豆近似色（BGR）与缺陷色
_BEAN_BGR = (96, 120, 150)      # 浅褐绿生豆
_BEAN_JITTER = 28               # 逐豆明度抖动幅度
_BLACK_BGR = (24, 22, 20)       # 黑豆（主缺陷）
_BACKGROUND = (188, 192, 198)   # 亚克力浅灰（BGR）

_MARKER_MM = 60.0               # 四角 ArUco 边长（mm），对齐规划 tray.yaml


class MockSource(Source):
    """内置合成帧序列源：``capture_pair`` 依次返回确定性的合成整盘对。

    参数
    ----
    out_dir:
        输出根目录（TrayScan 相对路径以此为准）。
    n_beans:
        每盘豆数（帧序列内逐帧在 ±20% 内确定性浮动）。
    width, height:
        输出分辨率（默认 2048×2048 ≈ 0.147 mm/px）。
    seed:
        帧序列种子；同 seed 逐帧像素级可复现。
    defect_rate:
        黑豆缺陷占比（合成演示用）。
    """

    def __init__(
        self,
        out_dir: str | Path,
        *,
        n_beans: int = 120,
        width: int = 2048,
        height: int = 2048,
        seed: int = 20260928,
        defect_rate: float = 0.08,
        scan_prefix: str = "mock",
    ) -> None:
        if n_beans < 0:
            raise ValueError(f"n_beans 必须 >= 0，得到 {n_beans}")
        if not 0.0 <= defect_rate <= 1.0:
            raise ValueError(f"defect_rate 必须在 [0,1]，得到 {defect_rate}")
        if width < 64 or height < 64:
            raise ValueError(f"分辨率过小: {width}x{height}")
        super().__init__(out_dir, scan_prefix=scan_prefix, source_kind="mock")
        self.n_beans = n_beans
        self.width = int(width)
        self.height = int(height)
        self.seed = int(seed)
        self.defect_rate = float(defect_rate)

    # ------------------------------------------------------------------
    def capture_pair(self, sample_id: str, tray_id: str) -> TrayScan:
        frame_idx = self._frame_idx  # 帧序（父类 _finalize_pair 里再递增）
        rng = np.random.default_rng([self.seed, frame_idx])

        layout = self._sample_layout(rng)
        top = self._render(rng, layout, side="top")
        bottom = self._render(rng, layout, side="bottom")
        return self._finalize_pair(sample_id, tray_id, top, bottom)

    # ------------------------------------------------------------------
    def _sample_layout(self, rng: np.random.Generator) -> list[dict]:
        """采样一盘布局：mm 坐标 + 半径 + 是否黑豆（top/bottom 共享布局）。"""
        n = max(0, int(round(self.n_beans * rng.uniform(0.8, 1.2))))
        # 避开四角 ArUco 区（码+静区外缘 = marker*1.5 = 90mm）
        margin_mm = _MARKER_MM * 1.5 + 10.0
        lo, hi = margin_mm, TRAY_MM - margin_mm
        beans: list[dict] = []
        tries = 0
        while len(beans) < n and tries < n * 60:
            tries += 1
            x = float(rng.uniform(lo, hi))
            y = float(rng.uniform(lo, hi))
            r = float(rng.uniform(2.6, 3.6))  # 罗豆典型等效半径 mm
            if any((x - b["x"]) ** 2 + (y - b["y"]) ** 2 < (1.15 * (r + b["r"])) ** 2 for b in beans):
                continue  # 稀疏盘：不粘连（ClassicSeg 已知短板场景先避开）
            beans.append({"x": x, "y": y, "r": r, "black": rng.random() < self.defect_rate})
        return beans

    def _render(self, rng: np.random.Generator, layout: list[dict], side: str) -> np.ndarray:
        """渲染单面：底噪 + 豆 + 四角 ArUco + 全局亮度扰动。"""
        w, h = self.width, self.height
        px_per_mm = min(w, h) / TRAY_MM
        ox = (w - TRAY_MM * px_per_mm) / 2.0  # 盘面居中偏移
        oy = (h - TRAY_MM * px_per_mm) / 2.0

        img = np.empty((h, w, 3), dtype=np.uint8)
        img[:] = _BACKGROUND
        noise = rng.integers(-4, 5, size=(h, w, 1), dtype=np.int16)
        img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)

        jit = 1.2 if side == "top" else 2.0  # bottom 翻面复拍：抖动略大
        for b in layout:
            dx, dy = rng.normal(0, jit, 2) if side == "bottom" else (0.0, 0.0)
            cx = ox + (b["x"] + dx) * px_per_mm
            cy = oy + (b["y"] + dy) * px_per_mm
            ra, rb = b["r"] * px_per_mm * 0.92, b["r"] * px_per_mm * 0.74
            angle = float(rng.uniform(0, 180))
            color = _BLACK_BGR if b["black"] else _BEAN_BGR
            if not b["black"]:
                shift = int(rng.integers(-_BEAN_JITTER, _BEAN_JITTER + 1))
                color = tuple(int(np.clip(c + shift, 0, 255)) for c in color)
            cv2.ellipse(img, (int(round(cx)), int(round(cy))), (int(round(ra)), int(round(rb))),
                        angle, 0, 360, color, -1, cv2.LINE_AA)
            # 中缝（生豆特征）+ 边缘暗晕，增加真实感但不影响阈值分割
            cv2.ellipse(img, (int(round(cx)), int(round(cy))), (int(round(ra)), int(round(rb))),
                        angle, 0, 360, tuple(int(c * 0.55) for c in color), 2, cv2.LINE_AA)

        self._draw_corner_markers(img, px_per_mm, ox, oy)

        gain = float(rng.uniform(0.94, 1.06))  # 全局光照扰动（双面独立）
        return np.clip(img.astype(np.float32) * gain, 0, 255).astype(np.uint8)

    def _draw_corner_markers(
        self, img: np.ndarray, px_per_mm: float, ox: float, oy: float
    ) -> None:
        """四角 ArUco（id=0..3，角位序 TL,TR,BR,BL），M3 标定直接可用。

        几何与贴码方式对齐 scripts/oss_smoke.py 的已验证路径：
        码中心 = 角内缩 marker/2，外扩 side//4 白色静区。
        """
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        side_px = max(16, int(round(_MARKER_MM * px_per_mm)))
        half_px = side_px // 2
        pad = max(4, side_px // 4)
        # 码中心内缩 marker/4：保证 side//4 白色静区完整落在画布内
        # （码贴边会被裁掉静区导致检测失败 —— W2 实测坑，勿改回 marker/2）
        _c = _MARKER_MM / 2 + _MARKER_MM / 4
        centers_mm = {
            0: (_c, _c),
            1: (TRAY_MM - _c, _c),
            2: (TRAY_MM - _c, TRAY_MM - _c),
            3: (_c, TRAY_MM - _c),
        }
        h, w = img.shape[:2]
        tile_side = 2 * (half_px + pad)
        for mid, (mx, my) in centers_mm.items():
            marker = cv2.aruco.generateImageMarker(dictionary, mid, side_px)
            marker_bgr = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
            tile = np.full((tile_side, tile_side, 3), 255, dtype=np.uint8)
            tile[pad : pad + marker_bgr.shape[0], pad : pad + marker_bgr.shape[1]] = marker_bgr
            cx = int(round(ox + mx * px_per_mm))
            cy = int(round(oy + my * px_per_mm))
            x0, y0 = cx - half_px - pad, cy - half_px - pad
            # 钳制到画布（低分辨率下码可能贴近边缘）
            dst = img[max(0, y0) : min(h, y0 + tile_side), max(0, x0) : min(w, x0 + tile_side)]
            src = tile[
                max(0, -y0) : tile_side - max(0, y0 + tile_side - h),
                max(0, -x0) : tile_side - max(0, x0 + tile_side - w),
            ]
            dst[...] = src
