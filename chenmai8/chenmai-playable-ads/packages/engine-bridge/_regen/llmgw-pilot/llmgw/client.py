"""llmgw.client —— chat-completions 通用客户端（纯标准库实现）。

设计要点（对应 SPEC.md）：
- 配置全部由环境变量（PF_LLM_*）注入，代码零厂商/端点/模型名硬编码；
- 支持：普通对话、图片 base64 输入、JSON 模式（response_format=json_object +
  schema 提示注入）、单次 HTTP 超时、指数退避重试、多模型按序降级、错误归因；
- 依赖仅 Python 标准库（urllib / json / base64 / http.client）。
"""

import base64
import http.client
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

__all__ = [
    "Client",
    "ConfigError",
    "Gateway",
    "LLMError",
    "chat",
    "endpoint_for",
    "json_of",
    "text_of",
]

# --------------------------------------------------------------- 环境变量契约

ENV_BASE_URL = "PF_LLM_BASE_URL"
ENV_API_KEY = "PF_LLM_API_KEY"
ENV_MODEL = "PF_LLM_MODEL"
ENV_FALLBACK_MODELS = "PF_LLM_FALLBACK_MODELS"
ENV_TIMEOUT = "PF_LLM_TIMEOUT"
ENV_MAX_RETRIES = "PF_LLM_MAX_RETRIES"
ENV_BACKOFF = "PF_LLM_BACKOFF"

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_BACKOFF = 0.8
BACKOFF_CAP = 8.0  # 退避封顶秒数

# JSON 模式 schema 提示注入的固定文案（SPEC §3）
JSON_SCHEMA_INSTRUCTION = (
    "只输出一个 JSON 对象：不要解释、不要 markdown 围栏，"
    "字段与类型必须符合以下 JSON Schema：\n"
)

# 可重试的 HTTP 状态码（5xx 全体另判）
RETRYABLE_STATUS = (408, 409, 429)


# --------------------------------------------------------------- 异常类型

class ConfigError(Exception):
    """配置缺失或非法（环境变量 / 构造参数 / base_url 形状）。"""


class LLMError(Exception):
    """LLM 请求最终失败；携带 status / model / attempts 归因信息。"""

    def __init__(self, message, status=None, model=None, attempts=None):
        super().__init__(message)
        self.status = status
        self.model = model
        self.attempts = list(attempts) if attempts else []

    def summary(self):
        """人读的尝试清单（SPEC §4）。"""
        lines = [str(self)]
        for i, att in enumerate(self.attempts, 1):
            lines.append("  %d. model=%s attempt=%s status=%s error=%s" % (
                i, att.get("model"), att.get("attempt"),
                att.get("status"), att.get("error")))
        return "\n".join(lines)


# 内部错误分类（SPEC §4 矩阵）；不导出。
class _Transient(Exception):
    """可重试：网络异常/超时、408/409/429/5xx、200 但响应体异常。"""

    def __init__(self, error, status=None):
        super().__init__(error)
        self.error = error
        self.status = status


class _SkipModel(Exception):
    """跳过当前模型：HTTP 404（模型不存在），不重试直接降级。"""

    def __init__(self, error, status=None):
        super().__init__(error)
        self.error = error
        self.status = status


class _Fatal(Exception):
    """致命：其余 4xx（400/401 参数或密钥问题），立即抛 LLMError。"""

    def __init__(self, error, status=None):
        super().__init__(error)
        self.error = error
        self.status = status


# --------------------------------------------------------------- 工具函数

def endpoint_for(base):
    """由服务根地址拼出 chat-completions 端点（SPEC §2）。

    去尾 ``/`` → path 为空时补 ``/v1`` → 追加 ``/chat/completions``；
    scheme 必须 http(s)，否则抛 :class:`ConfigError`。
    """
    if not isinstance(base, str) or not base.strip():
        raise ConfigError("缺少 %s（服务根地址）" % ENV_BASE_URL)
    root = base.strip().rstrip("/")
    if not root:
        raise ConfigError("%s 不能全为 '/'" % ENV_BASE_URL)
    parts = urllib.parse.urlsplit(root)
    if parts.scheme not in ("http", "https"):
        raise ConfigError("%s 的 scheme 必须是 http/https：%r" % (ENV_BASE_URL, base))
    if not parts.netloc:
        raise ConfigError("%s 缺少主机名：%r" % (ENV_BASE_URL, base))
    if not parts.path:
        root += "/v1"
    return root + "/chat/completions"


def _env_str(name):
    value = os.environ.get(name)
    return value.strip() if isinstance(value, str) else ""


def _env_float(name, default):
    raw = _env_str(name)
    if not raw:
        return float(default)
    try:
        return float(raw)
    except ValueError:
        raise ConfigError("%s 必须是数字：%r" % (name, raw))


def _env_int(name, default):
    raw = _env_str(name)
    if not raw:
        return int(default)
    try:
        return int(raw)
    except ValueError:
        raise ConfigError("%s 必须是整数：%r" % (name, raw))


def _dedup_keep_order(models):
    """主/备模型去重保序，合成 model_chain（SPEC §2）。"""
    seen = set()
    chain = []
    for m in models:
        name = str(m).strip()
        if name and name not in seen:
            seen.add(name)
            chain.append(name)
    return chain


def _clean_b64(data):
    """base64 紧凑化（去全部空白）+ 严格校验；非法抛 ValueError。"""
    compacted = "".join(str(data).split())
    try:
        base64.b64decode(compacted, validate=True)
    except Exception as exc:  # binascii.Error 等统一归一为 ValueError
        raise ValueError("非法 base64 图片数据：%s" % exc)
    return compacted


def _image_part(img):
    """把一种图片形状转成 image_url 内容部件（SPEC §3.1）。"""
    if isinstance(img, str):
        if img.startswith("data:"):
            url = img  # 完整 data URL 原样透传
        else:
            url = "data:image/png;base64," + _clean_b64(img)
    elif isinstance(img, (tuple, list)) and len(img) == 2:
        mime, data = img
        url = "data:%s;base64,%s" % (mime, _clean_b64(data))
    elif isinstance(img, dict):
        mime = img.get("mime_type") or img.get("mime") or "image/png"
        url = "data:%s;base64,%s" % (mime, _clean_b64(img.get("data", "")))
    else:
        raise ValueError("不支持的图片形状：%r" % (img,))
    return {"type": "image_url", "image_url": {"url": url}}


def _attach_images(messages, images):
    """把图片并入消息序列（SPEC §3.1 并入规则）。

    最后一条是 user 且 content 为纯文本 → 升级为 [text, image_url...] 数组；
    否则追加一条仅含图片的 user 消息。messages 须已是浅拷贝列表。
    """
    parts = [_image_part(img) for img in images]
    if not parts:
        return messages
    last = messages[-1] if messages else None
    if (isinstance(last, dict) and last.get("role") == "user"
            and isinstance(last.get("content"), str)):
        last["content"] = [{"type": "text", "text": last["content"]}] + parts
    else:
        messages.append({"role": "user", "content": list(parts)})
    return messages


def _inject_schema(messages, json_schema):
    """json_schema 提示注入（SPEC §3）。

    system 插入位置 = 首条已是 system 则 index 1，否则 index 0。
    """
    if json_schema is None:
        return messages
    if isinstance(json_schema, str):
        schema_text = json_schema
    else:
        schema_text = json.dumps(json_schema, ensure_ascii=False)
    note = {"role": "system", "content": JSON_SCHEMA_INSTRUCTION + schema_text}
    msgs = list(messages)
    if msgs and isinstance(msgs[0], dict) and msgs[0].get("role") == "system":
        msgs.insert(1, note)
    else:
        msgs.insert(0, note)
    return msgs


def _error_message_of(raw):
    """错误信息提取（SPEC §4）：响应体 JSON 的 error.message 优先，
    否则截 200 字节原文。"""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", "replace")

    def fallback():
        return raw[:200].decode("utf-8", "replace")

    try:
        data = json.loads(text)
    except ValueError:
        return fallback()
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            msg = err.get("message")
            if msg is not None:
                return str(msg)
        elif isinstance(err, str):
            return err
    return fallback()


# --------------------------------------------------------------- 结果提取

def text_of(resp):
    """取 choices[0].message.content；缺失抛 LLMError（SPEC §3）。"""
    try:
        content = resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMError("响应缺少 choices[0].message.content：%r" %
                       (resp if not isinstance(resp, dict) else list(resp.keys())))
    return content


def json_of(resp):
    """把助手文本解析为 JSON；失败抛 LLMError（含原文前 200 字）。

    容错剥围栏（SPEC §3）：strip 后以 ``` 开头 → strip("`") → lstrip →
    若前 4 字符小写为 "json" 则去掉 → json.loads。
    """
    original = text_of(resp)
    s = original.strip()
    if s.startswith("```"):
        s = s.strip("`").lstrip()
        if s[:4].lower() == "json":
            s = s[4:]
    try:
        return json.loads(s)
    except ValueError as exc:
        raise LLMError("助手输出不是合法 JSON（%s），原文前 200 字：%s"
                       % (exc, str(original)[:200]))


# --------------------------------------------------------------- 客户端本体

class Gateway:
    """chat-completions 通用网关客户端。

    构造参数缺省时逐项回退环境变量（SPEC §2）；
    ``chat()`` 调用级参数可再覆盖 timeout / max_retries / backoff。
    """

    def __init__(self, base_url=None, api_key=None, model=None,
                 fallback_models=None, timeout=None, max_retries=None,
                 backoff=None):
        self.base_url = (base_url if base_url is not None
                         else self._required_env(ENV_BASE_URL))
        self.api_key = (api_key if api_key is not None
                        else _env_str(ENV_API_KEY))
        self.model = (model if model is not None
                      else self._required_env(ENV_MODEL))
        if fallback_models is None:
            fallback_models = [p.strip()
                               for p in _env_str(ENV_FALLBACK_MODELS).split(",")
                               if p.strip()]
        self.timeout = (timeout if timeout is not None
                        else _env_float(ENV_TIMEOUT, DEFAULT_TIMEOUT))
        self.max_retries = (max_retries if max_retries is not None
                            else _env_int(ENV_MAX_RETRIES, DEFAULT_MAX_RETRIES))
        self.backoff = (backoff if backoff is not None
                        else _env_float(ENV_BACKOFF, DEFAULT_BACKOFF))
        self.model_chain = _dedup_keep_order([self.model] + list(fallback_models))

    @staticmethod
    def _required_env(name):
        value = _env_str(name)
        if not value:
            raise ConfigError("缺少环境变量 %s" % name)
        return value

    # ---------------------------------------------------------- 公共入口

    def chat(self, messages, images=None, json_schema=None, *, json_mode=False,
             timeout=None, max_retries=None, backoff=None, extra=None):
        """一次对话请求；返回服务端原始响应 dict。

        - messages：非空序列，每项含 role/content（原样透传，逐项浅拷贝）；
        - images：SPEC §3.1 的三种形状（+data URL 透传）；
        - json_schema / json_mode：JSON 模式（response_format=json_object +
          schema 提示注入）；
        - timeout / max_retries / backoff：调用级覆盖；
        - extra：透传请求体额外字段（如 temperature）。
        """
        msgs = self._prepare_messages(messages, images, json_schema)
        timeout = self.timeout if timeout is None else float(timeout)
        max_retries = (self.max_retries if max_retries is None
                       else int(max_retries))
        backoff = self.backoff if backoff is None else float(backoff)
        want_json = bool(json_mode) or json_schema is not None
        return self._run(msgs, want_json, timeout, max_retries, backoff, extra)

    # ---------------------------------------------------------- 内部实现

    @staticmethod
    def _prepare_messages(messages, images, json_schema):
        if messages is None:
            raise ValueError("messages 不能为空")
        msgs = [dict(m) for m in messages]  # 逐项浅拷贝，原样透传
        if not msgs:
            raise ValueError("messages 不能为空")
        msgs = _inject_schema(msgs, json_schema)
        if images:
            msgs = _attach_images(msgs, list(images))
        return msgs

    def _run(self, messages, want_json, timeout, max_retries, backoff, extra):
        """重试 / 降级主循环（SPEC §4 矩阵）。"""
        attempts = []
        last_status = None
        last_model = None
        for model in self.model_chain:
            attempt = 0  # 0 基；已消耗的尝试次数 = attempt
            while attempt <= max_retries:
                try:
                    return self._request_once(model, messages, want_json,
                                              timeout, extra)
                except _SkipModel as exc:
                    attempts.append({"model": model, "attempt": attempt + 1,
                                     "status": exc.status, "error": exc.error})
                    last_status, last_model = exc.status, model
                    break  # 不重试，直接降级下一模型
                except _Transient as exc:
                    attempts.append({"model": model, "attempt": attempt + 1,
                                     "status": exc.status, "error": exc.error})
                    last_status, last_model = exc.status, model
                    if attempt < max_retries:
                        time.sleep(min(backoff * (2 ** attempt), BACKOFF_CAP))
                    attempt += 1
                except _Fatal as exc:
                    attempts.append({"model": model, "attempt": attempt + 1,
                                     "status": exc.status, "error": exc.error})
                    raise LLMError("请求失败（HTTP %s）：%s"
                                   % (exc.status, exc.error),
                                   status=exc.status, model=model,
                                   attempts=attempts)
        raise LLMError("全部模型均失败：" + " → ".join(self.model_chain),
                       status=last_status, model=last_model, attempts=attempts)

    def _request_once(self, model, messages, want_json, timeout, extra):
        """单次 HTTP 请求；成功返回响应 dict，失败抛内部分类异常。"""
        endpoint = endpoint_for(self.base_url)
        body = {"model": model, "messages": messages}
        if want_json:
            body["response_format"] = {"type": "json_object"}
        if extra:
            body.update(extra)
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(endpoint, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        if self.api_key:
            req.add_header("Authorization", "Bearer " + self.api_key)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as http_resp:
                status = http_resp.status
                raw = http_resp.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            try:
                raw = exc.read() or b""
            except Exception:
                raw = b""
        except OSError as exc:  # URLError / socket.timeout / ConnectionError
            raise _Transient("网络异常或超时：%s" % exc, status=None)
        except http.client.HTTPException as exc:
            raise _Transient("HTTP 协议异常：%s" % exc, status=None)

        if status == 200:
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise _Transient("200 但响应体不是合法 JSON：%s" % exc, status=200)
            if not isinstance(payload, dict) or not payload.get("choices"):
                raise _Transient("200 但响应非 dict 或缺 choices", status=200)
            return payload

        message = _error_message_of(raw)
        if status == 404:
            raise _SkipModel("模型不存在（HTTP 404）：%s" % message, status=404)
        if status in RETRYABLE_STATUS or 500 <= status <= 599:
            raise _Transient("HTTP %s：%s" % (status, message), status=status)
        raise _Fatal("HTTP %s：%s" % (status, message), status=status)


# --------------------------------------------------------------- 便捷入口

Client = Gateway  # 别名（SPEC §3）


def chat(messages, images=None, json_schema=None, *, json_mode=False,
         timeout=None, max_retries=None, backoff=None, extra=None,
         base_url=None, api_key=None, model=None, fallback_models=None):
    """模块级便捷入口：临时 Gateway（配置逐项回退环境变量）。"""
    gw = Gateway(base_url=base_url, api_key=api_key, model=model,
                 fallback_models=fallback_models)
    return gw.chat(messages, images=images, json_schema=json_schema,
                   json_mode=json_mode, timeout=timeout,
                   max_retries=max_retries, backoff=backoff, extra=extra)
