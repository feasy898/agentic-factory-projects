# -*- coding: utf-8 -*-
"""m1_core.model_client · LLM 统一客户端【占位】。

定位（specs/01-contracts.md §8 横切约定 / specs/M1-agent-core.md §2）：
- 模型调用统一走本客户端（provider 适配层，支持本地/云端切换）；
  **禁止业务模块直连 SDK**；
- mock 模式可全离线跑 EVAL（M1 DoD：provider=mock 下全部 EVAL 可离线复跑）；
- 职责含：provider 适配、超时/重试、成本（token/费用）上报。

冻结调用边界（本占位仅声明接口形状，实现由 M1 交付；签名变更走 01 §7 契约变更流程）::

    class ModelClient(Protocol):
        def complete(self, request: ModelRequest) -> ModelResponse: ...
        # request  含：messages、tools(descriptor)、temperature、max_tokens、
        #             trace_id（贯穿 Task→Action→Event→Artifact→Trajectory）
        # response 含：text、tool_calls?、usage{prompt_tokens, completion_tokens}、
        #             cost（供 SPEC-M1-10 成本上报写 TaskState.budget 与事件流）、
        #             provider、model、latency_ms
        # 失败语义：超时/限流按可重试错误分类；重试预算耗尽抛 ModelClientError

    Provider 适配点：
    - provider="mock"      ：确定性离线实现（EVAL 默认；脚本化回放，不触网）
    - provider="openai_like"：云端适配（端点/密钥经配置注入，密钥永不入代码）
"""
from __future__ import annotations

__all__ = ["ModelClientError"]


class ModelClientError(RuntimeError):
    """模型调用失败（超时/重试预算耗尽/provider 错误）。"""


class ModelClient:
    """统一模型客户端占位：S0 阶段不提供实现。"""

    def __init__(self, provider: str = "mock", **options: object) -> None:
        self.provider = provider
        self.options = dict(options)

    def complete(self, request: dict) -> dict:  # noqa: D401
        """发起一次模型调用。M1 交付前一律不可用。"""
        raise NotImplementedError(
            "model_client 由 M1 交付实现（specs/M1-agent-core.md §2；"
            "provider=mock 模式须支持全离线 EVAL）"
        )
