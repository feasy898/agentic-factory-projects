"""M5 输出侧验收（T2.2）：AI 生成标识（流/非流）、BLOCK 代答/拒答文案库、输出复检钩子。

运行::

    cd REPO_ROOT && PYTHONUTF8=1 ./.venv/Scripts/python.exe -m evals.m5_outguard

exit 0 = 通过。通过线（开发指令 §6 M5）：
1. 标识存在性·非流式：content 尾部标识行 + ``choices[0].message.annotations``
   元数据（``[{"type":"ai_generated","text":<文案>}]``，§5.6）+ 响应头
   ``x-anongw-ai-label: 1``；文案可配置（自定义/空文案两形态）；
2. 标识存在性·流式：最后一个内容 delta 即标识尾注行；finish chunk
   ``choices[0].delta.annotations`` 与非流式同名同形；SSE 头同标；
3. BLOCK 文案正确：机密★样例 403 message == 文案库 CLASSIFICATION_MARK 模板
   （流式同源），错误信封不带 AI 标识；
4. 代答命中：命中代答关键词的拦截请求，403 message = 拒答模板 + 代答文案拼尾；
5. 复检钩子：``moderate(response)`` 接口——P0 空后端恒 safe（正常回答放行）；
   flagged 后端 → 403 content_blocked（reasons code=OUTPUT_MODERATION）+ 审计
   flag=output_flagged，且复检发生在**响应侧**（上游已收到脱敏 prompt）。

被测对象：outguard 包（label/fallback/moderation/service）+ gateway 接线
（pipeline 非流式注入 / BLOCK 文案 / sse 流式管线，流式管线本体由 evals.t0_stream 钉死）。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
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

from audit.store import InMemoryAuditStore  # noqa: E402
from common.config import load_app_config, load_dept_keys  # noqa: E402
from gateway.app import create_app  # noqa: E402
from gateway.mock_upstream import ECHO_MARKER, MockUpstreamServer  # noqa: E402
from masking.mapper import RESTORE_PATTERN  # noqa: E402
from outguard import (  # noqa: E402
    ANNOTATIONS_FIELD,
    HEADER_AI_LABEL,
    ModerationVerdict,
    OutguardService,
    ai_annotations,
    ai_label_tail,
    apply_message_label,
)
from outguard.fallback import (  # noqa: E402
    DEFAULT_TEXTS_PATH,
    block_message,
    canned_answer,
    default_texts,
    load_texts,
)
from outguard.moderation import NullModerator, verdict_of  # noqa: E402
from routing.models import RouteDecision, RouteReason  # noqa: E402

RESULTS: list[tuple[bool, str]] = []

DEPT = "民政局"
DEMO_KEY = "dk_5e6f7a8b"  # 演示明文（.env.example 文档化；YAML 只存 sha256）
MASK_KEY = "ef" * 32

ID_OK = "11010519491231002X"
PHONE_A = "138 0013 8000"
PHONE_B = "13800138000"
NORMAL_TEXT = f"居民张三的身份证号{ID_OK}，手机号{PHONE_A}，请核对低保申领材料。"
# 密级样例：不含任何代答关键词（文案精确等值断言用）
CLASSIFIED_TEXT = "机密★项目纪要：张三，手机号13800138002，不得外传。"
# 代答样例：密级词（触发 BLOCK）+ 代答关键词「借阅」（触发 canned 拼尾）
CANNED_TEXT = "我想申请借阅机密★档案，具体流程是什么？"
LABEL = "本内容由AI生成"
LABEL_TAIL = "\n" + LABEL
CUSTOM_LABEL = "AI辅助生成内容（演示）"
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


class FlagAllModerator:
    """eval 用复检后端：恒 flagged（验证钩子接线与拦截语义）。"""

    def __init__(self) -> None:
        self.calls = 0
        self.last_text = ""

    def moderate(self, text: str) -> ModerationVerdict:
        self.calls += 1
        self.last_text = text
        return ModerationVerdict(verdict="flagged", categories=["eval_flag"], detail="eval 后端恒拦")


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


def _chat_body(text: str, *, stream: bool = False, tools: bool = False) -> dict[str, Any]:
    body: dict[str, Any] = {"messages": [{"role": "user", "content": text}], "stream": stream}
    if tools:
        body["tools"] = TOOLS
    return body


async def _chat(client: httpx.AsyncClient, text: str, *, session: str,
                tools: bool = False) -> httpx.Response:
    return await client.post("/v1/chat/completions", json=_chat_body(text, tools=tools),
                             headers=_auth_headers(session))


async def _chat_stream(client: httpx.AsyncClient, text: str, *, session: str,
                       ) -> tuple[int, dict[str, str], list[str]]:
    """POST stream=true：返回 (状态码, 响应头, SSE帧列表)。"""
    frames: list[str] = []
    buf = ""
    async with client.stream("POST", "/v1/chat/completions", json=_chat_body(text, stream=True),
                             headers=_auth_headers(session)) as resp:
        status = resp.status_code
        headers = dict(resp.headers)
        if status != 200:
            body = (await resp.aread()).decode("utf-8")
            return status, headers, [body]
        async for chunk in resp.aiter_text():
            buf += chunk
            while "\n\n" in buf:
                frame, buf = buf.split("\n\n", 1)
                if frame.strip():
                    frames.append(frame)
    return status, headers, frames


def _parse_events(frames: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for frame in frames:
        for ln in frame.splitlines():
            if ln.startswith("data:"):
                payload = ln[len("data:"):].strip()
                if payload and payload != "[DONE]":
                    out.append(json.loads(payload))
    return out


def _content_deltas(events: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for event in events:
        choices = event.get("choices")
        if not choices or not isinstance(choices[0], dict):
            continue
        delta = choices[0].get("delta")
        if isinstance(delta, dict) and isinstance(delta.get("content"), str):
            out.append(delta["content"])
    return out


def _finish_delta(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in events:
        choices = event.get("choices")
        if choices and isinstance(choices[0], dict) and choices[0].get("finish_reason") is not None:
            delta = choices[0].get("delta")
            return delta if isinstance(delta, dict) else {}
    return None


async def _admin_text(srv: MockUpstreamServer) -> str:
    async with httpx.AsyncClient() as raw:
        return (await raw.get(f"{srv.base_url}/admin/text")).text


# ── 单元面：文案库 / 标识辅助 / 复检后端 ──────────────────────────


def check_texts_load() -> str:
    texts = load_texts(REPO_ROOT / "config" / "outguard_texts.yaml")
    assert texts == default_texts(), "YAML 文案库必须与内置默认全等（两者内容保持一致）"
    assert texts.block_default, "block.default 不得为空"
    for code in ("CLASSIFICATION_MARK", "INJECTION", "OUTPUT_MODERATION"):
        assert texts.block_by_code.get(code), f"block.by_code 缺 {code}"
    assert texts.canned and all(e.keywords and e.answer for e in texts.canned), "canned 条目不完整"
    missing = load_texts(REPO_ROOT / "config" / "definitely_absent.yaml")
    assert missing == default_texts(), "文件缺失必须等价回落内置默认"
    assert load_texts(None) == default_texts(), "path=None 必须返回内置默认"
    return "YAML==内置默认；三类模板齐备；缺失路径等价回落"


def check_block_message() -> str:
    texts = default_texts()
    cm = RouteDecision(route="BLOCK",
                       reasons=[RouteReason(code="CLASSIFICATION_MARK", detail="命中 机密★")])
    inj = RouteDecision(route="BLOCK",
                        reasons=[RouteReason(code="INJECTION", detail="命中 注入指令")])
    unk = RouteDecision(route="BLOCK", reasons=[RouteReason(code="NOT_A_CODE")])
    empty = RouteDecision(route="BLOCK")
    assert block_message(texts, cm) == texts.block_by_code["CLASSIFICATION_MARK"]
    assert block_message(texts, inj) == texts.block_by_code["INJECTION"]
    assert block_message(texts, unk) == texts.block_default, "未配置 code 回落 default"
    assert block_message(texts, empty) == texts.block_default, "空 reasons 回落 default"
    with_canned = block_message(texts, cm, "申请借阅机密★文件")
    assert with_canned.startswith(texts.block_by_code["CLASSIFICATION_MARK"])
    assert with_canned.endswith(canned_answer(texts, "申请借阅机密★文件") or ""), "代答须拼尾"
    # 纯函数性：同入参恒同输出、入参零改动
    snapshot = cm.model_copy(deep=True)
    assert block_message(texts, cm, "借阅") == block_message(texts, cm, "借阅")
    assert cm == snapshot, "block_message 不得改动 decision"
    return "code 模板/回落 default/代答拼尾/纯函数 全过"


def check_canned_answer() -> str:
    texts = default_texts()
    hit = canned_answer(texts, "涉密档案如何借阅")
    assert hit == texts.canned[0].answer, "关键词命中须返回固定口径"
    assert canned_answer(texts, "今天天气不错") is None, "无命中返回 None"
    assert canned_answer(texts, "") is None, "空文本返回 None"
    # 条目序即优先级：首条命中生效
    from outguard.models import CannedEntry
    two = default_texts()
    two.canned.insert(0, CannedEntry(id="first", keywords=["档案"], answer="首条口径"))
    assert canned_answer(two, "档案借阅") == "首条口径", "首条命中优先"
    return "命中/未命中/空文本/首条优先 全过"


def check_label_helpers() -> str:
    assert ai_label_tail(LABEL) == LABEL_TAIL
    assert ai_annotations(LABEL) == [{"type": "ai_generated", "text": LABEL}]
    msg: dict[str, Any] = {"role": "assistant", "content": "答案"}
    apply_message_label(msg, LABEL)
    assert msg["content"] == "答案" + LABEL_TAIL, "content 尾部标识行"
    assert msg[ANNOTATIONS_FIELD] == ai_annotations(LABEL), "annotations 元数据"
    apply_message_label(msg, LABEL)
    assert msg["content"] == "答案" + LABEL_TAIL, "重复注入不得叠加尾注（annotations 幂等）"
    null_msg: dict[str, Any] = {"role": "assistant", "content": None}
    apply_message_label(null_msg, LABEL)
    assert null_msg["content"] is None, "content 非 str 不加尾注"
    assert null_msg[ANNOTATIONS_FIELD] == ai_annotations(LABEL), "元数据面仍须标识"
    return "尾注行/annotations/幂等/content=null 形态 全过"


def check_moderation() -> str:
    verdict = NullModerator().moderate("任意文本")
    assert verdict.verdict == "safe" and verdict.categories == [], "P0 空后端恒 safe"
    assert verdict_of({"verdict": "flagged", "categories": ["x"], "detail": "d"}
                      ).verdict == "flagged", "dict→模型归一化（flagged）"
    assert verdict_of({"verdict": "weird"}).verdict == "safe", "未识 verdict 归 safe（宁放行不误拦）"
    assert verdict_of({"verdict": "safe", "categories": "bad"}).categories == [], "坏 categories 容错"
    assert verdict_of(verdict) is verdict, "模型入参原样返回"
    svc = OutguardService(default_texts(), ai_label=LABEL)
    assert svc.moderate("任意文本").verdict == "safe", "缺省后端=NullModerator"
    return "NullModerator 恒 safe；dict 归一化/未知值归 safe/缺省后端 全过"


# ── 端到端面：app 接线（fixtures 见 step_fixtures）─────────────────


def step_fixtures(ctx: dict[str, Any]) -> str:
    _assert_port_free(8901)
    _assert_port_free(8902)
    ctx["srv1"] = MockUpstreamServer(8901).start(timeout=15.0)
    ctx["srv2"] = MockUpstreamServer(8902).start(timeout=15.0)
    for srv in (ctx["srv1"], ctx["srv2"]):
        httpx.post(f"{srv.base_url}/admin/reset", timeout=5.0)

    cfg = load_app_config()  # 真实 config/app.yaml（含 outguard_texts 路径与默认文案）
    digests = load_dept_keys()
    if digests[DEPT] != hashlib.sha256(DEMO_KEY.encode()).hexdigest():
        raise AssertionError("demo key doc (.env.example) out of sync with dept_keys.yaml")
    ctx["cfg"] = cfg
    ctx["audit"] = InMemoryAuditStore()
    ctx["app"] = create_app(cfg=cfg, mask_key=MASK_KEY, dept_key_digests=digests,
                            audit_store=ctx["audit"])
    return "mocks on :8901/:8902 reset; gateway app with real config + in-memory audit"


def check_nonstream_label(ctx: dict[str, Any]) -> str:
    async def run() -> str:
        async with _gw_client(ctx["app"]) as client:
            r = await _chat(client, NORMAL_TEXT, session="sess_m5_nonstream")
            assert r.status_code == 200, f"status={r.status_code}"
            assert r.headers.get(HEADER_AI_LABEL) == "1", "响应头 x-anongw-ai-label"
            data = r.json()
            message = data["choices"][0]["message"]
            assert message["content"].endswith(LABEL_TAIL), f"尾部标识行: …{message['content'][-20:]!r}"
            assert message[ANNOTATIONS_FIELD] == ai_annotations(LABEL), "annotations 元数据"
            # 标识在还原之后注入：原值在位（还原不被尾注破坏）
            body = message["content"].split(LABEL_TAIL)[0]
            assert ID_OK in body and PHONE_B in body, "还原原值在位"
            assert RESTORE_PATTERN.search(body) is None, "正文占位符形状零残留"
            # 上游 echo 头在位（内容主体未被标识替换）
            assert body.startswith(ECHO_MARKER), "echo 头在位"
        return "非流式：尾注行+annotations+响应头；还原原值在位"
    return asyncio.run(run())


def check_nonstream_label_custom_and_empty(ctx: dict[str, Any]) -> str:
    async def run() -> str:
        cfg = ctx["cfg"]
        # 自定义文案
        app_custom = create_app(cfg=cfg.model_copy(update={"ai_label": CUSTOM_LABEL}),
                                mask_key=MASK_KEY, dept_key_digests=load_dept_keys(),
                                audit_store=InMemoryAuditStore())
        async with _gw_client(app_custom) as client:
            r = await _chat(client, NORMAL_TEXT, session="sess_m5_custom")
            assert r.status_code == 200
            message = r.json()["choices"][0]["message"]
            assert message["content"].endswith("\n" + CUSTOM_LABEL), "自定义尾注文案"
            assert message[ANNOTATIONS_FIELD] == ai_annotations(CUSTOM_LABEL), "自定义 annotations"
            assert r.headers.get(HEADER_AI_LABEL) == "1"
        # 空文案 → 不注入任何标识形态
        app_empty = create_app(cfg=cfg.model_copy(update={"ai_label": ""}),
                               mask_key=MASK_KEY, dept_key_digests=load_dept_keys(),
                               audit_store=InMemoryAuditStore())
        async with _gw_client(app_empty) as client:
            r = await _chat(client, NORMAL_TEXT, session="sess_m5_empty")
            assert r.status_code == 200
            message = r.json()["choices"][0]["message"]
            assert r.headers.get(HEADER_AI_LABEL) is None, "空文案不得下发表识头"
            assert ANNOTATIONS_FIELD not in message, "空文案不得注入 annotations"
            assert not message["content"].endswith("\n"), "空文案不得留空尾注行"
        return f"自定义文案={CUSTOM_LABEL!r} 生效；空文案三形态零注入"
    return asyncio.run(run())


def check_nonstream_toolcall_label(ctx: dict[str, Any]) -> str:
    async def run() -> str:
        async with _gw_client(ctx["app"]) as client:
            r = await _chat(client, NORMAL_TEXT, session="sess_m5_tool", tools=True)
            assert r.status_code == 200, f"status={r.status_code}"
            message = r.json()["choices"][0]["message"]
            assert message["content"] is None, "工具调用响应 content=null"
            assert message[ANNOTATIONS_FIELD] == ai_annotations(LABEL), "元数据面标识照发"
            assert r.headers.get(HEADER_AI_LABEL) == "1"
        return "工具调用（content=null）：annotations+响应头，尾注跳过不破坏结构"
    return asyncio.run(run())


def check_stream_label(ctx: dict[str, Any]) -> str:
    async def run() -> str:
        async with _gw_client(ctx["app"]) as client:
            status, headers, frames = await _chat_stream(client, NORMAL_TEXT,
                                                         session="sess_m5_stream")
        assert status == 200, f"status={status}"
        assert headers.get(HEADER_AI_LABEL) == "1", "SSE 响应头 x-anongw-ai-label"
        events = _parse_events(frames)
        contents = _content_deltas(events)
        assert contents, "必须有内容 delta"
        assert contents[-1] == LABEL_TAIL, f"最后一个内容 delta 即标识尾注行: {contents[-1]!r}"
        assert "".join(contents).endswith(LABEL_TAIL), "拼接视角尾部标识行"
        finish = _finish_delta(events)
        assert finish is not None and finish.get(ANNOTATIONS_FIELD) == ai_annotations(LABEL), \
            "finish chunk delta.annotations 与非流式同名同形"
        return "流式：末内容 delta=尾注行；finish delta.annotations 同形；SSE 头同标"
    return asyncio.run(run())


def check_block_classified(ctx: dict[str, Any]) -> str:
    texts = load_texts(REPO_ROOT / "config" / "outguard_texts.yaml")
    expect = texts.block_by_code["CLASSIFICATION_MARK"]

    async def run() -> str:
        async with _gw_client(ctx["app"]) as client:
            r = await _chat(client, CLASSIFIED_TEXT, session="sess_m5_block")
            assert r.status_code == 403, f"status={r.status_code}"
            assert r.headers.get(HEADER_AI_LABEL) is None, "错误信封不带 AI 标识头"
            err = r.json()["error"]
            assert err["code"] == "content_blocked"
            assert err["message"] == expect, f"message 须为 CLASSIFICATION_MARK 模板: {err['message']!r}"
            assert err["reasons"][0]["code"] == "CLASSIFICATION_MARK"
            # 流式 BLOCK 同源（开流前决出：普通 JSON，非 SSE）
            status, headers, frames = await _chat_stream(client, CLASSIFIED_TEXT,
                                                         session="sess_m5_block_s")
            assert status == 403 and headers.get("content-type", "").startswith("application/json"), \
                "流式 BLOCK 为普通 JSON"
            err_s = json.loads(frames[0])["error"]
            assert err_s["message"] == expect, "流式 BLOCK 文案同源"
        return "密级样例：403 message==文案库模板（流/非流同源）；信封零标识"
    return asyncio.run(run())


def check_block_canned(ctx: dict[str, Any]) -> str:
    texts = load_texts(REPO_ROOT / "config" / "outguard_texts.yaml")
    expect = texts.block_by_code["CLASSIFICATION_MARK"]
    canned = texts.canned[0].answer

    async def run() -> str:
        async with _gw_client(ctx["app"]) as client:
            r = await _chat(client, CANNED_TEXT, session="sess_m5_canned")
            assert r.status_code == 403, f"status={r.status_code}"
            err = r.json()["error"]
            assert err["code"] == "content_blocked"
            assert err["message"].startswith(expect), "拒答模板在前"
            assert err["message"].endswith(canned), "代答文案拼尾"
            assert "\n" in err["message"], "模板与代答换行分隔"
        return "代答命中：403 message = 拒答模板 + 换行 + 代答口径"
    return asyncio.run(run())


def check_moderation_hook(ctx: dict[str, Any]) -> str:
    texts = load_texts(REPO_ROOT / "config" / "outguard_texts.yaml")
    expect = texts.block_by_code["OUTPUT_MODERATION"]
    moderator = FlagAllModerator()
    svc = OutguardService(default_texts(), ai_label=LABEL, moderator=moderator)
    audit = InMemoryAuditStore()
    app = create_app(cfg=ctx["cfg"], mask_key=MASK_KEY, dept_key_digests=load_dept_keys(),
                     audit_store=audit, outguard=svc)

    async def run() -> str:
        async with _gw_client(app) as client:
            r = await _chat(client, NORMAL_TEXT, session="sess_m5_mod")
            assert r.status_code == 403, f"status={r.status_code}"
            err = r.json()["error"]
            assert err["code"] == "content_blocked", "复检拦截同 content_blocked 信封"
            assert err["reasons"][0]["code"] == "OUTPUT_MODERATION", "reasons code=OUTPUT_MODERATION"
            assert err["message"] == expect, "message==OUTPUT_MODERATION 模板"
            assert "eval_flag" in err["reasons"][0]["detail"], "风险类目进 detail"
        assert moderator.calls == 1 and ID_OK in moderator.last_text, \
            "复检发生在响应侧（还原后正文，含原值）"
        # 复检在上游消费之后：mock 已收到脱敏 prompt（占位符，无原值）
        upstream_text = await _admin_text(ctx["srv1"])
        assert ID_OK not in upstream_text and "〔身份证·" in upstream_text, \
            "复检拦截不回撤上游消费；上游只见占位符"
        events = audit.snapshot()
        assert events and events[-1].flags == ["output_flagged"], f"审计 flag: {events[-1].flags}"
        assert events[-1].blocked is False, "blocked 按路由决策（输出侧拦截以 flag 区分）"
        assert ID_OK not in (await _admin_text(ctx["srv1"])), "上游文本面零原值"
        return "flagged 后端 → 403 content_blocked（OUTPUT_MODERATION）；响应侧复检；审计 flag"
    return asyncio.run(run())


def main() -> int:
    ctx: dict[str, Any] = {}
    try:
        _record("fixtures(mock :8901/:8902 + 真实 config app)", lambda: step_fixtures(ctx))
        _record("texts-load(YAML==内置默认+缺失回落)", lambda: check_texts_load())
        _record("block-message(code 模板+回落+代答拼尾+纯函数)", lambda: check_block_message())
        _record("canned-answer(命中/未命中/空文本/首条优先)", lambda: check_canned_answer())
        _record("label-helpers(尾注/annotations/幂等/content=null)", lambda: check_label_helpers())
        _record("moderation(NullModerator+dict 归一化+未知值归 safe)", lambda: check_moderation())
        if ctx.get("app") is not None:
            _record("e2e:nonstream-label(尾注行+annotations+响应头+还原在位)", lambda: check_nonstream_label(ctx))
            _record("e2e:label-config(自定义文案生效+空文案零注入)", lambda: check_nonstream_label_custom_and_empty(ctx))
            _record("e2e:toolcall-label(content=null 元数据面标识)", lambda: check_nonstream_toolcall_label(ctx))
            _record("e2e:stream-label(末 delta 尾注+finish annotations)", lambda: check_stream_label(ctx))
            _record("e2e:block-classified(403 message==模板，流/非流同源)", lambda: check_block_classified(ctx))
            _record("e2e:block-canned(代答命中拼尾)", lambda: check_block_canned(ctx))
            _record("e2e:moderation-hook(flagged→403+响应侧复检+审计 flag)", lambda: check_moderation_hook(ctx))
    finally:
        for key in ("srv1", "srv2"):
            if key in ctx:
                ctx[key].stop()

    for _, line in RESULTS:
        print(line)
    passed = sum(1 for ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"M5 OUTGUARD: {passed}/{total} checks passed")
    if total < th_min():
        print(f"FAIL  scale: {total} checks < OUTGUARD_CASES_MIN={th_min()}")
        return 1
    return 0 if passed == total else 1


def th_min() -> int:
    from evals import thresholds
    return thresholds.OUTGUARD_CASES_MIN


if __name__ == "__main__":
    sys.exit(main())
