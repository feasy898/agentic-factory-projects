"""SSE 流式管线（开发指令 §8.2）：上游 chunk 字节流 → 还原 → AI 标识 → 客户端 SSE。

三段组合（async generator 管线，逐层可独立测试）：
1. :func:`iter_sse_data_lines` —— 字节流 → 事件 ``data:`` 载荷。按 ``\\n`` 切行并
   **跨 chunk 缓冲半行**（上游任意字节切块——含把多字节 UTF-8 切成两半——都不破行）；
   同一事件的多行 ``data:`` 按空行组帧、用换行拼接（SSE 规范）；
2. :class:`masking.toolbuf.ToolCallBuffer` —— 流式工具调用参数**增量累积，
   finish 前不发**；finish 时整体还原后作为单个 delta 发出（§6 M3 工具条目；
   T2.3 起实现归属 masking 包「工具还原」，本模块只做管线编排）；
3. :func:`compose_chat_stream` —— 主组合：逐事件透传 + 文本增量过
   :class:`masking.remap.StreamRestorer` + finish 时注入 AI 生成标识
   （文本尾注 delta + 元数据 ``annotations`` 字段，§5.6 流式注入方式）。

契约对齐（§5.6）：
- 流式 AI 标识 = 最后一个内容 delta 尾部标识行（实现：finish 前注入一个
  只含尾注的 content delta，客户端拼接视角即"最后一个 delta 尾部"）；
  元数据字段 ``annotations``（``[{"type": "ai_generated", "text": <文案>}]``）
  加在 finish chunk 的 ``choices[0].delta`` 上——与非流式
  ``choices[0].message.annotations`` 同名同形（字段只增不改名）；
- ``[DONE]`` 哨兵与事件帧格式原样透传；非 JSON 载荷原样透传（不吞不猜）。
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable

from common.logs import get_logger
from masking.mapper import SessionMapper
from masking.remap import StreamRestorer
from masking.toolbuf import ToolCallBuffer

log = get_logger(__name__)

#: SSE 结束哨兵（OpenAI 协议）
SSE_DONE = "[DONE]"

#: AI 生成标识的注解类型与元数据字段名（§5.6 annotations 字段；字段只增不改名）
AI_ANNOTATION_TYPE = "ai_generated"
ANNOTATIONS_FIELD = "annotations"

#: ``data:`` 行前缀（SSE 规范，冒号后可有可无一个空格）
_DATA_PREFIX = "data:"


def ai_label_tail(label: str) -> str:
    """标识行文本（作为内容尾部一行注入；含前导换行）。"""
    return "\n" + label


def ai_annotations(label: str) -> list[dict[str, str]]:
    """AI 标识元数据字段值（与非流式 annotations 字段同形）。"""
    return [{"type": AI_ANNOTATION_TYPE, "text": label}]


def format_sse(payload_json: str) -> str:
    """单条 SSE 事件帧（``data: <json>\\n\\n``）。"""
    return f"data: {payload_json}\n\n"


async def iter_sse_data_lines(chunks: AsyncIterator[bytes]) -> AsyncIterator[str]:
    """上游字节流 → SSE 事件 ``data:`` 载荷序列（按空行组帧；半行跨 chunk 缓冲；UTF-8 安全）。

    - 按 ``\\n`` 切行，行尾 ``\\r`` 去除（SSE 规范允许 CRLF）；行是完整字节序列后才
      decode，多字节字符被切成两半不会产生乱码（UTF-8 续字节不含 0x0A）；
    - **按空行组帧**（SSE 规范，审查 §A3）：同一事件内的连续多行 ``data:``（中间
      无空行）用 ``\\n`` 拼成一条载荷后一次产出——多行 data 拆写的 JSON 不会再因
      逐行解析失败而原样透传绕过还原管线；单行 ``data:`` 事件行为与逐行解析完全
      兼容；
    - ``data:`` 以外的事件字段/注释行跳过；空行 = 事件边界；流结束时未遇空行的
      残留 ``data:`` 行按一个事件产出。
    """
    buffer = b""
    data_lines: list[str] = []

    def flush_event() -> str | None:
        if not data_lines:
            return None
        payload = "\n".join(data_lines)
        data_lines.clear()
        return payload

    async for chunk in chunks:
        if not chunk:
            continue
        buffer += chunk
        while True:
            nl = buffer.find(b"\n")
            if nl < 0:
                break
            line, buffer = buffer[:nl], buffer[nl + 1:]
            if line.rstrip(b"\r") == b"":  # 空行 = 事件边界（CRLF 兼容）
                event = flush_event()
                if event is not None:
                    yield event
                continue
            payload = _data_payload(line)
            if payload is not None:
                data_lines.append(payload)
    if buffer:  # 流结束残留半行按一行处理
        payload = _data_payload(buffer)
        if payload is not None:
            data_lines.append(payload)
    event = flush_event()
    if event is not None:
        yield event


def _data_payload(raw_line: bytes) -> str | None:
    """一行字节 → ``data:`` 载荷文本；非 data 行返回 None。"""
    try:
        line = raw_line.decode("utf-8").rstrip("\r")
    except UnicodeDecodeError:
        log.warning("sse.undecodable_line_dropped", extra={"bytes": len(raw_line)})
        return None
    if not line.startswith(_DATA_PREFIX):
        return None
    payload = line[len(_DATA_PREFIX):]
    if payload.startswith(" "):
        payload = payload[1:]
    return payload


class StreamToolBuffer(ToolCallBuffer):
    """兼容别名：流式工具参数缓冲还原的实现已下沉 masking 包（masking.toolbuf）。

    保留导出名以免破坏既有引用；新代码请直接用 :class:`masking.toolbuf.ToolCallBuffer`。
    """


async def compose_chat_stream(
    chunks: AsyncIterator[bytes],
    *,
    mapper: SessionMapper,
    ai_label: str | None,
    on_content: Callable[[str], None] | None = None,
) -> AsyncIterator[str]:
    """主组合管线：上游字节流 → 网关 SSE 文本流（还原 + 工具 hold + AI 标识）。

    - 内容增量：过 :class:`StreamRestorer` 后放行；``on_content`` 在还原**前**
      收到上游原始内容（审计 response_preview 取占位符版本用）；
    - 工具增量：全部缓冲，finish 时整体还原为单个 delta；
    - finish chunk：**先 feed 本块**（正文尾片/参数尾片先进状态机与缓冲），再补发
      还原尾（restorer flush）、工具 delta、AI 标识内容 delta，最后给 finish chunk
      的首个 choice delta 加 ``annotations`` 元数据后放行；
    - 若上游未发 finish chunk 就 ``[DONE]``，在 [DONE] 前执行同一收尾序列；
    - 非法 JSON / 非 dict 载荷：原样透传（网关不吞不猜）。
    """
    restorer = StreamRestorer(mapper.lookup)
    tools = StreamToolBuffer()
    state = {"finished": False, "content_seen": False, "stop_seen": False}

    def finish_reason_of(event: dict) -> str | None:
        choices = event.get("choices")
        if not isinstance(choices, list):
            return None
        for choice in choices:
            if isinstance(choice, dict) and choice.get("finish_reason") is not None:
                return str(choice.get("finish_reason"))
        return None

    def finalize(reason: str | None) -> list[str]:
        """收尾序列（幂等）：还原尾 → 工具整发 → AI 标识尾注。"""
        if state["finished"]:
            return []
        state["finished"] = True
        out: list[str] = []
        tail = restorer.flush()
        if tail:
            out.append(format_sse(json.dumps(
                {"choices": [{"index": 0, "delta": {"content": tail}, "finish_reason": None}]},
                ensure_ascii=False)))
        for call in tools.finalize(mapper):
            out.append(format_sse(json.dumps(
                {"choices": [{"index": 0, "delta": {"tool_calls": [call]}, "finish_reason": None}]},
                ensure_ascii=False)))
        if ai_label and (state["content_seen"] or reason == "stop"):
            out.append(format_sse(json.dumps(
                {"choices": [{"index": 0, "delta": {"content": ai_label_tail(ai_label)},
                              "finish_reason": None}]},
                ensure_ascii=False)))
        return out

    def transform(event: dict, reason: str | None) -> dict:
        """单事件改写：内容增量还原 / 工具增量缓冲 / finish chunk 加 annotations。"""
        choices = event.get("choices")
        if not isinstance(choices, list):
            return event
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                continue
            content = delta.get("content")
            if isinstance(content, str) and content:
                if on_content is not None:
                    on_content(content)
                state["content_seen"] = True
                delta["content"] = restorer.feed(content)
            tool_calls = delta.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                tools.feed(tool_calls)
                del delta["tool_calls"]
            if reason is not None and choice.get("finish_reason") is not None:
                if ai_label and ANNOTATIONS_FIELD not in delta:
                    delta[ANNOTATIONS_FIELD] = ai_annotations(ai_label)
        return event

    async for payload in iter_sse_data_lines(chunks):
        if payload.strip() == SSE_DONE:
            for text in finalize(state["stop_seen"] or None):
                yield text
            yield f"data: {SSE_DONE}\n\n"
            return
        try:
            event = json.loads(payload)
        except ValueError:
            yield format_sse(payload)  # 非 JSON 载荷原样透传
            continue
        if not isinstance(event, dict):
            yield format_sse(payload)
            continue
        reason = finish_reason_of(event)
        if reason == "stop":
            state["stop_seen"] = True
        # 先 feed 本块（finish chunk 可能自带正文尾片/参数尾片——审查 §A3：顺序反了
        # 会把占位符前缀当普通文本吐出、参数尾片被删且不再发出），后 flush 收尾。
        transformed = transform(event, reason)
        if reason is not None:  # 仅 finish chunk 触发收尾（finalize 自身幂等）
            for text in finalize(reason):
                yield text
        yield format_sse(json.dumps(transformed, ensure_ascii=False))

    # 上游未发 [DONE] 即断流：补收尾（不让缓冲内容无声丢失）
    for text in finalize(None):
        yield text
