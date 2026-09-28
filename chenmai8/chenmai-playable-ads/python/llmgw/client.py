"""llmgw.client —— 通用 chat-completions 协议客户端（LLM 网关核心）。

协议形态（业界通用 chat-completions HTTP 协议）：
    POST {PF_LLM_BASE_URL}/chat/completions
    请求/响应均为 JSON；鉴权用 `Authorization: Bearer <key>`；
    多模态消息用 content 数组（text / image_url 的 data URL）；
    结构化输出用 response_format={"type": "json_object"}。

本模块不含任何具体厂商 / 端点 / 模型名——一切由环境变量注入：

    PF_LLM_BASE_URL          服务根地址（需含版本前缀，如 https://host/v1；
                             仅给主机名时自动补 /v1）
    PF_LLM_API_KEY           Bearer 密钥（可选；本地推理服务常免鉴权）
    PF_LLM_MODEL             主模型名
    PF_LLM_FALLBACK_MODELS   备用模型名列表，逗号分隔，按序降级
    PF_LLM_TIMEOUT           单次 HTTP 超时秒数（默认 30）
    PF_LLM_MAX_RETRIES       单模型最大重试次数（默认 2；耗尽后降级到下一模型）
    PF_LLM_BACKOFF           重试退避基数秒（默认 0.8，指数递增，单次封顶 8s）

重试 / 降级规则：
    - 可重试错误：网络异常、超时、HTTP 408/409/429/5xx、200 但响应体异常；
      同一模型指数退避重试至多 max_retries 次，仍失败则降级到下一模型；
    - 404（模型不存在）：不重试，直接降级到下一模型；
    - 其余 4xx（如 400/401 参数或密钥问题）：换模型也无益，立即抛 LLMError。

仅依赖 Python 标准库（urllib/json/base64），零第三方依赖。
"""

import base64
import binascii
import http.client
import json
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

__all__ = [
    "Gateway",
    "Client",
    "LLMError",
    "ConfigError",
    "chat",
    "text_of",
    "json_of",
    "endpoint_for",
]

_RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})
_SKIP_MODEL_STATUS = frozenset({404})  # 模型不存在：不重试，直接降级
_BACKOFF_CAP = 8.0


class ConfigError(RuntimeError):
    """环境变量缺失或非法。"""


class LLMError(RuntimeError):
    """一次 chat 请求最终失败（重试与降级均已耗尽，或遇到不可恢复错误）。

    属性：
        status: 最后一次的 HTTP 状态码（网络错误时为 None）
        model:  最后一次尝试的模型名
        attempts: 全部尝试记录 [{'model','attempt','status','error'}, ...]
    """

    def __init__(self, message, *, status=None, model=None, attempts=None):
        super().__init__(message)
        self.status = status
        self.model = model
        self.attempts = list(attempts or [])

    def summary(self):
        lines = [f"llmgw: 最终失败（共 {len(self.attempts)} 次尝试）"]
        for a in self.attempts:
            lines.append(
                f"  - model={a['model']} attempt={a['attempt']} "
                f"status={a['status']} error={a['error']}"
            )
        return "\n".join(lines)


class _AttemptError(Exception):
    """内部：单次尝试失败的分类。"""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class _Transient(_AttemptError):
    """可重试；同模型重试耗尽后降级到下一模型。"""


class _SkipModel(_AttemptError):
    """本模型不可用（如 404）；不重试，直接降级到下一模型。"""


class _Fatal(_AttemptError):
    """不可恢复（如 400/401）；立即终止，不再重试或降级。"""


def _env(name, default=None):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def endpoint_for(base_url):
    """由服务根地址拼出 chat-completions 端点。

    规则：去掉末尾 `/`；若只有主机名（无路径）则补协议惯用的 `/v1` 前缀；
    最后追加 `/chat/completions`。
    """
    if not base_url or not str(base_url).strip():
        raise ConfigError("PF_LLM_BASE_URL 未设置")
    base = str(base_url).strip().rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in ("http", "https"):
        raise ConfigError(f"PF_LLM_BASE_URL 必须以 http(s):// 开头，得到：{base_url!r}")
    if parsed.path in ("", "/"):
        base += "/v1"
    return base + "/chat/completions"


def _check_base64(data):
    compact = "".join(data.split())
    try:
        base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"图片不是合法 base64：{exc}") from None
    return compact


def _to_data_url(image):
    """把图片参数归一化为 data URL。

    支持三种形式：
        "PYJh..."                       裸 base64（默认按 image/png 处理）
        ("image/webp", "PYJh...")       (mime, base64) 元组
        {"mime_type": "...", "data": "..."}  字典
    也兼容传入完整 data URL（原样透传）。
    """
    if isinstance(image, dict):
        mime = str(image.get("mime_type") or image.get("mime") or "image/png")
        data = image.get("data")
        if not isinstance(data, str) or not data:
            raise ValueError("图片 dict 形式需要非空的 'data'（base64 字符串）")
    elif isinstance(image, (tuple, list)):
        if len(image) != 2:
            raise ValueError("图片元组形式为 (mime_type, base64)")
        mime, data = str(image[0]), image[1]
    elif isinstance(image, str):
        data = image
        mime = "image/png"
    else:
        raise ValueError(f"不支持的图片类型：{type(image).__name__}")

    if data.startswith("data:"):
        return data  # 已是 data URL
    compact = _check_base64(data)
    return f"data:{mime};base64,{compact}"


def _apply_images(messages, images):
    """把图片以 data URL 形式并入消息列表。

    规则：若最后一条是 user 且 content 为纯文本，则把它升级为
    [text, image_url...] 多模态数组；否则追加一条仅含图片的 user 消息。
    """
    if not images:
        return messages
    parts = [{"type": "image_url", "image_url": {"url": _to_data_url(img)}}
             for img in images]
    out = list(messages)
    if out and out[-1].get("role") == "user" and isinstance(out[-1].get("content"), str):
        last = dict(out[-1])
        last["content"] = [{"type": "text", "text": last["content"]}] + parts
        out[-1] = last
    else:
        out.append({"role": "user", "content": list(parts)})
    return out


def _extract_error_message(raw, fallback):
    """从错误响应体里尽量提取可读信息。"""
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        obj = None
    if isinstance(obj, dict):
        err = obj.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
        if isinstance(err, str) and err:
            return err
    if raw:
        return f"{fallback}: {raw[:200].decode('utf-8', 'replace')}"
    return fallback


def text_of(response):
    """从 chat 响应 dict 中取第一条助手文本。"""
    try:
        return response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMError("响应中没有助手文本（choices[0].message.content）") from None


def json_of(response):
    """把助手文本解析为 JSON dict（JSON 模式下使用）；解析失败抛 LLMError。

    容错：自动剥掉 ```json ...``` 围栏。
    """
    text = text_of(response)
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").lstrip()
        if stripped[:4].lower() == "json":
            stripped = stripped[4:]
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise LLMError(f"助手文本不是合法 JSON：{exc}；原文前 200 字：{text[:200]!r}") from None


class Gateway:
    """chat-completions 协议网关客户端。

    构造参数缺省时逐项回退到环境变量（见模块 docstring）。
    chat() 返回完整响应 dict；取文本用 text_of()，取解析后的 JSON 用 json_of()。
    """

    def __init__(self, base_url=None, api_key=None, model=None,
                 fallback_models=None, timeout=None, max_retries=None,
                 backoff=None):
        self.base_url = base_url if base_url is not None else _env("PF_LLM_BASE_URL")
        self.api_key = api_key if api_key is not None else _env("PF_LLM_API_KEY")
        self.model = model if model is not None else _env("PF_LLM_MODEL")
        if fallback_models is None:
            fallback_models = _env("PF_LLM_FALLBACK_MODELS", "") or ""
        if isinstance(fallback_models, str):
            fallback_models = [m.strip() for m in fallback_models.split(",")
                               if m.strip()]
        self.fallback_models = list(fallback_models)
        self.timeout = float(timeout if timeout is not None
                             else _env("PF_LLM_TIMEOUT", 30))
        self.max_retries = int(max_retries if max_retries is not None
                               else _env("PF_LLM_MAX_RETRIES", 2))
        self.backoff = float(backoff if backoff is not None
                             else _env("PF_LLM_BACKOFF", 0.8))

    @property
    def model_chain(self):
        """主模型 + 备用模型（去重、保序）。"""
        chain = []
        for m in [self.model, *self.fallback_models]:
            if m and m not in chain:
                chain.append(m)
        return chain

    def chat(self, messages, images=None, json_schema=None, *,
             json_mode=False, timeout=None, max_retries=None, backoff=None,
             extra=None):
        """发起一次对话请求，成功则返回完整响应 dict。

        参数：
            messages: [{"role": ..., "content": ...}, ...]，原样透传
            images:   图片列表（见 _to_data_url 支持的形式），base64 输入
            json_schema: 给出时启用 JSON 模式（response_format=json_object），
                      并把 schema 以 system 提示注入（json_object 协议本身
                      不携带 schema，这是通用兼容做法）
            json_mode:  仅开 JSON 模式、不注入 schema 提示
            timeout/max_retries/backoff: 逐次覆盖构造参数
            extra:    透传到请求体的额外字段（如 temperature）

        失败时抛 LLMError（attempts 属性含全部尝试记录）。
        """
        if not isinstance(messages, (list, tuple)) or not messages:
            raise ValueError("messages 必须为非空序列")
        cleaned = []
        for i, m in enumerate(messages):
            if not isinstance(m, dict) or "role" not in m or "content" not in m:
                raise ValueError(f"messages[{i}] 必须是含 role/content 的 dict")
            cleaned.append(dict(m))
        if not self.base_url:
            raise ConfigError("缺少 PF_LLM_BASE_URL（或 base_url 参数）")
        if not self.model:
            raise ConfigError("缺少 PF_LLM_MODEL（或 model 参数）")

        if json_schema is not None:
            hint = ("只输出一个 JSON 对象：不要解释、不要 markdown 围栏，"
                    "字段与类型必须符合以下 JSON Schema：\n"
                    + json.dumps(json_schema, ensure_ascii=False))
            at = 1 if cleaned and cleaned[0].get("role") == "system" else 0
            cleaned.insert(at, {"role": "system", "content": hint})
        cleaned = _apply_images(cleaned, images)

        payload = {"model": self.model, "messages": cleaned}
        if json_mode or json_schema is not None:
            payload["response_format"] = {"type": "json_object"}
        if extra:
            payload.update(extra)

        endpoint = endpoint_for(self.base_url)
        timeout_s = float(timeout) if timeout is not None else self.timeout
        retries = int(max_retries) if max_retries is not None else self.max_retries
        backoff_s = float(backoff) if backoff is not None else self.backoff

        attempts = []
        for model in self.model_chain:
            payload["model"] = model
            outcome = self._attempt_model(endpoint, payload, model,
                                          timeout_s, retries, backoff_s,
                                          attempts)
            if outcome is not None:
                return outcome
        raise LLMError("全部模型均失败：" + " → ".join(self.model_chain),
                       attempts=attempts)

    def _attempt_model(self, endpoint, payload, model, timeout_s, retries,
                       backoff_s, attempts):
        for attempt in range(retries + 1):
            try:
                return self._post(endpoint, payload, timeout_s)
            except _Fatal as exc:
                attempts.append({"model": model, "attempt": attempt,
                                 "status": exc.status, "error": str(exc)})
                raise LLMError(f"请求被拒绝（HTTP {exc.status}）：{exc}",
                               status=exc.status, model=model,
                               attempts=attempts) from None
            except _SkipModel as exc:
                attempts.append({"model": model, "attempt": attempt,
                                 "status": exc.status,
                                 "error": "模型不可用：" + str(exc)})
                return None
            except _Transient as exc:
                attempts.append({"model": model, "attempt": attempt,
                                 "status": exc.status, "error": str(exc)})
                if attempt == retries:
                    return None
                time.sleep(min(backoff_s * (2 ** attempt), _BACKOFF_CAP))
        return None

    def _post(self, endpoint, payload, timeout_s):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        req = urllib.request.Request(endpoint, data=data, headers=headers,
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                raw = resp.read()
                status = getattr(resp, "status", 200)
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read()
            except Exception:
                detail = b""
            msg = _extract_error_message(detail, f"HTTP {exc.code}")
            if exc.code in _RETRYABLE_STATUS:
                raise _Transient(exc.code, msg) from None
            if exc.code in _SKIP_MODEL_STATUS:
                raise _SkipModel(exc.code, msg) from None
            raise _Fatal(exc.code, msg) from None
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError,
                ConnectionError, BrokenPipeError, OSError) as exc:
            raise _Transient(None, f"网络/超时错误：{exc!r}") from None

        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise _Transient(status, "响应体不是合法 JSON") from None
        if not isinstance(body, dict) or not body.get("choices"):
            desc = body.get("error") if isinstance(body, dict) else body
            raise _Transient(status, f"响应缺少 choices：{desc!r}")
        return body


# 便捷别名
Client = Gateway


def chat(messages, images=None, json_schema=None, **call_kwargs):
    """模块级便捷入口：按当前环境变量构造临时 Gateway 并发起一次 chat。"""
    return Gateway().chat(messages, images=images, json_schema=json_schema,
                          **call_kwargs)
