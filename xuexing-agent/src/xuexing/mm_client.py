"""mm_client —— 多模态客户端（chat / vision / tts / asr 四能力）。

契约来源 specs/drafts/mm_client.spec.md（BACKLOG P3「mm_client 多模态客户端」）。
API 端点/模型/voice 以 docs/multimodal-api.md（2026-09-29 阶跃 API 实测矩阵）为事实来源。

封装阶跃（stepfun）多模态 API：端点白名单（https + api.stepfun.com + 解析 IP
阻断私网/环回/链路本地/保留/组播/未指定）、key 只从环境变量读
（XX_LLM_API_KEY → STEPFUN_API_KEY）、单一错误家族 LLMError 且绝不回显 key。
网络一律经可注入的 Transport 协议单口发出（契约测试用 MockTransport 全 mock，
零网络）；HttpTransport 是唯一网络豁免（仅参考，不在契约覆盖内，stdlib urllib +
前置 DNS 私网阻断）。冒烟真调仅在 XX_MM_SMOKE=1 且环境含 key 时发生。

内核确定性：请求构造全部是纯函数（同输入同字节）；multipart 用固定边界常量
（无隐藏随机）；不读时钟（timeout 是显式值）；纯 stdlib、零 xuexing 依赖。
"""
from __future__ import annotations

import base64
import ipaddress
import json
import math
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Mapping, Optional, Protocol, Sequence

__all__ = [
    "LLMError",
    "BASE_URL",
    "ALLOWED_HOST",
    "ENDPOINTS",
    "MODEL_CHAT",
    "MODEL_TTS",
    "MODEL_ASR",
    "TTS_VOICE",
    "TTS_FORMAT",
    "KEY_ENV_VARS",
    "DEFAULT_TIMEOUT",
    "BOUNDARY",
    "JSON_CONTENT_TYPE",
    "MULTIPART_CONTENT_TYPE",
    "IMAGE_MIME",
    "api_key",
    "check_url",
    "data_url",
    "vision_content",
    "multipart_body",
    "Transport",
    "MockTransport",
    "HttpTransport",
    "MMClient",
]

# ---------- 冻结常量（docs/multimodal-api.md 实测矩阵） ----------

BASE_URL = "https://api.stepfun.com"
ALLOWED_HOST = "api.stepfun.com"
ENDPOINTS = {
    "chat": BASE_URL + "/step_plan/v1/chat/completions",
    "tts": BASE_URL + "/step_plan/v1/audio/speech",
    # 注意：ASR 不在 step_plan 路径下（docs/multimodal-api.md 实测）
    "asr": BASE_URL + "/v1/audio/transcriptions",
}
MODEL_CHAT = "step-5-preview"        # 文本/视觉主力（vision 实测唯一可用）
MODEL_TTS = "stepaudio-2.5-tts"
MODEL_ASR = "stepaudio-2.5-asr"
TTS_VOICE = "linjiajiejie"
TTS_FORMAT = "mp3"
KEY_ENV_VARS = ("XX_LLM_API_KEY", "STEPFUN_API_KEY")  # 优先序
DEFAULT_TIMEOUT = 60.0
BOUNDARY = "xuexing-mm-boundary-v1"  # 固定边界：无隐藏随机，同输入同字节
JSON_CONTENT_TYPE = "application/json"
MULTIPART_CONTENT_TYPE = "multipart/form-data; boundary=" + BOUNDARY
IMAGE_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}

_CAP_BY_URL = {url: cap for cap, url in ENDPOINTS.items()}


class LLMError(RuntimeError):
    """多模态/LLM 相关失败：key 缺失、白名单违规、参数非法、HTTP 失败、响应形状错。

    安全条款：任何错误消息不得包含 api key 值。
    """


def _non_blank_str(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LLMError(f"{name} must be a non-blank str")
    return value


# ---------- key 纪律 ----------

def api_key(env: Optional[Mapping[str, str]] = None) -> str:
    """按 KEY_ENV_VARS 顺序取第一个 strip 后非空的值（返回 strip 后值）。

    env=None 读 os.environ；非 str 值视为缺失跳过；全缺 -> LLMError（不回显值）。
    """
    source: Mapping[str, str] = os.environ if env is None else env
    for name in KEY_ENV_VARS:
        value = source.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise LLMError("api key not set (looked in: " + ", ".join(KEY_ENV_VARS) + ")")


# ---------- 端点白名单守卫 ----------

def _system_resolve(host: str) -> list[str]:
    """系统 DNS 解析（仅参考路径：真实网络；契约测试恒注入解析桩，不经此处）。"""
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    out: list[str] = []
    for info in infos:
        ip = info[4][0]
        if ip not in out:  # 去重保序
            out.append(ip)
    return out


def check_url(url: str, *, resolve: Optional[Callable[[str], list[str]]] = None) -> None:
    """端点白名单守卫（六重门）：任一不过 raise LLMError，全过静默返回 None。

    1 str 可解析；2 scheme=https；3 无 userinfo；4 host 白名单（大小写不敏感）；
    5 显式端口必须 443；6 解析 IP 每一个都非私网/环回/链路本地/保留/组播/未指定。
    """
    if not isinstance(url, str) or not url:
        raise LLMError(f"url not allowed: {url!r}")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise LLMError(f"url scheme not allowed: {parsed.scheme!r}")
    if parsed.username is not None or parsed.password is not None:
        raise LLMError("url userinfo not allowed")
    host = parsed.hostname
    if host != ALLOWED_HOST:
        raise LLMError(f"url host not allowed: {host!r}")
    try:
        port = parsed.port
    except ValueError as e:
        raise LLMError(f"url port not allowed: {url!r}") from e
    if port is not None and port != 443:
        raise LLMError(f"url port not allowed: {port}")
    resolver = _system_resolve if resolve is None else resolve
    try:
        ips = resolver(host)
    except LLMError:
        raise
    except Exception as e:  # 注入桩/系统解析的任意失败统一归族
        raise LLMError(f"resolve failed for {host}: {e}") from e
    if not ips:
        raise LLMError(f"resolve returned no address for {host}")
    for raw in ips:
        if not isinstance(raw, str):
            raise LLMError(f"resolve returned non-string address: {raw!r}")
        try:
            ip = ipaddress.ip_address(raw.strip())
        except ValueError as e:
            raise LLMError(f"resolve returned invalid address: {raw!r}") from e
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise LLMError(f"resolved address not allowed: {raw}")


# ---------- 请求构造（纯函数） ----------

def data_url(image: bytes, image_format: str) -> str:
    """非空 bytes -> "data:{mime};base64,{b64}"；image_format 须在 IMAGE_MIME。"""
    if not isinstance(image, bytes) or not image:
        raise LLMError("image must be non-empty bytes")
    mime = IMAGE_MIME.get(image_format) if isinstance(image_format, str) else None
    if mime is None:
        raise LLMError(f"image format not allowed: {image_format!r}")
    return f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"


def vision_content(prompt: str, images: Sequence, image_format: str = "png") -> list[dict]:
    """多段 content：恰一个 text 段在最前 + 每图一个 image_url 段（按入参序）。"""
    _non_blank_str(prompt, "prompt")
    if not isinstance(images, (list, tuple)) or not images:
        raise LLMError("images must be a non-empty list/tuple")
    urls: list[str] = []
    for img in images:
        if isinstance(img, bytes):
            urls.append(data_url(img, image_format))
        elif isinstance(img, str) and img.startswith("data:image/"):
            urls.append(img)  # data URL 原样透传
        else:
            raise LLMError(f"image must be non-empty bytes or a data:image/ URL: {img!r}")
    content: list[dict] = [{"type": "text", "text": prompt}]
    content.extend({"type": "image_url", "image_url": {"url": u}} for u in urls)
    return content


def multipart_body(fields: Mapping[str, str], file_field: str, filename: str,
                   file_bytes: bytes, *, boundary: str = BOUNDARY) -> tuple[bytes, str]:
    """确定性 multipart 构造：fields 普通字段（无 Content-Type）+ 恰一个文件字段。

    返回 (请求体 bytes, content_type)；boundary 与任何字段名/值/filename/file_bytes
    碰撞 -> LLMError（防结构碰撞）。
    """
    _non_blank_str(file_field, "file_field")
    _non_blank_str(filename, "filename")
    _non_blank_str(boundary, "boundary")
    if not isinstance(file_bytes, bytes) or not file_bytes:
        raise LLMError("file_bytes must be non-empty bytes")
    if not isinstance(fields, Mapping):
        raise LLMError("fields must be a mapping of str to str")
    boundary_bytes = boundary.encode("utf-8")
    for key, value in fields.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise LLMError("fields must be a mapping of str to str")
        if boundary in key or boundary in value:
            raise LLMError("boundary collides with field content")
    if boundary in filename or boundary_bytes in file_bytes:
        raise LLMError("boundary collides with file content")
    parts: list[bytes] = []
    for key, value in fields.items():
        parts.append(
            (f"--{boundary}\r\n"
             f'Content-Disposition: form-data; name="{key}"\r\n'
             f"\r\n"
             f"{value}\r\n").encode("utf-8"))
    parts.append(
        (f"--{boundary}\r\n"
         f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
         f"Content-Type: application/octet-stream\r\n"
         f"\r\n").encode("utf-8"))
    parts.append(file_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


# ---------- 传输（唯一网络出口） ----------

class Transport(Protocol):
    """传输协议：post 返回 (HTTP 状态码, 响应体字节)。"""

    def post(self, url: str, *, headers: Mapping[str, str], body: bytes,
             content_type: str, timeout: float) -> tuple[int, bytes]: ...


class MockTransport:
    """确定性 mock 传输（契约测试零网络）：按端点回脚本化应答，calls 记录每次请求。"""

    DEFAULT_REPLIES = {
        "chat": (200, json.dumps(
            {"choices": [{"message": {"content": "模拟回答"}}]},
            ensure_ascii=False).encode("utf-8")),
        "tts": (200, b"ID3MOCKMP3"),
        "asr": (200, json.dumps({"text": "模拟转写"}, ensure_ascii=False).encode("utf-8")),
    }

    def __init__(self, replies: Optional[Mapping[str, tuple[int, bytes]]] = None) -> None:
        self.replies: dict[str, tuple[int, bytes]] = dict(self.DEFAULT_REPLIES)
        if replies:
            self.replies.update(replies)
        self.calls: list[dict] = []

    def post(self, url: str, *, headers: Mapping[str, str], body: bytes,
             content_type: str, timeout: float) -> tuple[int, bytes]:
        self.calls.append({
            "url": url,
            "headers": dict(headers),
            "body": bytes(body),
            "content_type": content_type,
            "timeout": timeout,
        })
        cap = _CAP_BY_URL.get(url)
        status, payload = self.replies.get(cap, (404, b'{"error":"mock: unknown url"}'))
        return status, payload


class HttpTransport:
    """生产传输【仅参考，无契约测试覆盖】：stdlib urllib 单次 POST。

    纵深防御：发送前再跑一次 check_url（真实 DNS 解析 + 私网阻断），与
    MMClient 内的守卫互为双保险。
    """

    def __init__(self, *, resolve: Optional[Callable[[str], list[str]]] = None) -> None:
        self._resolve = resolve

    def post(self, url: str, *, headers: Mapping[str, str], body: bytes,
             content_type: str, timeout: float) -> tuple[int, bytes]:
        check_url(url, resolve=self._resolve)
        request = urllib.request.Request(url, data=bytes(body), method="POST")
        for name, value in headers.items():
            request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                return int(resp.status), resp.read()
        except urllib.error.HTTPError as e:  # 必须先于 URLError（其子类）
            try:
                detail = e.read()
            except Exception:
                detail = b""
            return int(e.code), detail
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise LLMError(f"transport failed: {e}") from e


# ---------- 客户端 ----------

def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _parse_json_object(body: bytes, cap: str) -> dict:
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise LLMError(f"bad {cap} response: invalid json") from e
    if not isinstance(parsed, dict):
        raise LLMError(f"bad {cap} response: expected json object")
    return parsed


def _parse_chat_body(body: bytes, cap: str) -> str:
    parsed = _parse_json_object(body, cap)
    try:
        content = parsed["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"bad {cap} response: missing choices/message/content") from e
    if not isinstance(content, str):
        raise LLMError(f"bad {cap} response: content is not a str")
    return content


class MMClient:
    """四能力客户端：chat / vision / tts / asr。传输注入，key 构造时解析（fail-fast）。"""

    def __init__(self, transport: Transport, *, model: str = MODEL_CHAT,
                 tts_model: str = MODEL_TTS, asr_model: str = MODEL_ASR,
                 voice: str = TTS_VOICE, timeout: float = DEFAULT_TIMEOUT,
                 env: Optional[Mapping[str, str]] = None,
                 resolve: Optional[Callable[[str], list[str]]] = None) -> None:
        if not callable(getattr(transport, "post", None)):
            raise LLMError("transport must provide a callable post()")
        for name, value in (("model", model), ("tts_model", tts_model),
                            ("asr_model", asr_model), ("voice", voice)):
            _non_blank_str(value, name)
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or timeout <= 0):
            raise LLMError("timeout must be a positive finite number")
        self._transport = transport
        self._key = api_key(env)  # fail-fast；key 只存内存，绝不进日志/错误
        self._resolve = resolve
        self.model = model
        self.tts_model = tts_model
        self.asr_model = asr_model
        self.voice = voice
        self.timeout = float(timeout)

    # -- 内部：构造 headers -> 守卫 -> 单口发出；非 200 统一归族 --

    def _post(self, cap: str, body: bytes, content_type: str) -> tuple[int, bytes]:
        url = ENDPOINTS[cap]
        check_url(url, resolve=self._resolve)
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": content_type}
        status, resp = self._transport.post(
            url, headers=headers, body=body, content_type=content_type,
            timeout=self.timeout)
        if status != 200:
            raise LLMError(f"mm http {status}")
        return status, resp

    def chat(self, text: str, *, system: Optional[str] = None) -> str:
        _non_blank_str(text, "text")
        if system is not None:
            _non_blank_str(system, "system")
        messages: list[dict] = []
        if system is not None:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": text})
        payload = {"model": self.model, "messages": messages}
        _, resp = self._post("chat", _json_bytes(payload), JSON_CONTENT_TYPE)
        return _parse_chat_body(resp, "chat")

    def vision(self, prompt: str, images: Sequence,
               *, image_format: str = "png") -> str:
        content = vision_content(prompt, images, image_format)
        payload = {"model": self.model,
                   "messages": [{"role": "user", "content": content}]}
        _, resp = self._post("chat", _json_bytes(payload), JSON_CONTENT_TYPE)
        return _parse_chat_body(resp, "chat")

    def tts(self, text: str, *, voice: Optional[str] = None,
            response_format: str = TTS_FORMAT) -> bytes:
        _non_blank_str(text, "text")
        v = self.voice if voice is None else voice
        _non_blank_str(v, "voice")
        _non_blank_str(response_format, "response_format")
        payload = {"model": self.tts_model, "input": text, "voice": v,
                   "response_format": response_format}
        _, resp = self._post("tts", _json_bytes(payload), JSON_CONTENT_TYPE)
        return bytes(resp)  # 音频字节原样返回，不解析（I8 唯一宽容点）

    def asr(self, audio: bytes, *, filename: str = "audio.wav") -> str:
        if not isinstance(audio, bytes) or not audio:
            raise LLMError("audio must be non-empty bytes")
        _non_blank_str(filename, "filename")
        body, content_type = multipart_body(
            {"model": self.asr_model}, "file", filename, audio)
        _, resp = self._post("asr", body, content_type)
        parsed = _parse_json_object(resp, "asr")
        text = parsed.get("text")
        if not isinstance(text, str):
            raise LLMError("bad asr response: text is not a str")
        return text
