"""仿真可视化演示（开发指令 §8.1）：MuJoCo 窗口里跑 舀取 → 送达 → 撤回 循环。

行为与验收同源：直接复用 cs_orchestra 的 mock 回合（MockArm 在 cs_sim 内
执行 + SafetyEnvelope 硬闸 + 行为树全节点），演示的就是 e2e 通过的那条链，
只是把关节流实时投到物理引擎窗口。

用法（cwd 任意）::

    python scripts/demo_sim.py                       # 交互窗口（缺省 3 口，6 倍速）
    python scripts/demo_sim.py --bites 5 --speed 2   # 口数 / 倍速（speed 0=全速）
    python scripts/demo_sim.py --live-config         # 每口之间重读 config/workspace.json
                                                     # （改碗位/禁入区实时生效）
    python scripts/demo_sim.py --rerun               # 关节流旁挂 Rerun（.rrd 落盘）
    python scripts/demo_sim.py --frames 24 --out reports/demo_sim_frames
                                                     # 无头冒烟：matplotlib 3D 帧落盘
                                                     # （无显示环境/GPU 时验证用，exit 0）

现场演示要点（讲稿）：
- 桌面三碗（config/workspace.json bowls_m），送达停点在面部球面之外 5cm，
  用户前倾取食——"勺停口前、人凑上来"的安全设计；
- --live-config 下当场改 workspace.json 的 bowls_m / mouth_point_m /
  forbidden_zones，下一口立即生效：改到不可行位置时安全包络会拒绝指令并
  如实闩锁——安全不是演示模式让出来的，是每条指令过闸闸出来的。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

_SCRIPT_DIR = Path(__file__).resolve().parent
PKG_ROOT = _SCRIPT_DIR.parent
_REPO_ROOT = PKG_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import matplotlib  # noqa: E402

from chengshao.cs_orchestra.mock import make_mock_episode  # noqa: E402
from chengshao.cs_orchestra.core import OrchestraParams  # noqa: E402
from chengshao.cs_sim import EnvelopeValidator  # noqa: E402


# ---- 演示驱动器（逐 tick 渲染钩子 + 可选 live-config 重载） ----------------------


class DemoDriver:
    """在树 tick 之间做三件事： paced 渲染 / live-config / Rerun 镜像。"""

    def __init__(self, params: OrchestraParams, speed: float,
                 live_config: bool, frame_hook=None, rerun_hook=None) -> None:
        self.params = params
        self.speed = float(speed)
        self.live_config = bool(live_config)
        self.frame_hook = frame_hook
        self.rerun_hook = rerun_hook
        self._last_wall = time.perf_counter()
        self._wall_budget = 0.0
        self._ws_mtime: float | None = self._stat_ws()

    @property
    def _workspace_path(self) -> Path:
        return PKG_ROOT / "config" / "workspace.json"

    def _stat_ws(self) -> float | None:
        try:
            return self._workspace_path.stat().st_mtime
        except OSError:
            return None

    # -- 渲染节流（把 50Hz 树 tick 押到 watchable 的墙钟节奏） -------------------
    def _pace(self) -> None:
        if self.speed <= 0:
            return
        now = time.perf_counter()
        self._wall_budget += self.params.tick_s / self.speed
        due = self._wall_budget - (now - self._last_wall)
        if due > 0:
            time.sleep(min(due, 0.5))

    def _reload_if_changed(self, ctx) -> None:
        if not self.live_config:
            return
        mtime = self._stat_ws()
        if mtime is None or mtime == self._ws_mtime:
            return
        self._ws_mtime = mtime
        new_validator = EnvelopeValidator()  # 重读 config/workspace.json
        old = ctx.validator
        ctx.validator = new_validator
        ctx.env._validator = new_validator      # noqa: SLF001（演示脚本换闸配置）
        mock = ctx.env.inner
        if hasattr(mock, "_validator"):
            mock._validator = new_validator     # noqa: SLF001
        try:
            ctx.state.face_center = np.asarray(
                new_validator.config.face_center, dtype=float)
        except AttributeError:
            pass
        ctx.trace.add("live_config_reloaded", ts_ns=ctx.now_ns(),
                      face_center=[float(v) for v in new_validator.config.face_center])
        _ = old

    def on_tick(self, ctx, tick_i: int) -> None:
        del tick_i
        self._pace()
        # 口与口之间（bite=None）才是换配置的安全点
        if ctx.bite is None:
            self._reload_if_changed(ctx)
        if self.frame_hook is not None:
            self.frame_hook(ctx)
        if self.rerun_hook is not None:
            self.rerun_hook(ctx)


# ---- MuJoCo 交互窗口 --------------------------------------------------------------


def _mujoco_handles(model):
    """从 cs_sim 模型取出物理引擎原生 model/data（tier!=mjcf 时返回 None）。"""
    backend = getattr(model, "_backend", None)
    mj_model = getattr(backend, "_model", None) or getattr(backend, "mj_model", None)
    mj_data = getattr(backend, "_data", None) or getattr(backend, "mj_data", None)
    if mj_model is None or mj_data is None:
        return None, None, None
    return mj_model, mj_data, backend


def run_viewer(ns, driver: DemoDriver) -> None:
    """launch_passive 窗口 + 逐 tick 同步关节角；无 mjcf 模型时降级说明。"""
    mj_model, mj_data, backend = _mujoco_handles(ns.model)
    if mj_model is None:
        print("当前模型回退链层级不是物理引擎原生（tier=%s），无窗口可开；"
              "改用 --frames N 落帧演示。" % getattr(ns.model, "tier", "?"))
        ns.runner.run(driver)
        return
    import mujoco
    import mujoco.viewer

    jids = list(getattr(backend, "_jids", []))
    qadr = list(getattr(backend, "_qadr", []))
    last_sync = [0.0]

    with mujoco.viewer.launch_passive(mj_model, mj_data) as viewer:

        def push(ctx) -> None:
            q = ns.mock.current_q()
            for j, a in zip(jids, qadr):
                mj_data.qpos[a] = float(q[j])
            mujoco.mj_forward(mj_model, mj_data)
            now = time.perf_counter()
            if now - last_sync[0] > 1.0 / 60.0:  # 视窗 ~60fps 即可，别拖满 tick 率
                viewer.sync()
                last_sync[0] = now

        driver.frame_hook = push
        print("演示循环：舀取 → 送达（停点在面部球外 5cm）→ 等咬合 → 撤回；"
              "关闭窗口或跑满口数即结束。")
        summary = ns.runner.run(driver)
        viewer.sync()
    _print_summary(summary)


# ---- 无头落帧（matplotlib 3D；零 GL 依赖） ------------------------------------------


def run_frames(ns, driver: DemoDriver, n_frames: int, out_dir: Path) -> None:
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # 中文标注字体（Windows 自带雅黑/黑体；缺失时回退默认，仅告警不失败）
    try:
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
    except Exception:  # noqa: BLE001 —— 字体缺失不阻塞落帧
        pass
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: F401

    out_dir.mkdir(parents=True, exist_ok=True)
    model, validator = ns.model, ns.validator
    face = np.asarray(validator.config.face_center, dtype=float)
    face_r = validator.face_radius
    stop = np.asarray(validator.delivery_stop_point(), dtype=float)
    bowls = ns.params.bowls_m()
    home = np.asarray(ns.params.home_point_m, dtype=float)

    snaps: list[tuple[int, np.ndarray, str]] = []

    def grab(ctx) -> None:
        snaps.append((int(ctx.now_ns()), ns.mock.current_q(),
                      _phase_label(ctx)))

    driver.frame_hook = grab
    summary = ns.runner.run(driver)
    _print_summary(summary)

    if not snaps:
        raise RuntimeError("未采到任何帧")
    picks = np.unique(np.linspace(0, len(snaps) - 1, n_frames).astype(int))
    for k, i in enumerate(picks):
        ts, q, label = snaps[int(i)]
        fig = plt.figure(figsize=(7, 6))
        ax = fig.add_subplot(111, projection="3d")
        tcp = np.asarray(model.fk(q)[0:3], dtype=float)
        pts = np.asarray(model.link_points(q), dtype=float)
        chain = np.vstack([pts, tcp])
        ax.plot(chain[:, 0], chain[:, 1], chain[:, 2], "-o", c="#2660a4",
                ms=3, lw=1.6, label="arm")
        ax.scatter([tcp[0]], [tcp[1]], [tcp[2]], c="#ce2d4f", s=42, label="TCP/勺")
        _draw_sphere(ax, face, face_r, "#ee6c4d")
        ax.scatter([stop[0]], [stop[1]], [stop[2]], marker="*", c="#1b998b",
                   s=90, label="送达停点")
        for bi, bp in enumerate(bowls):
            ax.scatter([bp[0]], [bp[1]], [bp[2]], marker="s", s=60, label=f"碗{bi}")
        ax.scatter([home[0]], [home[1]], [home[2]], marker="^", c="#54445b",
                   s=50, label="家位")
        t = ts / 1e9
        ax.set_title(f"t={t:6.1f}s  {label}")
        ax.set_xlabel("x/m"); ax.set_ylabel("y/m"); ax.set_zlabel("z/m")
        ax.set_xlim(0.0, 0.55); ax.set_ylim(-0.35, 0.35); ax.set_zlim(-0.05, 0.5)
        ax.legend(loc="upper left", fontsize=7)
        fig.tight_layout()
        path = out_dir / f"frame_{k:03d}.png"
        fig.savefig(path, dpi=110)
        plt.close(fig)
    print(f"frames -> {out_dir}（{len(picks)} 张，源采样 {len(snaps)}）")


def _phase_label(ctx) -> str:
    b = ctx.bite
    if b is None:
        return f"口间（已完成 {len(ctx.bites_done)} 口）"
    return f"第{b.idx}口 {b.phase.name}（camera_role={ctx.camera_role}）"


def _draw_sphere(ax, center, radius, color) -> None:
    u = np.linspace(0, 2 * np.pi, 20)
    v = np.linspace(0, np.pi, 12)
    x = center[0] + radius * np.outer(np.cos(u), np.sin(v))
    y = center[1] + radius * np.outer(np.sin(u), np.sin(v))
    z = center[2] + radius * np.outer(np.ones_like(u), np.cos(v))
    ax.plot_wireframe(x, y, z, color=color, lw=0.4, alpha=0.5)


# ---- Rerun 旁挂（可选） -------------------------------------------------------------


def _wire_rerun() -> object | None:
    try:
        import rerun as rr
    except Exception:  # noqa: BLE001
        print("rerun-sdk 未安装，跳过旁挂视图")
        return None
    out = PKG_ROOT / "reports" / "demo_sim.rrd"
    rr.init("chengshao-demo-sim")
    rr.save(str(out))
    state = {"role": None, "bite": None}

    def hook(ctx) -> None:
        st_q = ctx.env.read().joint_pos
        rr.log("arm/joints", rr.Scalars([float(v) for v in st_q]))
        role = str(ctx.camera_role)
        if role != state["role"]:
            rr.log("camera/role", rr.TextLog(role))
            state["role"] = role
        bite = None if ctx.bite is None else ctx.bite.idx
        if bite != state["bite"]:
            rr.log("meal/bite", rr.TextLog(f"bite {bite}"))
            state["bite"] = bite

    print(f"rerun 镜像 -> {out}（演示后 `rerun {out.name}` 回放）")
    return hook


def _print_summary(summary: dict) -> None:
    print(f"demo 完成：bites={summary['bites']} outcomes={summary['outcomes']} "
          f"sim_s={summary['sim_s']} violations(unexpected)={summary['unexpected_failures']}")


# ---- 主流程 --------------------------------------------------------------------------


def _parse_args(argv=None):
    ap = argparse.ArgumentParser(
        prog="python scripts/demo_sim.py",
        description="仿真可视化演示：舀取→送达→撤回循环（§8.1；全 Mock 零硬件）")
    ap.add_argument("--bites", type=int, default=3, help="演示口数（默认 3）")
    ap.add_argument("--speed", type=float, default=6.0,
                    help="仿真加速倍数（仿真秒/墙钟秒）；0=全速（默认 6）")
    ap.add_argument("--live-config", action="store_true",
                    help="每口之间重读 config/workspace.json（碗位/禁入区实时生效）")
    ap.add_argument("--rerun", action="store_true", help="旁挂 Rerun 镜像（.rrd）")
    ap.add_argument("--frames", type=int, default=0,
                    help="无头冒烟：落 N 张 matplotlib 3D 帧（不交互，exit 0）")
    ap.add_argument("--out", default=str(PKG_ROOT / "reports" / "demo_sim_frames"),
                    help="落帧目录（--frames 模式）")
    ap.add_argument("--seed", type=int, default=20260929)
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    params = OrchestraParams.load()
    rerun_hook = _wire_rerun() if args.rerun else None
    ns = make_mock_episode(episode=1, script={}, bites=max(1, args.bites),
                           params=params, seed=args.seed)
    driver = DemoDriver(params, speed=args.speed, live_config=args.live_config,
                        rerun_hook=rerun_hook)
    print(f"模型层级 tier={ns.model.tier} 关节={ns.model.joint_names}")
    print(f"禁入区：面部球心 {np.round(ns.validator.config.face_center, 3).tolist()} "
          f"r={ns.validator.face_radius}m；送达停点 "
          f"{np.round(ns.validator.delivery_stop_point(), 3).tolist()}（球外 5cm）")
    if args.frames > 0:
        run_frames(ns, driver, args.frames, Path(args.out))
    else:
        run_viewer(ns, driver)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
