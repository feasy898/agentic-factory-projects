"""Mock 上游（本项目一等公民）：OpenAI 兼容的可控上游，供全链路无 key 验收。

能力（开发指令 §6 M1 mock_upstream 条目 + §9 e2e 步骤 1）：
- ``POST /v1/chat/completions``：非流式 + SSE 流式 + 工具调用；请求含 ``tools``
  （且 ``tool_choice != "none"``）时返回 tool_calls，``arguments`` 以
  ``{"query": <最后一条 user 消息>}`` 回显，供网关工具参数还原链路测试；
- 回显：把收到的最后一条 user 消息**原样**嵌入回答文本（前缀 :data:`ECHO_MARKER`
  + 实例名）。e2e 据此断言"客户端拿到还原答案"——上游回什么，网关就应还原什么；
- ring buffer：内存记录最近 N 条请求的完整文本（messages 全文 / 工具参数），
  经 ``GET /admin/records``、``GET /admin/text`` 暴露，e2e 据此断言
  "上游只收到占位符"；``POST /admin/reset`` 清空。缓冲只记 Authorization 是否
  存在，**不记录其值**（凭据不入日志红线）；
- 两实例：同一 app 不同 argv——``--port 8901``（互联网 mock）与 ``--port 8902``
  （政务云本地 mock）；8901/8902 端口隐含默认实例名与模型名（对齐 config/app.yaml）。

命令行启动（§9 步骤 1）::

    cd REPO_ROOT && PYTHONUTF8=1 ./.venv/Scripts/python.exe -m gateway.mock_upstream --port 8901
    cd REPO_ROOT && PYTHONUTF8=1 ./.venv/Scripts/python.exe -m gateway.mock_upstream --port 8902

进程内 fixture（evals / e2e 复用）::

    from gateway.mock_upstream import MockUpstreamServer
    with MockUpstreamServer(8901) as srv:            # 也支持 srv.ring 直接读缓冲
        httpx.post(f"{srv.base_url}/v1/chat/completions", json=payload)

自测（本模块的可执行验收）::

    cd REPO_ROOT && PYTHONUTF8=1 ./.venv/Scripts/python.exe -m evals.t0_mock_upstream   # exit 0 = 通过
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import threading
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from common.logs import get_logger, setup_logging

log = get_logger(__name__)

#: 回答文本的固定前缀（其后跟实例名换行 + 最后一条 user 消息原文）
ECHO_MARKER = "〔Mock上游回显〕"

#: 端口 → 默认（实例名, 模型名清单）；与 config/app.yaml 的 upstream 条目一致
DEFAULT_PORT_ROLES: dict[int, tuple[str, list[str]]] = {
    8901: ("internet_mock", ["mock-chat"]),
    8902: ("govcloud_local", ["gov-chat"]),
}


def _defaults_for_port(port: int) -> tuple[str, list[str]]:
    return DEFAULT_PORT_ROLES.get(port, ("mock", ["mock-chat"]))


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _content_text(content: Any) -> str:
    """消息 content 的文本化（str 原样；多段 list 取 text 部分拼接；其余 str()）。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for piece in content:
            if isinstance(piece, str):
                parts.append(piece)
            elif isinstance(piece, dict) and piece.get("type") == "text":
                parts.append(str(piece.get("text", "")))
        return "".join(parts)
    return str(content)


def _split_chunks(text: str, chunk_min: int, chunk_max: int) -> list[str]:
    """把文本切成 1..N 段，每段长度在 [chunk_min, chunk_max] 字符内随机。

    按字符切（真实上游不会发出非法 UTF-8 的半字节块），多字节中文因此天然
    参与切块压力——网关的流式还原必须容忍占位符被切进相邻两个 chunk。
    """
    lo = max(1, min(chunk_min, chunk_max))
    hi = max(lo, chunk_max)
    pieces: list[str] = []
    i = 0
    while i < len(text):
        n = random.randint(lo, hi)
        pieces.append(text[i : i + n])
        i += n
    return pieces


class RingBuffer:
    """线程安全的请求环形缓冲（e2e 断言"上游收到过什么"的唯一事实来源）。"""

    def __init__(self, maxlen: int = 200) -> None:
        self._lock = threading.Lock()
        self._items: deque[dict[str, Any]] = deque(maxlen=max(1, maxlen))
        self._seq = 0

    def add(self, record: dict[str, Any]) -> int:
        with self._lock:
            self._seq += 1
            item = {"seq": self._seq, **record}
            self._items.append(item)
            return self._seq

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._items]

    def texts(self) -> list[str]:
        """逐条拼接"收到的全文"，供 bytes 级断言（审查 §B：不看 messages 全文的
        断言是假绿——ring 里保存的 system/更早轮次必须参与）。

        每条请求产出：
        - ``messages`` 数组的 JSON 序列化全文（``ensure_ascii=False``——中文原样
          输出，bytes 级原值扫描才会真实命中）；
        - 有工具调用时追加 ``tool_arguments`` 原文。
        """
        out: list[str] = []
        for item in self.snapshot():
            out.append(json.dumps(item.get("messages", []), ensure_ascii=False,
                                  sort_keys=True))
            if item.get("tool_call"):
                out.append(str(item.get("tool_arguments", "")))
        return out

    def reset(self) -> int:
        with self._lock:
            cleared = len(self._items)
            self._items.clear()
            return cleared

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


def _openai_error(message: str, err_type: str = "invalid_request_error", status: int = 400) -> JSONResponse:
    """OpenAI 协议风格的错误信封（mock 是"上游"，不复用网关侧 §5.6 信封）。"""
    return JSONResponse(
        {"error": {"message": message, "type": err_type, "param": None, "code": None}},
        status_code=status,
    )


def create_app(
    *,
    name: str,
    models: list[str],
    ring_size: int = 200,
    chunk_min: int = 1,
    chunk_max: int = 7,
) -> FastAPI:
    """构造一个 mock 上游 app 实例（每次调用独立 ring buffer）。"""
    ring = RingBuffer(maxlen=ring_size)

    app = FastAPI(title="mock-upstream", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.ring = ring
    app.state.instance_name = name
    app.state.models = list(models)

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"ok": True, "instance": name, "models": list(models)}

    @app.get("/v1/models")
    async def list_models() -> dict[str, Any]:
        return {"object": "list", "data": [{"id": m, "object": "model", "owned_by": name} for m in models]}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 — 任何解析失败都归一为 400 错误信封
            return _openai_error("request body is not valid JSON")
        if not isinstance(body, dict):
            return _openai_error("request body must be a JSON object")
        raw_messages = body.get("messages")
        if not isinstance(raw_messages, list) or not raw_messages:
            return _openai_error("'messages' must be a non-empty array")

        messages: list[dict[str, str]] = []
        for msg in raw_messages:
            if not isinstance(msg, dict):
                return _openai_error("each message must be a JSON object")
            messages.append({"role": str(msg.get("role", "")), "content": _content_text(msg.get("content"))})
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), None)
        if last_user is None:
            last_user = messages[-1]["content"]

        tools = body.get("tools") if isinstance(body.get("tools"), list) else []
        tool_names = [
            str(t["function"].get("name", ""))
            for t in tools
            if isinstance(t, dict) and isinstance(t.get("function"), dict)
        ]
        use_tool = bool(tool_names) and body.get("tool_choice") != "none"
        tool_name = tool_names[0] if use_tool else ""
        tool_args = json.dumps({"query": last_user}, ensure_ascii=False) if use_tool else ""
        answer = "" if use_tool else f"{ECHO_MARKER}{name}\n{last_user}"

        ring.add({
            "ts": _utc_now_iso(),
            "instance": name,
            "model": str(body.get("model") or (models[0] if models else "mock-chat")),
            "stream": bool(body.get("stream")),
            "tools": tool_names,
            "tool_call": use_tool,
            "tool_name": tool_name,
            "tool_arguments": tool_args,
            "auth_header_present": "authorization" in request.headers,
            "messages": messages,
            "last_user_content": last_user,
            "peer": f"{request.client.host}:{request.client.port}" if request.client else "",
        })
        log.info("mock.chat.received", extra={
            "instance": name, "model": str(body.get("model") or ""), "stream": bool(body.get("stream")),
            "prompt_chars": len(last_user), "tool_call": use_tool, "n_messages": len(messages),
        })

        rid = "chatcmpl-" + uuid.uuid4().hex[:12]
        created = int(time.time())
        model = str(body.get("model") or (models[0] if models else "mock-chat"))
        headers = {"x-mock-instance": name, "cache-control": "no-store"}

        if body.get("stream"):
            gen = _stream_events(rid, created, model, answer, use_tool, tool_name, tool_args,
                                 chunk_min, chunk_max)
            return StreamingResponse(gen, media_type="text/event-stream", headers=headers)

        if use_tool:
            message: dict[str, Any] = {
                "role": "assistant", "content": None,
                "tool_calls": [{
                    "id": "call_" + uuid.uuid4().hex[:12], "type": "function",
                    "function": {"name": tool_name, "arguments": tool_args},
                }],
            }
            finish = "tool_calls"
            completion_tokens = len(tool_args)
        else:
            message = {"role": "assistant", "content": answer}
            finish = "stop"
            completion_tokens = len(answer)
        prompt_tokens = sum(len(m["content"]) for m in messages)
        payload = {
            "id": rid, "object": "chat.completion", "created": created, "model": model,
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }
        return JSONResponse(payload, headers=headers)

    @app.get("/admin/records")
    async def admin_records(limit: int = 0) -> dict[str, Any]:
        records = ring.snapshot()
        if limit > 0:
            records = records[-limit:]
        return {"instance": name, "count": len(records), "records": records}

    @app.get("/admin/text")
    async def admin_text() -> Response:
        return Response("\n".join(ring.texts()), media_type="text/plain; charset=utf-8")

    @app.post("/admin/reset")
    async def admin_reset() -> dict[str, Any]:
        return {"instance": name, "cleared": ring.reset()}

    return app


async def _stream_events(
    rid: str, created: int, model: str, answer: str,
    use_tool: bool, tool_name: str, tool_args: str,
    chunk_min: int, chunk_max: int,
) -> AsyncIterator[str]:
    """SSE 事件流：首块（role/tool_calls 声明）→ 内容/参数小切块 → finish → [DONE]。"""

    def sse(obj: dict[str, Any]) -> str:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    base = {"id": rid, "object": "chat.completion.chunk", "created": created, "model": model}
    if use_tool:
        first = {**base, "choices": [{
            "index": 0,
            "delta": {"role": "assistant", "content": None, "tool_calls": [{
                "index": 0, "id": "call_" + uuid.uuid4().hex[:12], "type": "function",
                "function": {"name": tool_name, "arguments": ""},
            }]},
            "finish_reason": None,
        }]}
    else:
        first = {**base, "choices": [{
            "index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None,
        }]}
    yield sse(first)

    pieces = _split_chunks(tool_args if use_tool else answer, chunk_min, chunk_max)
    for piece in pieces:
        if use_tool:
            delta: dict[str, Any] = {"tool_calls": [{"index": 0, "function": {"arguments": piece}}]}
        else:
            delta = {"content": piece}
        yield sse({**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]})
        await asyncio.sleep(0)

    yield sse({**base, "choices": [{
        "index": 0, "delta": {}, "finish_reason": "tool_calls" if use_tool else "stop",
    }]})
    yield "data: [DONE]\n\n"


class MockUpstreamServer:
    """进程内 mock 上游实例（uvicorn 后台线程），evals/e2e 的标准 fixture。

    用法::

        srv = MockUpstreamServer(8901).start()      # start(wait=True) 轮询 /healthz
        ...
        srv.stop()                                  # 优雅停线程并释放端口

    也支持 ``with MockUpstreamServer(8902) as srv:``；进程内可直接读 ``srv.ring``。
    """

    def __init__(
        self,
        port: int,
        *,
        name: str | None = None,
        models: list[str] | None = None,
        host: str = "127.0.0.1",
        ring_size: int = 200,
        chunk_min: int = 1,
        chunk_max: int = 7,
    ) -> None:
        def_name, def_models = _defaults_for_port(port)
        self.port = port
        self.host = host
        self.name = name or def_name
        self.models = models if models is not None else list(def_models)
        self.base_url = f"http://{host}:{port}"
        self.app = create_app(name=self.name, models=self.models, ring_size=ring_size,
                              chunk_min=chunk_min, chunk_max=chunk_max)
        self.ring: RingBuffer = self.app.state.ring
        self._server = uvicorn.Server(uvicorn.Config(
            self.app, host=host, port=port,
            log_level="warning", log_config=None, access_log=False,
        ))
        self._thread: threading.Thread | None = None

    def start(self, wait: bool = True, timeout: float = 10.0) -> MockUpstreamServer:
        self._thread = threading.Thread(
            target=self._server.run, name=f"mock-upstream-{self.port}", daemon=True,
        )
        self._thread.start()
        if wait:
            self.wait_ready(timeout)
        return self

    def wait_ready(self, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        last_exc: Exception | None = None
        while time.monotonic() < deadline:
            if self._thread is not None and not self._thread.is_alive():
                raise RuntimeError(f"mock upstream :{self.port} thread exited before ready")
            try:
                resp = httpx.get(f"{self.base_url}/healthz", timeout=1.0)
                if resp.status_code == 200 and resp.json().get("ok") is True:
                    return
            except Exception as exc:  # noqa: BLE001 — 启动窗口内连接失败属预期
                last_exc = exc
            time.sleep(0.1)
        raise RuntimeError(f"mock upstream :{self.port} not ready within {timeout}s (last: {last_exc})")

    def stop(self) -> None:
        self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._thread = None

    def __enter__(self) -> MockUpstreamServer:
        return self.start()

    def __exit__(self, *exc_info: object) -> None:
        self.stop()


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：``python -m gateway.mock_upstream --port 8901``（阻塞至 Ctrl+C）。"""
    parser = argparse.ArgumentParser(
        prog="gateway.mock_upstream",
        description="Mock 上游：OpenAI 兼容 /v1/chat/completions（回显 + ring buffer）",
    )
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, required=True, help="监听端口（8901 互联网 / 8902 政务云）")
    parser.add_argument("--name", default=None, help="实例名（缺省按端口隐含：8901=internet_mock, 8902=govcloud_local）")
    parser.add_argument("--models", default=None, help="逗号分隔的模型名（缺省按端口隐含）")
    parser.add_argument("--ring-size", type=int, default=200, help="ring buffer 容量（默认 200 条）")
    parser.add_argument("--chunk-min", type=int, default=1, help="流式单块最小字符数（默认 1）")
    parser.add_argument("--chunk-max", type=int, default=7, help="流式单块最大字符数（默认 7）")
    args = parser.parse_args(argv)

    def_name, def_models = _defaults_for_port(args.port)
    name = args.name or def_name
    models = (
        [m.strip() for m in args.models.split(",") if m.strip()]
        if args.models else list(def_models)
    )
    setup_logging("WARNING")
    app = create_app(name=name, models=models, ring_size=args.ring_size,
                     chunk_min=args.chunk_min, chunk_max=args.chunk_max)
    log.info("mock.upstream.start", extra={"instance": name, "host": args.host, "port": args.port, "models": models})
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
