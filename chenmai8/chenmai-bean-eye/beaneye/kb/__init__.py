"""知识库检索接口（M11 可选增强 · 接口留桩）。

为溯因智能体提供「标准文本 / 缺陷图说明 / 初加工规范」切块后的检索能力。
本模块只冻结接口与离线默认实现（NullKnowledgeBase 恒返回空），保证：

- 智能体主链路评测不依赖网络与任何重型依赖；
- 未来可插拔两类后端（均为可选增强，缺失时自动降级到本模块）：
  * ``EmbedKb``   —— 语义嵌入 + 向量索引（模型缓存到 ``models/``，
                     索引持久化到 ``data/kb_index/``），多语召回更好；
  * ``KeywordKb`` —— 词频检索兜底（无模型依赖，CPU 极快）。
- 后端未装配或装配失败时，业务侧拿到 :class:`NullKnowledgeBase`，
  溯因报告照常产出（citations 仅剩知识表自带条目）。

切块来源（内部规划，不在本模块实现）：三套标准 YAML + 缺陷图说明 +
初加工标准文本，按「条款/条目」粒度切块，chunk_id 形如
``kb:rootcause.black`` / ``std:cqi_fine_robusta#defect.black``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "KbChunk",
    "KnowledgeBase",
    "NullKnowledgeBase",
]


@dataclass(frozen=True)
class KbChunk:
    """一条知识库切块（检索结果的最小单元）。"""

    chunk_id: str  # 知识库 chunk id，可直接进 AgentReport.citations
    text: str  # 切块正文（原样引用，不得改写）
    source: str  # 来源标识，如 "std:cqi_fine_robusta" / "guide:defect-photos"
    score: float = 0.0  # 检索相关度（后端自定义标度，越高越相关）
    metadata: dict[str, Any] = field(default_factory=dict)  # 语言/标准条目号等


@runtime_checkable
class KnowledgeBase(Protocol):
    """知识库检索接口（M11 智能体的可选依赖）。

    实现必须离线安全：不可用时应返回空列表而不是抛异常，
    保证溯源主链路在任何部署形态下都能跑通。
    """

    def retrieve(self, query: str, k: int = 4) -> list[KbChunk]:
        """按查询文本返回至多 ``k`` 条切块，按相关度降序。"""
        ...


class NullKnowledgeBase:
    """离线空知识库：恒返回空（默认装配，零依赖零网络）。"""

    def retrieve(self, query: str, k: int = 4) -> list[KbChunk]:
        return []

    def __repr__(self) -> str:  # pragma: no cover
        return "NullKnowledgeBase()"
