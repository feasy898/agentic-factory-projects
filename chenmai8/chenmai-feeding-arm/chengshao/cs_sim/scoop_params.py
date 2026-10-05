"""舀取扫参配置装载与校验（D4 真机逐食物调参的预扫入口，配套 cs_sim.scoop_sweep）。

配置文件：``config/scoop_params.json``。内容分五段：

- ``food_set_source`` / ``foods``：食物集合与逐食物"捕获模型卡"。食物集合以
  仓库既有定义为准（``cs_schema.constants.DEFAULT_DISH_REGISTRY``），调用方用
  ``load_scoop_config(..., allowed_foods=...)`` 显式传入并做覆盖校验；
- ``spoon_geometry``：勺/碗几何与勺上检测口径（``min_food_ratio`` 与
  ``config/food_hsv.json`` 同值，改动须两边同步）；
- ``grid``：五个扫参维度的取值表（每维 ≤3 个取值，超限直接拒绝）；
- ``search``：试验次数/重试轮数/随机种子（试验次数上限 500，超限拒绝）；
- ``recommended``：扫参产出的每食物推荐参数（由 ``cs_sim.scoop_sweep`` 写回）。

纪律与 ``cs_food.config`` 一致：校验失败一律抛 ValueError 且错误带字段名；
**未声明的键视为拼写漂移，同样拒绝**。本模块只依赖标准库
（不 import cs_sim/cs_orchestra/cs_schema），保持 cs_sim 内的可独立复现性。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "DEFAULT_SCOOP_CONFIG_PATH",
    "FoodCard",
    "GridSpec",
    "ScoopConfig",
    "SpoonGeometry",
    "GRID_DIMS",
    "MAX_TRIALS_PER_FOOD",
    "MAX_GRID_VALUES_PER_DIM",
    "FOOD_SET_SOURCE",
    "load_scoop_config",
]

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
DEFAULT_SCOOP_CONFIG_PATH = CONFIG_DIR / "scoop_params.json"

#: 食物集合的权威来源（cs_schema 冻结常量，本模块只登记出处不做 import）
FOOD_SET_SOURCE = "cs_schema.constants.DEFAULT_DISH_REGISTRY"

#: 五个扫参维度（与 cs_orchestra.runtime.ScriptedScoop 构造参数同名）
GRID_DIMS: tuple[str, ...] = (
    "dip_offset_m",
    "tilt_deg",
    "approach_speed_mps",
    "retract_speed_mps",
    "bowl_rim_scrape",
)
MAX_GRID_VALUES_PER_DIM = 3  # 任务约束：每维 ≤3 个取值
MAX_TRIALS_PER_FOOD = 500  # 任务约束：每食物模拟试验 ≤500 次

_TOP_KEYS = {"_note", "version", "food_set_source", "spoon_geometry",
             "grid", "search", "foods", "recommended"}
_GEOM_KEYS = {"spoon_bowl_radius_m", "spoon_bowl_depth_m", "spoon_tip_drop_m",
              "bowl_interior_radius_m", "bowl_rim_offset_m", "food_fill_depth_m",
              "min_food_ratio", "full_spoon_mask_ratio"}
_SEARCH_KEYS = {"trials_per_food", "max_attempts", "seed", "entry_lateral_correction_m"}
_FOOD_KEYS = {"display_name", "rheology", "hsv_detectable", "hsv_note", "fill_factor",
              "push_speed_mps", "retention_speed_mps", "tilt_knee_deg", "tilt_fail_deg",
              "scrape_extra_ml", "surface_jitter_m", "entry_lateral_error_m",
              "bowl_place_error_m", "closed_loop_gain", "provenance"}
_RECOMMENDED_KEYS = set(GRID_DIMS) | {"sim_first_attempt_rate", "sim_final_success_rate",
                                     "sim_trials", "sim_attempts_per_trial",
                                     "source_report", "feasible_combos", "grid_size"}
_RHEOLOGIES = {"viscous_paste", "thin_porridge", "solid_gel"}


# ---- 校验小工具（与 cs_food.config 同纪律：ValueError + 字段名） ----------------

def _read_json(path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f"配置文件不存在: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"配置文件不是合法 JSON: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise ValueError(f"配置文件顶层必须是对象: {path}")
    return data


def _check_keys(data: dict, allowed: set[str], where: str,
                optional: frozenset[str] | set[str] = frozenset()) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"{where} 存在未声明字段: {unknown}")
    missing = sorted(allowed - optional - set(data))
    if missing:
        raise ValueError(f"{where} 缺少必需字段: {missing}")


def _num(data: dict, key: str, where: str, *, lo: float | None = None,
         hi: float | None = None) -> float:
    v = data[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"{where}.{key} 必须是数值（得到 {v!r}）")
    f = float(v)
    if lo is not None and f < lo:
        raise ValueError(f"{where}.{key}={f} 必须 ≥ {lo}")
    if hi is not None and f > hi:
        raise ValueError(f"{where}.{key}={f} 必须 ≤ {hi}")
    return f


def _int(data: dict, key: str, where: str, *, lo: int | None = None,
         hi: int | None = None) -> int:
    v = data[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValueError(f"{where}.{key} 必须是整数（得到 {v!r}）")
    if lo is not None and v < lo:
        raise ValueError(f"{where}.{key}={v} 必须 ≥ {lo}")
    if hi is not None and v > hi:
        raise ValueError(f"{where}.{key}={v} 必须 ≤ {hi}")
    return int(v)


def _text(data: dict, key: str, where: str) -> str:
    v = data[key]
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"{where}.{key} 必须是非空字符串")
    return v


def _flag(data: dict, key: str, where: str) -> bool:
    v = data[key]
    if not isinstance(v, bool):
        raise ValueError(f"{where}.{key} 必须是布尔值（得到 {v!r}）")
    return v


# ---- 数据类 ---------------------------------------------------------------------

@dataclass(frozen=True)
class SpoonGeometry:
    """勺/碗几何与勺上检测口径（长度单位 m，体积单位 ml）。

    - ``spoon_bowl_*``：勺碗球冠（半径、深度）；球冠容积 = π h²(3r−h)/3；
    - ``spoon_tip_drop_m``：TCP 到勺碗最低点的垂直落差（装配尺寸）；
    - ``bowl_*``：腕部相机视野内的碗内腔（内半径/碗口高度/食物液面高度），
      ``bowls_m`` 的 z 视为碗内底面；
    - ``min_food_ratio``：勺上有食物判定阈值（与 config/food_hsv.json 同值）；
    - ``full_spoon_mask_ratio``：满勺时勺区裁剪内食物掩码占比（工程先验）。
    """

    spoon_bowl_radius_m: float
    spoon_bowl_depth_m: float
    spoon_tip_drop_m: float
    bowl_interior_radius_m: float
    bowl_rim_offset_m: float
    food_fill_depth_m: float
    min_food_ratio: float
    full_spoon_mask_ratio: float

    def spoon_capacity_ml(self) -> float:
        """勺碗球冠容积（ml）。"""
        r, h = self.spoon_bowl_radius_m, self.spoon_bowl_depth_m
        return float(3.141592653589793 * h * h * (3.0 * r - h) / 3.0 * 1e6)

    def detect_fill_ratio(self) -> float:
        """勺上检查可判"有食物"所需的最小装勺率。

        由 ``min_food_ratio / full_spoon_mask_ratio`` 推出：掩码占比随装勺率
        线性增长，满勺时取 ``full_spoon_mask_ratio``。
        """
        return float(min(1.0, self.min_food_ratio / self.full_spoon_mask_ratio))


@dataclass(frozen=True)
class GridSpec:
    """五维扫参网格（每维 ≤3 个取值）。"""

    values: dict[str, tuple]

    def size(self) -> int:
        n = 1
        for dim in GRID_DIMS:
            n *= len(self.values[dim])
        return int(n)

    def as_dict(self) -> dict[str, list]:
        return {dim: list(self.values[dim]) for dim in GRID_DIMS}


@dataclass(frozen=True)
class FoodCard:
    """逐食物捕获模型卡（工程先验；未实测——见 provenance 字段）。"""

    name: str
    display_name: str
    rheology: str
    hsv_detectable: bool
    hsv_note: str
    fill_factor: float
    push_speed_mps: float
    retention_speed_mps: float
    tilt_knee_deg: float
    tilt_fail_deg: float
    scrape_extra_ml: float
    surface_jitter_m: float
    entry_lateral_error_m: float
    bowl_place_error_m: float
    closed_loop_gain: float
    provenance: str


@dataclass(frozen=True)
class ScoopConfig:
    """config/scoop_params.json 的装载结果。"""

    version: str
    food_set_source: str
    geometry: SpoonGeometry
    grid: GridSpec
    search: dict
    foods: dict[str, FoodCard]
    recommended: dict[str, dict]
    note: str

    def food_names(self) -> list[str]:
        return list(self.foods)


# ---- 装载 -----------------------------------------------------------------------

def _load_geometry(raw: dict) -> SpoonGeometry:
    where = "scoop_params.spoon_geometry"
    _check_keys(raw, _GEOM_KEYS, where)
    geom = SpoonGeometry(
        spoon_bowl_radius_m=_num(raw, "spoon_bowl_radius_m", where, lo=1e-3, hi=0.2),
        spoon_bowl_depth_m=_num(raw, "spoon_bowl_depth_m", where, lo=1e-4, hi=0.2),
        spoon_tip_drop_m=_num(raw, "spoon_tip_drop_m", where, lo=0.0, hi=0.5),
        bowl_interior_radius_m=_num(raw, "bowl_interior_radius_m", where, lo=1e-3, hi=0.2),
        bowl_rim_offset_m=_num(raw, "bowl_rim_offset_m", where, lo=0.0, hi=0.3),
        food_fill_depth_m=_num(raw, "food_fill_depth_m", where, lo=1e-3, hi=0.3),
        min_food_ratio=_num(raw, "min_food_ratio", where, lo=1e-3, hi=1.0),
        full_spoon_mask_ratio=_num(raw, "full_spoon_mask_ratio", where, lo=1e-3, hi=1.0),
    )
    if geom.spoon_bowl_depth_m >= geom.spoon_bowl_radius_m:
        raise ValueError(f"{where}.spoon_bowl_depth_m 必须 < spoon_bowl_radius_m")
    if geom.food_fill_depth_m > geom.bowl_rim_offset_m:
        raise ValueError(f"{where}.food_fill_depth_m 不得大于 bowl_rim_offset_m（溢出碗口）")
    if geom.spoon_bowl_radius_m >= geom.bowl_interior_radius_m:
        raise ValueError(f"{where}.spoon_bowl_radius_m 不得 ≥ bowl_interior_radius_m")
    return geom


def _load_grid(raw: dict) -> GridSpec:
    where = "scoop_params.grid"
    _check_keys(raw, set(GRID_DIMS), where)
    values: dict[str, tuple] = {}
    for dim in GRID_DIMS:
        seq = raw[dim]
        if not isinstance(seq, list) or not seq:
            raise ValueError(f"{where}.{dim} 必须是非空数组")
        if len(seq) > MAX_GRID_VALUES_PER_DIM:
            raise ValueError(
                f"{where}.{dim} 取值数 {len(seq)} 超过上限 {MAX_GRID_VALUES_PER_DIM}")
        if dim == "bowl_rim_scrape":
            vals = []
            for v in seq:
                if not isinstance(v, bool):
                    raise ValueError(f"{where}.{dim} 只能取布尔值（得到 {v!r}）")
                vals.append(v)
            if len(set(vals)) != len(vals):
                raise ValueError(f"{where}.{dim} 取值不得重复")
        else:
            lo, hi = {"dip_offset_m": (-0.05, 0.2), "tilt_deg": (0.0, 60.0),
                      "approach_speed_mps": (1e-3, 0.15),
                      "retract_speed_mps": (1e-3, 0.15)}[dim]
            vals = []
            for v in seq:
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    raise ValueError(f"{where}.{dim} 必须是数值（得到 {v!r}）")
                f = float(v)
                if not (lo <= f <= hi):
                    raise ValueError(f"{where}.{dim}={f} 超出允许区间 [{lo},{hi}]")
                vals.append(f)
            if len(set(vals)) != len(vals):
                raise ValueError(f"{where}.{dim} 取值不得重复")
        values[dim] = tuple(vals)
    if True not in values["bowl_rim_scrape"] and False not in values["bowl_rim_scrape"]:
        raise ValueError(f"{where}.bowl_rim_scrape 必须同时覆盖开与关")
    return GridSpec(values=values)


def _load_search(raw: dict) -> dict:
    where = "scoop_params.search"
    _check_keys(raw, _SEARCH_KEYS, where)
    return {
        "trials_per_food": _int(raw, "trials_per_food", where, lo=1,
                                 hi=MAX_TRIALS_PER_FOOD),
        "max_attempts": _int(raw, "max_attempts", where, lo=1, hi=8),
        "seed": _int(raw, "seed", where, lo=0),
        "entry_lateral_correction_m": _num(raw, "entry_lateral_correction_m", where,
                                           lo=0.0, hi=0.05),
    }


def _load_foods(raw: dict, geom: SpoonGeometry) -> dict[str, FoodCard]:
    if not isinstance(raw, dict) or not raw:
        raise ValueError("scoop_params.foods 必须是非空对象")
    out: dict[str, FoodCard] = {}
    for name, item in raw.items():
        where = f"scoop_params.foods[{name}]"
        if not isinstance(item, dict):
            raise ValueError(f"{where} 必须是对象")
        _check_keys(item, _FOOD_KEYS, where)
        rheology = _text(item, "rheology", where)
        if rheology not in _RHEOLOGIES:
            raise ValueError(f"{where}.rheology={rheology!r} 不在 {sorted(_RHEOLOGIES)} 内")
        card = FoodCard(
            name=name,
            display_name=_text(item, "display_name", where),
            rheology=rheology,
            hsv_detectable=_flag(item, "hsv_detectable", where),
            hsv_note=_text(item, "hsv_note", where),
            fill_factor=_num(item, "fill_factor", where, lo=0.0, hi=1.0),
            push_speed_mps=_num(item, "push_speed_mps", where, lo=1e-3, hi=1.0),
            retention_speed_mps=_num(item, "retention_speed_mps", where, lo=1e-3, hi=1.0),
            tilt_knee_deg=_num(item, "tilt_knee_deg", where, lo=0.0, hi=90.0),
            tilt_fail_deg=_num(item, "tilt_fail_deg", where, lo=0.0, hi=180.0),
            scrape_extra_ml=_num(item, "scrape_extra_ml", where, lo=0.0, hi=50.0),
            surface_jitter_m=_num(item, "surface_jitter_m", where, lo=0.0, hi=0.05),
            entry_lateral_error_m=_num(item, "entry_lateral_error_m", where,
                                       lo=0.0, hi=0.1),
            bowl_place_error_m=_num(item, "bowl_place_error_m", where, lo=0.0, hi=0.1),
            closed_loop_gain=_num(item, "closed_loop_gain", where, lo=0.0, hi=1.0),
            provenance=_text(item, "provenance", where),
        )
        if card.tilt_fail_deg < card.tilt_knee_deg:
            raise ValueError(f"{where}.tilt_fail_deg 不得小于 tilt_knee_deg")
        if card.scrape_extra_ml > geom.spoon_capacity_ml():
            raise ValueError(
                f"{where}.scrape_extra_ml={card.scrape_extra_ml} 超过勺碗容积 "
                f"{geom.spoon_capacity_ml():.2f} ml")
        out[name] = card
    return out


def _load_recommended(raw: dict, foods: dict[str, FoodCard], geom: SpoonGeometry,
                      grid: GridSpec) -> dict[str, dict]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("scoop_params.recommended 必须是对象")
    out: dict[str, dict] = {}
    for name, item in raw.items():
        where = f"scoop_params.recommended[{name}]"
        if name not in foods:
            raise ValueError(f"{where} 不在 foods 声明的食物集合内")
        if not isinstance(item, dict):
            raise ValueError(f"{where} 必须是对象")
        _check_keys(item, _RECOMMENDED_KEYS, where)
        rec: dict = {"bowl_rim_scrape": _flag(item, "bowl_rim_scrape", where)}
        for dim, lo, hi in (("dip_offset_m", -0.05, 0.2), ("tilt_deg", 0.0, 60.0),
                            ("approach_speed_mps", 1e-3, 0.15),
                            ("retract_speed_mps", 1e-3, 0.15)):
            rec[dim] = _num(item, dim, where, lo=lo, hi=hi)
        for key, lo, hi in (("sim_first_attempt_rate", 0.0, 1.0),
                            ("sim_final_success_rate", 0.0, 1.0)):
            rec[key] = _num(item, key, where, lo=lo, hi=hi)
        rec["sim_trials"] = _int(item, "sim_trials", where, lo=1,
                                 hi=MAX_TRIALS_PER_FOOD)
        rec["sim_attempts_per_trial"] = _int(item, "sim_attempts_per_trial", where,
                                             lo=1, hi=8)
        rec["source_report"] = _text(item, "source_report", where)
        rec["feasible_combos"] = _int(item, "feasible_combos", where, lo=0)
        rec["grid_size"] = _int(item, "grid_size", where, lo=1)
        if rec["grid_size"] != grid.size():
            raise ValueError(f"{where}.grid_size={rec['grid_size']} 与网格规模 "
                             f"{grid.size()} 不一致（网格改动后需重跑扫参）")
        out[name] = rec
    missing = sorted(set(foods) - set(out))
    if missing:
        raise ValueError(f"scoop_params.recommended 缺少食物: {missing}")
    return out


def load_scoop_config(path: str | Path | None = None, *,
                      allowed_foods: tuple[str, ...] | None = None) -> ScoopConfig:
    """装载 config/scoop_params.json。

    ``allowed_foods`` 传入时（调用方通常传
    ``cs_schema.constants.DEFAULT_DISH_REGISTRY``）额外校验食物集合与其一致：
    集合不一致 => ValueError（食物集合以仓库既有定义为准，本文件不得私设）。
    """
    file_path = Path(path) if path is not None else DEFAULT_SCOOP_CONFIG_PATH
    data = _read_json(file_path)
    # recommended 段由 scoop_sweep --write-config 产出，首扫前允许缺席
    _check_keys(data, _TOP_KEYS, "scoop_params", optional={"recommended"})

    geom = _load_geometry(data["spoon_geometry"])
    grid = _load_grid(data["grid"])
    search = _load_search(data["search"])
    foods = _load_foods(data["foods"], geom)
    if allowed_foods is not None:
        want = list(dict.fromkeys(allowed_foods))
        got = list(foods)
        if sorted(want) != sorted(got):
            raise ValueError(
                f"scoop_params.foods 集合 {got} 与食物集合权威来源 {FOOD_SET_SOURCE} "
                f"{want} 不一致")
    recommended = _load_recommended(data.get("recommended"), foods, geom, grid)

    return ScoopConfig(
        version=_text(data, "version", "scoop_params"),
        food_set_source=_text(data, "food_set_source", "scoop_params"),
        geometry=geom,
        grid=grid,
        search=search,
        foods=foods,
        recommended=recommended,
        note=_text(data, "_note", "scoop_params"),
    )
