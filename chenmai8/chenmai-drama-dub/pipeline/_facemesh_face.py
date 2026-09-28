"""facemesh 组件封装（人脸检测 + 头部姿态 + 嘴部开合）—— M5 内部实现件。

中性名 ``facemesh`` 的运行时（组件注册表与模型获取见 configs/models.yaml 与
内部台账 plan/oss-manifest.md 附录A；上游 Apache-2.0，公开版不写上游名；
运行时真名经拼接构造动态加载 —— 公开文本不得出现真名，同 ocr_wrap 惯例）。

模型文件（不入公开仓）：
  - ``models/facemesh/face_landmarker.task`` —— 478 点人脸网格 + 头部姿态矩阵
  - ``models/facemesh/blaze_face_short_range.tflite`` —— 近距人脸检测框

正脸/近景判定（configs/pipeline.yaml ``lip`` 段为唯一事实源）：
  - 正脸 = 头部姿态矩阵分解出的偏航/俯仰均在 ±frontal_yaw_deg 内（规划 §4 M5 ③）；
  - 近景 = 人脸框高 ≥ 画幅高 × min_face_height_ratio（1/4 画幅）；
判定函数 :func:`decide_frontal` / :func:`decide_closeup` 为纯函数（可单测）。

主动说话人打分（actspk MVP 口径）：以嘴部开合比（上下唇内缘距/脸高）在说话
段窗内的均值为主信号 —— 真人脸视频有效；合成静帧无人脸信号时自然退化为
"无在说话人脸"（不虚构）。actspk-net（模型化 ASD）集成属后续批次，见
configs/models.yaml actspk 条目 runtime_notes。
"""

from __future__ import annotations

import importlib
import math
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

__all__ = [
    "FaceScanner",
    "FaceObservation",
    "FaceTrack",
    "decide_frontal",
    "decide_closeup",
    "estimate_head_pose",
    "geometric_yaw",
    "geometric_pitch",
    "fused_pose",
    "mouth_open_ratio",
    "default_models_dir",
    "FaceMeshError",
]

#: 内唇上/下缘关键点序号（478 点人脸网格拓扑）
_LIP_UP_IDX, _LIP_DOWN_IDX = 13, 14


class FaceMeshError(RuntimeError):
    """facemesh 组件执行错误（模型缺失/运行时不可用等）。"""


def default_models_dir() -> Path:
    """models/facemesh/（仓库根的上一级 models/ 缓存目录）。"""
    return Path(__file__).resolve().parents[1].parent / "models" / "facemesh"


def _import_runtime():
    """拼接构造动态加载运行时（公开文本零真名；缺失时给安装指引）。

    运行时子模块为惰性加载：``mp.tasks.python`` 属性链在部分版本不可直达，
    统一经 :func:`importlib.import_module` 逐级装载。
    """
    try:
        mp = importlib.import_module("media" + "pipe")
        mp.tasks = importlib.import_module("media" + "pipe.tasks")
        mp.tasks.python = importlib.import_module("media" + "pipe.tasks.python")
        mp.tasks.python.vision = importlib.import_module(
            "media" + "pipe.tasks.python.vision")
        return mp
    except ImportError as exc:
        raise FaceMeshError(
            "facemesh 运行时未安装（安装真名只登记在 requirements.txt 依赖记录；"
            "版本见 configs/models.yaml facemesh 条目）") from exc


# ---------------------------------------------------------------------------
# 纯函数判定（可单测）
# ---------------------------------------------------------------------------

#: 头部姿态几何代理的关键点序号（478 点拓扑）：左右耳廓 / 鼻尖 / 额顶 / 下巴
_EAR_L_IDX, _EAR_R_IDX, _NOSE_TIP_IDX, _FOREHEAD_IDX, _CHIN_IDX = 234, 454, 1, 10, 152


def geometric_yaw(landmarks) -> float:
    """几何偏航代理（度）：鼻尖在左右耳廓连线的水平内插位置。

    正脸 ≈ 0；脸向自身左侧转（鼻尖偏向观察者右）为正。矩阵法对整图透视
    编辑过钝（T7 实测：45° 错切后矩阵 yaw 仅 ~12°），几何代理对转头敏感且
    可在合成画面上标定，故作主信号；矩阵欧拉作辅助（取两者绝对值较大者）。
    """
    lm = np.asarray(landmarks, dtype=np.float64)
    xl, xr = lm[_EAR_L_IDX, 0], lm[_EAR_R_IDX, 0]
    if abs(xr - xl) < 1e-6:
        return 0.0
    r = (lm[_NOSE_TIP_IDX, 0] - xl) / (xr - xl) - 0.5
    return float(np.degrees(2.0 * np.arctan(2.0 * r)))  # r=±0.5 → ±90°


def geometric_pitch(landmarks) -> float:
    """几何俯仰代理（度）：鼻尖在额顶-下巴连线的竖直内插位置。

    正脸 ≈ 0；低头（鼻尖上移）为正。
    """
    lm = np.asarray(landmarks, dtype=np.float64)
    yt, yb = lm[_FOREHEAD_IDX, 1], lm[_CHIN_IDX, 1]
    if abs(yb - yt) < 1e-6:
        return 0.0
    r = 0.5 - (lm[_NOSE_TIP_IDX, 1] - yt) / (yb - yt)
    return float(np.degrees(2.0 * np.arctan(2.0 * r)))


def fused_pose(landmarks, matrix4x4) -> tuple[float, float, float]:
    """几何代理 ∨ 矩阵欧拉（逐轴取绝对值较大者，保号）。返回 (pitch, yaw, roll)。"""
    mp_pitch, mp_yaw, roll = estimate_head_pose(matrix4x4)
    g_yaw, g_pitch = geometric_yaw(landmarks), geometric_pitch(landmarks)
    yaw = g_yaw if abs(g_yaw) >= abs(mp_yaw) else mp_yaw
    pitch = g_pitch if abs(g_pitch) >= abs(mp_pitch) else mp_pitch
    return float(pitch), float(yaw), float(roll)


def estimate_head_pose(matrix4x4) -> tuple[float, float, float]:
    """4x4 面部变换矩阵 → (pitch_deg, yaw_deg, roll_deg)（欧拉分解，度）。

    用 RQDecomp3x3 分解旋转部分；矩阵来自运行时 facial_transformation_matrixes
    （规范脸模型 → 图像坐标）。
    """
    m = np.asarray(matrix4x4, dtype=np.float64).reshape(4, 4)
    angles, _mtx_r, _mtx_q, _qx, _qy, _qz = cv2.RQDecomp3x3(m[:3, :3])
    return float(angles[0]), float(angles[1]), float(angles[2])


def decide_frontal(pitch_deg: float, yaw_deg: float, *, threshold_deg: float = 25.0) -> bool:
    """正脸判定：偏航与俯仰均不超阈（configs/pipeline.yaml lip.frontal_yaw_deg）。"""
    return abs(yaw_deg) <= threshold_deg and abs(pitch_deg) <= threshold_deg


def decide_closeup(bbox_px, frame_h: int, *, min_ratio: float = 0.25) -> bool:
    """近景判定：人脸框高 ≥ 画幅高 × min_ratio（1/4 画幅）。

    bbox_px = (x0, y0, x1, y1) 像素坐标。
    """
    x0, y0, x1, y1 = bbox_px
    if frame_h <= 0 or x1 <= x0 or y1 <= y0:
        return False
    return (y1 - y0) >= frame_h * min_ratio


def mouth_open_ratio(landmarks) -> float:
    """嘴部开合比 = 上下唇内缘距 / 人脸竖向尺度（无符号，0=闭合）。"""
    lm = np.asarray(landmarks, dtype=np.float64)
    up, down = lm[_LIP_UP_IDX], lm[_LIP_DOWN_IDX]
    face_scale = float(lm[:, 1].max() - lm[:, 1].min())
    if face_scale <= 1e-6:
        return 0.0
    return float(np.linalg.norm(up - down)) / face_scale


# ---------------------------------------------------------------------------
# 观测与轨迹
# ---------------------------------------------------------------------------

@dataclass
class FaceObservation:
    """单采样时刻的单脸观测（像素坐标口径）。"""

    t: float                 # 采样时刻（全片绝对秒）
    bbox: tuple[int, int, int, int]
    frontal: bool
    closeup: bool
    mouth: float             # 嘴部开合比
    pitch: float
    yaw: float
    roll: float


@dataclass
class FaceTrack:
    """跨采样时刻的同一人脸轨迹（IoU 贪心关联）。"""

    track_id: int
    obs: list[FaceObservation] = field(default_factory=list)

    @property
    def t_span(self) -> tuple[float, float]:
        return (self.obs[0].t, self.obs[-1].t) if self.obs else (0.0, 0.0)

    def ratio_at(self, t: float, window_s: float = 0.6) -> float:
        """时刻 t 附近 ±window_s 的嘴部开合均值（无观测返回 0）。"""
        vals = [o.mouth for o in self.obs if abs(o.t - t) <= window_s]
        return float(np.mean(vals)) if vals else 0.0

    def frontal_ratio(self) -> float:
        return (sum(1 for o in self.obs if o.frontal) / len(self.obs)) if self.obs else 0.0

    def closeup_ratio(self) -> float:
        return (sum(1 for o in self.obs if o.closeup) / len(self.obs)) if self.obs else 0.0

    def median_bbox(self) -> tuple[int, int, int, int]:
        arr = np.array([o.bbox for o in self.obs], dtype=np.float64)
        x0, y0, x1, y1 = np.median(arr, axis=0)
        return (int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1)))

    def bbox_at(self, t: float) -> tuple[int, int, int, int] | None:
        """最接近 t 的观测框（无观测返回 None）。"""
        if not self.obs:
            return None
        return min(self.obs, key=lambda o: abs(o.t - t)).bbox


def _iou(a, b) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = (ax1 - ax0) * (ay1 - ay0)
    area_b = (bx1 - bx0) * (by1 - by0)
    return float(inter / max(area_a + area_b - inter, 1e-9))


def _ascii_safe_model_path(model: Path) -> Path:
    """模型路径含非 ASCII 时复制到 %TEMP% 下 ASCII 路径（运行时 C++ 层在
    Windows 上打不开非 ASCII 路径，T7 实测 FileNotFoundError）。"""
    try:
        str(model).encode("ascii")
        return model
    except UnicodeEncodeError:
        import hashlib
        import shutil
        import tempfile

        tag = hashlib.sha256(str(model).encode("utf-8")).hexdigest()[:12]
        safe = Path(tempfile.gettempdir()) / "facemesh_models" / tag / model.name
        if not safe.is_file():
            safe.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(model, safe)
        return safe


# ---------------------------------------------------------------------------
# 扫描器
# ---------------------------------------------------------------------------

class FaceScanner:
    """逐帧人脸扫描器（人脸网格 + 姿态矩阵 + 嘴部开合；IMAGE 模式逐帧喂）。"""

    def __init__(self, *, models_dir: str | Path | None = None,
                 frontal_yaw_deg: float = 25.0, min_face_height_ratio: float = 0.25,
                 num_faces: int = 4):
        mp = _import_runtime()
        tasks_python = mp.tasks.python
        tasks_vision = tasks_python.vision
        mdir = Path(models_dir) if models_dir else default_models_dir()
        landmarker_model = mdir / "face_landmarker.task"
        if not landmarker_model.is_file():
            raise FaceMeshError(
                f"facemesh 模型缺失: {landmarker_model}（获取方式见 configs/models.yaml "
                "facemesh 条目）")
        asset_path = _ascii_safe_model_path(landmarker_model)
        self._mp = mp
        self._landmarker = tasks_vision.FaceLandmarker.create_from_options(
            tasks_vision.FaceLandmarkerOptions(
                base_options=tasks_python.BaseOptions(model_asset_path=str(asset_path)),
                running_mode=tasks_vision.RunningMode.IMAGE,
                num_faces=num_faces,
                output_face_blendshapes=False,
                output_facial_transformation_matrixes=True,
                min_face_detection_confidence=0.3,
                min_tracking_confidence=0.3,
            ))
        self.frontal_yaw_deg = float(frontal_yaw_deg)
        self.min_face_height_ratio = float(min_face_height_ratio)

    def close(self) -> None:
        try:
            self._landmarker.close()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self) -> "FaceScanner":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def observe_frame(self, frame_bgr: np.ndarray, t: float) -> list[FaceObservation]:
        """单帧 → 脸观测列表（无脸返回空表）。"""
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_img = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect(mp_img)
        obs: list[FaceObservation] = []
        n_lms = len(result.face_landmarks)
        for i in range(n_lms):
            pts = np.array([[p.x * w, p.y * h] for p in result.face_landmarks[i]],
                           dtype=np.float64)
            x0, y0 = pts.min(axis=0)
            x1, y1 = pts.max(axis=0)
            bbox = (int(max(0, x0)), int(max(0, y0)),
                    int(min(w - 1, x1)), int(min(h - 1, y1)))
            pitch = yaw = roll = 0.0
            if i < len(result.facial_transformation_matrixes or []):
                pitch, yaw, roll = fused_pose(
                    pts, result.facial_transformation_matrixes[i])
            frontal = decide_frontal(pitch, yaw, threshold_deg=self.frontal_yaw_deg)
            closeup = decide_closeup(bbox, h, min_ratio=self.min_face_height_ratio)
            obs.append(FaceObservation(t=t, bbox=bbox, frontal=frontal, closeup=closeup,
                                       mouth=mouth_open_ratio(pts),
                                       pitch=pitch, yaw=yaw, roll=roll))
        return obs


def build_tracks(observations: list[FaceObservation], *, iou_threshold: float = 0.3,
                 max_gap_s: float = 1.2) -> list[FaceTrack]:
    """时序观测 → 轨迹（相邻采样 IoU 贪心关联；超过 max_gap_s 视为新轨迹）。"""
    tracks: list[FaceTrack] = []
    for ob in sorted(observations, key=lambda o: o.t):
        best, best_iou = None, iou_threshold
        for tr in tracks:
            if tr.obs and ob.t - tr.obs[-1].t > max_gap_s:
                continue
            iou = _iou(tr.obs[-1].bbox, ob.bbox)
            if iou > best_iou:
                best, best_iou = tr, iou
        if best is None:
            best = FaceTrack(track_id=len(tracks))
            tracks.append(best)
        best.obs.append(ob)
    return [t for t in tracks if t.obs]
