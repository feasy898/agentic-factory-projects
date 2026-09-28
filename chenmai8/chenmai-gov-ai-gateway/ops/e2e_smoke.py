#!/usr/bin/env python3
"""端到端冒烟（开发指令 §9，D0 收工线）：mock 上游×2 + 网关全真链路，六用例 U1–U6。

拓扑（§9 步骤 1–2，全部本地、零外网依赖、零真实 API key）::

    客户端(本脚本) ──HTTP/TCP──► 网关 :9000（真实 config/app.yaml + .env 密钥）
                                   ├─ INTERNET ──► mock 上游 :8901（独立子进程）
                                   ├─ GOVCLOUD ──► mock 上游 :8902（独立子进程）
                                   └─ BLOCK    ──► 403 拦截（两 mock 零感知）

- mock 上游按 §9「同一 app 不同 argv」以**独立子进程**拉起
  （``python -m gateway.mock_upstream --port N``）；
- 网关在本进程内以 uvicorn 线程拉起（真实配置 + 真实端口 :9000，客户端走真实 TCP）；
  审计存储为进程内 v0 表——§9 U5 的"行数断言 + bytes 级零明文扫描"以该存储为对象，
  SQLite 库文件级扫描自 M7 落地后升级；/admin/api/audit 上线后自动改为 HTTP 交叉核对。

用例（§9 步骤 3；U1–U5 当天生效，U6 文件通道 D3 起生效）：
- U1 非流式：2 身份证 + 3 手机号（含分隔符写法）+ 人名 → 上游 bytes 级零原值、
  占位符计数精确（〔身份证·×2、〔手机号·×3）；客户端零占位符形状、原值（归一化形态）
  完整在位；响应头 x-anongw-route=INTERNET；
- U2 流式：同 prompt，SSE 逐 delta 拼接后同 U1 断言（外加流式 AI 生成标识尾注）；
  再以 mock 默认 1–7 字符随机切块模式重放 20 次，逐次全等断言（覆盖占位符被
  切进相邻两个 SSE chunk 的还原）；
- U3 三路由：普通材料→INTERNET/:8901；批量名单（≥3 结构化号码）→GOVCLOUD/:8902；
  机密★材料→403 content_blocked 且两 mock 均零新增；
- U4 工具调用：tools 定义 + arguments 中文含 PII → 上游收到占位符版参数、
  客户端收到还原版（JSON 可解析、占位符形状零残留）；
- U5 审计：行数 == 本次发送的全部 /v1/chat/completions 请求数；事件字段形状齐全；
  全部事件序列化后 bytes 级扫描所有用到的原值 → 零命中；
- U6 文件：inspect+export seeded docx → 重解析零命中（文件通道未上线时输出
  DEFERRED，不计失败）。

运行::

    cd REPO_ROOT && PYTHONUTF8=1 ./.venv/Scripts/python.exe ops/e2e_smoke.py
    # 等价：PYTHONUTF8=1 ./.venv/Scripts/python.exe -m ops.e2e_smoke

任何 FAIL → 退出码 1；DEFERRED 不影响退出码。
"""
from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import uvicorn

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from audit.store import InMemoryAuditStore  # noqa: E402
from common.config import (  # noqa: E402
    load_app_config,
    load_dept_keys,
    load_env_file,
    resolve_secret,
)
from gateway.app import create_app  # noqa: E402
from gateway.mock_upstream import ECHO_MARKER  # noqa: E402
from masking.mapper import RESTORE_PATTERN  # noqa: E402

# ── 固定拓扑与演示凭据（对齐 config/app.yaml / config/dept_keys.yaml）──────
MOCK_PORT_INTERNET = 8901
MOCK_PORT_GOVCLOUD = 8902
GATEWAY_PORT = 9000
GATEWAY_BASE = f"http://127.0.0.1:{GATEWAY_PORT}"

DEPT = "民政局"
DEMO_KEY = "dk_5e6f7a8b"        # 演示明文；config/dept_keys.yaml 只存其 sha256

AI_LABEL = "本内容由AI生成"      # config/app.yaml ai_label

READY_TIMEOUT_S = 20.0
AUDIT_SETTLE_TIMEOUT_S = 10.0
U2_REPLAYS = 20                 # §9 U2：流式重放次数


# ── 夹具：样例原值（bytes 级断言清单汇总于 RAW_VALUES）────────────────────
def _valid_id(prefix17: str) -> str:
    """给定 17 位前缀，计算 GB11643 校验位得到合法身份证样例（eval 专用夹具）。"""
    weights = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
    codes = "10X98765432"
    total = sum(int(ch) * w for ch, w in zip(prefix17, weights, strict=True))
    return prefix17 + codes[total % 11]


ID_A = "11010519491231002X"                 # 校验位合法样例
ID_B = _valid_id("46002219900307123")       # 海南区划前缀样例
ID_C = _valid_id("46002320010307123")       # 批量名单用
ID_D = _valid_id("11010519491231101")       # 批量名单用

PHONE_A = "13800138000"                     # 常规写法（= 归一化形态）
PHONE_B_RAW = "139 0013 9000"               # 空格分隔写法 → 归一化 PHONE_B
PHONE_B = "13900139000"
PHONE_C_RAW = "137-0013-7000"               # 连字符分隔写法 → 归一化 PHONE_C
PHONE_C = "13700137000"
PHONE_BLOCKED = "13900139001"               # 仅出现在机密样例（上游必须零感知）

PERSON = "张三"

U_TEXT = (f"居民{PERSON}（身份证{ID_A}、{ID_B}），联系电话{PHONE_A}、"
          f"{PHONE_B_RAW}、{PHONE_C_RAW}，请核对其低保申领材料并回电。")
U_RESTORED = (f"居民{PERSON}（身份证{ID_A}、{ID_B}），联系电话{PHONE_A}、"
              f"{PHONE_B}、{PHONE_C}，请核对其低保申领材料并回电。")

ORDINARY_TEXT = "本周全镇防汛演练安排在周四上午九点，请各村网格员提前到场并做好记录。"
BATCH_TEXT = f"低保名单：{ID_A}；{ID_C}；{ID_D}；联系人电话{PHONE_A}"
CLASSIFIED_TEXT = f"机密★干部考察纪要：考察对象{PERSON}，联系电话{PHONE_BLOCKED}，内部资料注意保密。"

TOOL_TEXT = f"查询{PERSON}名下低保发放记录，证件号{ID_D}，联系电话{PHONE_A}"
TOOL_RESTORED = f"查询{PERSON}名下低保发放记录，证件号{ID_D}，联系电话{PHONE_A}"

TOOLS = [{
    "type": "function",
    "function": {
        "name": "query_lowincome_record",
        "description": "按姓名与证件号查询低保台账",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "查询原文"}},
            "required": ["query"],
        },
    },
}]

#: 全部用例涉及的敏感原值（归一化 + 原始写法）；上游/审计 bytes 级扫描必须零命中。
#: 注：密级词表词（机密★等）不在此列——BLOCK 拦截语义允许其留在审计理由码之外的原文本形态。
RAW_VALUES: tuple[str, ...] = (
    ID_A, ID_B, ID_C, ID_D,
    PHONE_A, PHONE_B_RAW, PHONE_B, PHONE_C_RAW, PHONE_C, PHONE_BLOCKED,
)

U1_EXPECTED_PLACEHOLDERS = {"〔身份证·": 2, "〔手机号·": 3}
U3_BATCH_EXPECTED_PLACEHOLDERS = {"〔身份证·": 3, "〔手机号·": 1}

RESULTS: list[tuple[str, str, str]] = []   # (用例名, 状态 PASS/FAIL/DEFER, 详情)


# ── 通用小工具 ────────────────────────────────────────────────────────
def _assert_port_free(port: int) -> None:
    with socket.socket() as sock:
        sock.settimeout(0.3)
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"port {port} already occupied — 残留进程未退出？")


def _wait_ready(url: str, label: str, *, proc: subprocess.Popen | None = None,
                timeout: float = READY_TIMEOUT_S) -> None:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(f"{label} 进程提前退出 (code={proc.returncode})")
        try:
            resp = httpx.get(url, timeout=1.0)
            if resp.status_code == 200 and resp.json().get("ok") is True:
                return
        except Exception as exc:  # noqa: BLE001 — 启动窗口内连接失败属预期
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(0.1)
    raise RuntimeError(f"{label} 就绪超时（{timeout}s）：{last}")


def _record(name: str, fn) -> None:
    try:
        detail = fn() or ""
        # 约定：返回值以 "DEFERRED" 开头 = 用例按期未生效（如 U6 文件通道 D3 前），不计失败
        status = "DEFER" if detail.startswith("DEFERRED") else "PASS"
        RESULTS.append((name, status, detail))
    except Exception as exc:  # noqa: BLE001 — 汇总所有失败后统一退出
        RESULTS.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))


# ── mock 上游子进程管理（§9 步骤 1）───────────────────────────────────
def _start_mock(port: int) -> subprocess.Popen:
    _assert_port_free(port)
    proc = subprocess.Popen(
        [sys.executable, "-m", "gateway.mock_upstream", "--port", str(port)],
        cwd=str(REPO_ROOT),
        env={**os.environ, "PYTHONUTF8": "1"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _wait_ready(f"http://127.0.0.1:{port}/healthz", label=f"mock:{port}", proc=proc)
    return proc


def _mock_count(base: str) -> int:
    return int(httpx.get(f"{base}/admin/records", timeout=5.0).json()["count"])


def _mock_text(base: str) -> bytes:
    return httpx.get(f"{base}/admin/text", timeout=5.0).content


def _mock_last_record(base: str) -> dict[str, Any]:
    records = httpx.get(f"{base}/admin/records", timeout=5.0).json()["records"]
    if not records:
        raise AssertionError(f"{base} ring buffer 为空")
    return records[-1]


def _assert_no_raw(blob: bytes, values: tuple[str, ...], where: str) -> None:
    hits = [v for v in values if v.encode("utf-8") in blob]
    if hits:
        raise AssertionError(f"{where} 出现原值（bytes 级命中）: {hits}")


def _assert_placeholder_counts(text: str, expected: dict[str, int]) -> None:
    for marker, want in expected.items():
        got = text.count(marker)
        if got != want:
            raise AssertionError(f"占位符 {marker}** 计数 {got} != {want}：{text!r}")


# ── 网关（§9 步骤 2：真实配置 + 真实端口；审计 v0 表留断言句柄）──────────
def _start_gateway(ctx: dict[str, Any]) -> None:
    _assert_port_free(GATEWAY_PORT)
    load_env_file()  # .env 预载（MASK_KEY / MOCK_KEY；不覆盖已有环境变量）
    cfg = load_app_config()
    mask_key = resolve_secret(cfg.mask_key_env)  # 缺失即抛明确错误
    ctx["audit"] = InMemoryAuditStore()
    app = create_app(cfg=cfg, mask_key=mask_key, dept_key_digests=load_dept_keys(),
                     audit_store=ctx["audit"])
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=GATEWAY_PORT,
        log_level="warning", log_config=None, access_log=False,
    ))
    thread = threading.Thread(target=server.run, name="anongw-e2e", daemon=True)
    thread.start()
    _wait_ready(f"{GATEWAY_BASE}/healthz", label="gateway:9000")
    ctx["gw_server"], ctx["gw_thread"] = server, thread


def _stop_gateway(ctx: dict[str, Any]) -> None:
    server = ctx.get("gw_server")
    if server is not None:
        server.should_exit = True
    thread = ctx.get("gw_thread")
    if thread is not None:
        thread.join(timeout=5.0)


# ── 客户端请求（§9 步骤 3）────────────────────────────────────────────
def _auth(session: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {DEMO_KEY}", "x-anongw-session-id": session}


def _send_chat(client: httpx.Client, body: dict[str, Any], session: str,
               ctx: dict[str, Any]) -> tuple[int, dict[str, str], list[str], str]:
    """发送 /v1/chat/completions 并计数（U5 行数断言基数）。

    返回 (状态码, 响应头, SSE帧列表, 末尾残留文本)。非 SSE 响应的 JSON 体在残留文本里。
    """
    ctx["chat_sent"] += 1
    frames: list[str] = []
    with client.stream("POST", "/v1/chat/completions", json=body,
                       headers=_auth(session)) as resp:
        status, headers = resp.status_code, dict(resp.headers)
        buf = ""
        for chunk in resp.iter_text():
            buf += chunk
            while "\n\n" in buf:
                frame, buf = buf.split("\n\n", 1)
                if frame.strip():
                    frames.append(frame)
    return status, headers, frames, buf


def _plain_body(text: str, *, model: str | None = "mock-chat", stream: bool = False,
                tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"messages": [{"role": "user", "content": text}], "stream": stream}
    if model is not None:
        body["model"] = model
    if tools is not None:
        body["tools"] = tools
    return body


def _sse_events(frames: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for frame in frames:
        for line in frame.splitlines():
            if line.startswith("data:"):
                payload = line[len("data:"):].strip()
                if payload and payload != "[DONE]":
                    out.append(json.loads(payload))
    return out


def _sse_done_seen(frames: list[str]) -> bool:
    return any(line.strip() == "data: [DONE]" for f in frames for line in f.splitlines())


def _sse_content(events: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for event in events:
        choices = event.get("choices") or []
        if choices and isinstance(choices[0], dict):
            delta = choices[0].get("delta") or {}
            if isinstance(delta.get("content"), str):
                parts.append(delta["content"])
    return "".join(parts)


def _plain_answer_ok(content: str, expected: str, *, streaming: bool) -> str:
    """客户端答案断言：占位符形状零残留、还原全等。

    流式（T0.5 已生效）必须带 AI 生成标识尾注；非流式的标识注入自 M5 输出侧落地，
    当前允许「无尾注」与「尾注形态」两种（M5 落地后收紧为仅后者）。
    """
    if RESTORE_PATTERN.search(content):
        raise AssertionError(f"占位符泄漏到客户端: {content!r}")
    if content == expected:
        return "exact"
    if content == f"{expected}\n{AI_LABEL}":
        if streaming:
            return "exact+label"
        return "with-ai-label(M5 预留形态)"
    if streaming:
        raise AssertionError(f"还原答案不匹配：\n got={content!r}\n exp={expected!r}（流式须带标识尾注）")
    raise AssertionError(f"还原答案不匹配：\n got={content!r}\n exp={expected!r}")


# ── U1 非流式（§9 U1）─────────────────────────────────────────────────
def case_u1(ctx: dict[str, Any]) -> str:
    client: httpx.Client = ctx["client"]
    base = ctx["mock_internet"]
    before = _mock_count(base)
    status, headers, frames, raw = _send_chat(
        client, _plain_body(U_TEXT), "sess_e2e_u1", ctx)
    if status != 200:
        raise AssertionError(f"status={status} body={raw[:200]!r}")
    if headers.get("x-anongw-route") != "INTERNET":
        raise AssertionError(f"route header: {headers.get('x-anongw-route')}")
    if not headers.get("x-anongw-request-id", "").startswith("req_"):
        raise AssertionError("request-id header missing")
    if headers.get("x-anongw-session-id") != "sess_e2e_u1":
        raise AssertionError("session-id header mismatch")
    data = json.loads(raw)
    content = data["choices"][0]["message"]["content"]
    _plain_answer_ok(content, f"{ECHO_MARKER}internet_mock\n{U_RESTORED}", streaming=False)
    for value in (ID_A, ID_B, PHONE_A, PHONE_B, PHONE_C):
        if value not in content:
            raise AssertionError(f"原值未还原: {value}")
    if data["model"] != "mock-chat" or data["usage"]["total_tokens"] <= 0:
        raise AssertionError(f"passthrough shape: model={data['model']} usage={data['usage']}")
    # 上游：仅 +1 条；全占位符（计数精确）；bytes 级零原值
    if _mock_count(base) != before + 1:
        raise AssertionError(f"8901 ring delta {_mock_count(base) - before}")
    upstream_text = _mock_last_record(base)["last_user_content"]
    _assert_placeholder_counts(upstream_text, U1_EXPECTED_PLACEHOLDERS)
    _assert_no_raw(_mock_text(base), RAW_VALUES, "mock:8901")
    return "200 INTERNET；上游全占位符（身份证×2/手机号×3，bytes 级零原值）；客户端还原完整"


# ── U2 流式 + 重放 20 次（§9 U2）──────────────────────────────────────
def case_u2(ctx: dict[str, Any]) -> str:
    client: httpx.Client = ctx["client"]
    base = ctx["mock_internet"]
    before = _mock_count(base)
    expected = f"{ECHO_MARKER}internet_mock\n{U_RESTORED}\n{AI_LABEL}"

    def one_replay() -> str:
        status, headers, frames, raw = _send_chat(
            client, _plain_body(U_TEXT, stream=True), "sess_e2e_u2", ctx)
        if status != 200:
            raise AssertionError(f"status={status} body={raw[:200]!r}")
        if not headers.get("content-type", "").startswith("text/event-stream"):
            raise AssertionError(f"content-type: {headers.get('content-type')}")
        if headers.get("x-anongw-route") != "INTERNET":
            raise AssertionError(f"route header: {headers.get('x-anongw-route')}")
        if headers.get("x-anongw-ai-label") != "1":
            raise AssertionError(f"ai-label header: {headers.get('x-anongw-ai-label')}")
        if not _sse_done_seen(frames):
            raise AssertionError("missing [DONE] sentinel")
        content = _sse_content(_sse_events(frames))
        _plain_answer_ok(content, expected, streaming=True)
        return content

    first = one_replay()
    # 重放 20 次：mock 每次以 1–7 字符随机切块重发，占位符跨 chunk 切分须逐次还原全等
    for i in range(U2_REPLAYS):
        content = one_replay()
        if content != first:
            raise AssertionError(f"replay#{i + 1} content drift")
    if _mock_count(base) != before + 1 + U2_REPLAYS:
        raise AssertionError(f"8901 ring delta {_mock_count(base) - before}")
    _assert_no_raw(_mock_text(base), RAW_VALUES, "mock:8901")
    upstream_text = _mock_last_record(base)["last_user_content"]
    _assert_placeholder_counts(upstream_text, U1_EXPECTED_PLACEHOLDERS)
    return f"200 SSE；首传 + {U2_REPLAYS} 次随机切块重放全等；上游全占位符；AI 标识尾注在位"


# ── U3 三路由（§9 U3）─────────────────────────────────────────────────
def case_u3(ctx: dict[str, Any]) -> str:
    client: httpx.Client = ctx["client"]
    base1, base2 = ctx["mock_internet"], ctx["mock_govcloud"]
    b1, b2 = _mock_count(base1), _mock_count(base2)

    # ① 普通材料 → INTERNET / :8901
    status, headers, frames, raw = _send_chat(
        client, _plain_body(ORDINARY_TEXT), "sess_e2e_u3a", ctx)
    if status != 200 or headers.get("x-anongw-route") != "INTERNET":
        raise AssertionError(f"ordinary: {status} route={headers.get('x-anongw-route')}")
    content = json.loads(raw)["choices"][0]["message"]["content"]
    _plain_answer_ok(content, f"{ECHO_MARKER}internet_mock\n{ORDINARY_TEXT}", streaming=False)
    if _mock_count(base1) != b1 + 1 or _mock_count(base2) != b2:
        raise AssertionError("ordinary forward split wrong")

    # ② 批量名单 → GOVCLOUD / :8902
    status, headers, frames, raw = _send_chat(
        client, _plain_body(BATCH_TEXT, model=None), "sess_e2e_u3b", ctx)
    if status != 200 or headers.get("x-anongw-route") != "GOVCLOUD":
        raise AssertionError(f"batch: {status} route={headers.get('x-anongw-route')}")
    content = json.loads(raw)["choices"][0]["message"]["content"]
    _plain_answer_ok(content, f"{ECHO_MARKER}govcloud_local\n{BATCH_TEXT}", streaming=False)
    if ID_A not in content:
        raise AssertionError("batch client restore failed")
    if _mock_count(base2) != b2 + 1 or _mock_count(base1) != b1 + 1:
        raise AssertionError("batch forward split wrong")
    up = _mock_last_record(base2)["last_user_content"]
    _assert_placeholder_counts(up, U3_BATCH_EXPECTED_PLACEHOLDERS)
    _assert_no_raw(_mock_text(base2), RAW_VALUES, "mock:8902")

    # ③ 机密★材料 → 403 拦截，两 mock 均零新增
    status, headers, frames, raw = _send_chat(
        client, _plain_body(CLASSIFIED_TEXT), "sess_e2e_u3c", ctx)
    if status != 403:
        raise AssertionError(f"classified: {status} body={raw[:200]!r}")
    err = json.loads(raw)["error"]
    if err["code"] != "content_blocked":
        raise AssertionError(f"code: {err['code']}")
    if not err.get("reasons") or err["reasons"][0]["code"] != "CLASSIFICATION_MARK":
        raise AssertionError(f"reasons: {err['reasons']}")
    if headers.get("x-anongw-route") != "BLOCK":
        raise AssertionError(f"route header on block: {headers.get('x-anongw-route')}")
    if _mock_count(base1) != b1 + 1 or _mock_count(base2) != b2 + 1:
        raise AssertionError("blocked request reached an upstream")
    _assert_no_raw(_mock_text(base1) + _mock_text(base2), (PHONE_BLOCKED,), "mocks")
    return "普通→8901 / 批量→8902 / 机密★→403（reasons[0]=CLASSIFICATION_MARK）；上游零原值"


# ── U4 工具调用（§9 U4）───────────────────────────────────────────────
def case_u4(ctx: dict[str, Any]) -> str:
    client: httpx.Client = ctx["client"]
    base = ctx["mock_internet"]
    before = _mock_count(base)
    status, headers, frames, raw = _send_chat(
        client, _plain_body(TOOL_TEXT, tools=TOOLS), "sess_e2e_u4", ctx)
    if status != 200:
        raise AssertionError(f"status={status} body={raw[:200]!r}")
    message = json.loads(raw)["choices"][0]["message"]
    calls = message.get("tool_calls") or []
    if len(calls) != 1 or calls[0]["function"]["name"] != "query_lowincome_record":
        raise AssertionError(f"tool_calls: {message}")
    args = calls[0]["function"]["arguments"]
    try:
        parsed = json.loads(args)
    except ValueError as exc:
        raise AssertionError(f"arguments not JSON: {args!r}") from exc
    if parsed != {"query": TOOL_RESTORED}:
        raise AssertionError(f"restored arguments mismatch: {parsed!r}")
    if RESTORE_PATTERN.search(args):
        raise AssertionError(f"placeholder leaked in arguments: {args!r}")
    record = _mock_last_record(base)
    if not record.get("tool_call") or _mock_count(base) != before + 1:
        raise AssertionError("upstream did not record the tool call")
    up_args = record["tool_arguments"]
    _assert_no_raw(up_args.encode("utf-8"), RAW_VALUES, "mock:8901 tool_arguments")
    if "〔身份证·" not in up_args or "〔手机号·" not in up_args:
        raise AssertionError(f"upstream arguments lack placeholders: {up_args!r}")
    return "上游收到占位符版参数；客户端拿到还原版（JSON 全等、占位符零残留）"


# ── U5 审计（§9 U5）───────────────────────────────────────────────────
def case_u5(ctx: dict[str, Any]) -> str:
    audit: InMemoryAuditStore = ctx["audit"]
    expected = ctx["chat_sent"]
    deadline = time.monotonic() + AUDIT_SETTLE_TIMEOUT_S
    while len(audit) < expected and time.monotonic() < deadline:
        time.sleep(0.1)  # 流式审计随流收尾落账，留短暂结算窗口
    events = audit.snapshot()
    if len(events) != expected:
        raise AssertionError(f"audit rows={len(events)}, expect {expected}")

    routes = [e.route for e in events]
    if routes.count("BLOCK") != 1 or routes.count("GOVCLOUD") != 1:
        raise AssertionError(f"route mix: BLOCK={routes.count('BLOCK')} GOVCLOUD={routes.count('GOVCLOUD')}")
    if routes.count("INTERNET") != expected - 2:
        raise AssertionError(f"INTERNET count {routes.count('INTERNET')} != {expected - 2}")
    for event in events:
        if not event.request_id.startswith("req_") or not event.session_id.startswith("sess_"):
            raise AssertionError(f"ids: {event.request_id}/{event.session_id}")
        if event.dept != DEPT or event.latency_ms < 0:
            raise AssertionError(f"dept/latency: {event.dept}/{event.latency_ms}")
        if (event.route == "BLOCK") != event.blocked:
            raise AssertionError(f"blocked flag mismatch on {event.request_id}")
        if event.route == "BLOCK" and event.upstream is not None:
            raise AssertionError("blocked event must not name an upstream")
    blocked = next(e for e in events if e.route == "BLOCK")
    if blocked.response_preview != "":
        raise AssertionError("blocked response_preview must be empty")
    by_session = {e.session_id: e for e in events}
    u1 = by_session["sess_e2e_u1"]
    if "〔手机号·" not in u1.prompt_preview or ID_A in u1.prompt_preview:
        raise AssertionError(f"u1 prompt preview not masked: {u1.prompt_preview!r}")
    if "〔身份证·" not in u1.response_preview or RESTORE_PATTERN.search(u1.response_preview) is None:
        raise AssertionError(f"u1 response preview not placeholder-version: {u1.response_preview!r}")
    # bytes 级零明文：全部事件序列化后扫描所有原值（§9 U5 的 v0 等价口径；SQLite 文件级自 M7）
    blob = "\n".join(e.model_dump_json() for e in events).encode("utf-8")
    _assert_no_raw(blob, RAW_VALUES, "audit store")
    # 管理面查询 API（M7 落地后自动启用交叉核对；未上线仅提示）
    note = ""
    try:
        resp = ctx["client"].get("/admin/api/audit", timeout=5.0)
    except Exception:  # noqa: BLE001
        resp = None
    if resp is not None and resp.status_code == 200:
        rows = resp.json()
        n = rows.get("total", len(rows.get("events", rows.get("items", []))))
        if n != expected:
            raise AssertionError(f"/admin/api/audit rows={n} != {expected}")
        note = "；/admin/api/audit 交叉核对一致"
    else:
        note = "；/admin/api/audit 未上线（M7 落地后自动交叉核对）"
    return f"{expected} 条事件（1 BLOCK + 1 GOVCLOUD + {expected - 2} INTERNET）；" \
           f"预览占位符版本；bytes 级零明文{note}"


# ── U6 文件通道（§9 U6；D3 起生效）────────────────────────────────────
def case_u6(ctx: dict[str, Any]) -> str:
    """seeded docx → inspect 命中 → export → 重解析零残留。

    文件通道未上线（404）时输出 DEFERRED（§9：U6 自 D3 起纳入），不计失败。
    """
    try:
        from docx import Document  # 文件解析通道依赖（filechannel 任务引入）
    except ImportError as exc:  # pragma: no cover — D3 前不应触达
        return f"DEFERRED: 文件通道未上线且解析依赖缺失（{exc}）"
    doc = Document()
    doc.add_paragraph(f"低保公示名单：{ID_B}，联系电话{PHONE_A}。")
    buf = io.BytesIO()
    doc.save(buf)
    payload = buf.getvalue()
    resp = ctx["client"].post(
        "/v1/files/inspect",
        files={"file": ("低保公示.docx", payload,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        timeout=30.0)
    if resp.status_code == 404:
        return "DEFERRED: 文件通道未上线（/v1/files/inspect 404；§9 U6 自 D3 起生效）"
    if resp.status_code != 200:
        raise AssertionError(f"inspect: {resp.status_code} {resp.text[:200]!r}")
    report = resp.json()
    summary = report.get("summary") or {}
    if summary.get("ID_CARD", 0) < 1 or summary.get("PHONE_MOBILE", 0) < 1:
        raise AssertionError(f"inspect summary misses seeded PII: {summary}")
    exported = ctx["client"].post(
        "/v1/files/export", data={"mode": "sanitize"},
        files={"file": ("低保公示.docx", payload,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        timeout=30.0)
    if exported.status_code != 200:
        raise AssertionError(f"export: {exported.status_code} {exported.text[:200]!r}")
    if not exported.headers.get("x-report-id"):
        raise AssertionError("export missing X-Report-Id header")
    reopened = Document(io.BytesIO(exported.content))
    text = "\n".join(p.text for p in reopened.paragraphs)
    _assert_no_raw(text.encode("utf-8"), (ID_B, PHONE_A), "exported docx")
    return "inspect 命中 seeded PII；export 后重解析零残留"


def main() -> int:
    ctx: dict[str, Any] = {"chat_sent": 0}
    mocks: list[subprocess.Popen] = []
    try:
        # §9 步骤 1–2：拉起两 mock 子进程 + 网关（真实端口），并复位缓冲
        mocks.append(_start_mock(MOCK_PORT_INTERNET))
        mocks.append(_start_mock(MOCK_PORT_GOVCLOUD))
        ctx["mock_internet"] = f"http://127.0.0.1:{MOCK_PORT_INTERNET}"
        ctx["mock_govcloud"] = f"http://127.0.0.1:{MOCK_PORT_GOVCLOUD}"
        for base in (ctx["mock_internet"], ctx["mock_govcloud"]):
            httpx.post(f"{base}/admin/reset", timeout=5.0)
        _start_gateway(ctx)
        ctx["client"] = httpx.Client(base_url=GATEWAY_BASE, timeout=httpx.Timeout(30.0))

        cases: list[tuple[str, Any]] = [
            ("U1 非流式往返", case_u1),
            ("U2 流式往返+重放20", case_u2),
            ("U3 三路由", case_u3),
            ("U4 工具调用还原", case_u4),
            ("U5 审计入库", case_u5),
            ("U6 文件通道", case_u6),
        ]
        for name, fn in cases:
            _record(name, lambda f=fn: f(ctx))
    finally:
        _stop_gateway(ctx)
        for proc in mocks:
            proc.terminate()
        for proc in mocks:
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()

    # §9 步骤 4：PASS/FAIL 摘要
    print("=" * 64)
    print("e2e_smoke（§9 六用例；U1–U5 当天生效，U6 D3 起生效）")
    print("=" * 64)
    for name, status, detail in RESULTS:
        print(f"{status:<7} {name} — {detail}")
    passed = sum(1 for _, s, _ in RESULTS if s == "PASS")
    failed = sum(1 for _, s, _ in RESULTS if s == "FAIL")
    deferred = sum(1 for _, s, _ in RESULTS if s == "DEFER")
    print("-" * 64)
    print(f"e2e_smoke: {passed} PASS, {failed} FAIL, {deferred} DEFERRED "
          f"(共发送 {ctx['chat_sent']} 个 /v1/chat/completions 请求)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
