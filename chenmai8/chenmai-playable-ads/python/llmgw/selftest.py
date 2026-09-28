"""llmgw.selftest —— 全离线自测（标准库 http.server 起本地 mock 服务）。

mock 服务模拟 chat-completions 端点（POST /v1/chat/completions），
按请求内容路由；全程仅访问 127.0.0.1，零外网依赖。覆盖 6 项：

    ① 普通对话：system+user 消息回声、choices/usage 结构、Bearer 密钥校验、
      上游回显密钥时错误文本（str/summary/repr/traceback）已脱敏
    ② JSON 模式：response_format=json_object + json_schema 提示注入与解析
    ③ 图片输入：base64 → data URL，mock 端解码比对字节一致
    ④ 重试/退避/限流：500 重试成功；假时钟断言指数退避 0.8/1.6/…封顶 8s；
      429 读 Retry-After 且同密钥跨模型共享冷却；跨模型总尝试上限
    ⑤ 超时降级：主模型慢响应触发客户端超时 → 降级到备用模型成功
    （另含 0 号项：环境变量驱动 + 鉴权 + 端点拼接 + ConfigError）

运行（在 python/ 目录下）：
    .venv/Scripts/python.exe -m llmgw.selftest

全部 PASS 时打印 SELFTEST PASS 并退出码 0，否则退出码 1。
"""

import base64
import json
import os
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from llmgw import (Client, ConfigError, Gateway, LLMError, chat, endpoint_for,
                   json_of, redact, text_of)

HOST = "127.0.0.1"
API_KEY = "mock-key-0123456789abcdef"
PRIMARY_MODEL = "mock-primary"
SLOW_MODEL = "mock-slow-primary"
FALLBACK_MODEL = "mock-fallback"
SLOW_SECONDS = 3.0

IMAGE_BYTES = b"PF-MOCK-PNG-\x89PNG-bytes-0123"
IMAGE_B64 = base64.b64encode(IMAGE_BYTES).decode("ascii")


class FakeClock:
    """假时钟：sleep 只记账并推进 now，退避/冷却断言不真等。"""

    def __init__(self, now=100.0):
        self.now = float(now)
        self.sleeps: list[float] = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(float(seconds))
        self.now += float(seconds)


# ---------------------------------------------------------------- mock 服务

class MockState:
    """线程安全的请求计数与记录。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._counts = {}
        self.requests = []

    def bump(self, key):
        with self._lock:
            self._counts[key] = self._counts.get(key, 0) + 1
            return self._counts[key]

    def count(self, key):
        with self._lock:
            return self._counts.get(key, 0)

    def record(self, entry):
        with self._lock:
            self.requests.append(entry)


def _extract(messages):
    """从 mock 收到的消息里提取全部文本、图片数量与图片字节是否匹配。"""
    texts, n_images, images_ok = [], 0, True
    for m in messages:
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                ptype = part.get("type")
                if ptype == "text":
                    texts.append(str(part.get("text", "")))
                elif ptype == "image_url":
                    n_images += 1
                    url = (part.get("image_url") or {}).get("url", "")
                    ok = False
                    if url.startswith("data:image/"):
                        _, _, b64 = url.partition(",")
                        try:
                            ok = base64.b64decode(b64) == IMAGE_BYTES
                        except Exception:
                            ok = False
                    if not ok:
                        images_ok = False
    return texts, n_images, images_ok


class MockHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):  # 静音访问日志
        pass

    def _json(self, status, obj, extra_headers=None):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = None
        if not isinstance(body, dict):
            self._json(400, {"error": {"message": "请求体不是合法 JSON"}})
            return

        state = self.server.state
        model = str(body.get("model", ""))
        texts, n_images, images_ok = _extract(body.get("messages") or [])
        state.record({
            "path": self.path,
            "model": model,
            "auth": self.headers.get("Authorization", ""),
            "texts": texts,
            "n_images": n_images,
            "response_format": (body.get("response_format") or {}).get("type", ""),
        })

        if self.headers.get("Authorization", "") != "Bearer " + API_KEY:
            self._json(401, {"error": {"message": "密钥不匹配"}})
            return
        if self.path != "/v1/chat/completions":
            self._json(404, {"error": {"message": "未知路径 " + self.path}})
            return

        def reply(content):
            self._json(200, {
                "id": "chatcmpl-mock-001",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0,
                             "message": {"role": "assistant",
                                         "content": content},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 5,
                          "total_tokens": 8},
            })

        joined = "\n".join(texts)

        # 路由⑤：慢模型——拖过客户端超时，逼出降级
        if model == SLOW_MODEL:
            time.sleep(SLOW_SECONDS)
            reply("slow-finished-but-too-late")
            return
        # 路由④a：首次 500、再次成功——测重试
        if "RETRY-MARKER" in joined:
            n = state.bump("retry")
            if n == 1:
                self._json(500, {"error": {"message": "mock 临时故障（第 1 次）"}})
            else:
                reply("retry-ok-attempt-%d" % n)
            return
        # 路由④b：恒 500——假时钟测指数退避序列
        if "BACKOFF-MARKER" in joined:
            self._json(500, {"error": {"message": "mock 恒定故障（退避测量）"}})
            return
        # 路由④c：首个请求 429 + Retry-After: 1.5，其后 200——测限流冷却
        if "LIMIT-MARKER" in joined:
            if state.bump("limit") == 1:
                self._json(429, {"error": {"message": "mock 限流"}},
                           extra_headers={"Retry-After": "1.5"})
            else:
                reply("limit-ok-after-429")
            return
        # 路由④d：恒 429 + Retry-After: 0.01——测总尝试上限
        if "CAP-MARKER" in joined:
            self._json(429, {"error": {"message": "mock 持续限流"}},
                       extra_headers={"Retry-After": "0.01"})
            return
        # 路由①b：500 错误体回显 Authorization——测错误文本脱敏
        if "ECHO-KEY-MARKER" in joined:
            self._json(500, {"error": {"message": "上游回显: "
                                       + self.headers.get("Authorization", "")}})
            return
        # 路由③：图片字节校验
        if "IMAGE-MARKER" in joined:
            if n_images >= 1 and images_ok:
                reply("IMG-OK count=%d" % n_images)
            else:
                reply("IMG-BAD images=%d bytes_ok=%s" % (n_images, images_ok))
            return
        # 路由②：JSON 模式——并确认 schema 提示随请求到达
        if (body.get("response_format") or {}).get("type") == "json_object":
            schema_seen = any("JSON Schema" in t for t in texts)
            reply(json.dumps({"ok": True, "mock": True, "model": model,
                              "schema_seen": schema_seen},
                             ensure_ascii=False))
            return
        # 路由①：普通对话——回声
        reply("ECHO:" + joined)


class MockServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr):
        self.state = MockState()
        super().__init__(addr, MockHandler)

    def handle_error(self, request, client_address):
        # 测试⑤中客户端超时后主动断开，服务端写回会报错——属预期，静默
        pass


# ---------------------------------------------------------------- 测试项

_RESULTS = []


def _check(name, fn):
    try:
        fn()
    except Exception as exc:  # 自测框架需接住一切断言失败
        _RESULTS.append((name, False, str(exc)))
        print(f"[FAIL] {name}: {exc}")
    else:
        _RESULTS.append((name, True, ""))
        print(f"[PASS] {name}")


def test_env_and_auth(state):
    """环境变量驱动 + 鉴权 + 端点拼接规则。"""
    assert endpoint_for("http://h:8000/v1") == "http://h:8000/v1/chat/completions"
    assert endpoint_for("http://h:8000") == "http://h:8000/v1/chat/completions"
    assert endpoint_for("http://h:8000/") == "http://h:8000/v1/chat/completions"

    # 错误密钥 → mock 401 → LLMError 且 status=401
    bad = Client(api_key="wrong-key")
    try:
        bad.chat([{"role": "user", "content": "x"}])
    except LLMError as exc:
        assert exc.status == 401, f"期望 401，得到 {exc.status}"
        assert exc.attempts, "LLMError 应携带尝试记录"
    else:
        raise AssertionError("错误密钥应抛 LLMError")

    # 上游错误体回显 Bearer 密钥 → str/summary/repr/traceback 全部脱敏
    echo = Client(api_key=API_KEY, max_retries=0)
    try:
        echo.chat([{"role": "user", "content": "ECHO-KEY-MARKER 回显密钥"}])
    except LLMError as exc:
        tb_text = "".join(traceback.format_exception(exc))
        for where, blob in (("str", str(exc)), ("summary", exc.summary()),
                            ("repr", repr(exc)), ("traceback", tb_text)):
            assert API_KEY not in blob, f"密钥泄漏进 {where}：{blob[:160]!r}"
        assert "[REDACTED]" in exc.summary(), \
            f"summary 应含脱敏占位：{exc.summary()[:160]!r}"
    else:
        raise AssertionError("回显密钥的 500（重试耗尽）应最终抛 LLMError")

    # 裸密钥出现在错误体（无 Bearer 前缀）也必须抹掉
    text = redact("boom key=mock-key-0123456789abcdef over", API_KEY)
    assert API_KEY not in text and "[REDACTED]" in text, text

    # 缺环境变量 → ConfigError
    saved = {k: os.environ.get(k) for k in ("PF_LLM_BASE_URL", "PF_LLM_MODEL")}
    try:
        for k in saved:
            os.environ.pop(k, None)
        try:
            chat([{"role": "user", "content": "x"}])
        except ConfigError:
            pass
        else:
            raise AssertionError("缺少 PF_LLM_BASE_URL/PF_LLM_MODEL 应抛 ConfigError")
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_normal_chat(state):
    """① 普通对话。"""
    resp = chat([
        {"role": "system", "content": "你是回声服务"},
        {"role": "user", "content": "ping-ABC"},
    ])
    assert isinstance(resp, dict), "返回必须是 dict"
    assert resp.get("model") == PRIMARY_MODEL, \
        f"应使用 PF_LLM_MODEL 指定的主模型，得到 {resp.get('model')}"
    assert text_of(resp) == "ECHO:你是回声服务\nping-ABC"
    assert resp["usage"]["total_tokens"] == 8
    last = state.requests[-1]
    assert last["auth"] == "Bearer " + API_KEY, "Bearer 密钥应来自 PF_LLM_API_KEY"
    assert last["response_format"] == "", "普通对话不应带 response_format"


def test_json_mode(state):
    """② JSON 模式（response_format=json_object + schema 提示）。"""
    schema = {"type": "object", "required": ["ok"],
              "properties": {"ok": {"type": "boolean"}}}
    resp = chat([{"role": "user", "content": "给一个 JSON"}], json_schema=schema)
    data = json_of(resp)
    assert isinstance(data, dict) and data.get("ok") is True, f"JSON 解析结果异常：{data}"
    assert data.get("schema_seen") is True, "json_schema 提示未随请求到达服务端"
    last = state.requests[-1]
    assert last["response_format"] == "json_object", "应设置 response_format=json_object"


def test_image_input(state):
    """③ 图片 base64 输入（裸 base64 与 (mime, base64) 元组两种形式）。"""
    resp = chat(
        [{"role": "user", "content": "IMAGE-MARKER 这张图里有什么"}],
        images=[IMAGE_B64],
    )
    text = text_of(resp)
    assert text.startswith("IMG-OK"), f"图片字节校验失败：{text}"
    assert "count=1" in text

    resp2 = chat(
        [{"role": "user", "content": "IMAGE-MARKER 元组形式"}],
        images=[("image/png", IMAGE_B64)],
    )
    assert text_of(resp2).startswith("IMG-OK"), text_of(resp2)

    # 坏 base64 应在客户端被拦截
    try:
        chat([{"role": "user", "content": "x"}], images=["%%%not-base64%%%"])
    except ValueError:
        pass
    else:
        raise AssertionError("非法 base64 应抛 ValueError")


def test_retry_backoff_429(state):
    """④ 重试/退避/限流：500 重试成功；假时钟锁退避序列；429 共享冷却；总尝试上限。"""
    # a) 首次 500 → 自动重试成功（真时钟，退避钉 0.05s 不拖慢自测）
    before = state.count("retry")
    resp = chat([{"role": "user", "content": "RETRY-MARKER 试一下"}],
                max_retries=3, backoff=0.05)
    assert text_of(resp) == "retry-ok-attempt-2", text_of(resp)
    assert state.count("retry") == before + 2, \
        "应恰好两次请求（第 1 次 500 + 第 2 次成功）"

    # b) 假时钟锁指数退避序列：0.8 → 1.6 → 3.2 → 6.4 → 封顶 8.0
    fc = FakeClock()
    gw = Client(api_key=API_KEY, model=PRIMARY_MODEL, fallback_models=[],
                max_retries=5, backoff=0.8, clock=fc.clock, sleep=fc.sleep)
    try:
        gw.chat([{"role": "user", "content": "BACKOFF-MARKER"}])
    except LLMError:
        pass
    else:
        raise AssertionError("恒 500 应最终抛 LLMError")
    assert fc.sleeps == [0.8, 1.6, 3.2, 6.4, 8.0], \
        f"退避序列应 [0.8, 1.6, 3.2, 6.4, 8.0]（封顶 8s），得到 {fc.sleeps}"

    # c) 429 + Retry-After：同密钥跨模型共享冷却（备用模型请求前先等冷却）
    fc2 = FakeClock()
    gw2 = Client(api_key=API_KEY, model=PRIMARY_MODEL,
                 fallback_models=[FALLBACK_MODEL], max_retries=0,
                 clock=fc2.clock, sleep=fc2.sleep)
    resp = gw2.chat([{"role": "user", "content": "LIMIT-MARKER 限流"}])
    assert resp.get("model") == FALLBACK_MODEL, \
        f"429 后应降级到备用模型，得到 {resp.get('model')}"
    assert text_of(resp) == "limit-ok-after-429", text_of(resp)
    assert any(abs(s - 1.5) < 1e-9 for s in fc2.sleeps), \
        f"主→备模型切换应先等 Retry-After=1.5s 共享冷却，sleeps={fc2.sleeps}"
    assert fc2.sleeps.index(1.5) == 0, \
        f"冷却应发生在降级请求之前，sleeps={fc2.sleeps}"

    # d) 总尝试上限：恒 429 时跨模型累计达上限立即中止，不再无限连打
    fc3 = FakeClock()
    gw3 = Client(api_key=API_KEY, model=PRIMARY_MODEL,
                 fallback_models=[FALLBACK_MODEL, "mock-x", "mock-y"],
                 max_retries=2, max_total_attempts=4,
                 clock=fc3.clock, sleep=fc3.sleep)
    try:
        gw3.chat([{"role": "user", "content": "CAP-MARKER 上限"}])
    except LLMError as exc:
        assert len(exc.attempts) == 4, \
            f"达总尝试上限应恰好 4 次尝试，实际 {len(exc.attempts)}"
        assert "上限" in str(exc), f"错误信息应说明触发了上限：{exc}"
    else:
        raise AssertionError("恒 429 超总尝试上限应抛 LLMError")


def test_timeout_fallback(state):
    """⑤ 慢模型超时 → 降级到 PF_LLM_FALLBACK_MODELS 中的备用模型。"""
    slow_before = sum(1 for r in state.requests if r["model"] == SLOW_MODEL)
    gw = Gateway(model=SLOW_MODEL, fallback_models=[FALLBACK_MODEL],
                 timeout=0.6, max_retries=0, backoff=0.05)
    t0 = time.monotonic()
    resp = gw.chat([{"role": "user", "content": "SLOW-MARKER 慢路由"}])
    elapsed = time.monotonic() - t0
    assert resp.get("model") == FALLBACK_MODEL, \
        f"应由备用模型服务，得到 {resp.get('model')}"
    assert text_of(resp) == "ECHO:SLOW-MARKER 慢路由"
    assert elapsed < SLOW_SECONDS, \
        f"降级应尽快返回（耗时 {elapsed:.2f}s ≥ 慢模型 {SLOW_SECONDS}s）"
    slow_after = sum(1 for r in state.requests if r["model"] == SLOW_MODEL)
    assert slow_after == slow_before + 1, "慢模型应恰好被尝试 1 次即降级"


# ---------------------------------------------------------------- 主流程

def _force_utf8_stdio() -> None:
    """Windows 管道/控制台默认非 UTF-8 代码页，固定输出编码避免中文乱码。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def main():
    _force_utf8_stdio()
    server = MockServer((HOST, 0))
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever,
                              kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()

    # 全部配置由环境变量注入（客户端代码零硬编码）
    os.environ["PF_LLM_BASE_URL"] = f"http://{HOST}:{port}/v1"
    os.environ["PF_LLM_API_KEY"] = API_KEY
    os.environ["PF_LLM_MODEL"] = PRIMARY_MODEL
    os.environ["PF_LLM_FALLBACK_MODELS"] = FALLBACK_MODEL
    os.environ["PF_LLM_TIMEOUT"] = "20"
    os.environ["PF_LLM_MAX_RETRIES"] = "2"
    os.environ["PF_LLM_BACKOFF"] = "0.05"

    print(f"mock 服务已启动：http://{HOST}:{port}/v1/chat/completions（仅本机，无外网）")
    try:
        state = server.state
        _check("0 环境变量驱动/鉴权/端点拼接/错误脱敏", lambda: test_env_and_auth(state))
        _check("1 普通对话", lambda: test_normal_chat(state))
        _check("2 JSON 模式", lambda: test_json_mode(state))
        _check("3 图片 base64 输入", lambda: test_image_input(state))
        _check("4 重试/退避/限流（假时钟）", lambda: test_retry_backoff_429(state))
        _check("5 超时→降级模型", lambda: test_timeout_fallback(state))
    finally:
        server.shutdown()
        server.server_close()

    total = len(_RESULTS)
    failed = [r for r in _RESULTS if not r[1]]
    print(f"\n共 {total} 项，通过 {total - len(failed)} 项")
    if failed:
        for name, _, err in failed:
            print(f"  FAIL {name}: {err}")
        return 1
    print("SELFTEST PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
