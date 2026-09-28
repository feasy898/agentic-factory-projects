"""语义适配器（开发指令 §6 M2）：prompt/文本语义审核入口。

P0 口径（铁律 D）：**always-safe 空实现**——``moderate`` 恒返回
``{"verdict": "safe", "categories": []}``，即"未发现任何语义级风险"的中性判定；
D4 换 guard 模型后端（moderation model，路径配置 ``config.app.moderation_model``）
时仅替换本文件实现，``moderate(text) -> {verdict, categories}`` 形状不变，
注入拦截率/误拦率的验收见 ``evals.m2_semantic``（D4 起生效）。
"""
from __future__ import annotations

from typing import Any


class SemanticAdapter:
    """语义审核适配器（P0：always-safe，不产出任何判定）。"""

    def __init__(self, model_path: str | None = None) -> None:
        self.model_path = model_path

    def moderate(self, text: str) -> dict[str, Any]:
        """语义审核（P0：恒 safe；verdict ∈ {"safe", "flagged"}，categories 为风险类目表）。"""
        return {"verdict": "safe", "categories": []}


_ADAPTER: SemanticAdapter | None = None


def get_semantic_adapter(model_path: str | None = None) -> SemanticAdapter:
    """进程级单例。"""
    global _ADAPTER
    if _ADAPTER is None:
        _ADAPTER = SemanticAdapter(model_path)
    return _ADAPTER
