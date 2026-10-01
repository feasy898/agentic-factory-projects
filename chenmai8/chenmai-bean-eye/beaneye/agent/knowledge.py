"""M11 根因知识表加载器（configs/rootcause.yaml）。

TemplateAgent 的唯一数据源：缺陷 → 加工环节归因先验（causes/stage +
likelihood）→ 三语证据句模板 + 三语改进建议 + 引用条目。

加载期即强校验（失败抛 :class:`RootCauseConfigError`，错误带文件路径）：

- ``defects`` 必须与 ``configs/taxonomy.yaml`` 的缺陷类**恰好一一对应**
  （12 类，不含 normal）——「全缺陷类×三语建议齐全」由此成为加载期不变式；
- 三语（zh/en/vi）advice / evidence 缺语言、缺条目、空文本都拒绝；
- stage 只能取加工五环节；likelihood ∈ (0, 1]；
- 证据句模板的占位符在加载期用哑值试格式化，坏占位符提前暴露。

本模块只依赖 PyYAML 与 beaneye.taxonomy，不 import numpy/cv2/httpx。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOTCAUSE_PATH = REPO_ROOT / "configs" / "rootcause.yaml"
DEFAULT_TAXONOMY_PATH = REPO_ROOT / "configs" / "taxonomy.yaml"

LANGS: tuple[str, ...] = ("zh", "en", "vi")
# 契约规定的加工环节（AgentReport.cause.stage 规范取值）
VALID_STAGES: tuple[str, ...] = ("采摘", "发酵", "干燥", "仓储", "脱壳")

# 证据句占位符在加载期的哑值（用于提前暴露坏占位符）
_PLACEHOLDER_DUMMY: dict[str, str] = {
    "count": "2",
    "share": "20.0%",
    "total": "10",
    "name": "x",
    "stage": "y",
}

__all__ = [
    "DEFAULT_ROOTCAUSE_PATH",
    "DEFAULT_TAXONOMY_PATH",
    "LANGS",
    "VALID_STAGES",
    "RootCauseConfigError",
    "CauseRule",
    "DefectKnowledge",
    "GeneralKnowledge",
    "RootCauseKnowledge",
    "load_rootcause",
]


class RootCauseConfigError(ValueError):
    """rootcause.yaml 缺失 / 非法 / 与 taxonomy 不一致时抛出。"""


@dataclass(frozen=True)
class CauseRule:
    """单条环节归因先验。"""

    stage: str  # 加工环节（VALID_STAGES 之一）
    likelihood: float  # 先验强度 (0, 1]


@dataclass(frozen=True)
class DefectKnowledge:
    """单个缺陷类的根因知识（不可变）。"""

    key: str  # taxonomy key
    causes: tuple[CauseRule, ...]  # 已按 likelihood 降序
    evidence: dict[str, str]  # lang -> 证据句模板（含占位符）
    advice: dict[str, tuple[str, ...]]  # lang -> 建议列表
    citations: tuple[str, ...]

    def primary_stage(self) -> str:
        """主归因环节（likelihood 最高的候选）。"""
        return self.causes[0].stage

    def format_evidence(
        self,
        rule: CauseRule,
        lang: str,
        *,
        count: int,
        total: int,
        name: str,
        stage_display: dict[str, dict[str, str]],
    ) -> str:
        """把证据句模板按语言与实据格式化（占位符见模块文件头）。"""
        share = f"{(count / total * 100.0):.1f}%" if total > 0 else "0.0%"
        return self.evidence[lang].format(
            count=count,
            share=share,
            total=total,
            name=name,
            stage=stage_display.get(rule.stage, {}).get(lang, rule.stage),
        )


@dataclass(frozen=True)
class GeneralKnowledge:
    """通用建议与引用（好豆批的全部输出；缺陷批追加在其后）。"""

    advice: dict[str, tuple[str, ...]]
    citations: tuple[str, ...]


@dataclass(frozen=True)
class RootCauseKnowledge:
    """整张根因知识表（不可变视图）。"""

    defects: dict[str, DefectKnowledge]  # taxonomy 缺陷 key → 知识
    general: GeneralKnowledge
    stages: tuple[str, ...]
    stage_names: dict[str, dict[str, str]]  # stage -> {en, vi}（zh 即键）

    def format_stage(self, stage: str, lang: str) -> str:
        """环节名的显示文本（en/vi 走译名表，zh 即环节键）。"""
        if lang == "zh":
            return stage
        return self.stage_names.get(stage, {}).get(lang, stage)


# ---------------------------------------------------------------------------
# 加载与校验
# ---------------------------------------------------------------------------


def _where(path: Path | None) -> str:
    return f" (文件: {path})" if path is not None else ""


def _fail(msg: str, path: Path | None) -> "RootCauseConfigError":
    return RootCauseConfigError(f"{msg}{_where(path)}")


def _check_lang_map(
    m: object, what: str, *, path: Path | None, want_items: bool
) -> dict[str, tuple[str, ...]]:
    """校验 {zh,en,vi} 三语映射；want_items=True 时值必须是非空字符串列表。"""
    if not isinstance(m, dict) or set(m.keys()) != set(LANGS):
        raise _fail(f"{what} 必须恰含三语键 {list(LANGS)}，得到 {m!r}", path)
    out: dict[str, tuple[str, ...]] = {}
    for lang in LANGS:
        v = m[lang]
        if want_items:
            if (
                not isinstance(v, list)
                or not v
                or not all(isinstance(x, str) and x.strip() for x in v)
            ):
                raise _fail(
                    f"{what}[{lang}] 必须是非空字符串列表（条目不得空白）", path
                )
            out[lang] = tuple(v)
        else:
            if not isinstance(v, str) or not v.strip():
                raise _fail(f"{what}[{lang}] 必须是非空字符串", path)
            out[lang] = (v,)
    return out


def _load(path: Path | None) -> tuple[dict, Path]:
    p = Path(path) if path is not None else DEFAULT_ROOTCAUSE_PATH
    if not p.is_file():
        raise _fail("根因知识表不存在", p)
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise _fail(f"根因知识表 YAML 解析失败:\n{e}", p) from e
    if not isinstance(raw, dict):
        raise _fail("根因知识表顶层必须是映射", p)
    return raw, p


def load_rootcause(
    path: str | Path | None = None,
    *,
    taxonomy: "object | None" = None,  # beaneye.taxonomy.Taxonomy
) -> RootCauseKnowledge:
    """加载并校验根因知识表（默认 configs/rootcause.yaml）。

    ``taxonomy`` 缺省时加载默认 taxonomy；传入自定义 taxonomy 时，
    ``defects`` 的覆盖校验以它为准（与缺陷体系联动）。
    """
    from beaneye.taxonomy import Taxonomy, load_taxonomy

    tax = taxonomy if isinstance(taxonomy, Taxonomy) else load_taxonomy()
    raw, p = _load(path)

    version = raw.get("version")
    if not isinstance(version, int) or version < 1:
        raise _fail(f"version 必须 >= 1，得到 {version!r}", p)

    stages = raw.get("stages", list(VALID_STAGES))
    if (
        not isinstance(stages, list)
        or not stages
        or not all(isinstance(s, str) and s.strip() for s in stages)
    ):
        raise _fail("stages 必须是非空环节名列表", p)
    if len(set(stages)) != len(stages):
        raise _fail(f"stages 存在重复环节: {stages}", p)

    # 环节译名（en/vi；zh 即环节键本身）
    stage_names_raw = raw.get("stage_names", {})
    if not isinstance(stage_names_raw, dict):
        raise _fail("stage_names 必须是 环节→译名 映射", p)
    stage_names: dict[str, dict[str, str]] = {}
    for s in stages:
        names = stage_names_raw.get(s)
        if (
            not isinstance(names, dict)
            or set(names.keys()) != {"en", "vi"}
            or not all(isinstance(v, str) and v.strip() for v in names.values())
        ):
            raise _fail(f"stage_names[{s!r}] 必须恰含非空 en/vi 译名", p)
        stage_names[s] = {"en": names["en"], "vi": names["vi"]}

    # 三语证据句模板（整库共用）
    evidence = _check_lang_map(raw.get("evidence"), "evidence", path=p, want_items=False)
    for lang in LANGS:
        try:
            evidence[lang][0].format(**_PLACEHOLDER_DUMMY)
        except (KeyError, IndexError, ValueError) as e:
            raise _fail(f"evidence[{lang}] 含非法占位符: {e}", p) from e

    # defects：与 taxonomy 缺陷类恰好一一对应
    defects_raw = raw.get("defects")
    if not isinstance(defects_raw, dict) or not defects_raw:
        raise _fail("defects 必须是非空映射", p)
    expected = set(tax.defect_keys())  # 12 类（不含 normal）
    got = set(defects_raw)
    missing = sorted(expected - got)
    extra = sorted(got - expected)
    if missing:
        raise _fail(f"defects 缺少 taxonomy 缺陷类: {missing}", p)
    if extra:
        raise _fail(f"defects 含 taxonomy 之外的键: {extra}（normal 走 general）", p)
    if "normal" in got:
        raise _fail("defects 不得包含 normal（好豆批走 general）", p)

    defects: dict[str, DefectKnowledge] = {}
    for key, item in defects_raw.items():
        if not isinstance(item, dict):
            raise _fail(f"defects.{key} 必须是映射", p)
        causes_raw = item.get("causes")
        if not isinstance(causes_raw, list) or not causes_raw:
            raise _fail(f"defects.{key}.causes 必须是非空列表", p)
        rules: list[CauseRule] = []
        for i, c in enumerate(causes_raw):
            if not isinstance(c, dict):
                raise _fail(f"defects.{key}.causes[{i}] 必须是映射", p)
            stage = c.get("stage")
            if stage not in stages:
                raise _fail(
                    f"defects.{key}.causes[{i}].stage 非法: {stage!r}（合法: {list(stages)}）", p
                )
            lik = c.get("likelihood")
            if not isinstance(lik, (int, float)) or isinstance(lik, bool):
                raise _fail(f"defects.{key}.causes[{i}].likelihood 必须是数值", p)
            if not math.isfinite(float(lik)) or not 0.0 < float(lik) <= 1.0:
                raise _fail(
                    f"defects.{key}.causes[{i}].likelihood 必须在 (0, 1]，得到 {lik!r}", p
                )
            rules.append(CauseRule(stage=stage, likelihood=float(lik)))
        rules.sort(key=lambda r: -r.likelihood)
        # 建议加载期再做一次哑值格式化（证据模板 + 各候选环节译名）
        for r in rules:
            for lang in LANGS:
                try:
                    evidence[lang][0].format(
                        count=1,
                        share="1.0%",
                        total=1,
                        name=getattr(tax.get(key), lang),
                        stage=stage_names.get(r.stage, {}).get(lang, r.stage),
                    )
                except (KeyError, IndexError, ValueError) as e:
                    raise _fail(
                        f"defects.{key} 证据句在 {lang} 下格式化失败: {e}", p
                    ) from e
        defects[key] = DefectKnowledge(
            key=key,
            causes=tuple(rules),
            evidence={lang: texts[0] for lang, texts in evidence.items()},
            advice=_check_lang_map(item.get("advice"), f"defects.{key}.advice", path=p, want_items=True),
            citations=_check_citations(item.get("citations"), f"defects.{key}.citations", p),
        )

    general_raw = raw.get("general")
    if not isinstance(general_raw, dict):
        raise _fail("general 必须是映射", p)
    general = GeneralKnowledge(
        advice=_check_lang_map(general_raw.get("advice"), "general.advice", path=p, want_items=True),
        citations=_check_citations(general_raw.get("citations"), "general.citations", p),
    )

    return RootCauseKnowledge(
        defects=defects,
        general=general,
        stages=tuple(stages),
        stage_names=stage_names,
    )


def _check_citations(v: object, what: str, path: Path | None) -> tuple[str, ...]:
    if (
        not isinstance(v, list)
        or not v
        or not all(isinstance(x, str) and x.strip() for x in v)
    ):
        raise _fail(f"{what} 必须是非空字符串列表", path)
    return tuple(v)
