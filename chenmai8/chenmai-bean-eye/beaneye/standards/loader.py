"""标准 YAML 加载与校验（M9 · beaneye/standards）。

职责（开发指令 §4 M9 spec）：
- ``load_standard(id)``：加载并校验 ``configs/standards/<id>.yaml``；
  ``verified:false`` 的字段收集为 warnings（最终经 GradingDecision.warnings
  传递给 M10 护照页脚"标准阈值核对中"角标）；
- 未知 standard_id 或 YAML 非法 → :class:`StandardsError`，**错误信息含
  文件路径与行号**（解析错误由 PyYAML mark 携带；语义错误由本模块
  逐键记录行号后以 ``路径:行号: 问题`` 格式报告）；
- ``list_standards()``：枚举可用标准 id。

YAML → 数据视图：映射一律解析为 :class:`LMap`（dict 子类 + 逐键行号），
重复键直接报错（PyYAML 默认静默后者覆盖前者，对标准配置是隐患）。

校验规则要点：
- 顶层键固定（standard/display/sample_g/count_rule/severity_order/
  defect_classes/grades/metrology/weight，可选 fail_grade/notes），
  未知键=拼写隐患 → 报错；
- ``standard`` 必须与文件名 stem 一致（按 id 加载时天然成立）；
- ``severity_order`` 必须是 taxonomy 全排列且 [0]=normal（复用
  beaneye.severity.SeverityOrder 校验，与 M7 同一套规则）；
- ``defect_classes`` 类别集合必须与 taxonomy 一致，kind 必须一致
  （主/次归属唯一数据源是 configs/taxonomy.yaml）；
- ``grades`` 必须从最优到最差单调放宽（primary/secondary 上限非递减、
  sieve_min 非递增且 null 只能出现在尾部）；
- ``count_rule`` 接受 most_severe_per_bean / per_side 声明；但 v1 引擎
  只实现 most_severe_per_bean（per_side 与契约 BatchResult.defect_counts
  不变式冲突，evaluate 时明确报错）。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Hashable

import yaml

from beaneye.severity import SeverityError, SeverityOrder
from beaneye.taxonomy import VALID_KINDS, Taxonomy, load_taxonomy

__all__ = [
    "DEFAULT_STANDARDS_DIR",
    "StandardsError",
    "LMap",
    "ClassInfo",
    "GradeRule",
    "MetrologyCfg",
    "WeightCfg",
    "Standard",
    "load_standard",
    "list_standards",
]

# configs/standards 目录（beaneye/standards/loader.py → 仓库根/configs/standards）
DEFAULT_STANDARDS_DIR = Path(__file__).resolve().parents[2] / "configs" / "standards"

VALID_COUNT_RULES = ("most_severe_per_bean", "per_side")


class StandardsError(ValueError):
    """标准 id 未知 / YAML 非法 / 配置自相矛盾时抛出（信息含路径与行号）。"""


# ---------------------------------------------------------------------------
# 带行号的 YAML 映射
# ---------------------------------------------------------------------------


class LMap(dict):
    """带逐键行号的 YAML 映射（行号 1-based）。

    ``line_of[key]`` 记录键所在行；访问不存在的键行号时回退 ``start_line``
    （映射首行）。语义校验报错时用它拼 ``路径:行号: 问题``。
    """

    def __init__(self, data=(), *, line_of: dict[str, int] | None = None, start_line: int = 0):
        super().__init__(data)
        self.line_of: dict[str, int] = dict(line_of or {})
        self.start_line = int(start_line)

    def line(self, key: str) -> int:
        """键所在行号；键不存在时回退映射首行。"""
        return self.line_of.get(key, self.start_line)


class _LineLoader(yaml.SafeLoader):
    """SafeLoader + 重复键报错 + 逐键行号记录。

    注意：顶层映射走 ``construct_yaml_map``（注册表中存的是函数对象，
    子类必须重新 add_constructor 才能生效），嵌套映射走 ``construct_mapping``。
    """

    def construct_yaml_map(self, node):  # noqa: N802 (PyYAML 命名)
        data = LMap()
        yield data
        value = self.construct_mapping(node)
        data.update(value)
        if isinstance(value, LMap):
            data.line_of = dict(value.line_of)
            data.start_line = value.start_line
        return data

    def construct_mapping(self, node, deep: bool = False):  # noqa: N802 (PyYAML 命名)
        seen: set[Hashable] = set()
        for key_node, _value_node in node.value:
            key = self.construct_object(key_node, deep=True)
            if not isinstance(key, Hashable):
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found unhashable key",
                    key_node.start_mark,
                )
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"重复键: {key!r}",
                    key_node.start_mark,
                )
            seen.add(key)
        raw = yaml.SafeLoader.construct_mapping(self, node, deep=True)
        lm = LMap(raw, start_line=node.start_mark.line + 1)
        for key_node, _value_node in node.value:
            key = self.construct_object(key_node, deep=True)
            if isinstance(key, str):
                lm.line_of[key] = key_node.start_mark.line + 1
        return lm


# 覆盖 tag:map 的构造函数（否则顶层映射仍由 SafeConstructor.construct_yaml_map
# 构造为普通 dict，丢失行号）
_LineLoader.add_constructor("tag:yaml.org,2002:map", _LineLoader.construct_yaml_map)


def _err(path: Path | None, line: int, msg: str) -> StandardsError:
    where = f"{path}:{line}: " if path is not None else f"line {line}: "
    return StandardsError(f"{where}{msg}")


# ---------------------------------------------------------------------------
# 数据视图
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClassInfo:
    """标准 YAML defect_classes 单类别（展示副本；主/次归属以 taxonomy 为准）。"""

    key: str
    kind: str
    zh: str
    en: str
    vi: str


@dataclass(frozen=True)
class GradeRule:
    """单个级别阈值（grades 从最优到最差排列，index 即位次）。"""

    index: int
    name: str
    primary_max: int
    secondary_full_max: int
    sieve_min: int | None  # null = 不设筛目条件
    verified: bool


@dataclass(frozen=True)
class MetrologyCfg:
    """计量对照基准（M8 sieve_pass/ΔE 与 M9 色差条件共用）。"""

    min_screen: int
    reference_lab: tuple[float, float, float]
    reference_lab_verified: bool
    delta_e_max: float | None  # None = 不判色差


@dataclass(frozen=True)
class WeightCfg:
    """估重系数（M8 估重用）。"""

    model: str
    g_per_mm2: float
    verified: bool


@dataclass(frozen=True)
class Standard:
    """一份已加载并校验的标准配置（不可变视图）。"""

    standard_id: str
    path: Path | None
    sha256: str  # 文件字节 sha256（小写 hex64）→ GradingDecision.standard_yaml_sha
    display: dict[str, str]
    sample_g: float
    count_rule: str
    severity_order: SeverityOrder
    defect_classes: dict[str, ClassInfo]
    grades: tuple[GradeRule, ...]
    fail_grade: str
    metrology: MetrologyCfg
    weight: WeightCfg
    notes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = field(default=())  # verified:false 收集

    def grade_names(self) -> list[str]:
        return [g.name for g in self.grades]


# ---------------------------------------------------------------------------
# 校验工具
# ---------------------------------------------------------------------------


def _is_num(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _require_keys(path: Path, m: LMap, required: tuple[str, ...], where: str) -> None:
    missing = [k for k in required if k not in m]
    if missing:
        raise _err(path, m.start_line, f"{where} 缺少必需键: {missing}（现有键 {sorted(m.keys())}）")


def _reject_unknown_keys(path: Path, m: LMap, allowed: tuple[str, ...], where: str) -> None:
    extra = [k for k in m if k not in allowed]
    if extra:
        raise _err(path, m.line(extra[0]), f"{where} 存在未知键: {extra}（允许 {list(allowed)}）")


def _want_str(path: Path, m: LMap, key: str, where: str) -> str:
    v = m[key]
    if not isinstance(v, str) or not v.strip():
        raise _err(path, m.line(key), f"{where}.{key} 必须是非空字符串，得到 {v!r}")
    return v


def _want_bool(path: Path, m: LMap, key: str, where: str, default: bool) -> bool:
    if key not in m:
        return default
    v = m[key]
    if not isinstance(v, bool):
        raise _err(path, m.line(key), f"{where}.{key} 必须是布尔值，得到 {v!r}")
    return v


TOP_REQUIRED = (
    "standard",
    "display",
    "sample_g",
    "count_rule",
    "severity_order",
    "defect_classes",
    "grades",
    "metrology",
    "weight",
)
TOP_OPTIONAL = ("fail_grade", "notes")

_GRADE_KEYS = ("name", "primary_max", "secondary_full_max", "sieve_min", "verified")
_CLASS_KEYS = ("kind", "zh", "en", "vi")


# ---------------------------------------------------------------------------
# 主加载流程
# ---------------------------------------------------------------------------


def list_standards() -> list[str]:
    """枚举 configs/standards/ 下可用标准 id（= 文件 stem，升序）。"""
    if not DEFAULT_STANDARDS_DIR.is_dir():
        return []
    return sorted(p.stem for p in DEFAULT_STANDARDS_DIR.glob("*.yaml"))


def _resolve_path(target: str | Path) -> Path:
    """id 或路径 → YAML 文件路径；id 未知时列出可用项。"""
    p = Path(target)
    looks_like_path = p.suffix in (".yaml", ".yml") or any(sep in str(target) for sep in ("/", "\\"))
    if not looks_like_path and not p.exists():
        p = DEFAULT_STANDARDS_DIR / f"{target}.yaml"
    if not p.is_file():
        raise StandardsError(
            f"未知标准 {target!r}：文件不存在 {p}"
            f"（可用标准: {list_standards()}；目录: {DEFAULT_STANDARDS_DIR}）"
        )
    return p


def _parse(path: Path) -> LMap:
    """读文件 → LMap；解析错误包装为 StandardsError（PyYAML mark 自带路径与行号）。"""
    try:
        with path.open("rb") as fh:  # 文件句柄流：mark 中携带文件名
            raw = yaml.load(fh, Loader=_LineLoader)
    except yaml.YAMLError as e:
        raise StandardsError(f"标准 YAML 解析失败: {path}\n{e}") from e
    if not isinstance(raw, LMap):
        raise _err(path, 1, f"顶层必须是映射，得到 {type(raw).__name__}")
    return raw


def load_standard(target: str | Path, *, taxonomy: Taxonomy | None = None) -> Standard:
    """加载并校验一份标准配置。

    ``target`` 可为标准 id（如 ``"cqi_fine_robusta"``，读
    ``configs/standards/<id>.yaml``）或 YAML 文件路径（文件名 stem 必须与
    内容 ``standard`` 一致）。非法即抛 :class:`StandardsError`（含路径行号）。
    """
    path = _resolve_path(target)
    tax = taxonomy if taxonomy is not None else load_taxonomy()
    raw = _parse(path)
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    # -- 顶层 --------------------------------------------------------------
    _reject_unknown_keys(path, raw, TOP_REQUIRED + TOP_OPTIONAL, "顶层")
    _require_keys(path, raw, TOP_REQUIRED, "顶层")

    std_id = _want_str(path, raw, "standard", "顶层")
    if std_id != path.stem:
        raise _err(path, raw.line("standard"), f"standard({std_id!r}) 与文件名 stem({path.stem!r}) 不一致")

    # -- display / sample_g / count_rule ------------------------------------
    disp = raw["display"]
    if not isinstance(disp, LMap):
        raise _err(path, raw.line("display"), "display 必须是映射")
    _reject_unknown_keys(path, disp, ("zh", "en", "vi"), "display")
    _require_keys(path, disp, ("zh", "en", "vi"), "display")
    display = {lang: _want_str(path, disp, lang, "display") for lang in ("zh", "en", "vi")}

    if not _is_num(raw["sample_g"]) or raw["sample_g"] <= 0:
        raise _err(path, raw.line("sample_g"), f"sample_g 必须是正数，得到 {raw['sample_g']!r}")
    sample_g = float(raw["sample_g"])

    count_rule = _want_str(path, raw, "count_rule", "顶层")
    if count_rule not in VALID_COUNT_RULES:
        raise _err(
            path,
            raw.line("count_rule"),
            f"count_rule 非法: {count_rule!r}（允许 {list(VALID_COUNT_RULES)}）",
        )

    # -- severity_order（复用 M7 校验，与 M7 同一套规则）---------------------
    order = raw["severity_order"]
    if not isinstance(order, list) or not order or not all(isinstance(k, str) for k in order):
        raise _err(path, raw.line("severity_order"), f"severity_order 必须是非空字符串列表，得到 {order!r}")
    try:
        sev = SeverityOrder(tuple(order), source=f"standard:{std_id}")
        sev.ensure_covers_taxonomy(tax)
    except SeverityError as e:
        raise _err(path, raw.line("severity_order"), f"severity_order 非法: {e}") from e

    # -- defect_classes（类别集合与 kind 必须与 taxonomy 一致）---------------
    classes_raw = raw["defect_classes"]
    if not isinstance(classes_raw, LMap) or not classes_raw:
        raise _err(path, raw.line("defect_classes"), "defect_classes 必须是非空映射")
    tax_keys = set(tax.keys())
    have_keys = set(classes_raw.keys())
    if have_keys != tax_keys:
        raise _err(
            path,
            classes_raw.start_line,
            f"defect_classes 与 taxonomy 类别不一致：缺失 {sorted(tax_keys - have_keys)}，"
            f"未知 {sorted(have_keys - tax_keys)}",
        )
    defect_classes: dict[str, ClassInfo] = {}
    for key in classes_raw:
        item = classes_raw[key]
        if not isinstance(item, LMap):
            raise _err(path, classes_raw.line(key), f"defect_classes.{key} 必须是映射")
        _reject_unknown_keys(path, item, _CLASS_KEYS, f"defect_classes.{key}")
        _require_keys(path, item, _CLASS_KEYS, f"defect_classes.{key}")
        kind = _want_str(path, item, "kind", f"defect_classes.{key}")
        if kind not in VALID_KINDS:
            raise _err(path, item.line("kind"), f"defect_classes.{key}.kind 非法: {kind!r}（允许 {list(VALID_KINDS)}）")
        if kind != tax.get(key).kind:
            raise _err(
                path,
                item.line("kind"),
                f"defect_classes.{key}.kind={kind!r} 与 taxonomy({tax.get(key).kind!r}) 不一致"
                "（主/次归属唯一数据源是 configs/taxonomy.yaml）",
            )
        defect_classes[key] = ClassInfo(
            key=key,
            kind=kind,
            zh=_want_str(path, item, "zh", f"defect_classes.{key}"),
            en=_want_str(path, item, "en", f"defect_classes.{key}"),
            vi=_want_str(path, item, "vi", f"defect_classes.{key}"),
        )

    # -- grades（单调放宽：从最优到最差）-------------------------------------
    grades_raw = raw["grades"]
    if not isinstance(grades_raw, list) or not grades_raw:
        raise _err(path, raw.line("grades"), "grades 必须是非空列表")
    grades: list[GradeRule] = []
    names: set[str] = set()
    for i, item in enumerate(grades_raw):
        where = f"grades[{i}]"
        if not isinstance(item, LMap):
            raise _err(path, raw.line("grades"), f"{where} 必须是映射")
        _reject_unknown_keys(path, item, _GRADE_KEYS, where)
        _require_keys(path, item, _GRADE_KEYS, where)
        name = _want_str(path, item, "name", where)
        if name in names:
            raise _err(path, item.line("name"), f"{where}.name 重复: {name!r}")
        names.add(name)
        for k in ("primary_max", "secondary_full_max"):
            if not _is_int(item[k]) or item[k] < 0:
                raise _err(path, item.line(k), f"{where}.{k} 必须是 >=0 的整数，得到 {item[k]!r}")
        sieve_min = item["sieve_min"]
        if sieve_min is not None and (not _is_int(sieve_min) or sieve_min < 1):
            raise _err(path, item.line("sieve_min"), f"{where}.sieve_min 必须是 >=1 的整数或 null，得到 {sieve_min!r}")
        if not isinstance(item["verified"], bool):
            raise _err(path, item.line("verified"), f"{where}.verified 必须是布尔值，得到 {item['verified']!r}")
        grades.append(
            GradeRule(
                index=i,
                name=name,
                primary_max=item["primary_max"],
                secondary_full_max=item["secondary_full_max"],
                sieve_min=sieve_min,
                verified=item["verified"],
            )
        )
        if i > 0:
            prev = grades[i - 1]
            if grades[i].primary_max < prev.primary_max:
                raise _err(path, item.line("primary_max"),
                           f"{where}.primary_max({grades[i].primary_max}) 不得小于上一级({prev.primary_max})——"
                           "grades 必须从最优到最差单调放宽")
            if grades[i].secondary_full_max < prev.secondary_full_max:
                raise _err(path, item.line("secondary_full_max"),
                           f"{where}.secondary_full_max({grades[i].secondary_full_max}) 不得小于上一级"
                           f"({prev.secondary_full_max})——grades 必须从最优到最差单调放宽")
            if prev.sieve_min is None and grades[i].sieve_min is not None:
                raise _err(path, item.line("sieve_min"),
                           f"{where}.sieve_min 在上一级为 null 后不得再设数值——sieve_min 必须非递增且 null 只能在尾部")
            if prev.sieve_min is not None and grades[i].sieve_min is not None and grades[i].sieve_min > prev.sieve_min:
                raise _err(path, item.line("sieve_min"),
                           f"{where}.sieve_min({grades[i].sieve_min}) 不得高于上一级({prev.sieve_min})")

    # -- fail_grade ----------------------------------------------------------
    fail_grade = "未达级"
    if "fail_grade" in raw:
        fail_grade = _want_str(path, raw, "fail_grade", "顶层")
        if fail_grade in names:
            raise _err(path, raw.line("fail_grade"), f"fail_grade({fail_grade!r}) 不得与任何 grade 重名")

    # -- notes ---------------------------------------------------------------
    notes: tuple[str, ...] = ()
    if "notes" in raw:
        if not isinstance(raw["notes"], list) or not all(isinstance(s, str) for s in raw["notes"]):
            raise _err(path, raw.line("notes"), "notes 必须是字符串列表")
        notes = tuple(raw["notes"])

    # -- metrology -----------------------------------------------------------
    met = raw["metrology"]
    if not isinstance(met, LMap):
        raise _err(path, raw.line("metrology"), "metrology 必须是映射")
    _reject_unknown_keys(
        path, met, ("sieve_targets", "reference_lab", "reference_lab_verified", "delta_e_max"), "metrology"
    )
    _require_keys(path, met, ("sieve_targets", "reference_lab", "delta_e_max"), "metrology")

    st = met["sieve_targets"]
    if not isinstance(st, LMap):
        raise _err(path, met.line("sieve_targets"), "metrology.sieve_targets 必须是映射")
    _reject_unknown_keys(path, st, ("min_screen", "verified"), "metrology.sieve_targets")
    _require_keys(path, st, ("min_screen",), "metrology.sieve_targets")
    if not _is_int(st["min_screen"]) or st["min_screen"] < 1:
        raise _err(path, st.line("min_screen"), f"metrology.sieve_targets.min_screen 必须 >=1，得到 {st['min_screen']!r}")
    sieve_verified = _want_bool(path, st, "verified", "metrology.sieve_targets", default=False)

    lab = met["reference_lab"]
    if not isinstance(lab, list) or len(lab) != 3 or not all(_is_num(v) for v in lab):
        raise _err(path, met.line("reference_lab"), f"metrology.reference_lab 必须是 3 个数字，得到 {lab!r}")
    lab_verified = _want_bool(path, met, "reference_lab_verified", "metrology", default=False)

    de_max = met["delta_e_max"]
    if de_max is not None and (not _is_num(de_max) or de_max < 0):
        raise _err(path, met.line("delta_e_max"), f"metrology.delta_e_max 必须是 >=0 的数字或 null，得到 {de_max!r}")

    metrology = MetrologyCfg(
        min_screen=st["min_screen"],
        reference_lab=(float(lab[0]), float(lab[1]), float(lab[2])),
        reference_lab_verified=lab_verified,
        delta_e_max=None if de_max is None else float(de_max),
    )

    # -- weight ---------------------------------------------------------------
    w = raw["weight"]
    if not isinstance(w, LMap):
        raise _err(path, raw.line("weight"), "weight 必须是映射")
    _reject_unknown_keys(path, w, ("model", "g_per_mm2", "verified"), "weight")
    _require_keys(path, w, ("model", "g_per_mm2"), "weight")
    model = _want_str(path, w, "model", "weight")
    if not _is_num(w["g_per_mm2"]) or w["g_per_mm2"] <= 0:
        raise _err(path, w.line("g_per_mm2"), f"weight.g_per_mm2 必须是正数，得到 {w['g_per_mm2']!r}")
    weight = WeightCfg(
        model=model,
        g_per_mm2=float(w["g_per_mm2"]),
        verified=_want_bool(path, w, "verified", "weight", default=False),
    )

    # -- verified:false 收集为 warnings（稳定键路径，供 M10 页脚角标）---------
    warnings: list[str] = []
    for g in grades:
        if not g.verified:
            warnings.append(f"verified:false @ grades[{g.index}](name={g.name})")
    if not sieve_verified:
        warnings.append("verified:false @ metrology.sieve_targets(min_screen)")
    if not metrology.reference_lab_verified:
        warnings.append("verified:false @ metrology.reference_lab")
    if not weight.verified:
        warnings.append("verified:false @ weight")

    return Standard(
        standard_id=std_id,
        path=path,
        sha256=sha256,
        display=display,
        sample_g=sample_g,
        count_rule=count_rule,
        severity_order=sev,
        defect_classes=defect_classes,
        grades=tuple(grades),
        fail_grade=fail_grade,
        metrology=metrology,
        weight=weight,
        notes=notes,
        warnings=tuple(warnings),
    )
