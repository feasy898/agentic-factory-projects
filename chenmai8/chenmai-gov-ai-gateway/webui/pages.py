"""演示前端页面（M9，无框架：Jinja2 模板 + 原生 JS）。

四页全量（开发指令 §6 M9；T3.3 体检页 → T4.3 演示控制页 → T5.2 看板页+聊天页）：

- GET /webui         演示首页：四页入口清单（探针字符串「文件体检」）；
- GET /webui/files   文件体检页：上传 → 报告（风险徽标/汇总/命中明细）→
                     导出按钮（fetch 调 /v1/files/inspect、/v1/files/export，
                     纯浏览器端 FormData，无构建步骤、无外部依赖）；
- GET /webui/demo    演示控制页：五场景清单 + 场景材料下载入口 + 一键载入聊天；
- GET /webui/chat    对话双屏页（T5.2）：左栏对话（route 徽标/拦截卡/流式 SSE），
                     右栏「上游实际收到内容」（经 /internal/anonymize 实时取
                     脱敏视图，§10 场景1 双屏对比）；
- GET /webui/dashboard 审计看板页（T5.2）：指标卡（今日拦截等）+ 手写 SVG 柱状图
                     （路由分布/Top 部门/命中类别）+ 审计明细表（分页）；数据
                     服务端直读审计存储（webui.dashboard.read_events 适配内存表
                     与 SQLite 写队列两种形态），分页在 Python 内存完成；
- GET /webui/demo/materials/{filename}        场景材料下载：**白名单文件名**（仅
                     生成器已登记的演示夹具），按需物化到 data/fixtures/materials/
                     后回传——与 ops/e2e_smoke、ops/demo/build_fixtures 同源；
- GET /webui/demo/materials/{filename}/text  场景材料纯文本（一键载入聊天页用；
                     服务端经 filechannel 解析抽取，与下载物同字节同源）。

看板「演示态」一键切换（T5.3，本模块 mount 末尾挂载 webui/demo_api.py）：
- POST /admin/api/demo/seed   一键注入三部门合成演示数据（幂等；ops/seed_demo 同源核心）
- POST /admin/api/demo/clear  一键清除演示数据（只删 sess_demo_ 前缀合成事件）
- GET  /admin/api/demo/state  演示态摘要（总量/演示态/按部门/按路由/类别分布）
（部门 Key 鉴权，口径对齐 T5.1 管理面；看板页面板经这三个端点切换演示态。）

不做登录（演示模式，M9 spec）；样式朴素但结构清晰。材料为合成演示数据
（seeded 冻结值），不含任何真实个人信息。
"""
from __future__ import annotations

import json
from datetime import UTC
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.templating import Jinja2Templates

from benchmark.generator.materials import (
    CLASSIFIED_MATERIAL,
    DEMO_SCAN_FILENAME,
    MATERIALS,
    ORDINARY_MATERIAL,
    ROSTER_MATERIAL,
    WEBPAGE_CLEAN_MATERIAL,
    WEBPAGE_INJECTED_MATERIAL,
    build_demo_scan,
    build_materials,
)
from common.config import REPO_ROOT
from webui.dashboard import (
    PAGE_SIZE_DEFAULT,
    PAGE_SIZES,
    bar_chart_svg,
    paginate,
    read_events,
    route_badge,
    summarize,
)

#: 模板目录（包内固定；export_public 会整体拷贝源码树）
_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

#: 明细表时间列统一 UTC（工程约定：时间统一 UTC ISO8601）
_UTC = UTC

#: 演示材料物化目录（构建物，不入库；与 e2e / build_fixtures CLI 同目录）
_DEMO_DIR = REPO_ROOT / "data" / "fixtures" / "materials"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

#: 页面清单（演示首页入口与 m9_webui 探针共用）
PAGES: tuple[dict[str, str], ...] = (
    {"path": "/webui/files", "title": "文件体检", "desc": "公开前体检报告 + 彻底删除式导出",
     "status": "已上线（T3.3）"},
    {"path": "/webui/demo", "title": "演示控制页", "desc": "五场景清单 + 场景材料下载/一键载入聊天（场景4 防注入 / 场景5 扫描件体检就绪）",
     "status": "已上线（T4.3；一键载入 T5.2）"},
    {"path": "/webui/chat", "title": "对话双屏", "desc": "脱敏对话 + 上游实际收到内容对照（route 徽标/拦截卡/流式）",
     "status": "已上线（T5.2）"},
    {"path": "/webui/dashboard", "title": "审计看板", "desc": "指标卡 + SVG 柱状图（路由/部门/类别）+ 审计明细分页 + 演示态一键切换",
     "status": "已上线（T5.2；演示态切换 T5.3）"},
)

#: 演示场景清单（§10 五场景；编号按任务单 T4.3——场景4=防注入、场景5=扫描件体检，
#: 与开发指令 §10 表的编号对照见 ops/demo/README.md）
DEMO_SCENES: tuple[dict, ...] = (
    {"no": "场景1", "title": "双屏对比", "desc": "脱敏对话＋上游实际收到内容对照",
     "materials": (), "status": "已就绪（T5.2 聊天页）"},
    {"no": "场景2", "title": "三份材料三路由",
     "desc": "普通公文→INTERNET／低保名单→GOVCLOUD／机密纪要→BLOCK 拦截",
     "materials": (ORDINARY_MATERIAL.filename, ROSTER_MATERIAL.filename,
                   CLASSIFIED_MATERIAL.filename),
     "status": "已就绪（T5.2 一键载入聊天）"},
    {"no": "场景3", "title": "看板指标", "desc": "审计统计 + bench 报告数字对照",
     "materials": (), "status": "已就绪（T5.2 看板页）"},
    {"no": "场景4", "title": "防注入",
     "desc": "检索网页里埋注入指令→语义层拦截（403 INJECTION·flag=injection）；"
             "脚本 ops/demo/scene4.md",
     "materials": (WEBPAGE_CLEAN_MATERIAL.filename, WEBPAGE_INJECTED_MATERIAL.filename),
     "status": "已就绪（T4.3）"},
    {"no": "场景5", "title": "扫描件体检",
     "desc": "扫描 PDF→OCR 体检 HIGH→重打码导出→再体检零残留；脚本 ops/demo/scene5.md",
     "materials": (DEMO_SCAN_FILENAME,),
     "status": "已就绪（T4.3）"},
)

#: 材料下载白名单（演示下载只服务生成器已登记的夹具文件名——路径穿越结构性排除）
_MATERIAL_NAMES: frozenset[str] = frozenset(
    {*(m.filename for m in MATERIALS), DEMO_SCAN_FILENAME})

_MATERIAL_CONTENT_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
}

#: 演示部门 Key（明文与 .env.example 注释一致；config/dept_keys.yaml 只存 sha256）。
#: 演示模式无登录（M9 spec），聊天页浏览器端携带部门 Key 调 /v1/* 与 /internal/*。
DEMO_DEPTS: tuple[dict[str, str], ...] = (
    {"name": "县政府办", "key": "dk_1a2b3c4d"},
    {"name": "民政局", "key": "dk_5e6f7a8b"},
    {"name": "某镇", "key": "dk_9c0d1e2f"},
)


def _materialize(filename: str) -> bytes:
    """物化白名单演示材料并回传字节（幂等：同构建器双构建字节级一致）。

    网关工作目录即 REPO_ROOT（python -m gateway 启动口径），材料目录相对定位；
    文件缺失时按需构建，已存在时构建器原样重写同一字节。
    """
    build_materials(_DEMO_DIR)
    if filename == DEMO_SCAN_FILENAME:
        build_demo_scan(_DEMO_DIR)
    return (_DEMO_DIR / filename).read_bytes()


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

    @app.get("/webui/demo")
    async def webui_demo(request: Request):
        """演示控制页：五场景清单 + 场景材料下载 + 一键载入聊天（T5.2）。"""
        scenes = [
            {"no": s["no"], "title": s["title"], "desc": s["desc"],
             "status": s["status"],
             "materials": [{"filename": name,
                            "href": f"/webui/demo/materials/{name}",
                            "chat_href": f"/webui/chat?material={quote(name)}"}
                           for name in s["materials"]]}
            for s in DEMO_SCENES
        ]
        return templates.TemplateResponse(request, "demo.html",
                                          {"page_title": "演示控制页", "scenes": scenes})

    @app.get("/webui/chat")
    async def webui_chat(request: Request):
        """对话双屏页（T5.2）：左栏对话（route 徽标/拦截卡/SSE 流式）+
        右栏「上游实际收到内容」（/internal/anonymize 脱敏视图，§10 场景1）。"""
        return templates.TemplateResponse(request, "chat.html", {
            "page_title": "对话双屏",
            "depts": DEMO_DEPTS,
            "models": ["mock-chat", "gov-chat"],
        })

    @app.get("/webui/dashboard")
    async def webui_dashboard(request: Request, page: int = 1,
                              page_size: int = PAGE_SIZE_DEFAULT):
        """审计看板页（T5.2）：指标卡 + 手写 SVG 柱状图 + 审计明细分页。

        数据服务端直读审计存储（``request.app.state.audit``，内存表与 SQLite
        写队列两种形态均适配）；分页/聚合纯 Python 内存完成，不新增 SQL 面。
        """
        events = read_events(request.app.state.audit)
        view = summarize(events)
        page_view = paginate(events, page, page_size)
        rows = [{
            "ts": e.ts.astimezone(_UTC).strftime("%Y-%m-%d %H:%M:%S") + " UTC",
            "dept": e.dept or "—",
            "badge": route_badge(e.route),
            "route": e.route,
            "reasons": "、".join(e.reasons) if e.reasons else "—",
            "flags": "、".join(e.flags) if e.flags else "—",
            "counts": " ".join(f"{k}×{v}" for k, v in e.class_counts.items()) or "—",
            "upstream": e.upstream or "—",
            "latency_ms": e.latency_ms,
            "preview": e.prompt_preview or e.response_preview or "—",
            "request_id": e.request_id or "—",
        } for e in page_view["rows"]]
        return templates.TemplateResponse(request, "dashboard.html", {
            "page_title": "审计看板",
            "kpi": view["kpi"],
            "routes": view["routes"],
            "depts": view["depts"],
            "categories": view["categories"],
            "svg_routes": bar_chart_svg(view["routes"], label_key="route",
                                        value_key="count", title="路由分布",
                                        color="#2563eb"),
            "svg_depts": bar_chart_svg(view["depts"], label_key="dept",
                                       value_key="count", title="Top 部门",
                                       color="#047857"),
            "svg_categories": bar_chart_svg(view["categories"], label_key="category",
                                            value_key="count", title="命中类别 Top",
                                            color="#b45309"),
            "rows": rows,
            "page": page_view["page"],
            "page_size": page_view["page_size"],
            "total": page_view["total"],
            "total_pages": page_view["total_pages"],
            "page_sizes": PAGE_SIZES,
            # T5.3 看板演示态一键切换：面板经 /admin/api/demo/* 注入/清除三部门合成数据
            "demo_depts": DEMO_DEPTS,
        })

    @app.get("/webui/demo/materials/{filename}")
    async def demo_material(filename: str) -> Response:
        """场景材料下载（白名单 + 按需物化；M9 演示模式无登录）。"""
        if filename not in _MATERIAL_NAMES:
            raise HTTPException(status_code=404, detail="unknown demo material")
        data = _materialize(filename)
        media_type = _MATERIAL_CONTENT_TYPES.get(Path(filename).suffix.lower(),
                                                 "application/octet-stream")
        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition":
                     f"attachment; filename=\"{filename}\"; "
                     f"filename*=UTF-8''{quote(filename)}"},
        )

    @app.get("/webui/demo/materials/{filename}/text")
    async def demo_material_text(filename: str) -> Response:
        """场景材料纯文本（一键载入聊天页；白名单同下载面，服务端解析抽取）。"""
        if filename not in _MATERIAL_NAMES:
            raise HTTPException(status_code=404, detail="unknown demo material")
        from filechannel.parsers import parse_any  # noqa: PLC0415 — 延迟导入避环

        data = _materialize(filename)
        parsed = parse_any(filename, data)
        text = "\n".join(seg.text for seg in parsed.segments)
        return Response(
            content=json.dumps({"filename": filename, "text": text}, ensure_ascii=False),
            media_type="application/json; charset=utf-8",
        )

    # 看板演示态管理 API（T5.3：/admin/api/demo/seed|clear|state，部门 Key 鉴权，
    # 口径对齐 T5.1 管理面；注入/清除全合成演示数据，ops/seed_demo.py 同源核心）
    from webui.demo_api import mount as mount_demo_api  # noqa: PLC0415 — 延迟导入避免环

    mount_demo_api(app)
