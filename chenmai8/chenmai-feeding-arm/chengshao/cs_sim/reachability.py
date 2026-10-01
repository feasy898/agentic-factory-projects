"""可达空间分析：体素网格扫描与 PNG 渲染（开发指令 §5.1）。

可达定义（位置级）：存在关节向量 q（满足限位）使 TCP 到达该体素中心。
扫描用仅位置 DLS（速度更快），相邻体素间温启动（上一解作初值）以加速收敛。
"""

from __future__ import annotations

import numpy as np

from .backends import KinematicBackend
from .ik_solver import solve_dls, solve_with_restarts

__all__ = ["build_grid_points", "sweep_reachability", "render_reach_map_png"]

_GRID_KEYS = ("x_m", "y_m", "z_m")


def build_grid_points(grid: dict) -> np.ndarray:
    """网格描述 -> 体素中心点阵 (N, 3)。

    ``grid`` 结构：{"x_m": [min, max], "y_m": [min, max], "z_m": [min, max],
    "res_m": 步长}。扫描顺序为 x->y->z 递增（利于温启动）。
    """
    for key in _GRID_KEYS:
        if key not in grid or len(grid[key]) != 2 or grid[key][0] >= grid[key][1]:
            raise ValueError(f"invalid grid bounds for {key!r}: {grid.get(key)}")
    res = float(grid.get("res_m", 0.05))
    if res <= 1e-4:
        raise ValueError(f"grid res too small: {res}")

    def _axis(lo: float, hi: float) -> np.ndarray:
        # 端点含入的确定性计数（避免 arange 的浮点端点抖动）
        n = int(round((hi - lo) / res)) + 1
        return lo + res * np.arange(n, dtype=float)

    xs = _axis(float(grid["x_m"][0]), float(grid["x_m"][1]))
    ys = _axis(float(grid["y_m"][0]), float(grid["y_m"][1]))
    zs = _axis(float(grid["z_m"][0]), float(grid["z_m"][1]))
    if len(xs) * len(ys) * len(zs) > 200_000:
        raise ValueError("grid too large; increase res_m")
    pts = np.stack(np.meshgrid(xs, ys, zs, indexing="ij"), axis=-1).reshape(-1, 3)
    return np.ascontiguousarray(pts, dtype=float)


def sweep_reachability(backend: KinematicBackend, points: np.ndarray) -> np.ndarray:
    """对点阵逐点做位置级 IK，返回 bool 数组（True=可达）。

    温启动：按输入顺序扫描，上一体素的解作为下一体的初值；失败再用确定性
    多起点重启兜底。v3.1 审查补丁（修复 IK 假收敛）后重校：单一 warm/名义
    位形尝试会把可达体素大量漏判（200 体素抽样实测：仅 warm 6%，+12 重启
    兜底 ~50%，32 重启 54%），故加重启兜底。
    """
    lower = backend.joint_lower
    upper = backend.joint_upper
    mid = 0.5 * (lower + upper)
    warm = mid.copy()
    flags = np.zeros(len(points), dtype=bool)
    pos_tol = 5e-4  # 与 IK 收敛门槛一致（远小于体素尺寸，避免跨体素误判）
    fallback_restarts = 12
    for i, p in enumerate(points):
        # 目标姿态：保持当前温启动构型姿态（位置级可达性对姿态不敏感）
        _, rot = backend.fk(warm)
        res = solve_dls(
            backend, p, rot, warm, iters=80, pos_tol_m=pos_tol, pos_only=True, max_step_rad=0.8
        )
        solved = res.converged
        q_sol = res.q
        if not solved:
            # 兜底：确定性多起点重启（逐体素同种子序列，可复现）
            res2 = solve_with_restarts(
                backend, p, rot, pos_only=True, restarts=fallback_restarts, rng_seed=1
            )
            if res2 is not None and res2.converged:
                solved = True
                q_sol = res2.q
        if solved:
            flags[i] = True
            warm = np.clip(q_sol, lower, upper)
        else:
            warm = mid.copy()
    return flags


def render_reach_map_png(result: dict, out_path) -> str:
    """可达性结果 -> PNG（3D 散点 + 中面切片）。返回写出路径字符串。

    无显示环境安全：强制 Agg 后端。
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pts = np.asarray(result.get("reachable_points_m", []), dtype=float)
    grid = result.get("grid", {})
    res_m = float(grid.get("res_m", 0.0))
    bounds = {k: grid.get(k, [0.0, 0.0]) for k in ("x_m", "y_m", "z_m")}

    # 重建不可达点阵（用于灰底显示）
    all_pts = build_grid_points(grid)
    n_all = len(all_pts)
    n_ok = len(pts)
    mask = np.zeros(n_all, dtype=bool)
    if n_ok:
        # reachable 点即 all_pts 的子集（同序生成），用最近邻匹配标记
        from scipy.spatial import cKDTree

        tree = cKDTree(all_pts)
        _, idx = tree.query(pts, k=1)
        mask[np.asarray(idx, dtype=int)] = True

    fig = plt.figure(figsize=(13.0, 5.6), dpi=130)
    ax = fig.add_subplot(1, 2, 1, projection="3d")
    if n_all > n_ok:
        ax.scatter(
            all_pts[~mask][:, 0], all_pts[~mask][:, 1], all_pts[~mask][:, 2],
            s=3, c="lightgray", alpha=0.25, label="unreachable",
        )
    if n_ok:
        sc = ax.scatter(
            pts[:, 0], pts[:, 1], pts[:, 2], s=5, c=pts[:, 2], cmap="viridis",
            alpha=0.85, label="reachable",
        )
        fig.colorbar(sc, ax=ax, shrink=0.6, label="z (m)")
    ax.set_xlabel("x (m)"); ax.set_ylabel("y (m)"); ax.set_zlabel("z (m)")
    frac = result.get("reachable_fraction", 0.0)
    ax.set_title(f"Reachable workspace (pos-level IK)\n"
                 f"{result.get('n_voxels_reachable', 0)}/{result.get('n_voxels_total', 0)}"
                 f" voxels = {frac * 100:.1f}%  res={res_m:.3f} m")
    ax.legend(loc="upper left", fontsize=8)

    ax2 = fig.add_subplot(1, 2, 2)
    # 取 |y| 最小的层面作 XZ 切片热图
    if n_all:
        ys = np.unique(np.round(all_pts[:, 1], 6))
        y_mid = ys[len(ys) // 2] if len(ys) else 0.0
        sel = np.abs(all_pts[:, 1] - y_mid) < 1e-6
        xs = np.unique(np.round(all_pts[sel, 0], 6))
        zs = np.unique(np.round(all_pts[sel, 2], 6))
        grid2d = np.full((len(zs), len(xs)), np.nan)
        xi = {v: i for i, v in enumerate(xs)}
        zi = {v: i for i, v in enumerate(zs)}
        ok = mask[sel]
        for k, pt in enumerate(all_pts[sel]):
            if ok[k]:
                grid2d[zi[round(float(pt[2]), 6)], xi[round(float(pt[0]), 6)]] = 1.0
        im = ax2.pcolormesh(xs, zs, grid2d, shading="nearest", cmap="Greens", vmin=0, vmax=1.4)
        fig.colorbar(im, ax=ax2, shrink=0.8, label="reachable (1)")
        ax2.set_xlabel("x (m)"); ax2.set_ylabel("z (m)")
        ax2.set_title(f"XZ slice @ y={y_mid:+.3f} m")
        ax2.set_aspect("equal")

    fig.suptitle("cs_sim reachability map (base frame, X forward / Y left / Z up)", fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    out_path = str(out_path)
    fig.savefig(out_path)
    plt.close(fig)
    return out_path
