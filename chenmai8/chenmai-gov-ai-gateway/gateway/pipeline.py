"""网关主链路（T0.4 非流式 + T0.5 流式）：detect → mask → route → 转发 → 还原 → outguard → audit。

请求处理顺序（开发指令 §3 数据流）::

    1 auth(dept key，app 层) → 2 detect(recognizers：规则层 + 语义层注入检测，
      :func:`recognizers.pipeline.detect_full`) → 3 mask(会话稳定占位符)
    → 4 route(routing.engine v0) → 5 转发(gateway.provider，非流式/流式两形态)
    → 6 还原(占位符→原值) → 7 outguard(输出侧：复检钩子 + AI 生成标识；BLOCK 时
      代答/拒答文案，outguard 包) → 8 audit(零明文硬闸；直构=内存表，app 默认=SQLite 写队列)

非流式与流式共用 :meth:`GatewayService._prepare`（detect+mask+route，纯前置）；
差异只在转发与还原形态：
- 非流式：整体 JSON 转发 → 整段正则还原（正文 + 工具参数串级）；
- 流式（§8.2）：``stream=true`` 打开上游 SSE，经 :mod:`gateway.sse` 组合管线
  逐块透传——文本增量过 :class:`masking.remap.StreamRestorer`（占位符跨 chunk
  缓冲还原）、工具参数 hold-to-finish、finish 时注入 AI 生成标识（§5.6 流式方式）。

范围与取舍（后续任务扩展时保持类与方法形状）：
- 出站**全量检测面**（审查 §A1/A4）：除消息 content 文本段外，``tools`` 定义、
  历史消息 ``tool_calls`` / ``function_call``、非 text 多模态段的字符串叶节点
  全部过 detect→mask；任一 BLOCK_FLAG 命中（含密级词藏在上述任意位置）整单拦截；
- 多段 content：文本段逐段检测/脱敏后原位替换，非文本段的字符串叶同样过检测面；
- BLOCK/上游不可达/上游协议错误在**开流前**决出，仍返回普通 JSON 信封；
  开流后（已 200）的中途断流只能以 SSE 错误事件收尾；
- 流式审计在流收尾时落账（response_preview 为**还原前**占位符版本）；
  零明文硬闸失败时事件不落库并大声记日志（流已 200，500 无法回传）。

审计红线：prompt/response 预览只存**占位符版本**（safe_preview 截断，≤500 字符；
截断点不切中敏感串）；密级词（BLOCK_FLAG 命中的表面形式）在预览中以
「〔密级·已拦截〕」占位——密级词属拦截语义、不进审计明文面；
入库前经 :func:`audit.store.assert_no_raw_pii` 硬闸（归一化值 + 表面形式同查）。
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
from audit.store import AuditSink, InMemoryAuditStore, RawPiiLeakError, safe_preview
from common.config import AppConfig
from common.logs import get_logger
from evals.thresholds import GATEWAY_TEXT_MAX_CHARS
from gateway import sse
from gateway.models import ApiError, ErrorBody
from gateway.provider import (
    UpstreamStream,
    UpstreamUnavailableError,
    forward_chat,
    open_stream_chat,
)
from masking.mapper import SessionMapper, SessionRegistry
from masking.toolbuf import restore_arguments
from outguard.fallback import DEFAULT_BLOCK_DEFAULT
from outguard.label import HEADER_AI_LABEL, apply_message_label
from outguard.models import ModerationVerdict
from outguard.service import OutguardService
from recognizers.models import EntityClass, Finding
from recognizers.pipeline import detect_full
from routing.engine import decide
from routing.models import RouteDecision, RouteReason

log = get_logger(__name__)

#: 错误信封 code 词表（§5.6：BLOCK 固定 content_blocked，其余复用同一信封）
CODE_BAD_REQUEST = "bad_request"
CODE_UNAUTHORIZED = "unauthorized"
CODE_PAYLOAD_TOO_LARGE = "payload_too_large"
CODE_INTERNAL_ERROR = "internal_error"
CODE_UPSTREAM_ERROR = "upstream_error"

#: 输出侧复检钩子命中（flagged）时的 reasons code 与审计 flag（outguard.moderation）
CODE_OUTPUT_MODERATION = "OUTPUT_MODERATION"
FLAG_OUTPUT_FLAGGED = "output_flagged"

#: 上游不可达时返回的 HTTP 状态码
STATUS_UPSTREAM_UNAVAILABLE = 502

#: §5.2 R2：INJECTION 决定性拦截的审计 flag（「记录 flag=injection」）
FLAG_INJECTION = "injection"

#: BLOCK 兜底拒答文案（兼容导出；运行时文案取 outguard 文案库——T2.2 起模板按
#: 决定性 reason code 回退、代答命中拼尾，见 outguard/fallback.py）
BLOCK_MESSAGE = DEFAULT_BLOCK_DEFAULT

# HEADER_AI_LABEL（§6 M5：x-anongw-ai-label: 1）自 outguard.label 导入使用。

#: 审计预览中密级词（BLOCK_FLAG 命中）的固定占位文案（拦截语义，不进明文面）
CLASSIFIED_REDACTED = "〔密级·已拦截〕"

#: 审计预览中注入指令（BLOCK_FLAG 命中）的固定占位文案（同上，按类型区分标注）
INJECTION_REDACTED = "〔注入·已拦截〕"


def _block_flags(decision: RouteDecision) -> list[str]:
    """BLOCK 审计 flags：决定性理由为 INJECTION 时记 ``flag=injection``（§5.2 R2）。"""
    if decision.reasons and decision.reasons[0].code == "INJECTION":
        return [FLAG_INJECTION]
    return []


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


def _iter_string_leaves(obj: Any):
    """递归产出 JSON 结构中的字符串叶节点；字符串值本身不再下探。"""
    if isinstance(obj, dict):
        for value in obj.values():
            if isinstance(value, str):
                yield value
            else:
                yield from _iter_string_leaves(value)
    elif isinstance(obj, list):
        for value in obj:
            if isinstance(value, str):
                yield value
            else:
                yield from _iter_string_leaves(value)


def _aux_texts(body: dict[str, Any]) -> list[str]:
    """出站**辅助检测面**的字符串全集（去重前）：

    - ``tools`` 定义（function.description / parameters 说明等全部字符串叶）；
    - 历史消息的 ``tool_calls``（含每条 function 的 name/arguments）与
      ``function_call``（legacy 形态）——PII/密级词常藏在历史参数里；
    - content 中**非 text** 多模态段的字符串叶（如 image_url 的 data URL、alt 文本）。

    content 的 str 段与 ``type=="text"`` 段由 :func:`_content_segments` 主面覆盖，
    不在此重复。
    """
    texts: list[str] = []
    tools = body.get("tools")
    if isinstance(tools, list):
        for tool in tools:
            texts.extend(_iter_string_leaves(tool))
    for message in body.get("messages") or []:
        if not isinstance(message, dict):
            continue
        for key in ("tool_calls", "function_call"):
            value = message.get(key)
            if isinstance(value, dict):
                texts.extend(_iter_string_leaves(value))
            elif isinstance(value, list):
                for call in value:
                    if isinstance(call, (dict, list)):
                        texts.extend(_iter_string_leaves(call))
        content = message.get("content")
        if isinstance(content, list):
            for piece in content:
                if isinstance(piece, str) or (isinstance(piece, dict) and piece.get("type") == "text"):
                    continue
                if isinstance(piece, (dict, list)):
                    texts.extend(_iter_string_leaves(piece))
    return texts


def _apply_aux_masked(obj: Any, masked: dict[str, str]) -> Any:
    """深拷贝式出站重建：dict/list 结构中的字符串叶按 ``原文 → 脱敏文`` 映射替换。

    映射中没有的字符串原样保留（与出站检测面同一全集，未映射即未检出）。
    """
    if isinstance(obj, str):
        return masked.get(obj, obj)
    if isinstance(obj, dict):
        return {k: _apply_aux_masked(v, masked) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_apply_aux_masked(v, masked) for v in obj]
    return obj


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
    aux_masked: dict[str, str]
    prompt_preview: str
    prompt_masked: str                       # 同 preview 但不做密级词占位（代答匹配输入）
    mapper: SessionMapper
    decision: RouteDecision
    headers: dict[str, str]
    used_values: set[str]
    used_surfaces: set[str]


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
        outguard: OutguardService | None = None,
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
        # outguard（T2.2 输出侧）：AI 标识 + 拦截文案库 + 复检钩子；
        # 缺省按 config 构造（文案库 config/outguard_texts.yaml，缺失回落内置默认）。
        self.outguard = outguard if outguard is not None else OutguardService.from_config(cfg)
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
        prep = self._prepare(body, session_id=session_id, request_id=request_id)
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
                flags=flags, normalized_values=sorted(prep.used_values | prep.used_surfaces),
            )
            return GatewayResult(status_code, payload, headers)

        # ── BLOCK：拦截（403 语义），上游不感知；文案=reason 模板+代答（outguard）──
        if decision.route == "BLOCK":
            payload = ApiError.content_blocked(
                self.outguard.block_reply(decision, prep.prompt_masked),
                reasons=decision.reasons,
            ).model_dump()
            return finish(403, payload, upstream_name=None, response_preview="",
                          flags=_block_flags(decision))

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

        # 6) 还原：占位符 → 原值（正文 + 工具参数；预览=占位符版本经检测+脱敏，
        #    见 _safe_response_preview——模型自由文本不得以原值/拦截词明文落审计）
        response_preview = self._safe_response_preview(
            self._first_choice_content(data), session_id)
        self._restore_choices(data, prep.mapper)

        # 7) 输出侧复检钩子（§6 M5 moderate(response)；P0 空后端恒 safe 零影响）：
        #    flagged → 按 content_blocked 拦截本次响应（上游已消费，审计如实记 flag）
        flagged = self._moderate_response(data)
        if flagged is not None:
            return finish(403, flagged, upstream_name=upstream.name,
                          response_preview=response_preview, flags=[FLAG_OUTPUT_FLAGGED])

        # 8) AI 生成标识（§5.6 非流式方式）：首 choice message 尾注 + annotations
        #    元数据 + 响应头；错误信封（上方各分支）不加——不是 AI 生成内容
        if self.outguard.ai_label:
            headers = {**headers, HEADER_AI_LABEL: "1"}
            self._apply_ai_label(data, self.outguard.ai_label)
        return finish(200, data, upstream_name=upstream.name,
                      response_preview=response_preview, flags=[])

    # ── 主入口：流式（T0.5）───────────────────────────────────────
    async def handle_chat_stream(
        self, body: Any, *, dept: str, session_id: str, request_id: str
    ) -> GatewayStreamResult:
        started = time.perf_counter()
        self._validate_body(body)
        prep = self._prepare(body, session_id=session_id, request_id=request_id)
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
                flags=flags, normalized_values=sorted(prep.used_values | prep.used_surfaces),
            )
            return GatewayStreamResult(status_code=status_code, headers=headers, payload=payload)

        # ── BLOCK：拦截（403 语义），上游不感知；流式同样先拦再谈；
        #    文案=reason 模板+代答（outguard），与非流式同源 ──
        if decision.route == "BLOCK":
            payload = ApiError.content_blocked(
                self.outguard.block_reply(decision, prep.prompt_masked),
                reasons=decision.reasons,
            ).model_dump()
            return finish(403, payload, upstream_name=None,
                          flags=_block_flags(decision))

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
        ai_label = self.outguard.ai_label or None
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
                # 流式审计：response_preview=占位符版本经检测+脱敏（同非流式口径，
                # 见 _safe_response_preview）；硬闸失败=不落库
                try:
                    self._audit(
                        request_id=request_id, session_id=session_id, dept=dept,
                        decision=decision, findings=prep.findings,
                        prompt_preview=prep.prompt_preview,
                        response_preview=self._safe_response_preview(
                            "".join(preview_parts), session_id),
                        upstream_name=upstream.name,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        flags=(["upstream_stream_interrupted"] if interrupted else []),
                        normalized_values=sorted(prep.used_values | prep.used_surfaces),
                    )
                except RawPiiLeakError as exc:
                    log.error("audit.raw_pii_gate.tripped", extra={
                        "request_id": request_id, "kind": exc.kind,
                    })

        return GatewayStreamResult(status_code=200, headers=headers, payload=None, events=guarded())

    # ── 前置（detect + mask + route，非流式/流式共用）────────────
    def _prepare(self, body: dict[str, Any], *, session_id: str,
                 request_id: str) -> _Prepared:
        messages = body.get("messages") or []
        # 2) detect：逐消息逐段检测（规则层 + 语义层注入检测全检测面）+ 出站辅助面
        #    （tools/历史 tool_calls/非 text 段）；fid 按 消息→段→span位置→辅助面 顺序编放
        #    （请求内自增）。语义层 INJECTION 命中（BLOCK_FLAG）同样从段/辅助面进 findings，
        #    经下方 decide R2 整单拦截（藏于工具描述的注入指令同权，§5.2）。
        findings: list[Finding] = []
        findings_by_segment: dict[tuple[int, int], list[Finding]] = {}
        segments_by_message: dict[int, list[_Segment]] = {}
        seq = 0
        for msg_index, message in enumerate(messages):
            segments = _content_segments(message.get("content"), msg_index)
            segments_by_message[msg_index] = segments
            for segment in segments:
                local: list[Finding] = []
                for found in detect_full(segment.text):
                    seq += 1
                    local.append(found.model_copy(update={"fid": f"f_{seq:04d}"}))
                findings_by_segment[(msg_index, segment.piece_index)] = local
                findings.extend(local)

        # 辅助检测面：同样字符串全量过全检测面（密级词/注入指令藏在 tools description /
        # 历史 tool_calls.arguments / 非 text 段也必须触发整单拦截，审查 §A4）。
        # 相同原文只检一次（fid 不重复、审计计数不翻倍）。
        aux_findings: dict[str, list[Finding]] = {}
        for text in _aux_texts(body):
            if text in aux_findings:
                continue
            local: list[Finding] = []
            for found in detect_full(text):
                seq += 1
                local.append(found.model_copy(update={"fid": f"f_{seq:04d}"}))
            aux_findings[text] = local
        findings.extend(f for local in aux_findings.values() for f in local)

        # 3) mask：会话稳定占位符（BLOCK_FLAG/白名单不参与替换）；辅助面同表映射
        mapper = self.registry.get(session_id)
        masked_contents: dict[tuple[int, int], str] = {}
        aux_masked: dict[str, str] = {}
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
        for text, local in aux_findings.items():
            spans = [
                (f.start, f.end, f.type, f.normalized) for f in local
                if f.action_hint == "MASK" and not f.whitelisted
            ]
            if not spans:
                continue
            masked_text, entries = mapper.mask(text, spans)
            if masked_text != text:
                aux_masked[text] = masked_text
            used_values.update(e.normalized for e in entries)

        # 硬闸断言清单：归一化值 + 表面形式同查（审查 §A2：分隔符写法不得绕闸；
        # BLOCK_FLAG 的表面形式（密级词）也在清单——预览中已占位，不得再出现原词）
        used_surfaces = {
            f.raw for f in findings
            if not f.whitelisted and f.action_hint in ("MASK", "BLOCK_FLAG") and f.raw
        }

        # 4) route：决策矩阵纯函数（BLOCK > GOVCLOUD > INTERNET；辅助面命中同权）
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
        prompt_preview = self._last_user_text(messages, segments_by_message,
                                              masked_contents, findings_by_segment,
                                              redact_block_flags=True)
        # 代答匹配输入（outguard.block_reply）：同源但**不**做密级词占位——
        # 密级词正属代答语义（涉密咨询），占位后关键词就匹配不上了；
        # 该文本只做匹配、不回显不入库（403 message 是 YAML 固定文案）。
        prompt_masked = self._last_user_text(messages, segments_by_message,
                                             masked_contents, findings_by_segment,
                                             redact_block_flags=False)
        return _Prepared(
            findings=findings, segments_by_message=segments_by_message,
            masked_contents=masked_contents, aux_masked=aux_masked,
            prompt_preview=prompt_preview, prompt_masked=prompt_masked,
            mapper=mapper, decision=decision, headers=headers,
            used_values=used_values, used_surfaces=used_surfaces,
        )

    # ── 校验与组装 ────────────────────────────────────────────────
    @staticmethod
    def _validate_body(body: Any) -> None:
        if not isinstance(body, dict):
            raise ChatBodyError("request body must be a JSON object")
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ChatBodyError("'messages' must be a non-empty array")
        for index, message in enumerate(messages):
            if not isinstance(message, dict):
                raise ChatBodyError("each message must be a JSON object")
            # 单条文本段长度上限（畸形输入加固 T7.2：超长单行 400，不进检测面
            # 拖垮延迟预算；识别/脱敏契约以有限文本为前提，阈值见 evals/thresholds.py）
            for segment in _content_segments(message.get("content"), index):
                if len(segment.text) > GATEWAY_TEXT_MAX_CHARS:
                    raise ChatBodyError(
                        f"message text too long: {len(segment.text)} chars "
                        f"(limit {GATEWAY_TEXT_MAX_CHARS})")
        for text in _aux_texts(body):
            if len(text) > GATEWAY_TEXT_MAX_CHARS:
                raise ChatBodyError(
                    f"tools/history text too long: {len(text)} chars "
                    f"(limit {GATEWAY_TEXT_MAX_CHARS})")

    def _resolve_upstream(self, decision: RouteDecision):
        """RouteDecision.upstream → 上游配置；BLOCK/配置缺失返回 None。"""
        return self._upstreams_by_name.get(decision.upstream or "")

    def _out_payload(self, body: dict[str, Any], prep: _Prepared, upstream, *,
                     stream: bool) -> dict[str, Any]:
        """上游请求体：剥离 messages/stream 重建（模型缺省取该上游清单首项）。

        ``tools`` 等顶层字段经 :func:`_apply_aux_masked` 重建（深拷贝，不改写
        请求体原对象）——其字符串叶已在 :meth:`_prepare` 过检测面并拿到脱敏版。
        """
        out_payload = {
            k: (_apply_aux_masked(v, prep.aux_masked) if isinstance(v, (dict, list)) else v)
            for k, v in body.items() if k not in ("messages", "stream")
        }
        out_payload["model"] = str(body.get("model")
                                   or (upstream.models[0] if upstream.models else "default"))
        out_payload["messages"] = [
            self._masked_message(message, prep.masked_contents, prep.aux_masked, msg_index)
            for msg_index, message in enumerate(body["messages"])
        ]
        if stream:
            out_payload["stream"] = True
        return out_payload

    @staticmethod
    def _masked_message(message: dict[str, Any], masked_contents: dict[tuple[int, int], str],
                        aux_masked: dict[str, str], msg_index: int) -> dict[str, Any]:
        """用脱敏文本重建消息：str 整体替换；list 原位替换文本段。

        非 text 多模态段、历史 ``tool_calls`` / ``function_call`` 的字符串叶
        （arguments/name 等）经 ``aux_masked`` 映射替换——这些位置不再原样透传
        （审查 §A1/A4：出站全量检测面）。
        """
        out = {**message}
        content = message.get("content")
        if isinstance(content, str):
            out["content"] = masked_contents.get((msg_index, -1), content)
        elif isinstance(content, list):
            pieces: list[Any] = []
            for piece_index, piece in enumerate(content):
                if isinstance(piece, str):
                    pieces.append(masked_contents.get((msg_index, piece_index), piece))
                elif isinstance(piece, dict) and piece.get("type") == "text":
                    text = str(piece.get("text", ""))
                    pieces.append({**piece, "text": masked_contents.get((msg_index, piece_index), text)})
                elif isinstance(piece, (dict, list)):
                    pieces.append(_apply_aux_masked(piece, aux_masked))
                else:
                    pieces.append(piece)
            out["content"] = pieces
        if isinstance(out.get("tool_calls"), list):
            out["tool_calls"] = [_apply_aux_masked(call, aux_masked) for call in out["tool_calls"]]
        if isinstance(out.get("function_call"), (dict, list)):
            out["function_call"] = _apply_aux_masked(out["function_call"], aux_masked)
        return out

    @staticmethod
    def _last_user_text(messages: list[dict[str, Any]], segments_by_message: dict[int, list[_Segment]],
                        masked_contents: dict[tuple[int, int], str],
                        findings_by_segment: dict[tuple[int, int], list[Finding]],
                        *, redact_block_flags: bool) -> str:
        """最后一条 user 消息的脱敏全文（无 user 消息则最后一条；≤500 由审计侧裁）。

        ``redact_block_flags=True``（审计预览口径）：密级词（BLOCK_FLAG 命中）以
        :data:`CLASSIFIED_REDACTED` 占位——拦截语义的表面形式不进审计明文面
        （审查 §B：U5 黑名单含密级词）。``False``（代答匹配口径）保留占位后的
        原字面（密级词不脱敏、不外发，仅用于 outguard 关键词匹配）。
        """
        target = next((i for i in range(len(messages) - 1, -1, -1)
                       if str(messages[i].get("role", "")) == "user"), len(messages) - 1)
        parts: list[str] = []
        for segment in segments_by_message.get(target, []):
            text = masked_contents.get((target, segment.piece_index), segment.text)
            if redact_block_flags:
                for f in findings_by_segment.get((target, segment.piece_index), []):
                    if f.action_hint == "BLOCK_FLAG" and f.raw:
                        marker = (INJECTION_REDACTED if f.type is EntityClass.INJECTION
                                  else CLASSIFIED_REDACTED)
                        text = text.replace(f.raw, marker)
            parts.append(text)
        return "\n".join(parts)

    def _safe_response_preview(self, text: str, session_id: str) -> str:
        """审计 response_preview（§5.4「已还原后仅含占位符版本」的执行面）。

        上游答案的占位符版本原样保留（回显占位符仍是占位符），再走与 prompt
        预览同源的处理：①规则层检测 + 会话稳定占位符——真实大模型的自由文本
        自发写出的结构化 PII（如示例手机号 138…、编造身份证）不得以明文进审计
        库（bytes 级零明文红线对真实模型面同样成立，T8.3 收官批实锤：U8 腿
        模型答案写出示例值 → 全库扫描命中 → RawPiiLeakError）；②密级词/注入
        词（BLOCK_FLAG 表面形式）以 CLASSIFIED/INJECTION_REDACTED 占位——拦截
        语义的表面形式与 prompt 预览同口径不进审计明文面。人名等 NER 层实体
        规则层不可见，属 open-vocabulary 残余，由 U8 的命中宿主裁定兜底
        （e2e_smoke._u8_adjudicated_db_scan）。
        """
        if not text:
            return ""
        findings = detect_full(text)
        spans = [(f.start, f.end, f.type, f.normalized) for f in findings
                 if f.action_hint == "MASK" and not f.whitelisted]
        masked, _entries = self.registry.get(session_id).mask(text, spans)
        for f in findings:
            if f.action_hint == "BLOCK_FLAG" and f.raw:
                marker = (INJECTION_REDACTED if f.type is EntityClass.INJECTION
                          else CLASSIFIED_REDACTED)
                masked = masked.replace(f.raw, marker)
        return masked

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
                        # 非流式直接整体还原（§6 M3 工具条目；实现归 masking.toolbuf）
                        fn["arguments"] = restore_arguments(mapper, fn["arguments"])

    # ── 输出侧（T2.2 outguard）：复检钩子 + AI 标识 ──────────────
    def _moderate_response(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """输出侧复检钩子（§6 M5 moderate(response)）：flagged → content_blocked 信封。

        复检对象：还原后的首 choice 正文（P0 空后端恒 safe；P1 语义审核模型
        采样执行，注入 OutguardService.moderator 即生效，此处接线不再变更）。
        ``flagged`` → 403 信封 reasons code=OUTPUT_MODERATION（detail 带风险类目），
        message 取文案库 OUTPUT_MODERATION 模板；无正文（纯工具调用响应）不复检。
        """
        content = self._first_choice_content(data)
        if not content:
            return None
        verdict: ModerationVerdict = self.outguard.moderate(content)
        if verdict.verdict != "flagged":
            return None
        detail = "输出侧复检命中：" + ("、".join(verdict.categories)
                                       if verdict.categories else (verdict.detail or "flagged"))
        reason = RouteReason(code=CODE_OUTPUT_MODERATION, detail=detail)
        decision = RouteDecision(route="BLOCK", reasons=[reason])
        return ApiError.content_blocked(
            self.outguard.block_reply(decision), reasons=[reason],
        ).model_dump()

    @staticmethod
    def _apply_ai_label(data: dict[str, Any], label: str) -> None:
        """AI 生成标识（§5.6 非流式方式，原地改写）：首 choice message 尾注 + annotations。"""
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            return
        message = choices[0].get("message")
        if isinstance(message, dict):
            apply_message_label(message, label)

    # ── 审计 ─────────────────────────────────────────────────────
    def _audit(self, *, request_id: str, session_id: str, dept: str,
               decision: RouteDecision, findings: list[Finding],
               prompt_preview: str, response_preview: str, upstream_name: str | None,
               latency_ms: int, flags: list[str], normalized_values: list[str]) -> AuditEvent:
        counts = Counter(f.type.value for f in findings if not f.whitelisted)
        # safe_preview：截断点不切中敏感串（normalized_values 已含表面形式，§A2）
        event = AuditEvent(
            ts=datetime.now(UTC), request_id=request_id, session_id=session_id,
            dept=dept or "", route=decision.route, blocked=decision.route == "BLOCK",
            reasons=[r.code for r in decision.reasons], class_counts=dict(counts),
            prompt_preview=safe_preview(prompt_preview, normalized_values),
            response_preview=safe_preview(response_preview, normalized_values),
            upstream=upstream_name, latency_ms=max(0, latency_ms), flags=flags,
        )
        # 零明文硬闸：失败抛 RawPiiLeakError（app 层映射 500，事件不落库）
        return self.audit.append(event, normalized_values)
