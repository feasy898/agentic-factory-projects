"""上游适配（provider gateway adapter）：OpenAI 兼容异步转发客户端。

非流式转发 + 流式打开（SSE 逐块透传由 gateway/sse.py 组合管线接手）。
上游清单来自 config/app.yaml（name/base_url/api_key_env/models/route），
api_key 按环境变量名在请求期解析，永不落配置/日志。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from common.config import UpstreamCfg

DEFAULT_TIMEOUT_S = 60.0


class UpstreamUnavailableError(RuntimeError):
    """上游不可达/返回非 JSON（网络层失败）；由网关映射为 502 错误信封。"""


def chat_endpoint(base_url: str) -> str:
    """base_url（约定以 /v1 结尾）→ chat/completions 端点。"""
    return base_url.rstrip("/") + "/chat/completions"


def _auth_headers(api_key: str | None) -> dict[str, str]:
    return {"authorization": f"Bearer {api_key}"} if api_key else {}


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
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(chat_endpoint(upstream.base_url), json=payload,
                                     headers=_auth_headers(api_key))
    except httpx.HTTPError as exc:
        raise UpstreamUnavailableError(f"upstream {upstream.name} unreachable: {type(exc).__name__}") from exc
    try:
        data = resp.json()
    except ValueError as exc:
        raise UpstreamUnavailableError(f"upstream {upstream.name} returned non-JSON body") from exc
    if not isinstance(data, dict):
        raise UpstreamUnavailableError(f"upstream {upstream.name} returned non-object JSON")
    return resp.status_code, data


class UpstreamStream:
    """已打开的上游流式连接：状态码先知，200 后逐块迭代，用毕必须 :meth:`aclose`。

    非 200 时响应体已被完整读入 :attr:`body`（调用方直接 JSON 解析做透明传递），
    连接同时已释放；200 时调用方 ``aiter()`` 消费字节流，结束/异常路径都要
    ``await aclose()``（gateway/sse.py 的组合管线在 finally 中保证）。
    """

    def __init__(self, name: str, client: httpx.AsyncClient, resp: httpx.Response) -> None:
        self.name = name
        self._client = client
        self._resp = resp
        self.status_code = resp.status_code
        self.body: bytes = b""
        self._closed = False  # 非 200 的读体+释放统一在 aread()/aclose() 完成

    async def aread(self) -> bytes:
        """读入完整响应体并释放连接（非 200 透明传递路径专用）。"""
        if not self.body:
            try:
                self.body = await self._resp.aread()
            finally:
                await self.aclose()
        return self.body

    def aiter(self) -> AsyncIterator[bytes]:
        """200 路径：响应体字节块迭代器（SSE 组合管线消费）。"""
        return self._resp.aiter_bytes()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._resp.aclose()
        finally:
            await self._client.aclose()


async def open_stream_chat(
    upstream: UpstreamCfg,
    payload: dict[str, Any],
    *,
    api_key: str | None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> UpstreamStream:
    """流式转发：POST {base_url}/chat/completions（``stream=true`` 由调用方置入 payload）。

    返回 :class:`UpstreamStream`——状态码在返回时已知（headers 到达即返回，
    响应体尚未读），网关据此决定：BLOCK 之外的错误状态码透明传递 JSON；
    200 则把字节流交给 gateway/sse.py 组合管线（还原 + AI 标识）。
    连接失败（DNS/连接/超时）抛 :class:`UpstreamUnavailableError` → 502 信封。
    """
    client = httpx.AsyncClient(timeout=timeout_s)
    try:
        request = client.build_request("POST", chat_endpoint(upstream.base_url), json=payload,
                                       headers=_auth_headers(api_key))
        resp = await client.send(request, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        raise UpstreamUnavailableError(
            f"upstream {upstream.name} unreachable: {type(exc).__name__}") from exc
    except BaseException:
        await client.aclose()
        raise
    return UpstreamStream(upstream.name, client, resp)
