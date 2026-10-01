"""看板 HTTP 服务：冻结契约（开发指令 §3.2）+ 单页看板 + SSE 实时刷新。

冻结契约（只增不改名，§3.2）：
    POST /api/session/start {user_id} -> {session_id}
    POST /api/bite      (BiteRecord)  -> 204
    GET  /api/session/current         -> MealSession
    GET  /api/stream                  (SSE，看板实时刷新)

本模块追加的端点（契约只增纪律允许）：
    GET  /api/health          存活探针（测试/编排等待就绪用）
    GET  /api/summary         看板聚合快照（口数/时长/克数/结局分布）
    POST /api/session/end     结束当前会话（行为树"吃饱了"出口 / 演示收尾）
    GET  /api/events          事件流镜像倒序（回放/取证）
    GET  /                    单页看板（本地静态资源，离线可开）

SSE 事件（text/event-stream）：
    snapshot        连接建立即推：{session, summary}
    bite            新单口：{session_id, bite, summary}
    session_started / session_ended：{session, summary}
另每 15s 推一行 SSE 注释心跳（": keepalive"）防中间层空闲断连。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:  # 以仓库根为 cwd（pytest / pythonpath=. / python -m chengshao.cs_dashboard）
    from chengshao.cs_dashboard.store import (
        DEFAULT_DB_PATH,
        ActiveSessionExistsError,
        DuplicateBiteError,
        NoActiveSessionError,
        Store,
        StoreError,
    )
    from chengshao.cs_schema import BiteRecord, MealSession
except ImportError:  # 以 chengshao/ 为 cwd（python -m cs_dashboard）
    from cs_dashboard.store import (  # type: ignore[no-redef]
        DEFAULT_DB_PATH,
        ActiveSessionExistsError,
        DuplicateBiteError,
        NoActiveSessionError,
        Store,
        StoreError,
    )
    from cs_schema import BiteRecord, MealSession  # type: ignore[no-redef]

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_KEEPALIVE_S = 15.0

_STATUS_FOR_ERROR: dict[type[StoreError], int] = {
    NoActiveSessionError: 409,
    ActiveSessionExistsError: 409,
    DuplicateBiteError: 409,
}


class SessionStartRequest(BaseModel):
    """POST /api/session/start 请求体（契约只写 user_id）。

    min_length=1 与契约 MealSession.user_id 的约束一致，
    让空 user_id 在请求校验层得到 422，而不是落库时才炸 500。
    """

    user_id: str = Field(min_length=1)


class _Hub:
    """进程内 SSE 订阅中心（所有句柄都在 uvicorn 事件循环上，put_nowait 安全）。"""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(q)

    def publish(self, event: str, data: dict[str, Any]) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait({"event": event, "data": data})
            except asyncio.QueueFull:  # 慢消费者丢帧优先于阻塞主链路
                pass


def create_app(store: Store | None = None, db_path: str | Path = DEFAULT_DB_PATH) -> FastAPI:
    """应用工厂。store 缺省时按 db_path（默认仓库根 data/care.db）自建。"""
    app = FastAPI(
        title="chengshao-care-dashboard",
        version="1.0.0",
        description="桌面助餐机械臂 · 护理看板（冻结 HTTP 契约 §3.2）",
    )
    store = store if store is not None else Store(db_path)
    hub = _Hub()
    app.state.store = store
    app.state.hub = hub

    @app.exception_handler(StoreError)
    async def _store_error_handler(_request: Request, exc: StoreError) -> JSONResponse:
        status = _STATUS_FOR_ERROR.get(type(exc), 500)
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    # ---- 冻结契约 -----------------------------------------------------------

    @app.post("/api/session/start")
    async def session_start(body: SessionStartRequest) -> dict[str, str]:
        session = store.start_session(body.user_id)
        hub.publish(
            "session_started",
            {"session": session.model_dump(mode="json"), "summary": store.summary(session)},
        )
        return {"session_id": session.session_id}

    @app.post("/api/bite", status_code=204)
    async def bite(record: BiteRecord) -> Response:
        """写入单口（body=契约 BiteRecord，pydantic 校验失败自动 422）。"""
        session_id = store.add_bite(record)
        current = store.current_session()
        hub.publish(
            "bite",
            {
                "session_id": session_id,
                "bite": record.model_dump(mode="json"),
                "summary": store.summary(current),
            },
        )
        return Response(status_code=204)

    @app.get("/api/session/current")
    async def session_current() -> MealSession:
        session = store.current_session()
        if session is None:
            raise NoActiveSessionError("还没有任何进餐会话")
        return session

    @app.get("/api/stream")
    async def stream() -> StreamingResponse:
        return StreamingResponse(_event_stream(hub, store), media_type="text/event-stream")

    # ---- 追加端点 -----------------------------------------------------------

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/summary")
    async def summary() -> dict[str, Any]:
        return store.summary()

    @app.post("/api/session/end")
    async def session_end() -> dict[str, Any]:
        session = store.end_session()
        payload = {
            "session": session.model_dump(mode="json"),
            "summary": store.summary(session),
        }
        hub.publish("session_ended", payload)
        return payload

    @app.get("/api/events")
    async def events(limit: int = 100) -> list[dict[str, Any]]:
        return store.recent_events(limit=limit)

    # ---- 静态看板 -----------------------------------------------------------

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html", media_type="text/html")

    return app


async def _event_stream(hub: _Hub, store: Store) -> AsyncIterator[str]:
    """SSE 主循环：先发 snapshot，随后转发实时事件，空闲推心跳。"""
    q = hub.subscribe()
    try:
        session = store.current_session()
        snap = {
            "session": None if session is None else session.model_dump(mode="json"),
            "summary": store.summary(session),
        }
        yield f"event: snapshot\ndata: {_sse_data(snap)}\n\n"
        while True:
            try:
                item = await asyncio.wait_for(q.get(), timeout=_KEEPALIVE_S)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield f"event: {item['event']}\ndata: {_sse_data(item['data'])}\n\n"
    finally:
        hub.unsubscribe(q)


def _sse_data(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


__all__ = ["create_app"]
