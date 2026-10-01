"""基准码选碗（spec §3 / §3.1）。

BowlSelector.detect：灰度化 → ArUco 检测 → 只留已登记码 → 码边长=四边均值 →
按（边长降序，碗序升序）排序；未登记码一律忽略。
select：最大可见码（离得最近）对应碗序；无可选码返回 None。

检测预处理与参数（spec §3.1，代码为权威）：当前实现 = 仅灰度化 + 全缺省检测参数
（ArucoDetector(dictionary, DetectorParameters())）；调用方无预二值化、无自适应
窗口调整、无任何参数覆盖。ids 形态：cv2 5.0.0 返回扁平 (N,) int32，4.x 系列为
(N,1) 列向量——统一 ids.ravel() 后逐码迭代，跨版本安全。
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .config import BowlConfig, load_bowl_config


@dataclass(frozen=True)
class BowlMarker:
    """一个已登记基准码的观测。"""

    marker_id: int
    bowl_index: int
    side_px: float  # 码边长 = 四边均值
    center_px: tuple[int, int]  # 像素坐标 (x, y)


def _validate_img(img: object) -> np.ndarray:
    """输入校验：ndarray / uint8 / 2D 灰度或 3 通道 BGR / 非空，否则 ValueError。"""
    if not isinstance(img, np.ndarray):
        raise ValueError(f"场景帧必须是 numpy ndarray，得到 {type(img).__name__}")
    if img.dtype != np.uint8:
        raise ValueError(f"场景帧必须是 uint8，得到 {img.dtype}")
    if img.ndim == 2:
        pass  # 灰度
    elif img.ndim == 3 and img.shape[2] == 3:
        pass  # BGR
    else:
        raise ValueError(f"场景帧必须是 2D 灰度或 HxWx3 BGR，得到 shape={img.shape}")
    if img.shape[0] == 0 or img.shape[1] == 0:
        raise ValueError(f"场景帧不能为空图，得到 shape={img.shape}")
    return img


class BowlSelector:
    """基准码（ArUco）→ 碗序选择。"""

    def __init__(self, config_path: str | None = None, cam_ref: str | None = None) -> None:
        cfg: BowlConfig = load_bowl_config(config_path)
        self.cam_ref: str = cam_ref if cam_ref is not None else cfg.cam_ref
        self._marker_to_bowl: dict[int, int] = dict(cfg.marker_to_bowl)
        self._min_side_px: float = float(cfg.min_side_px)
        dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, cfg.dictionary))
        # 全缺省检测参数（spec §3.1：无预二值化 / 无自适应窗口 / 无参数覆盖）
        self._detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())

    def detect(self, img: np.ndarray) -> list[BowlMarker]:
        img = _validate_img(img)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        corners, ids, _ = self._detector.detectMarkers(gray)
        if ids is None or corners is None:
            return []
        markers: list[BowlMarker] = []
        # ids.ravel()：把 5.0 扁平 (N,) 与 4.x (N,1) 列向量都归一成"每码一元素"
        for corner, mid in zip(corners, ids.ravel()):
            marker_id = int(mid)
            bowl_index = self._marker_to_bowl.get(marker_id)
            if bowl_index is None:
                continue  # 未登记码一律忽略（他人干扰物不误选）
            pts = np.asarray(corner, dtype=np.float64).reshape(-1, 2)  # (4,2)
            sides = [
                float(np.linalg.norm(pts[i] - pts[(i + 1) % 4])) for i in range(4)
            ]
            side_px = sum(sides) / 4.0  # 码边长 = 四边均值
            if side_px < self._min_side_px:
                continue  # 过小码 = 过远/噪声，过滤
            cx, cy = pts.mean(axis=0)
            markers.append(
                BowlMarker(
                    marker_id=marker_id,
                    bowl_index=bowl_index,
                    side_px=side_px,
                    center_px=(int(round(float(cx))), int(round(float(cy)))),
                )
            )
        markers.sort(key=lambda m: (-m.side_px, m.bowl_index))  # 边长降序，碗序升序
        return markers

    def select(self, img: np.ndarray) -> int | None:
        markers = self.detect(img)
        if not markers:
            return None  # 上层保持上一选择或下 tick 重扫
        return markers[0].bowl_index  # 最大可见码 = 离得最近
