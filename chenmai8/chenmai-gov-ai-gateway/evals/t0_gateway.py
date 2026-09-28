"""T0.4 网关非流式链路自测：mock 上游 + 网关（进程内 ASGI）全链路冒烟。

运行::

    cd REPO_ROOT && PYTHONUTF8=1 ./.venv/Scripts/python.exe -m evals.t0_gateway

exit 0 = 通过。检查项（对应任务单 T0.4 完成定义：普通样例往返还原成功、密级样例被拦）：
1. fixtures：mock 上游 :8901/:8902 拉起并复位；网关 app 经 create_app 构造（真实
   config/app.yaml + 真实 config/dept_keys.yaml，audit 内存表注入）；
2. healthz / v1/models：存活与路由目标清单（仅名字）；
3. 鉴权：无 key / 错 key → 401 unauthorized（信封形状 §5.6）；演示部门 key 命中 → 200；
4. 请求体校验：非法 JSON / 空 messages / stream=true → 400 bad_request；
5. 普通样例（U1 缩小版）：身份证+手机号 → route=INTERNET（x-anongw-* 三头齐全）；
   mock8901 收到**全占位符**（/admin/text bytes 级零原值）；客户端拿到**还原答案**
   （占位符形状零残留、原值在位）；上游请求模型名缺省取上游清单首项；
6. 会话稳定占位符：同 session 重发 → 上游收到的占位符文本全等；跨 session → 不等；
7. 批量名单（≥3 结构化号码）→ route=GOVCLOUD，mock8902 收到、mock8901 零新增；
8. 密级样例（机密★）→ 403 content_blocked，reasons[0]=CLASSIFICATION_MARK，
   两 mock 均零新增（字节级）；
9. 干净文本 → INTERNET，上游零占位符，理由码 NO_FINDING；
10. 审计 v0（内存）：事件数=已处理请求数；普通事件 class_counts/reasons/dept/upstream
    正确、preview 为占位符版本；密级事件 blocked=true、upstream=null；
    全部 preview bytes 级扫描零原值；零明文硬闸直测（泄漏原值 → RawPiiLeakError 不落库）；
11. /internal/detect：fid 请求内自增；/internal/anonymize + /internal/restore 双向往返；
12. 上游不可达 → 502 upstream_error 信封。
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import socket
import sys
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("MOCK_KEY", "mock-demo-key")  # 上游 api_key_env 在请求期解析

from httpx import ASGITransport  # noqa: E402

from audit.models import AuditEvent  # noqa: E402
from audit.store import InMemoryAuditStore, RawPiiLeakError  # noqa: E402
from common.config import load_app_config, load_dept_keys  # noqa: E402
from gateway.app import create_app  # noqa: E402
from gateway.mock_upstream import MockUpstreamServer  # noqa: E402
from gateway.pipeline import GatewayService  # noqa: E402
from masking.mapper import RESTORE_PATTERN  # noqa: E402

RESULTS: list[tuple[bool, str]] = []

DEPT = "民政局"
DEMO_KEY = "dk_5e6f7a8b"  # 演示明文（.env.example 文档化；YAML 只存 sha256）
MASK_KEY = "cd" * 32

ID_OK = "11010519491231002X"          # GB11643 校验位有效的样例号
PHONE_A = "138 0013 8000"             # 分隔符写法（归一化 → 13800138000）
PHONE_B = "13800138000"


def _valid_id(prefix17: str) -> str:
    """给定 17 位前缀，枚举校验位得到合法身份证样例（eval 专用夹具工具）。"""
    weights = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
    codes = "10X98765432"
    total = sum(int(ch) * w for ch, w in zip(prefix17, weights, strict=True))
    return prefix17 + codes[total % 11]


ID_B = _valid_id("11010519491231101")
ID_C = _valid_id("11010519491231202")

NORMAL_TEXT = f"居民张三的身份证号{ID_OK}，手机号{PHONE_A}，请核对低保申领材料。"
BATCH_TEXT = f"低保名单：{ID_OK}；{ID_B}；{ID_C}；联系电话{PHONE_B}"
CLASSIFIED_TEXT = "机密★项目纪要：张三，手机号13800138002，不得外传。"
CLEAN_TEXT = "今天下午三点召开全镇防汛工作会议，请各村干部参加。"


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


def _auth_headers(session: str = "sess_eval_normal") -> dict[str, str]:
    return {"Authorization": f"Bearer {DEMO_KEY}", "x-anongw-session-id": session}


def _chat_body(text: str, *, model: str | None = "mock-chat", stream: Any = False) -> dict[str, Any]:
    body: dict[str, Any] = {"messages": [{"role": "user", "content": text}]}
    if model is not None:
        body["model"] = model
    if stream is not None:
        body["stream"] = stream
    return body


async def _chat(client: httpx.AsyncClient, text: str, *, session: str = "sess_eval_normal",
                model: str | None = "mock-chat") -> httpx.Response:
    return await client.post("/v1/chat/completions", json=_chat_body(text, model=model),
                             headers=_auth_headers(session))


async def _admin_text(srv: MockUpstreamServer) -> bytes:
    async with httpx.AsyncClient() as raw:
        return (await raw.get(f"{srv.base_url}/admin/text")).content


# ── 检查步骤 ───────────────────────────────────────────────────────
def step_fixtures(ctx: dict[str, Any]) -> str:
    _assert_port_free(8901)
    _assert_port_free(8902)
    ctx["srv1"] = MockUpstreamServer(8901).start(timeout=15.0)
    ctx["srv2"] = MockUpstreamServer(8902).start(timeout=15.0)
    for srv in (ctx["srv1"], ctx["srv2"]):
        httpx.post(f"{srv.base_url}/admin/reset", timeout=5.0)

    cfg = load_app_config()  # 真实 config/app.yaml：8901/internet_mock + 8902/govcloud_local
    digests = load_dept_keys()  # 真实 config/dept_keys.yaml
    if digests[DEPT] != hashlib.sha256(DEMO_KEY.encode()).hexdigest():
        raise AssertionError("demo key doc (.env.example) out of sync with dept_keys.yaml")
    ctx["audit"] = InMemoryAuditStore()
    ctx["app"] = create_app(cfg=cfg, mask_key=MASK_KEY, dept_key_digests=digests,
                            audit_store=ctx["audit"])
    ctx["cfg"] = cfg
    return "mocks on :8901/:8902 reset; gateway app with real config + in-memory audit"


def step_health_models(ctx: dict[str, Any]) -> str:
    async def run() -> str:
        async with _gw_client(ctx["app"]) as client:
            health = (await client.get("/healthz")).json()
            if health.get("ok") is not True:
                raise AssertionError(f"healthz: {health}")
            models = (await client.get("/v1/models")).json()
            ids = sorted(m["id"] for m in models["data"])
            routes = {m["id"]: m["route"] for m in models["data"]}
            if "mock-chat" not in ids or "gov-chat" not in ids:
                raise AssertionError(f"models: {ids}")
            if routes["mock-chat"] != "INTERNET" or routes["gov-chat"] != "GOVCLOUD":
                raise AssertionError(f"routes: {routes}")
        return f"healthz ok; models={ids} (names only, route-tagged)"
    return asyncio.run(run())


def step_auth(ctx: dict[str, Any]) -> str:
    async def run() -> str:
        async with _gw_client(ctx["app"]) as client:
            r_none = await client.post("/v1/chat/completions", json=_chat_body(CLEAN_TEXT))
            if r_none.status_code != 401 or r_none.json()["error"]["code"] != "unauthorized":
                raise AssertionError(f"no-key: {r_none.status_code} {r_none.json()}")
            r_bad = await client.post("/v1/chat/completions", json=_chat_body(CLEAN_TEXT),
                                      headers={"Authorization": "Bearer dk_00000000"})
            if r_bad.status_code != 401:
                raise AssertionError(f"bad-key: {r_bad.status_code}")
            err = r_bad.json()["error"]
            if set(err) != {"code", "message", "reasons"}:
                raise AssertionError(f"envelope: {set(err)}")
            r_ok = await _chat(client, CLEAN_TEXT)
            if r_ok.status_code != 200:
                raise AssertionError(f"valid dept key rejected: {r_ok.status_code}")
        return "no-key/bad-key -> 401 unauthorized envelope; demo dept key -> 200"
    return asyncio.run(run())


def step_body_validation(ctx: dict[str, Any]) -> str:
    async def run() -> str:
        async with _gw_client(ctx["app"]) as client:
            r_raw = await client.post("/v1/chat/completions", content=b"{not-json",
                                      headers={**_auth_headers(), "content-type": "application/json"})
            if r_raw.status_code != 400 or r_raw.json()["error"]["code"] != "bad_request":
                raise AssertionError(f"invalid json: {r_raw.status_code}")
            r_empty = await client.post("/v1/chat/completions", json={"messages": []},
                                        headers=_auth_headers())
            if r_empty.status_code != 400:
                raise AssertionError(f"empty messages: {r_empty.status_code}")
            r_stream = await client.post("/v1/chat/completions",
                                         json=_chat_body(CLEAN_TEXT, stream=True),
                                         headers=_auth_headers())
            if r_stream.status_code != 400:
                raise AssertionError(f"stream=true should be explicit 400 in v0: {r_stream.status_code}")
        return "invalid JSON / empty messages / stream=true -> 400 bad_request"
    return asyncio.run(run())


def step_normal_roundtrip(ctx: dict[str, Any]) -> str:
    """普通样例：往返还原成功 + 上游零原值（任务单完成定义第 1 条）。"""
    async def run() -> str:
        srv1: MockUpstreamServer = ctx["srv1"]
        before = len(srv1.ring)
        async with _gw_client(ctx["app"]) as client:
            resp = await _chat(client, NORMAL_TEXT)
        if resp.status_code != 200:
            raise AssertionError(f"status {resp.status_code}: {resp.text[:200]}")
        if resp.headers.get("x-anongw-route") != "INTERNET":
            raise AssertionError(f"route header: {resp.headers.get('x-anongw-route')}")
        if not resp.headers.get("x-anongw-request-id", "").startswith("req_"):
            raise AssertionError("request-id header missing")
        if resp.headers.get("x-anongw-session-id") != "sess_eval_normal":
            raise AssertionError("session-id header mismatch")
        content = resp.json()["choices"][0]["message"]["content"]
        if RESTORE_PATTERN.search(content):
            raise AssertionError(f"placeholder leaked to client: {content!r}")
        if ID_OK not in content or PHONE_B not in content:
            raise AssertionError(f"original values not restored: {content!r}")
        if len(srv1.ring) != before + 1:
            raise AssertionError(f"8901 ring delta {len(srv1.ring) - before}")
        upstream_text = srv1.ring.snapshot()[-1]["last_user_content"]
        if ID_OK.encode() in (await _admin_text(srv1)) or PHONE_B.encode() in (await _admin_text(srv1)):
            raise AssertionError("raw value reached upstream (bytes-level)")
        if "〔身份证·" not in upstream_text or "〔手机号·" not in upstream_text:
            raise AssertionError(f"upstream text lacks placeholders: {upstream_text!r}")
        body = resp.json()
        if body["model"] != "mock-chat" or body["usage"]["total_tokens"] <= 0:
            raise AssertionError(f"passthrough shape: model={body['model']} usage={body['usage']}")
        return "200 INTERNET; upstream all-placeholder (bytes-clean); client restored (zero placeholder shape)"
    return asyncio.run(run())


def step_session_stability(ctx: dict[str, Any]) -> str:
    async def run() -> str:
        srv1: MockUpstreamServer = ctx["srv1"]
        async with _gw_client(ctx["app"]) as client:
            await _chat(client, NORMAL_TEXT, session="sess_stab_a")
            up_a1 = srv1.ring.snapshot()[-1]["last_user_content"]
            await _chat(client, NORMAL_TEXT, session="sess_stab_a")
            up_a2 = srv1.ring.snapshot()[-1]["last_user_content"]
            await _chat(client, NORMAL_TEXT, session="sess_stab_b")
            up_b = srv1.ring.snapshot()[-1]["last_user_content"]
        if up_a1 != up_a2:
            raise AssertionError("same session produced different placeholders")
        if up_a1 == up_b:
            raise AssertionError("different sessions produced identical placeholders")
        return "same-session placeholder text identical; cross-session differs (design intent)"
    return asyncio.run(run())


def step_batch_govcloud(ctx: dict[str, Any]) -> str:
    async def run() -> str:
        srv1: MockUpstreamServer = ctx["srv1"]
        srv2: MockUpstreamServer = ctx["srv2"]
        before1, before2 = len(srv1.ring), len(srv2.ring)
        async with _gw_client(ctx["app"]) as client:
            resp = await _chat(client, BATCH_TEXT, session="sess_eval_batch")
        if resp.headers.get("x-anongw-route") != "GOVCLOUD":
            raise AssertionError(f"route: {resp.headers.get('x-anongw-route')}")
        if len(srv2.ring) != before2 + 1 or len(srv1.ring) != before1:
            raise AssertionError(f"forward split wrong: 8901+{len(srv1.ring)-before1}, 8902+{len(srv2.ring)-before2}")
        up = srv2.ring.snapshot()[-1]["last_user_content"]
        for rid in (ID_OK, "110105194912311019", "110105194912312027", PHONE_B):
            if rid.encode() in (await _admin_text(srv2)):
                raise AssertionError(f"raw {rid} reached govcloud mock")
        if "〔身份证·" not in up:
            raise AssertionError("govcloud upstream text lacks placeholders")
        if resp.json()["choices"][0]["message"]["content"].find(ID_OK) == -1:
            raise AssertionError("client restore failed on govcloud path")
        return "route=GOVCLOUD via 8902 only; masked upstream; client answer restored"
    return asyncio.run(run())


def step_classified_block(ctx: dict[str, Any]) -> str:
    """密级样例：拦截（任务单完成定义第 2 条）。"""
    async def run() -> str:
        srv1: MockUpstreamServer = ctx["srv1"]
        srv2: MockUpstreamServer = ctx["srv2"]
        before1, before2 = len(srv1.ring), len(srv2.ring)
        async with _gw_client(ctx["app"]) as client:
            resp = await _chat(client, CLASSIFIED_TEXT, session="sess_eval_secret")
        if resp.status_code != 403:
            raise AssertionError(f"status {resp.status_code}")
        err = resp.json()["error"]
        if err["code"] != "content_blocked":
            raise AssertionError(f"code: {err['code']}")
        if err["reasons"][0]["code"] != "CLASSIFICATION_MARK" or "机密★" not in err["reasons"][0]["detail"]:
            raise AssertionError(f"reasons: {err['reasons']}")
        if "x-anongw-route" not in resp.headers:
            raise AssertionError("route header missing on block")
        if len(srv1.ring) != before1 or len(srv2.ring) != before2:
            raise AssertionError("blocked request reached an upstream")
        return "403 content_blocked (CLASSIFICATION_MARK); both mocks saw nothing"
    return asyncio.run(run())


def step_clean_text(ctx: dict[str, Any]) -> str:
    async def run() -> str:
        srv1: MockUpstreamServer = ctx["srv1"]
        before = len(srv1.ring)
        async with _gw_client(ctx["app"]) as client:
            resp = await _chat(client, CLEAN_TEXT, session="sess_eval_clean")
        if resp.headers.get("x-anongw-route") != "INTERNET" or len(srv1.ring) != before + 1:
            raise AssertionError("clean text should flow INTERNET via 8901")
        up = srv1.ring.snapshot()[-1]["last_user_content"]
        if "〔" in up:
            raise AssertionError(f"clean text should not be masked: {up!r}")
        audit_events = ctx["audit"].snapshot()
        if audit_events[-1].reasons != ["NO_FINDING"] or audit_events[-1].blocked:
            raise AssertionError(f"reasons: {audit_events[-1].reasons}")
        return "INTERNET passthrough untouched; audit reasons=[NO_FINDING]"
    return asyncio.run(run())


def step_audit(ctx: dict[str, Any]) -> str:
    events = ctx["audit"].snapshot()
    # 已审计请求数：auth步 1 + normal 1 + stab×3 + batch 1 + classified 1 + clean 1 = 8
    if len(events) != 8:
        raise AssertionError(f"audit rows={len(events)}, expect 8")
    auth_ok, normal = events[0], events[1]
    if auth_ok.reasons != ["NO_FINDING"] or auth_ok.class_counts != {}:
        raise AssertionError(f"auth-step event: {auth_ok.reasons}/{auth_ok.class_counts}")
    if normal.route != "INTERNET" or normal.blocked or normal.dept != DEPT:
        raise AssertionError(f"normal event: {normal.route}/{normal.blocked}/{normal.dept}")
    if normal.class_counts != {"ID_CARD": 1, "PHONE_MOBILE": 1}:
        raise AssertionError(f"class_counts: {normal.class_counts}")
    if normal.reasons != ["SINGLE_STRUCTURED_PII"] or normal.upstream != "internet_mock":
        raise AssertionError(f"reasons/upstream: {normal.reasons}/{normal.upstream}")
    if "〔身份证·" not in normal.prompt_preview or ID_OK in normal.prompt_preview:
        raise AssertionError(f"prompt preview not masked: {normal.prompt_preview!r}")
    if "〔" not in normal.response_preview or RESTORE_PATTERN.search(normal.response_preview) is None:
        raise AssertionError(f"response preview should be placeholder version: {normal.response_preview!r}")
    secret = next(e for e in events if e.route == "BLOCK")
    if not secret.blocked or secret.upstream is not None:
        raise AssertionError(f"blocked event: blocked={secret.blocked} upstream={secret.upstream}")
    if not secret.reasons or secret.reasons[0] != "CLASSIFICATION_MARK" \
            or any(code != "CLASSIFICATION_MARK" for code in secret.reasons):
        # 样例命中两个密级词（机密★/不得外传）→ 每词一条理由，第一条为决定性理由
        raise AssertionError(f"blocked reasons: {secret.reasons}")
    batch = next(e for e in events if e.route == "GOVCLOUD")
    if batch.class_counts.get("ID_CARD") != 3 or "BATCH_STRUCTURED_PII" not in batch.reasons:
        raise AssertionError(f"batch event: {batch.class_counts}/{batch.reasons}")
    if any(e.latency_ms < 0 for e in events):
        raise AssertionError("latency negative")
    raw_values = [ID_OK, ID_B, ID_C, PHONE_B, "13800138002"]
    blob = "\n".join(e.prompt_preview + "\n" + e.response_preview for e in events).encode("utf-8")
    hits = [v for v in raw_values if v.encode("utf-8") in blob]
    if hits:
        raise AssertionError(f"raw values leaked into audit previews: {hits}")
    return "8 events; shapes/counts/reasons correct; previews placeholder-only (bytes-level clean)"


def step_audit_raw_gate(ctx: dict[str, Any]) -> str:
    store = InMemoryAuditStore()
    leaking = AuditEvent(ts="2026-09-28T00:00:00Z", prompt_preview=f"身份证{ID_OK}")
    try:
        store.append(leaking, [ID_OK])
    except RawPiiLeakError:
        pass
    else:
        raise AssertionError("raw-PII gate did not trip")
    if len(store) != 0:
        raise AssertionError("leaking event must not be stored")
    clean = AuditEvent(ts="2026-09-28T00:00:00Z", prompt_preview="身份证〔身份证·abcd1234〕")
    store.append(clean, [ID_OK])
    if len(store) != 1:
        raise AssertionError("clean event should be stored")
    return "assert_no_raw_pii trips on raw value (not stored); masked preview stored"


def step_internal_endpoints(ctx: dict[str, Any]) -> str:
    async def run() -> str:
        async with _gw_client(ctx["app"]) as client:
            d = (await client.post("/internal/detect", json={"text": f"联系{PHONE_B}，证件{ID_OK}"})).json()
            fids = [f["fid"] for f in d["findings"]]
            if fids != ["f_0001", "f_0002"] or d["findings"][0]["normalized"] != PHONE_B:
                raise AssertionError(f"detect: {d}")
            a = (await client.post("/internal/anonymize",
                                   json={"text": f"证件{ID_OK}", "session_id": "sess_internal"})).json()
            if "〔身份证·" not in a["masked"] or not a["mappings"]:
                raise AssertionError(f"anonymize: {a}")
            r = (await client.post("/internal/restore",
                                   json={"text": a["masked"], "session_id": "sess_internal"})).json()
            if r["restored"] != f"证件{ID_OK}":
                raise AssertionError(f"restore: {r}")
        return "detect fid auto-increment; anonymize/restore round-trip equal"
    return asyncio.run(run())


def step_upstream_unreachable(ctx: dict[str, Any]) -> str:
    cfg = ctx["cfg"].model_copy(deep=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        dead_port = int(sock.getsockname()[1])
    cfg.upstreams[0].base_url = f"http://127.0.0.1:{dead_port}/v1"
    service = GatewayService(cfg, MASK_KEY)

    async def run() -> str:
        result = await service.handle_chat(
            _chat_body(CLEAN_TEXT), dept=DEPT, session_id="sess_dead", request_id="req_dead")
        if result.status_code != 502 or result.payload["error"]["code"] != "upstream_error":
            raise AssertionError(f"{result.status_code} {result.payload}")
        if len(service.audit) != 1 or service.audit.snapshot()[0].flags != ["upstream_unavailable"]:
            raise AssertionError("upstream failure not audited with flag")
        return "dead upstream -> 502 upstream_error envelope; audited with flag"
    return asyncio.run(run())


STEPS = (
    ("fixtures:start-and-config", step_fixtures),
    ("health+models", step_health_models),
    ("auth:401-and-dept-key", step_auth),
    ("body:validation-400", step_body_validation),
    ("chat:normal-roundtrip", step_normal_roundtrip),
    ("chat:session-stable-placeholders", step_session_stability),
    ("chat:batch-govcloud", step_batch_govcloud),
    ("chat:classified-blocked", step_classified_block),
    ("chat:clean-passthrough", step_clean_text),
    ("audit:in-memory-store", step_audit),
    ("audit:raw-pii-gate", step_audit_raw_gate),
    ("internal:detect-anonymize-restore", step_internal_endpoints),
    ("upstream:unreachable-502", step_upstream_unreachable),
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
    print(f"T0 GATEWAY NONSTREAM: {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
