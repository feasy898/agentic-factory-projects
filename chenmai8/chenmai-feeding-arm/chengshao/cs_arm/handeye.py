"""手眼标定求解器（开发指令 §3.2 冻结签名；hw-toolchain spec §2 第 3/4 步）。

契约（§3.2，v3.1）::

    def calibrate_handeye(cam, arm, points: list) -> tuple[np.ndarray, float]
    # eye-to-hand（顶部相机，板装夹爪）→ T_base_cam → config/calib/handeye_scene.npz
    # eye-in-hand（腕部相机，板固定桌面、动臂采 N 位姿）→ T_flange_cam →
    # config/calib/handeye_wrist.npz；key：T_base_cam / T_flange_cam, reproj_err_mm。
    # 通过线：重投影残差 ≤3mm 或 ≤2px。

职责边界（本模块只**求解**，不触硬件、不下发指令）：
- ``points`` 为**已采集**样本列表（每项 = (T_base_flange, 角点像素坐标) 或
  :class:`HandEyeSample`；ArmState 需借助 ``arm`` 的 FK 转法兰位姿）；
- 采集阶段的臂运动必须由调用方经 SafetyEnvelope 驱动（契约 §3.1：
  ArmCommand 只能由包络下达），相机帧由调用方供给；
- npz 的装载顺序（npz 优先、名义值兜底）在 ``cs_orchestra.core`` 已有实现，
  本模块只负责产出正确 key 的 npz 数据（由 scripts/calibrate_handeye.py 落盘）。

求解口径：
- 单视角板位姿：``cv2.solvePnP``（IPPE 初值 + 迭代精化）→ T_cam_board；
- 手眼：``cv2.calibrateHandEye``（TSAI）。eye-in-hand 输入 gripper2base /
  target2cam → 输出 cam2gripper（= T_flange_cam）；eye-to-hand 按官方口径
  输入取逆（base2gripper）→ 输出 cam2base（= T_base_cam）；
- 残差：用手眼解 + 全视角板位姿的 SE3 均值重构每视角的 T_cam_board，
  重投影角点到像素（RMS px）；板角点在 base 系的"链路值 vs 单视角测量值"
  距离 RMS（mm）。通过线 = mm ≤3 或 px ≤2。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

try:  # 仓库根运行（pytest）与包根运行（-m cs_arm.*）双形态
    from chengshao.cs_sim.frames import matrix_from_quat
except ImportError:  # pragma: no cover - 包根直跑形态
    from cs_sim.frames import matrix_from_quat  # type: ignore[no-redef]

__all__ = [
    "MODE_EYE_TO_HAND",
    "MODE_EYE_IN_HAND",
    "REPROJ_ERR_MM_MAX",
    "REPROJ_ERR_PX_MAX",
    "MIN_VIEWS",
    "HandEyeSample",
    "HandEyeResult",
    "chessboard_object_points",
    "board_mark_point",
    "calibrate_handeye",
    "solve_handeye",
]

MODE_EYE_TO_HAND = "eye-to-hand"
MODE_EYE_IN_HAND = "eye-in-hand"

#: 通过线（hw-toolchain spec §2/§3：重投影残差 ≤3mm 或 ≤2px）
REPROJ_ERR_MM_MAX = 3.0
REPROJ_ERR_PX_MAX = 2.0
#: calibrateHandEye 解算所需最少视角（≥6 才有非退化旋转轴组合）
MIN_VIEWS = 6


# ---- 数据结构 -------------------------------------------------------------------

@dataclass(frozen=True)
class HandEyeSample:
    """单视角采集样本（法兰位姿来自 FK/回读；角点来自棋盘检测）。

    ``mark_uv``：板角定向标（黑圆贴片，位于 obj[0] 角外侧）的像素质心。
    纯角点棋盘的点阵中心对称，检测器每帧返回的起始角可能相差 180°/镜像——
    没有定向标时跨视角的 obj↔img 对应关系无法保证一致，手眼平移解会退化。
    有 mark_uv 时本模块逐视角在 4 种翻转里挑选与标一致的那一种（真机板准备：
    在棋盘 (0,0) 角外侧贴黑色圆标，T10 板准备项）。
    """

    T_base_flange: np.ndarray  # (4,4) base→法兰
    corners_px: np.ndarray  # (N,2) float32/float64，行主序（与 obj_points 对应）
    K: np.ndarray | None = None  # (3,3) 内参；None → 用 cam.intrinsics / 统一 K
    mark_uv: np.ndarray | None = None  # (2,) 定向标像素质心；None=按原始顺序


@dataclass(frozen=True)
class HandEyeResult:
    """手眼解算结果（T 与双口径残差 + 通过线判定）。"""

    mode: str
    T: np.ndarray  # (4,4) eye-in-hand: T_flange_cam；eye-to-hand: T_base_cam
    n_views: int
    reproj_err_mm: float
    reproj_err_px: float
    per_view_err_px: list[float] = field(default_factory=list)
    per_view_err_mm: list[float] = field(default_factory=list)
    method: str = "tsai"
    n_views_before_outlier_reject: int = 0  # 离群剔除前的视角数（审计用）
    thresholds: dict = field(default_factory=lambda: {
        "reproj_err_mm_max": REPROJ_ERR_MM_MAX,
        "reproj_err_px_max": REPROJ_ERR_PX_MAX,
        "min_views": MIN_VIEWS,
    })

    @property
    def pass_line_met(self) -> bool:
        """通过线：≤3mm 或 ≤2px（且视角数足够）。"""
        return (self.n_views >= MIN_VIEWS
                and (self.reproj_err_mm <= REPROJ_ERR_MM_MAX
                     or self.reproj_err_px <= REPROJ_ERR_PX_MAX))


# ---- 棋盘几何 -------------------------------------------------------------------

def chessboard_object_points(cols: int = 9, rows: int = 6,
                             square_m: float = 0.02) -> np.ndarray:
    """棋盘**内角点**的板系 3D 坐标（(N,3)，行主序，与 cv2 检测顺序一致）。

    板系约定：X 沿列、Y 沿行、Z=0（平面板）；原点在角点阵几何中心。
    """
    pts = np.zeros((cols * rows, 3), dtype=np.float64)
    xs = np.arange(cols, dtype=np.float64) * float(square_m)
    ys = np.arange(rows, dtype=np.float64) * float(square_m)
    k = 0
    for j in range(rows):  # 行主序：外层行、内层列（cv2 findChessboardCorners 顺序）
        for i in range(cols):
            pts[k, 0] = xs[i]
            pts[k, 1] = ys[j]
            k += 1
    pts[:, 0] -= float(xs[-1]) / 2.0
    pts[:, 1] -= float(ys[-1]) / 2.0
    return pts


def board_mark_point(cols: int = 9, rows: int = 6, square_m: float = 0.02) -> np.ndarray:
    """板角定向标（黑圆贴片中心）的板系坐标：obj[0] 角外侧 1.3 格（板缘外 0.5 格，
    与棋盘留出间隙，保证连通域分割不与棋盘格粘连）。"""
    return np.array([(-(cols - 1) / 2.0 - 1.3) * float(square_m),
                     (-(rows - 1) / 2.0 - 1.3) * float(square_m),
                     0.0], dtype=np.float64)


# ---- 位姿小工具 -----------------------------------------------------------------

def _invert(T: np.ndarray) -> np.ndarray:
    """SE(3) 求逆（利用刚体结构，比一般矩阵求逆数值更稳）。"""
    R = T[:3, :3]
    t = T[:3, 3]
    out = np.eye(4)
    out[:3, :3] = R.T
    out[:3, 3] = -R.T @ t
    return out


def pose_from_ee(ee_pos: list[float] | np.ndarray,
                 ee_quat: list[float] | np.ndarray) -> np.ndarray:
    """ArmState.ee_pos/ee_quat（[w,x,y,z]）→ T_base_flange（4×4）。"""
    m = np.eye(4)
    m[:3, :3] = matrix_from_quat(np.asarray(ee_quat, dtype=float))
    m[:3, 3] = np.asarray(ee_pos, dtype=float)
    return m


def _mean_pose(poses: list[np.ndarray]) -> np.ndarray:
    """SE(3) 均值：平移取算术均值；旋转取 chordal 均值后 SVD 投影回 SO(3)。"""
    rs = np.stack([np.asarray(p, dtype=float)[:3, :3] for p in poses])
    ts = np.stack([np.asarray(p, dtype=float)[:3, 3] for p in poses])
    m = rs.mean(axis=0)
    u, _, vt = np.linalg.svd(m)
    d = np.sign(np.linalg.det(u @ vt))
    r = u @ np.diag([1.0, 1.0, d]) @ vt
    out = np.eye(4)
    out[:3, :3] = r
    out[:3, 3] = ts.mean(axis=0)
    return out


def _as_samples(points: list, cam, arm, K_default: np.ndarray | None) -> list[HandEyeSample]:
    """把 points 归一化为 HandEyeSample 列表。

    每项允许：
    - :class:`HandEyeSample`（原样）；
    - (T_base_flange(4×4), corners_px(N,2)) 二元组；
    - (ArmState, corners_px) 二元组——借助 ``arm`` 的 FK（``arm.model.fk`` 或
      ``arm.fk``）把 ee_pos/ee_quat 转为法兰位姿。
    """
    K_cam = None
    if cam is not None:
        K_cam = getattr(cam, "intrinsics", None)
        if K_cam is not None:
            K_cam = np.asarray(K_cam, dtype=float)
    samples: list[HandEyeSample] = []
    for item in points:
        # 鸭子类型判样本（isinstance 会因 cs_arm 的双形态导入产生两个类对象而
        # 误判——顶层 cs_arm 与 chengshao.cs_arm 是不同实例，见 cs_arm/__init__）
        if hasattr(item, "T_base_flange") and hasattr(item, "corners_px"):
            mark = getattr(item, "mark_uv", None)
            if mark is not None:
                mark = np.asarray(mark, dtype=float).reshape(2)
            samples.append(HandEyeSample(T_base_flange=item.T_base_flange,
                                         corners_px=item.corners_px,
                                         K=item.K, mark_uv=mark))
            continue
        if not (isinstance(item, (tuple, list)) and len(item) == 2):
            raise ValueError("calibrate_handeye: points 每项须为 HandEyeSample 或 "
                             "(末端位姿|ArmState, corners_px) 二元组")
        pose, corners = item
        corners = np.asarray(corners, dtype=float)
        if corners.ndim != 2 or corners.shape[1] != 2:
            raise ValueError(f"corners_px 须为 (N,2)，得到 shape={corners.shape}")
        if not hasattr(pose, "ee_pos"):  # 已是 4×4
            T = np.asarray(pose, dtype=float)
            if T.shape != (4, 4):
                raise ValueError(f"T_base_flange 须为 (4,4)，得到 shape={T.shape}")
        else:  # ArmState：用 arm 侧 FK
            fk = None
            model = getattr(arm, "model", None)
            if model is not None and hasattr(model, "fk"):
                fk = model.fk
            elif hasattr(arm, "fk"):
                fk = arm.fk
            if fk is None:
                raise ValueError("ArmState 样本需要 arm 提供 FK（arm.model.fk / arm.fk）")
            pose7 = fk([float(v) for v in pose.joint_pos])
            T = pose_from_ee(pose7[0:3], pose7[3:7])
        mark = getattr(item, "mark_uv", None) if isinstance(item, HandEyeSample) else None
        if mark is not None:
            mark = np.asarray(mark, dtype=float).reshape(2)
        samples.append(HandEyeSample(T_base_flange=T, corners_px=corners,
                                     K=K_cam, mark_uv=mark))
    if K_default is not None:
        K_default = np.asarray(K_default, dtype=float)
        samples = [HandEyeSample(T_base_flange=s.T_base_flange,
                                 corners_px=s.corners_px,
                                 K=(s.K if s.K is not None else K_default),
                                 mark_uv=s.mark_uv)
                   for s in samples]
    return samples


# ---- 求解 -----------------------------------------------------------------------

def _solve_pnp(obj_pts: np.ndarray, img_pts: np.ndarray, K: np.ndarray):
    """单视角 PnP：IPPE（共面特化）初值 + 迭代精化 → T_cam_board (4×4) 或 None。"""
    import cv2

    dist = np.zeros(5, dtype=np.float64)  # 标定口径：内参与畸变一并标定时可传入畸变
    obj = np.ascontiguousarray(obj_pts.reshape(-1, 1, 3), dtype=np.float64)
    img = np.ascontiguousarray(img_pts.reshape(-1, 1, 2), dtype=np.float64)
    ok, rvec, tvec = cv2.solvePnP(obj, img, K, dist, flags=cv2.SOLVEPNP_IPPE)
    if not ok:
        return None
    ok, rvec, tvec = cv2.solvePnP(obj, img, K, dist, rvec, tvec,
                                  useExtrinsicGuess=True,
                                  flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        return None
    R, _ = cv2.Rodrigues(rvec)
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = tvec.reshape(3)
    return T


def _corner_variants(corners_px: np.ndarray, cols: int, rows: int) -> list[np.ndarray]:
    """检测角点的 4 种板系对应（棋盘点阵中心对称，检测器起始角可能任取）。"""
    g = np.asarray(corners_px, dtype=float).reshape(rows, cols, 2)
    return [g.reshape(-1, 2),
            g[:, ::-1, :].reshape(-1, 2),
            g[::-1, :, :].reshape(-1, 2),
            g[::-1, ::-1, :].reshape(-1, 2)]


def _resolve_sample_pose(obj: np.ndarray, s: HandEyeSample,
                         cols: int, rows: int, mark_pt: np.ndarray | None):
    """单视角板位姿：PnP + 定向标消歧（4 翻转中选与 mark_uv 一致的那一种）。

    返回 (T_cam_board, corners_canonical)；无 mark_uv 时按原始顺序解（对应
    关系一致性由采集方保证）；有 mark_uv 但 4 种翻转均对不上 → (None, None)
    （该视角如实剔除）。
    """
    K = np.asarray(s.K, dtype=float)
    if s.mark_uv is None or mark_pt is None:
        return _solve_pnp(obj, s.corners_px, K), np.asarray(s.corners_px, dtype=float)
    for variant in _corner_variants(s.corners_px, cols, rows):
        t_cb = _solve_pnp(obj, variant, K)
        if t_cb is None:
            continue
        p_cam = t_cb[:3, :3] @ mark_pt + t_cb[:3, 3]
        uv = (K @ p_cam.reshape(3, 1)).reshape(3)
        uv = uv[0:2] / uv[2]
        grid = np.asarray(s.corners_px, dtype=float).reshape(rows, cols, 2)
        dx = float(np.median(np.linalg.norm(np.diff(grid, axis=1), axis=2)))
        dy = float(np.median(np.linalg.norm(np.diff(grid, axis=0), axis=2)))
        tol_px = 0.8 * float(np.median([v for v in (dx, dy) if v > 1e-6] or [1.0]))
        if float(np.linalg.norm(uv - s.mark_uv)) <= tol_px:
            return t_cb, variant
    return None, None


def solve_handeye(samples: list[HandEyeSample], *, mode: str,
                  obj_points: np.ndarray, method: str = "tsai",
                  board_shape: tuple[int, int] | None = None,
                  mark_point: np.ndarray | None = None) -> HandEyeResult:
    """手眼解算主入口（不触硬件；samples 由调用方采集）。

    - ``mode="eye-in-hand"``：相机在法兰上、板固定桌面 → 返回 T_flange_cam；
    - ``mode="eye-to-hand"``：相机固定（顶部）、板装夹爪 → 返回 T_base_cam；
    - ``board_shape=(cols, rows)`` 与 ``mark_point``（板角定向标板系坐标，
      :func:`board_mark_point`）：样本带 ``mark_uv`` 时必须提供，用于逐视角
      消除棋盘点阵的 4 重翻转歧义；
    - 残差口径见模块 docstring；``pass_line_met`` = ≤3mm 或 ≤2px。
    """
    import cv2

    if mode not in (MODE_EYE_TO_HAND, MODE_EYE_IN_HAND):
        raise ValueError(f"mode 须为 {MODE_EYE_TO_HAND!r}/{MODE_EYE_IN_HAND!r}，得到 {mode!r}")
    obj = np.asarray(obj_points, dtype=np.float64)
    if obj.ndim != 2 or obj.shape[1] != 3:
        raise ValueError(f"obj_points 须为 (N,3)，得到 shape={obj.shape}")
    n_corners = obj.shape[0]
    if board_shape is None:
        board_shape = (9, 6)  # 缺省棋盘（与 chessboard_object_points 缺省一致）
        if n_corners != board_shape[0] * board_shape[1]:
            board_shape = None
    if any(s.mark_uv is not None for s in samples):
        if board_shape is None or mark_point is None:
            raise ValueError("样本带 mark_uv（定向标）时必须提供 board_shape 与 "
                             "mark_point（board_mark_point）")
    cols, rows = int(board_shape[0]), int(board_shape[1])
    if cols * rows != n_corners:
        raise ValueError(f"board_shape {board_shape} 与 obj_points 数量 {n_corners} 不符")
    if len(samples) < MIN_VIEWS:
        raise ValueError(f"有效视角不足：{len(samples)} < {MIN_VIEWS}")

    methods = {"tsai": cv2.CALIB_HAND_EYE_TSAI, "park": cv2.CALIB_HAND_EYE_PARK,
               "horaud": cv2.CALIB_HAND_EYE_HORAUD, "daniilidis": cv2.CALIB_HAND_EYE_DANIILIDIS}
    if method not in methods:
        raise ValueError(f"method 须为 {sorted(methods)} 之一，得到 {method!r}")

    # 1) 单视角 PnP → T_cam_board（含定向标消歧；失败视角如实剔除并计数）
    T_cam_board_list: list[np.ndarray] = []
    corners_canon: list[np.ndarray] = []
    used: list[HandEyeSample] = []
    n_pnp_failed = 0
    n_disambig_failed = 0
    for idx, s in enumerate(samples):
        if s.K is None:
            raise ValueError(f"样本 {idx} 缺内参 K（cam.intrinsics 或 sample.K）")
        if s.corners_px.shape[0] != n_corners:
            n_pnp_failed += 1
            continue
        t_cb, cn = _resolve_sample_pose(obj, s, cols, rows,
                                        None if mark_point is None
                                        else np.asarray(mark_point, dtype=float))
        if t_cb is None:
            if s.mark_uv is not None:
                n_disambig_failed += 1
            else:
                n_pnp_failed += 1
            continue
        T_cam_board_list.append(t_cb)
        corners_canon.append(cn)
        used.append(s)
    if len(used) < MIN_VIEWS:
        raise ValueError(
            f"PnP 有效视角不足：{len(used)}/{len(samples)} < {MIN_VIEWS} "
            f"（PnP 失败 {n_pnp_failed}，定向标不匹配 {n_disambig_failed}）")

    # 2) calibrateHandEye：eye-in-hand 直喂 gripper2base；eye-to-hand 输入取逆
    #   （官方口径：base2gripper 进 → cam2base 出，推导见模块 docstring）。
    def _solve(views, poses, corner_sets):
        r_g2b, t_g2b, r_t2c, t_t2c = [], [], [], []
        for s, t_cb in zip(views, poses):
            T_bf = np.asarray(s.T_base_flange, dtype=float)
            R_g, t_g = T_bf[:3, :3], T_bf[:3, 3]
            if mode == MODE_EYE_TO_HAND:
                inv = _invert(T_bf)
                R_g, t_g = inv[:3, :3], inv[:3, 3]
            r_g2b.append(R_g)
            t_g2b.append(t_g.reshape(3, 1))
            r_t2c.append(t_cb[:3, :3])
            t_t2c.append(t_cb[:3, 3].reshape(3, 1))
        R_x, t_x = cv2.calibrateHandEye(r_g2b, t_g2b, r_t2c, t_t2c,
                                        method=methods[method])
        X = np.eye(4)
        X[:3, :3] = np.asarray(R_x, dtype=float)
        X[:3, 3] = np.asarray(t_x, dtype=float).reshape(3)

        # 双口径残差：链路重构的 T_cam_board vs 单视角 PnP 测量
        #   eye-in-hand（板固定桌面）：不变量 = 板在 base 系位姿
        #     board_i = T_bf_i @ X @ T_cb_i → 均值板位 → 重构 T_cb_pred_i
        #   eye-to-hand（板装夹爪）：不变量 = 板在**法兰系**位姿
        #     anchor_i = inv(T_bf_i) @ X @ T_cb_i → 均值锚位 → 重构 T_cb_pred_i
        if mode == MODE_EYE_IN_HAND:
            anchors = [s.T_base_flange @ X @ t_cb
                       for s, t_cb in zip(views, poses)]
            anchor_mean = _mean_pose(anchors)
            t_cb_pred = [_invert(X) @ _invert(s.T_base_flange) @ anchor_mean
                         for s in views]
        else:
            anchors = [_invert(s.T_base_flange) @ X @ t_cb
                       for s, t_cb in zip(views, poses)]
            anchor_mean = _mean_pose(anchors)
            t_cb_pred = [_invert(X) @ s.T_base_flange @ anchor_mean for s in views]
        anchor_ref = (anchor_mean[:3, :3] @ obj.T).T + anchor_mean[:3, 3]
        errs_px: list[float] = []
        errs_mm: list[float] = []
        for vi, (s, cn, t_cb_prd) in enumerate(zip(views, corner_sets, t_cb_pred)):
            K_v = np.asarray(s.K, dtype=float)
            # 像素残差：链路预测的板位重投影 vs（消歧后的）检测角点
            cam_pts = t_cb_prd[:3, :3] @ obj.T + t_cb_prd[:3, 3].reshape(3, 1)
            uv = (K_v @ cam_pts).T
            uv = uv[:, 0:2] / uv[:, 2:3]
            errs_px.append(float(np.sqrt(np.mean(np.sum((uv - cn) ** 2, axis=1)))))
            # mm 残差：板角点"均值锚位 vs 单视角测量"距离（不变量坐标系下）
            a_i = anchors[vi]
            base_i = (a_i[:3, :3] @ obj.T).T + a_i[:3, 3]
            errs_mm.append(float(np.sqrt(np.mean(np.sum((base_i - anchor_ref) ** 2,
                                                        axis=1))) * 1000.0))
        return X, errs_px, errs_mm

    X, errs_px, errs_mm = _solve(used, T_cam_board_list, corners_canon)

    # 2b) 离群视角剔除（一次重解）：坏视角（误配/边缘视角）会污染 TSAI 平移解。
    #   判据：px 残差 > max(2px, 3×中位数)；剔除后仍需 ≥ MIN_VIEWS。
    med = float(np.median(errs_px))
    thr = max(REPROJ_ERR_PX_MAX, 3.0 * med)
    keep = [i for i, e in enumerate(errs_px) if e <= thr]
    n_outlier = len(used) - len(keep)
    if n_outlier > 0 and len(keep) >= MIN_VIEWS:
        used2 = [used[i] for i in keep]
        poses2 = [T_cam_board_list[i] for i in keep]
        cn2 = [corners_canon[i] for i in keep]
        X, errs_px, errs_mm = _solve(used2, poses2, cn2)
        used, T_cam_board_list, corners_canon = used2, poses2, cn2

    return HandEyeResult(
        mode=mode,
        T=X,
        n_views=len(used),
        reproj_err_mm=float(np.mean(errs_mm)),
        reproj_err_px=float(np.mean(errs_px)),
        per_view_err_px=[round(v, 4) for v in errs_px],
        per_view_err_mm=[round(v, 4) for v in errs_mm],
        method=method,
        n_views_before_outlier_reject=len(used) + n_outlier,
    )


def calibrate_handeye(cam, arm, points: list, *, mode: str = MODE_EYE_IN_HAND,
                      obj_points: np.ndarray | None = None,
                      board_shape: tuple[int, int] | None = None,
                      mark_point: np.ndarray | None = None) -> tuple[np.ndarray, float]:
    """契约 §3.2 冻结签名：由采集样本解手眼，返回 (T, 重投影残差 mm)。

    - ``cam``：需提供 ``intrinsics``（3×3 K）；样本未带 K 时使用；
    - ``arm``：样本为 ArmState 时提供 FK（``arm.model.fk`` / ``arm.fk``）；
    - ``points``：样本列表（见 :func:`_as_samples`）；本函数**不下发任何指令**；
    - ``mode``：eye-in-hand → T_flange_cam；eye-to-hand → T_base_cam；
    - ``board_shape`` / ``mark_point``：样本带定向标（mark_uv）时必填。
    残差为 mm 口径；px 口径与通过线判定请用 :func:`solve_handeye` 的完整结果。
    """
    pts = np.asarray(obj_points) if obj_points is not None else chessboard_object_points()
    samples = _as_samples(points, cam, arm, K_default=None)
    res = solve_handeye(samples, mode=mode, obj_points=pts,
                        board_shape=board_shape, mark_point=mark_point)
    return res.T, float(res.reproj_err_mm)
