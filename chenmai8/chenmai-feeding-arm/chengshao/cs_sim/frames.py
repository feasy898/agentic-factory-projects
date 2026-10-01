"""位姿数学工具：旋转矩阵 / 四元数(w 在前) / rpy / SO(3) 对数。

约定（与 cs_schema 冻结契约一致，见开发指令 §1/§3.1）：
- 坐标系为机械臂 base 系：X 前向、Y 左、Z 上；单位米 / 弧度。
- 四元数一律 ``[w, x, y, z]``（w 在前），与 MuJoCo 相同。
- rpy 为固定角 (roll, pitch, yaw)，等价 R = Rz(yaw) @ Ry(pitch) @ Rx(roll)，
  与参考 URDF 的 <origin rpy=...> 约定一致（ikpy 同此约定）。

仅依赖 numpy；供本包内各后端与求解器共用。
"""

from __future__ import annotations

import numpy as np

__all__ = [
    "quat_from_matrix",
    "matrix_from_quat",
    "rpy_from_matrix",
    "matrix_from_rpy",
    "so3_log",
    "quat_angle_between",
    "segment_point_distance",
    "segment_segment_distance",
]


def quat_from_matrix(R: np.ndarray) -> np.ndarray:
    """旋转矩阵 -> 单位四元数 [w, x, y, z]（Shepperd 法，数值稳定）。"""
    R = np.asarray(R, dtype=float)
    trace = float(np.trace(R))
    if trace > 0.0:
        s = np.sqrt(trace + 1.0) * 2.0
        w = 0.25 * s
        x = (R[2, 1] - R[1, 2]) / s
        y = (R[0, 2] - R[2, 0]) / s
        z = (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] >= R[1, 1] and R[0, 0] >= R[2, 2]:
        s = np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2.0
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] >= R[2, 2]:
        s = np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2.0
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2.0
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s
    q = np.array([w, x, y, z], dtype=float)
    return q / np.linalg.norm(q)


def matrix_from_quat(q: np.ndarray) -> np.ndarray:
    """单位四元数 [w, x, y, z] -> 3x3 旋转矩阵。"""
    w, x, y, z = np.asarray(q, dtype=float) / np.linalg.norm(q)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ],
        dtype=float,
    )


def matrix_from_rpy(roll: float, pitch: float, yaw: float) -> np.ndarray:
    """固定角 rpy -> 旋转矩阵，R = Rz(yaw) @ Ry(pitch) @ Rx(roll)。"""
    cr, sr = np.cos(roll), np.sin(roll)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)
    Rx = np.array([[1.0, 0.0, 0.0], [0.0, cr, -sr], [0.0, sr, cr]])
    Ry = np.array([[cp, 0.0, sp], [0.0, 1.0, 0.0], [-sp, 0.0, cp]])
    Rz = np.array([[cy, -sy, 0.0], [sy, cy, 0.0], [0.0, 0.0, 1.0]])
    return Rz @ Ry @ Rx


def rpy_from_matrix(R: np.ndarray) -> np.ndarray:
    """旋转矩阵 -> rpy (roll, pitch, yaw)。万向锁时取 yaw=0 的等效解。"""
    R = np.asarray(R, dtype=float)
    pitch = np.arctan2(-R[2, 0], float(np.hypot(R[0, 0], R[1, 0])))
    if abs(np.cos(pitch)) < 1e-12:
        # 万向锁：roll 与 yaw 耦合，约定取 yaw=0
        roll = np.arctan2(-R[1, 2], R[1, 1])
        return np.array([roll, pitch, 0.0])
    roll = np.arctan2(R[2, 1], R[2, 2])
    yaw = np.arctan2(R[1, 0], R[0, 0])
    return np.array([roll, pitch, yaw])


def so3_log(R: np.ndarray) -> np.ndarray:
    """SO(3) 对数：旋转矩阵 -> 轴角向量（方向=轴，模长=角度），world 系。

    对任意 R∈SO(3) 数值稳定：小角用反对称近似，近 pi 用四元数路径。
    """
    R = np.asarray(R, dtype=float)
    cos_th = float(np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0))
    theta = float(np.arccos(cos_th))
    if theta < 1e-7:
        return 0.5 * np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
    if theta > np.pi - 1e-4:
        # 近 pi：反对称项退化，改由四元数向量部分取轴
        q = quat_from_matrix(R)
        if q[0] < 0.0:
            q = -q
        v = q[1:4]
        n = float(np.linalg.norm(v))
        if n < 1e-12:
            return np.zeros(3)
        return (theta / n) * v
    factor = theta / (2.0 * np.sin(theta))
    return factor * np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])


def quat_angle_between(q1: np.ndarray, q2: np.ndarray) -> float:
    """两个 wxyz 四元数之间的测地角（弧度，最短路径，值域 [0, pi]）。"""
    q1 = np.asarray(q1, dtype=float) / np.linalg.norm(q1)
    q2 = np.asarray(q2, dtype=float) / np.linalg.norm(q2)
    dot = float(abs(np.dot(q1, q2)))
    return 2.0 * float(np.arccos(min(1.0, dot)))


def segment_point_distance(a: np.ndarray, b: np.ndarray, p: np.ndarray) -> float:
    """点到线段 ab 的最短距离。"""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    p = np.asarray(p, dtype=float)
    ab = b - a
    denom = float(ab @ ab)
    if denom < 1e-18:
        return float(np.linalg.norm(p - a))
    t = float(np.clip(((p - a) @ ab) / denom, 0.0, 1.0))
    return float(np.linalg.norm(p - (a + t * ab)))


def segment_segment_distance(p1: np.ndarray, q1: np.ndarray, p2: np.ndarray, q2: np.ndarray) -> float:
    """线段 p1q1 与线段 p2q2 的最短距离（标准解法）。"""
    p1 = np.asarray(p1, dtype=float)
    q1 = np.asarray(q1, dtype=float)
    p2 = np.asarray(p2, dtype=float)
    q2 = np.asarray(q2, dtype=float)
    d1 = q1 - p1
    d2 = q2 - p2
    r = p1 - p2
    a = float(d1 @ d1)
    e = float(d2 @ d2)
    f = float(d2 @ r)
    eps = 1e-18
    if a <= eps and e <= eps:
        return float(np.linalg.norm(p1 - p2))
    if a <= eps:
        s = 0.0
        t = float(np.clip(f / e, 0.0, 1.0))
    else:
        c = float(d1 @ r)
        if e <= eps:
            t = 0.0
            s = float(np.clip(-c / a, 0.0, 1.0))
        else:
            b = float(d1 @ d2)
            denom = a * e - b * b
            s = float(np.clip((b * f - c * e) / denom, 0.0, 1.0)) if denom > eps else 0.0
            t = float((b * s + f) / e)
            if t < 0.0:
                t = 0.0
                s = float(np.clip(-c / a, 0.0, 1.0))
            elif t > 1.0:
                t = 1.0
                s = float(np.clip((b - c) / a, 0.0, 1.0))
    return float(np.linalg.norm(p1 + s * d1 - (p2 + t * d2)))
