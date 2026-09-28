"""缺陷分类体系加载器（M1 · 契约附件）

唯一数据源：``configs/taxonomy.yaml``。全链路 ``defect`` 字段的合法取值、
严重度默认序、素材来源类别映射都从这里读。

用法::

    from beaneye.taxonomy import load_taxonomy

    tax = load_taxonomy()
    tax.severity_rank("black")   # -> 12
    tax.is_valid_key("black")    # -> True
    tax.map_upstream("poly12", "frozen")  # -> "dried"
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "configs" / "taxonomy.yaml"

VALID_KINDS = ("primary", "secondary", "normal")

__all__ = [
    "DEFAULT_TAXONOMY_PATH",
    "TaxonomyError",
    "DefectClass",
    "Taxonomy",
    "load_taxonomy",
]


class TaxonomyError(ValueError):
    """taxonomy.yaml 缺失 / 非法 / 自相矛盾时抛出。"""


@dataclass(frozen=True)
class DefectClass:
    """单个缺陷类别定义。"""

    key: str
    kind: str  # primary | secondary | normal
    zh: str
    en: str
    vi: str
    counts_as_defect: bool
    verified: bool
    vi_verified: bool


class Taxonomy:
    """已加载并校验的分类体系（不可变视图）。"""

    def __init__(self, raw: dict, source_path: Path | None = None):
        self._raw = raw
        self.source_path = source_path
        self.version: int = int(raw.get("version", 0))
        self._classes: dict[str, DefectClass] = {}
        for key, item in (raw.get("classes") or {}).items():
            try:
                self._classes[key] = DefectClass(
                    key=key,
                    kind=item["kind"],
                    zh=item["zh"],
                    en=item["en"],
                    vi=item["vi"],
                    counts_as_defect=bool(item["counts_as_defect"]),
                    verified=bool(item.get("verified", False)),
                    vi_verified=bool(item.get("vi_verified", False)),
                )
            except KeyError as e:
                raise TaxonomyError(f"类别 {key!r} 缺少字段 {e}") from e
        self.severity_order: list[str] = list(raw.get("severity_order") or [])
        self.upstream_mapping: dict[str, dict[str, str | None]] = {
            src: dict(m) for src, m in (raw.get("upstream_mapping") or {}).items()
        }
        self.notes: list[str] = list(raw.get("notes") or [])
        self._validate()

    # ------------------------------------------------------------------
    def _validate(self) -> None:
        where = f" (文件: {self.source_path})" if self.source_path else ""
        if not self._classes:
            raise TaxonomyError(f"classes 为空{where}")
        if self.version < 1:
            raise TaxonomyError(f"version 必须 >= 1{where}")
        for key, dc in self._classes.items():
            if dc.kind not in VALID_KINDS:
                raise TaxonomyError(f"类别 {key!r} 的 kind 非法: {dc.kind!r}{where}")
        if not self.severity_order:
            raise TaxonomyError(f"severity_order 为空{where}")
        if len(set(self.severity_order)) != len(self.severity_order):
            dup = {k for k in self.severity_order if self.severity_order.count(k) > 1}
            raise TaxonomyError(f"severity_order 存在重复类别: {sorted(dup)}{where}")
        unknown = set(self.severity_order) - set(self._classes)
        if unknown:
            raise TaxonomyError(f"severity_order 含未定义类别: {sorted(unknown)}{where}")
        missing = set(self._classes) - set(self.severity_order)
        if missing:
            raise TaxonomyError(f"类别未进入 severity_order: {sorted(missing)}{where}")
        if self.severity_order[0] != "normal":
            raise TaxonomyError(f"severity_order[0] 必须是 normal（0=normal 契约）{where}")
        normal = self._classes["normal"]
        if normal.kind != "normal" or normal.counts_as_defect:
            raise TaxonomyError(f"normal 类必须 kind=normal 且 counts_as_defect=false{where}")
        for src, mapping in self.upstream_mapping.items():
            for up_key, target in mapping.items():
                if target is not None and target not in self._classes:
                    raise TaxonomyError(
                        f"upstream_mapping[{src}][{up_key!r}] 目标 {target!r} 不在 classes 中{where}"
                    )

    # ------------------------------------------------------------------
    def is_valid_key(self, key: str) -> bool:
        return key in self._classes

    def require(self, key: str) -> DefectClass:
        if key not in self._classes:
            raise TaxonomyError(
                f"未知缺陷类别 {key!r}；合法取值: {sorted(self._classes)}"
            )
        return self._classes[key]

    def get(self, key: str) -> DefectClass:
        return self._classes[key]

    def keys(self) -> list[str]:
        return list(self._classes)

    def severity_rank(self, key: str) -> int:
        """严重度位次：0=normal，越大越严重（severity_order 下标）。"""
        if key not in self._severity_index:
            raise TaxonomyError(
                f"未知缺陷类别 {key!r}；合法取值: {sorted(self._classes)}"
            )
        return self._severity_index[key]

    @property
    def _severity_index(self) -> dict[str, int]:
        return {k: i for i, k in enumerate(self.severity_order)}

    def primary_keys(self) -> list[str]:
        return [k for k, dc in self._classes.items() if dc.kind == "primary"]

    def secondary_keys(self) -> list[str]:
        return [k for k, dc in self._classes.items() if dc.kind == "secondary"]

    def defect_keys(self) -> list[str]:
        """计入缺陷计数的类别（不含 normal；含 peaberry 标注类需另按 counts_as_defect 判断）。"""
        return [k for k, dc in self._classes.items() if dc.kind != "normal"]

    def counting_defect_keys(self) -> list[str]:
        """真正计入缺陷计数的类别（counts_as_defect=true，peaberry 不在内）。"""
        return [k for k, dc in self._classes.items() if dc.counts_as_defect]

    def map_upstream(self, source: str, upstream_key: str) -> str | None:
        """素材来源类别 → 本体系 key；未登记来源或 null → None。"""
        return self.upstream_mapping.get(source, {}).get(upstream_key)

    def upstream_sources(self) -> list[str]:
        return list(self.upstream_mapping)


def load_taxonomy(path: str | Path | None = None) -> Taxonomy:
    """加载并校验 taxonomy.yaml（默认 configs/taxonomy.yaml）。"""
    p = Path(path) if path is not None else DEFAULT_TAXONOMY_PATH
    if not p.is_file():
        raise TaxonomyError(f"taxonomy 文件不存在: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise TaxonomyError(f"taxonomy YAML 解析失败: {p}\n{e}") from e
    if not isinstance(raw, dict):
        raise TaxonomyError(f"taxonomy YAML 顶层必须是映射: {p}")
    return Taxonomy(raw, source_path=p)
