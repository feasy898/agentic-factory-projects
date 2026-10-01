"""T0.3 mock 上游自测：拉起两实例并用 httpx 调通（可作 evals/e2e fixture 复用）。

运行::

    cd REPO_ROOT && PYTHONUTF8=1 ./.venv/Scripts/python.exe -m evals.t0_mock_upstream

exit 0 = 通过。检查项：
1. fixture 启动：:8901(internet_mock/mock-chat)、:8902(govcloud_local/gov-chat) 两实例
   经 MockUpstreamServer 类 API 拉起，/healthz 就绪；
2. /v1/models 清单与实例配置一致；
3. 非流式回显：OpenAI 响应形状 + 最后一条 user 消息原样出现在回答尾部 + 头部实例名；
4. ring buffer（HTTP 视图）：/admin/records 记录逐字等于请求（messages/last_user_content）；
5. ring buffer（进程内直读）：srv.ring 与 HTTP 视图全等（fixture 双通道）；
6. 流式回显：SSE 事件逐块可解析、delta 拼接与非流式回显全等（确定性）、[DONE] 收尾、
   finish_reason=stop、小切块生效（≥2 块）、多字节 UTF-8 逐字节全等；
7. 工具调用：非流式返回 tool_calls（arguments={"query": 原文}）；流式 tool_calls
   arguments 分块拼接与非流式全等；
8. /admin/text 全文 bytes 级包含原文（e2e 零原值断言的取数通道）；
9. /admin/reset 清空后 records=0、text 为空；
10. 错误形状：空 messages → 400 OpenAI 风格错误信封；
11. fixture 复用性：临时端口 start→stop→同端口 restart→stop；
12. CLI 形态：子进程 ``python -m gateway.mock_upstream --port <临时>`` 拉起、回显、
    /admin/records 生效、terminate 退出（§9 "同一 app 不同 argv" 的两实例形态）。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gateway.mock_upstream import ECHO_MARKER, MockUpstreamServer  # noqa: E402

RESULTS: list[tuple[bool, str]] = []

PROBE = ("请核对本人民俗申报材料：张三，身份证号 460022199003071234，手机 13800138000，"
         "住址澄迈县老城镇示范街１２３号（多字节：①②③·全角）。")
PROBE2 = "低保名单核验：李四 460022199003071235，联系电话 13900139000"
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


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _assert_port_free(port: int) -> None:
    with socket.socket() as sock:
        sock.settimeout(0.3)
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"port {port} already occupied — leftover mock upstream running?")


def _chat_payload(text: str, *, stream: bool = False, tools: list | None = None,
                  model: str = "mock-chat") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": text}],
        "stream": stream,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    return payload


def _sse_events(client: httpx.Client, url: str, payload: dict[str, Any]) -> tuple[list[Any], str | None, int]:
    """POST 流式请求并解析 SSE：返回 (data 事件列表(以 None 代表 [DONE]), 实例名, 事件数)。"""
    events: list[Any] = []
    instance: str | None = None
    n_chunks = 0
    with client.stream("POST", url, json=payload, timeout=15.0) as resp:
        if resp.status_code != 200:
            raise AssertionError(f"stream status {resp.status_code}: {resp.read()[:200]!r}")
        instance = resp.headers.get("x-mock-instance")
        ctype = resp.headers.get("content-type", "")
        if "text/event-stream" not in ctype:
            raise AssertionError(f"content-type not SSE: {ctype}")
        for line in resp.iter_lines():
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                events.append(None)
                break
            events.append(json.loads(data))
            n_chunks += 1
    return events, instance, n_chunks


def _join_deltas(events: list[Any]) -> tuple[str, str | None, str | None]:
    """拼接 content deltas；同时返回 finish_reason 与 tool_calls arguments 拼接。"""
    parts: list[str] = []
    args_parts: list[str] = []
    finish: str | None = None
    for ev in events:
        if ev is None:
            continue
        for choice in ev.get("choices", []):
            delta = choice.get("delta", {})
            if delta.get("content"):
                parts.append(delta["content"])
            for tc in delta.get("tool_calls") or []:
                args_parts.append(tc.get("function", {}).get("arguments", ""))
            if choice.get("finish_reason"):
                finish = choice["finish_reason"]
    return "".join(parts), finish, "".join(args_parts) or None


# ── 检查步骤 ───────────────────────────────────────────────────────
def step_start_servers(ctx: dict[str, Any]) -> str:
    _assert_port_free(8901)
    _assert_port_free(8902)
    srv1 = MockUpstreamServer(8901).start(timeout=15.0)
    srv2 = MockUpstreamServer(8902).start(timeout=15.0)
    ctx["srv1"], ctx["srv2"] = srv1, srv2
    for srv, want in ((srv1, ("internet_mock", ["mock-chat"])), (srv2, ("govcloud_local", ["gov-chat"]))):
        health = httpx.get(f"{srv.base_url}/healthz", timeout=5.0).json()
        if health != {"ok": True, "instance": want[0], "models": want[1]}:
            raise AssertionError(f"healthz mismatch: {health}")
    return "8901=internet_mock, 8902=govcloud_local both ready"


def step_models_list(ctx: dict[str, Any]) -> str:
    seen = []
    for srv, want in ((ctx["srv1"], "mock-chat"), (ctx["srv2"], "gov-chat")):
        data = httpx.get(f"{srv.base_url}/v1/models", timeout=5.0).json()
        ids = [m["id"] for m in data["data"]]
        if ids != [want]:
            raise AssertionError(f"{srv.name}: models={ids}")
        seen.append(f"{srv.name}:{ids[0]}")
    return ", ".join(seen)


def step_echo_nonstream(ctx: dict[str, Any]) -> str:
    resp = httpx.post(f"{ctx['srv1'].base_url}/v1/chat/completions",
                      json=_chat_payload(PROBE), timeout=10.0)
    if resp.status_code != 200:
        raise AssertionError(f"status {resp.status_code}")
    if resp.headers.get("x-mock-instance") != "internet_mock":
        raise AssertionError(f"instance header: {resp.headers.get('x-mock-instance')}")
    body = resp.json()
    if body["object"] != "chat.completion" or not body["id"].startswith("chatcmpl-"):
        raise AssertionError(f"envelope: {body['object']}/{body['id']}")
    choice = body["choices"][0]
    msg = choice["message"]
    if msg["role"] != "assistant" or choice["finish_reason"] != "stop":
        raise AssertionError(f"choice: role={msg['role']} finish={choice['finish_reason']}")
    expected = f"{ECHO_MARKER}internet_mock\n{PROBE}"
    if msg["content"] != expected:
        raise AssertionError("echo content not verbatim")
    usage = body["usage"]
    if not (usage["prompt_tokens"] > 0 and usage["completion_tokens"] > 0
            and usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]):
        raise AssertionError(f"usage: {usage}")
    ctx["echo_8901"] = msg["content"]
    return "shape + verbatim echo + instance header + usage ok"


def step_ring_http(ctx: dict[str, Any]) -> str:
    data = httpx.get(f"{ctx['srv1'].base_url}/admin/records", timeout=5.0).json()
    if data["instance"] != "internet_mock" or data["count"] < 1:
        raise AssertionError(f"count={data['count']}")
    last = data["records"][-1]
    if last["last_user_content"] != PROBE:
        raise AssertionError("last_user_content not verbatim")
    if last["messages"] != [{"role": "user", "content": PROBE}]:
        raise AssertionError("messages not verbatim")
    if last["stream"] is not False or last["tools"] != [] or last["tool_call"] is not False:
        raise AssertionError(f"flags wrong: stream={last['stream']} tools={last['tools']}")
    if last["auth_header_present"] is not False:
        raise AssertionError("auth_header_present should be False (no auth sent)")
    return f"count={data['count']}, last record verbatim"


def step_ring_direct(ctx: dict[str, Any]) -> str:
    http_view = httpx.get(f"{ctx['srv1'].base_url}/admin/records", timeout=5.0).json()["records"]
    direct_view = ctx["srv1"].ring.snapshot()
    if direct_view != http_view:
        raise AssertionError("direct ring != HTTP view")
    if not ctx["srv1"].ring.texts():
        raise AssertionError("texts() empty")
    return "srv.ring (in-process) equals /admin/records"


def step_echo_stream(ctx: dict[str, Any]) -> str:
    events, instance, n_chunks = _sse_events(
        ctx["client"], f"{ctx['srv2'].base_url}/v1/chat/completions", _chat_payload(PROBE, stream=True))
    if instance != "govcloud_local":
        raise AssertionError(f"instance header: {instance}")
    if not events or events[-1] is not None:
        raise AssertionError("missing [DONE] terminator")
    content, finish, tool_args = _join_deltas(events)
    if finish != "stop" or tool_args is not None:
        raise AssertionError(f"finish={finish} tool_args={tool_args!r}")
    expected = f"{ECHO_MARKER}govcloud_local\n{PROBE}"
    if content != expected:
        raise AssertionError("joined stream content != nonstream echo (determinism broken)")
    if content.encode("utf-8") != expected.encode("utf-8"):
        raise AssertionError("multibyte bytes not identical")
    if n_chunks < 2:
        raise AssertionError(f"chunking ineffective: {n_chunks} data events")
    return f"{n_chunks} data events, joined content byte-identical to echo"


def step_tools_nonstream(ctx: dict[str, Any]) -> str:
    resp = httpx.post(f"{ctx['srv1'].base_url}/v1/chat/completions",
                      json=_chat_payload(PROBE2, tools=TOOLS, model="mock-chat"), timeout=10.0)
    if resp.status_code != 200:
        raise AssertionError(f"status {resp.status_code}")
    body = resp.json()
    choice = body["choices"][0]
    msg = choice["message"]
    if choice["finish_reason"] != "tool_calls":
        raise AssertionError(f"finish={choice['finish_reason']}")
    calls = msg.get("tool_calls") or []
    if len(calls) != 1 or calls[0]["type"] != "function":
        raise AssertionError(f"tool_calls: {calls}")
    fn = calls[0]["function"]
    if fn["name"] != "query_lowincome_record":
        raise AssertionError(f"tool name: {fn['name']}")
    if json.loads(fn["arguments"]) != {"query": PROBE2}:
        raise AssertionError(f"arguments: {fn['arguments']}")
    ctx["tool_args"] = fn["arguments"]
    return f"tool_calls({fn['name']}) arguments echo verbatim"


def step_tools_stream(ctx: dict[str, Any]) -> str:
    events, _, n_chunks = _sse_events(
        ctx["client"], f"{ctx['srv2'].base_url}/v1/chat/completions",
        _chat_payload(PROBE2, stream=True, tools=TOOLS, model="gov-chat"))
    if events[-1] is not None:
        raise AssertionError("missing [DONE]")
    _, finish, args = _join_deltas(events)
    if finish != "tool_calls":
        raise AssertionError(f"finish={finish}")
    if args != ctx["tool_args"]:
        raise AssertionError("streamed tool arguments != nonstream arguments")
    return f"arguments streamed in {n_chunks} events, concatenation equal"


def step_admin_text(ctx: dict[str, Any]) -> str:
    hits = 0
    for srv, probe in ((ctx["srv1"], PROBE2), (ctx["srv2"], PROBE)):
        text = httpx.get(f"{srv.base_url}/admin/text", timeout=5.0)
        if probe.encode("utf-8") not in text.content:
            raise AssertionError(f"{srv.name}: probe bytes missing from /admin/text")
        hits += 1
    return f"{hits} instances expose full received text (bytes-level ready for e2e)"


def step_admin_reset(ctx: dict[str, Any]) -> str:
    for srv in (ctx["srv1"], ctx["srv2"]):
        cleared = httpx.post(f"{srv.base_url}/admin/reset", timeout=5.0).json()["cleared"]
        if cleared < 1:
            raise AssertionError(f"{srv.name}: cleared={cleared}")
        after = httpx.get(f"{srv.base_url}/admin/records", timeout=5.0).json()
        if after["count"] != 0:
            raise AssertionError(f"{srv.name}: count after reset = {after['count']}")
        if httpx.get(f"{srv.base_url}/admin/text", timeout=5.0).content != b"":
            raise AssertionError(f"{srv.name}: text after reset not empty")
    return "both instances reset to zero"


def step_error_shape(ctx: dict[str, Any]) -> str:
    resp = httpx.post(f"{ctx['srv1'].base_url}/v1/chat/completions",
                      json={"model": "mock-chat", "messages": []}, timeout=10.0)
    if resp.status_code != 400:
        raise AssertionError(f"status {resp.status_code}")
    err = resp.json().get("error")
    if not isinstance(err, dict) or set(err) != {"message", "type", "param", "code"}:
        raise AssertionError(f"error envelope: {err}")
    return "empty messages -> 400 OpenAI-style error envelope"


def step_fixture_restart(ctx: dict[str, Any]) -> str:
    port = _free_port()
    with MockUpstreamServer(port, name="restart_probe") as srv:
        if httpx.get(f"{srv.base_url}/healthz", timeout=5.0).json()["ok"] is not True:
            raise AssertionError("first start not healthy")
    with MockUpstreamServer(port, name="restart_probe2") as srv:  # 同端口重启 = 端口确已释放
        body = httpx.get(f"{srv.base_url}/healthz", timeout=5.0).json()
        if body["instance"] != "restart_probe2":
            raise AssertionError(f"restart instance: {body}")
    return f"port {port} start->stop->restart ok (conftest-friendly lifecycle)"


def step_cli_subprocess(ctx: dict[str, Any]) -> str:
    port = _free_port()
    env = {**os.environ, "PYTHONUTF8": "1"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "gateway.mock_upstream", "--port", str(port), "--name", "cli_probe"],
        cwd=str(REPO_ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 20.0
        while True:
            try:
                if httpx.get(f"{base}/healthz", timeout=1.0).json().get("ok"):
                    break
            except Exception:  # noqa: BLE001 — 启动窗口内连接失败属预期
                if proc.poll() is not None:
                    raise AssertionError(f"cli process exited early: rc={proc.returncode}") from None
                if time.monotonic() > deadline:
                    raise AssertionError("cli instance not ready within 20s") from None
                time.sleep(0.2)
        resp = httpx.post(f"{base}/v1/chat/completions", json=_chat_payload("CLI 探针：王五 460022199003071236"),
                          timeout=10.0)
        if "王五 460022199003071236" not in resp.json()["choices"][0]["message"]["content"]:
            raise AssertionError("cli echo failed")
        records = httpx.get(f"{base}/admin/records", timeout=5.0).json()
        if records["instance"] != "cli_probe" or records["count"] != 1:
            raise AssertionError(f"cli records: {records['instance']}/{records['count']}")
        return f"subprocess instance on :{port} ready, echo + records ok"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


STEPS = (
    ("fixtures:start-two-instances", step_start_servers),
    ("models:list", step_models_list),
    ("echo:nonstream", step_echo_nonstream),
    ("ring:records-http", step_ring_http),
    ("ring:direct-parity", step_ring_direct),
    ("echo:stream", step_echo_stream),
    ("tools:nonstream", step_tools_nonstream),
    ("tools:stream", step_tools_stream),
    ("ring:text-bytes", step_admin_text),
    ("ring:reset", step_admin_reset),
    ("error:invalid-messages", step_error_shape),
    ("fixture:restart-cycle", step_fixture_restart),
    ("cli:subprocess", step_cli_subprocess),
)


def main() -> int:
    ctx: dict[str, Any] = {"client": httpx.Client()}
    for name, fn in STEPS:
        _record(name, lambda f=fn, c=ctx: f(c))
    ctx["client"].close()
    for srv in ("srv1", "srv2"):
        if srv in ctx:
            ctx[srv].stop()

    for _, line in RESULTS:
        print(line)
    passed = sum(1 for ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"T0 MOCK UPSTREAM: {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
