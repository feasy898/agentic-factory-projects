"""llm_openai —— GPU 机本地大模型 OpenAI 兼容服务（FastAPI，:9004；政务网关批次 6 上游）。

角色：本仓库网关（gateway，:9000）敏感度路由的「政务云 / 互联网」双上游，
以 OpenAI chat 协议子集对外服务；部署形态沿用本机已验证的 transformers fp16 直跑
模式（Volta sm_70 无 bf16/无 FA2 → fp16 + sdpa），单卡显存预算 ≤20G。

接口口径（OpenAI chat 协议子集，字段与 gateway/provider.py 对齐）：
  GET  /health
      → {"service","loaded","device","cuda_available","model_dir","serve_model",
         "versions","error","vram","load_s","warmup_s"}
  POST /v1/chat/completions
      请求：OpenAI 形状（messages 必填；stream/temperature/top_p/max_tokens 可选；
            tools 透传给对话模板但不承诺结构化 tool_calls 输出；n>1 不支持；
            多余字段宽容忽略）
      非流式响应：{"id","object":"chat.completion","created","model",
            "choices":[{"index","message":{"role","content"},"finish_reason"}],
            "usage":{"prompt_tokens","completion_tokens","total_tokens"},
            "timing_ms"}（timing_ms 为本仓扩展字段）
      流式响应：SSE，`data: {chat.completion.chunk}` 序列 + 终止 `data: [DONE]`；
            首 delta 携带 role，内容增量携带 content，末帧 finish_reason=stop，
            末帧附 usage/timing_ms 扩展字段。
  GET  /admin/records[?limit=N] / GET /admin/text / POST /admin/reset
      请求环形缓冲（e2e U8 断言「上游收到过什么」的唯一事实来源，与网关仓
      mock 上游同口径）：内存记录最近 N 条请求的 messages 全文（逐条 JSON 序列
      化中文原样，供 bytes 级脱敏断言）。凭据红线：Authorization 只记是否在位
      及其 SHA256 前 8 位指纹（``auth_key_sha8``，不可逆），**不记原值**——
      e2e 据此断言 internet / govcloud 两 profile 携带了不同的 key 头。

推理约束（与 gpu-services 既有服务同纪律）：fp16 + sdpa；无 bf16；不依赖重型
推理运行时；生成串行化（单卡单进程份额，threading.Lock）。
思考型模板默认关闭思考段（LLM_THINKING=0），输出侧再兜底过滤 `<think>` 段，
保证上游拿到纯答案文本（流式用增量状态机，跨 chunk 切分的标签也能正确抑制）。

部署：权重目录由 gpu/setup_llm_service.sh 预置（模型真实名/来源只存在于部署
环境与镜像源，公开仓库零上游名，审查 §E）→ gpu-services/llm_openai/run_gpu.sh
start（127.0.0.1:9004 常驻）→ 本机 ops/tunnel_gpu.sh（默认 9004）隧道访问；
GPU 机侧常驻保活 = gpu/llm_keepalive.sh。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import sys
import threading
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

try:  # 仅供 FastAPI 注解解析（Request 对象注入 → Authorization 指纹）；服务运行必然有 fastapi
    from fastapi import Request  # noqa: F401
except ImportError:  # pragma: no cover
    Request = Any  # type: ignore[assignment, misc]

MODEL_DIR = os.environ.get("LLM_MODEL_DIR", "/data/xdng/models/llm-chat-8b")
DEVICE = os.environ.get("LLM_DEVICE", "cuda:0")  # 配合 CUDA_VISIBLE_DEVICES 选物理卡
SERVE_MODEL = os.environ.get("LLM_SERVE_MODEL", "local-chat-8b")  # 对外模型名（中性）
MAX_CTX = int(os.environ.get("LLM_MAX_CTX", "4096"))  # prompt+生成 的总 token 上限（显存护栏）
MAX_NEW_CAP = int(os.environ.get("LLM_MAX_NEW_CAP", "1024"))
THINKING = os.environ.get("LLM_THINKING", "0") == "1"  # 默认关思考段（纯答案文本）
DEFAULT_TEMP = float(os.environ.get("LLM_TEMP_DEFAULT", "0.7"))
DEFAULT_TOP_P = float(os.environ.get("LLM_TOP_P_DEFAULT", "0.8"))
STREAM_TIMEOUT_S = float(os.environ.get("LLM_STREAM_TIMEOUT_S", "600"))

_THINK_OPEN, _THINK_CLOSE = "<think>", "</think>"

status: dict[str, Any] = {
    "service": "llm_openai",
    "version": "1.0",
    "device": DEVICE,
    "model_dir": MODEL_DIR,
    "serve_model": SERVE_MODEL,
    "loaded": False,
    "error": None,
    "load_s": None,
    "warmup_s": None,
}
_M: dict[str, Any] = {}  # tokenizer/model 常驻
_INFER_LOCK = threading.Lock()


class RingBuffer:
    """线程安全的请求环形缓冲（e2e 断言「真实上游收到过什么」的唯一事实来源）。

    与网关仓 mock 上游的 RingBuffer 同口径：``texts()`` 逐条产出 messages 数组
    的 JSON 序列化全文（``ensure_ascii=False`` 中文原样，bytes 级脱敏扫描才会
    真实命中）。本服务为单进程自足部署（GPU 机平铺单文件，无仓库内依赖），
    故此处内置实现而不跨包导入。
    """

    def __init__(self, maxlen: int = 200) -> None:
        self._lock = threading.Lock()
        self._items: deque[dict[str, Any]] = deque(maxlen=max(1, maxlen))
        self._seq = 0

    def add(self, record: dict[str, Any]) -> int:
        with self._lock:
            self._seq += 1
            item = {"seq": self._seq, **record}
            self._items.append(item)
            return self._seq

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._items]

    def texts(self) -> list[str]:
        with self._lock:
            items = [dict(item) for item in self._items]
        return [json.dumps(it.get("messages", []), ensure_ascii=False, sort_keys=True)
                for it in items]

    def reset(self) -> int:
        with self._lock:
            cleared = len(self._items)
            self._items.clear()
            return cleared

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


_RING = RingBuffer()  # 本服务唯一 ring：internet / govcloud 两 profile 共用同一进程


def _auth_fingerprint(request: Any) -> tuple[bool, str]:
    """Authorization 指纹：(是否在位, bearer 值 SHA256 前 8 位)；原值永不落缓冲。"""
    auth = ""
    try:
        headers = getattr(request, "headers", None)
        auth = headers.get("authorization", "") if headers is not None else ""
    except Exception:  # noqa: BLE001 —— 指纹面取不到不挡主链路
        auth = ""
    if not auth:
        return False, ""
    parts = auth.split(None, 1)
    bearer = parts[1].strip() if len(parts) > 1 else auth.strip()
    return True, hashlib.sha256(bearer.encode("utf-8")).hexdigest()[:8]


def _load_model() -> None:
    """装载权重（fp16 + sdpa；Volta 有 fp16 无 bf16）。失败如实暴露在 /health，不静默。"""
    if not os.path.isdir(MODEL_DIR):
        status["error"] = f"权重目录不存在: {MODEL_DIR}（先跑 gpu/setup_llm_service.sh）"
        return
    t0 = time.perf_counter()
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        tok = AutoTokenizer.from_pretrained(MODEL_DIR, trust_remote_code=False)
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_DIR,
            torch_dtype=torch.float16,
            attn_implementation="sdpa",
            trust_remote_code=False,
        )
        model.to(DEVICE).eval()
        _M["tok"] = tok
        _M["model"] = model
        status["versions"] = {
            "transformers": __import__("transformers").__version__,
            "torch": torch.__version__,
        }
        status["load_s"] = round(time.perf_counter() - t0, 3)
        # 暖机：短生成触发内核调度/显存池初始化，首请求不再承担冷启动
        t1 = time.perf_counter()
        ids = tok("你好", return_tensors="pt").to(DEVICE)
        with torch.inference_mode():
            model.generate(**ids, do_sample=False, max_new_tokens=8,
                           pad_token_id=tok.pad_token_id or tok.eos_token_id)
        status["warmup_s"] = round(time.perf_counter() - t1, 3)
        status["loaded"] = True
    except Exception as exc:  # noqa: BLE001 —— 装载期任何异常都如实上报
        status["error"] = f"{type(exc).__name__}: {exc}"


@asynccontextmanager
async def _lifespan(_app: Any):
    _load_model()
    yield


def _build_app() -> Any:
    from fastapi import FastAPI

    return FastAPI(title="llm_openai", version=status["version"], lifespan=_lifespan)


app = _build_app()


def _vram_info() -> dict[str, Any]:
    try:
        import torch

        if not torch.cuda.is_available():
            return {}
        free_b, total_b = torch.cuda.mem_get_info(DEVICE)
        return {
            "free_mb": round(free_b / 1024 / 1024),
            "total_mb": round(total_b / 1024 / 1024),
            "allocated_mb": round(torch.cuda.memory_allocated(DEVICE) / 1024 / 1024),
            "peak_mb": round(torch.cuda.max_memory_allocated(DEVICE) / 1024 / 1024),
        }
    except Exception:  # noqa: BLE001 —— 显存查询失败不影响主流程
        return {}


@app.get("/health")
def health() -> dict[str, Any]:
    import torch

    return {
        **status,
        "cuda_available": torch.cuda.is_available(),
        "vram": _vram_info(),
    }


def _messages_text(content: str | list[Any] | None) -> str:
    """content 归一：字符串原样；OpenAI 多段数组取 text 段拼接；None → 空串。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for seg in content:
        if isinstance(seg, dict) and isinstance(seg.get("text"), str):
            parts.append(seg["text"])
        elif isinstance(seg, str):
            parts.append(seg)
    return "".join(parts)


class ChatRequest(BaseModel):
    """宽容接收 OpenAI 请求形状（多余字段忽略），供文档化与校验入口使用。"""

    model_config = {"extra": "ignore"}
    model: str = ""
    messages: list[dict[str, Any]]
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stream: bool = False


def _extract_request(payload: dict[str, Any]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """从原始 JSON 抽 (messages, 生成参数)；协议宽容（多余字段忽略）。"""
    msgs_raw = payload.get("messages")
    if not isinstance(msgs_raw, list) or not msgs_raw:
        raise ValueError("messages 必须为非空数组")
    messages: list[dict[str, str]] = []
    for m in msgs_raw:
        if not isinstance(m, dict) or "role" not in m:
            raise ValueError("message 形状非法（需 {role, content}）")
        messages.append({"role": str(m["role"]), "content": _messages_text(m.get("content"))})
    n = int(payload.get("n") or 1)
    if n > 1:
        raise ValueError("n>1 不支持（本地单卡服务）")
    opts: dict[str, Any] = {
        "temperature": payload.get("temperature"),
        "top_p": payload.get("top_p"),
        "max_tokens": payload.get("max_tokens"),
        "tools": payload.get("tools"),
    }
    return messages, opts


def _apply_template(messages: list[dict[str, str]], tools: Any) -> str:
    tok = _M["tok"]
    kwargs: dict[str, Any] = {
        "add_generation_prompt": True,
        "tokenize": False,
        "enable_thinking": THINKING,  # 模板未定义该变量时被忽略（无害）
    }
    if tools:
        kwargs["tools"] = tools
    return tok.apply_chat_template(messages, **kwargs)


def _prepare_inputs(prompt: str, max_new: int) -> tuple[dict[str, Any], int]:
    """编码 + 上下文护栏：prompt+max_new 超上限时对 prompt 左截断（保尾部）。"""
    import torch

    tok = _M["tok"]
    ids = tok(prompt, return_tensors="pt", add_special_tokens=False)
    n_total = ids["input_ids"].shape[1]
    budget = max(64, MAX_CTX - max_new)
    if n_total > budget:
        ids = {k: v[:, n_total - budget:] for k, v in ids.items()}
    inputs = {k: v.to(DEVICE) for k, v in ids.items()}
    if "attention_mask" not in inputs:
        inputs["attention_mask"] = torch.ones_like(inputs["input_ids"])
    return inputs, int(inputs["input_ids"].shape[1])


def _gen_kwargs(max_new: int, temperature: float | None, top_p: float | None,
                streamer: Any = None) -> dict[str, Any]:
    tok = _M["tok"]
    temp = DEFAULT_TEMP if temperature is None else float(temperature)
    topp = DEFAULT_TOP_P if top_p is None else float(top_p)
    kwargs: dict[str, Any] = {
        "max_new_tokens": max_new,
        "pad_token_id": tok.pad_token_id or tok.eos_token_id,
    }
    if streamer is not None:
        kwargs["streamer"] = streamer
    if temp and temp > 0:
        kwargs.update(do_sample=True, temperature=temp, top_p=max(0.05, min(topp, 1.0)))
    else:
        kwargs.update(do_sample=False)
    return kwargs


class _ThinkFilter:
    """流式 `<think>` 段抑制状态机（跨 chunk 切分的标签也能正确识别/扣留）。"""

    def __init__(self) -> None:
        self.buf = ""
        self.suppress = False

    @staticmethod
    def _partial_len(s: str, tag: str) -> int:
        for k in range(min(len(s), len(tag) - 1), 0, -1):
            if s.endswith(tag[:k]):
                return k
        return 0

    def feed(self, piece: str) -> str:
        self.buf += piece
        out: list[str] = []
        while self.buf:
            if self.suppress:
                idx = self.buf.find(_THINK_CLOSE)
                if idx < 0:
                    keep = self._partial_len(self.buf, _THINK_CLOSE)
                    self.buf = self.buf[len(self.buf) - keep:]
                    break
                self.buf = self.buf[idx + len(_THINK_CLOSE):]
                self.suppress = False
                continue
            idx = self.buf.find(_THINK_OPEN)
            if idx >= 0:
                out.append(self.buf[:idx])
                self.buf = self.buf[idx + len(_THINK_OPEN):]
                self.suppress = True
                continue
            keep = self._partial_len(self.buf, _THINK_OPEN)
            out.append(self.buf[: len(self.buf) - keep])
            self.buf = self.buf[len(self.buf) - keep:]
            break
        return "".join(out)

    def flush(self) -> str:
        """收尾：未闭合的思考段丢弃；普通残余原样放出。"""
        if self.suppress:
            self.buf = ""
            return ""
        out, self.buf = self.buf, ""
        return out


_THINK_RE = re.compile(r"<think>.*?</think>", re.S)
_THINK_OPEN_RE = re.compile(r"<think>.*\Z", re.S)


def _clean_text(text: str) -> str:
    """非流式兜底：剥思考段（含未闭合形态）后去首尾空白。"""
    text = _THINK_RE.sub("", text)
    text = _THINK_OPEN_RE.sub("", text)
    return text.strip()


@app.post("/v1/chat/completions")
def chat_completions(payload: dict[str, Any], request: Request) -> Any:
    """OpenAI 兼容入口：按 payload.stream 分流（流式返回 StreamingResponse）。"""
    from fastapi import HTTPException
    from fastapi.responses import JSONResponse, StreamingResponse

    if not status["loaded"]:
        raise HTTPException(status_code=503, detail=f"模型未装载: {status['error']}")
    try:
        messages, opts = _extract_request(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    want_stream = bool(payload.get("stream"))
    t0 = time.perf_counter()
    try:
        prompt = _apply_template(messages, opts.get("tools")).strip()
    except Exception as exc:  # noqa: BLE001 —— 模板失败按 400 语义回
        raise HTTPException(status_code=400, detail=f"对话模板失败: {exc}") from exc

    max_new = min(int(opts.get("max_tokens") or 512), MAX_NEW_CAP)
    auth_present, auth_sha8 = _auth_fingerprint(request)
    peer = ""
    try:  # request.client 在某些 ASGI 形态下可为 None
        peer = f"{request.client.host}:{request.client.port}" if request.client else ""
    except Exception:  # noqa: BLE001 —— 指纹面取不到不挡主链路
        peer = ""
    _RING.add({
        "ts": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "model": str(payload.get("model") or SERVE_MODEL),
        "stream": want_stream,
        "max_tokens": max_new,
        "auth_header_present": auth_present,
        "auth_key_sha8": auth_sha8,
        "messages": messages,
        "peer": peer,
    })
    if want_stream:
        return StreamingResponse(
            _sse_stream(prompt, max_new, opts, t0),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    # —— 非流式：串行锁内一次性生成 ——
    import torch

    with _INFER_LOCK:
        inputs, n_prompt = _prepare_inputs(prompt, max_new)
        kwargs = _gen_kwargs(max_new, opts["temperature"], opts["top_p"])
        with torch.inference_mode():
            out = _M["model"].generate(**inputs, **kwargs)
    new_tokens = out[0][n_prompt:]
    content = _clean_text(_M["tok"].decode(new_tokens, skip_special_tokens=True))
    n_comp = int(new_tokens.shape[0])
    body = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": SERVE_MODEL,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop" if n_comp < max_new else "length",
        }],
        "usage": {
            "prompt_tokens": n_prompt,
            "completion_tokens": n_comp,
            "total_tokens": n_prompt + n_comp,
        },
        "timing_ms": int((time.perf_counter() - t0) * 1000),
    }
    return JSONResponse(status_code=200, content=body)


@app.get("/admin/records")
def admin_records(limit: int = 0) -> dict[str, Any]:
    """ring 快照（e2e U8 断言面）：count + records（messages 全文 + key 指纹，无原值）。"""
    records = _RING.snapshot()
    if limit > 0:
        records = records[-limit:]
    return {"service": "llm_openai", "count": len(records), "records": records}


@app.get("/admin/text")
def admin_text() -> Any:
    """收到的全文（逐条 messages JSON 序列化、中文原样）——bytes 级脱敏断言对象。"""
    from fastapi.responses import Response

    return Response("\n".join(_RING.texts()), media_type="text/plain; charset=utf-8")


@app.post("/admin/reset")
def admin_reset() -> dict[str, Any]:
    """清空 ring buffer（e2e 用例开跑前复位）。"""
    return {"service": "llm_openai", "cleared": _RING.reset()}


def _sse_stream(prompt: str, max_new: int, opts: dict[str, Any], t0: float) -> Any:
    """同步生成器（Starlette 经线程池迭代，不阻塞事件循环）：SSE chunk 序列 + [DONE]。"""
    from transformers import TextIteratorStreamer

    chat_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    def _frame(delta: dict[str, Any], finish: str | None, extra: dict | None = None) -> str:
        chunk: dict[str, Any] = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": SERVE_MODEL,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        if extra:
            chunk.update(extra)
        return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    yield _frame({"role": "assistant"}, None)
    streamer = TextIteratorStreamer(_M["tok"], skip_prompt=True, skip_special_tokens=True,
                                    timeout=STREAM_TIMEOUT_S)
    n_prompt_box: list[int] = []
    err: list[str] = []

    def _worker() -> None:
        try:
            with _INFER_LOCK:
                inputs, n_prompt = _prepare_inputs(prompt, max_new)
                n_prompt_box.append(n_prompt)
                kwargs = _gen_kwargs(max_new, opts["temperature"], opts["top_p"],
                                     streamer=streamer)
                import torch

                with torch.inference_mode():
                    _M["model"].generate(**inputs, **kwargs)
        except Exception as exc:  # noqa: BLE001 —— 生成线程异常经 err 通道回传
            err.append(f"{type(exc).__name__}: {exc}")
        finally:
            streamer.end()

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    flt = _ThinkFilter()
    n_comp = 0
    first_emitted = False
    try:
        while True:
            try:
                piece = next(streamer)
            except StopIteration:
                break
            except queue.Empty:  # 流超时（防御，正常路径不会走到）
                err.append(f"stream timeout {STREAM_TIMEOUT_S}s")
                break
            n_comp += 1  # 以增量 piece 为粒度近似计数（与真实 token 数可有出入，如实口径）
            text = flt.feed(piece)
            if text:
                if not first_emitted:
                    text = text.lstrip()  # 首增量去前导空白（生成提示后常带换行）
                    first_emitted = True
                if text:
                    yield _frame({"content": text}, None)
        tail = flt.flush()
        if tail:
            yield _frame({"content": tail}, None)
        thread.join(timeout=STREAM_TIMEOUT_S)
    finally:
        if err:
            yield _frame({}, "stop", {"error": {"message": err[0], "type": "server_error"}})
        else:
            n_prompt = n_prompt_box[0] if n_prompt_box else 0
            yield _frame({}, "stop", {
                "usage": {
                    "prompt_tokens": n_prompt,
                    "completion_tokens": n_comp,
                    "total_tokens": n_prompt + n_comp,
                },
                "timing_ms": int((time.perf_counter() - t0) * 1000),
            })
        yield "data: [DONE]\n\n"


def main() -> None:
    ap = argparse.ArgumentParser(prog="service.py", description="llm_openai 服务（:9004）")
    ap.add_argument("--port", type=int, default=int(os.environ.get("LLM_PORT", "9004")))
    ap.add_argument("--host", default="127.0.0.1")  # 只监听回环；外部一律走 ssh 隧道
    args = ap.parse_args()
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    sys.exit(main())
