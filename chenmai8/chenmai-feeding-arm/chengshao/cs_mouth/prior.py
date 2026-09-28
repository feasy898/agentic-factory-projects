"""MouthPrior：mono 后端的先验尺度与相机参数（config/mouth_prior.json）。

开发指令 §1/§5.3：v3 无深度相机，mono 为主路径——口部距离 z 固定取先验
（默认 0.42m），横向/纵向误差 ±3–5cm 由交互设计吸收；距离核查（静态卷尺
三点实测）超线时只修本文件、不阻塞。

本类只承载几何/标定结构与缺省值；行为阈值（张嘴/转头/皱眉）在 cs_schema
冻结常量中，不在此重复。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

PKG_PARENT = Path(__file__).resolve().parents[1]  # chengshao/（包根）
DEFAULT_CONFIG_PATH = PKG_PARENT / "config" / "mouth_prior.json"

# 人脸关键点检测模型（一次性下载，权重不入库：.gitignore 含 *.task 与 models/）
DEFAULT_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/latest/face_landmarker.task"
)

# 缺省 cam→base 外参。约定（开发指令 §1 冻结）：
# base 系 X 朝用户 / Y 朝左 / Z 朝上；相机系 OpenCV（X 右 / Y 下 / Z 前向）。
# 旋转行：cam_z→base_x（光轴指向用户）、cam_x→-base_y、cam_y→-base_z；
# 平移：相机装于底盘前方 0.05m、右侧 0.20m、高 0.30m 处（缺省摆位，可标定覆盖）。
_DEFAULT_T_BASE_CAM = [
    [0.0, 0.0, 1.0, 0.05],
    [-1.0, 0.0, 0.0, -0.20],
    [0.0, -1.0, 0.0, 0.30],
    [0.0, 0.0, 0.0, 1.0],
]


@dataclass
class MouthPrior:
    """mono 先验尺度 + 内外参 + 模型路径。JSON 往返兼容（config/mouth_prior.json）。"""

    distance_m: float = 0.42  # 口部距离先验（米）
    mouth_height_m: float = 0.25  # 坐姿口部相对底盘高度缺省（米，首帧失效时的名义值）
    error_band_m: tuple[float, float] = (0.03, 0.05)  # mono 已知误差带 ±3–5cm
    calib_closed_ratio: float = 0.11  # 口径比标定：闭嘴簇上限（实测闭嘴 ≈0.057–0.10）
    calib_open_ratio: float = 0.23  # 口径比标定：张嘴簇下限（实测张嘴 ≈0.226–0.30）
    max_side: int = 640  # 推理前最长边缩放（CPU 时延保障）
    # 相机内参（参考分辨率下的缺省标称值；真机标定后覆盖）
    fx: float = 460.0
    fy: float = 460.0
    cx: float = 320.0
    cy: float = 240.0
    ref_width: int = 640
    ref_height: int = 480
    # cam→base 外参（4×4 齐次，行主序）
    T_base_cam: list[list[float]] = field(default_factory=lambda: [row[:] for row in _DEFAULT_T_BASE_CAM])
    model_path: str = "models/face_landmarker.task"  # 相对包根或 cwd，或绝对路径
    model_url: str = DEFAULT_MODEL_URL

    # ---- 序列化 -------------------------------------------------------------
    def to_dict(self) -> dict:
        d = asdict(self)
        d["error_band_m"] = list(self.error_band_m)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "MouthPrior":
        known = {f for f in cls.__dataclass_fields__}  # noqa: C416
        clean = {k: v for k, v in d.items() if k in known}
        if "error_band_m" in clean:
            clean["error_band_m"] = tuple(clean["error_band_m"])
        return cls(**clean)

    def save(self, path: str | Path = DEFAULT_CONFIG_PATH) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    # ---- 装载 ---------------------------------------------------------------
    @classmethod
    def load(cls, path: str | Path | None = None) -> "MouthPrior":
        """从 config 装载；文件缺失/损坏时回退缺省值（不抛异常，工程容错）。"""
        p = Path(path) if path is not None else DEFAULT_CONFIG_PATH
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        try:
            return cls.from_dict(d)
        except (TypeError, ValueError):
            return cls()

    def with_updates(self, **kw) -> "MouthPrior":
        return replace(self, **kw)

    # ---- 路径与几何 ----------------------------------------------------------
    def resolve_model_path(self) -> Path:
        """模型文件解析：绝对路径 → cwd 相对 → 包根相对，取第一个存在的。"""
        p = Path(self.model_path)
        if p.is_absolute():
            return p
        for base in (Path.cwd(), PKG_PARENT):
            cand = base / p
            if cand.is_file():
                return cand
        return PKG_PARENT / p  # 都不存在时返回包根意图路径（供报错信息）

    def intrinsics_for(self, width: int, height: int) -> tuple[float, float, float, float]:
        """按图像尺寸缩放内参（config 内参对应 ref_width×ref_height）。"""
        sx = width / float(self.ref_width)
        sy = height / float(self.ref_height)
        return self.fx * sx, self.fy * sy, self.cx * sx, self.cy * sy

    def matrix_base_cam(self):
        """T_base_cam 4×4 numpy（行主序）。"""
        import numpy as np

        m = np.array(self.T_base_cam, dtype=float)
        if m.shape != (4, 4):
            raise ValueError("T_base_cam 必须为 4×4")
        return m


def default_prior() -> MouthPrior:
    """代码内缺省（不经 config 文件）。"""
    return MouthPrior()
