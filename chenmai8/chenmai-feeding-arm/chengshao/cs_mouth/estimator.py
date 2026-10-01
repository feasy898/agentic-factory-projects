"""MouthEstimator：口部三维估计（接口契约 §3.2；v1.1 增补腕部双职路径）。

mono 主路径管线（每帧）::

    BGR 图 → 最长边缩放(prior.max_side) → 人脸 478 关键点 + 头姿矩阵 + blendshapes
    → 口中心像素(上下内唇 13/14 均值)
    → jaw_open = 几何口径比 gap/eye 线性映射（标定常数在 prior；
      静帧上 blendshape jawOpen 实测不区分张闭嘴，见 assets/face_samples/README）
    → frown = blendshape mouthFrown 左右均值（browDown 在微笑时误报，弃用）
    → 头姿 yaw/pitch/roll = 面部变换矩阵欧拉分解（yaw 绕相机竖直轴，转头判 |yaw|）
    → mono 距离（prior.mode 切换，契约 v1.1）:
        fixed: 相机系射线 × prior.distance_m（顶部相机回退路径）
        ipd:   Z = fx × prior.ipd_m / ipd_px（腕部双职：瞳距先验，近距 20–50cm）
    → depth: 关键点像素查深度
    → cam→base：fixed/depth 用 prior.T_base_cam；
      v1.1 传 cam_pose=(T_base_flange, T_flange_cam) 时 T_base_cam = FK × 手眼外参
    → MouthPose（base 系）；提供 cam_pose 的帧 source="wrist"（契约 v1.1）

失效帧行为（契约 §3.1）：valid=False，x/y/z 沿用上一有效值（无历史时用名义位姿
[prior.distance_m, 0, prior.mouth_height_m]），confidence=0。

线程模型：单线程使用（行为树 tick 内直调），不加锁。
"""

from __future__ import annotations

import math
import time
from typing import Callable, Literal

import numpy as np

from ._schema import MouthPose, MouthSource
from .prior import IPD_PX_MIN, IPD_Z_RANGE_M, IRIS_CENTER_L, IRIS_CENTER_R, MouthPrior

# ---- 人脸关键点索引（canonical face mesh，478 点） ---------------------------
_LIP_UPPER_INNER = 13  # 上内唇中心
_LIP_LOWER_INNER = 14  # 下内唇中心
_EYE_OUTER_L = 33  # 左眼外角（图像左侧）
_EYE_OUTER_R = 263  # 右眼外角（图像右侧）

BACKENDS: tuple[str, ...] = ("mono", "depth")

# blendshape 计数与关键点数（完整性校验）
_N_LANDMARKS_EXPECTED = 478


class MouthEstimator:
    """口部三维估计器。backend="mono"（演示主路径）| "depth"（延后保留）。

    契约签名（§3.2；v1.1 向后兼容扩展——新增参数全部可选、缺省行为不变）::

        __init__(backend="mono", prior: MouthPrior,
                 pose_provider: Callable[[], tuple] | None = None)
        from_bgr(img, depth=None, *, cam_pose=None)

    - ``pose_provider``：无参函数，返回 ``(T_base_flange, T_flange_cam)``（4×4）；
      提供后每次 ``from_bgr`` 未显式传 ``cam_pose`` 时自动取用（行为树接 FK 用）。
    - ``cam_pose``：单帧覆盖的 ``(T_base_flange, T_flange_cam)``；提供该参数（或
      pose_provider 生效）时走 IPD 估距、``source="wrist"``（腕部双职契约 v1.1）。
    prior 缺省时从 config/mouth_prior.json 装载（便利重载，不改变契约用法）。
    """

    def __init__(
        self,
        backend: Literal["mono", "depth"] = "mono",
        prior: MouthPrior | None = None,
        pose_provider: Callable[[], tuple] | None = None,
    ) -> None:
        if backend not in BACKENDS:
            raise ValueError(f"backend 必须取 {BACKENDS}，收到 {backend!r}")
        self.backend = backend
        self.prior = prior if prior is not None else MouthPrior.load()
        self.pose_provider = pose_provider
        self._landmarker = None  # 惰性初始化（首次 from_bgr 时加载模型）

    # ---- 对外主入口 ----------------------------------------------------------
    def from_bgr(
        self,
        img: np.ndarray,
        depth: np.ndarray | None = None,
        *,
        cam_pose: tuple | None = None,
    ) -> MouthPose:
        """BGR 图（+可选深度图，与 RGB 对齐、单位米或毫米）→ MouthPose（base 系）。

        v1.1：``cam_pose=(T_base_flange, T_flange_cam)`` 启用腕部双职路径（IPD 估距 +
        FK 位姿换算，``source="wrist"``）；缺省 None 时行为与 v1.0 完全一致。
        """
        if img is None or getattr(img, "ndim", 0) != 3:
            return self._invalid_pose(time.time_ns(), "输入图像为空或非 3 通道")
        ts = time.time_ns()

        # v1.1：解析相机位姿（单帧参数优先，其次 pose_provider）
        T_pose = cam_pose if cam_pose is not None else (
            self.pose_provider() if self.pose_provider is not None else None
        )
        if T_pose is not None:
            if self.backend != "mono":
                raise ValueError("cam_pose（腕部双职）仅支持 backend='mono'")
            T_base_cam = self.prior.compose_cam_pose(T_pose[0], T_pose[1])
            use_ipd = True
        else:
            T_base_cam = None
            use_ipd = self.backend == "mono" and self.prior.mode == "ipd"

        work = self._prepare(img)
        result = self._detect(work)
        if result is None:
            return self._invalid_pose(ts, "未检出人脸")
        landmarks, blendshapes, head_from_matrix = result
        h, w = work.shape[:2]

        # 口中心像素与几何量
        pl = np.asarray([[p.x, p.y] for p in landmarks], dtype=float)
        mouth_xy = (pl[_LIP_UPPER_INNER] + pl[_LIP_LOWER_INNER]) / 2.0
        u = float(mouth_xy[0]) * w
        v = float(mouth_xy[1]) * h
        # 口径比在归一化坐标下计算（尺度约简，与标定一致）；像素尺度仅供置信度
        eye_n = float(np.linalg.norm(pl[_EYE_OUTER_L] - pl[_EYE_OUTER_R]))
        gap_n = float(np.linalg.norm(pl[_LIP_UPPER_INNER] - pl[_LIP_LOWER_INNER]))
        ratio = gap_n / max(eye_n, 1e-9)
        eye_px = eye_n * max(w, h)
        jaw_open = self._ratio_to_jaw(ratio)
        frown = self._blendshape_frown(blendshapes)
        head_yaw, head_pitch, head_roll = head_from_matrix

        # 三维：mono=固定先验 / IPD 瞳距估距（v1.1）；depth=像素查深
        source = MouthSource(self.backend)
        if self.backend == "mono":
            if use_ipd:
                pos_cam = self._ipd_ray_to_cam(pl, u, v, w, h)
                if pos_cam is None:
                    return self._invalid_pose(ts, "IPD 估距不可靠（过远/过小/出量程）")
                source = MouthSource.WRIST
            else:
                pos_cam = self._mono_ray_to_cam(u, v, w, h)
        else:
            pos_cam = self._depth_lookup(u, v, depth)
            if pos_cam is None:
                return self._invalid_pose(ts, "深度缺失/越界")

        pos_base = self._to_base(pos_cam, T_base_cam)
        conf = self._confidence(u, v, w, h, eye_px=eye_px)
        self._last_valid_pos = pos_base
        return MouthPose(
            ts_ns=ts,
            valid=True,
            x=float(pos_base[0]),
            y=float(pos_base[1]),
            z=float(pos_base[2]),
            jaw_open=jaw_open,
            frown=frown,
            head_yaw=head_yaw,
            head_pitch=head_pitch,
            head_roll=head_roll,
            source=source,
            confidence=conf,
        )

    # ---- 内部 -----------------------------------------------------------------
    def _prepare(self, img: np.ndarray) -> np.ndarray:
        """最长边缩放到 prior.max_side（CPU 时延保障；小图不动）。"""
        max_side = int(self.prior.max_side)
        h, w = img.shape[:2]
        long_side = max(h, w)
        if long_side <= max_side:
            return img
        s = max_side / float(long_side)
        import cv2

        return cv2.resize(img, (int(round(w * s)), int(round(h * s))), interpolation=cv2.INTER_AREA)

    def _ensure_loaded(self):
        if self._landmarker is None:
            model_file = self.prior.resolve_model_path()
            if not model_file.is_file():
                raise FileNotFoundError(
                    "未找到人脸关键点模型："
                    f"{model_file}\n"
                    f"请执行 python scripts/fetch_models.py（或下载 {self.prior.model_url} "
                    "放到 models/face_landmarker.task）"
                )
            # 以字节流加载：绕开 Windows 下 C 层对非 ASCII 路径的限制
            model_bytes = model_file.read_bytes()
            import mediapipe as mp
            from mediapipe.tasks.python import vision
            from mediapipe.tasks.python.core.base_options import BaseOptions

            options = vision.FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_buffer=model_bytes),
                running_mode=vision.RunningMode.IMAGE,
                num_faces=1,
                output_face_blendshapes=True,
                output_facial_transformation_matrixes=True,
            )
            self._landmarker = vision.FaceLandmarker.create_from_options(options)
        return self._landmarker

    def _detect(self, work: np.ndarray):
        import cv2
        import mediapipe as mp

        landmarker = self._ensure_loaded()
        rgb = cv2.cvtColor(work, cv2.COLOR_BGR2RGB)
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        res = landmarker.detect(mp_img)
        if not res.face_landmarks:
            return None
        landmarks = res.face_landmarks[0]
        if len(landmarks) < _N_LANDMARKS_EXPECTED:  # 关键点不完整按失效处理
            return None
        bs: dict[str, float] = {}
        if res.face_blendshapes:
            bs = {c.category_name: float(c.score) for c in res.face_blendshapes[0]}
        head = self._head_from_matrix(res.facial_transformation_matrixes)
        return landmarks, bs, head

    @staticmethod
    def _head_from_matrix(mats) -> tuple[float, float, float]:
        """面部变换矩阵（cam→face）→ 欧拉角（rad）。

        分解约定 R = Ry(yaw)·Rx(pitch)·Rz(roll)：yaw 绕相机竖直轴（转头），
        pitch 绕相机横轴（点头），roll 绕光轴（歪头）。
        """
        if not mats:
            return 0.0, 0.0, 0.0
        R = np.asarray(mats[0], dtype=float)[:3, :3]
        yaw = math.atan2(R[0, 2], R[2, 2])
        pitch = math.atan2(-R[1, 2], math.hypot(R[0, 2], R[2, 2]))
        roll = math.atan2(R[1, 0], R[1, 1])
        return yaw, pitch, roll

    def _ratio_to_jaw(self, ratio: float) -> float:
        """几何口径比 → jaw_open∈[0,1]（标定常数见 prior；阈值用 cs_schema 冻结值）。"""
        lo = self.prior.calib_closed_ratio
        hi = self.prior.calib_open_ratio
        if hi <= lo:
            return 0.0
        return float(min(1.0, max(0.0, (ratio - lo) / (hi - lo))))

    @staticmethod
    def _blendshape_frown(bs: dict[str, float]) -> float:
        """皱眉强度：mouthFrown 左右均值（browDown 微笑误报大，不采用）。"""
        a = bs.get("mouthFrownLeft", 0.0)
        b = bs.get("mouthFrownRight", 0.0)
        return float(min(1.0, max(0.0, (a + b) / 2.0)))

    def _mono_ray_to_cam(self, u: float, v: float, w: int, h: int) -> np.ndarray:
        """mono（fixed 模式）：口中心像素射线 × 固定先验距离（相机系）。"""
        fx, fy, cx, cy = self.prior.intrinsics_for(w, h)
        ray = np.array([(u - cx) / fx, (v - cy) / fy, 1.0])
        return ray * (self.prior.distance_m / float(np.linalg.norm(ray)))

    def _ipd_ray_to_cam(self, pl: np.ndarray, u: float, v: float,
                        w: int, h: int) -> np.ndarray | None:
        """mono（v1.1 ipd 模式，腕部双职）：瞳距先验估距（相机系）。

        Z = fx × ipd_m / ipd_px，ipd_px = 左右虹膜中心（468/473）像素距；
        射线方向仍由口中心像素给出。距离出 [IPD_Z_RANGE_M] 量程或 ipd_px
        过小（< IPD_PX_MIN，过远/分辨率不足）时返回 None（按失效帧处理）。
        """
        fx, fy, cx, cy = self.prior.intrinsics_for(w, h)
        iris = np.asarray(
            [[pl[IRIS_CENTER_R][0] * w, pl[IRIS_CENTER_R][1] * h],
             [pl[IRIS_CENTER_L][0] * w, pl[IRIS_CENTER_L][1] * h]],
            dtype=float,
        )
        ipd_px = float(np.linalg.norm(iris[0] - iris[1]))
        if ipd_px < IPD_PX_MIN:
            return None
        z = float(fx) * float(self.prior.ipd_m) / ipd_px
        if not (IPD_Z_RANGE_M[0] <= z <= IPD_Z_RANGE_M[1]):
            return None
        ray = np.array([(u - cx) / fx, (v - cy) / fy, 1.0])
        return ray * (z / float(np.linalg.norm(ray)))

    def _depth_lookup(self, u: float, v: float, depth: np.ndarray | None) -> np.ndarray | None:
        """depth 后端：口中心 5×5 窗口中值查深 → 像素反演（相机系）。

        深度单位：浮点图按米；整型图按毫米（>50 自动判定为毫米）。
        """
        if depth is None or getattr(depth, "ndim", 0) != 2:
            return None
        dh, dw = depth.shape[:2]
        uu = int(min(max(round(u), 2), dw - 3))
        vv = int(min(max(round(v), 2), dh - 3))
        win = depth[vv - 2 : vv + 3, uu - 2 : uu + 3].astype(float)
        finite = win[np.isfinite(win)]
        if finite.size == 0:
            return None
        z = float(np.median(finite))
        if np.issubdtype(depth.dtype, np.integer) or z > 50.0:
            z /= 1000.0  # 毫米 → 米
        if not (0.05 <= z <= 3.0):  # 口部场景合理量程
            return None
        fx, fy, cx, cy = self.prior.intrinsics_for(dw, dh)
        return np.array([(u - cx) * z / fx, (v - cy) * z / fy, z])

    def _to_base(self, pos_cam: np.ndarray, T_base_cam: np.ndarray | None = None) -> np.ndarray:
        """cam→base：v1.1 传入 T_base_cam（腕部双职 FK×手眼）时用之，否则用 prior 配置。"""
        T = self.prior.matrix_base_cam() if T_base_cam is None else T_base_cam
        return (T @ np.array([pos_cam[0], pos_cam[1], pos_cam[2], 1.0]))[:3]

    def _confidence(self, u: float, v: float, w: int, h: int, eye_px: float) -> float:
        """启发式置信度：贴边/脸小衰减（无真值，仅排序用；契约约束 0-1）。"""
        conf = 0.90 if self.backend == "mono" else 0.85
        m = 0.03
        if u < w * m or u > w * (1 - m) or v < h * m or v > h * (1 - m):
            conf -= 0.15
        if eye_px < 12.0:
            conf -= 0.30
        return float(min(1.0, max(0.0, conf)))

    def _invalid_pose(self, ts: int, _reason: str) -> MouthPose:
        """失效帧：沿用上一有效值（无历史用名义位姿），confidence=0（契约 §3.1）。"""
        if getattr(self, "_last_valid_pos", None) is not None:
            pos = np.asarray(self._last_valid_pos, dtype=float)
        else:
            pos = np.array([self.prior.distance_m, 0.0, self.prior.mouth_height_m])
        return MouthPose(
            ts_ns=ts,
            valid=False,
            x=float(pos[0]),
            y=float(pos[1]),
            z=float(pos[2]),
            jaw_open=0.0,
            frown=0.0,
            head_yaw=0.0,
            head_pitch=0.0,
            head_roll=0.0,
            source=MouthSource(self.backend),
            confidence=0.0,
        )
