"""分拣线配置（configs/sort.yaml）的加载与校验。

只依赖 PyYAML，保证配置面在任何轻量场景可独立使用（与
``beaneye.calibration.config`` 同约定）。全部校验失败抛
:class:`SortConfigError`，错误信息带文件路径与字段名。

配置分区（详见 configs/sort.yaml 注释）：

- ``workspace``：桌面系工作空间边界 + home 位（Mock 与 Session 共用的安全包络）；
- ``speeds``：各阶段限速（mm/s）与速度硬上限；
- ``pick``：抓取高度 / 巡航高度 / 夹爪耗时；
- ``extrinsic``：托盘系 → 臂系的平面外参（相机中心相对臂基座偏移 + 平面旋转，
  **默认值留待真机三点标定回填**）；
- ``bins``：缺陷类别 → 分级盒桌面坐标（mm）；``default`` 为未登记类别的兜底盒；
- ``estop``：软件急停语义参数；
- ``so101``：SO-101 真机参数（端口 / 舵机表 / 连杆几何占位值，**明日实测核对**）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "sort.yaml"

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "SortConfigError",
    "WorkspaceBounds",
    "SpeedLimits",
    "PickParams",
    "ExtrinsicParams",
    "EstopParams",
    "MotorSpec",
    "So101Params",
    "SortConfig",
    "load_sort_config",
]


class SortConfigError(ValueError):
    """分拣配置缺失 / YAML 非法 / 字段越界或自相矛盾。"""


# ---------------------------------------------------------------------------
# 分区数据类（全部 frozen，加载期定形）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkspaceBounds:
    """桌面系工作空间安全包络（长方体）。

    构造期即校验不变式（min<max、z>=0、home 在包络内），违规抛
    :class:`SortConfigError`——直接构造（测试/代码内）与 YAML 加载同一口径。
    """

    x_min_mm: float
    x_max_mm: float
    y_min_mm: float
    y_max_mm: float
    z_min_mm: float
    z_max_mm: float
    home_mm: tuple[float, float, float]

    def __post_init__(self) -> None:
        for name in ("x_min_mm", "y_min_mm", "z_min_mm", "x_max_mm", "y_max_mm", "z_max_mm"):
            v = float(getattr(self, name))
            if not math.isfinite(v):
                raise SortConfigError(f"workspace.{name} 必须是有限数，得到 {v}")
        if self.x_min_mm >= self.x_max_mm or self.y_min_mm >= self.y_max_mm or self.z_min_mm >= self.z_max_mm:
            raise SortConfigError(f"workspace 各 min 必须小于对应 max，得到 {self}")
        if self.z_min_mm < 0:
            raise SortConfigError(f"workspace.z_min_mm 不得为负（0=桌面），得到 {self.z_min_mm}")
        home = tuple(float(v) for v in self.home_mm)
        if len(home) != 3 or not all(math.isfinite(v) for v in home):
            raise SortConfigError(f"workspace.home_mm 必须是 [x, y, z] 有限数，得到 {self.home_mm!r}")
        if not self.contains(*home):
            raise SortConfigError(
                f"workspace.home_mm {home} 不在工作空间包络内——home 必须可达"
            )

    def contains(self, x: float, y: float, z: float, *, tol: float = 0.0) -> bool:
        """点 (x, y, z) 是否在包络内（含 ``tol`` 毫米容差）。"""
        return (
            self.x_min_mm - tol <= x <= self.x_max_mm + tol
            and self.y_min_mm - tol <= y <= self.y_max_mm + tol
            and self.z_min_mm - tol <= z <= self.z_max_mm + tol
        )

    def check(self, x: float, y: float, z: float, *, tol: float = 0.0) -> None:
        """不在包络内抛 :class:`SortConfigError`（带诊断信息）。"""
        if not self.contains(x, y, z, tol=tol):
            raise SortConfigError(
                f"目标点 ({x:.1f}, {y:.1f}, {z:.1f}) mm 超出工作空间包络 "
                f"x[{self.x_min_mm}, {self.x_max_mm}] "
                f"y[{self.y_min_mm}, {self.y_max_mm}] "
                f"z[{self.z_min_mm}, {self.z_max_mm}]"
            )


@dataclass(frozen=True)
class SpeedLimits:
    """各阶段限速（mm/s）。``max_mm_s`` 为硬上限，任何指令不得超过。"""

    max_mm_s: float
    default_mm_s: float
    travel_mm_s: float
    descend_mm_s: float
    lift_mm_s: float


@dataclass(frozen=True)
class PickParams:
    """抓取动作参数（毫米 / 秒）。"""

    pick_z_mm: float        # 抓取面高度（豆顶面）
    travel_z_mm: float      # 巡航安全高度
    gripper_travel_s: float  # 夹爪开合动作耗时（秒，Mock 模拟用）


@dataclass(frozen=True)
class ExtrinsicParams:
    """托盘系 → 臂系平面外参（2D 刚体：平面旋转 + 平移）。

    **默认全零留待真机标定**：托盘 ArUco 标定已给出 px→托盘 mm（含平面
    旋转），本节只补「托盘原点相对臂基座」的安装偏移与残余旋转。
    """

    yaw_deg: float
    offset_mm: tuple[float, float]


@dataclass(frozen=True)
class EstopParams:
    """软件急停语义。"""

    torque_off: bool             # 急停时是否下力矩（真机）
    require_home_after_resume: bool  # 复位后必须重新 home 才允许作业


@dataclass(frozen=True)
class MotorSpec:
    """单舵机参数（SO-101 Feetech 总线）。"""

    id: int
    min_deg: float
    max_deg: float
    center_raw: float      # 0° 对应的原始位置寄存器值
    raw_per_deg: float     # 度 → 原始值刻度（含方向；负值 = 反向）


@dataclass(frozen=True)
class So101Params:
    """SO-101 真机参数（连杆几何为占位默认值，明日实测核对回填）。"""

    port: str
    baudrate: int
    motors: dict[str, MotorSpec]
    base_offset_mm: float   # 基座旋转轴 → 肩关节的水平径向偏移
    shoulder_z_mm: float    # 肩关节相对桌面的高度
    l1_mm: float            # 肩 → 肘 有效连杆长
    l2_mm: float            # 肘 → 腕 + 夹爪 有效连杆长
    speed_scaling: float    # mm/s → 舵机速度寄存器值换算系数（占位）
    move_timeout_s: float
    poll_interval_s: float
    arrival_tol_deg: float
    gripper_open_deg: float    # 夹爪张开角
    gripper_closed_deg: float  # 夹爪夹紧角


@dataclass(frozen=True)
class SortConfig:
    """configs/sort.yaml 的强类型视图（不可变）。"""

    workspace: WorkspaceBounds
    speeds: SpeedLimits
    pick: PickParams
    extrinsic: ExtrinsicParams
    bins_mm: dict[str, tuple[float, float]]
    estop: EstopParams
    so101: So101Params
    source_path: Path | None = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# 加载与校验
# ---------------------------------------------------------------------------


def _require_map(raw: dict, key: str, where: str) -> dict:
    val = raw.get(key, None)
    if not isinstance(val, dict):
        raise SortConfigError(f"{where}: 缺少 `{key}` 节或其不是映射")
    return val


def _num(src: dict, key: str, where: str, *, default: float | None = None) -> float:
    val = src.get(key, default)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise SortConfigError(f"{where}: `{key}` 必须是数值，得到 {val!r}")
    v = float(val)
    if not math.isfinite(v):
        raise SortConfigError(f"{where}: `{key}` 必须是有限数，得到 {v}")
    return v


def _load_workspace(raw: dict, where: str) -> WorkspaceBounds:
    ws = _require_map(raw, "workspace", where)
    home_raw = ws.get("home_mm", None)
    if not isinstance(home_raw, (list, tuple)) or len(home_raw) != 3:
        raise SortConfigError(f"{where}: workspace.home_mm 必须是 [x, y, z]，得到 {home_raw!r}")
    # 包络不变式（min<max / z>=0 / home 可达）由 WorkspaceBounds 构造期统一把关
    return WorkspaceBounds(
        x_min_mm=_num(ws, "x_min_mm", where),
        x_max_mm=_num(ws, "x_max_mm", where),
        y_min_mm=_num(ws, "y_min_mm", where),
        y_max_mm=_num(ws, "y_max_mm", where),
        z_min_mm=_num(ws, "z_min_mm", where),
        z_max_mm=_num(ws, "z_max_mm", where),
        home_mm=(float(home_raw[0]), float(home_raw[1]), float(home_raw[2])),
    )


def _load_speeds(raw: dict, where: str) -> SpeedLimits:
    sp = _require_map(raw, "speeds", where)
    out = SpeedLimits(
        max_mm_s=_num(sp, "max_mm_s", where),
        default_mm_s=_num(sp, "default_mm_s", where),
        travel_mm_s=_num(sp, "travel_mm_s", where),
        descend_mm_s=_num(sp, "descend_mm_s", where),
        lift_mm_s=_num(sp, "lift_mm_s", where),
    )
    for name in ("default_mm_s", "travel_mm_s", "descend_mm_s", "lift_mm_s"):
        v = getattr(out, name)
        if not (0.0 < v):
            raise SortConfigError(f"{where}: speeds.{name} 必须 > 0，得到 {v}")
        if v > out.max_mm_s:
            raise SortConfigError(
                f"{where}: speeds.{name}={v} 超过硬上限 max_mm_s={out.max_mm_s}"
            )
    return out


def _load_pick(raw: dict, where: str) -> PickParams:
    pk = _require_map(raw, "pick", where)
    out = PickParams(
        pick_z_mm=_num(pk, "pick_z_mm", where),
        travel_z_mm=_num(pk, "travel_z_mm", where),
        gripper_travel_s=_num(pk, "gripper_travel_s", where),
    )
    if out.pick_z_mm < 0:
        raise SortConfigError(f"{where}: pick.pick_z_mm 不得为负，得到 {out.pick_z_mm}")
    if out.travel_z_mm <= out.pick_z_mm:
        raise SortConfigError(
            f"{where}: pick.travel_z_mm({out.travel_z_mm}) 必须 > pick_z_mm({out.pick_z_mm})"
        )
    if out.gripper_travel_s < 0:
        raise SortConfigError(f"{where}: pick.gripper_travel_s 不得为负")
    return out


def _load_extrinsic(raw: dict, where: str) -> ExtrinsicParams:
    ex = _require_map(raw, "extrinsic", where)
    off = ex.get("offset_mm", [0.0, 0.0])
    if not isinstance(off, (list, tuple)) or len(off) != 2:
        raise SortConfigError(f"{where}: extrinsic.offset_mm 必须是 [dx, dy]，得到 {off!r}")
    return ExtrinsicParams(
        yaw_deg=_num(ex, "yaw_deg", where),
        offset_mm=(float(off[0]), float(off[1])),
    )


def _load_bins(raw: dict, where: str) -> dict[str, tuple[float, float]]:
    bins = _require_map(raw, "bins", where)
    if not bins:
        raise SortConfigError(f"{where}: bins 不能为空（至少要有 default 兜底盒）")
    if "default" not in bins:
        raise SortConfigError(f"{where}: bins 必须含 `default` 兜底盒")
    out: dict[str, tuple[float, float]] = {}
    for key, xy in bins.items():
        if not isinstance(xy, (list, tuple)) or len(xy) != 2:
            raise SortConfigError(f"{where}: bins.{key} 必须是 [x, y] mm，得到 {xy!r}")
        x, y = float(xy[0]), float(xy[1])
        if not (math.isfinite(x) and math.isfinite(y)):
            raise SortConfigError(f"{where}: bins.{key} 必须是有限坐标，得到 {xy!r}")
        out[str(key)] = (x, y)
    return out


def _load_estop(raw: dict, where: str) -> EstopParams:
    es = _require_map(raw, "estop", where)
    return EstopParams(
        torque_off=bool(es.get("torque_off", True)),
        require_home_after_resume=bool(es.get("require_home_after_resume", True)),
    )


def _load_so101(raw: dict, where: str) -> So101Params:
    so = _require_map(raw, "so101", where)
    port = so.get("port", None)
    if not isinstance(port, str) or not port:
        raise SortConfigError(f"{where}: so101.port 必须是非空字符串（如 COM3），得到 {port!r}")
    baud = so.get("baudrate", None)
    if isinstance(baud, bool) or not isinstance(baud, int) or baud <= 0:
        raise SortConfigError(f"{where}: so101.baudrate 必须是正整数，得到 {baud!r}")
    motors_raw = _require_map(so, "motors", f"{where}.so101")
    if not motors_raw:
        raise SortConfigError(f"{where}: so101.motors 不能为空")
    motors: dict[str, MotorSpec] = {}
    seen_ids: set[int] = set()
    for name, m in motors_raw.items():
        if not isinstance(m, dict):
            raise SortConfigError(f"{where}: so101.motors.{name} 必须是映射")
        mid = m.get("id", None)
        if isinstance(mid, bool) or not isinstance(mid, int) or not (1 <= mid <= 253):
            raise SortConfigError(f"{where}: so101.motors.{name}.id 必须是 1..253 整数，得到 {mid!r}")
        if mid in seen_ids:
            raise SortConfigError(f"{where}: so101.motors.{name}.id={mid} 与其他舵机重复")
        seen_ids.add(mid)
        spec = MotorSpec(
            id=mid,
            min_deg=_num(m, "min_deg", f"{where}.so101.motors.{name}"),
            max_deg=_num(m, "max_deg", f"{where}.so101.motors.{name}"),
            center_raw=_num(m, "center_raw", f"{where}.so101.motors.{name}"),
            raw_per_deg=_num(m, "raw_per_deg", f"{where}.so101.motors.{name}"),
        )
        if spec.min_deg >= spec.max_deg:
            raise SortConfigError(
                f"{where}: so101.motors.{name} min_deg 必须小于 max_deg，得到 {spec}"
            )
        if spec.raw_per_deg == 0:
            raise SortConfigError(f"{where}: so101.motors.{name}.raw_per_deg 不得为 0")
        motors[str(name)] = spec
    for key in ("base_offset_mm", "shoulder_z_mm", "l1_mm", "l2_mm", "speed_scaling"):
        if _num(so, key, where) < 0:
            raise SortConfigError(f"{where}: so101.{key} 不得为负")
    return So101Params(
        port=port,
        baudrate=baud,
        motors=motors,
        base_offset_mm=_num(so, "base_offset_mm", where),
        shoulder_z_mm=_num(so, "shoulder_z_mm", where),
        l1_mm=_num(so, "l1_mm", where),
        l2_mm=_num(so, "l2_mm", where),
        speed_scaling=_num(so, "speed_scaling", where),
        move_timeout_s=_num(so, "move_timeout_s", where),
        poll_interval_s=_num(so, "poll_interval_s", where),
        arrival_tol_deg=_num(so, "arrival_tol_deg", where),
        gripper_open_deg=_num(so, "gripper_open_deg", where),
        gripper_closed_deg=_num(so, "gripper_closed_deg", where),
    )


def load_sort_config(path: str | Path | None = None) -> SortConfig:
    """加载并校验分拣配置；``path=None`` 用仓库默认 ``configs/sort.yaml``。"""
    p = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not p.is_file():
        raise SortConfigError(f"分拣配置文件不存在: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SortConfigError(f"分拣配置 YAML 解析失败 {p}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SortConfigError(f"分拣配置顶层必须是映射，{p} 得到 {type(raw).__name__}")
    where = str(p)

    cfg = SortConfig(
        workspace=_load_workspace(raw, where),
        speeds=_load_speeds(raw, where),
        pick=_load_pick(raw, where),
        extrinsic=_load_extrinsic(raw, where),
        bins_mm=_load_bins(raw, where),
        estop=_load_estop(raw, where),
        so101=_load_so101(raw, where),
        source_path=p,
    )
    # 交叉校验：巡航高度必须落在工作空间内；分级盒必须可达（xy 在包络内）
    ws = cfg.workspace
    if cfg.pick.travel_z_mm > ws.z_max_mm:
        raise SortConfigError(
            f"{where}: pick.travel_z_mm={cfg.pick.travel_z_mm} 超出工作空间 "
            f"z_max_mm={ws.z_max_mm}——巡航高度必须可达"
        )
    for name, (x, y) in cfg.bins_mm.items():
        if not ws.contains(x, y, cfg.pick.travel_z_mm):
            raise SortConfigError(
                f"{where}: bins.{name}=({x}, {y}) 在工作空间包络外（含巡航高度 "
                f"z={cfg.pick.travel_z_mm}）——分级盒必须放臂可及处"
            )
    return cfg
