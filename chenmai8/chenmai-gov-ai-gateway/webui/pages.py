"""演示前端页面（M9，无框架：Jinja2 模板 + 原生 JS）。

页面路线（开发指令 §6 M9 四页；本模块 T3.3 先行体检页，其余 T5.2 补全）：

- GET /webui         演示首页：已上线页面入口（探针字符串「文件体检」）；
- GET /webui/files   文件体检页骨架：上传 → 报告（风险徽标/汇总/命中明细）→
                     导出按钮（fetch 调 /v1/files/inspect、/v1/files/export，
                     纯浏览器端 FormData，无构建步骤、无外部依赖）。

不做登录（演示模式，M9 spec）；样式朴素但结构清晰。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates

#: 模板目录（包内固定；export_public 会整体拷贝源码树）
_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

#: 页面清单（演示首页入口与 m9_webui 探针共用）
PAGES: tuple[dict[str, str], ...] = (
    {"path": "/webui/files", "title": "文件体检", "desc": "公开前体检报告 + 彻底删除式导出",
     "status": "已上线（T3.3）"},
    {"path": "/webui/chat", "title": "对话双屏", "desc": "脱敏对话 + 上游实际收到内容对照",
     "status": "待上线（T5.2）"},
    {"path": "/webui/dashboard", "title": "审计看板", "desc": "按部门/路由/拦截类别指标",
     "status": "待上线（T5.2）"},
)


def mount(app: FastAPI) -> None:
    """把演示页路由挂到网关应用（create_app 末尾调用）。"""

    @app.get("/webui")
    async def webui_index(request: Request):
        """演示首页：页面入口清单。"""
        return templates.TemplateResponse(request, "index.html",
                                          {"pages": PAGES, "healthz": "/healthz"})

    @app.get("/webui/files")
    async def webui_files(request: Request):
        """文件体检页骨架：上传 → 报告高亮 → 导出按钮（§6 M9）。"""
        return templates.TemplateResponse(request, "files.html", {"page_title": "文件体检"})
