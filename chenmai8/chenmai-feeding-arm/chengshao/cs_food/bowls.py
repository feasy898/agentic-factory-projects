"""选碗：场景相机基准码检测与碗位选择（开发指令 §5.5）。

3 碗 3 码：码贴碗沿，码编号 → 碗序号映射在 config/bowl_markers.json。
行为树黑板键 ``bowl_sel: int`` 由 ``BowlSelector.select()`` 给出：
取画面中最大可见码（离得最近）对应的碗序号；无已登记可见码时返回 None，
由上层保持上一选择或触发重找。未登记的码一律忽略（他人干扰物不误选）。
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .config import BowlConfig, load_bowl_config


@dataclass(frozen=True)
class BowlMarker:
    """一个可见碗码的检测结果。"""

    marker_id: int  # 基准码编号（config 已登记）
    bowl_index: int  # 碗序号（黑板键 bowl_sel 的取值域）
    center_px: tuple[int, int]  # 码中心像素坐标 (x, y)
    side_px: float  # 码边长（像素，四边均值；近似"离相机远近"）

    def validate(self) -> None:
        if self.marker_id < 0 or self.bowl_index < 0:
            raise ValueError("marker_id/bowl_index 必须非负")
        if self.side_px < 0:
            raise ValueError("side_px 必须非负")


def _validate_image(img: object) -> np.ndarray:
    """校验输入为非空 uint8 灰度或 BGR 图，返回原数组。"""
    if not isinstance(img, np.ndarray):
        raise ValueError("img 必须是 numpy.ndarray")
    if img.dtype != np.uint8:
        raise ValueError(f"img 必须是 uint8，实际 dtype={img.dtype}")
    if img.ndim == 3 and img.shape[2] not in (1, 3):
        raise ValueError(f"img 通道数必须为 1 或 3，实际 shape={img.shape}")
    if img.ndim not in (2, 3):
        raise ValueError(f"img 必须是 HxW（灰度）或 HxWx3（BGR），实际 shape={img.shape}")
    if img.shape[0] == 0 or img.shape[1] == 0:
        raise ValueError("img 尺寸为空")
    return img


class BowlSelector:
    """基准码选碗器（检测由 OpenCV 基准码模块完成）。

    参数：
    - config_path：bowl_markers 配置路径；None 用缺省 config/bowl_markers.json；
    - dictionary：覆盖配置中的码字典（注入自定义字典对象，测试/扩展用）。
    """

    def __init__(self, config_path: str | object | None = None, dictionary: object | None = None) -> None:
        cfg: BowlConfig = load_bowl_config(config_path)
        self._marker_to_bowl: dict[int, int] = dict(cfg.marker_to_bowl)
        self._min_side_px = cfg.min_side_px
        self._cam_ref = cfg.cam_ref
        if dictionary is not None:
            self._dictionary = dictionary
        else:
            self._dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, cfg.dictionary))
        self._detector = cv2.aruco.ArucoDetector(
            self._dictionary, cv2.aruco.DetectorParameters()
        )

    @property
    def cam_ref(self) -> str:
        return self._cam_ref

    def detect(self, img: np.ndarray) -> list[BowlMarker]:
        """检测场景图中所有已登记碗码，按边长降序（并列时按碗序号升序）。"""
        frame = _validate_image(img)
        if frame.ndim == 3:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = self._detector.detectMarkers(frame)

        found: list[BowlMarker] = []
        if ids is None:
            return found
        for corner, raw_id in zip(corners, ids.ravel()):
            marker_id = int(raw_id)
            bowl_index = self._marker_to_bowl.get(marker_id)
            if bowl_index is None:
                continue  # 未登记码：忽略
            pts = corner[0]
            side = float(
                np.mean([np.linalg.norm(pts[i] - pts[(i + 1) % 4]) for i in range(4)])
            )
            if side < self._min_side_px:
                continue  # 过小码（过远/噪声）：按 config 过滤
            cx, cy = pts.mean(axis=0)
            found.append(
                BowlMarker(
                    marker_id=marker_id,
                    bowl_index=bowl_index,
                    center_px=(int(round(float(cx))), int(round(float(cy)))),
                    side_px=side,
                )
            )
        found.sort(key=lambda m: (-m.side_px, m.bowl_index))
        return found

    def select(self, img: np.ndarray) -> int | None:
        """给出 bowl_sel：最大可见码对应的碗序号；无可选码时 None。"""
        markers = self.detect(img)
        return markers[0].bowl_index if markers else None


__all__ = ["BowlMarker", "BowlSelector"]
