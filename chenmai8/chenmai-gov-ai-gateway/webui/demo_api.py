"""看板「演示态」管理端点（T5.3）：``/admin/api/demo/*`` —— 演示态一键切换的服务面。

三个端点（形状与鉴权口径对齐 T5.1 管理面，只增不改名）::

    POST /admin/api/demo/seed   一键注入三部门演示数据（幂等：先清旧演示事件再注入）
                                → ops.seed_demo.seed_demo 的摘要（inserted/routes/…）
    POST /admin/api/demo/clear  一键清除演示数据（只删 sess_demo_ 前缀的合成事件）
                                → {"removed": N}
    GET  /admin/api/demo/state  演示态摘要（总量/演示态/按部门/按路由/演示态类别分布）
                                → ops.seed_demo.demo_state 的摘要

看板页（webui/templates/dashboard.html「演示态」面板）经这三个端点做**一键切换**：
演示态 ON = seed（注入全合成事件，看板指标随之呈现三部门分布）；演示态 OFF =
clear（摘掉的只是合成事件，真实流量事件不受影响）。

鉴权（与 /admin/api/audit 同一硬口径，T5.1）：任意一个有效部门 Key
（``Authorization: Bearer <dept_key>``）放行；缺 key / 错 key → 401。
生产部署另须仅经本地管理面/内网访问（与 /internal/* 同一安全注记）。

安全与数据口径：
- 注入的是**全合成**数据（ops/seed_demo，seed 固定；取值域与 e2e 验收黑名单
  主动错开），经网关同一条 ``GatewayService._prepare``/落账代码路径构造，
  过零明文硬闸，写后对库文件做 bytes 级零明文复扫——演示数据与真实流量
  事件同库同规格，看板两种态可同屏对照；
- seed/clear 的写路径一律走审计 sink（写队列 + 硬闸）或参数绑定 DELETE
  （``substr(session_id,1,?)=?``，无拼接/f-string 组 SQL，审查项：外部输入
  一律绑定）。
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from gateway import deps
from gateway.models import ApiError, ErrorBody
from ops.seed_demo import clear_demo, demo_state, seed_demo

# 错误信封 code（与 gateway/pipeline / admin_api 错误词表同源——只增不改名）
CODE_UNAUTHORIZED = "unauthorized"
CODE_BAD_REQUEST = "bad_request"


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    """§5.6 错误信封（与 gateway/app 同一形状）。"""
    return JSONResponse(ApiError(error=ErrorBody(code=code, message=message)).model_dump(),
                        status_code=status_code)


def _authenticate(app: FastAPI, request: Request) -> str | None:
    """部门 Key 鉴权（常量时间比较，与 /admin/api/audit 同一实现）；未命中 None。"""
    return deps.authenticate(
        deps.extract_bearer(request.headers.get("authorization")),
        app.state.dept_key_digests,
    )


def mount(app: FastAPI) -> None:
    """把看板演示态管理 API 挂到网关应用（webui.pages.mount 末尾调用）。"""

    @app.post("/admin/api/demo/seed")
    async def demo_seed(request: Request) -> JSONResponse:
        """一键注入三部门演示数据（幂等 replace）；走网关同一构造/落账路径。"""
        if _authenticate(app, request) is None:
            return _error_response(401, CODE_UNAUTHORIZED,
                                   "无效部门 Key（Authorization: Bearer dk_***）")
        try:
            summary = seed_demo(sink=app.state.audit, service=app.state.service,
                                cfg=app.state.cfg)
        except (RuntimeError, ValueError) as exc:
            return _error_response(400, CODE_BAD_REQUEST, str(exc))
        # 摘要只含计数与占位符预览（合成原值不进响应）；class_counts 键即类别名
        return JSONResponse(summary)

    @app.post("/admin/api/demo/clear")
    async def demo_clear(request: Request) -> JSONResponse:
        """一键清除演示数据（只删 sess_demo_ 前缀的合成事件）。"""
        if _authenticate(app, request) is None:
            return _error_response(401, CODE_UNAUTHORIZED,
                                   "无效部门 Key（Authorization: Bearer dk_***）")
        store = app.state.audit
        try:
            removed = clear_demo(store)
        except TypeError as exc:  # 存储形态不支持清理：明确报错，绝不误删
            return _error_response(400, CODE_BAD_REQUEST, str(exc))
        return JSONResponse({"removed": removed})

    @app.get("/admin/api/demo/state")
    async def demo_state_api(request: Request) -> JSONResponse:
        """演示态摘要（看板面板渲染口径；只读，SQLite 形态不触写路径）。"""
        if _authenticate(app, request) is None:
            return _error_response(401, CODE_UNAUTHORIZED,
                                   "无效部门 Key（Authorization: Bearer dk_***）")
        return JSONResponse(demo_state(app.state.audit))

