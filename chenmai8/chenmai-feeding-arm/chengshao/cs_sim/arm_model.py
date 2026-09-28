"""ArmModel：面向冻结契约（开发指令 §3.2）的仿真层机械模型。

契约签名（只增不改）::

    def load_arm(physics_model_path: str = "auto") -> cs_sim.ArmModel
    class ArmModel:
        def fk(self, q: list[float]) -> list[float]            # -> ee_pos+quat
        def ik(self, target_pos, target_quat, seed=None) -> list[float] | None
        def reachable_map(self, grid) -> dict

- ``fk`` 返回 7 个浮点：ee_pos(3, base 系, 米) + ee_quat(4, [w,x,y,z])，
  与 cs_schema 的 EE_POS_LEN + EE_QUAT_LEN 布局一致；
- ``ik`` 无解（或超差）返回 None；
- ``grid`` 为体素网格描述 dict：{"x_m":[min,max], "y_m":[...], "z_m":[...], "res_m": r}；
- 模型回退链见 ``model_source``：MJCF -> URDF -> 内置名义链，``physics_model_path``
  为 ``"auto"``（或空串）时自动走链，显式路径则按扩展名选择装载器并严格校验。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .backends import IkpyChainBackend, KinematicBackend, MujocoBackend
from .frames import matrix_from_quat, quat_from_matrix
from .ik_solver import IkResult, solve_with_restarts
from .model_source import (
    DEFAULT_MODEL_SOURCE,
    MODEL_TIER_CHAIN_BUILTIN,
    ModelResolution,
    discover_model_file,
    file_sha256_prefix,
)
from .reachability import build_grid_points, render_reach_map_png, sweep_reachability

__all__ = ["ArmModel", "load_arm", "EE_POSE_VEC_LEN", "DEFAULT_GRID"]

# fk 输出向量长度 = ee_pos(3) + ee_quat(4)（对应冻结契约 §3.1 的字段布局）
EE_POSE_VEC_LEN = 7

# 可达空间默认扫描范围（base 系，米）：覆盖参考臂的全部作业空间并留边
DEFAULT_GRID: dict = {
    "x_m": [0.00, 0.50],
    "y_m": [-0.40, 0.40],
    "z_m": [-0.05, 0.50],
    "res_m": 0.03,
}


class ArmModel:
    """冻结契约的 ArmModel。内部持有运动学后端，屏蔽回退链差异。"""

    def __init__(self, backend: KinematicBackend) -> None:
        self._backend = backend
        self.info: dict = dict(backend.source_meta())

    # ---- 契约属性（只增） -----------------------------------------------------

    @property
    def tier(self) -> str:
        """模型回退层级：mjcf / urdf_mujoco / chain_builtin / chain_urdf_ikpy。"""
        return self._backend.tier

    @property
    def n_joints(self) -> int:
        return self._backend.n_joints

    @property
    def joint_names(self) -> list[str]:
        return list(self._backend.joint_names)

    @property
    def joint_lower(self) -> list[float]:
        return [float(v) for v in self._backend.joint_lower]

    @property
    def joint_upper(self) -> list[float]:
        return [float(v) for v in self._backend.joint_upper]

    # ---- 冻结契约方法 ---------------------------------------------------------

    def fk(self, q: list[float]) -> list[float]:
        """正运动学：q -> [x, y, z, qw, qx, qy, qz]（base 系，米 / w 在前四元数）。"""
        pos, rot = self._backend.fk(np.asarray(q, dtype=float))
        quat = quat_from_matrix(rot)
        return [float(pos[0]), float(pos[1]), float(pos[2]),
                float(quat[0]), float(quat[1]), float(quat[2]), float(quat[3])]

    def ik(
        self,
        target_pos: list[float],
        target_quat: list[float],
        seed: list[float] | None = None,
    ) -> list[float] | None:
        """逆运动学：目标位置(3) + 目标四元数(4, w 在前) -> q 或 None（无解/超差）。

        内部多起点 DLS，收敛门槛（0.5mm / 5mrad）严于 §5.1 通过线
        （5mm / 0.05rad）。返回的 q 满足关节限位。
        """
        tp = np.asarray(target_pos, dtype=float)
        tq = np.asarray(target_quat, dtype=float)
        if tp.shape != (3,):
            raise ValueError(f"target_pos must have 3 elements, got shape {tp.shape}")
        if tq.shape != (4,):
            raise ValueError(f"target_quat must have 4 elements [w,x,y,z], got shape {tq.shape}")
        trot = matrix_from_quat(tq)
        seed_arr = None if seed is None else np.asarray(seed, dtype=float)
        res = solve_with_restarts(self._backend, tp, trot, seed=seed_arr)
        if res is None or not res.converged:
            return None
        return [float(v) for v in res.q]

    def reachable_map(self, grid: dict) -> dict:
        """可达性体素统计（位置级可达：存在 q 使 TCP 到达该体素中心）。

        返回 dict：网格描述、体素计数、可达比例、可达点列表等（含 PNG 渲染
        所需数据，渲染本身用 :func:`render_reach_map_png`）。
        """
        points = build_grid_points(grid)
        reachable = sweep_reachability(self._backend, points)
        n_total = int(points.shape[0])
        n_ok = int(np.count_nonzero(reachable))
        return {
            "grid": dict(grid),
            "n_voxels_total": n_total,
            "n_voxels_reachable": n_ok,
            "reachable_fraction": (n_ok / n_total) if n_total else 0.0,
            "reachable_points_m": points[reachable].tolist(),
            "n_unreachable": n_total - n_ok,
        }

    # ---- 扩展方法（契约允许的只增部分） ---------------------------------------

    def ik_detailed(
        self,
        target_pos: list[float],
        target_quat: list[float],
        seed: list[float] | None = None,
        restarts: int | None = None,
    ) -> IkResult | None:
        """带诊断信息的 IK（供 eval 与调试；契约外的只增方法）。

        ``restarts=None`` 时用求解器默认重启数（32）。
        """
        trot = matrix_from_quat(np.asarray(target_quat, dtype=float))
        seed_arr = None if seed is None else np.asarray(seed, dtype=float)
        kwargs = {} if restarts is None else {"restarts": restarts}
        return solve_with_restarts(
            self._backend, np.asarray(target_pos, dtype=float), trot, seed=seed_arr, **kwargs
        )

    def fk_pose(self, q: list[float]) -> tuple[np.ndarray, np.ndarray]:
        """fk 的矩阵形式（内部/调试用）：(pos (3,), R (3,3))。"""
        return self._backend.fk(np.asarray(q, dtype=float))

    def validate(self) -> dict:
        """装载校验（load_arm 的"加载并校验"）：结构、数值、自洽性检查。

        任一检查不过即抛 ValueError。返回摘要 dict。
        """
        b = self._backend
        if b.n_joints < 2:
            raise ValueError(f"too few joints: {b.n_joints}")
        if len(b.joint_names) != b.n_joints:
            raise ValueError("joint_names length mismatch")
        if not np.all(np.isfinite(b.joint_lower)) or not np.all(np.isfinite(b.joint_upper)):
            raise ValueError("non-finite joint limits")
        if np.any(b.joint_upper <= b.joint_lower):
            raise ValueError("invalid joint limits (upper <= lower)")
        mid = 0.5 * (b.joint_lower + b.joint_upper)
        pose = self.fk([float(v) for v in mid])
        if len(pose) != EE_POSE_VEC_LEN or not all(np.isfinite(pose)):
            raise ValueError(f"fk output invalid: {pose}")
        quat_norm = float(np.linalg.norm(pose[3:7]))
        if abs(quat_norm - 1.0) > 1e-6:
            raise ValueError(f"fk quaternion not unit: |q|={quat_norm}")
        # TCP 应落在合理工作包络内（参考臂 ~0.5m 级）
        reach = float(np.linalg.norm(pose[0:3]))
        if reach > 1.2 or reach < 0.02:
            raise ValueError(f"TCP at mid pose out of plausible envelope: {reach:.3f} m")
        return {
            "n_joints": b.n_joints,
            "joint_names": list(b.joint_names),
            "tcp_mid_reach_m": reach,
            "tier": b.tier,
        }

    def render_reach_map(self, result: dict, out_path) -> str:
        """把 :meth:`reachable_map` 的结果渲染为 PNG，返回写出路径。"""
        return render_reach_map_png(result, out_path)


def load_arm(physics_model_path: str = DEFAULT_MODEL_SOURCE) -> ArmModel:
    """装载机械模型（冻结契约入口）："auto" 走回退链；显式路径严格装载。"""
    path_str = (physics_model_path or DEFAULT_MODEL_SOURCE).strip()
    if path_str in ("", DEFAULT_MODEL_SOURCE):
        resolution: ModelResolution = discover_model_file()
        backend = _backend_for(resolution)
        model = ArmModel(backend)
        model.validate()
        return model

    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"model file not found: {path}")
    backend = MujocoBackend(path)
    model = ArmModel(backend)
    model.validate()
    return model


def _backend_for(resolution: ModelResolution) -> KinematicBackend:
    """按回退链解析结果构造后端；任一层装载/校验失败自动降到下一层。

    层序：MJCF（物理引擎）→ 同目录 URDF（物理引擎）→ 同目录 URDF（ikpy 链）
    → 内置名义链（无文件依赖，最后手段）。
    """
    candidates: list[Path] = []
    if resolution.path is not None:
        candidates.append(resolution.path)
        if resolution.path.suffix.lower() in (".xml", ".mjcf"):
            sibling = resolution.path.with_suffix(".urdf")
            if sibling.exists():
                candidates.append(sibling)

    for cand in candidates:
        try:
            backend: KinematicBackend = MujocoBackend(cand)
            ArmModel(backend).validate()
            return backend
        except Exception:  # noqa: BLE001 —— 回退链语义：降级继续
            continue

    # URDF 的纯运动学链途径（不依赖物理引擎），最后才是内置名义链
    urdf_candidates = [c for c in candidates if c.suffix.lower() == ".urdf"]
    for cand in urdf_candidates:
        try:
            chain_backend = IkpyChainBackend(urdf_path=cand)
            ArmModel(chain_backend).validate()
            return chain_backend
        except Exception:  # noqa: BLE001
            continue
    return IkpyChainBackend()
