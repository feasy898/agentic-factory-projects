"""DB46/T 642—2024 法定数值表加载与法定理化等级判定（轨3 · DB46 口径）。

数据源 ``configs/standards/db46_t642.yaml`` 的 **legal 节**——从标准印刷稿
PDF 抄录固化的法定数值（文本层抽取 + 表格页位图人工双重复核；每值带条款
号，见该文件头与 legal 节注释）。法定数值与引擎阈值同文件存放（单一来源）：
引擎消费顶层 grades（defect_pct_max 等三轴），本模块消费 legal 节。

本模块做两件事：
- :func:`load_db46_legal`：加载并校验法定表（杯品/理化双维度 + 全局理化
  限值 + 筛差容差 + 检验方法），供精品/普通判定层与测试消费；
- :func:`db46_legal_grade`：在同一输入（主/次缺陷计数 + 筛目直方 + 水分
  占位）上给出 **DB46 法定理化等级**（4.3 表 2 口径），实现"DB46 口径
  同时给出其法定等级"。

**粒数→质量百分比近似（重要口径）**：DB46 的「缺陷豆，%」是质量百分比
（检验方法 5.3 按 GB/T 15033）；本仓 v0 只有盘面**粒数**。v0 以粒数占比
近似质量百分比（``pct ≈ 缺陷粒数/总粒数×100``，同密度假设），并在判定
理由中显式标注该近似（``db46.reason.count_to_mass_approx``）；到货称重
标定后可换质量口径重算。粒度判定按 6.5.4 的 5% 降档容差如实实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

__all__ = [
    "DEFAULT_DB46_LEGAL_PATH",
    "DB46LegalError",
    "DB46PhysGrade",
    "DB46Legal",
    "load_db46_legal",
    "db46_legal_grade",
]

DEFAULT_DB46_LEGAL_PATH = Path(__file__).resolve().parents[2] / "configs" / "standards" / "db46_t642.yaml"


class DB46LegalError(ValueError):
    """DB46 法定表缺失 / 非法 / 自相矛盾时抛出。"""


@dataclass(frozen=True)
class DB46PhysGrade:
    """单个理化等级（4.3 表 2 一行；min/max 为该级区间界）。"""

    name: str  # 一级 / 二级 / 三级
    defect_pct_max: float  # 缺陷豆 % 上限
    foreign_matter_pct_max: float  # 外来杂质 % 上限
    sieve_min: int  # 粒度（筛号）下限（本级主档）
    no_serious_defect: bool  # 该级是否要求无严重缺陷（表 2 表尾：一级应无严重缺陷）
    defect_pct_min: float | None = None  # 区间下界（仅 informational；判定用上限）
    foreign_matter_pct_min: float | None = None
    sieve_max: int | None = None  # 主档上界（如二级 14～15 的 15）


@dataclass(frozen=True)
class DB46Legal:
    """一份已校验的 DB46 法定数值表（抄录固化数据的内存视图）。"""

    standard: str
    phys_grades: tuple[DB46PhysGrade, ...]  # 从最优到最差
    moisture_pct_max: float  # 表 2 全局：水分 ≤12.0
    ash_pct_max: float  # 表 2 全局：灰分 ≤5.5
    caffeine_pct_min: float  # 表 2 续：咖啡因 ≥1.5
    sieve_tolerance_frac: float  # 6.5.4 粒度降档容差（0.05）
    sensory_sample_g: int  # 5.1 感官取样 300 g
    source_path: Path | None = None


def _num(v: object, where: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise DB46LegalError(f"{where} 必须是数值，得到 {v!r}")
    return float(v)


def _int(v: object, where: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise DB46LegalError(f"{where} 必须是整数，得到 {v!r}")
    return int(v)


def load_db46_legal(path: str | Path | None = None) -> DB46Legal:
    """加载并校验 DB46 法定表（缺省读 ``configs/standards/db46_t642.yaml`` 的 legal 节）。"""
    p = Path(path) if path is not None else DEFAULT_DB46_LEGAL_PATH
    if not p.is_file():
        raise DB46LegalError(f"DB46 法定表文件不存在: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise DB46LegalError(f"DB46 法定表 YAML 解析失败: {p}\n{e}") from e
    if not isinstance(raw, dict):
        raise DB46LegalError(f"DB46 法定表顶层必须是映射: {p}")
    section = raw.get("legal")
    if not isinstance(section, dict):
        raise DB46LegalError(f"`legal` 节缺失或不是映射（source={p}）——法定数值与引擎阈值同文件存放")
    raw = section

    grades_raw = raw.get("phys_grades")
    if not isinstance(grades_raw, list) or not grades_raw:
        raise DB46LegalError(f"`phys_grades` 必须是非空列表（source={p}）")
    grades: list[DB46PhysGrade] = []
    prev_max: float | None = None
    prev_sieve: int | None = None
    for i, g in enumerate(grades_raw):
        if not isinstance(g, dict):
            raise DB46LegalError(f"phys_grades[{i}] 必须是映射（source={p}）")
        for k in ("name", "defect_pct_max", "foreign_matter_pct_max", "sieve_min"):
            if k not in g:
                raise DB46LegalError(f"phys_grades[{i}] 缺少键 {k!r}（source={p}）")
        name = g["name"]
        if not isinstance(name, str) or not name.strip():
            raise DB46LegalError(f"phys_grades[{i}].name 必须是非空字符串（source={p}）")
        d_max = _num(g["defect_pct_max"], f"phys_grades[{i}].defect_pct_max (source={p})")
        f_max = _num(g["foreign_matter_pct_max"], f"phys_grades[{i}].foreign_matter_pct_max (source={p})")
        s_min = _int(g["sieve_min"], f"phys_grades[{i}].sieve_min (source={p})")
        # 单调放宽校验（与 loader.py grades 同纪律：从最优到最差）
        if prev_max is not None and d_max < prev_max:
            raise DB46LegalError(
                f"phys_grades[{i}].defect_pct_max({d_max}) 不得小于上一级({prev_max})——必须单调放宽（source={p}）"
            )
        if prev_sieve is not None and s_min > prev_sieve:
            raise DB46LegalError(
                f"phys_grades[{i}].sieve_min({s_min}) 不得高于上一级({prev_sieve})——必须单调放宽（source={p}）"
            )
        prev_max, prev_sieve = d_max, s_min
        grades.append(
            DB46PhysGrade(
                name=name,
                defect_pct_max=d_max,
                foreign_matter_pct_max=f_max,
                sieve_min=s_min,
                no_serious_defect=bool(g.get("no_serious_defect", False)),
                defect_pct_min=None if g.get("defect_pct_min") is None else _num(g["defect_pct_min"], f"phys_grades[{i}].defect_pct_min"),
                foreign_matter_pct_min=None if g.get("foreign_matter_pct_min") is None else _num(g["foreign_matter_pct_min"], f"phys_grades[{i}].foreign_matter_pct_min"),
                sieve_max=None if g.get("sieve_max") is None else _int(g["sieve_max"], f"phys_grades[{i}].sieve_max"),
            )
        )

    glob = raw.get("phys_global")
    if not isinstance(glob, dict):
        raise DB46LegalError(f"`phys_global` 必须是映射（source={p}）")
    tol = raw.get("sieve_tolerance") or {}
    if not isinstance(tol, dict) or "frac_allowed_off_grade" not in tol:
        raise DB46LegalError(f"`sieve_tolerance.frac_allowed_off_grade` 缺失（source={p}）")
    methods = raw.get("methods") or {}
    if not isinstance(methods, dict) or "sensory_sample_g" not in methods:
        raise DB46LegalError(f"`methods.sensory_sample_g` 缺失（source={p}）")

    return DB46Legal(
        standard=str(raw.get("standard", "DB46/T 642—2024")),
        phys_grades=tuple(grades),
        moisture_pct_max=_num(glob["moisture_pct_max"], "phys_global.moisture_pct_max"),
        ash_pct_max=_num(glob["ash_pct_max"], "phys_global.ash_pct_max"),
        caffeine_pct_min=_num(glob["caffeine_pct_min"], "phys_global.caffeine_pct_min"),
        sieve_tolerance_frac=_num(tol["frac_allowed_off_grade"], "sieve_tolerance.frac_allowed_off_grade"),
        sensory_sample_g=_int(methods["sensory_sample_g"], "methods.sensory_sample_g"),
        source_path=p,
    )


def _below_frac(sieve_hist: dict[str, int], total: int, sieve_min: int) -> tuple[int, float]:
    """筛目 < sieve_min 的粒数与占比（键须为目数整数字符串）。"""
    below = 0
    for key, n in sieve_hist.items():
        try:
            screen = int(key)
        except (TypeError, ValueError):
            raise DB46LegalError(f"sieve_hist 键 {key!r} 不是目数整数字符串") from None
        if screen < sieve_min:
            below += int(n)
    frac = (below / total) if total else 0.0
    return below, frac


def db46_legal_grade(
    primary_count: int,
    secondary_count: int,
    bean_count: int,
    sieve_hist: dict[str, int],
    legal: DB46Legal | None = None,
    *,
    moisture_pct: float | None = None,
    foreign_matter_pct: float | None = None,
) -> tuple[str | None, list[str]]:
    """按 DB46/T 642—2024 表 2 口径判**法定理化等级**。

    入参为主/次缺陷粒数与整盘筛目直方（引擎/计量同源口径）；返回
    ``(等级名或 None, 理由列表)``——等级名带「理化」前缀（如 ``理化一级``）
    以区分杯品维度与贸易档位；None 仅在致命输入（空盘）时出现。
    判定规则（全部实现自法定条款，出处见 configs/db46_t642_legal_2024.yaml）：
    1. 缺陷豆 % ≈ (主+次)粒数/总粒数×100（v0 粒数近似质量%，理由显式标注）；
    2. 一级附加「无严重缺陷」（表 2 表尾行：primary==0）；
    3. 粒度按 6.5.4 容差：本级允许 ≤5% 不符但须符合下一级主档下限；
    4. 水分（表 2 全局 ≤12.0）仅在提供 ``moisture_pct`` 时参与，未提供记
       占位理由（v0 管线无水分计）；
    5. 取**满足全部条件的最高等级**；全部未达 → ``理化等外``。
    外来杂质（表 2）v0 无计量来源，仅在接受 ``foreign_matter_pct`` 时核。
    """
    leg = legal if legal is not None else load_db46_legal()
    reasons: list[str] = []

    if bean_count <= 0:
        reasons.append("db46.reason.empty_tray")
        return None, reasons

    defect_pct = (primary_count + secondary_count) / bean_count * 100.0
    reasons.append(
        f"db46.reason.count_to_mass_approx:defect_pct={defect_pct:.2f}"
        f";primary={primary_count};secondary={secondary_count};bean_count={bean_count}"
    )

    # 水分（表 2 全局）：提供才核；未提供 → 占位理由（不阻断）
    if moisture_pct is not None and moisture_pct > leg.moisture_pct_max:
        reasons.append(
            f"db46.reason.moisture_over:moisture={moisture_pct:g};limit={leg.moisture_pct_max:g}"
        )
        return "理化等外", reasons
    if moisture_pct is None:
        reasons.append("db46.reason.moisture_placeholder:moisture=none")

    # 外来杂质（表 2）：v0 无计量来源，仅在接受值时核
    if foreign_matter_pct is not None:
        worst = leg.phys_grades[-1]
        if foreign_matter_pct > worst.foreign_matter_pct_max:
            reasons.append(
                f"db46.reason.foreign_matter_over:fm={foreign_matter_pct:g};"
                f"limit={worst.foreign_matter_pct_max:g}"
            )
            return "理化等外", reasons

    tol = leg.sieve_tolerance_frac
    for gi, g in enumerate(leg.phys_grades):  # 从最优到最差，取第一个满足者
        if defect_pct > g.defect_pct_max:
            continue  # 理由在落选时统一相对最终选定级输出，避免噪声
        if g.no_serious_defect and primary_count > 0:
            continue
        # 粒度（6.5.4 容差）：本级允许 ≤tol 不符本级下限，但不符者须符合下一级
        # 主档下限；最差级无下一级 → 不符者只需符合基本要求（基本要求无粒度）。
        below_min, below_min_frac = _below_frac(sieve_hist, bean_count, g.sieve_min)
        if below_min_frac > tol + 1e-9:
            continue
        if gi + 1 < len(leg.phys_grades):
            next_sieve = leg.phys_grades[gi + 1].sieve_min
            below_next, _ = _below_frac(sieve_hist, bean_count, next_sieve)
            if below_next > 0:
                continue
        reasons.append(
            f"db46.reason.sieve_ok:sieve_min={g.sieve_min};below={below_min};"
            f"frac={below_min_frac:.4f};tolerance={tol:g}"
        )
        reasons.append(f"db46.reason.grade_selected:grade=理化{g.name}")
        return f"理化{g.name}", reasons

    # 全部未达：相对最严一级输出落选理由
    top = leg.phys_grades[0]
    below_top, below_top_frac = _below_frac(sieve_hist, bean_count, top.sieve_min)
    reasons.append(
        f"db46.reason.defect_over_or_sieve_fail:defect_pct={defect_pct:.2f};"
        f"limit={top.defect_pct_max:g};primary={primary_count};"
        f"sieve_min={top.sieve_min};below={below_top};frac={below_top_frac:.4f};tolerance={tol:g}"
    )
    reasons.append("db46.reason.grade_selected:grade=理化等外")
    return "理化等外", reasons
