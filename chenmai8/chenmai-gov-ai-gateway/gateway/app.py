"""网关 FastAPI 应用（骨架 v0）：/v1/chat/completions 非流式+流式 + 文件通道 + 调试/健康端点。

端点（§5.6，实装子集；管理面端点由 T5.1 补全）::

    POST /v1/chat/completions   OpenAI 兼容（``stream=true`` 走 SSE 流式）；鉴权
                                Authorization: Bearer <dept_key>；响应附
                                x-anongw-route / x-anongw-request-id / x-anongw-session-id；
                                成功回答另附 x-anongw-ai-label: 1（§6 M5，AI 生成标识头，
                                流式随 SSE 头、非流式同头）
    GET  /v1/models             路由目标清单（脱敏视图，仅名字）
    POST /v1/files/inspect      multipart 上传 → FileReport JSON（T3.3 文件通道；
                                详见 filechannel/service.py 鉴权面说明——报告 raw 为
                                上传者自带文件内容回显，演示模式不做部门 Key 鉴权）
    POST /v1/files/export       multipart 上传 + ``mode=sanitize`` → 清理后文件流，
                                响应头附 ``X-Report-Id``（导出前体检报告 id）
    POST /internal/detect       {text} → findings（调试；需部门 Key）
    POST /internal/anonymize    {text, session_id} → 占位符版本（调试/演示对比屏；需部门 Key）
    POST /internal/restore      {text, session_id} → 还原版本（调试/演示对比屏；需部门 Key）
    GET  /webui, /webui/files   演示页（M9 体检页骨架，webui/pages.py 挂载）
    GET  /healthz               存活

/internal/* 调试端点（审查 §A1）：复用与 /v1/chat/completions 同一部门 Key 鉴权
（Authorization: Bearer <dept_key>），未命中 → 401——响应含 Finding.raw/还原原文，
绝不无鉴权暴露；生产部署另须仅经本地管理面/内网访问（见 README 安全注记）。

落库形态（T1.3）：不注入时审计走 SQLite 写队列（cfg.audit_db）、会话映射走
SessionStore（cfg.session_db，TTL=cfg.session_ttl_h，lifespan 挂清理协程）——
生产与注入两种形态见 :func:`create_app` 文档。
请求体上限：Content-Length > 网关上限即 413（畸形输入用例由 e2e 任务补全）；
文件通道上限 50MB（evals.thresholds.FILE_SIZE_MAX_BYTES，§6 M6）。
流式语义（§6 M1/T0.5）：BLOCK / 上游不可达 / 上游协议错误在开流前决出，
返回普通 JSON 错误信封；开流后为 ``text/event-stream``，AI 标识以内容尾注 +
finish chunk ``annotations`` 元数据注入（gateway/sse.py 组合管线）。
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse

from audit.store import AuditSink, RawPiiLeakError
from audit.writer import SqliteAuditWriter
from common.config import (
    REPO_ROOT,
    AppConfig,
    load_app_config,
    load_dept_keys,
    resolve_secret,
)
from common.logs import get_logger
from evals.thresholds import FILE_SIZE_MAX_BYTES, GATEWAY_BODY_MAX_BYTES
from filechannel.errors import DocumentParseError, FileTooLargeError, UnsupportedFileType
from filechannel.service import BadModeError, ExportBlockedError, FileService
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
from masking.session_store import SessionStore
from recognizers.rule.detect import detect

log = get_logger(__name__)

#: 会话 TTL 清理协程的运行间隔（秒）
CLEANUP_INTERVAL_S = 300.0

#: 文件通道错误码（§5.6 错误信封复用面；413/400/422 映射见 filechannel/errors.py 口径）
CODE_UNSUPPORTED_FILE = "unsupported_file_type"
CODE_FILE_PARSE = "file_parse_error"
CODE_EXPORT_BLOCKED = "export_blocked"


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(ApiError(error=ErrorBody(code=code, message=message)).model_dump(),
                        status_code=status_code)


def _content_disposition(filename: str) -> str:
    """附件下载头：ASCII 兜底名 + RFC 5987 UTF-8 扩展名（报头仅允许 latin-1 字节）。"""
    ascii_name = filename.encode("ascii", "replace").decode("ascii").replace('"', "_")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def resolve_db_path(p: str | Path) -> Path:
    """库文件路径解析：相对路径按仓库根（config 同侧）解析。"""
    path = Path(p)
    return path if path.is_absolute() else REPO_ROOT / path


def create_app(
    *,
    cfg: AppConfig | None = None,
    mask_key: str | None = None,
    dept_key_digests: dict[str, str] | None = None,
    audit_store: AuditSink | None = None,
    session_registry: Any | None = None,
    outguard: Any | None = None,
) -> FastAPI:
    """构造网关应用。生产入口不传参（读 config/ 与环境）；测试可全量注入。

    默认落库形态（T1.3）：
    - ``audit_store`` 缺省 → :class:`audit.writer.SqliteAuditWriter`（队列+WAL，
      路径 ``cfg.audit_db``），app 关闭时排干队列收尾；
    - ``session_registry`` 缺省 → :class:`masking.session_store.SessionStore`
      （LRU+SQLite ``masking_map``+TTL，路径 ``cfg.session_db``，TTL ``cfg.session_ttl_h``），
      lifespan 启动 TTL 清理协程、关闭时收尾；
    - ``outguard``（T2.2）缺省 → :class:`outguard.service.OutguardService.from_config`
      （文案库 ``cfg.outguard_texts``）；注入自定义复检后端时构造 OutguardService
      传入（P1 语义审核模型采样执行入口）；
    - 注入形态（evals）不接管生命周期，由注入方自行 close。
    """
    cfg = cfg or load_app_config()
    if mask_key is None:
        resolved = resolve_secret(cfg.mask_key_env, required=False)
        if not resolved:
            raise RuntimeError(f"missing required secret env: {cfg.mask_key_env}")
        mask_key = resolved
    digests = dept_key_digests if dept_key_digests is not None else load_dept_keys()

    audit = audit_store if audit_store is not None else SqliteAuditWriter(resolve_db_path(cfg.audit_db))
    registry = session_registry
    owns_registry = registry is None
    if registry is None:
        registry = SessionStore(mask_key.encode("utf-8"), resolve_db_path(cfg.session_db),
                                ttl=timedelta(hours=cfg.session_ttl_h))
    service = GatewayService(cfg, mask_key, audit_store=audit, registry=registry,
                             outguard=outguard)
    files = FileService(cfg)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        task = asyncio.create_task(registry.cleanup_loop(CLEANUP_INTERVAL_S)) if owns_registry else None
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            if isinstance(audit, SqliteAuditWriter):
                audit.close()
            if owns_registry and isinstance(registry, SessionStore):
                registry.close()

    app = FastAPI(title="gov-anon-gateway", docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)
    app.state.service = service
    app.state.cfg = cfg
    app.state.dept_key_digests = digests
    app.state.audit = audit
    app.state.session_registry = registry
    app.state.file_service = files

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

    @app.post("/v1/files/inspect")
    async def files_inspect(request: Request,
                            file: Annotated[UploadFile, File(...)]) -> JSONResponse:
        """multipart 上传 → 公开前体检报告（§5.5 FileReport JSON）。

        体积双闸：Content-Length 预检 + 实读字节复核（均 413）；
        种类不识别/解析失败 → 400 错误信封（code 见 §5.6 复用面）。
        """
        try:
            content_length = int(request.headers.get("content-length", "0") or "0")
        except ValueError:
            content_length = 0
        if content_length > FILE_SIZE_MAX_BYTES:
            return _error_response(413, CODE_PAYLOAD_TOO_LARGE,
                                   f"文件超过上限 {FILE_SIZE_MAX_BYTES} 字节")
        data = await file.read()
        try:
            report = files.inspect_bytes(file.filename or "", data)
        except FileTooLargeError:
            return _error_response(413, CODE_PAYLOAD_TOO_LARGE,
                                   f"文件超过上限 {FILE_SIZE_MAX_BYTES} 字节")
        except UnsupportedFileType as exc:
            return _error_response(400, CODE_UNSUPPORTED_FILE, str(exc))
        except DocumentParseError as exc:
            return _error_response(422, CODE_FILE_PARSE, str(exc))
        except Exception:  # noqa: BLE001 — 兜底 500（不泄漏内部细节）
            log.error("files.inspect.unhandled_error", extra={"exc_type": "InternalError"})
            return _error_response(500, CODE_INTERNAL_ERROR, "internal error")
        return JSONResponse(report.model_dump())

    @app.post("/v1/files/export")
    async def files_export(
            file: Annotated[UploadFile, File(...)],
            mode: Annotated[str, Form()] = "sanitize") -> Response:
        """multipart 上传 + ``mode=sanitize`` → 删除式清理后的文件流（§5.6）。

        响应头：``X-Report-Id`` = 导出前体检报告 id（FileService 登记表可查）；
        ``X-Sanitize-Method`` = 实际生效的导出方式（如实标注：引擎名/删值/栅格
        兜底，§6「重打码渲染版在报告中如实标注方式」）；``Content-Disposition``
        = sanitized_<原文件名>。命中无法物理定位/导出物零残留复核不净时 422
        export_blocked（宁可阻止不可漏删）。
        """
        data = await file.read()
        try:
            result = files.export_bytes(file.filename or "", data, mode)
        except BadModeError as exc:
            return _error_response(400, CODE_BAD_REQUEST, str(exc))
        except FileTooLargeError:
            return _error_response(413, CODE_PAYLOAD_TOO_LARGE,
                                   f"文件超过上限 {FILE_SIZE_MAX_BYTES} 字节")
        except UnsupportedFileType as exc:
            return _error_response(400, CODE_UNSUPPORTED_FILE, str(exc))
        except DocumentParseError as exc:
            return _error_response(422, CODE_FILE_PARSE, str(exc))
        except ExportBlockedError as exc:
            return _error_response(422, CODE_EXPORT_BLOCKED, str(exc))
        except Exception:  # noqa: BLE001
            log.error("files.export.unhandled_error", extra={"exc_type": "InternalError"})
            return _error_response(500, CODE_INTERNAL_ERROR, "internal error")
        return Response(content=result.data, media_type=result.content_type, headers={
            "X-Report-Id": result.report.file_id,
            "X-Sanitize-Method": result.method,
            "Content-Disposition": _content_disposition(result.download_name),
        })

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

        # 5) 主链路（流式 / 非流式分流；校验与错误信封两形态一致）
        wants_stream = body.get("stream") is True
        try:
            if wants_stream:
                result = await service.handle_chat_stream(body, dept=dept, session_id=session_id,
                                                          request_id=request_id)
                if result.events is not None:
                    log.info("chat.completed", extra={
                        "request_id": request_id, "session_id": session_id, "dept": dept,
                        "route": result.headers.get("x-anongw-route"), "status": 200,
                        "stream": True,
                    })
                    return StreamingResponse(result.events, status_code=result.status_code,
                                             media_type="text/event-stream",
                                             headers=result.headers)
                log.info("chat.completed", extra={
                    "request_id": request_id, "session_id": session_id, "dept": dept,
                    "route": result.headers.get("x-anongw-route"), "status": result.status_code,
                    "stream": True,
                })
                return JSONResponse(result.payload, status_code=result.status_code,
                                    headers=result.headers)
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
        if deps.authenticate(
            deps.extract_bearer(request.headers.get("authorization")), digests,
        ) is None:
            return _error_response(401, CODE_UNAUTHORIZED, "无效部门 Key（Authorization: Bearer dk_***）")
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
        if deps.authenticate(
            deps.extract_bearer(request.headers.get("authorization")), digests,
        ) is None:
            return _error_response(401, CODE_UNAUTHORIZED, "无效部门 Key（Authorization: Bearer dk_***）")
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
        if deps.authenticate(
            deps.extract_bearer(request.headers.get("authorization")), digests,
        ) is None:
            return _error_response(401, CODE_UNAUTHORIZED, "无效部门 Key（Authorization: Bearer dk_***）")
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return _error_response(400, CODE_BAD_REQUEST, "request body is not valid JSON")
        if not isinstance(body, dict) or not isinstance(body.get("text"), str):
            return _error_response(400, CODE_BAD_REQUEST, "'text' must be a string")
        session_id = body.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            session_id = deps.new_session_id()
        mapper = service.registry.get(session_id)
        return JSONResponse({"session_id": session_id, "restored": mapper.restore(body["text"])})

    # 演示前端（M9，无框架 Jinja2 + 原生 JS；体检页骨架先行，其余页面 T5.2 补全）
    from webui.pages import mount as mount_webui  # noqa: PLC0415 — 延迟导入避免环

    mount_webui(app)

    return app
