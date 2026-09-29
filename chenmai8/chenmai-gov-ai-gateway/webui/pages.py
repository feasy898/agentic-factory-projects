"""演示前端页面（M9，无框架：Jinja2 模板 + 原生 JS）。

页面路线（开发指令 §6 M9 四页；本模块 T3.3 先行体检页，T4.3 补演示控制页
骨架，聊天/看板页 T5.2 补全）：

- GET /webui         演示首页：已上线页面入口（探针字符串「文件体检」）；
- GET /webui/files   文件体检页骨架：上传 → 报告（风险徽标/汇总/命中明细）→
                     导出按钮（fetch 调 /v1/files/inspect、/v1/files/export，
                     纯浏览器端 FormData，无构建步骤、无外部依赖）；
- GET /webui/demo    演示控制页骨架（T4.3）：五场景清单 + 场景材料下载入口
                     （场景4 防注入 / 场景5 扫描件体检已就绪；一键加载进聊天
                     待 T5.2/T6.2）；
- GET /webui/demo/materials/{filename}  场景材料下载：**白名单文件名**（仅生成器
                     已登记的演示夹具），按需调用 benchmark.generator.materials
                     构建器物化到 data/fixtures/materials/ 后回传——与
                     ops/e2e_smoke、ops/demo/build_fixtures 同源同构建器。

不做登录（演示模式，M9 spec）；样式朴素但结构清晰。材料为合成演示数据
（seeded 冻结值），不含任何真实个人信息。
"""
from __future__ import annotations

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

#: 模板目录（包内固定；export_public 会整体拷贝源码树）
_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

#: 演示材料物化目录（构建物，不入库；与 e2e / build_fixtures CLI 同目录）
_DEMO_DIR = REPO_ROOT / "data" / "fixtures" / "materials"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

#: 页面清单（演示首页入口与 m9_webui 探针共用）
PAGES: tuple[dict[str, str], ...] = (
    {"path": "/webui/files", "title": "文件体检", "desc": "公开前体检报告 + 彻底删除式导出",
     "status": "已上线（T3.3）"},
    {"path": "/webui/demo", "title": "演示控制页", "desc": "五场景清单 + 场景材料下载（场景4 防注入 / 场景5 扫描件体检就绪）",
     "status": "骨架已上线（T4.3；一键加载 T5.2/T6.2）"},
    {"path": "/webui/chat", "title": "对话双屏", "desc": "脱敏对话 + 上游实际收到内容对照",
     "status": "待上线（T5.2）"},
    {"path": "/webui/dashboard", "title": "审计看板", "desc": "按部门/路由/拦截类别指标",
     "status": "待上线（T5.2）"},
)

#: 演示场景清单（§10 五场景；编号按任务单 T4.3——场景4=防注入、场景5=扫描件体检，
#: 与开发指令 §10 表的编号对照见 ops/demo/README.md）
DEMO_SCENES: tuple[dict, ...] = (
    {"no": "场景1", "title": "双屏对比", "desc": "脱敏对话＋上游实际收到内容对照",
     "materials": (), "status": "聊天页待上线（T5.2）"},
    {"no": "场景2", "title": "三份材料三路由",
     "desc": "普通公文→INTERNET／低保名单→GOVCLOUD／机密纪要→BLOCK 拦截",
     "materials": (ORDINARY_MATERIAL.filename, ROSTER_MATERIAL.filename,
                   CLASSIFIED_MATERIAL.filename),
     "status": "材料就绪；页面 T5.2"},
    {"no": "场景3", "title": "看板指标", "desc": "审计统计 + bench 报告数字对照",
     "materials": (), "status": "待上线（T5.2）"},
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
        """演示控制页骨架：五场景清单 + 场景材料下载（T4.3 场景4/5 就绪）。"""
        scenes = [
            {"no": s["no"], "title": s["title"], "desc": s["desc"],
             "status": s["status"],
             "materials": [{"filename": name, "href": f"/webui/demo/materials/{name}"}
                           for name in s["materials"]]}
            for s in DEMO_SCENES
        ]
        return templates.TemplateResponse(request, "demo.html",
                                          {"page_title": "演示控制页", "scenes": scenes})

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
