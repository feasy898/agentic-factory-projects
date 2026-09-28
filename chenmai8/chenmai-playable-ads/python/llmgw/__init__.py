"""llmgw —— LLM 网关（M6）。

通用 chat-completions 协议抽象层：对话 / 图片 base64 输入 / JSON 模式 /
超时重试 / 多模型降级。端点、密钥、模型全部由环境变量驱动
（PF_LLM_BASE_URL / PF_LLM_API_KEY / PF_LLM_MODEL / PF_LLM_FALLBACK_MODELS），
代码零厂商硬编码；仅依赖 Python 标准库。

用法：
    from llmgw import Gateway, text_of, json_of
    gw = Gateway()  # 配置来自环境变量
    resp = gw.chat([{"role": "user", "content": "ping"}])
    print(text_of(resp))

    # 图片输入（base64）+ JSON 模式
    resp = gw.chat([{"role": "user", "content": "描述这张图"}],
                   images=["<base64...>"],
                   json_schema={"type": "object", "required": ["desc"]})
    data = json_of(resp)

离线自测（内置 mock 服务，无外网访问）：
    python -m llmgw.selftest
"""

from llmgw.client import (
    Client,
    ConfigError,
    Gateway,
    LLMError,
    chat,
    endpoint_for,
    json_of,
    redact,
    text_of,
)

__all__ = [
    "Gateway",
    "Client",
    "LLMError",
    "ConfigError",
    "chat",
    "text_of",
    "json_of",
    "endpoint_for",
    "redact",
]

__version__ = "0.1.0"
