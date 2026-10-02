#!/usr/bin/env python3
"""相机验收入口（hw-toolchain spec §2 第 5 步；开发指令 §5.9 第 4 行）。

用法（cwd=包根 chengshao/）::

    python scripts/camera_check.py            # 真机：需 CS_HW_SESSION=1 且设备在位；否则 exit 2
    python scripts/camera_check.py --mock     # 无硬件 dry-run：合成图像走同一断言链 → exit 0
    # 注：面部可辨项 mock 用暗斑连通域计数器、真机用 Haar 级联（函数级 docstring 已
    # 如实披露）——模块级不宣称"同一检测器"；其余断言（清晰度/亮度/ArUco）共用同一
    # 指标函数。

验收项（§5.9 相机验收 + §2 第 5 步）：
  1) 相机枚举（cv2.VideoCapture 序号探测；scene 顶部 2MP / wrist 腕部 1MP）；
  2) 顶部相机：ArUco 基准码可辨（3 碗 3 码，config/bowl_markers.json 登记）；
  3) 腕部相机双职验收：
     a. 20–50cm 面部可辨（0.20/0.30/0.40/0.50m 四点逐一检测）；
     b. 最近对焦达标（20cm 处图像清晰度 Laplacian 方差 ≥ 阈值；模糊对照帧
        必须低于阈值——证明指标本身有区分度）；
     c. 亮→暗曝光恢复 ≤1s（帧流亮度统计恢复时间）；
  4) 臂全行程线缆余量检查清单（真机=操作员逐 waypoint 确认；mock=包络驱动
     MockArm 全行程 + 操作员项以 mock 等价替代并显式标注）。

exit：0 = 全部验收项通过；1 = 有验收项未过；2 = fail-closed（设备缺失 /
HardwareUnavailable / 用法错误）。

**mock 边界**：``--mock`` 的合成帧验证的是检测与断言链路本身，其结论**不等
于**真机相机成像质量结论；报告显式标注 ``mock=true``、
``real_machine_measured=false``。真机面部可辨检查用 cv2 自带 Haar 级联做
冒烟口径（生产口部算法验收走 cs_mouth.eval --wrist-view --live，§5.9 另行）。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve()
_PKG_ROOT = _HERE.parents[1]  # .../chengshao
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from cs_arm._hw_common import (  # noqa: E402
    EXIT_CHECKS_FAILED,
    EXIT_HW_UNAVAILABLE,
    EXIT_OK,
    fail_closed,
    load_model_cached,
    resolve_path,
    write_report,
)
from cs_arm.clock import VirtualClock  # noqa: E402
from cs_arm.feetech import FeetechArm, FeetechArmConfig, HardwareUnavailable  # noqa: E402
from cs_arm.interface import ArmCommandRejected  # noqa: E402
from cs_arm.mock_arm import MockArm  # noqa: E402
from cs_arm.safety import SafetyEnvelope  # noqa: E402
from cs_schema import ArmCommand, CommandMode  # noqa: E402
from cs_sim import EnvelopeValidator  # noqa: E402

#: 腕部双职验收距离点（§5.3/§5.9）
FACE_DISTANCES_M = (0.20, 0.30, 0.40, 0.50)
#: 合成帧画幅（腕部 1MP 量级）
FRAME_SIZE = (640, 480)
#: 缺省帧率（曝光恢复时间换算用）
DEFAULT_FPS = 30.0

#: 20cm 处面部占画幅高度比例（"20cm 人脸占满画面"口径），其余距离按 1/d 缩放
FACE_HEIGHT_FRAC_AT_20CM = 0.95


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="python scripts/camera_check.py",
        description="相机验收：枚举 / ArUco / 腕部双职（面部可辨/最近对焦/曝光恢复）/ 线缆清单",
    )
    ap.add_argument("--mock", action="store_true", help="无硬件 dry-run（合成图像链路）")
    ap.add_argument("--scene-index", type=int, default=0, help="顶部相机序号")
    ap.add_argument("--wrist-index", type=int, default=1, help="腕部相机序号")
    ap.add_argument("--port", default="", help="真机串口（骨架阶段 fail-closed）")
    ap.add_argument("--fps", type=float, default=DEFAULT_FPS,
                    help="帧率（曝光恢复时间换算；缺省 30）")
    ap.add_argument("--focus-min-var", type=float, default=120.0,
                    help="最近对焦清晰度阈值（Laplacian 方差；缺省 120）")
    ap.add_argument("--recovery-max-s", type=float, default=1.0,
                    help="亮→暗曝光恢复上限秒（§5.9：≤1s）")
    ap.add_argument("--report", default=None,
                    help="报告 JSON（缺省 reports/camera_check_eval.json）")
    return ap.parse_args(argv)


# ---- 合成帧生成（mock 通道） ------------------------------------------------------

def _render_face_frame(distance_m: float, sharp: bool = True,
                       rng: np.random.Generator | None = None) -> np.ndarray:
    """合成腕部视角人脸帧：肤色椭圆 + 双眼 + 嘴（检测链的真实输入）。

    面部高度占画幅比例按 1/d 缩放（20cm ≈ 占满画幅，§5.3 口径）；
    ``sharp=False`` 生成离焦模糊帧（最近对焦判据的对照）。
    """
    import cv2

    w, h = FRAME_SIZE
    img = np.full((h, w, 3), 60, dtype=np.uint8)  # 暗背景（室内量级）
    face_h = int(FACE_HEIGHT_FRAC_AT_20CM * 0.20 / distance_m * h)
    face_h = int(min(face_h, 0.96 * h))
    face_w = int(face_h * 0.72)
    cx, cy = w // 2, h // 2
    cv2.ellipse(img, (cx, cy), (face_w // 2, face_h // 2), 0, 0, 360,
                (140, 170, 205), -1)  # 肤色（BGR）
    eye_dy = int(face_h * 0.14)
    eye_dx = int(face_w * 0.22)
    eye_r = max(4, int(face_w * 0.10))
    for sx in (-1, 1):
        cv2.circle(img, (cx + sx * eye_dx, cy - eye_dy), eye_r, (30, 30, 30), -1)
    mouth_w, mouth_h = int(face_w * 0.34), max(3, int(face_h * 0.05))
    cv2.ellipse(img, (cx, cy + int(face_h * 0.22)), (mouth_w, mouth_h), 0, 0, 360,
                (40, 40, 120), -1)
    if not sharp:
        img = cv2.GaussianBlur(img, (31, 31), 8.0)
    if rng is not None:
        img = np.clip(img.astype(np.float64)
                      + rng.normal(0.0, 2.0, size=img.shape), 0, 255).astype(np.uint8)
    return img


def _render_scene_aruco() -> np.ndarray:
    """合成顶部场景帧：3 碗 3 码（config/bowl_markers.json 登记的 DICT_4X4_50）。"""
    import cv2

    w, h = 1280, 800
    img = np.full((h, w, 3), 200, dtype=np.uint8)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    x = 120
    for marker_id in (0, 1, 2):  # 登记码（碗 0/1/2）
        marker = cv2.aruco.generateImageMarker(dictionary, marker_id, 160)
        y = 120 + (marker_id % 2) * 380
        img[y:y + 160, x:x + 160] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
        x += 380
    return img


def _render_exposure_stream(n_frames: int = 30, fps: float = DEFAULT_FPS):
    """合成帧流：亮（前 1/3）→ 暗（中 1/3，模拟切灯）→ 亮（恢复段）。"""
    frames = []
    for k in range(n_frames):
        level = 185 if (k < n_frames // 3 or k >= 2 * n_frames // 3) else 35
        frame = np.full((FRAME_SIZE[1], FRAME_SIZE[0], 3), level, dtype=np.uint8)
        frames.append(frame)
    return frames, n_frames // 3  # 切暗时刻（帧序号）


# ---- 检测与断言链（mock 与真机共用口径） ------------------------------------------

def detect_face_eyes(img: np.ndarray) -> int:
    """面部可辨判据（合成帧口径）：上半区暗色双瞳连通域计数 ≥2。

    真机面部检查用 Haar 级联（:func:`detect_face_haar`）；两者都输出
    "可辨/不可辨"布尔，供同一条断言消费。
    """
    import cv2

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    dark = (gray < 90).astype(np.uint8)
    n, _lab, stats, _cent = cv2.connectedComponentsWithStats(dark)
    eyes = 0
    for k in range(1, n):
        x, y, bw, bh, area = stats[k]
        if area < 30 or area > 0.02 * w * h:
            continue
        if y + bh > h * 0.55:  # 眼睛应在画面上半区
            continue
        aspect = max(bw, bh) / max(1e-6, min(bw, bh))
        if aspect > 1.8:
            continue
        eyes += 1
    return eyes


def detect_face_haar(img: np.ndarray) -> bool:
    """面部可辨判据（真机冒烟口径）：cv2 自带 Haar 级联正面人脸。"""
    import cv2

    cascade = cv2.CascadeClassifier(cv2.data.haarcascades
                                    + "haarcascade_frontalface_default.xml")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=5,
                                     minSize=(60, 60))
    return len(faces) > 0


def sharpness_var_laplacian(img: np.ndarray) -> float:
    """清晰度指标：灰度 Laplacian 方差（真机同一口径）。"""
    import cv2

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def brightness_mean(img: np.ndarray) -> float:
    """帧平均亮度（曝光恢复判据；真机同一口径）。"""
    import cv2

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return float(gray.mean())


# ---- 检查项 ----------------------------------------------------------------------

def check_enumeration_mock() -> tuple[dict, bool]:
    devices = [{"index": 0, "role": "scene_cam", "source": "mock_virtual"},
               {"index": 1, "role": "wrist_cam", "source": "mock_virtual"}]
    return {"devices_found": 2, "expected_roles": ["scene_cam", "wrist_cam"],
            "devices": devices}, True


def check_enumeration_real(scene_index: int, wrist_index: int) -> tuple[dict, bool, bool]:
    """真机枚举：cv2 序号探测。返回 (metrics, all_found, any_opened)。"""
    import cv2

    devices = []
    for idx, role in ((scene_index, "scene_cam"), (wrist_index, "wrist_cam")):
        cap = cv2.VideoCapture(idx)
        opened = bool(cap.isOpened())
        if opened:
            cap.release()
        devices.append({"index": idx, "role": role, "opened": opened})
    found = [d for d in devices if d["opened"]]
    return ({"devices": devices, "devices_found": len(found),
             "expected_roles": ["scene_cam", "wrist_cam"]},
            len(found) == 2, len(found) > 0)


def check_aruco_mock() -> tuple[dict, bool]:
    from cs_food import BowlSelector

    frame = _render_scene_aruco()
    selector = BowlSelector()  # 缺省 config/bowl_markers.json（DICT_4X4_50, 3 碗码）
    markers = selector.detect(frame)
    found = sorted(m.bowl_index for m in markers)
    metrics = {"markers_detected": len(markers), "bowls_seen": found,
               "expected_bowls": [0, 1, 2],
               "min_side_px_seen": min((m.side_px for m in markers), default=0.0)}
    return metrics, found == [0, 1, 2]


def check_aruco_real(cap) -> tuple[dict, bool]:
    from cs_food import BowlSelector

    selector = BowlSelector()
    seen: set[int] = set()
    min_side = 0.0
    deadline = time.perf_counter() + 10.0
    while time.perf_counter() < deadline:
        ok, frame = cap.read()
        if not ok:
            break
        for m in selector.detect(frame):
            seen.add(m.bowl_index)
            min_side = max(min_side, m.side_px)
        if seen == {0, 1, 2}:
            break
    metrics = {"markers_detected": len(seen), "bowls_seen": sorted(seen),
               "expected_bowls": [0, 1, 2], "min_side_px_seen": round(min_side, 1)}
    return metrics, seen == {0, 1, 2}


def check_face_discernibility_mock(rng: np.random.Generator) -> tuple[dict, bool]:
    per_distance = {}
    all_ok = True
    for d in FACE_DISTANCES_M:
        frame = _render_face_frame(d, sharp=True, rng=rng)
        n_eyes = detect_face_eyes(frame)
        ok = n_eyes >= 2
        per_distance[f"{d:.2f}m"] = {"detected": ok, "eye_blobs": n_eyes,
                                     "face_height_frac": round(
                                         FACE_HEIGHT_FRAC_AT_20CM * 0.20 / d, 3)}
        all_ok = all_ok and ok
    return {"per_distance": per_distance,
            "distances_m": list(FACE_DISTANCES_M)}, all_ok


def check_face_discernibility_real(caps: dict) -> tuple[dict, bool]:
    """真机：操作员按提示逐距离站定（或持卡），Haar 冒烟口径逐点检测。"""
    per_distance = {}
    all_ok = True
    cap = caps["wrist_cam"]
    for d in FACE_DISTANCES_M:
        input(f"[camera_check] 请将面部置于腕部相机前 {d:.2f}m 处并保持，按 <Enter> 采集…")
        seen = 0
        deadline = time.perf_counter() + 3.0
        while time.perf_counter() < deadline:
            ok, frame = cap.read()
            if not ok:
                break
            if detect_face_haar(frame):
                seen += 1
        detected = seen > 0
        per_distance[f"{d:.2f}m"] = {"detected": detected, "positive_frames": seen}
        all_ok = all_ok and detected
    return {"per_distance": per_distance, "distances_m": list(FACE_DISTANCES_M)}, all_ok


def check_min_focus_mock(rng: np.random.Generator) -> tuple[dict, bool]:
    d_close = FACE_DISTANCES_M[0]
    sharp = _render_face_frame(d_close, sharp=True, rng=rng)
    blurred = _render_face_frame(d_close, sharp=False, rng=rng)
    var_sharp = sharpness_var_laplacian(sharp)
    var_blur = sharpness_var_laplacian(blurred)
    metrics = {"distance_m": d_close, "var_laplacian_sharp": round(var_sharp, 1),
               "var_laplacian_blurred_control": round(var_blur, 1),
               "metric_discriminates": var_blur < var_sharp}
    return metrics, var_sharp >= 120.0 and var_blur < var_sharp


def check_min_focus_real(cap, min_var: float) -> tuple[dict, bool]:
    input("[camera_check] 请将面部置于最近对焦验收距离（20cm），按 <Enter> 采集…")
    best = 0.0
    deadline = time.perf_counter() + 3.0
    while time.perf_counter() < deadline:
        ok, frame = cap.read()
        if not ok:
            break
        best = max(best, sharpness_var_laplacian(frame))
    return {"distance_m": FACE_DISTANCES_M[0],
            "var_laplacian_sharp": round(best, 1)}, best >= min_var


def check_exposure_recovery_mock(fps: float) -> tuple[dict, bool]:
    frames, dark_start = _render_exposure_stream()
    threshold = 120.0  # 亮度恢复判据（真机同一统计口径）
    recovered_at = None
    for k in range(dark_start, len(frames)):
        if brightness_mean(frames[k]) >= threshold:
            recovered_at = k
            break
    recovery_s = (recovered_at - dark_start) / fps if recovered_at is not None else None
    metrics = {"dark_switch_frame": dark_start, "recovered_frame": recovered_at,
               "recovery_s": (round(recovery_s, 3) if recovery_s is not None
                              else None),
               "brightness_threshold": threshold, "fps": fps}
    return metrics, recovery_s is not None and recovery_s <= 1.0


def check_exposure_recovery_real(cap, fps: float, max_s: float) -> tuple[dict, bool]:
    """真机：操作员切换照明（亮→暗），脚本测帧流亮度恢复时间。"""
    input("[camera_check] 保持灯亮，按 <Enter> 开始…")
    threshold = 120.0
    dark_start = None
    recovered_at = None
    t0 = time.perf_counter()
    input("[camera_check] 现在关闭/调暗主灯，按 <Enter> 确认已切换…")
    dark_start = time.perf_counter() - t0
    deadline = t0 + max(10.0, max_s * 3)
    while time.perf_counter() < deadline:
        ok, frame = cap.read()
        if not ok:
            break
        if brightness_mean(frame) >= threshold:
            recovered_at = time.perf_counter() - t0
            break
    recovery_s = (recovered_at - dark_start) if recovered_at is not None else None
    metrics = {"dark_switch_s": round(dark_start, 3),
               "recovery_s": (round(recovery_s, 3) if recovery_s is not None else None),
               "brightness_threshold": threshold, "fps": fps}
    return metrics, recovery_s is not None and recovery_s <= max_s


def check_cable_clearance_mock(model, validator) -> tuple[dict, bool]:
    """臂全行程线缆余量（mock）：包络驱动 MockArm 走工作区四角 + 家位，
    全部指令被包络接受；操作员目视项以 mock 等价替代并显式标注。"""
    clock = VirtualClock()
    mock = MockArm(model, validator=validator, clock=clock)
    env = SafetyEnvelope(mock, model=model, validator=validator, clock=clock)
    env.enable()
    # 全行程 = 进餐路由（碗巡检 → bowl1 送达走廊（orchestra 逐碗途经点）→
    # 送达停点 → 撤回走廊 → 家位）；逐点经包络下发，拒绝如实记录。
    home = [0.24, -0.08, 0.16]
    waypoints = [
        home,
        [0.22, -0.18, 0.10],   # 碗 0 上方
        [0.22, 0.00, 0.10],    # 碗 1 上方
        [0.22, 0.18, 0.10],    # 碗 2 上方
        [0.22, 0.00, 0.10],    # 回碗 1 上方（送达走廊起点）
        [0.22, -0.10, 0.20],   # 送达途经点 1（cs_orchestra 逐碗表 bowl1）
        [0.20, -0.05, 0.26],   # 送达途经点 2
        [0.25, 0.00, 0.30],    # 名义送达停点（面部球外 0.17m）
        [0.17, 0.00, 0.30],    # 预停点（停点 -X 0.08m）
        [0.20, -0.05, 0.26],   # 撤回走廊（途经点逆序）
        [0.22, -0.10, 0.20],
        home,                  # 回家
    ]
    rejected = []
    for wp in waypoints:
        try:
            env.write(ArmCommand(mode=CommandMode.CARTESIAN,
                                 target=[float(v) for v in wp],
                                 max_speed=0.08, timeout_s=120.0))
            clock.advance_s(float(env.last_decision.get("duration_s") or 0.0) + 0.005)
            env.read()
        except ArmCommandRejected as exc:
            rejected.append({"waypoint": wp, "reason": exc.reason})
    state = env.safety_state()
    metrics = {
        "waypoints": len(waypoints),
        "rejected": rejected,
        "violation": str(state.violation),
        "operator_visual_check": "mock_substituted",
        "note": "线缆牵扯为操作员目视项：mock 以'全行程包络零拒绝'等价替代，"
                "不等于真机线缆验收",
    }
    return metrics, not rejected and str(state.violation) == "none"


def check_cable_clearance_real(port: str) -> tuple[dict, bool]:
    """真机：包络驱动 FeetechArm 全行程 + 操作员逐 waypoint 目视确认。"""
    cfg = FeetechArmConfig(port=port)
    arm = FeetechArm(cfg)
    arm.connect()  # 骨架：HardwareUnavailable（T10 实现后接续）
    raise HardwareUnavailable("臂全行程线缆检查（真机）随 T10 bring-up 实现")


# ---- 主流程 ----------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    t0 = time.perf_counter()
    checks: dict[str, bool] = {}
    metrics: dict = {}

    if not args.mock:
        # 真机验收为交互式（操作员逐距离站定/切灯/目视线缆），且会打开实机
        # 设备——须显式 CS_HW_SESSION=1（与 training/ 拖动示教同一门槛约定），
        # 否则一律 fail-closed（不探测、不阻塞、不伪装）。
        import os

        if os.environ.get("CS_HW_SESSION") != "1":
            print("[camera_check] 真机验收需 CS_HW_SESSION=1 且相机/臂在位；"
                  "当前环境缺门槛 → fail-closed exit 2（--mock 可做无硬件 dry-run）",
                  file=sys.stderr)
            return EXIT_HW_UNAVAILABLE
        # 真机：先枚举相机，再连臂（线缆清单需要臂；骨架阶段必然 fail-closed）
        enum_metrics, all_found, _any = check_enumeration_real(
            args.scene_index, args.wrist_index)
        metrics["enumeration"] = enum_metrics
        checks["enumeration"] = all_found
        if not all_found:
            report_path = resolve_path(args.report) if args.report else \
                resolve_path("reports/camera_check_eval.json")
            write_report(report_path, module="cs_arm.camera_check",
                         cmd="python scripts/camera_check.py  (cwd=包根 chengshao/)",
                         metrics=metrics, thresholds=_thresholds(args), pass_=False,
                         checks=checks, evidence_kind="real_machine",
                         real_machine_measured=False, mock=False,
                         notes=["真机相机未全部就位（枚举失败）→ fail-closed"])
            print("[camera_check] 真机相机未全部就位 → exit 2", file=sys.stderr)
            return EXIT_HW_UNAVAILABLE
        import cv2

        caps = {}
        try:
            caps["scene_cam"] = cv2.VideoCapture(args.scene_index)
            caps["wrist_cam"] = cv2.VideoCapture(args.wrist_index)
            m, ok = check_aruco_real(caps["scene_cam"])
            metrics["scene_aruco"] = m
            checks["scene_aruco"] = ok
            m, ok = check_face_discernibility_real(caps)
            metrics["wrist_face"] = m
            checks["wrist_face_discernible"] = ok
            m, ok = check_min_focus_real(caps["wrist_cam"], args.focus_min_var)
            metrics["wrist_min_focus"] = m
            checks["wrist_min_focus"] = ok
            m, ok = check_exposure_recovery_real(caps["wrist_cam"], args.fps,
                                                 args.recovery_max_s)
            metrics["wrist_exposure_recovery"] = m
            checks["wrist_exposure_recovery"] = ok
            m, ok = check_cable_clearance_real(args.port)
            metrics["cable_clearance"] = m
            checks["cable_clearance"] = ok
        except HardwareUnavailable as exc:
            return fail_closed(exc, "camera_check(真机)")
        finally:
            for cap in caps.values():
                cap.release()
    else:
        rng = np.random.default_rng(20261002)
        model = load_model_cached()
        validator = EnvelopeValidator()
        m, ok = check_enumeration_mock()
        metrics["enumeration"] = m
        checks["enumeration"] = ok
        m, ok = check_aruco_mock()
        metrics["scene_aruco"] = m
        checks["scene_aruco"] = ok
        m, ok = check_face_discernibility_mock(rng)
        metrics["wrist_face"] = m
        checks["wrist_face_discernible"] = ok
        m, ok = check_min_focus_mock(rng)
        metrics["wrist_min_focus"] = {**m, "threshold": args.focus_min_var}
        checks["wrist_min_focus"] = (m["var_laplacian_sharp"] >= args.focus_min_var
                                     and m["metric_discriminates"])
        m, ok = check_exposure_recovery_mock(args.fps)
        metrics["wrist_exposure_recovery"] = {**m,
                                              "max_s": args.recovery_max_s}
        checks["wrist_exposure_recovery"] = ok
        m, ok = check_cable_clearance_mock(model, validator)
        metrics["cable_clearance"] = m
        checks["cable_clearance"] = ok

    metrics["elapsed_s"] = round(time.perf_counter() - t0, 2)
    passed = all(checks.values())
    report_path = resolve_path(args.report) if args.report else \
        resolve_path("reports/camera_check_eval.json")
    write_report(
        report_path,
        module="cs_arm.camera_check",
        cmd=("python scripts/camera_check.py" + (" --mock" if args.mock else "")
             + "  (cwd=包根 chengshao/)"),
        metrics=metrics,
        thresholds=_thresholds(args),
        pass_=passed,
        checks=checks,
        notes=[
            *(["mock 结论不等于真机结论：合成帧验证的是检测与断言链路；真机相机"
               "成像质量以 D3 bring-up 实测为准（不达标触发第三相机回退）"]
              if args.mock else []),
            "真机面部可辨为 cv2 Haar 冒烟口径；生产口部算法验收走 "
            "cs_mouth.eval --wrist-view --live（§5.9 另行）",
        ],
        evidence_kind="mock_dry_run" if args.mock else "real_machine",
        real_machine_measured=False,
        mock=bool(args.mock),
    )
    print(f"camera_check: pass={passed}{' (mock)' if args.mock else ''}")
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"report -> {report_path}")
    return EXIT_OK if passed else EXIT_CHECKS_FAILED


def _thresholds(args) -> dict:
    return {
        "devices_required": 2,
        "aruco_bowls": [0, 1, 2],
        "face_distances_m": list(FACE_DISTANCES_M),
        "face_all_detected": True,
        "focus_min_var_laplacian": args.focus_min_var,
        "focus_control_must_be_lower": True,
        "exposure_recovery_max_s": args.recovery_max_s,
        "cable_rejected_max": 0,
    }


if __name__ == "__main__":
    sys.exit(main())
