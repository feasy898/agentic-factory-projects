"""M9 webui 验收（T3.3 体检页 + T4.3 演示控制页 + T5.2 聊天页/看板页全量口径）。

运行::

    cd REPO_ROOT && PYTHONUTF8=1 ./.venv/Scripts/python.exe -m evals.m9_webui

exit 0 = 通过。M9 全量口径（开发指令 §6：四页 GET 200 + 探针字符串）中聊天页/
看板页由 T5.2 补全，本入口验收已上线面：

1. GET /webui        演示首页 200，探针「文件体检」与 /webui/files 入口在位；
2. GET /webui/files  体检页 200，骨架三要素探针齐全——上传控件（file-input）、
   体检按钮（inspect-btn）、导出按钮（export-btn），且指明两个 API 端点路径；
3. POST /v1/files/inspect（docx，seeded 身份证+手机号）→ 200 FileReport 契约形状
   （§5.5 字段齐全、fid 请求内自增、kind/sha256/risk_level/summary 正确）；
4. POST /v1/files/export（docx，mode=sanitize）→ 200，X-Report-Id 在位且登记表
   可查；导出物 python-docx 重开逐字扫描零残留；
5. xlsx 隐藏列体检：隐藏列内的敏感属性命中 → HIGH；导出物重开：隐藏列已整列
   删除（无 hidden 维度、无值），普通命中单元格删值；
6. pdf 体检+导出：种子身份证带页面定位框（render 坐标）；导出物重抽取零残留；
7. 错误形状：未知文件种类 → 400 unsupported_file_type 信封；非法导出 mode →
   400 bad_request；缺文件字段 → 422（FastAPI 校验面）；50MB 上限在服务层
   生效（FileTooLargeError）；
8. GET /webui/demo  演示控制页 200（T4.3）：五场景清单探针（场景4 防注入/
   场景5 扫描件体检）+ 场景材料下载链接 + 「载入聊天」一键入口在位；
9. GET /webui/demo/materials/{filename}  场景材料下载：白名单外 404；埋注版
   docx → 200 真实 docx 字节；合成扫描件 pdf → 200 且经 /v1/files/inspect
   报 kind=scan_pdf、身份证 ≥3、risk=HIGH（OCR 体检链路端到端可演示）；
10. GET /webui/demo/materials/{filename}/text（T5.2 一键载入聊天用）：白名单外
   404；白名单 docx → 200 JSON，text 含埋注段、与直接解析下载物逐字一致；
11. GET /webui/chat（T5.2 双屏对比页）：200，探针齐全——双栏标记
   「上游实际收到」+ /v1/chat/completions + /internal/anonymize +
   x-anongw-route + SSE 客户端标记（text/event-stream、[DONE]）+
   部门 Key 选择器 + x-anongw-session-id 续接口；
12. GET /webui/dashboard（T5.2 看板页）空库零态渲染：200，指标卡三槽位、
   <svg> 柱状图、审计明细空态提示在位；
13. 看板页数据渲染（23 条 seeded 混合事件注入内存审计）：指标卡数值
   （今日请求/今日拦截/累计/拦截率）与注入事实一致；三张手写 SVG 柱状图
   渲染（路由分布/Top 部门/命中类别）；BLOCK 行带 route 徽标
   （badge-block）；明细分页：page=1 显示 10 行 + 下一页，page=2 行集
    不同，page=999 钳位到末页，page_size=50 全量单页。
14. 聊天页 SSE 兼容（真实流式闭环）：临时端口起 mock 上游 + 网关实例
    （真实 config 语义 + 部门 Key）→ POST /v1/chat/completions
    stream=true（seeded PII prompt）→ 200 text/event-stream、
    x-anongw-route=INTERNET、[DONE] 收尾、delta 拼接为**还原版**
    （原值在位、占位符零残留、AI 标识尾注在）；mock 上游 ring buffer
    bytes 级零原值；随后 GET /webui/dashboard 在同一 app 上渲染出
    该请求事件（request_id 在表内）——页面 200 / 数据渲染 / SSE 兼容
    三断言同链闭环；GET /webui/chat 同实例 200。

网关进程内 ASGI 启动（主实例：真实 config/app.yaml + 内存审计，零外部依赖；
SSE 检查额外起进程内 mock 上游与临时端口）。
"""
from __future__ import annotations

import asyncio
import importlib
import io
import json
import os
import re
import socket
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("MOCK_KEY", "mock-demo-key")  # 上游 api_key_env（本 eval 不触上游）

from httpx import ASGITransport  # noqa: E402

from audit.models import AuditEvent  # noqa: E402
from audit.store import InMemoryAuditStore  # noqa: E402
from benchmark.generator.personas import load_corpus_config  # noqa: E402
from common.config import UpstreamCfg, load_app_config, load_dept_keys  # noqa: E402
from evals.thresholds import FILE_SIZE_MAX_BYTES  # noqa: E402
from filechannel.errors import FileTooLargeError  # noqa: E402
from filechannel.service import FileService  # noqa: E402
from gateway.app import create_app  # noqa: E402
from gateway.mock_upstream import MockUpstreamServer  # noqa: E402
from masking.mapper import RESTORE_PATTERN  # noqa: E402

RESULTS: list[tuple[bool, str]] = []

MASK_KEY = "cd" * 32

#: seeded 样例（eval 专用夹具，GB11643 校验位合法）
_ID17 = "46002219900307123"
_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_CODES = "10X98765432"
ID_A = _ID17 + _ID_CODES[sum(int(c) * w for c, w in zip(_ID17, _ID_WEIGHTS, strict=True)) % 11]
PHONE_A = "13800138000"
BANK_A = "6222020200112233451"          # 过 Luhn 的夹具卡号由下方 _luhn 补校验位
PERSON = "张三"

DOCX_TEXT = f"低保公示名单：{PERSON}，身份证号{ID_A}，联系电话{PHONE_A}。"


def _luhn(seed19: str) -> str:
    """19 位卡号：前 18 位给定，第 19 位补 Luhn 校验位。"""
    digits = [int(c) for c in seed19[:18]]

    def check(digits_: list[int]) -> int:
        total = 0
        for i, d in enumerate(reversed(digits_)):
            if i % 2 == 0:
                d *= 2
                if d > 9:
                    d -= 9
            total += d
        return (10 - total % 10) % 10

    return seed19[:18] + str(check(digits))


BANK_A = _luhn("6222020200112233451")


def _record(name: str, fn) -> None:
    try:
        detail = fn() or ""
        RESULTS.append((True, f"PASS  {name}" + (f" — {detail}" if detail else "")))
    except Exception as exc:  # noqa: BLE001 — 汇总所有失败后统一退出
        RESULTS.append((False, f"FAIL  {name} — {type(exc).__name__}: {exc}"))


def _build_docx() -> bytes:
    from docx import Document

    doc = Document()
    doc.add_paragraph(DOCX_TEXT)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _build_xlsx_with_hidden_col() -> bytes:
    """隐藏列 D 存敏感属性词 + 普通列存身份证/银行卡（隐藏列=假删除重灾区）。"""
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Sheet1"
    ws.append(["户主", "公民身份号码", "银行账户", "备注"])
    ws.append([PERSON, ID_A, BANK_A, "低保对象"])
    col_idx = ws["D1"].column
    ws.column_dimensions[get_column_letter(col_idx)].hidden = True
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _build_pdf() -> bytes:
    """经 config 坐标动态加载 pdf 写入库（与 seeded 夹具同源），单页两行种子值。"""
    pdfmod = importlib.import_module(str(load_corpus_config()["pdf_writer"]["module"]))
    doc = pdfmod.open()
    page = doc.new_page(width=595.0, height=842.0)
    page.insert_text((72.0, 90.0), f"行政处罚决定书\n当事人{PERSON}，身份证号{ID_A}",
                     fontname="china-s", fontsize=11)
    page.insert_text((72.0, 120.0), f"联系电话{PHONE_A}，尾号账户{BANK_A}",
                     fontname="china-s", fontsize=11)
    data = doc.tobytes(deflate=True, no_new_id=True)
    doc.close()
    return data


def _post_inspect(app: Any, data: bytes, filename: str,
                  content_type: str) -> httpx.Response:
    async def run() -> httpx.Response:
        async with httpx.AsyncClient(transport=ASGITransport(app=app),
                                     base_url="http://anongw.test") as client:
            return await client.post("/v1/files/inspect",
                                     files={"file": (filename, data, content_type)})
    return asyncio.run(run())


def _post_export(app: Any, data: bytes, filename: str,
                 content_type: str, mode: str = "sanitize") -> httpx.Response:
    async def run() -> httpx.Response:
        async with httpx.AsyncClient(transport=ASGITransport(app=app),
                                     base_url="http://anongw.test") as client:
            return await client.post("/v1/files/export", data={"mode": mode},
                                     files={"file": (filename, data, content_type)})
    return asyncio.run(run())


def _get(app: Any, path: str) -> httpx.Response:
    async def run() -> httpx.Response:
        async with httpx.AsyncClient(transport=ASGITransport(app=app),
                                     base_url="http://anongw.test") as client:
            return await client.get(path)
    return asyncio.run(run())


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_MIME = "application/pdf"

_FILE_REPORT_KEYS = {"file_id", "filename", "sha256", "kind", "pages",
                     "findings", "risk_level", "summary"}


def check_webui_index(app: Any) -> str:
    resp = _get(app, "/webui")
    assert resp.status_code == 200, f"status={resp.status_code}"
    html = resp.text
    for probe in ("文件体检", "/webui/files"):
        assert probe in html, f"探针缺失: {probe}"
    return "200；探针「文件体检」+ 体检页入口在位"


def check_webui_files_page(app: Any) -> str:
    resp = _get(app, "/webui/files")
    assert resp.status_code == 200, f"status={resp.status_code}"
    html = resp.text
    probes = ("file-input", "inspect-btn", "export-btn",
              "/v1/files/inspect", "/v1/files/export")
    missing = [p for p in probes if p not in html]
    assert not missing, f"骨架探针缺失: {missing}"
    return f"200；上传控件/体检按钮/导出按钮 + 两端点路径探针齐全（{len(probes)} 项）"


def check_webui_demo_page(app: Any) -> str:
    """演示控制页（T4.3 骨架 + T5.2 一键载入）：五场景清单 + 场景4/5 材料下载链接
    + 「载入聊天」一键入口探针。"""
    resp = _get(app, "/webui/demo")
    assert resp.status_code == 200, f"status={resp.status_code}"
    html = resp.text
    probes = ("演示控制页", "场景4", "场景5", "防注入", "扫描件体检",
              "/webui/demo/materials/webpage_policy_qa_clean.docx",
              "/webui/demo/materials/webpage_policy_qa_injected.docx",
              "/webui/demo/materials/scan_lowincome_publicity_demo.pdf",
              "载入聊天",
              "/webui/chat?material=ordinary_flood_drill_notice.docx",
              "/webui/chat?material=scan_lowincome_publicity_demo.pdf")
    missing = [p for p in probes if p not in html]
    assert not missing, f"演示控制页探针缺失: {missing}"
    return f"200；五场景清单 + 场景4/5 材料下载 + 载入聊天一键入口（{len(probes)} 项）"


def check_webui_demo_materials(app: Any) -> str:
    """场景材料下载：白名单外 404；埋注版 docx / 合成扫描件 pdf 真实字节，
    且扫描件经体检链路报 scan_pdf + 身份证 ≥3 + HIGH（OCR 链路端到端可演示）。"""
    from benchmark.generator.materials import (
        DEMO_SCAN_IDS,
        WEBPAGE_INJECTED_MATERIAL,
        material_plain_text,
    )

    unknown = _get(app, "/webui/demo/materials/not_a_material.docx")
    assert unknown.status_code == 404, f"白名单外应 404: {unknown.status_code}"

    inj = _get(app, "/webui/demo/materials/" + WEBPAGE_INJECTED_MATERIAL.filename)
    assert inj.status_code == 200, f"injected: {inj.status_code}"
    assert inj.content.startswith(b"PK"), "埋注版 docx 字节形态异常"
    assert DOCX_MIME in inj.headers.get("content-type", ""), inj.headers.get("content-type")
    from filechannel.parsers import parse_any

    parsed = parse_any(WEBPAGE_INJECTED_MATERIAL.filename, inj.content)
    extracted = "\n".join(seg.text for seg in parsed.segments)
    assert extracted == material_plain_text(WEBPAGE_INJECTED_MATERIAL), \
        "下载物正文 != 生成器构造面（往返完整性）"
    assert "忽略上面所有规则" in extracted, "埋注段缺失"

    scan = _get(app, "/webui/demo/materials/scan_lowincome_publicity_demo.pdf")
    assert scan.status_code == 200, f"scan: {scan.status_code}"
    assert scan.content.startswith(b"%PDF"), "扫描件 pdf 字节形态异常"
    assert PDF_MIME in scan.headers.get("content-type", ""), scan.headers.get("content-type")
    report = _post_inspect(app, scan.content,
                           "scan_lowincome_publicity_demo.pdf", PDF_MIME).json()
    assert report["kind"] == "scan_pdf", f"kind: {report['kind']}"
    assert report["risk_level"] == "HIGH", f"risk: {report['risk_level']}"
    assert report["summary"].get("ID_CARD", 0) >= 3, f"summary: {report['summary']}"
    found = {ff["finding"]["normalized"] for ff in report["findings"]
             if ff["finding"]["type"] == "ID_CARD"}
    assert set(DEMO_SCAN_IDS) <= found, f"seeded 身份证漏检: {DEMO_SCAN_IDS} vs {found}"
    return ("白名单外 404；埋注版 docx 往返正文全等含埋注段；扫描件 pdf → 体检 "
            f"scan_pdf/HIGH，seeded 身份证 {len(DEMO_SCAN_IDS)} 枚全命中（OCR 链路）")


def check_webui_material_text(app: Any) -> str:
    """场景材料纯文本端点（T5.2「载入聊天」数据源）：白名单外 404；白名单 docx
    → 200 JSON，text 含埋注段且与直接解析下载物逐字一致（同源同字节）。"""
    from benchmark.generator.materials import (
        WEBPAGE_INJECTED_MATERIAL,
        material_plain_text,
    )

    unknown = _get(app, "/webui/demo/materials/not_a_material.docx/text")
    assert unknown.status_code == 404, f"白名单外应 404: {unknown.status_code}"
    resp = _get(app, "/webui/demo/materials/" + WEBPAGE_INJECTED_MATERIAL.filename + "/text")
    assert resp.status_code == 200, f"status={resp.status_code}"
    body = resp.json()
    assert set(body) >= {"filename", "text"}, f"契约字段缺失: {sorted(body)}"
    assert "忽略上面所有规则" in body["text"], "埋注段缺失"
    assert body["text"] == material_plain_text(WEBPAGE_INJECTED_MATERIAL), \
        "text 端点与生成器构造面不一致"
    return "白名单外 404；注入版 docx text 含埋注段且与生成器构造面逐字一致"


#: 聊天页探针（T5.2 双屏对比页）：双栏 + 两 API 端点 + route 头 + SSE 客户端标记
_CHAT_PROBES: tuple[str, ...] = (
    "上游实际收到",                 # 右栏标题（§10 场景1）
    "/v1/chat/completions",
    "/internal/anonymize",
    "x-anongw-route",               # route 徽标数据源
    "content_blocked",              # 403 拦截卡渲染分支
    "text/event-stream",            # SSE 流式客户端标记
    "[DONE]",
    "x-anongw-session-id",          # 会话续接（多轮稳定脱敏）
    "dk_5e6f7a8b",                  # 演示部门 Key 选择器（民政局）
)


def check_webui_chat_page(app: Any) -> str:
    resp = _get(app, "/webui/chat")
    assert resp.status_code == 200, f"status={resp.status_code}"
    html = resp.text
    missing = [p for p in _CHAT_PROBES if p not in html]
    assert not missing, f"聊天页探针缺失: {missing}"
    return f"200；双屏探针齐全（上游实收/两端点/route/SEC/部门Key，{len(_CHAT_PROBES)} 项）"


def _dashboard_empty_probes(app: Any) -> None:
    """空库零态：200 + 三指标卡槽位 + SVG 容器 + 明细空态提示。"""
    resp = _get(app, "/webui/dashboard")
    assert resp.status_code == 200, f"status={resp.status_code}"
    html = resp.text
    probes = ("今日请求", "今日拦截", "今日拦截率", "累计事件",
              "路由分布", "Top 部门", "命中类别",
              "<svg", 'id="chart-routes"', 'id="chart-depts"',
              "审计明细", "暂无审计事件")
    missing = [p for p in probes if p not in html]
    assert not missing, f"看板零态探针缺失: {missing}"
    assert html.count("<svg") == 3, f"三张 SVG 柱状图应各一张: {html.count('<svg')}"


def _seed_audit_events(store: InMemoryAuditStore, n: int = 23) -> list[AuditEvent]:
    """注入 n 条混合审计事件（三部门/三路由/含拦截/含 flags；预览全占位符形态）。

    时间/编号按 i 递增（后写更新），部门计数确定：民政局 10 > 县政府办 7 > 某镇 6
    （Top 部门断言确定）；路由计数确定：INTERNET/GOVCLOUD 各 8、BLOCK 7。
    """
    base = datetime.now(UTC) - timedelta(minutes=40)
    events: list[AuditEvent] = []
    for i in range(n):
        route = ("INTERNET", "GOVCLOUD", "BLOCK")[i % 3]
        dept = "民政局" if i < 10 else ("县政府办" if i < 17 else "某镇")
        ev = AuditEvent(
            ts=base + timedelta(seconds=i * 15),
            request_id=f"req_m9_{i:02d}",
            session_id=f"sess_m9_{i % 4}",
            dept=dept, route=route, blocked=(route == "BLOCK"),
            reasons=(["CLASSIFICATION_MARK"] if route == "BLOCK" else []),
            class_counts={"ID_CARD": 2, "PHONE_MOBILE": 3},
            prompt_preview=f"〔身份证·m9e{i:04d}〕提交的〔手机号·m9f{i:04d}〕材料",
            response_preview="" if route == "BLOCK" else f"已受理〔人名·m9g{i:04d}〕的申请。",
            upstream=None if route == "BLOCK" else "internet_mock",
            latency_ms=12 + i,
            flags=["injection"] if i == 7 else [],
        )
        events.append(ev)
    for ev in events:
        store.append(ev)          # InMemoryAuditStore.append 会跑零明文硬闸（预览无罪值）
    return events


def _page_rows(html: str) -> list[str]:
    return re.findall(r'[^>]+</td>\s*<td class="rid">(req_m9_\d\d)', html)


def check_webui_dashboard_render(app: Any, store: InMemoryAuditStore) -> str:
    """看板页数据渲染断言（T5.2）：注入 23 条事件后分页渲染 + KPI + 三图 + 徽标。"""
    _seed_audit_events(store, 23)

    def _kpi(html: str, kpi_id: str) -> int:
        m = re.search(rf'id="{kpi_id}">(\d+)<', html)
        assert m, f"指标卡 {kpi_id} 缺失或不含数值"
        return int(m.group(1))

    # ── 指标卡：与注入事实逐项一致 ──
    html = _get(app, "/webui/dashboard").text
    assert _kpi(html, "kpi-today-total") == 23, "今日请求数不符"
    assert _kpi(html, "kpi-today-blocked") == 7, "今日拦截数不符"
    assert _kpi(html, "kpi-total") == 23, "累计事件数不符"
    assert "30.4%" in html, "今日拦截率（7/23）不符"
    assert 'id="kpi-today-blocked"' in html

    # ── 三张手写 SVG 柱状图 ──
    assert html.count("<svg") == 3, f"SVG 图数量: {html.count('<svg')}"
    depts_chart = re.search(r'id="chart-depts">(.*?)</div>', html, re.S)
    assert depts_chart and "民政局" in depts_chart.group(1), "Top 部门图缺 Top1（民政局）"
    routes_chart = html.split('id="chart-routes">')[1].split("</div>")[0]
    for route in ("INTERNET", "GOVCLOUD", "BLOCK"):
        assert route in routes_chart, f"路由分布图缺 {route}"
    # ── route 徽标（BLOCK 行） ──
    assert "badge-block" in html and "badge-internet" in html, "route 徽标缺失"

    # ── 分页：10/10/3 三页 + 越界钳位 + 换页大小 ──
    page1 = _get(app, "/webui/dashboard?page=1").text
    rows1 = _page_rows(page1)
    assert len(rows1) == 10, f"第 1 页行数: {len(rows1)}"
    assert rows1[0] == "req_m9_22", f"第 1 页首行应为最新: {rows1[0]}"
    assert "req_m9_13" in rows1 and "req_m9_12" not in page1, "第 1 页行集越界"
    assert "下一页" in page1

    page2 = _get(app, "/webui/dashboard?page=2").text
    rows2 = _page_rows(page2)
    assert len(rows2) == 10 and rows2[0] == "req_m9_12", f"第 2 页行集: {rows2[:1]}"
    assert "req_m9_22" not in page2, "第 2 页不应含第 1 页行"

    page_clamp = _get(app, "/webui/dashboard?page=999").text
    rows3 = _page_rows(page_clamp)
    assert len(rows3) == 3 and rows3[0] == "req_m9_02", f"越界页码应钳位到末页: {rows3}"
    assert "共 23 条" in page_clamp

    page_big = _get(app, "/webui/dashboard?page=1&page_size=50").text
    assert len(_page_rows(page_big)) == 23, "page_size=50 应单页全量"
    return ("23 事件：KPI 23/7/23+30.4%；三 SVG 图（部门 Top=民政局/三路由）；"
            "badge 徽标在位；分页 10/10/3 + page=999 钳位 + page_size=50")


def check_webui_dashboard_initial(app: Any) -> str:
    _dashboard_empty_probes(app)
    return "空库零态：200 + 三指标卡 + 三 SVG 容器 + 明细空态提示"


DEMO_KEY_T52 = "dk_5e6f7a8b"          # 民政局（.env.example 演示明文，哈希在 config/dept_keys.yaml）
CHAT_SSE_TEXT = f"居民{PERSON}的身份证号{ID_A}，手机号{PHONE_A}，请核对低保申领材料。"
PHONE_A_T52 = PHONE_A                  # PHONE_A = "13800138000"（模块夹具，同归一化参考）
LABEL_TAIL = "\n" + "本内容由AI生成"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _post_chat_stream(app: Any, text: str, *, session: str) -> tuple[int, dict[str, str], str]:
    """模拟聊天页 JS 的流式请求（Bearer 部门 Key + x-anongw-session-id）。"""

    async def run() -> tuple[int, dict[str, str], str]:
        async with httpx.AsyncClient(transport=ASGITransport(app=app),
                                     base_url="http://anongw.test") as client:
            async with client.stream(
                    "POST", "/v1/chat/completions",
                    json={"model": "mock-chat",
                          "messages": [{"role": "user", "content": text}],
                          "stream": True},
                    headers={"Authorization": f"Bearer {DEMO_KEY_T52}",
                             "x-anongw-session-id": session}) as resp:
                raw = ""
                async for chunk in resp.aiter_text():
                    raw += chunk
                return resp.status_code, dict(resp.headers), raw

    return asyncio.run(run())


def check_webui_chat_sse_roundtrip(app: Any) -> str:
    """T5.2 SSE 兼容闭环（聊天页数据面真实跑通，非探针字符串）：

    临时端口 mock 上游 + 独立网关实例 → stream=true 请求 seeded PII prompt →
    200 text/event-stream / route 头 / [DONE] 收尾 / delta 拼接=还原版
    （原值复位、占位符零残留、AI 标识尾注）→ mock ring bytes 级零原值 →
    同一实例 GET /webui/chat 与 /webui/dashboard 均 200 且看板渲染出该请求事件。
    """
    port = _free_port()
    srv = MockUpstreamServer(port, name="internet_mock", models=["mock-chat"]).start()
    store = InMemoryAuditStore()
    try:
        cfg = load_app_config().model_copy(update={"upstreams": [UpstreamCfg(
            name="internet_mock", base_url=f"http://127.0.0.1:{port}/v1",
            api_key_env="MOCK_KEY", models=["mock-chat"], route="INTERNET",
        )]})
        app2 = create_app(cfg=cfg, mask_key=MASK_KEY, dept_key_digests=load_dept_keys(),
                          audit_store=store)
        status, headers, raw = _post_chat_stream(app2, CHAT_SSE_TEXT, session="sess_m9_sse")

        assert status == 200, f"stream status={status} body={raw[:200]!r}"
        assert "text/event-stream" in headers.get("content-type", ""), \
            f"content-type={headers.get('content-type')}"
        assert headers.get("x-anongw-route") == "INTERNET", \
            f"route header={headers.get('x-anongw-route')}"
        assert headers.get("x-anongw-ai-label") == "1", "AI 标识头缺失"
        request_id = headers.get("x-anongw-request-id", "")
        assert request_id.startswith("req_"), f"request-id={request_id}"

        # SSE 帧解析（与聊天页 JS 同规则：空行分帧 + data: 行 + [DONE] 收尾）
        frames = [f for f in raw.split("\n\n") if f.strip()]
        assert frames, "SSE 帧为空"
        assert any(line.strip() == "data: [DONE]" for f in frames for line in f.splitlines()), \
            "缺 [DONE] 收尾"
        events = []
        for frame in frames:
            for line in frame.splitlines():
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if payload != "[DONE]":
                    events.append(json.loads(payload))
        deltas = [e["choices"][0]["delta"] for e in events if e.get("choices")]
        content = "".join(d.get("content", "") for d in deltas
                          if isinstance(d.get("content"), str))
        assert ID_A in content and PHONE_A_T52 in content, \
            f"还原版缺原值: {content[:120]!r}"
        # 占位符形状零残留（RESTORE_PATTERN = 〔标签·hex8-10〕）；注意 mock 回显前缀
        # 〔Mock上游回显〕不匹配该形态，不算泄漏。
        assert RESTORE_PATTERN.search(content) is None, \
            f"占位符泄漏到客户端流: {content[:120]!r}"
        assert content.endswith(LABEL_TAIL), f"AI 标识尾注缺失: ...{content[-30:]!r}"

        # 上游侧：ring buffer 收到的应全为占位符（bytes 级零原值）
        ring = httpx.get(f"{srv.base_url}/admin/text", timeout=5.0).text
        for value in (ID_A, PHONE_A_T52, PERSON):
            assert value not in ring, f"上游收到原值: {value}"

        # 同实例页面：聊天页 200 + 看板渲染出本请求事件
        chat = _get(app2, "/webui/chat")
        assert chat.status_code == 200, f"chat status={chat.status_code}"
        dash = _get(app2, "/webui/dashboard").text
        assert request_id in dash, "看板明细缺本请求事件"
        assert "民政局" in dash and "INTERNET" in dash, "看板缺部门/路由渲染"
        assert 'id="kpi-total">1<' in dash, "累计事件应为 1"
        return (f"200 SSE：{len(frames)} 帧/[DONE]/还原版（{len(content)} 字符，零占位符泄漏）；"
                f"上游 ring 零原值；看板渲染 {request_id}（民政局·INTERNET）")
    finally:
        srv.stop()


def check_inspect_docx(app: Any) -> str:
    resp = _post_inspect(app, _build_docx(), "低保公示.docx", DOCX_MIME)
    assert resp.status_code == 200, f"status={resp.status_code} body={resp.text[:200]!r}"
    report = resp.json()
    assert _FILE_REPORT_KEYS <= set(report), f"契约字段缺失: {_FILE_REPORT_KEYS - set(report)}"
    assert report["kind"] == "docx" and report["filename"] == "低保公示.docx"
    assert len(report["sha256"]) == 64 and report["file_id"].startswith("file_")
    summary = report["summary"]
    assert summary.get("ID_CARD", 0) >= 1 and summary.get("PHONE_MOBILE", 0) >= 1, \
        f"seeded PII 漏检: {summary}"
    assert report["risk_level"] == "MID", f"风险分级: {report['risk_level']}"
    fids = [ff["finding"]["fid"] for ff in report["findings"]]
    assert fids == [f"f_{i:04d}" for i in range(1, len(fids) + 1)], f"fid 编号: {fids}"
    assert any(ff["finding"]["type"] == "PERSON" for ff in report["findings"]), "人名未检出"
    return (f"200 FileReport；summary={summary}；fid 请求内自增 {len(fids)} 条；"
            f"risk={report['risk_level']}")


def check_export_docx(app: Any) -> str:
    from docx import Document

    payload = _build_docx()
    resp = _post_export(app, payload, "低保公示.docx", DOCX_MIME)
    assert resp.status_code == 200, f"status={resp.status_code} body={resp.text[:200]!r}"
    report_id = resp.headers.get("x-report-id")
    assert report_id and report_id.startswith("file_"), f"X-Report-Id: {report_id}"
    assert DOCX_MIME in resp.headers.get("content-type", ""), resp.headers.get("content-type")
    reopened = Document(io.BytesIO(resp.content))
    text = "\n".join(p.text for p in reopened.paragraphs)
    for value in (ID_A, PHONE_A, PERSON):
        assert value not in text, f"导出物残留原值: {value}"
    assert "低保公示名单" in text, "非命中文本应保留（删除式而非清空全文）"
    return f"200；X-Report-Id={report_id}；重开扫描身份证/手机号/人名零残留；未命中文本保留"


def check_xlsx_hidden_col(app: Any) -> str:
    from openpyxl import load_workbook

    payload = _build_xlsx_with_hidden_col()
    resp = _post_inspect(app, payload, "roster.xlsx", XLSX_MIME)
    assert resp.status_code == 200, f"status={resp.status_code} body={resp.text[:200]!r}"
    report = resp.json()
    assert report["kind"] == "xlsx"
    assert report["risk_level"] == "HIGH", f"隐藏列敏感属性应为 HIGH: {report['risk_level']}"
    summary = report["summary"]
    assert summary.get("SENSITIVE_ATTR", 0) >= 1 and summary.get("ID_CARD", 0) >= 1 \
        and summary.get("BANK_CARD", 0) >= 1, f"summary 漏检: {summary}"
    assert any(ff["location"] == "Sheet1!D2" for ff in report["findings"]), \
        f"隐藏列定位缺失: {[ff['location'] for ff in report['findings']]}"

    resp = _post_export(app, payload, "roster.xlsx", XLSX_MIME)
    assert resp.status_code == 200, f"export status={resp.status_code} {resp.text[:200]!r}"
    wb = load_workbook(io.BytesIO(resp.content))
    ws = wb["Sheet1"]
    hidden = [d.hidden for d in ws.column_dimensions.values()] + \
             [d.hidden for d in ws.row_dimensions.values()]
    assert not any(hidden), f"导出物仍存在隐藏维度: {hidden}"
    values = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    for value in (ID_A, BANK_A, "低保对象", PERSON):
        assert not any(value in v for v in values), f"导出物残留: {value}"
    return "体检 HIGH（隐藏列 D2 敏感属性+身份证+银行卡）；导出物无隐藏维度、seeded 值零残留"


def check_pdf_roundtrip(app: Any) -> str:
    payload = _build_pdf()
    resp = _post_inspect(app, payload, "决定书.pdf", PDF_MIME)
    assert resp.status_code == 200, f"status={resp.status_code} body={resp.text[:200]!r}"
    report = resp.json()
    assert report["kind"] == "pdf" and report["pages"] >= 1
    assert report["summary"].get("ID_CARD", 0) >= 1 and report["summary"].get("PHONE_MOBILE", 0) >= 1
    located = [ff for ff in report["findings"] if ff["finding"]["type"] == "ID_CARD"]
    assert located and located[0]["bbox"] is not None, "身份证命中缺页面定位框"
    x0, y0, x1, y1 = located[0]["bbox"]
    assert 0 <= x0 < x1 and 0 <= y0 < y1, f"bbox 非法: {located[0]['bbox']}"

    resp = _post_export(app, payload, "决定书.pdf", PDF_MIME)
    assert resp.status_code == 200, f"export status={resp.status_code} {resp.text[:200]!r}"
    pdfmod = importlib.import_module(str(load_corpus_config()["pdf_writer"]["module"]))
    doc = pdfmod.open(stream=resp.content, filetype="pdf")
    text = "".join(p.get_text("text") for p in doc)
    doc.close()
    for value in (ID_A, PHONE_A, BANK_A, PERSON):
        assert value not in text, f"导出物重抽取残留: {value}"
    assert "行政处罚决定书" in text, "非命中文本应保留（涂删式而非清空全文）"
    return f"体检 bbox 在位（{located[0]['bbox']}）；导出物重抽取身份证/手机/卡号/人名零残留"


def check_error_shapes(app: Any) -> str:
    # 未知文件种类 → 400 unsupported_file_type 信封
    resp = _post_inspect(app, "这不是文件，是纯文本".encode(), "note.txt", "text/plain")
    assert resp.status_code == 400, f"txt inspect: {resp.status_code}"
    assert resp.json()["error"]["code"] == "unsupported_file_type", resp.text[:200]
    # 非法导出 mode → 400 bad_request
    resp = _post_export(app, _build_docx(), "a.docx", DOCX_MIME, mode="hide")
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "bad_request", resp.text[:200]
    # 缺文件字段 → 422（FastAPI 校验面）
    async def run_missing() -> httpx.Response:
        async with httpx.AsyncClient(transport=ASGITransport(app=app),
                                     base_url="http://anongw.test") as client:
            return await client.post("/v1/files/inspect", data={})
    resp = asyncio.run(run_missing())
    assert resp.status_code == 422, f"missing file: {resp.status_code}"
    # 50MB 上限（服务层硬闸，直接构造超限字节流）
    svc = FileService(load_app_config())
    try:
        svc.inspect_bytes("big.bin", b"\x00" * (FILE_SIZE_MAX_BYTES + 1))
    except FileTooLargeError:
        pass
    else:  # pragma: no cover — 硬闸失效
        raise AssertionError("50MB 上限未生效")
    return "400 unsupported_file_type / 400 bad_request / 422 缺文件 / 50MB 硬闸生效"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    cfg = load_app_config()  # 真实 config/app.yaml（含 pdf_engine_module）
    audit = InMemoryAuditStore()
    app = create_app(cfg=cfg, mask_key=MASK_KEY,
                     dept_key_digests={"民政局": "0" * 64},
                     audit_store=audit)

    _record("webui 首页（/webui）", lambda: check_webui_index(app))
    _record("体检页骨架（/webui/files）", lambda: check_webui_files_page(app))
    _record("演示控制页（/webui/demo，T4.3+载入聊天）", lambda: check_webui_demo_page(app))
    _record("演示材料下载（白名单/往返/扫描件体检）", lambda: check_webui_demo_materials(app))
    _record("场景材料 text 端点（载入聊天）", lambda: check_webui_material_text(app))
    _record("聊天页双屏（/webui/chat，T5.2）", lambda: check_webui_chat_page(app))
    _record("看板空库零态（/webui/dashboard）", lambda: check_webui_dashboard_initial(app))
    _record("inspect docx（FileReport 契约）", lambda: check_inspect_docx(app))
    _record("export docx（X-Report-Id + 零残留）", lambda: check_export_docx(app))
    _record("xlsx 隐藏列体检+删列导出", lambda: check_xlsx_hidden_col(app))
    _record("pdf 体检（bbox）+涂删导出零残留", lambda: check_pdf_roundtrip(app))
    _record("错误形状（400/422/50MB 闸）", lambda: check_error_shapes(app))
    _record("看板数据渲染（KPI/三图/徽标/分页）", lambda: check_webui_dashboard_render(app, audit))
    _record("聊天页 SSE 兼容闭环（stream=还原+看板落事件）",
            lambda: check_webui_chat_sse_roundtrip(app))

    print("=" * 64)
    print("evals.m9_webui（T3.3 体检页 + T4.3 演示控制页 + T5.2 聊天页/看板页全量）")
    print("=" * 64)
    for _ok, line in RESULTS:
        print(line)
    passed = sum(1 for ok, _ in RESULTS if ok)
    print("-" * 64)
    print(f"m9_webui: {passed}/{len(RESULTS)} 检查通过")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
