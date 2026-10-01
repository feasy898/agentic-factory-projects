"""taxonomy 加载器（beaneye/taxonomy.py 的唯一数据源 = configs/taxonomy.yaml）。

spec 依据（docs/assets/specs/severity.md）：
- §2：唯一权威 = 契约附件 configs/taxonomy.yaml（classes 节 + severity_order）。
- §3：默认序取自 taxonomy.yaml 的 severity_order，下标即 severity_rank
  （0=normal，越大越严重）；Taxonomy.severity_rank 每次访问现场重算索引，
  不预计算 rank 表、不跨调用缓存。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

import yaml

#: taxonomy 契约附件默认位置：仓库根 configs/taxonomy.yaml
DEFAULT_TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "configs" / "taxonomy.yaml"


class TaxonomyError(ValueError):
    """taxonomy 契约附件不满足契约不变式（类别集/默认序）。"""


@dataclass(frozen=True)
class Taxonomy:
    """缺陷分类体系（classes + severity_order 默认序）。"""

    version: int
    classes: Mapping[str, Mapping[str, Any]]
    severity_order: list[str] = field(default_factory=list)
    source: str = ""

    def keys(self) -> tuple[str, ...]:
        """全部合法 defect 取值（= classes 的 key，YAML 顺序）。"""
        return tuple(self.classes.keys())

    def severity_rank(self, key: str) -> int:
        """类别在默认序中的下标（0=normal）。每次调用现场 index 重算，无缓存。"""
        return list(self.severity_order).index(key)

    def kind(self, key: str) -> Optional[str]:
        """primary / secondary / normal；未知类别 → None。"""
        info = self.classes.get(key)
        return info.get("kind") if info else None

    def is_countable(self, key: str) -> bool:
        """counts_as_defect（peaberry=false）；未知类别 → False。"""
        info = self.classes.get(key)
        return bool(info and info.get("counts_as_defect", False))

    def __contains__(self, key: object) -> bool:
        return key in self.classes

    def __len__(self) -> int:
        return len(self.classes)


def _validate(classes: Mapping[str, Any], order: list[str]) -> None:
    if not classes:
        raise TaxonomyError("taxonomy 缺少 classes 节或为空")
    if not order:
        raise TaxonomyError("taxonomy 缺少 severity_order")
    if len(set(order)) != len(order):
        raise TaxonomyError(f"severity_order 存在重复类别: {order}")
    if order[0] != "normal":
        raise TaxonomyError("severity_order[0] 必须是 normal（0=normal 是契约）")
    expected = set(classes.keys())
    got = set(order)
    if got != expected:
        raise TaxonomyError(
            f"severity_order 与 classes 不一致: 缺失={sorted(expected - got)} "
            f"未知={sorted(got - expected)}"
        )


def _load(path: Path) -> Taxonomy:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TaxonomyError(f"taxonomy YAML 不是映射: {path}")
    classes: dict[str, dict[str, Any]] = dict(data.get("classes") or {})
    order = [str(k) for k in (data.get("severity_order") or [])]
    _validate(classes, order)
    return Taxonomy(
        version=int(data.get("version", 1)),
        classes=classes,
        severity_order=order,
        source=str(path),
    )


_CACHE: dict[str, Taxonomy] = {}


def load_taxonomy(path: str | Path | None = None) -> Taxonomy:
    """加载 taxonomy 契约附件（缺省 configs/taxonomy.yaml，按路径缓存配置对象）。"""
    p = Path(path) if path is not None else DEFAULT_TAXONOMY_PATH
    key = str(p.resolve())
    if key not in _CACHE:
        _CACHE[key] = _load(p)
    return _CACHE[key]
