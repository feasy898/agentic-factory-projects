"""摄像头口部实时演示（开发指令 §8.2）：478 关键点 + jaw_open 实时条 + 转头报警。

讲稿落点（§8.2 原文）：
- **腕部相机双职**：舀取时看勺、送达时看脸——一颗相机两份工作
  （传感器复用，整机更便宜）；
- 近距瞳距先验（IPD≈63mm）估距误差 X cm（--wrist 模式实时显示估距），
  勺停口前 5cm、用户前倾自取；
- 深度相机是机构版高配选项（接口不变、无感切换，本演示不依赖）。

输入源（--source）：
  auto    摄像头优先，打不开自动回退内置视频（缺省）；
  camera  cv2.VideoCapture(--device)；
  video   内置视频源循环播放（assets/face_samples/face_demo_carousel.mp4，
          由 bundled/*.jpg 合成——无摄像头演示的缺省回退）；
  bundled 资产库真人样本轮播（assets/face_samples/bundled，视频缺失时的再回退）；
  cartoon 程序合成卡通脸（张嘴动画；纯离线、零样本依赖）。

用法（cwd 任意）::

    python scripts/demo_mouth.py                    # 自动选源交互窗口
    python scripts/demo_mouth.py --wrist            # 腕部双职（IPD 估距 + FK 位姿）
    python scripts/demo_mouth.py --frames 6 --out reports/demo_mouth_frames
                                                    # 无头冒烟：标注帧落盘，exit 0

按键（交互窗口）：q/ESC 退出；空格=软件急停演示提示。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

_SCRIPT_DIR = Path(__file__).resolve().parent
PKG_ROOT = _SCRIPT_DIR.parent
_REPO_ROOT = PKG_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from chengshao.cs_mouth.estimator import MouthEstimator  # noqa: E402
from chengshao.cs_mouth.imgio import (  # noqa: E402
    imread_u,
    imwrite_u,
    open_video_u,
    release_video_u,
)
from chengshao.cs_mouth.prior import MouthPrior  # noqa: E402
from chengshao.cs_mouth.synth import draw_cartoon_face  # noqa: E402
from chengshao.cs_orchestra.core import NOMINAL_T_FLANGE_CAM  # noqa: E402
from chengshao.cs_schema.constants import (  # noqa: E402
    FROWN_ASK_THRESHOLD,
    HEAD_YAW_TURN_THRESHOLD_RAD,
    JAW_OPEN_THRESHOLD,
)

BUNDLED_DIR = PKG_ROOT / "assets" / "face_samples" / "bundled"
BUNDLED_VIDEO = PKG_ROOT / "assets" / "face_samples" / "face_demo_carousel.mp4"


# ---- 输入源 ------------------------------------------------------------------------


class CameraSource:
    """实时摄像头；打不开抛 RuntimeError（调用方回退）。"""

    name = "camera"

    def __init__(self, device: int = 0) -> None:
        self.cap = cv2.VideoCapture(int(device))
        if not self.cap.isOpened():
            raise RuntimeError(f"摄像头 device={device} 打不开")

    def read(self):
        ok, frame = self.cap.read()
        return frame if ok else None

    def close(self) -> None:
        self.cap.release()


class VideoFileSource:
    """内置视频源循环播放（无摄像头时的缺省回退；中文路径安全 open）。

    由 assets/face_samples/bundled/*.jpg 合成（每帧驻留 0.6s @10fps）；
    播完自动从头循环，读帧失败重开一次后仍失败才抛错（由调用方再回退）。
    """

    name = "video"

    def __init__(self, path: Path = BUNDLED_VIDEO) -> None:
        self.path = Path(path)
        self.cap = open_video_u(self.path)
        if self.cap is None:
            raise RuntimeError(f"内置视频打不开：{self.path}")

    def read(self):
        ok, frame = self.cap.read()
        if not ok:  # 播完 -> 循环
            release_video_u(self.cap)
            self.cap = open_video_u(self.path)
            if self.cap is None:
                return None
            ok, frame = self.cap.read()
        return frame if ok else None

    def close(self) -> None:
        release_video_u(self.cap)


class BundledSource:
    """资产样本轮播（真人种子变体，~2fps 节奏由外部 sleep 控制）。"""

    name = "bundled"

    def __init__(self) -> None:
        self.files = sorted(BUNDLED_DIR.glob("*.jpg"))
        if not self.files:
            raise RuntimeError(f"内置样本缺失：{BUNDLED_DIR}")
        self.i = -1

    def read(self):
        self.i = (self.i + 1) % len(self.files)
        return imread_u(self.files[self.i])  # 中文路径安全读图

    def close(self) -> None:
        pass


class CartoonSource:
    """程序合成卡通脸：张嘴正弦动画（仅供人看；jaw 标定簇来自真人样本）。"""

    name = "cartoon"

    def __init__(self) -> None:
        self.t0 = time.perf_counter()

    def read(self):
        ph = (time.perf_counter() - self.t0) % 4.0
        mouth = float(np.clip(np.sin(ph / 4.0 * 2 * np.pi) * 0.5 + 0.5, 0.0, 1.0))
        return draw_cartoon_face(640, 480, mouth_open=mouth)

    def close(self) -> None:
        pass


def open_source(kind: str, device: int) -> object:
    if kind == "camera":
        return CameraSource(device)
    if kind == "video":
        return VideoFileSource()
    if kind == "bundled":
        return BundledSource()
    if kind == "cartoon":
        return CartoonSource()
    # auto：摄像头优先，回退内置视频，再回退样本轮播，最后卡通
    try:
        src = CameraSource(device)
        print("输入源：摄像头")
        return src
    except RuntimeError:
        pass
    try:
        src = VideoFileSource()
        print(f"输入源：内置视频循环（{src.path.name}；未检出可用摄像头）")
        return src
    except RuntimeError:
        pass
    try:
        src = BundledSource()
        print(f"输入源：内置样本轮播（{len(src.files)} 帧；内置视频缺失）")
        return src
    except RuntimeError:
        print("输入源：程序合成卡通脸（样本资产缺失）")
        return CartoonSource()


# ---- 478 关键点叠加（仅可视化；状态量一律以 MouthEstimator 输出为准） ----------------


class _LandmarkPainter:
    """惰性加载 FaceLandmarker，出归一化关键点像素坐标（画点用）。

    与 MouthEstimator 各自独立推理（一次模型加载 ~2s，逐帧 ~20ms）：
    演示要画全脸 478 点，而冻结契约 MouthPose 只携带状态量不带点集——
    两者并行不悖：点用于人看，状态用于逻辑。
    """

    def __init__(self, prior: MouthPrior) -> None:
        self._model_path = prior.resolve_model_path()
        self._landmarker = None
        self.available = self._model_path.is_file()

    def _ensure(self):
        if self._landmarker is None:
            import mediapipe as mp
            from mediapipe.tasks.python import vision
            from mediapipe.tasks.python.core.base_options import BaseOptions

            options = vision.FaceLandmarkerOptions(
                base_options=BaseOptions(
                    model_asset_buffer=self._model_path.read_bytes()),
                running_mode=vision.RunningMode.IMAGE,
                num_faces=1,
            )
            self._landmarker = vision.FaceLandmarker.create_from_options(options)
        return self._landmarker

    def points(self, img: np.ndarray) -> list[tuple[int, int]] | None:
        if not self.available:
            return None
        try:
            import mediapipe as mp

            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            res = self._ensure().detect(
                mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
            if not res.face_landmarks:
                return None
            h, w = img.shape[:2]
            return [(int(p.x * w), int(p.y * h)) for p in res.face_landmarks[0]]
        except Exception:  # noqa: BLE001 —— 可视化失败不影响状态链路
            return None


def draw_landmarks(img: np.ndarray, points: list[tuple[int, int]] | None) -> np.ndarray:
    """在图上画全脸关键点点云（青色小点；无点原样返回）。"""
    if not points:
        return img
    for u, v in points:
        cv2.circle(img, (u, v), 1, (220, 220, 80), -1, cv2.LINE_AA)
    return img


# ---- 标注叠加 ------------------------------------------------------------------------


def _bar(img, x, y, w, h, frac, color, label) -> None:
    frac = float(min(1.0, max(0.0, frac)))
    cv2.rectangle(img, (x, y), (x + w, y + h), (70, 70, 70), -1)
    cv2.rectangle(img, (x, y), (x + int(w * frac), y + h), color, -1)
    cv2.rectangle(img, (x, y), (x + w, y + h), (200, 200, 200), 1)
    cv2.putText(img, label, (x, y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                (235, 235, 235), 1, cv2.LINE_AA)


def annotate(img, pose, elapsed_ms: float, wrist_mode: bool) -> np.ndarray:
    h, w = img.shape[:2]
    panel_w = 300
    canvas = np.full((h, w + panel_w, 3), (28, 30, 34), np.uint8)
    canvas[:h, :w] = img

    if pose.valid:
        cv2.putText(canvas, "FACE OK", (10, 26), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (90, 200, 90), 2, cv2.LINE_AA)
    else:
        cv2.putText(canvas, "NO FACE", (10, 26), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (60, 60, 230), 2, cv2.LINE_AA)

    jaw = float(pose.jaw_open)
    yaw = abs(float(pose.head_yaw))
    turning = pose.valid and yaw > HEAD_YAW_TURN_THRESHOLD_RAD
    open_mouth = pose.valid and jaw > JAW_OPEN_THRESHOLD
    frowning = pose.valid and float(pose.frown) > FROWN_ASK_THRESHOLD

    # 转头报警横幅（§8.2：转头即停）
    if turning:
        cv2.rectangle(canvas, (0, h // 2 - 26), (w, h // 2 + 26), (40, 40, 210), -1)
        cv2.putText(canvas, "HEAD TURNED - HOLD", (16, h // 2 + 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)

    # 面部状态横幅
    banner = "MOUTH OPEN - DELIVER" if open_mouth else (
        "FROWN - PAUSE & ASK" if frowning else "tracking")
    b_color = (60, 180, 75) if open_mouth else ((60, 60, 230) if frowning
                                                else (150, 150, 150))
    cv2.rectangle(canvas, (0, h - 28), (w, h), (28, 30, 34), -1)
    cv2.putText(canvas, banner, (10, h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                b_color, 2, cv2.LINE_AA)

    # 右侧仪表面板
    px = w + 14
    _bar(canvas, px, 52, 260, 22, jaw, (80, 200, 80) if open_mouth else (120, 120, 120),
         f"jaw_open {jaw:.2f}  (thr {JAW_OPEN_THRESHOLD:.2f})")
    _bar(canvas, px, 112, 260, 22, yaw / (2 * HEAD_YAW_TURN_THRESHOLD_RAD),
         (60, 60, 230) if turning else (120, 120, 120),
         f"head_yaw {np.degrees(yaw):.0f} deg (thr 25)")
    _bar(canvas, px, 172, 260, 22, float(pose.frown),
         (60, 60, 230) if frowning else (120, 120, 120),
         f"frown {float(pose.frown):.2f} (thr {FROWN_ASK_THRESHOLD:.2f})")
    mode = "wrist/IPD" if wrist_mode else "fixed prior"
    dist_txt = f"Z(ipd)~{float(pose.z):.2f} m" if wrist_mode else \
        f"z prior {float(pose.z):.2f} m"
    cv2.putText(canvas, f"source: {pose.source}  ({mode})", (px, 232),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)
    cv2.putText(canvas, dist_txt, (px, 256), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                (90, 200, 220), 1, cv2.LINE_AA)
    cv2.putText(canvas, f"pose base (m): ({pose.x:.2f}, {pose.y:.2f}, {pose.z:.2f})",
                (px, 280), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1,
                cv2.LINE_AA)
    cv2.putText(canvas, f"inference {elapsed_ms:.0f} ms", (px, 304),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1, cv2.LINE_AA)
    cv2.putText(canvas, "wrist cam dual duty: spoon check +", (px, 340),
                cv2.FONT_HERSHEY_SIMPLEX, 0.46, (170, 170, 170), 1, cv2.LINE_AA)
    cv2.putText(canvas, "mouth tracking (one camera, two jobs)", (px, 358),
                cv2.FONT_HERSHEY_SIMPLEX, 0.46, (170, 170, 170), 1, cv2.LINE_AA)
    cv2.putText(canvas, "spoon stops 5cm before mouth;", (px, 382),
                cv2.FONT_HERSHEY_SIMPLEX, 0.46, (170, 170, 170), 1, cv2.LINE_AA)
    cv2.putText(canvas, "user leans in (soft spoon, low speed)", (px, 400),
                cv2.FONT_HERSHEY_SIMPLEX, 0.46, (170, 170, 170), 1, cv2.LINE_AA)
    cv2.putText(canvas, "q/ESC quit   SPACE=soft estop demo", (px, h - 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.46, (150, 150, 150), 1, cv2.LINE_AA)
    return canvas


# ---- 主流程 --------------------------------------------------------------------------


def _parse_args(argv=None):
    ap = argparse.ArgumentParser(
        prog="python scripts/demo_mouth.py",
        description="口部实时演示：478 关键点+jaw 实时条+转头报警（§8.2）")
    ap.add_argument("--source", choices=["auto", "camera", "video", "bundled", "cartoon"],
                    default="auto", help="输入源（auto=摄像头优先，回退内置视频）")
    ap.add_argument("--device", type=int, default=0, help="摄像头序号")
    ap.add_argument("--wrist", action="store_true",
                    help="腕部双职模式：IPD 瞳距估距 + 名义 FK 位姿（契约 v1.1）")
    ap.add_argument("--frames", type=int, default=0,
                    help="无头冒烟：处理 N 帧落盘（不弹窗，exit 0）")
    ap.add_argument("--out", default=str(PKG_ROOT / "reports" / "demo_mouth_frames"),
                    help="落帧目录（--frames 模式）")
    ap.add_argument("--max-seconds", type=float, default=0.0,
                    help="交互模式最长运行秒数（0=直到按键退出）")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    prior = MouthPrior.load()
    if args.wrist:
        prior = prior.with_updates(mode="ipd")
    est = MouthEstimator(backend="mono", prior=prior)

    # 腕部双职：名义送达停点位姿 + 名义手眼外参（真机由 FK×handeye_wrist.npz 提供）
    cam_pose = None
    if args.wrist:
        t_flange = np.eye(4)
        t_flange[:3, 3] = [0.25, 0.0, 0.30]
        cam_pose = (t_flange, np.asarray(NOMINAL_T_FLANGE_CAM, dtype=float))

    try:
        src = open_source(args.source, args.device)
    except RuntimeError as exc:
        print(f"输入源不可用：{exc}")
        return 1

    print("讲稿：腕部相机双职——舀取时看勺、送达时看脸，一颗相机两份工作"
          "（传感器复用，整机更便宜）；近距瞳距先验估距，勺停口前 5cm、"
          "用户前倾自取；深度相机是机构版高配选项。")

    painter = _LandmarkPainter(prior)
    if not painter.available:
        print(f"提示：人脸关键点模型缺失（{painter._model_path}），"
              "关键点点云叠加不可用（python scripts/fetch_models.py 可补）")

    out_dir = Path(args.out)
    headless = args.frames > 0
    if headless:
        out_dir.mkdir(parents=True, exist_ok=True)

    n_done = 0
    t_start = time.perf_counter()
    try:
        while True:
            frame = src.read()
            if frame is None:
                print("输入源结束")
                break
            t0 = time.perf_counter()
            pose = est.from_bgr(frame, cam_pose=cam_pose)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            frame = draw_landmarks(frame, painter.points(frame))
            canvas = annotate(frame, pose, elapsed_ms, wrist_mode=cam_pose is not None)

            if headless:
                path = out_dir / f"frame_{n_done:03d}.png"
                if not imwrite_u(path, canvas):  # 中文路径安全写图
                    print(f"frame {n_done}: 落盘失败 {path}")
                    return 1
                print(f"frame {n_done}: valid={pose.valid} source={pose.source} "
                      f"jaw={pose.jaw_open:.2f} yaw={np.degrees(abs(float(pose.head_yaw))):.0f}deg "
                      f"z={pose.z:.2f}m -> {path.name}")
                n_done += 1
                if n_done >= args.frames:
                    break
            else:
                cv2.imshow("chengshao mouth demo", canvas)
                key = cv2.waitKey(400 if src.name != "camera" else 1) & 0xFF
                if key in (ord("q"), 27):
                    break
                if key == ord(" "):
                    print("软件急停（演示）：latch SafetyEnvelope 后臂停（真机 T10 "
                          "safety_drill 接线）")
                if args.max_seconds > 0 and \
                        time.perf_counter() - t_start > args.max_seconds:
                    break
    finally:
        src.close()
        if not headless:
            cv2.destroyAllWindows()
    print(f"demo 结束：{n_done} 帧")
    if n_done == 0:
        print("未产出任何帧（输入源不可用或读帧失败）", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
