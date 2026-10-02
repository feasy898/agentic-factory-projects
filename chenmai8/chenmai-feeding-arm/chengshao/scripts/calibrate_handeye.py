#!/usr/bin/env python3
"""手眼标定入口（hw-toolchain spec §2 第 3/4 步；开发指令 §5.9 第 2/3 行）。

用法（cwd=包根 chengshao/）::

    # 顶部相机 eye-to-hand（板装夹爪，采 12 位姿）→ config/calib/handeye_scene.npz
    python scripts/calibrate_handeye.py --cam scene --points 12 \
        --out config/calib/handeye_scene.npz

    # 腕部相机 eye-in-hand（板固定桌面、动臂采 15 位姿）→ handeye_wrist.npz
    python scripts/calibrate_handeye.py --cam wrist --mode eye-in-hand --points 15 \
        --out config/calib/handeye_wrist.npz

    # 无硬件 dry-run（合成数据闭环：cs_sim FK 生成法兰位姿 + 合成棋盘图像 →
    # 同一条 检测→PnP→calibrateHandEye→残差 链路）：
    python scripts/calibrate_handeye.py --cam scene --points 12 --mock
    python scripts/calibrate_handeye.py --cam wrist --mode eye-in-hand --points 15 --mock

通过线（§5.9）：重投影残差 ≤3mm 或 ≤2px。产出 npz 的 key：
- scene：``T_base_cam`` + ``reproj_err_mm``；
- wrist：``T_flange_cam`` + ``reproj_err_mm``（装载顺序 npz 优先、名义值兜底，
  见 cs_orchestra.core.load_t_flange_cam——本脚本只产出正确 key，不改装载）。

exit：0 = 通过线达标；1 = 采集/解算完成但未达通过线（或有效视角不足）；
2 = fail-closed（硬件缺失 / HardwareUnavailable / 用法错误）。

**mock 边界（务必区分）**：``--mock`` 用合成棋盘图像与 cs_sim FK 法兰位姿验证的是
标定**链路**（渲染→检测→PnP→手眼解算→残差→npz），其残差是合成数据上的残差，
**不等于**真机标定精度结论；报告显式标注 ``mock=true``、
``real_machine_measured=false``。
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
from cs_arm.handeye import (  # noqa: E402
    MODE_EYE_IN_HAND,
    MODE_EYE_TO_HAND,
    HandEyeSample,
    board_mark_point,
    chessboard_object_points,
    pose_from_ee,
    solve_handeye,
)
from cs_arm.interface import ArmCommandRejected  # noqa: E402
from cs_arm.mock_arm import MockArm  # noqa: E402
from cs_arm.safety import SafetyEnvelope  # noqa: E402
from cs_schema import ArmCommand, CommandMode  # noqa: E402
from cs_sim import EnvelopeValidator  # noqa: E402

MODE_BY_CAM = {"scene": MODE_EYE_TO_HAND, "wrist": MODE_EYE_IN_HAND}

#: 合成相机内参（mock；scene=2MP 档、wrist=1MP 广角档的量级，非实测）
MOCK_CAMERAS = {
    "scene": {"size": (1280, 800), "fx": 1000.0},
    "wrist": {"size": (960, 600), "fx": 430.0},
}

#: 缺省标定板（wrist 用小板：桌面臂腕部相机工作距离 0.1–0.25m，大板出视野）
BOARD_DEFAULTS = {
    "scene": {"cols": 9, "rows": 6, "square_mm": 20.0},
    "wrist": {"cols": 6, "rows": 5, "square_mm": 15.0},
}

#: 视角倾斜带（板面法向与光轴夹角）：近正对（fronto-parallel）时平面 PnP 存在
#: 镜面二义性，真机采集规程同样要求 ≥25° 斜视角
TILT_BAND_DEG = (25.0, 75.0)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="python scripts/calibrate_handeye.py",
        description="手眼标定（eye-to-hand / eye-in-hand；通过线 ≤3mm 或 ≤2px）",
    )
    ap.add_argument("--cam", required=True, choices=sorted(MODE_BY_CAM),
                    help="scene=顶部相机（eye-to-hand）/ wrist=腕部相机（eye-in-hand）")
    ap.add_argument("--mode", default=None, choices=[MODE_EYE_TO_HAND, MODE_EYE_IN_HAND],
                    help="缺省：scene→eye-to-hand，wrist→eye-in-hand")
    ap.add_argument("--points", type=int, default=None,
                    help="采集位姿数（spec：scene 12 / wrist 15；解算至少 6 视角）")
    ap.add_argument("--out", default=None,
                    help="npz 输出（真机缺省 config/calib/handeye_<cam>.npz；"
                         "--mock 缺省 reports/mock_handeye_<cam>.npz——合成外参不入 "
                         "config/calib/，防真机链路误装载；相对路径相对 cwd）")
    ap.add_argument("--report", default=None,
                    help="报告 JSON（缺省 reports/handeye_<cam>_eval.json）")
    ap.add_argument("--mock", action="store_true", help="无硬件 dry-run（合成数据闭环）")
    ap.add_argument("--board-cols", type=int, default=None,
                    help="棋盘内角点列数（缺省：scene 9 / wrist 6）")
    ap.add_argument("--board-rows", type=int, default=None,
                    help="棋盘内角点行数（缺省：scene 6 / wrist 5）")
    ap.add_argument("--square-mm", type=float, default=None,
                    help="棋盘格边长 mm（缺省：scene 20 / wrist 15）")
    ap.add_argument("--port", default="", help="真机串口（骨架阶段 fail-closed）")
    ap.add_argument("--cam-index", type=int, default=None,
                    help="真机相机序号（scene 缺省 0 / wrist 缺省 1）")
    ap.add_argument("--seed", type=int, default=20261002)
    return ap.parse_args(argv)


# ---- 合成棋盘渲染与检测（--mock 通道；检测链与真机共用） -------------------------

def _invert(T: np.ndarray) -> np.ndarray:
    R = T[:3, :3]
    t = T[:3, 3]
    out = np.eye(4)
    out[:3, :3] = R.T
    out[:3, 3] = -R.T @ t
    return out


def _look_at(pos: np.ndarray, target: np.ndarray) -> np.ndarray:
    """base→cam 位姿：cam Z 轴指向 target（OpenCV 相机系，Z 前向）。"""
    zc = target - pos
    zc = zc / np.linalg.norm(zc)
    up = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(up, zc))) > 0.95:
        up = np.array([0.0, 1.0, 0.0])
    xc = np.cross(up, zc)
    xc /= np.linalg.norm(xc)
    yc = np.cross(zc, xc)
    m = np.eye(4)
    m[:3, :3] = np.column_stack([xc, yc, zc])
    m[:3, 3] = pos
    return m


def _project(K: np.ndarray, T_cam_board: np.ndarray, obj: np.ndarray) -> np.ndarray:
    pts = (T_cam_board[:3, :3] @ obj.T + T_cam_board[:3, 3].reshape(3, 1)).T
    uv = (K @ pts.T).T
    return uv[:, 0:2] / uv[:, 2:3]


def _square_corner_grid(cols: int, rows: int, sq: float) -> np.ndarray:
    """方格角点扩展网格（(rows+2, cols+2, 3)）：内圈与内角点网格对齐。"""
    xs = (np.arange(cols + 2) - (cols + 1) / 2.0) * sq
    ys = (np.arange(rows + 2) - (rows + 1) / 2.0) * sq
    gx, gy = np.meshgrid(xs, ys)
    g = np.zeros((rows + 2, cols + 2, 3))
    g[:, :, 0] = gx
    g[:, :, 1] = gy
    return g


def render_board_image(t_cam_board: np.ndarray, K: np.ndarray,
                       size: tuple[int, int], cols: int, rows: int, sq: float,
                       obj: np.ndarray, rng: np.random.Generator):
    """把棋盘按 T_cam_board 渲染成 BGR 图（含板角定向标）；不可见返回 None。

    必须先做**正深度门**：板在相机系 z ≤ 0 的视角（板在相机背后）经针孔
    投影会得到镜像坐标，图像看似合法、实则物理不成立——此处直接判不可见。
    """
    import cv2

    w, h = size
    grid = _square_corner_grid(cols, rows, sq)
    flat = grid.reshape(-1, 3)
    pts = (t_cam_board[:3, :3] @ flat.T + t_cam_board[:3, 3].reshape(3, 1)).T
    if not np.isfinite(pts).all() or float(pts[:, 2].min()) < 0.05:
        return None  # 板不在相机前方（或过近）：物理不可见
    uv = (K @ pts.T).T
    uv = uv[:, 0:2] / uv[:, 2:3]
    uv = uv.reshape(rows + 2, cols + 2, 2)
    inner = uv[1:-1, 1:-1, :].reshape(-1, 2)
    margin = 26.0
    if (inner[:, 0].min() < margin or inner[:, 0].max() > w - margin
            or inner[:, 1].min() < margin or inner[:, 1].max() > h - margin):
        return None
    spread = float(np.linalg.norm(inner.max(axis=0) - inner.min(axis=0)))
    if not (150.0 <= spread <= 0.60 * min(w, h)):
        return None  # 过远/过近：视为不可见

    img = np.full((h, w, 3), 235, dtype=np.uint8)
    for j in range(rows + 1):
        for i in range(cols + 1):
            quad = np.array([uv[j, i], uv[j, i + 1], uv[j + 1, i + 1], uv[j + 1, i]],
                            dtype=np.float64)
            if not np.isfinite(quad).all():
                return None
            color = (25, 25, 25) if (i + j) % 2 == 0 else (240, 240, 240)
            cv2.fillConvexPoly(img, np.round(quad).astype(np.int32), color)
    # 板角定向标（黑圆，obj[0] 角外侧 1.3 格）：消除点阵 4 重翻转歧义。
    # 半径取 0.25 格边长（连通域面积 ≈0.1 格面积，与棋盘格可分）。
    mark = _project(K, t_cam_board, board_mark_point(cols, rows, sq).reshape(1, 3))
    mark_px = float(np.linalg.norm(uv[1, 1] - uv[0, 0]))  # 一格对角线像素长
    if np.isfinite(mark).all():
        r = max(3, int(round(0.25 * mark_px / 1.414)))
        cv2.circle(img, (int(round(mark[0, 0])), int(round(mark[0, 1]))), r,
                   (25, 25, 25), -1)
    img = cv2.GaussianBlur(img, (3, 3), 0.8)
    noise = rng.normal(0.0, 2.5, size=img.shape)
    return np.clip(img.astype(np.float64) + noise, 0, 255).astype(np.uint8)


def detect_corners(img, cols: int, rows: int):
    """棋盘角点 + 板角定向标检测（mock 与真机共用同一条 cv2 检测链）。

    返回 (corners(N,2), mark_uv(2,) | None)；棋盘未检出 → None。
    定向标 = 棋盘外的小暗圆斑（面积 < 0.45 格面积、近圆形），取最圆者。
    """
    import cv2

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    flags = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE
    ok, corners = cv2.findChessboardCorners(gray, (cols, rows), flags=flags)
    if not ok:
        return None
    corners = cv2.cornerSubPix(
        gray, corners, (5, 5), (-1, -1),
        (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 1e-3))
    corners = corners.reshape(-1, 2)

    # 定向标：连通域里找"小而圆"的暗斑（棋盘格是大块，按面积上限区分）
    grid = corners.reshape(rows, cols, 2)
    spacing = float(np.median([np.median(np.linalg.norm(np.diff(grid, axis=a), axis=2))
                               for a in (0, 1)]))
    sq_area = spacing * spacing
    dark = (gray < 110).astype(np.uint8)
    n, _labels, stats, centroids = cv2.connectedComponentsWithStats(dark)
    mark_uv = None
    best_circ = 0.0
    for k in range(1, n):
        x, y, bw, bh, area = stats[k]
        if not (12 <= area <= 0.45 * sq_area) or bw < 3 or bh < 3:
            continue
        aspect = max(bw, bh) / max(1e-6, min(bw, bh))
        fill = area / float(bw * bh)
        circ = fill / max(aspect, 1e-6)  # 圆盘：fill≈π/4≈0.785、aspect≈1
        if aspect > 1.6 or fill < 0.55:
            continue
        if circ > best_circ:
            best_circ = circ
            mark_uv = centroids[k].copy()
    return corners, mark_uv


# ---- 位形候选（随机采样；可见性由渲染/检测链如实裁决） --------------------------

def _fk_split(model, q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    pose7 = model.fk([float(v) for v in q])
    return np.asarray(pose7[0:3], dtype=float), np.asarray(pose7[3:7], dtype=float)


# ---- 采集（mock；真机采集在 collect_samples_real，骨架阶段 fail-closed） ---------

def _board_anchor_gt(mode: str) -> tuple[np.ndarray, str]:
    """合成 GT 的板锚定位姿（mock 专用；真机以现场摆板为准）。

    - eye-in-hand：板**斜靠**在桌面支架上、板面朝臂（中心 [0.30,0,0.15]、法向
      朝臂根上方）——桌面臂腕部相机的可行视点都集中在"收臂俯视"位形族，
      平铺板会被近正对视角（fronto-parallel）卡死镜面二义性；D3 真机采集
      规程同款：板斜靠、≥25° 斜视角。
    - eye-to-hand：板平装在夹爪下端（法兰 Z 向外移 0.055m），随臂入顶部
      相机视野。
    """
    if mode == MODE_EYE_IN_HAND:
        center = np.array([0.30, 0.0, 0.15])
        zc = np.array([-0.75, 0.0, 0.66])
        zc /= np.linalg.norm(zc)
        xc = np.cross([0.0, 0.0, 1.0], zc)
        xc /= np.linalg.norm(xc)
        yc = np.cross(zc, xc)
        T = np.eye(4)
        T[:3, :3] = np.column_stack([xc, yc, zc])
        T[:3, 3] = center
        return T, "板斜靠支架（板面朝臂，防 fronto-parallel 镜面二义性）"
    T = np.eye(4)
    T[:3, 3] = np.array([0.0, 0.0, 0.055])
    return T, "板平装夹爪下端（随臂入顶部相机视野）"


def _sample_candidate_q(mode: str, model, rng: np.random.Generator) -> np.ndarray:
    """关节位形候选采样（可见性由渲染/检测链如实裁决）。

    采样族按 cs_sim FK 可行域聚焦（纯 FK 廉价；驱动仍逐条经包络，被拒如实
    剔除）：
    - eye-in-hand："收臂俯视"工作位形族（本臂腕部相机唯一能稳定看到桌面部
      的位形族，见 reports/handeye_wrist_eval.json 的采集统计）；
    - eye-to-hand：工作区走廊位形（TCP 落 x 0.05–0.32 / |y|≤0.25 / z 0–0.4，
      板随臂入顶部相机视野）。
    """
    lo = np.asarray(model.joint_lower, dtype=float)
    hi = np.asarray(model.joint_upper, dtype=float)
    if mode == MODE_EYE_IN_HAND:
        q = np.array([
            rng.uniform(-0.5, 0.5),
            rng.uniform(float(lo[1]) + 0.02, -1.25),
            rng.uniform(-0.15, 0.45),
            rng.uniform(1.25, float(hi[3]) - 0.02),
            rng.uniform(float(lo[4]), float(hi[4])),
            rng.uniform(float(lo[5]), float(hi[5])),
        ])
        return np.clip(q, lo, hi)
    q = np.array([
        rng.uniform(-0.6, 0.6),
        rng.uniform(-1.5, 0.2),
        rng.uniform(-0.6, 0.8),
        rng.uniform(-0.8, 1.6),
        rng.uniform(float(lo[4]), float(hi[4])),
        rng.uniform(float(lo[5]), float(hi[5])),
    ])
    return np.clip(q, lo, hi)


def collect_samples_mock(mode: str, model, validator, obj, cols, rows, sq_m: float,
                         n_points: int, seed: int) -> tuple[list[HandEyeSample], dict]:
    """--mock 采集：cs_sim FK 法兰位姿 + 合成棋盘图像 → 同一条检测/解算链。"""
    from cs_orchestra.core import NOMINAL_T_FLANGE_CAM

    rng = np.random.default_rng(seed)
    spec = MOCK_CAMERAS["scene" if mode == MODE_EYE_TO_HAND else "wrist"]
    w, h = spec["size"]
    K = np.array([[spec["fx"], 0.0, w / 2.0 - 0.5],
                  [0.0, spec["fx"], h / 2.0 - 0.5],
                  [0.0, 0.0, 1.0]], dtype=float)

    if mode == MODE_EYE_IN_HAND:
        t_flange_cam_gt = np.asarray(NOMINAL_T_FLANGE_CAM, dtype=float)
        t_base_board_gt, board_note = _board_anchor_gt(mode)
        gt = t_flange_cam_gt
    else:
        t_base_cam_gt = _look_at(np.array([0.34, -0.04, 0.80]),
                                 np.array([0.15, 0.0, 0.05]))
        t_flange_board_gt, board_note = _board_anchor_gt(mode)
        gt = t_base_cam_gt

    samples: list[HandEyeSample] = []
    candidates_tried = 0
    drive_rejected = 0
    render_skipped = 0
    detect_failed = 0
    fronto_skipped = 0
    tcp_oob = 0
    max_candidates = 8000
    clock = VirtualClock()
    mock = MockArm(model, validator=validator, clock=clock)
    env = SafetyEnvelope(mock, model=model, validator=validator, clock=clock)
    env.enable()
    while len(samples) < n_points and candidates_tried < max_candidates:
        q_target = _sample_candidate_q(mode, model, rng)
        candidates_tried += 1
        if mode == MODE_EYE_TO_HAND:
            tcp = np.asarray(model.fk([float(v) for v in q_target])[0:3], dtype=float)
            if not (0.05 <= tcp[0] <= 0.32 and abs(tcp[1]) <= 0.25
                    and 0.0 <= tcp[2] <= 0.40):
                tcp_oob += 1
                continue  # 板随臂，TCP 出顶部相机视野的位形直接跳过
        try:  # 一切指令经包络（契约 §3.1）
            env.write(ArmCommand(mode=CommandMode.JOINTS,
                                 target=[float(v) for v in q_target],
                                 max_speed=0.8, timeout_s=120.0))
        except ArmCommandRejected:
            drive_rejected += 1
            continue
        clock.advance_s(float(env.last_decision["duration_s"]) + 0.005)
        state = env.read()
        t_bf_meas = pose_from_ee(state.ee_pos, state.ee_quat)
        if mode == MODE_EYE_IN_HAND:
            t_cam_board = _invert(t_bf_meas @ t_flange_cam_gt) @ t_base_board_gt
        else:
            t_cam_board = _invert(t_base_cam_gt) @ t_bf_meas @ t_flange_board_gt
        # 倾斜带过滤：近正对视角的平面 PnP 存在镜面二义性（真机规程同款）
        normal_cam = t_cam_board[:3, :3] @ np.array([0.0, 0.0, 1.0])
        tilt_deg = float(np.degrees(np.arccos(
            min(1.0, abs(float(np.dot(normal_cam, [0.0, 0.0, 1.0])))))))
        if not (TILT_BAND_DEG[0] <= tilt_deg <= TILT_BAND_DEG[1]):
            fronto_skipped += 1
            continue
        img = render_board_image(t_cam_board, K, (w, h), cols, rows, sq_m, obj, rng)
        if img is None:
            render_skipped += 1
            continue
        det = detect_corners(img, cols, rows)
        if det is None:
            detect_failed += 1
            continue
        corners, mark_uv = det
        if corners.shape[0] != obj.shape[0]:
            detect_failed += 1
            continue
        samples.append(HandEyeSample(T_base_flange=t_bf_meas,
                                     corners_px=corners.astype(float), K=K,
                                     mark_uv=(None if mark_uv is None
                                              else np.asarray(mark_uv, dtype=float))))
    info = {
        "intrinsics_source": "synthetic_known",
        "image_size_px": [w, h],
        "board_anchor": board_note,
        "tilt_band_deg": list(TILT_BAND_DEG),
        "candidates_tried": candidates_tried,
        "drive_rejected": drive_rejected,
        "tcp_out_of_view": tcp_oob,
        "render_skipped": render_skipped,
        "detect_failed": detect_failed,
        "fronto_skipped": fronto_skipped,
        "views_collected": len(samples),
        "ground_truth_key": ("T_flange_cam" if mode == MODE_EYE_IN_HAND
                             else "T_base_cam"),
        "ground_truth_T": gt.tolist(),
    }
    return samples, info


def collect_samples_real(args, model, validator, obj, cols, rows, sq_m: float,
                         n_points: int) -> tuple[list[HandEyeSample], dict]:
    """真机采集：FeetechArm 骨架阶段 connect() 即抛 HardwareUnavailable（exit 2）。"""
    cfg = FeetechArmConfig(port=args.port)
    arm = FeetechArm(cfg)
    arm.connect()  # 骨架：HardwareUnavailable（T10 实现采集闭环后接续）
    raise HardwareUnavailable("真机手眼采集闭环（实拍棋盘 + 法兰位姿回读）"
                              "随 T10 bring-up 实现")  # pragma: no cover


# ---- 主流程 ----------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    mode = args.mode or MODE_BY_CAM[args.cam]
    if mode != MODE_BY_CAM[args.cam]:
        print(f"[calibrate_handeye] --cam {args.cam} 只支持 {MODE_BY_CAM[args.cam]}",
              file=sys.stderr)
        return EXIT_HW_UNAVAILABLE
    n_points = args.points if args.points is not None else (
        12 if mode == MODE_EYE_TO_HAND else 15)
    if n_points < 6:
        print("[calibrate_handeye] --points 至少 6（解算下限）", file=sys.stderr)
        return EXIT_HW_UNAVAILABLE

    bd = BOARD_DEFAULTS[args.cam]
    cols = int(args.board_cols if args.board_cols is not None else bd["cols"])
    rows = int(args.board_rows if args.board_rows is not None else bd["rows"])
    square_mm = float(args.square_mm if args.square_mm is not None
                      else bd["square_mm"])
    sq_m = square_mm / 1000.0
    obj = chessboard_object_points(cols, rows, sq_m)
    t0 = time.perf_counter()

    model = load_model_cached()
    validator = EnvelopeValidator()
    try:
        if args.mock:
            samples, info = collect_samples_mock(mode, model, validator, obj,
                                                 cols, rows, sq_m, n_points,
                                                 args.seed)
        else:
            samples, info = collect_samples_real(args, model, validator, obj,
                                                 cols, rows, sq_m, n_points)
    except HardwareUnavailable as exc:
        return fail_closed(exc, f"calibrate_handeye({args.cam}, {mode}) 采集")

    try:
        result = solve_handeye(samples, mode=mode, obj_points=obj,
                               board_shape=(cols, rows),
                               mark_point=board_mark_point(cols, rows, sq_m))
    except ValueError as exc:  # 有效视角不足等：如实判失败（exit 1，不伪装）
        report_path = resolve_path(args.report) if args.report else \
            resolve_path(f"reports/handeye_{args.cam}_eval.json")
        write_report(
            report_path,
            module=f"cs_arm.handeye:{args.cam}",
            cmd=f"python scripts/calibrate_handeye.py --cam {args.cam} --points "
                f"{n_points}" + (" --mock" if args.mock else "") + "  (cwd=包根 chengshao/)",
            metrics={"views_collected": len(samples), "points_requested": n_points,
                     "collection": info, "error": str(exc)},
            thresholds={"reproj_err_mm_max": 3.0, "reproj_err_px_max": 2.0,
                        "min_views": 6},
            pass_=False,
            evidence_kind="mock_dry_run" if args.mock else "real_machine_calibration",
            real_machine_measured=False,
            mock=bool(args.mock),
        )
        print(f"[calibrate_handeye] 解算失败：{exc}", file=sys.stderr)
        print(f"report -> {report_path}")
        return EXIT_CHECKS_FAILED

    elapsed = round(time.perf_counter() - t0, 2)

    # npz 落盘（key 契约：T_base_cam / T_flange_cam + reproj_err_mm）。
    # 安全闸（独立复核高危项，2026-10-02 修）：未达通过线的标定**不得落**
    # config/calib/——load_t_flange_cam 无条件 npz 优先装载且不校验残差，
    # 失败外参一旦落默认路径会被腕部口部链路静默采用（禁入区锚错位）。
    # 因此：mock 缺省写 reports/；真机过线缺省写 config/calib/；
    # 真机未过线写 reports/handeye_<cam>_failed.npz（暂存）并返回失败；
    # --out 显式指向 config/calib/ 且未过线时同样改道暂存路径。
    key = "T_base_cam" if mode == MODE_EYE_TO_HAND else "T_flange_cam"
    passed = result.pass_line_met
    calib_root = resolve_path("config/calib")
    if args.out:
        out_path = resolve_path(args.out)
        if not passed:
            try:
                out_path.resolve().relative_to(calib_root.resolve())
                under_calib = True
            except ValueError:
                under_calib = False
            if under_calib:
                out_path = resolve_path(f"reports/handeye_{args.cam}_failed.npz")
                print("[calibrate_handeye] 警告：未过通过线，拒绝写入 config/calib/，"
                      f"改落暂存路径 {out_path}", file=sys.stderr)
    elif args.mock:
        out_path = resolve_path(f"reports/mock_handeye_{args.cam}.npz")
    elif passed:
        out_path = resolve_path(f"config/calib/handeye_{args.cam}.npz")
    else:
        out_path = resolve_path(f"reports/handeye_{args.cam}_failed.npz")
        print("[calibrate_handeye] 警告：未过通过线，标定结果只落暂存路径，"
              "不写 config/calib/（防失败外参被装载）", file=sys.stderr)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(out_path, **{
        key: result.T,
        "reproj_err_mm": np.float64(result.reproj_err_mm),
        "reproj_err_px": np.float64(result.reproj_err_px),
        "mode": np.array(mode),
        "n_views": np.int64(result.n_views),
        "K": np.asarray(samples[0].K, dtype=float),
        "board": np.array(f"{cols}x{rows}@{square_mm:g}mm"),
        "mock": np.array(bool(args.mock)),
        "date": np.array(time.strftime("%Y-%m-%d")),
    })

    # mock 附加校验：估计 vs 合成 GT（链路正确性证据；不作为通过线）
    est_vs_gt = None
    if args.mock:
        gt = np.asarray(info["ground_truth_T"], dtype=float)
        pos_err = float(np.linalg.norm(result.T[:3, 3] - gt[:3, 3]) * 1000.0)
        cos = float(np.clip((np.trace(result.T[:3, :3].T @ gt[:3, :3]) - 1.0) / 2.0,
                            -1.0, 1.0))
        est_vs_gt = {"pos_err_mm": round(pos_err, 3),
                     "angle_err_deg": round(float(np.degrees(np.arccos(cos))), 4)}

    metrics = {
        "cam": args.cam,
        "mode": mode,
        "key": key,
        "points_requested": n_points,
        "views_used": result.n_views,
        "reproj_err_mm": round(result.reproj_err_mm, 4),
        "reproj_err_px": round(result.reproj_err_px, 4),
        "method": result.method,
        "T": result.T.tolist(),
        "collection": info,
        "est_vs_gt_mock_only": est_vs_gt,
        "elapsed_s": elapsed,
    }
    thresholds = {"reproj_err_mm_max": 3.0, "reproj_err_px_max": 2.0,
                  "min_views": 6, "rule": "重投影残差 ≤3mm 或 ≤2px"}
    report_path = resolve_path(args.report) if args.report else \
        resolve_path(f"reports/handeye_{args.cam}_eval.json")
    write_report(
        report_path,
        module=f"cs_arm.handeye:{args.cam}",
        cmd=(f"python scripts/calibrate_handeye.py --cam {args.cam} "
             f"(--mode {mode}) --points {n_points} --out {out_path.name}"
             + (" --mock" if args.mock else "") + "  (cwd=包根 chengshao/)"),
        metrics=metrics,
        thresholds=thresholds,
        pass_=passed,
        notes=[
            "通过线=重投影残差 ≤3mm 或 ≤2px（§5.9）",
            *(["mock 结论不等于真机结论：合成棋盘图像 + cs_sim FK 位姿，残差是合成"
               "数据上的链路验证；真机标定精度以 D3 bring-up 实测为准"]
              if args.mock else ["真机标定：残差来自实拍棋盘与实回读法兰位姿"]),
        ],
        evidence_kind="mock_dry_run" if args.mock else "real_machine_calibration",
        real_machine_measured=False,
        mock=bool(args.mock),
    )
    print(f"calibrate_handeye({args.cam}/{mode}): views={result.n_views} "
          f"err_mm={result.reproj_err_mm:.3f} err_px={result.reproj_err_px:.3f} "
          f"pass={passed}{' (mock)' if args.mock else ''}")
    print(f"npz -> {out_path}")
    print(f"report -> {report_path}")
    return EXIT_OK if passed else EXIT_CHECKS_FAILED


if __name__ == "__main__":
    sys.exit(main())
