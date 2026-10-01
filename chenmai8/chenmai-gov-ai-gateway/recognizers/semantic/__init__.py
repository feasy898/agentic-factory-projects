"""语义层（M2，T4.2 第一档）：注入检测词表 + 位置启发 + LLM-judge 适配器。

对外入口：
- :func:`adapter.SemanticAdapter.moderate` — 契约形状 ``{verdict, categories}``（P0 冻结）；
- :func:`adapter.SemanticAdapter.detect` — INJECTION Finding 列表（网关主链路消费，
  经 ``routing.engine.decide`` R2 完成「拦截进 decide」）；
- :func:`adapter.get_semantic_adapter` — 进程级单例。
"""
from recognizers.semantic.adapter import SemanticAdapter, get_semantic_adapter

__all__ = ["SemanticAdapter", "get_semantic_adapter"]
