"""网关非流式主链路（T0.4）：detect → mask → route → 转发 → 还原 → audit v0。

请求处理顺序（开发指令 §3 数据流，v0 覆盖非流式）::

    1 auth(dept key，app 层) → 2 detect(recognizers.rule v0) → 3 mask(会话稳定占位符)
    → 4 route(routing.engine v0) → 5 转发(gateway.provider，非流式)
    → 6 还原(占位符→原值) → 7 audit(audit.store 内存版，零明文硬闸)

范围与取舍（v0，后续任务扩展时保持类与方法形状）：
- 仅非流式：``stream=true`` 明确报 400（流式链路任务接管 SSE 管线）；
- 多段 content：文本段逐段检测/脱敏后原位替换，非文本段（如图片引用）原样保留；
- 工具调用：响应 ``tool_calls[].function.arguments`` 做占位符串级还原
  （参数级 JSON 还原由脱敏任务补全）；
- 上游错误（非 2xx）透明传递上游协议错误体；网络层失败映射 502 错误信封。

审计红线：prompt/response 预览只存**占位符版本**（≤500 字符）；
入库前经 :func:`audit.store.assert_no_raw_pii` 硬闸，失败映射 500 且不落库。
"""
from __future__ import annotations

import os
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from audit.models import AuditEvent
from audit.store import InMemoryAuditStore
from common.config import AppConfig
from gateway.models import ApiError, ErrorBody
from gateway.provider import UpstreamUnavailableError, forward_chat
from masking.mapper import SessionRegistry
from recognizers.models import Finding
from recognizers.rule.detect import detect
from routing.engine import decide
from routing.models import RouteDecision

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


class ChatBodyError(ValueError):
    """请求体校验失败（映射 400 bad_request）。"""


@dataclass
class GatewayResult:
    """单次请求处理结果：HTTP 状态码 + 响应 JSON + 追加响应头。"""

    status_code: int
    payload: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


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


class GatewayService:
    """网关服务：持有配置、会话映射注册表与审计存储，处理 /v1/chat/completions 链路。"""

    def __init__(
        self,
        cfg: AppConfig,
        mask_key: str,
        *,
        audit_store: InMemoryAuditStore | None = None,
        session_capacity: int = 1024,
    ) -> None:
        self.cfg = cfg
        # 注意：InMemoryAuditStore 实现了 __len__，不能用 `or` 兜底（空表为 falsy 会被替换）
        self.audit = audit_store if audit_store is not None else InMemoryAuditStore()
        self.registry = SessionRegistry(mask_key.encode("utf-8"), capacity=session_capacity)
        self._upstreams_by_name = {u.name: u for u in cfg.upstreams}
        self._upstream_for: dict[str, str] = {}
        for upstream in cfg.upstreams:
            if upstream.route in ("INTERNET", "GOVCLOUD") and upstream.route not in self._upstream_for:
                self._upstream_for[upstream.route] = upstream.name

    # ── 主入口 ────────────────────────────────────────────────────
    async def handle_chat(
        self, body: Any, *, dept: str, session_id: str, request_id: str
    ) -> GatewayResult:
        started = time.perf_counter()
        self._validate_body(body)
        messages: list[dict[str, Any]] = body["messages"]

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

        def finish(status_code: int, payload: dict[str, Any], *, upstream_name: str | None,
                   response_preview: str, flags: list[str]) -> GatewayResult:
            """审计落账（零明文硬闸失败时 RawPiiLeakError 向上抛，映射 500）并组装结果。"""
            self._audit(
                request_id=request_id, session_id=session_id, dept=dept,
                decision=decision, findings=findings,
                prompt_preview=prompt_preview, response_preview=response_preview,
                upstream_name=upstream_name, latency_ms=int((time.perf_counter() - started) * 1000),
                flags=flags, normalized_values=sorted(used_values),
            )
            return GatewayResult(status_code, payload, headers)

        # ── BLOCK：拦截（403 语义），上游不感知 ──
        if decision.route == "BLOCK":
            payload = ApiError.content_blocked(BLOCK_MESSAGE, reasons=decision.reasons).model_dump()
            return finish(403, payload, upstream_name=None, response_preview="", flags=[])

        # 5) 转发（非流式）：按决策选择上游，模型缺省取该上游清单首项
        upstream = self._upstreams_by_name.get(decision.upstream or "")
        if upstream is None:
            return finish(
                500,
                _error_payload(CODE_INTERNAL_ERROR, f"route target misconfigured: {decision.upstream!r}"),
                upstream_name=None, response_preview="", flags=["route_misconfigured"],
            )

        out_payload = {k: v for k, v in body.items() if k not in ("messages", "stream")}
        out_payload["model"] = str(body.get("model") or (upstream.models[0] if upstream.models else "default"))
        out_payload["messages"] = [
            self._masked_message(message, masked_contents, msg_index)
            for msg_index, message in enumerate(messages)
        ]
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
        self._restore_choices(data, mapper)
        return finish(200, data, upstream_name=upstream.name,
                      response_preview=response_preview, flags=[])

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
        if body.get("stream") is True:
            raise ChatBodyError("streaming is not supported in this build; retry with stream=false")

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
