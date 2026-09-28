"""T0.5 流式链路自测：SSE 透传 + remap 状态机 + 流式 AI 生成标识。

运行::

    cd REPO_ROOT && PYTHONUTF8=1 ./.venv/Scripts/python.exe -m evals.t0_stream

exit 0 = 通过。检查项（对应任务单 T0.5 完成定义：对 mock 上游的流式响应，
客户端收到的文本已还原、无占位符泄漏、带 AI 标识）：
1. fixtures：mock 上游 :8901/:8902 拉起并复位；网关 app（真实 config + 注入密钥）；
2. 流式普通样例：stream=true → 200 text/event-stream；x-anongw-* 三头齐全 +
   x-anongw-ai-label: 1；SSE 帧合法、[DONE] 收尾；
   delta 拼接 == mock 回显**还原版**（原值在位、占位符形状零残留）；
   内容尾部带 AI 标识行；finish chunk delta 带 ``annotations`` 元数据字段；
3. 上游收到的仍是**全占位符**（/admin/text bytes 级零原值）；
4. remap 状态机（单元级）：随机 1–7 字符切块 fuzz —— ``feed()*k + flush()``
   恒等于整段 restore（含占位符相邻/文本无占位符/未知占位符混排三种模板）；
   显式跨块切分占位符；缓冲有界（≤32）；超 32 字符无闭合 → 普通文本放行；
   流末 flush 残留候选；
5. SSE 字节层：任意字节切块（含把多字节 UTF-8 切成两半）→ 半行缓冲解析
   逐事件全等；经 compose_chat_stream 全管线输出与整段处理全等；
6. 密级样例 stream=true → 403 content_blocked（普通 JSON，非 SSE），上游零感知；
7. 批量名单 stream=true → GOVCLOUD 经 8902，还原 + AI 标识 + 上游零原值；
8. 工具调用流式：arguments 增量 hold，finish 前不发放；finish 时**单个 delta**
   整体还原（JSON 可解析、原值在位、占位符零残留），finish_reason=tool_calls；
9. 干净文本流式：占位符零涉及，还原 = 原文，AI 标识仍在；
10. 审计：每个已处理流式请求一条事件；response_preview 为**还原前占位符版本**；
    全部 preview bytes 级零原值；
11. 上游不可达 + stream=true → 502 upstream_error 信封（开流前决出，非 SSE）。
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import socket
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("MOCK_KEY", "mock-demo-key")  # 上游 api_key_env 在请求期解析

from httpx import ASGITransport  # noqa: E402

from audit.store import InMemoryAuditStore  # noqa: E402
from common.config import load_app_config, load_dept_keys  # noqa: E402
from gateway import sse  # noqa: E402
from gateway.app import create_app  # noqa: E402
from gateway.mock_upstream import ECHO_MARKER, MockUpstreamServer  # noqa: E402
from gateway.pipeline import GatewayService  # noqa: E402
from masking.mapper import RESTORE_PATTERN, SessionMapper  # noqa: E402
from masking.remap import MAX_PLACEHOLDER_LEN, StreamRestorer  # noqa: E402
from recognizers.models import EntityClass  # noqa: E402

RESULTS: list[tuple[bool, str]] = []

DEPT = "民政局"
DEMO_KEY = "dk_5e6f7a8b"
MASK_KEY = "ab" * 32

ID_OK = "11010519491231002X"
PHONE_A = "138 0013 8000"          # 分隔符写法（归一化 → 13800138000）
PHONE_B = "13800138000"

NORMAL_TEXT = f"居民张三的身份证号{ID_OK}，手机号{PHONE_A}，请核对低保申领材料。"
# 还原版：占位符 → 归一化原值（手机号去分隔符），其余逐字不变
RESTORED_NORMAL = f"居民张三的身份证号{ID_OK}，手机号{PHONE_B}，请核对低保申领材料。"
EXPECTED_ECHO = f"{ECHO_MARKER}internet_mock\n{RESTORED_NORMAL}"
LABEL = "本内容由AI生成"
LABEL_TAIL = "\n" + LABEL

BATCH_TEXT = "低保名单：11010519491231002X；110105194912311019；110105194912312027；联系电话13800138000"
CLASSIFIED_TEXT = "机密★项目纪要：张三，手机号13800138002，不得外传。"
CLEAN_TEXT = "今天下午三点召开全镇防汛工作会议，请各村干部参加。"

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


def _record(name: str, fn) -> None:
    try:
        detail = fn()
        RESULTS.append((True, f"PASS  {name}" + (f" — {detail}" if detail else "")))
    except Exception as exc:  # noqa: BLE001 — 汇总所有失败后统一退出
        RESULTS.append((False, f"FAIL  {name} — {type(exc).__name__}: {exc}"))


def _assert_port_free(port: int) -> None:
    with socket.socket() as sock:
        sock.settimeout(0.3)
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"port {port} already occupied — leftover process running?")


def _gw_client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://anongw.test")


def _auth_headers(session: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {DEMO_KEY}", "x-anongw-session-id": session}


async def _chat_stream(client: httpx.AsyncClient, body: dict[str, Any],
                       *, session: str) -> tuple[int, dict[str, str], list[str], str]:
    """POST stream=true：返回 (状态码, 响应头, SSE帧列表, 原始全文)。

    帧切分仅对 SSE 响应有意义（两空行分帧）；JSON 错误响应从原始全文解析。
    """
    events: list[str] = []
    buf = ""
    async with client.stream("POST", "/v1/chat/completions", json=body,
                             headers=_auth_headers(session)) as resp:
        status = resp.status_code
        headers = dict(resp.headers)
        async for chunk in resp.aiter_text():
            buf += chunk
            while "\n\n" in buf:
                frame, buf = buf.split("\n\n", 1)
                if frame.strip():
                    events.append(frame)
    return status, headers, events, buf


def _parse_events(frames: list[str]) -> list[dict[str, Any]]:
    """SSE 帧 → JSON 事件列表（[DONE] 帧不计入）。"""
    out: list[dict[str, Any]] = []
    for frame in frames:
        lines = [ln for ln in frame.splitlines() if ln.startswith("data:")]
        for ln in lines:
            payload = ln[len("data:"):].strip()
            if payload == "[DONE]":
                continue
            out.append(json.loads(payload))
    return out


def _has_done(frames: list[str]) -> bool:
    return any(ln.strip() == "data: [DONE]" for f in frames for ln in f.splitlines())


def _deltas(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e["choices"][0]["delta"] for e in events
            if isinstance(e, dict) and e.get("choices") and isinstance(e["choices"][0], dict)]


def _content_of(deltas: list[dict[str, Any]]) -> str:
    return "".join(d["content"] for d in deltas if isinstance(d.get("content"), str))


def _finish_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in events
            if isinstance(e, dict) and e.get("choices") and isinstance(e["choices"][0], dict)
            and e["choices"][0].get("finish_reason") is not None]


async def _admin_text(srv: MockUpstreamServer) -> bytes:
    async with httpx.AsyncClient() as raw:
        return (await raw.get(f"{srv.base_url}/admin/text")).content


# ── HTTP 检查步骤 ──────────────────────────────────────────────────
def step_fixtures(ctx: dict[str, Any]) -> str:
    _assert_port_free(8901)
    _assert_port_free(8902)
    ctx["srv1"] = MockUpstreamServer(8901).start(timeout=15.0)
    ctx["srv2"] = MockUpstreamServer(8902).start(timeout=15.0)
    for srv in (ctx["srv1"], ctx["srv2"]):
        httpx.post(f"{srv.base_url}/admin/reset", timeout=5.0)
    cfg = load_app_config()
    digests = load_dept_keys()
    ctx["audit"] = InMemoryAuditStore()
    ctx["app"] = create_app(cfg=cfg, mask_key=MASK_KEY, dept_key_digests=digests,
                            audit_store=ctx["audit"])
    ctx["cfg"] = cfg
    return "mocks on :8901/:8902 reset; gateway app with real config + in-memory audit"


def step_stream_normal(ctx: dict[str, Any]) -> str:
    """核心用例：流式响应已还原、无占位符泄漏、带 AI 标识（任务单完成定义）。"""
    async def run() -> str:
        srv1: MockUpstreamServer = ctx["srv1"]
        before = len(srv1.ring)
        async with _gw_client(ctx["app"]) as client:
            status, headers, frames, raw = await _chat_stream(
                client, {"messages": [{"role": "user", "content": NORMAL_TEXT}],
                         "model": "mock-chat", "stream": True}, session="sess_stream_normal")
        if status != 200:
            raise AssertionError(f"status {status}")
        if not headers.get("content-type", "").startswith("text/event-stream"):
            raise AssertionError(f"content-type: {headers.get('content-type')}")
        if headers.get("x-anongw-route") != "INTERNET":
            raise AssertionError(f"route header: {headers.get('x-anongw-route')}")
        if not headers.get("x-anongw-request-id", "").startswith("req_"):
            raise AssertionError("request-id header missing")
        if headers.get("x-anongw-session-id") != "sess_stream_normal":
            raise AssertionError("session-id header mismatch")
        if headers.get("x-anongw-ai-label") != "1":
            raise AssertionError(f"ai-label header: {headers.get('x-anongw-ai-label')}")
        if not _has_done(frames):
            raise AssertionError("missing [DONE] sentinel")
        events = _parse_events(frames)
        deltas = _deltas(events)
        content = _content_of(deltas)
        if not content.startswith(EXPECTED_ECHO):
            raise AssertionError(f"restored echo mismatch: {content!r}")
        if not content.endswith(LABEL_TAIL):
            raise AssertionError(f"AI label tail missing: {content!r}")
        # 去掉网关注入的标识尾注后，正文必须与整段还原全等（占位符形状零残留）
        if RESTORE_PATTERN.search(content[: -len(LABEL_TAIL)]):
            raise AssertionError(f"placeholder leaked to client: {content!r}")
        if ID_OK not in content or PHONE_B not in content:
            raise AssertionError(f"original values not restored: {content!r}")
        # AI 标识元数据字段：finish chunk 的 delta.annotations
        finish_events = _finish_events(events)
        if len(finish_events) != 1 or finish_events[0]["choices"][0]["finish_reason"] != "stop":
            raise AssertionError(f"finish events: {[e['choices'][0].get('finish_reason') for e in finish_events]}")
        annotations = finish_events[0]["choices"][0]["delta"].get("annotations")
        if not (isinstance(annotations, list) and annotations
                and annotations[0].get("type") == "ai_generated"
                and annotations[0].get("text") == LABEL):
            raise AssertionError(f"annotations metadata: {annotations}")
        # 标识尾注是最后一个内容 delta
        content_pieces = [d["content"] for d in deltas if isinstance(d.get("content"), str) and d["content"]]
        if content_pieces and content_pieces[-1] != LABEL_TAIL:
            raise AssertionError(f"label is not the last content delta: {content_pieces[-1]!r}")
        # 上游只收到占位符版本（bytes 级）
        if len(srv1.ring) != before + 1:
            raise AssertionError(f"ring delta {len(srv1.ring) - before}")
        admin = await _admin_text(srv1)
        if ID_OK.encode() in admin or PHONE_B.encode() in admin:
            raise AssertionError("raw value reached upstream (bytes-level)")
        return ("200 SSE; echo restored byte-exact (placeholder-free); AI label tail + "
                "annotations + header; upstream all-placeholder")
    return asyncio.run(run())


def step_stream_block(ctx: dict[str, Any]) -> str:
    async def run() -> str:
        srv1, srv2 = ctx["srv1"], ctx["srv2"]
        before1, before2 = len(srv1.ring), len(srv2.ring)
        async with _gw_client(ctx["app"]) as client:
            status, headers, frames, raw = await _chat_stream(
                client, {"messages": [{"role": "user", "content": CLASSIFIED_TEXT}],
                         "model": "mock-chat", "stream": True}, session="sess_stream_secret")
        if status != 403:
            raise AssertionError(f"status {status}")
        if not headers.get("content-type", "").startswith("application/json"):
            raise AssertionError(f"block should be plain JSON, got {headers.get('content-type')}")
        err = json.loads(raw)["error"]
        if err["code"] != "content_blocked":
            raise AssertionError(f"body: {raw!r}")
        if err["reasons"][0]["code"] != "CLASSIFICATION_MARK":
            raise AssertionError(f"reasons: {err['reasons']}")
        if headers.get("x-anongw-route") != "BLOCK":
            raise AssertionError(f"route header on block: {headers.get('x-anongw-route')}")
        if len(srv1.ring) != before1 or len(srv2.ring) != before2:
            raise AssertionError("blocked stream request reached an upstream")
        return "stream=true classified -> 403 content_blocked JSON (not SSE); upstreams saw nothing"
    return asyncio.run(run())


def step_stream_govcloud(ctx: dict[str, Any]) -> str:
    async def run() -> str:
        srv1, srv2 = ctx["srv1"], ctx["srv2"]
        before1, before2 = len(srv1.ring), len(srv2.ring)
        async with _gw_client(ctx["app"]) as client:
            status, headers, frames, raw = await _chat_stream(
                client, {"messages": [{"role": "user", "content": BATCH_TEXT}],
                         "model": "gov-chat", "stream": True}, session="sess_stream_batch")
        if status != 200 or headers.get("x-anongw-route") != "GOVCLOUD":
            raise AssertionError(f"{status} route={headers.get('x-anongw-route')}")
        content = _content_of(_deltas(_parse_events(frames)))
        if not content.startswith(f"{ECHO_MARKER}govcloud_local\n"):
            raise AssertionError(f"govcloud echo: {content!r}")
        if RESTORE_PATTERN.search(content):
            raise AssertionError(f"placeholder leaked: {content!r}")
        if "11010519491231002X" not in content:
            raise AssertionError(f"restore failed: {content!r}")
        if len(srv2.ring) != before2 + 1 or len(srv1.ring) != before1:
            raise AssertionError("forward split wrong")
        admin = await _admin_text(srv2)
        if b"11010519491231002X" in admin:
            raise AssertionError("raw value reached govcloud mock (bytes-level)")
        return "stream GOVCLOUD via :8902 only; restored + label; upstream bytes-clean"
    return asyncio.run(run())


def step_stream_tool_call(ctx: dict[str, Any]) -> str:
    """工具调用：arguments 增量 hold-to-finish，单个 delta 整体还原。"""
    async def run() -> str:
        async with _gw_client(ctx["app"]) as client:
            status, headers, frames, raw = await _chat_stream(
                client, {"messages": [{"role": "user", "content": NORMAL_TEXT}],
                         "model": "mock-chat", "stream": True, "tools": TOOLS},
                session="sess_stream_tool")
        if status != 200:
            raise AssertionError(f"status {status}")
        events = _parse_events(frames)
        deltas = _deltas(events)
        tool_deltas = [d for d in deltas if isinstance(d.get("tool_calls"), list)]
        if len(tool_deltas) != 1:
            raise AssertionError(f"expected single held tool delta, got {len(tool_deltas)}")
        call = tool_deltas[0]["tool_calls"][0]
        args = call["function"]["arguments"]
        try:
            parsed = json.loads(args)
        except ValueError as exc:
            raise AssertionError(f"arguments not valid JSON: {args!r}") from exc
        if parsed != {"query": RESTORED_NORMAL}:
            raise AssertionError(f"restored arguments mismatch: {parsed!r}")
        if RESTORE_PATTERN.search(args):
            raise AssertionError(f"placeholder leaked in tool arguments: {args!r}")
        finish_events = _finish_events(events)
        if not finish_events or finish_events[0]["choices"][0]["finish_reason"] != "tool_calls":
            raise AssertionError("finish_reason != tool_calls")
        # 工具路径无正文 → 无标识尾注内容 delta，但元数据字段在 finish delta 上
        ann = finish_events[0]["choices"][0]["delta"].get("annotations")
        if not (isinstance(ann, list) and ann and ann[0]["type"] == "ai_generated"):
            raise AssertionError(f"annotations missing on tool finish: {ann}")
        return "tool arguments held to finish; single restored delta (JSON exact); annotations present"
    return asyncio.run(run())


def step_stream_clean(ctx: dict[str, Any]) -> str:
    async def run() -> str:
        async with _gw_client(ctx["app"]) as client:
            status, headers, frames, raw = await _chat_stream(
                client, {"messages": [{"role": "user", "content": CLEAN_TEXT}],
                         "model": "mock-chat", "stream": True}, session="sess_stream_clean")
        if status != 200:
            raise AssertionError(f"status {status}")
        content = _content_of(_deltas(_parse_events(frames)))
        if content != f"{ECHO_MARKER}internet_mock\n{CLEAN_TEXT}{LABEL_TAIL}":
            raise AssertionError(f"clean passthrough mismatch: {content!r}")
        return "clean text streams through untouched; label still appended"
    return asyncio.run(run())


def step_stream_audit(ctx: dict[str, Any]) -> str:
    """4 个已处理流式请求（normal/block/govcloud/tool/clean 中除 unreachable 外）审计完整。"""
    events = ctx["audit"].snapshot()
    # normal + block + govcloud + tool + clean = 5 条（全部走 dept key 的请求）
    if len(events) != 5:
        raise AssertionError(f"audit rows={len(events)}, expect 5")
    normal = events[0]
    if normal.route != "INTERNET" or normal.upstream != "internet_mock" or normal.blocked:
        raise AssertionError(f"normal event: {normal.route}/{normal.upstream}/{normal.blocked}")
    if normal.class_counts != {"ID_CARD": 1, "PHONE_MOBILE": 1}:
        raise AssertionError(f"class_counts: {normal.class_counts}")
    # response_preview = 还原前占位符版本（有占位符形状、无原值）
    if "〔身份证·" not in normal.response_preview or ID_OK in normal.response_preview:
        raise AssertionError(f"response preview not placeholder-version: {normal.response_preview!r}")
    if "〔手机号·" not in normal.prompt_preview:
        raise AssertionError(f"prompt preview not masked: {normal.prompt_preview!r}")
    blocked = next(e for e in events if e.route == "BLOCK")
    if not blocked.blocked or blocked.upstream is not None:
        raise AssertionError(f"blocked event: {blocked.blocked}/{blocked.upstream}")
    if any(e.route == "GOVCLOUD" for e in events) is False:
        raise AssertionError("govcloud event missing")
    raw_values = [ID_OK, PHONE_B, "110105194912311019", "110105194912312027", "13800138002"]
    blob = "\n".join(e.prompt_preview + "\n" + e.response_preview for e in events).encode("utf-8")
    hits = [v for v in raw_values if v.encode("utf-8") in blob]
    if hits:
        raise AssertionError(f"raw values leaked into audit previews: {hits}")
    if any(e.flags for e in events):
        raise AssertionError(f"unexpected flags: {[e.flags for e in events]}")
    return "5 stream requests audited; previews placeholder-version (bytes-level zero raw)"


def step_stream_upstream_unreachable(ctx: dict[str, Any]) -> str:
    cfg = ctx["cfg"].model_copy(deep=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        dead_port = int(sock.getsockname()[1])
    cfg.upstreams[0].base_url = f"http://127.0.0.1:{dead_port}/v1"
    service = GatewayService(cfg, MASK_KEY)

    async def run() -> str:
        result = await service.handle_chat_stream(
            {"messages": [{"role": "user", "content": CLEAN_TEXT}], "stream": True},
            dept=DEPT, session_id="sess_dead", request_id="req_dead")
        if result.events is not None:
            raise AssertionError("dead upstream should not open a stream")
        if result.status_code != 502 or result.payload["error"]["code"] != "upstream_error":
            raise AssertionError(f"{result.status_code} {result.payload}")
        if len(service.audit) != 1 or service.audit.snapshot()[0].flags != ["upstream_unavailable"]:
            raise AssertionError("upstream failure not audited with flag")
        return "dead upstream + stream=true -> 502 upstream_error envelope (decided pre-stream)"
    return asyncio.run(run())


# ── 单元级检查：remap 状态机与 SSE 字节层 ─────────────────────────
def _fuzz_mapper() -> SessionMapper:
    mapper = SessionMapper("sess_remap_fuzz", MASK_KEY.encode())
    return mapper


def _split_chars(text: str, rnd: random.Random, lo: int = 1, hi: int = 7) -> list[str]:
    pieces: list[str] = []
    i = 0
    while i < len(text):
        n = rnd.randint(lo, hi)
        pieces.append(text[i : i + n])
        i += n
    return pieces


def step_remap_fuzz(ctx: dict[str, Any]) -> str:
    """随机 1–7 字符切块 fuzz：流式还原 == 整段还原（M3 fuzz 口径的单元级版）。"""
    mapper = _fuzz_mapper()
    templates = [
        # 占位符相邻 + 交错正文
        ("证件{x}与证件{y}，联系{p}或{q}；住址{a}。",
         [(EntityClass.ID_CARD, ID_OK), (EntityClass.ID_CARD, "110105194912311019"),
          (EntityClass.PHONE_MOBILE, PHONE_B), (EntityClass.PHONE_MOBILE, "13900139000"),
          (EntityClass.ADDRESS, "澄迈县老城镇示范街1号")]),
        # 无占位符纯文本
        ("本段没有任何需要脱敏的内容，仅有普通公文用语。", []),
        # 未知占位符（映射表外形状）与已知占位符混排
        ("〔未知·deadbeef〕与{x}之间。", [(EntityClass.PERSON, "张三")]),
    ]
    pairs: list[tuple[str, str]] = []  # (masked, filled)
    for tpl, values in templates:
        # 按槽位顺序把 {x} 填成原值，同时记录原值 span
        filled_parts: list[str] = []
        spans: list[tuple[int, int, EntityClass, str]] = []
        cursor = 0
        for etype, value in values:
            open_at = tpl.index("{", cursor)
            close_at = tpl.index("}", open_at)
            filled_parts.append(tpl[cursor:open_at])
            start = sum(len(p) for p in filled_parts)
            filled_parts.append(value)
            spans.append((start, start + len(value), etype, value))
            cursor = close_at + 1
        filled_parts.append(tpl[cursor:])
        filled = "".join(filled_parts)
        masked, _entries = mapper.mask(filled, spans)
        whole = mapper.restore(masked)
        if whole != filled:
            raise AssertionError(f"whole-restore sanity failed: {whole!r}")
        pairs.append((masked, filled))
    for seed in range(300):
        rnd = random.Random(seed)
        masked, filled = pairs[seed % len(pairs)]
        restorer = StreamRestorer(mapper.lookup)
        out = "".join(restorer.feed(p) for p in _split_chars(masked, rnd))
        out += restorer.flush()
        if out != filled:
            raise AssertionError(f"seed={seed} mismatch:\n out={out!r}\n exp={filled!r}")
    return "300 chunked-restore fuzz cases == whole-restore (3 templates incl. unknown-placeholder)"


def step_remap_edges(ctx: dict[str, Any]) -> str:
    """边界：显式跨块切分 / 缓冲有界 / 超 32 字符放行 / flush 残留。"""
    mapper = _fuzz_mapper()
    masked, _ = mapper.mask(f"号码{PHONE_B}", [(2, 2 + len(PHONE_B), EntityClass.PHONE_MOBILE, PHONE_B)])
    ph = masked[2:]  # 〔手机号·xxxxxxxx〕
    # 1) 占位符被切进两个 chunk（显式）
    r = StreamRestorer(mapper.lookup)
    out = r.feed("号码" + ph[:5]) + r.feed(ph[5:] + "。") + r.flush()
    if out != f"号码{PHONE_B}。":
        raise AssertionError(f"split-across-chunks: {out!r}")
    # 2) 缓冲有界：喂入占位符每一块后 pending ≤ 32；凑齐闭合即整匹替换、flush 为空
    r = StreamRestorer(mapper.lookup)
    got = []
    for piece in _split_chars(ph, random.Random(7)):
        got.append(r.feed(piece))
        if r.pending_len > MAX_PLACEHOLDER_LEN:
            raise AssertionError(f"buffer exceeded cap: {r.pending_len}")
    if "".join(got) != PHONE_B or r.flush() != "":
        raise AssertionError(f"streamed placeholder not replaced: {''.join(got)!r} flush={r.flush()!r}")
    # 3) 超 32 字符无闭合 → 普通文本放行（含其中的 〔 与后续真实占位符）
    long_plain = "〔这段远远超过三十二个字符的方括号文本没有任何占位符形状，所以必须按普通文本原样放行"
    stream_text = long_plain + "〕" + masked
    r = StreamRestorer(mapper.lookup)
    out = "".join(r.feed(p) for p in _split_chars(stream_text, random.Random(11))) + r.flush()
    if out != long_plain + "〕" + f"号码{PHONE_B}":
        raise AssertionError(f"overflow release mismatch: {out!r}")
    # 4) 流末残留候选按普通文本放行
    r = StreamRestorer(mapper.lookup)
    if (r.feed("结尾悬着一个〔没闭合") + r.flush()) != "结尾悬着一个〔没闭合":
        raise AssertionError("dangling candidate not released on flush")
    return "split-across-chunks / bounded buffer / >32 overflow release / flush dangling all correct"


async def _fake_byte_chunks(data: bytes, rnd: random.Random) -> AsyncIterator[bytes]:
    """把字节串按 1–5 字节随机切块（可切进 UTF-8 多字节字符中间）。"""
    i = 0
    while i < len(data):
        n = rnd.randint(1, 5)
        yield data[i : i + n]
        i += n


async def _drain(agen) -> list[str]:
    return [x async for x in agen]


def step_sse_byte_layer(ctx: dict[str, Any]) -> str:
    """SSE 字节层：任意字节切块（含多字节字符中间）→ 事件序列全等；全管线输出全等。"""
    async def run() -> str:
        mapper = _fuzz_mapper()
        masked, _ = mapper.mask(f"证件{ID_OK}，电话{PHONE_B}",
                                [(2, 2 + len(ID_OK), EntityClass.ID_CARD, ID_OK)])
        payloads = [
            json.dumps({"choices": [{"index": 0, "delta": {"role": "assistant", "content": ""},
                                    "finish_reason": None}]}, ensure_ascii=False),
        ]
        pieces = [masked[i:i + 3] for i in range(0, len(masked), 3)]
        for piece in pieces:
            payloads.append(json.dumps(
                {"choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]},
                ensure_ascii=False))
        payloads.append(json.dumps(
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}, ensure_ascii=False))
        # 事件文本 → SSE 帧 → 字节 → 随机切块
        expected = [*payloads, sse.SSE_DONE]  # 解析器把 [DONE] 哨兵也作为一条载荷产出
        text = "".join(f"data: {p}\n\n" for p in payloads) + "data: [DONE]\n\n"
        for seed in (1, 2, 3):
            rnd = random.Random(seed)
            got = [p async for p in sse.iter_sse_data_lines(_fake_byte_chunks(text.encode("utf-8"), rnd))]
            if got != expected:
                raise AssertionError(f"seed={seed} event mismatch:\n got={got!r}\n exp={expected!r}")
        # 全管线：字节切块 → compose → 还原 + 标识 + [DONE]
        rnd = random.Random(42)
        lines = await _drain(sse.compose_chat_stream(
            _fake_byte_chunks(text.encode("utf-8"), rnd), mapper=mapper, ai_label=LABEL))
        out_events = [json.loads(ln[len("data:"):]) for ln in lines if ln.strip() != "data: [DONE]"]
        content = _content_of(_deltas(out_events))
        if content != f"证件{ID_OK}，电话{PHONE_B}" + LABEL_TAIL:
            raise AssertionError(f"composed content mismatch: {content!r}")
        if lines[-1].strip() != "data: [DONE]":
            raise AssertionError(f"last line: {lines[-1]!r}")
        finish_events = _finish_events(out_events)
        if not finish_events or "annotations" not in finish_events[0]["choices"][0]["delta"]:
            raise AssertionError("annotations missing on finish delta")
        return "byte-level splits (incl. mid-UTF-8) parse identical; full pipeline output exact"
    return asyncio.run(run())


STEPS = (
    ("fixtures:start-and-config", step_fixtures),
    ("stream:normal-restored-labeled", step_stream_normal),
    ("stream:blocked-403-json", step_stream_block),
    ("stream:govcloud-restored", step_stream_govcloud),
    ("stream:tool-call-hold-restore", step_stream_tool_call),
    ("stream:clean-passthrough", step_stream_clean),
    ("stream:audit-previews", step_stream_audit),
    ("stream:upstream-unreachable-502", step_stream_upstream_unreachable),
    ("remap:chunked-fuzz-300", step_remap_fuzz),
    ("remap:edge-cases", step_remap_edges),
    ("sse:byte-level-partial-lines", step_sse_byte_layer),
)


def main() -> int:
    ctx: dict[str, Any] = {}
    try:
        for name, fn in STEPS:
            _record(name, lambda f=fn, c=ctx: f(c))
    finally:
        for key in ("srv1", "srv2"):
            if key in ctx:
                ctx[key].stop()

    for _, line in RESULTS:
        print(line)
    passed = sum(1 for ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"T0 GATEWAY STREAM: {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
