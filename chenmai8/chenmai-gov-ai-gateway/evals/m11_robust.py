"""M11 健壮性验收入口（批次7 T7.2）：畸形输入优雅拒绝 + 非法 SSE 帧不失能 + 并发 50 零串扰。

运行::

    cd REPO_ROOT && PYTHONUTF8=1 ./.venv/Scripts/python.exe -m evals.m11_robust

exit 0 = 通过。固化 §11 风险 8「大文件/畸形输入打崩网关」的防护门：任何畸形输入
都不许崩网关（500 裸奔/异常栈/进程退出）或挂网关（客户端超时仍未应答），畸形
请求按语义落 4xx + §5.6 错误信封（error.code/message/reasons 齐全）。

拓扑（全部本地真实 TCP；端口与 e2e :9000/:8901/:8902/:9010 及 GPU 隧道 :9004 错开）::

    客户端(本脚本) ──► 主网关 :9012 ─┬─ INTERNET ──► mock 上游 :8911（进程内）
                                     └─ GOVCLOUD ──► mock 上游 :8912（进程内）
    客户端 ──► 坏上游网关 :9013 ── INTERNET ──► 行为可控坏上游 :8913
    （非法 SSE 帧专用：垃圾 JSON 帧 / 不可解码字节 / 超长无换行行 / 流中途中断）

主网关独立临时审计库（tmp/m11_robust_audit.db，SQLite 写队列=生产落库形态），
不碰 config 指定的 data/audit.db；坏上游网关用进程内审计表。会话注册表均为
进程内实例（不落盘）。

检查项（①畸形输入 ②并发极端负载 ③以下断言即本模块固化面）：

- body 畸形（主网关）：>10MB body（Content-Length 与 chunked 两形态）→ 413
  payload_too_large（超限先有界排空再应答，客户端拿到完整 413 而非连接重置）；
  深嵌套 JSON（可解析深度 / 解析器爆栈深度）→ 400；JSON 数组体 → 400（T7.2 前
  在 body.get 处 500 裸奔，加固点）；非法 JSON → 400；空/缺 messages、非对象
  消息 → 400——以上全部信封形状齐全，且 mock 上游 ring 零新增（畸形请求不出网）；
- 超长单行：单条文本超 GATEWAY_TEXT_MAX_CHARS → 400（不进检测面拖垮延迟预算）；
  帽内 15 万字符单行 → 200 照常回显（帽不过度伤正常长文）；/internal/detect
  超帽 → 400；
- 文件通道畸形：>50MB 上传 inspect/export → 413（Header 预检 + multipart 尺寸
  预检 + 实读复核三闸，超限不读入内存）；假 docx（非 zip 字节）→ 422
  file_parse_error；不支持的扩展名 → 400 unsupported_file_type；
  合法小 docx 照常 200 体检（畸形不伤正常通道）；
- 非法 SSE 帧（坏上游 ×4 模式）：垃圾 JSON 帧（协议透传不吞不猜）/ 不可解码
  字节（丢行）/ 12MB 单行洪泛（行帽丢弃，客户端不再收到 12MB 垃圾）/ 流中途
  断连（SSE error 事件收尾 + 审计 flag=upstream_stream_interrupted）——每模式
  流都有界终止、审计落账，事后坏上游网关 healthz + 非流式合法请求仍 200
  （流式异常不毒化网关）；
- 并发 50（mock 上游）：45 独值会话 + 5 同值异会话并发打出——全 200；
  零串扰三面：客户端响应 i 只含自己的原值（其余 45 值零出现）、上游 ring
  50 条占位符与期望集合一一对应（同值异会话 → 5 个互异占位符=会话隔离）、
  审计恰 50 行 request_id 互异（不错行）且逐事件只含本会话占位符；库文件
  bytes 级扫描 46 个原值零命中；同会话重发占位符全等（并发下会话稳定）；
  事后 healthz 200。
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import re
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("MOCK_KEY", "mock-demo-key")  # 上游 api_key_env 在请求期解析

from audit.store import InMemoryAuditStore, assert_db_no_raw_pii  # noqa: E402
from audit.writer import SqliteAuditWriter  # noqa: E402
from common.config import load_app_config, load_dept_keys  # noqa: E402
from evals.thresholds import (  # noqa: E402
    FILE_SIZE_MAX_BYTES,
    GATEWAY_BODY_MAX_BYTES,
    GATEWAY_JSON_MAX_DEPTH,
    GATEWAY_SSE_LINE_MAX_BYTES,
    GATEWAY_TEXT_MAX_CHARS,
    M11_CONCURRENCY_REQUESTS,
    M11_CONCURRENCY_TIMEOUT_S,
    M11_MALFORMED_TIMEOUT_S,
)
from gateway.app import create_app  # noqa: E402
from gateway.mock_upstream import ECHO_MARKER, MockUpstreamServer  # noqa: E402
from masking.mapper import RESTORE_PATTERN, SessionRegistry  # noqa: E402
from recognizers.models import EntityClass  # noqa: E402

# ── 固定拓扑与凭据（对齐 config/dept_keys.yaml；端口全专用）─────────────
MOCK_PORT_INTERNET = 8911
MOCK_PORT_GOVCLOUD = 8912
BAD_UPSTREAM_PORT = 8913
GATEWAY_PORT = 9012
BAD_GATEWAY_PORT = 9013

DEPT = "民政局"
DEMO_KEY = "dk_5e6f7a8b"        # 演示明文；config/dept_keys.yaml 只存其 sha256
MASK_KEY = "ab" * 32

TMP_DIR = REPO_ROOT / "tmp"
AUDIT_DB = TMP_DIR / "m11_robust_audit.db"

READY_TIMEOUT_S = 20.0
FILES_TIMEOUT_S = 120.0         # 51MB 上传的宽限（挂死即 FAIL 的上界）
AUDIT_SETTLE_TIMEOUT_S = 10.0

#: 占位符形状（上游侧/审计预览侧提取用）
PLACEHOLDER_RE = re.compile(r"〔手机号·([0-9a-f]{8,12})〕")

RESULTS: list[tuple[str, str, str]] = []   # (检查名, PASS/FAIL, 详情)

AI_LABEL = "本内容由AI生成"      # config/app.yaml ai_label（非流式尾注形态）


# ── 通用小工具 ────────────────────────────────────────────────────────
def _record(name: str, fn) -> None:
    try:
        detail = fn() or ""
        RESULTS.append((name, "PASS", detail))
    except Exception as exc:  # noqa: BLE001 — 汇总所有失败后统一退出
        RESULTS.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))


def _assert_port_free(port: int) -> None:
    with socket.socket() as sock:
        sock.settimeout(0.3)
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"port {port} already occupied — 残留进程自检 netstat -ano")


def _wait_ready(port: int, label: str, *, timeout: float = READY_TIMEOUT_S) -> None:
    """轮询自起服务 /healthz 直到就绪（显式 127.0.0.1 + int 端口，无插值面）。"""
    import http.client

    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            conn = http.client.HTTPConnection("127.0.0.1", int(port), timeout=1.0)
            try:
                conn.request("GET", "/healthz")
                resp = conn.getresponse()
                body = json.loads(resp.read().decode("utf-8"))
            finally:
                conn.close()
            if resp.status == 200 and body.get("ok") is True:
                return
            last = f"healthz status={resp.status}"
        except Exception as exc:  # noqa: BLE001 — 启动窗口内连接失败属预期
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(0.1)
    raise RuntimeError(f"{label} 就绪超时（{timeout}s）：{last}")


def _start_server(app: Any, port: int, name: str, *, quiet: bool = False) -> tuple[uvicorn.Server, threading.Thread]:
    _assert_port_free(port)
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=port,
        # quiet：坏上游的故意中途断流会以 ERROR 级打异常栈（预期行为），静音之
        log_level="critical" if quiet else "warning", log_config=None, access_log=False,
    ))
    thread = threading.Thread(target=server.run, name=name, daemon=True)
    thread.start()
    _wait_ready(port, label=f"{name}:{port}")
    return server, thread


def _stop_server(ctx: dict[str, Any], key: str) -> None:
    server = ctx.get(key)
    thread = ctx.get(f"{key}_thread")
    if server is not None:
        server.should_exit = True
    if thread is not None:
        thread.join(timeout=5.0)


def _drop_db(db_path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)


def _auth(session: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {DEMO_KEY}", "x-anongw-session-id": session}


def _chat_body(text: str, *, stream: bool = False,
               model: str | None = "mock-chat") -> dict[str, Any]:
    body: dict[str, Any] = {"messages": [{"role": "user", "content": text}], "stream": stream}
    if model is not None:
        body["model"] = model
    return body


def _assert_envelope(resp: httpx.Response, want_status: int, code: str | None = None) -> dict[str, Any]:
    """§5.6 错误信封形状断言：4xx + error.code/message/reasons 齐全。"""
    if resp.status_code != want_status:
        raise AssertionError(f"status={resp.status_code}（期望 {want_status}） body={resp.text[:160]!r}")
    if not 400 <= resp.status_code < 500:
        raise AssertionError(f"非 4xx: {resp.status_code}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise AssertionError(f"响应非 JSON 信封: {resp.text[:160]!r}") from exc
    err = payload.get("error")
    if not isinstance(err, dict):
        raise AssertionError(f"缺 error 对象: {payload}")
    if not isinstance(err.get("code"), str) or not err["code"]:
        raise AssertionError(f"error.code 缺失: {err}")
    if not isinstance(err.get("message"), str) or not err["message"]:
        raise AssertionError(f"error.message 缺失: {err}")
    if not isinstance(err.get("reasons"), list):
        raise AssertionError(f"error.reasons 缺失: {err}")
    if code is not None and err["code"] != code:
        raise AssertionError(f"error.code={err['code']}（期望 {code}）")
    return err


def _wait_audit_rows(store: Any, expected: int, *, timeout: float = AUDIT_SETTLE_TIMEOUT_S) -> None:
    """等待审计行数到位（SQLite 写队列批量落库/流式随流收尾都留结算窗口）。"""
    deadline = time.monotonic() + timeout
    while len(store) < expected and time.monotonic() < deadline:
        time.sleep(0.1)
    if len(store) < expected:
        raise AssertionError(f"审计行数 {len(store)} < 期望 {expected}")


def _deep_json(depth: int) -> str:
    """depth 层嵌套的 JSON 文本（{\"a\": 包裹）。"""
    s = "0"
    for _ in range(depth):
        s = '{"a":' + s + "}"
    return s


# ── 坏上游（非法 SSE 帧专用；行为按模式切换）──────────────────────────
def _gen_garbage_json(_last: str) -> StreamingResponse:  # noqa: ARG001 — 形参统一签名
    async def gen():
        for _ in range(3):
            yield "data: {这不是JSON的垃圾帧 garbage-frame}\n\n"
        yield ('data: {"choices":[{"index":0,"delta":{"content":"尾帧"},'
               '"finish_reason":"stop"}]}\n\n')
        yield "data: [DONE]\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


def _gen_undecodable(_last: str) -> StreamingResponse:
    async def gen():
        yield b"\xff\xfe not-utf8-line\n\n"             # 非 data 行（应跳过）
        yield b"data: \xff\xfe\x00broken\n\n"           # data 行含非法 UTF-8（应丢行）
        yield b'data: {"choices":[{"index":0,"delta":{"content":"ok"},' \
              b'"finish_reason":"stop"}]}\n\n'
        yield b"data: [DONE]\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


def _gen_flood_line(_last: str) -> StreamingResponse:
    size = GATEWAY_SSE_LINE_MAX_BYTES + 4 * 1024 * 1024   # 12MB 单行无换行 → 行帽丢弃

    async def gen():
        yield b"A" * size
        yield b"\n"
        yield b'data: {"choices":[{"index":0,"delta":{"content":"after-flood"},' \
              b'"finish_reason":"stop"}]}\n\n'
        yield b"data: [DONE]\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


def _gen_midstream_drop(_last: str) -> StreamingResponse:
    async def gen():
        yield 'data: {"choices":[{"index":0,"delta":{"content":"半截"}}]}\n\n'
        raise RuntimeError("bad upstream drops connection midstream")
    return StreamingResponse(gen(), media_type="text/event-stream")


BAD_MODES: dict[str, Any] = {
    "garbage_json": _gen_garbage_json,
    "undecodable": _gen_undecodable,
    "flood_line": _gen_flood_line,
    "midstream_drop": _gen_midstream_drop,
}

#: 每模式流式审计期望 (落账行数增量, flags)
BAD_MODE_AUDIT: dict[str, tuple[int, list[str]]] = {
    "garbage_json": (1, []),
    "undecodable": (1, []),
    "flood_line": (1, []),
    "midstream_drop": (1, ["upstream_stream_interrupted"]),
}


def _bad_upstream_app() -> FastAPI:
    """行为可控坏上游：POST /admin/behavior 切模式；非流式恒正常回显（事后可用性断言）。"""
    app = FastAPI(title="m11-bad-upstream", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.mode = "garbage_json"

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"ok": True, "service": "m11-bad-upstream", "mode": app.state.mode}

    @app.post("/admin/behavior")
    async def behavior(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return JSONResponse({"error": "bad json"}, status_code=400)
        mode = str(body.get("mode", ""))
        if mode not in BAD_MODES:
            return JSONResponse({"error": f"unknown mode: {mode}"}, status_code=400)
        app.state.mode = mode
        return {"mode": mode}

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> Any:
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        last_user = ""
        messages = body.get("messages") if isinstance(body.get("messages"), list) else []
        for message in reversed(messages):
            if isinstance(message, dict) and message.get("role") == "user" \
                    and isinstance(message.get("content"), str):
                last_user = message["content"]
                break
        if not body.get("stream"):
            # 非流式：正常 JSON 回显（网关「事后仍可用」断言用）
            return JSONResponse({
                "id": "chatcmpl-bad", "object": "chat.completion", "created": 0,
                "model": str(body.get("model") or "mock-chat"),
                "choices": [{"index": 0,
                             "message": {"role": "assistant", "content": f"BADUP {last_user}"},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": len(last_user), "completion_tokens": len(last_user) + 6,
                          "total_tokens": 2 * len(last_user) + 6},
            })
        return BAD_MODES[app.state.mode](last_user)

    return app


# ── 检查步骤 ──────────────────────────────────────────────────────────
def step_fixtures(ctx: dict[str, Any]) -> str:
    for port in (MOCK_PORT_INTERNET, MOCK_PORT_GOVCLOUD, BAD_UPSTREAM_PORT,
                 GATEWAY_PORT, BAD_GATEWAY_PORT):
        _assert_port_free(port)
    # 端口 8911/8912 不在 mock 的 DEFAULT_PORT_ROLES 表内 → 显式给实例名/模型名
    # （回显前缀 = ECHO_MARKER + 实例名，断言依赖与 e2e 同名）
    ctx["srv1"] = MockUpstreamServer(MOCK_PORT_INTERNET, name="internet_mock",
                                     models=["mock-chat"]).start(timeout=15.0)
    ctx["srv2"] = MockUpstreamServer(MOCK_PORT_GOVCLOUD, name="govcloud_local",
                                     models=["gov-chat"]).start(timeout=15.0)
    for srv in (ctx["srv1"], ctx["srv2"]):
        httpx.post(f"{srv.base_url}/admin/reset", timeout=5.0)
    ctx["srv_bad"] = _bad_upstream_app()
    ctx["bad_srv"], ctx["bad_srv_thread"] = _start_server(
        ctx["srv_bad"], BAD_UPSTREAM_PORT, "m11-bad-upstream", quiet=True)

    cfg = load_app_config().model_copy(deep=True)
    for upstream in cfg.upstreams:
        if upstream.name == "internet_mock":
            upstream.base_url = f"http://127.0.0.1:{MOCK_PORT_INTERNET}/v1"
        elif upstream.name == "govcloud_local":
            upstream.base_url = f"http://127.0.0.1:{MOCK_PORT_GOVCLOUD}/v1"
    digests = load_dept_keys()
    if digests[DEPT] != hashlib.sha256(DEMO_KEY.encode()).hexdigest():
        raise AssertionError("demo key out of sync with dept_keys.yaml")

    # 主网关：独立临时审计库 + 进程内会话注册表（不碰 data/ 与 .env）
    TMP_DIR.mkdir(exist_ok=True)
    _drop_db(AUDIT_DB)
    ctx["audit"] = SqliteAuditWriter(AUDIT_DB)
    ctx["registry"] = SessionRegistry(MASK_KEY.encode("utf-8"))
    app = create_app(cfg=cfg, mask_key=MASK_KEY, dept_key_digests=digests,
                     audit_store=ctx["audit"], session_registry=ctx["registry"])
    ctx["gw"], ctx["gw_thread"] = _start_server(app, GATEWAY_PORT, "m11-gateway")

    # 坏上游网关：仅绑 :8913 一个 INTERNET 上游 + 进程内审计表
    cfg_bad = load_app_config().model_copy(deep=True)
    internet = next(u for u in cfg_bad.upstreams if u.name == "internet_mock")
    internet.base_url = f"http://127.0.0.1:{BAD_UPSTREAM_PORT}/v1"
    cfg_bad.upstreams = [internet]
    ctx["audit_bad"] = InMemoryAuditStore()
    app_bad = create_app(cfg=cfg_bad, mask_key=MASK_KEY, dept_key_digests=digests,
                         audit_store=ctx["audit_bad"],
                         session_registry=SessionRegistry(MASK_KEY.encode("utf-8")))
    ctx["bad_gw"], ctx["bad_gw_thread"] = _start_server(app_bad, BAD_GATEWAY_PORT, "m11-gateway-bad")

    ctx["client"] = httpx.Client(base_url=f"http://127.0.0.1:{GATEWAY_PORT}",
                                 timeout=httpx.Timeout(M11_MALFORMED_TIMEOUT_S))
    ctx["client_bad"] = httpx.Client(base_url=f"http://127.0.0.1:{BAD_GATEWAY_PORT}",
                                     timeout=httpx.Timeout(M11_MALFORMED_TIMEOUT_S))
    return (f"mocks :{MOCK_PORT_INTERNET}/:{MOCK_PORT_GOVCLOUD} reset; bad upstream "
            f":{BAD_UPSTREAM_PORT}; gateways :{GATEWAY_PORT}/:{BAD_GATEWAY_PORT} "
            f"（独立临时审计库 {AUDIT_DB.name}）")


def step_body_malformed(ctx: dict[str, Any]) -> str:
    """① body 畸形族：全部 4xx+信封、mock 上游零感知、网关不崩不挂。"""
    client: httpx.Client = ctx["client"]
    srv1: MockUpstreamServer = ctx["srv1"]
    srv2: MockUpstreamServer = ctx["srv2"]
    ring1, ring2 = len(srv1.ring), len(srv2.ring)
    json_headers = {**_auth("sess_m11_malformed"), "content-type": "application/json"}

    # M1 >10MB body（Content-Length 形态）→ 413（Header 预检，秒回）
    big = json.dumps({"messages": [{"role": "user",
                                    "content": "A" * (GATEWAY_BODY_MAX_BYTES + 1024)}]}).encode()
    resp = client.post("/v1/chat/completions", content=big, headers=json_headers)
    _assert_envelope(resp, 413, "payload_too_large")

    # M2 >10MB body（chunked / 无 Content-Length 形态）→ 413（有界读取途中超限，
    # 排空后应答——客户端必须拿到完整 413 而非连接重置）
    def chunks():
        piece = b"A" * 65536
        for _ in range((GATEWAY_BODY_MAX_BYTES // 65536) + 2):
            yield piece
    resp = client.post("/v1/chat/completions", content=chunks(), headers=json_headers)
    _assert_envelope(resp, 413, "payload_too_large")

    # M3a 深嵌套（可解析深度 > GATEWAY_JSON_MAX_DEPTH）→ 400 嵌套超深
    body = ('{"messages":[{"role":"user","content":[{"type":"image_url",'
            '"image_url":' + _deep_json(GATEWAY_JSON_MAX_DEPTH + 200) + '}]}]}').encode()
    resp = client.post("/v1/chat/completions", content=body, headers=json_headers)
    err = _assert_envelope(resp, 400, "bad_request")
    if "nesting" not in err["message"]:
        raise AssertionError(f"嵌套超深信息缺失: {err['message']!r}")

    # M3b 深嵌套（解析器爆栈深度）→ 400（加固前：RecursionError 逃逸为 500 裸奔）
    body = ('{"messages":[{"role":"user","content":'
            + _deep_json(100_000) + "}]}").encode()
    resp = client.post("/v1/chat/completions", content=body, headers=json_headers)
    _assert_envelope(resp, 400, "bad_request")

    # M4 JSON 数组体 → 400（加固前：body.get 崩 500，T7.2 探针实锤）
    resp = client.post("/v1/chat/completions", content=b"[1,2,3]", headers=json_headers)
    _assert_envelope(resp, 400, "bad_request")

    # M5 非法 JSON → 400
    resp = client.post("/v1/chat/completions", content=b"{not-json", headers=json_headers)
    _assert_envelope(resp, 400, "bad_request")

    # M6 空/缺 messages、非对象消息 → 400
    for bad_body in ({"messages": []}, {"model": "mock-chat"},
                     {"messages": ["字符串不是消息对象"]},
                     {"messages": [{"role": "user", "content": "x"}, 42]}):
        resp = client.post("/v1/chat/completions", json=bad_body, headers=_auth("sess_m11_malformed"))
        _assert_envelope(resp, 400, "bad_request")

    # 畸形请求一律不出网：两 mock ring 零新增
    if len(srv1.ring) != ring1 or len(srv2.ring) != ring2:
        raise AssertionError(f"畸形请求抵达上游: 8911+{len(srv1.ring) - ring1}, "
                             f"8912+{len(srv2.ring) - ring2}")
    # 网关仍存活：healthz + 一条合法请求照常 200
    if client.get("/healthz").status_code != 200:
        raise AssertionError("healthz not ok after body malformed batch")
    resp = client.post("/v1/chat/completions", json=_chat_body("灾情核查联系电话13800138000。"),
                       headers=_auth("sess_m11_malformed_ok"))
    if resp.status_code != 200 or resp.headers.get("x-anongw-route") != "INTERNET":
        raise AssertionError(f"合法请求受阻: {resp.status_code}")
    ring1 += 1
    if len(srv1.ring) != ring1:
        raise AssertionError("合法请求未按预期出网")
    return ("10MB×2 形态→413（含 chunked 排空后应答）；深嵌套×2/数组体/非法 JSON/"
            "空缺 messages×4→400；全信封形状齐全；上游零感知；事后合法请求 200")


def step_text_length(ctx: dict[str, Any]) -> str:
    """超长单行：超帽 400、帽内 200 照常、/internal/detect 同帽。"""
    client: httpx.Client = ctx["client"]
    srv1: MockUpstreamServer = ctx["srv1"]
    headers = _auth("sess_m11_textcap")

    # 超长单行（单条文本超 GATEWAY_TEXT_MAX_CHARS）→ 400 错误信封（有界时间）
    long_line = "A" * (GATEWAY_TEXT_MAX_CHARS + 10_000)
    resp = client.post("/v1/chat/completions", json=_chat_body(long_line), headers=headers)
    err = _assert_envelope(resp, 400, "bad_request")
    if "too long" not in err["message"]:
        raise AssertionError(f"超长提示缺失: {err['message']!r}")

    # /internal/detect 同帽 → 400
    resp = client.post("/internal/detect", json={"text": long_line}, headers=headers)
    _assert_envelope(resp, 400, "bad_request")

    # 帽内 15 万字符单行 → 200 照常出网回显（帽不过度伤正常长文）
    ring1 = len(srv1.ring)
    moderate = "A" * 150_000
    resp = client.post("/v1/chat/completions", json=_chat_body(moderate), headers=headers)
    if resp.status_code != 200:
        raise AssertionError(f"帽内 15 万字符单行被误拒: {resp.status_code} {resp.text[:120]!r}")
    if resp.headers.get("x-anongw-route") != "INTERNET":
        raise AssertionError("帽内单行路由异常")
    content = resp.json()["choices"][0]["message"]["content"]
    expected_echo = f"{ECHO_MARKER}internet_mock\n{moderate}"
    if content not in (expected_echo, f"{expected_echo}\n{AI_LABEL}"):
        raise AssertionError("帽内单行回显不完整: "
                             f"len(got)={len(content)} len(exp)={len(expected_echo)} "
                             f"head={content[:60]!r} tail={content[-60:]!r}")
    if len(srv1.ring) != ring1 + 1:
        raise AssertionError("帽内单行未出网")
    return (f"超帽（>{GATEWAY_TEXT_MAX_CHARS} 字符）→400 信封（chat+internal 双面）；"
            f"帽内 150k 字符单行→200 照常回显出网")


def step_files_malformed(ctx: dict[str, Any]) -> str:
    """文件通道畸形：>50MB → 413 双端点；假 docx → 422；未知扩展名 → 400；正常件照常。"""
    client: httpx.Client = ctx["client"]
    docx_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    # >50MB（FILE_SIZE_MAX_BYTES + 1MB）→ inspect/export 均 413 信封
    big = os.urandom(FILE_SIZE_MAX_BYTES + 1024 * 1024)
    resp = client.post("/v1/files/inspect",
                       files={"file": ("big.docx", big, docx_mime)}, timeout=FILES_TIMEOUT_S)
    _assert_envelope(resp, 413, "payload_too_large")
    resp = client.post("/v1/files/export", data={"mode": "sanitize"},
                       files={"file": ("big.docx", big, docx_mime)}, timeout=FILES_TIMEOUT_S)
    _assert_envelope(resp, 413, "payload_too_large")
    del big

    # 假 docx（非 zip 字节）→ 422 file_parse_error（解析全 try/except 口径）
    resp = client.post("/v1/files/inspect",
                       files={"file": ("fake.docx", b"this is not a zip file", docx_mime)})
    _assert_envelope(resp, 422, "file_parse_error")
    resp = client.post("/v1/files/export", data={"mode": "sanitize"},
                       files={"file": ("fake.docx", b"this is not a zip file", docx_mime)})
    _assert_envelope(resp, 422, "file_parse_error")

    # 不支持的扩展名 → 400 unsupported_file_type
    resp = client.post("/v1/files/inspect",
                       files={"file": ("data.xyz", b"123", "application/octet-stream")})
    _assert_envelope(resp, 400, "unsupported_file_type")

    # 正常小 docx 照常体检（畸形不伤正常通道）
    from docx import Document

    doc = Document()
    doc.add_paragraph("居民张三身份证460022199003071230，联系电话13800138000。")
    buf = io.BytesIO()
    doc.save(buf)
    resp = client.post("/v1/files/inspect",
                       files={"file": ("ok.docx", buf.getvalue(), docx_mime)})
    if resp.status_code != 200:
        raise AssertionError(f"正常 docx 体检受阻: {resp.status_code} {resp.text[:120]!r}")
    summary = resp.json().get("summary") or {}
    if summary.get("ID_CARD", 0) < 1 or summary.get("PHONE_MOBILE", 0) < 1:
        raise AssertionError(f"正常 docx 体检命中异常: {summary}")
    return ("50MB+ 上传 inspect/export→413 信封；假 docx→422 file_parse_error；"
            "未知扩展名→400；正常 docx 体检 200 命中 seeded PII")


def step_illegal_sse(ctx: dict[str, Any]) -> str:
    """非法 SSE 帧 ×4 模式：流有界终止、审计如实、网关事后可用。"""
    client_bad: httpx.Client = ctx["client_bad"]
    audit_bad: InMemoryAuditStore = ctx["audit_bad"]
    base = f"http://127.0.0.1:{BAD_UPSTREAM_PORT}"
    details: list[str] = []
    body_text = "请查询联系电话13800138000的档案。"

    for mode, (rows, want_flags) in BAD_MODE_AUDIT.items():
        httpx.post(f"{base}/admin/behavior", json={"mode": mode}, timeout=5.0)
        audit_before = len(audit_bad)
        frames: list[str] = []
        received = 0
        with client_bad.stream("POST", "/v1/chat/completions",
                               json=_chat_body(body_text, stream=True),
                               headers=_auth(f"sess_m11_sse_{mode}"),
                               timeout=M11_MALFORMED_TIMEOUT_S) as resp:
            status = resp.status_code
            media_type = resp.headers.get("content-type", "")
            buf = ""
            for chunk in resp.iter_bytes():
                received += len(chunk)
                buf += chunk.decode("utf-8", errors="replace")
                while "\n\n" in buf:
                    frame, buf = buf.split("\n\n", 1)
                    if frame.strip():
                        frames.append(frame)
        if status != 200:
            raise AssertionError(f"[{mode}] status={status}")
        if not media_type.startswith("text/event-stream"):
            raise AssertionError(f"[{mode}] content-type={media_type}")
        if not any(line.strip() == "data: [DONE]" for f in frames for line in f.splitlines()) \
                and "upstream stream interrupted" not in "".join(frames):
            raise AssertionError(f"[{mode}] 流未按约定终止: frames={frames[-2:]!r}")
        _wait_audit_rows(audit_bad, audit_before + rows)
        event = audit_bad.snapshot()[-1]
        if event.flags != want_flags:
            raise AssertionError(f"[{mode}] 审计 flags={event.flags} 期望 {want_flags}")
        # 网关事后可用：healthz + 非流式合法请求 200（流式异常不毒化网关）
        if client_bad.get("/healthz").status_code != 200:
            raise AssertionError(f"[{mode}] 坏上游网关 healthz 失败")
        resp = client_bad.post("/v1/chat/completions", json=_chat_body(body_text),
                               headers=_auth(f"sess_m11_sse_ok_{mode}"))
        if resp.status_code != 200 or body_text not in resp.json()["choices"][0]["message"]["content"]:
            raise AssertionError(f"[{mode}] 事后非流式请求异常: {resp.status_code}")
        detail = {
            "garbage_json": "垃圾 JSON 帧原样透传（不吞不猜）+ [DONE] 正常收尾",
            "undecodable": "非法 UTF-8 字节行丢弃不炸",
            "flood_line": f"12MB 超长行按行帽丢弃，客户端仅收到 {received} 字节（<1MB）",
            "midstream_drop": "流中途断连→SSE error 事件收尾 + 审计 flag=upstream_stream_interrupted",
        }[mode]
        if mode == "flood_line" and received >= 1_000_000:
            raise AssertionError(f"[flood_line] 洪泛行未被丢弃: 收到 {received} 字节")
        details.append(detail)
    return "；".join(details)


def step_concurrency(ctx: dict[str, Any]) -> str:
    """② 并发 50（mock 上游）：零串扰三面 + 会话隔离 + 审计不错行 + 库级零明文。"""
    n = M11_CONCURRENCY_REQUESTS
    client: httpx.Client = ctx["client"]
    srv1: MockUpstreamServer = ctx["srv1"]
    audit: SqliteAuditWriter = ctx["audit"]
    registry = ctx["registry"]

    shared_phone = "13899990000"
    unique_phones = [f"138{i:08d}" for i in range(n - 5)]          # 45 独值
    plan: list[tuple[str, str, str]] = []                           # (session, phone, text)
    for i in range(n):
        phone = unique_phones[i] if i < n - 5 else shared_phone     # 后 5 请求同值异会话
        session = f"sess_m11_c{i:02d}"
        plan.append((session, phone, f"居民档案编号{i:03d}，联系电话{phone}，请核对材料。"))
    all_values = sorted(set(unique_phones + [shared_phone]))        # 46 个原值

    # 期望占位符（§5.3.1 冻结算法，同注册表实例 → 与网关必然一致）
    expected_ph = {session: registry.get(session).placeholder_for(
        EntityClass.PHONE_MOBILE, phone)[0] for session, phone, _ in plan}

    async def fire() -> tuple[list[tuple[int, dict[str, str], dict[str, Any]]], float, int]:
        limits = httpx.Limits(max_connections=n + 10, max_keepalive_connections=n + 10)
        async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{GATEWAY_PORT}",
                limits=limits, timeout=httpx.Timeout(M11_CONCURRENCY_TIMEOUT_S)) as sess:
            retries = 0

            async def one(index: int) -> tuple[int, dict[str, str], dict[str, Any]]:
                nonlocal retries
                session, _phone, text = plan[index]
                # 错峰开连（20ms×index）：50 条请求 ~1s 内全部在途（并发度不减），
                # 避免同瞬 50 次新建回环连接的 SYN 突发被 Windows 拒连
                await asyncio.sleep(0.02 * index)
                for attempt in range(3):
                    try:
                        r = await sess.post("/v1/chat/completions", json=_chat_body(text),
                                            headers=_auth(session))
                        return r.status_code, dict(r.headers), r.json()
                    except httpx.ConnectError:
                        # 环境代价：本机新建回环连接偶发拒连——有界重试，不计失败
                        retries += 1
                        if attempt == 2:
                            raise
                        await asyncio.sleep(0.5 * (attempt + 1))
                raise AssertionError("unreachable")

            started = time.perf_counter()
            out = list(await asyncio.gather(*(one(i) for i in range(n))))
            return out, time.perf_counter() - started, retries

    audit.flush(timeout_s=5.0)
    audit_before = len(audit)
    ring_before = len(srv1.ring)
    results, wall_s, connect_retries = asyncio.run(fire())

    # 全 200 + 路由/会话头 + 客户端零串扰（响应 i 只含自己的原值）
    for i, (status, headers, data) in enumerate(results):
        session, phone, _text = plan[i]
        if status != 200 or headers.get("x-anongw-route") != "INTERNET":
            raise AssertionError(f"#{i} status={status} route={headers.get('x-anongw-route')}")
        if headers.get("x-anongw-session-id") != session:
            raise AssertionError(f"#{i} session 头串扰: {headers.get('x-anongw-session-id')}")
        content = data["choices"][0]["message"]["content"]
        if RESTORE_PATTERN.search(content):
            raise AssertionError(f"#{i} 占位符泄漏到客户端: {content[:120]!r}")
        if phone not in content:
            raise AssertionError(f"#{i} 自己的原值未还原")
        others = [p for j, (_s, p, _t) in enumerate(plan) if j != i and p != phone]
        hit = [p for p in others if p in content]
        if hit:
            raise AssertionError(f"#{i} 响应串入他请求原值: {hit}")

    # 上游零串扰：ring 恰 +50，占位符与期望集合一一对应；同值异会话 → 互异占位符
    ring = srv1.ring.snapshot()[ring_before:]
    if len(ring) != n:
        raise AssertionError(f"上游 ring 新增 {len(ring)} != {n}")
    got_ph: list[str] = []
    for record in ring:
        text = record["last_user_content"]
        marks = PLACEHOLDER_RE.findall(text)
        if len(marks) != 1:
            raise AssertionError(f"上游单条占位符数 {len(marks)} != 1: {text[:80]!r}")
        got_ph.append(marks[0])
        blob = json.dumps(record.get("messages", []), ensure_ascii=False)
        hits = [v for v in all_values if v in blob]
        if hits:
            raise AssertionError(f"上游收到原值: {hits}")
    if len(set(got_ph)) != n:
        raise AssertionError(f"上游占位符去重 {len(set(got_ph))} != {n}（会话隔离破坏）")
    expected_set = {ph.split("·")[1].rstrip("〕") for ph in expected_ph.values()}
    if set(got_ph) != expected_set:
        raise AssertionError("上游占位符集合与期望（session,phone）派生集不一致")
    shared_marks = {expected_ph[s].split("·")[1].rstrip("〕")
                    for s, p, _ in plan if p == shared_phone}
    if len(shared_marks) != 5:
        raise AssertionError("同值异会话未产生 5 个互异占位符")

    # 审计不错行：恰 +50 行、request_id 互异、逐事件只含本会话占位符
    if not audit.flush(timeout_s=10.0):
        raise AssertionError("audit write queue did not drain")
    _wait_audit_rows(audit, audit_before + n)
    batch = [event for _, event in audit.fetch_all()][audit_before:]
    if len(batch) != n:
        raise AssertionError(f"审计新增 {len(batch)} 行 != {n}")
    req_ids = [e.request_id for e in batch]
    if len(set(req_ids)) != n:
        raise AssertionError(f"审计 request_id 去重 {len(set(req_ids))} != {n}（错行/重行）")
    if {e.session_id for e in batch} != {s for s, _p, _t in plan}:
        raise AssertionError("审计会话集合与请求不一致")
    for event in batch:
        if event.route != "INTERNET" or event.blocked or event.dept != DEPT:
            raise AssertionError(f"审计事件路由面异常: {event.session_id} {event.route}")
        if event.class_counts != {"PHONE_MOBILE": 1}:
            raise AssertionError(f"审计 class_counts 异常: {event.class_counts}")
        marks = PLACEHOLDER_RE.findall(event.prompt_preview)
        if len(marks) != 1:
            raise AssertionError(f"审计预览占位符数异常: {event.prompt_preview!r}")
        if marks[0] not in expected_set:
            raise AssertionError(f"审计预览占位符不在期望集: {marks[0]}")
        hits = [v for v in all_values if v in event.prompt_preview + event.response_preview]
        if hits:
            raise AssertionError(f"审计预览泄漏原值: {hits}")

    # 库文件 bytes 级零明文（46 原值，§9 U5 口径）
    audit.checkpoint()
    scanned = assert_db_no_raw_pii(AUDIT_DB, all_values)

    # 并发下会话稳定：同会话重发同值 → 占位符全等；新会话同值 → 互异
    ring_before2 = len(srv1.ring)
    resp = client.post("/v1/chat/completions", json=_chat_body(plan[n - 5][2]),
                       headers=_auth(plan[n - 5][0]))
    if resp.status_code != 200:
        raise AssertionError(f"同会话重发失败: {resp.status_code}")
    last_marks = PLACEHOLDER_RE.findall(srv1.ring.snapshot()[-1]["last_user_content"])
    if last_marks != [expected_ph[plan[n - 5][0]].split("·")[1].rstrip("〕")]:
        raise AssertionError("同会话重发占位符漂移（并发下会话不稳定）")
    resp = client.post("/v1/chat/completions", json=_chat_body(plan[n - 5][2]),
                       headers=_auth("sess_m11_new_session"))
    new_marks = PLACEHOLDER_RE.findall(srv1.ring.snapshot()[-1]["last_user_content"])
    if not new_marks or new_marks == last_marks:
        raise AssertionError("跨会话占位符未区分")
    if len(srv1.ring) != ring_before2 + 2:
        raise AssertionError("稳定性探针出网数异常")

    if client.get("/healthz").status_code != 200:
        raise AssertionError("healthz not ok after concurrency batch")
    return (f"{n} 并发全 200（批总耗时 {wall_s:.1f}s，错峰开连+连接重试 {connect_retries} 次——"
            f"本机新建回环连接 ~1s/条的环境代价）；"
            f"零串扰三面（客户端响应互斥 / 上游 {n} 占位符一一对应且"
            f"同值异会话 5 占位符互异 / 审计 {n} 行 request_id 互异逐行只含本会话占位符）；"
            f"库文件 {scanned} 字节零明文（46 原值）；同会话占位符稳定、跨会话互异")


def step_alive(ctx: dict[str, Any]) -> str:
    """收尾存活面：两网关 healthz + 主网关流式合法请求照常（全链仍绿）。"""
    client: httpx.Client = ctx["client"]
    client_bad: httpx.Client = ctx["client_bad"]
    if client.get("/healthz").status_code != 200 or \
            client_bad.get("/healthz").status_code != 200:
        raise AssertionError("healthz not ok (main/bad gateway)")
    payloads: list[str] = []
    with client.stream("POST", "/v1/chat/completions",
                       json=_chat_body("收尾核查联系电话13900139000。", stream=True),
                       headers=_auth("sess_m11_alive"), timeout=M11_MALFORMED_TIMEOUT_S) as resp:
        if resp.status_code != 200:
            raise AssertionError(f"收尾流式请求失败: {resp.status_code}")
        buf = ""
        for chunk in resp.iter_text():
            buf += chunk
            while "\n\n" in buf:
                frame, buf = buf.split("\n\n", 1)
                if frame.strip():
                    for line in frame.splitlines():
                        if line.startswith("data:"):
                            payload = line[len("data:"):].strip()
                            if payload and payload != "[DONE]":
                                payloads.append(payload)
    parts: list[str] = []
    for payload in payloads:
        try:
            event = json.loads(payload)
        except ValueError:
            continue
        choices = event.get("choices") or []
        if choices and isinstance(choices[0], dict):
            delta = choices[0].get("delta") or {}
            if isinstance(delta.get("content"), str):
                parts.append(delta["content"])
    content = "".join(parts)
    if "13900139000" not in content:
        raise AssertionError(f"收尾流式还原异常: {content[:120]!r}")
    return "两网关 healthz 200；主网关流式合法请求照常（还原+标识全链仍绿）"


STEPS = (
    ("fixtures:start-topology", step_fixtures),
    ("malformed:body-4xx-envelope", step_body_malformed),
    ("malformed:oversize-single-line", step_text_length),
    ("malformed:file-channel", step_files_malformed),
    ("robust:illegal-sse-frames", step_illegal_sse),
    ("load:concurrency-50-zero-crosstalk", step_concurrency),
    ("alive:after-all-madness", step_alive),
)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ctx: dict[str, Any] = {}
    try:
        for name, fn in STEPS:
            _record(name, lambda f=fn, c=ctx: f(c))
    finally:
        client = ctx.get("client")
        if client is not None:
            client.close()
        client_bad = ctx.get("client_bad")
        if client_bad is not None:
            client_bad.close()
        for key in ("gw", "bad_gw", "bad_srv"):
            _stop_server(ctx, key)
        for key in ("srv1", "srv2"):
            srv = ctx.get(key)
            if srv is not None:
                srv.stop()
        audit = ctx.get("audit")
        if audit is not None:
            audit.close()
        _drop_db(AUDIT_DB)

    for name, status, detail in RESULTS:
        print(f"{status:<7} {name} — {detail}")
    total = len(RESULTS)
    passed = sum(1 for _, s, _ in RESULTS if s == "PASS")
    failed = sum(1 for _, s, _ in RESULTS if s == "FAIL")
    print("-" * 64)
    print(f"M11 ROBUST(T7.2 畸形输入/极端负载): {passed}/{total} checks passed")
    print(f"m11_robust: {passed} PASS / {failed} FAIL"
          f"（畸形输入 4xx+信封；非法 SSE 有界终止；并发 {M11_CONCURRENCY_REQUESTS} 零串扰）")
    return 0 if failed == 0 and passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
