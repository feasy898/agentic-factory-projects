"""llmgw —— chat-completions 通用客户端（纯标准库，配置全靠 env 注入）。"""

from llmgw.client import (Client, ConfigError, Gateway, LLMError, chat,
                          endpoint_for, json_of, text_of)

__all__ = [
    "Client",
    "ConfigError",
    "Gateway",
    "LLMError",
    "chat",
    "endpoint_for",
    "json_of",
    "text_of",
]
