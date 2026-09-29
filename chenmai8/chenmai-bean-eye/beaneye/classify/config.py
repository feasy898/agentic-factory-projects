"""M5 分类 · 规则表配置（configs/rules_v0.yaml 的加载与校验）。

``configs/rules_v0.yaml`` 是 RulesV0 的**规则表数据**（阈值即数据，代码
不含任何类别阈值——D7 用本地豆照片回填时只改 YAML）。schema 见该文件头
注释；:func:`load_rules_config` 严格校验（未知键/未知特征/未知类别/坏区间
一律拒绝，错误信息带文件路径与键路径），与 beaneye.segment.config /
beaneye.synth.config 同约定。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, fields as dc_fields
from pathlib import Path

import yaml

from beaneye.classify.features import ColorRefs, FeatureParams, FEATURE_NAMES
from beaneye.taxonomy import Taxonomy, load_taxonomy

__all__ = [
    "DEFAULT_RULES_CONFIG_PATH",
    "RULES_OPS",
    "RuleCondition",
    "RuleDef",
    "RulesV0Config",
    "RulesConfigError",
    "load_rules_config",
]

DEFAULT_RULES_CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "rules_v0.yaml"

RULES_OPS = {"lt", "le", "gt", "ge"}


class RulesConfigError(ValueError):
    """规则表缺失 / YAML 非法 / 未知特征或类别 / 数值越界。"""


@dataclass(frozen=True)
class RuleCondition:
    """单条判定条件：``feat op value``（如 lab_l_mean lt 92.0）。"""

    feat: str
    op: str
    value: float


@dataclass(frozen=True)
class RuleDef:
    """一条规则：全部 when 条件 AND 命中 → 判为 defect，置信度 conf。"""

    defect: str
    conf: float
    when: tuple[RuleCondition, ...]


@dataclass(frozen=True)
class RulesV0Config:
    """RulesV0 规则表（不可变；加载期校验完毕）。"""

    version: int
    rules: tuple[RuleDef, ...]
    normal_conf: float
    feature_params: FeatureParams = field(default_factory=FeatureParams)
    color_refs: ColorRefs = field(default_factory=ColorRefs)


def _num(v: object, where: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise RulesConfigError(f"{where}: 必须是数值，得到 {v!r}")
    out = float(v)
    if not math.isfinite(out):
        raise RulesConfigError(f"{where}: 必须是有限数值，得到 {v!r}")
    return out


def load_rules_config(
    path: str | Path | None = None,
    taxonomy: Taxonomy | None = None,
) -> RulesV0Config:
    """加载并校验规则表；``path=None`` 用仓库默认 ``configs/rules_v0.yaml``。"""
    p = Path(path) if path is not None else DEFAULT_RULES_CONFIG_PATH
    if not p.is_file():
        raise RulesConfigError(f"规则表文件不存在: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RulesConfigError(f"规则表 YAML 解析失败 {p}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RulesConfigError(f"{p}: 顶层必须是映射，得到 {type(raw).__name__}")
    where = str(p)

    allowed_top = {"version", "defaults", "features", "references", "rules"}
    unknown = sorted(set(raw) - allowed_top)
    if unknown:
        raise RulesConfigError(f"{where}: 未知顶层键 {unknown}（允许: {sorted(allowed_top)}）")
    if raw.get("version") != 1:
        raise RulesConfigError(f"{where}: `version` 必须是 1，得到 {raw.get('version')!r}")

    tax = taxonomy if taxonomy is not None else load_taxonomy()
    defect_keys = set(tax.keys()) - {"normal"}

    # ---- features 节（FeatureParams 字段级校验） ---------------------------
    fp = FeatureParams()
    fnode = raw.get("features", {})
    if not isinstance(fnode, dict):
        raise RulesConfigError(f"{where}: `features` 必须是映射")
    unknown = sorted(set(fnode) - {f.name for f in dc_fields(FeatureParams)})
    if unknown:
        raise RulesConfigError(f"{where}: features 未知键 {unknown}（合法: 特征参数字段）")
    overrides: dict[str, float | int] = {}
    for k, v in fnode.items():
        cur = getattr(fp, k)
        if isinstance(cur, bool) or isinstance(v, bool):
            raise RulesConfigError(f"{where}: features.{k} 必须是数值，得到 {v!r}")
        if isinstance(cur, int) and (not isinstance(v, int)):
            raise RulesConfigError(f"{where}: features.{k} 必须是整数，得到 {v!r}")
        val = _num(v, f"{where}: features.{k}")
        if isinstance(cur, int):
            val = int(val)
        if val < 0:
            raise RulesConfigError(f"{where}: features.{k} 必须 ≥ 0，得到 {val}")
        overrides[k] = val
    if overrides:
        fp = FeatureParams(**overrides)  # type: ignore[arg-type]

    # ---- references 节（CIE 参考点） ---------------------------------------
    cr = ColorRefs()
    rnode = raw.get("references", {})
    if not isinstance(rnode, dict):
        raise RulesConfigError(f"{where}: `references` 必须是映射")
    unknown = sorted(set(rnode) - {"black_ref_cie", "premium_ref_cie"})
    if unknown:
        raise RulesConfigError(f"{where}: references 未知键 {unknown}")
    for key in ("black_ref_cie", "premium_ref_cie"):
        if key not in rnode:
            continue
        vec = rnode[key]
        if not isinstance(vec, (list, tuple)) or len(vec) != 3:
            raise RulesConfigError(f"{where}: references.{key} 必须是 [L, a, b] 三元组，得到 {vec!r}")
        cie = tuple(_num(x, f"{where}: references.{key}[{i}]") for i, x in enumerate(vec))
        cr = _with_ref(cr, key, cie)  # type: ignore[arg-type]

    # ---- defaults 节 --------------------------------------------------------
    dnode = raw.get("defaults", {})
    if not isinstance(dnode, dict):
        raise RulesConfigError(f"{where}: `defaults` 必须是映射")
    unknown = sorted(set(dnode) - {"normal_conf"})
    if unknown:
        raise RulesConfigError(f"{where}: defaults 未知键 {unknown}")
    normal_conf = _num(dnode.get("normal_conf", 0.6), f"{where}: defaults.normal_conf")
    if not 0.0 <= normal_conf <= 1.0:
        raise RulesConfigError(f"{where}: defaults.normal_conf 必须在 [0,1]，得到 {normal_conf}")

    # ---- rules 节 ------------------------------------------------------------
    rlist = raw.get("rules")
    if not isinstance(rlist, list) or not rlist:
        raise RulesConfigError(f"{where}: `rules` 必须是非空列表")
    rules: list[RuleDef] = []
    for i, item in enumerate(rlist):
        rw = f"{where}: rules[{i}]"
        if not isinstance(item, dict):
            raise RulesConfigError(f"{rw}: 必须是映射")
        unknown = sorted(set(item) - {"defect", "conf", "when"})
        if unknown:
            raise RulesConfigError(f"{rw}: 未知键 {unknown}")
        defect = item.get("defect")
        if defect not in defect_keys:
            raise RulesConfigError(
                f"{rw}.defect 必须是 taxonomy 缺陷类（非 normal），得到 {defect!r}；"
                f"合法: {sorted(defect_keys)}"
            )
        conf = _num(item.get("conf", 0.8), f"{rw}.conf")
        if not 0.0 <= conf <= 1.0:
            raise RulesConfigError(f"{rw}.conf 必须在 [0,1]，得到 {conf}")
        when = item.get("when")
        if not isinstance(when, list) or not when:
            raise RulesConfigError(f"{rw}.when 必须是非空条件列表")
        conds: list[RuleCondition] = []
        for j, c in enumerate(when):
            cw = f"{rw}.when[{j}]"
            if not isinstance(c, dict) or sorted(c) != ["feat", "op", "value"]:
                raise RulesConfigError(
                    f"{cw}: 必须是 {{feat, op, value}} 映射，得到 {c!r}"
                )
            if c["feat"] not in FEATURE_NAMES:
                raise RulesConfigError(
                    f"{cw}.feat 未知特征 {c['feat']!r}；合法: {list(FEATURE_NAMES)}"
                )
            if c["op"] not in RULES_OPS:
                raise RulesConfigError(
                    f"{cw}.op 必须是 {sorted(RULES_OPS)} 之一，得到 {c['op']!r}"
                )
            conds.append(
                RuleCondition(
                    feat=str(c["feat"]), op=str(c["op"]), value=_num(c["value"], f"{cw}.value")
                )
            )
        rules.append(RuleDef(defect=str(defect), conf=conf, when=tuple(conds)))

    return RulesV0Config(
        version=1,
        rules=tuple(rules),
        normal_conf=normal_conf,
        feature_params=fp,
        color_refs=cr,
    )


def _with_ref(cr: ColorRefs, key: str, cie: tuple[float, float, float]) -> ColorRefs:
    data = {
        "black_ref_cie": cr.black_ref_cie,
        "premium_ref_cie": cr.premium_ref_cie,
        key: cie,
    }
    return ColorRefs(**data)  # type: ignore[arg-type]
