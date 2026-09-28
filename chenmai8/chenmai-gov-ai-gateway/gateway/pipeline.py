"""网关主链路（T0.4 非流式 + T0.5 流式）：detect → mask → route → 转发 → 还原 → audit v0。

请求处理顺序（开发指令 §3 数据流）::

    1 auth(dept key，app 层) → 2 detect(recognizers.rule v0) → 3 mask(会话稳定占位符)
    → 4 route(routing.engine v0) → 5 转发(gateway.provider，非流式/流式两形态)
    → 6 还原(占位符→原值) → 7 audit(零明文硬闸；直构=内存表，app 默认=SQLite 写队列)

非流式与流式共用 :meth:`GatewayService._prepare`（detect+mask+route，纯前置）；
差异只在转发与还原形态：
- 非流式：整体 JSON 转发 → 整段正则还原（正文 + 工具参数串级）；
- 流式（§8.2）：``stream=true`` 打开上游 SSE，经 :mod:`gateway.sse` 组合管线
  逐块透传——文本增量过 :class:`masking.remap.StreamRestorer`（占位符跨 chunk
  缓冲还原）、工具参数 hold-to-finish、finish 时注入 AI 生成标识（§5.6 流式方式）。

范围与取舍（后续任务扩展时保持类与方法形状）：
- 多段 content：文本段逐段检测/脱敏后原位替换，非文本段（如图片引用）原样保留；
- BLOCK/上游不可达/上游协议错误在**开流前**决出，仍返回普通 JSON 信封；
  开流后（已 200）的中途断流只能以 SSE 错误事件收尾；
- 流式审计在流收尾时落账（response_preview 为**还原前**占位符版本）；
  零明文硬闸失败时事件不落库并大声记日志（流已 200，500 无法回传）。

审计红线：prompt/response 预览只存**占位符版本**（≤500 字符）；
入库前经 :func:`audit.store.assert_no_raw_pii` 硬闸。
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from audit.models import AuditEvent
from audit.store import AuditSink, InMemoryAuditStore, RawPiiLeakError
from common.config import AppConfig
from common.logs import get_logger
from gateway import sse
from gateway.models import ApiError, ErrorBody
from gateway.provider import (
    UpstreamStream,
    UpstreamUnavailableError,
    forward_chat,
    open_stream_chat,
)
from masking.mapper import SessionMapper, SessionRegistry
from recognizers.models import Finding
from recognizers.rule.detect import detect
from routing.engine import decide
from routing.models import RouteDecision

log = get_logger(__name__)

#: 错误信封 code 词表（§5.6：BLOCK 固定 content_blocked，其余复用同一信封）
CODE_BAD_REQUEST = "bad_request"
CODE_UNAUTHORIZED = "unauthorized"
CODE_PAYLOAD_TOO_LARGE = "payload_too_large"
CODE_INTERNAL_ERROR = "internal_error"
CODE_UPSTREAM_ERROR = "upstream_error"

#: 上游不可达时返回的 HTTP 状态码
STATUS_UPSTREAM_UNAVAILABLE = 502

#: BLOCK 拦截的固定提示文案（§5.6 错误语义；代答/拒答模板由输出侧任务接管）
BLOCK_MESSAGE = "涉密/涉敏内容已拦截，请通过保密渠道办理或删除敏感标识后重试"

#: AI 生成标识响应头（§6 M5：x-anongw-ai-label: 1；流式响应随 SSE 头下发）
HEADER_AI_LABEL = "x-anongw-ai-label"


class ChatBodyError(ValueError):
    """请求体校验失败（映射 400 bad_request）。"""


@dataclass
class GatewayResult:
    """非流式单次请求处理结果：HTTP 状态码 + 响应 JSON + 追加响应头。"""

    status_code: int
    payload: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class GatewayStreamResult:
    """流式请求处理结果：``events`` 非 None ⇒ 200 SSE 流；否则为普通 JSON 信封。"""

    status_code: int
    headers: dict[str, str] = field(default_factory=dict)
    payload: dict[str, Any] | None = None
    events: AsyncIterator[str] | None = None


@dataclass
class _Segment:
    """一段可检测文本：消息内定位 + 文本内容。"""

    msg_index: int
    piece_index: int          # list content 中的下标；str content 恒为 -1
    text: str


def _content_segments(content: Any, msg_index: int) -> list[_Segment]:
    """消息 content → 文本段列表（str 原样一段；list 取 str/text 段；其余无段）。"""
    if isinstance(content, str):
        return [_Segment(msg_index, -1, content)]
    if isinstance(content, list):
        segments: list[_Segment] = []
        for piece_index, piece in enumerate(content):
            if isinstance(piece, str):
                segments.append(_Segment(msg_index, piece_index, piece))
            elif isinstance(piece, dict) and piece.get("type") == "text":
                segments.append(_Segment(msg_index, piece_index, str(piece.get("text", ""))))
        return segments
    return []


def _error_payload(code: str, message: str,
                   reasons: list | None = None) -> dict[str, Any]:
    """§5.6 错误信封：``{"error": {"code","message","reasons"}}``。"""
    return {"error": ErrorBody(code=code, message=message, reasons=reasons or []).model_dump()}


@dataclass
class _Prepared:
    """非流式/流式共用的前置产物（detect+mask+route 一次完成）。"""

    findings: list[Finding]
    segments_by_message: dict[int, list[_Segment]]
    masked_contents: dict[tuple[int, int], str]
    prompt_preview: str
    mapper: SessionMapper
    decision: RouteDecision
    headers: dict[str, str]
    used_values: set[str]


class GatewayService:
    """网关服务：持有配置、会话映射注册表与审计存储，处理 /v1/chat/completions 链路。"""

    def __init__(
        self,
        cfg: AppConfig,
        mask_key: str,
        *,
        audit_store: AuditSink | None = None,
        registry: Any = None,
        session_capacity: int = 1024,
    ) -> None:
        self.cfg = cfg
        # 注意：审计/会话存储都可能实现 __len__，不能用 `or` 兜底（空表为 falsy 会被替换）。
        # audit_store：任何满足 AuditSink（append(event, normalized_values)）的写入口——
        # 缺省进程内表（直构形态）；生产经 create_app 注入 SQLite 写队列（audit/writer）。
        self.audit = audit_store if audit_store is not None else InMemoryAuditStore()
        # registry：SessionRegistry 或 SessionStore（.get(session_id) → SessionMapper）；
        # 缺省进程内 LRU（直构形态）。
        self.registry = (registry if registry is not None
                         else SessionRegistry(mask_key.encode("utf-8"), capacity=session_capacity))
        self._upstreams_by_name = {u.name: u for u in cfg.upstreams}
        self._upstream_for: dict[str, str] = {}
        for upstream in cfg.upstreams:
            if upstream.route in ("INTERNET", "GOVCLOUD") and upstream.route not in self._upstream_for:
                self._upstream_for[upstream.route] = upstream.name

    # ── 主入口：非流式 ────────────────────────────────────────────
    async def handle_chat(
        self, body: Any, *, dept: str, session_id: str, request_id: str
    ) -> GatewayResult:
        started = time.perf_counter()
        self._validate_body(body)
        prep = self._prepare(body["messages"], session_id=session_id, request_id=request_id)
        decision = prep.decision
        headers = prep.headers
        prompt_preview = prep.prompt_preview

        def finish(status_code: int, payload: dict[str, Any], *, upstream_name: str | None,
                   response_preview: str, flags: list[str]) -> GatewayResult:
            """审计落账（零明文硬闸失败时 RawPiiLeakError 向上抛，映射 500）并组装结果。"""
            self._audit(
                request_id=request_id, session_id=session_id, dept=dept,
                decision=decision, findings=prep.findings,
                prompt_preview=prompt_preview, response_preview=response_preview,
                upstream_name=upstream_name, latency_ms=int((time.perf_counter() - started) * 1000),
                flags=flags, normalized_values=sorted(prep.used_values),
            )
            return GatewayResult(status_code, payload, headers)

        # ── BLOCK：拦截（403 语义），上游不感知 ──
        if decision.route == "BLOCK":
            payload = ApiError.content_blocked(BLOCK_MESSAGE, reasons=decision.reasons).model_dump()
            return finish(403, payload, upstream_name=None, response_preview="", flags=[])

        upstream = self._resolve_upstream(decision)
        if upstream is None:
            return finish(
                500,
                _error_payload(CODE_INTERNAL_ERROR, f"route target misconfigured: {decision.upstream!r}"),
                upstream_name=None, response_preview="", flags=["route_misconfigured"],
            )

        out_payload = self._out_payload(body, prep, upstream, stream=False)
        api_key = os.environ.get(upstream.api_key_env) or None
        try:
            status, data = await forward_chat(upstream, out_payload, api_key=api_key)
        except UpstreamUnavailableError as exc:
            return finish(
                STATUS_UPSTREAM_UNAVAILABLE,
                _error_payload(CODE_UPSTREAM_ERROR, str(exc)),
                upstream_name=upstream.name, response_preview="", flags=["upstream_unavailable"],
            )
        if status != 200:
            # 上游协议错误体透明传递（含上游错误形状），网关不改写
            return finish(status, data, upstream_name=upstream.name,
                          response_preview="", flags=[f"upstream_status_{status}"])

        # 6) 还原：占位符 → 原值（正文 + 工具参数；预览保留占位符版本）
        response_preview = self._first_choice_content(data)
        self._restore_choices(data, prep.mapper)
        return finish(200, data, upstream_name=upstream.name,
                      response_preview=response_preview, flags=[])

    # ── 主入口：流式（T0.5）───────────────────────────────────────
    async def handle_chat_stream(
        self, body: Any, *, dept: str, session_id: str, request_id: str
    ) -> GatewayStreamResult:
        started = time.perf_counter()
        self._validate_body(body)
        prep = self._prepare(body["messages"], session_id=session_id, request_id=request_id)
        decision = prep.decision
        headers = prep.headers

        def finish(status_code: int, payload: dict[str, Any], *, upstream_name: str | None,
                   flags: list[str]) -> GatewayStreamResult:
            """开流前决出的终态（BLOCK/错误）：普通 JSON 信封，无 SSE。"""
            self._audit(
                request_id=request_id, session_id=session_id, dept=dept,
                decision=decision, findings=prep.findings,
                prompt_preview=prep.prompt_preview, response_preview="",
                upstream_name=upstream_name, latency_ms=int((time.perf_counter() - started) * 1000),
                flags=flags, normalized_values=sorted(prep.used_values),
            )
            return GatewayStreamResult(status_code=status_code, headers=headers, payload=payload)

        # ── BLOCK：拦截（403 语义），上游不感知；流式同样先拦再谈 ──
        if decision.route == "BLOCK":
            payload = ApiError.content_blocked(BLOCK_MESSAGE, reasons=decision.reasons).model_dump()
            return finish(403, payload, upstream_name=None, flags=[])

        upstream = self._resolve_upstream(decision)
        if upstream is None:
            return finish(
                500,
                _error_payload(CODE_INTERNAL_ERROR, f"route target misconfigured: {decision.upstream!r}"),
                upstream_name=None, flags=["route_misconfigured"],
            )

        out_payload = self._out_payload(body, prep, upstream, stream=True)
        api_key = os.environ.get(upstream.api_key_env) or None
        stream: UpstreamStream
        try:
            stream = await open_stream_chat(upstream, out_payload, api_key=api_key)
        except UpstreamUnavailableError as exc:
            return finish(
                STATUS_UPSTREAM_UNAVAILABLE,
                _error_payload(CODE_UPSTREAM_ERROR, str(exc)),
                upstream_name=upstream.name, flags=["upstream_unavailable"],
            )
        if stream.status_code != 200:
            # 上游协议错误体透明传递（body 已随 aread() 读尽、连接已释放）
            raw_body = await stream.aread()
            try:
                data = json.loads(raw_body)
            except ValueError:
                return finish(
                    STATUS_UPSTREAM_UNAVAILABLE,
                    _error_payload(CODE_UPSTREAM_ERROR, f"upstream {upstream.name} returned non-JSON body"),
                    upstream_name=upstream.name, flags=["upstream_non_json"],
                )
            if not isinstance(data, dict):
                return finish(
                    STATUS_UPSTREAM_UNAVAILABLE,
                    _error_payload(CODE_UPSTREAM_ERROR, f"upstream {upstream.name} returned non-object JSON"),
                    upstream_name=upstream.name, flags=["upstream_non_json"],
                )
            return finish(stream.status_code, data, upstream_name=upstream.name,
                          flags=[f"upstream_status_{stream.status_code}"])

        # 200：进入 SSE 组合管线（还原 + 工具 hold + AI 标识）；审计随流收尾落账
        ai_label = (self.cfg.ai_label or "").strip() or None
        if ai_label:
            headers = {**headers, HEADER_AI_LABEL: "1"}
        preview_parts: list[str] = []
        composed = sse.compose_chat_stream(
            stream.aiter(), mapper=prep.mapper, ai_label=ai_label,
            on_content=preview_parts.append,
        )

        async def guarded() -> AsyncIterator[str]:
            """组合管线 + 连接释放 + 中途断流 SSE 错误事件 + 流收尾审计。"""
            interrupted = False
            try:
                try:
                    async for text in composed:
                        yield text
                except (httpx.HTTPError, UpstreamUnavailableError) as exc:
                    interrupted = True
                    log.error("chat_stream.upstream_interrupted", extra={
                        "request_id": request_id, "exc_type": type(exc).__name__,
                    })
                    yield sse.format_sse(json.dumps({
                        "error": {"message": "upstream stream interrupted",
                                  "type": "upstream_error", "param": None, "code": None},
                    }, ensure_ascii=False))
                finally:
                    await stream.aclose()
            finally:
                # 流式审计：response_preview 取还原前占位符版本；硬闸失败=不落库
                try:
                    self._audit(
                        request_id=request_id, session_id=session_id, dept=dept,
                        decision=decision, findings=prep.findings,
                        prompt_preview=prep.prompt_preview,
                        response_preview="".join(preview_parts),
                        upstream_name=upstream.name,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        flags=(["upstream_stream_interrupted"] if interrupted else []),
                        normalized_values=sorted(prep.used_values),
                    )
                except RawPiiLeakError as exc:
                    log.error("audit.raw_pii_gate.tripped", extra={
                        "request_id": request_id, "kind": exc.kind,
                    })

        return GatewayStreamResult(status_code=200, headers=headers, payload=None, events=guarded())

    # ── 前置（detect + mask + route，非流式/流式共用）────────────
    def _prepare(self, messages: list[dict[str, Any]], *, session_id: str,
                 request_id: str) -> _Prepared:
        # 2) detect：逐消息逐段检测；fid 按 消息→段→span位置 顺序编放（请求内自增）
        findings: list[Finding] = []
        findings_by_segment: dict[tuple[int, int], list[Finding]] = {}
        segments_by_message: dict[int, list[_Segment]] = {}
        seq = 0
        for msg_index, message in enumerate(messages):
            segments = _content_segments(message.get("content"), msg_index)
            segments_by_message[msg_index] = segments
            for segment in segments:
                local: list[Finding] = []
                for found in detect(segment.text):
                    seq += 1
                    local.append(found.model_copy(update={"fid": f"f_{seq:04d}"}))
                findings_by_segment[(msg_index, segment.piece_index)] = local
                findings.extend(local)

        # 3) mask：会话稳定占位符（BLOCK_FLAG/白名单不参与替换）
        mapper = self.registry.get(session_id)
        masked_contents: dict[tuple[int, int], str] = {}
        used_values: set[str] = set()
        for msg_index, segments in segments_by_message.items():
            for segment in segments:
                spans = [
                    (f.start, f.end, f.type, f.normalized)
                    for f in findings_by_segment.get((msg_index, segment.piece_index), [])
                    if f.action_hint == "MASK" and not f.whitelisted
                ]
                masked_text, entries = mapper.mask(segment.text, spans)
                masked_contents[(msg_index, segment.piece_index)] = masked_text
                used_values.update(e.normalized for e in entries)

        # 4) route：决策矩阵纯函数（BLOCK > GOVCLOUD > INTERNET）
        decision = decide(
            findings,
            upstream_for=self._upstream_for,
            batch_pii_min=self.cfg.thresholds.batch_pii_to_govcloud,
        )
        headers = {
            "x-anongw-route": decision.route,
            "x-anongw-request-id": request_id,
            "x-anongw-session-id": session_id,
        }
        prompt_preview = self._prompt_preview(messages, segments_by_message, masked_contents)
        return _Prepared(
            findings=findings, segments_by_message=segments_by_message,
            masked_contents=masked_contents, prompt_preview=prompt_preview,
            mapper=mapper, decision=decision, headers=headers, used_values=used_values,
        )

    # ── 校验与组装 ────────────────────────────────────────────────
    @staticmethod
    def _validate_body(body: Any) -> None:
        if not isinstance(body, dict):
            raise ChatBodyError("request body must be a JSON object")
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ChatBodyError("'messages' must be a non-empty array")
        for message in messages:
            if not isinstance(message, dict):
                raise ChatBodyError("each message must be a JSON object")

    def _resolve_upstream(self, decision: RouteDecision):
        """RouteDecision.upstream → 上游配置；BLOCK/配置缺失返回 None。"""
        return self._upstreams_by_name.get(decision.upstream or "")

    def _out_payload(self, body: dict[str, Any], prep: _Prepared, upstream, *,
                     stream: bool) -> dict[str, Any]:
        """上游请求体：剥离 messages/stream 重建（模型缺省取该上游清单首项）。"""
        out_payload = {k: v for k, v in body.items() if k not in ("messages", "stream")}
        out_payload["model"] = str(body.get("model")
                                   or (upstream.models[0] if upstream.models else "default"))
        out_payload["messages"] = [
            self._masked_message(message, prep.masked_contents, msg_index)
            for msg_index, message in enumerate(body["messages"])
        ]
        if stream:
            out_payload["stream"] = True
        return out_payload

    @staticmethod
    def _masked_message(message: dict[str, Any], masked_contents: dict[tuple[int, int], str],
                        msg_index: int) -> dict[str, Any]:
        """用脱敏文本重建消息：str 整体替换；list 原位替换文本段；非文本 content 原样。"""
        content = message.get("content")
        if isinstance(content, str):
            masked = masked_contents.get((msg_index, -1), content)
            return {**message, "content": masked}
        if isinstance(content, list):
            pieces: list[Any] = []
            for piece_index, piece in enumerate(content):
                if isinstance(piece, str):
                    pieces.append(masked_contents.get((msg_index, piece_index), piece))
                elif isinstance(piece, dict) and piece.get("type") == "text":
                    text = str(piece.get("text", ""))
                    pieces.append({**piece, "text": masked_contents.get((msg_index, piece_index), text)})
                else:
                    pieces.append(piece)
            return {**message, "content": pieces}
        return dict(message)

    @staticmethod
    def _prompt_preview(messages: list[dict[str, Any]], segments_by_message: dict[int, list[_Segment]],
                        masked_contents: dict[tuple[int, int], str]) -> str:
        """审计预览：最后一条 user 消息的脱敏全文（无 user 消息则最后一条；≤500 由审计模型裁）。"""
        target = next((i for i in range(len(messages) - 1, -1, -1)
                       if str(messages[i].get("role", "")) == "user"), len(messages) - 1)
        segments = segments_by_message.get(target, [])
        return "\n".join(masked_contents.get((target, s.piece_index), s.text) for s in segments)

    @staticmethod
    def _first_choice_content(data: dict[str, Any]) -> str:
        """响应预览取数：首个 choice 的 message.content（占位符版本，还原前）。"""
        choices = data.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
        return ""

    @staticmethod
    def _restore_choices(data: dict[str, Any], mapper: Any) -> None:
        """原地还原响应中的占位符：choices[*].message.content 与 tool_calls 参数。"""
        choices = data.get("choices")
        if not isinstance(choices, list):
            return
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if not isinstance(message, dict):
                continue
            if isinstance(message.get("content"), str):
                message["content"] = mapper.restore(message["content"])
            tool_calls = message.get("tool_calls")
            if isinstance(tool_calls, list):
                for call in tool_calls:
                    if not isinstance(call, dict):
                        continue
                    fn = call.get("function")
                    if isinstance(fn, dict) and isinstance(fn.get("arguments"), str):
                        fn["arguments"] = mapper.restore(fn["arguments"])

    # ── 审计 ─────────────────────────────────────────────────────
    def _audit(self, *, request_id: str, session_id: str, dept: str,
               decision: RouteDecision, findings: list[Finding],
               prompt_preview: str, response_preview: str, upstream_name: str | None,
               latency_ms: int, flags: list[str], normalized_values: list[str]) -> AuditEvent:
        counts = Counter(f.type.value for f in findings if not f.whitelisted)
        event = AuditEvent(
            ts=datetime.now(UTC), request_id=request_id, session_id=session_id,
            dept=dept or "", route=decision.route, blocked=decision.route == "BLOCK",
            reasons=[r.code for r in decision.reasons], class_counts=dict(counts),
            prompt_preview=prompt_preview[:500], response_preview=response_preview[:500],
            upstream=upstream_name, latency_ms=max(0, latency_ms), flags=flags,
        )
        # 零明文硬闸：失败抛 RawPiiLeakError（app 层映射 500，事件不落库）
        return self.audit.append(event, normalized_values)
