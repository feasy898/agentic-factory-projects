"""缺陷分类体系加载器（configs/taxonomy.yaml 唯一数据源）。

重生成实现依据：docs/assets/specs/severity.md §2 与 docs/assets/CONTRACTS.md
「数据文件与配置 · DATA-taxonomy」。taxonomy 提供：

- 合法类别全集（``keys``，全链路 ``defect`` 字段构造期校验的取值域）
- 默认严重度序（``severity_order``，下标即 severity_rank，``[0]`` 恒 normal）
- 逐类属性（``kind`` 主/次/好豆、``counts_as_defect`` 可计性）

加载结果按路径缓存（同机同文件多模块共用同一实例）。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Iterator

import yaml

__all__ = ["Taxonomy", "TaxonomyError", "load_taxonomy"]


class TaxonomyError(RuntimeError):
    """taxonomy 数据缺失 / 结构非法 / 类别键越界。"""


class Taxonomy:
    """13 类缺陷分类体系：合法取值、主次归属、可计性与默认严重度序。"""

    def __init__(self, data: dict, source: str = "taxonomy") -> None:
        if not isinstance(data, dict):
            raise TaxonomyError("taxonomy 顶层必须是映射")
        classes = data.get("classes")
        if not isinstance(classes, dict) or not classes:
            raise TaxonomyError("taxonomy 缺少非空 classes 节")
        order = data.get("severity_order")
        if not isinstance(order, list) or not order:
            raise TaxonomyError("taxonomy 缺少非空 severity_order 节")
        keys = [str(k) for k in order]
        if len(set(keys)) != len(keys):
            raise TaxonomyError("severity_order 存在重复类别")
        if set(keys) != {str(k) for k in classes}:
            raise TaxonomyError("severity_order 与 classes 类别集合不一致")
        if keys[0] != "normal":
            raise TaxonomyError("severity_order[0] 必须是 normal（0=normal 是契约）")
        self._classes: dict[str, dict] = {str(k): dict(v) for k, v in classes.items()}
        self._order: list[str] = keys
        self.source = source
        self.version = int(data.get("version", 1))

    # -- 容器协议 -----------------------------------------------------------
    def keys(self) -> tuple[str, ...]:
        """全部类别键（含 normal）。"""
        return tuple(self._classes)

    def __contains__(self, key: object) -> bool:
        return key in self._classes

    def __iter__(self) -> Iterator[str]:
        return iter(self._classes)

    def __len__(self) -> int:
        return len(self._classes)

    # -- 严重度序 -------------------------------------------------------------
    @property
    def severity_order(self) -> list[str]:
        """默认严重度序（下标即 severity_rank，[0] 恒 normal）。"""
        return list(self._order)

    def severity_rank(self, key: str) -> int:
        """类别在默认序中的位次；未知类别报错。"""
        if key not in self._order:
            raise TaxonomyError(f"类别 {key!r} 不在 taxonomy severity_order")
        return self._order.index(key)

    # -- 逐类属性 -------------------------------------------------------------
    def info(self, key: str) -> dict:
        if key not in self._classes:
            raise TaxonomyError(f"未知类别 {key!r}（不在 taxonomy）")
        return self._classes[key]

    def kind(self, key: str) -> str:
        """类别归属：primary（主缺陷）/ secondary（次缺陷）/ normal（好豆）。"""
        return str(self.info(key).get("kind", ""))

    def counts_as_defect(self, key: str) -> bool:
        """是否计入缺陷计数；未知类别一律 False（severity spec §1）。"""
        if key not in self._classes:
            return False
        return bool(self._classes[key].get("counts_as_defect", False))


@lru_cache(maxsize=None)
def _load_cached(path: str) -> Taxonomy:
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    tax = Taxonomy(data, source=f"taxonomy:{Path(path).as_posix()}")
    return tax


def load_taxonomy(path: str | Path | None = None) -> Taxonomy:
    """加载 taxonomy（默认仓库根 ``configs/taxonomy.yaml``，按路径缓存）。"""
    if path is None:
        path = Path(__file__).resolve().parent.parent / "configs" / "taxonomy.yaml"
    p = Path(path)
    if not p.is_file():
        raise TaxonomyError(f"taxonomy 数据文件不存在: {p}")
    return _load_cached(str(p))
