"""上游适配（provider gateway adapter）：OpenAI 兼容异步转发客户端。

v0 只需非流式转发；流式 SSE 逐块透传由流式链路任务在同一模块扩展。
上游清单来自 config/app.yaml（name/base_url/api_key_env/models/route），
api_key 按环境变量名在请求期解析，永不落配置/日志。
"""
from __future__ import annotations

from typing import Any

import httpx

from common.config import UpstreamCfg

DEFAULT_TIMEOUT_S = 60.0


class UpstreamUnavailableError(RuntimeError):
    """上游不可达/返回非 JSON（网络层失败）；由网关映射为 502 错误信封。"""


def chat_endpoint(base_url: str) -> str:
    """base_url（约定以 /v1 结尾）→ chat/completions 端点。"""
    return base_url.rstrip("/") + "/chat/completions"


async def forward_chat(
    upstream: UpstreamCfg,
    payload: dict[str, Any],
    *,
    api_key: str | None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> tuple[int, dict[str, Any]]:
    """非流式转发：POST {base_url}/chat/completions → (上游HTTP状态码, JSON 体)。

    上游返回非 2xx 时同样返回其状态码与错误 JSON（网关对上游错误做透明传递，
    错误体是上游协议形状，不经网关错误信封改写）。
    """
    headers = {"authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(chat_endpoint(upstream.base_url), json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise UpstreamUnavailableError(f"upstream {upstream.name} unreachable: {type(exc).__name__}") from exc
    try:
        data = resp.json()
    except ValueError as exc:
        raise UpstreamUnavailableError(f"upstream {upstream.name} returned non-JSON body") from exc
    if not isinstance(data, dict):
        raise UpstreamUnavailableError(f"upstream {upstream.name} returned non-object JSON")
    return resp.status_code, data
