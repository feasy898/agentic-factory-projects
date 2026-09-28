"""网关 FastAPI 应用（骨架 v0）：/v1/chat/completions 非流式 + 调试/健康端点。

端点（§5.6，v0 实装子集；文件/管理面端点由对应任务补全）::

    POST /v1/chat/completions   OpenAI 兼容非流式；鉴权 Authorization: Bearer <dept_key>；
                                响应附 x-anongw-route / x-anongw-request-id / x-anongw-session-id
    GET  /v1/models             路由目标清单（脱敏视图，仅名字）
    POST /internal/detect       {text} → findings（调试）
    POST /internal/anonymize    {text, session_id} → 占位符版本（调试/演示对比屏）
    POST /internal/restore      {text, session_id} → 还原版本（调试/演示对比屏）
    GET  /healthz               存活

请求体上限：Content-Length > 网关上限即 413（畸形输入用例由 e2e 任务补全）。
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from audit.store import InMemoryAuditStore, RawPiiLeakError
from common.config import (
    AppConfig,
    load_app_config,
    load_dept_keys,
    resolve_secret,
)
from common.logs import get_logger
from evals.thresholds import GATEWAY_BODY_MAX_BYTES
from gateway import deps
from gateway.models import ApiError, ErrorBody
from gateway.pipeline import (
    CODE_BAD_REQUEST,
    CODE_INTERNAL_ERROR,
    CODE_PAYLOAD_TOO_LARGE,
    CODE_UNAUTHORIZED,
    ChatBodyError,
    GatewayService,
)
from recognizers.rule.detect import detect

log = get_logger(__name__)


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(ApiError(error=ErrorBody(code=code, message=message)).model_dump(),
                        status_code=status_code)


def create_app(
    *,
    cfg: AppConfig | None = None,
    mask_key: str | None = None,
    dept_key_digests: dict[str, str] | None = None,
    audit_store: InMemoryAuditStore | None = None,
) -> FastAPI:
    """构造网关应用。生产入口不传参（读 config/ 与环境）；测试可全量注入。"""
    cfg = cfg or load_app_config()
    if mask_key is None:
        resolved = resolve_secret(cfg.mask_key_env, required=False)
        if not resolved:
            raise RuntimeError(f"missing required secret env: {cfg.mask_key_env}")
        mask_key = resolved
    digests = dept_key_digests if dept_key_digests is not None else load_dept_keys()
    service = GatewayService(cfg, mask_key, audit_store=audit_store)

    app = FastAPI(title="gov-anon-gateway", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.service = service
    app.state.cfg = cfg
    app.state.dept_key_digests = digests

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"ok": True, "service": "gov-anon-gateway"}

    @app.get("/v1/models")
    async def list_models() -> dict[str, Any]:
        """路由目标清单（脱敏视图，仅名字：模型 id + 上游名 + 路由面）。"""
        data = [
            {"id": model, "object": "model", "owned_by": upstream.name, "route": upstream.route}
            for upstream in cfg.upstreams
            for model in upstream.models
        ]
        return {"object": "list", "data": data}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> JSONResponse:
        # 1) auth：部门 Key 常量时间比较（§5.6 Bearer 形态）
        dept = deps.authenticate(
            deps.extract_bearer(request.headers.get("authorization")), digests,
        )
        if dept is None:
            return _error_response(401, CODE_UNAUTHORIZED, "无效部门 Key（Authorization: Bearer dk_***）")

        # 2) 请求体上限（畸形输入完整防护由 e2e 任务补全）
        try:
            content_length = int(request.headers.get("content-length", "0") or "0")
        except ValueError:
            content_length = 0
        if content_length > GATEWAY_BODY_MAX_BYTES:
            return _error_response(413, CODE_PAYLOAD_TOO_LARGE, "请求体超过网关上限")

        # 3) 解析 body
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 — 任何解析失败都归一为 400 错误信封
            return _error_response(400, CODE_BAD_REQUEST, "request body is not valid JSON")

        # 4) 标识：session 可由客户端携带（多轮稳定脱敏），request 每请求新生成
        session_id = request.headers.get("x-anongw-session-id") or deps.new_session_id()
        request_id = deps.new_request_id()

        # 5) 主链路
        try:
            result = await service.handle_chat(body, dept=dept, session_id=session_id,
                                               request_id=request_id)
        except ChatBodyError as exc:
            return _error_response(400, CODE_BAD_REQUEST, str(exc))
        except RawPiiLeakError as exc:
            log.error("audit.raw_pii_gate.tripped", extra={"request_id": request_id, "kind": exc.kind})
            return _error_response(500, CODE_INTERNAL_ERROR, "审计零明文断言失败，事件未落库")
        except Exception as exc:  # noqa: BLE001 — 兜底为 500 错误信封（不泄漏内部细节）
            log.error("chat.unhandled_error", extra={
                "request_id": request_id, "exc_type": type(exc).__name__,
            })
            return _error_response(500, CODE_INTERNAL_ERROR, "internal error")
        log.info("chat.completed", extra={
            "request_id": request_id, "session_id": session_id, "dept": dept,
            "route": result.headers.get("x-anongw-route"), "status": result.status_code,
        })
        return JSONResponse(result.payload, status_code=result.status_code, headers=result.headers)

    @app.post("/internal/detect")
    async def internal_detect(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return _error_response(400, CODE_BAD_REQUEST, "request body is not valid JSON")
        text = body.get("text") if isinstance(body, dict) else None
        if not isinstance(text, str):
            return _error_response(400, CODE_BAD_REQUEST, "'text' must be a string")
        found = detect(text)
        numbered = [f.model_copy(update={"fid": f"f_{i:04d}"}) for i, f in enumerate(found, start=1)]
        return JSONResponse({"findings": [f.model_dump() for f in numbered]})

    @app.post("/internal/anonymize")
    async def internal_anonymize(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return _error_response(400, CODE_BAD_REQUEST, "request body is not valid JSON")
        if not isinstance(body, dict) or not isinstance(body.get("text"), str):
            return _error_response(400, CODE_BAD_REQUEST, "'text' must be a string")
        session_id = body.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            session_id = deps.new_session_id()
        text = body["text"]
        spans = [
            (f.start, f.end, f.type, f.normalized)
            for f in detect(text)
            if f.action_hint == "MASK" and not f.whitelisted
        ]
        mapper = service.registry.get(session_id)
        masked, entries = mapper.mask(text, spans)
        return JSONResponse({
            "session_id": session_id,
            "masked": masked,
            "mappings": [e.model_dump(mode="json") for e in entries],
        })

    @app.post("/internal/restore")
    async def internal_restore(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return _error_response(400, CODE_BAD_REQUEST, "request body is not valid JSON")
        if not isinstance(body, dict) or not isinstance(body.get("text"), str):
            return _error_response(400, CODE_BAD_REQUEST, "'text' must be a string")
        session_id = body.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return _error_response(400, CODE_BAD_REQUEST, "'session_id' must be a non-empty string")
        mapper = service.registry.get(session_id)
        return JSONResponse({"session_id": session_id, "restored": mapper.restore(body["text"])})

    return app
