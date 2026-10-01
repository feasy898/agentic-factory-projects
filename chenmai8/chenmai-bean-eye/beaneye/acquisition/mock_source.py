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
使 Mock 帧未来可直接喂给 M3 标定。码位几何（盘边长/码边长/四码中心）
以 configs/tray.yaml 为唯一真源——Mock、打印板（make_aruco.py）、
标定配置三者同坐标，Mock 帧对默认配置标定 px_per_mm 误差 <1%
（回归锚点见 tests/test_acquisition.py）。
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from beaneye.schemas import TrayScan

from beaneye.acquisition.source import Source
from beaneye.calibration.config import load_tray_config

__all__ = ["MockSource", "TRAY_MM"]

# ---------------------------------------------------------------------------
# 码位几何单一真源（W13 修复）：四角 ArUco 的盘面布局只认 configs/tray.yaml。
# 此前 Mock 自行内缩到 45mm 而配置是 30mm，跨距 210mm 会被标定配到 240mm，
# 「检测点对配置点」的自洽门照样放行约 +14% 尺度误差——现同源后不会发生。
# ---------------------------------------------------------------------------
_CFG = load_tray_config()          # 仓库默认 configs/tray.yaml（缺失即抛 TrayConfigError）
TRAY_MM = _CFG.tray_mm             # 盘面边长（mm）
MARKER_MM = _CFG.marker_mm         # 码边长（mm）
CENTERS_MM: dict[int, tuple[float, float]] = dict(_CFG.centers_mm)

# 画布外缘（mm）：模拟相机视野略大于盘面。码中心在 tray.yaml 的 (30,30)mm
# （码贴盘角），其 side/4 静区伸出盘外 15mm——外缘 ≥15mm 即静区完整落 canvas，
# 取代旧「中心内缩 marker/4」的布局（该布局与 tray.yaml 不一致，已废止）。
_MARGIN_MM = 20.0

# 罗布斯塔生豆近似色（BGR）与缺陷色
_BEAN_BGR = (96, 120, 150)      # 浅褐绿生豆
_BEAN_JITTER = 28               # 逐豆明度抖动幅度
_BLACK_BGR = (24, 22, 20)       # 黑豆（主缺陷）
_BACKGROUND = (188, 192, 198)   # 亚克力浅灰（BGR）


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
        # 采集几何（单一真源 tray.yaml）：画布 = 盘面 + 四周外缘，盘面居中。
        self.px_per_mm = min(self.width, self.height) / (TRAY_MM + 2.0 * _MARGIN_MM)

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
        margin_mm = MARKER_MM * 1.5 + 10.0
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
        px_per_mm = self.px_per_mm
        ox = (w - TRAY_MM * px_per_mm) / 2.0  # 盘面居中偏移（画布外缘各 _MARGIN_MM）
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

        码心 mm 坐标取 ``CENTERS_MM``（configs/tray.yaml，单一几何真源，
        与打印板 make_aruco.py / 标定配置完全同源）。码外 1/4 边长白静区
        伸出盘外约 15mm，由画布外缘 ``_MARGIN_MM=20mm`` 完整保住
        （W2 实测坑：静区被裁则检测失败——用视野外缘而非内缩码心解决）。
        """
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        side_px = max(16, int(round(MARKER_MM * px_per_mm)))
        half_px = side_px // 2
        pad = max(4, side_px // 4)
        centers_mm = CENTERS_MM
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
