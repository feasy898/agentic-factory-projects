"""统一适配器: OpenAI 兼容 HTTP + 预算守卫 + 本地兜底调度。

设计:
- Endpoint: 某能力的 base/key/model; configured=False 时直接走本地 (D-004)。
- BudgetGuard: 生图300/VLM1500/TTS200/ASR200, 计入 api_usage 表(route='api', 含失败尝试, 见 DECISIONS);
  耗尽后即便配置了 API 也只走本地。
- Adapter.call(): API 成功即返回; 失败重试1次(共2次尝试)后切本地兜底并留事件痕。
  api_fn/local_fn 均可注入, 测试用 stub, 本地实现允许 lazy import。
- HTTP 用标准库 urllib, 不引入 requests 依赖。
"""

from __future__ import annotations

import base64
import json
import uuid
import urllib.request

CAPABILITY_LIMITS = {"image": 300, "vlm": 1500, "tts": 200, "asr": 200}


class Endpoint:
    def __init__(self, capability: str, base: str = "", key: str = "", model: str = ""):
        self.capability = capability
        self.base = (base or "").rstrip("/")
        self.key = key or ""
        self.model = model or ""

    @property
    def configured(self) -> bool:
        return bool(self.base and self.key and self.model)


def endpoint_from_env(env: dict, capability: str) -> Endpoint:
    """env 为 src.config.parse_api_env() 的输出。"""
    c = env.get(capability.upper(), {})
    return Endpoint(capability, c.get("base", ""), c.get("key", ""), c.get("model", ""))


class BudgetGuard:
    """按能力计数的 API 预算守卫; 计数持久化在 api_usage 表。"""

    def __init__(self, db, limits: dict | None = None):
        self.db = db
        self.limits = dict(CAPABILITY_LIMITS)
        if limits:
            self.limits.update(limits)

    def used(self, capability: str) -> int:
        return self.db.api_usage_count(capability, route="api")

    def remaining(self, capability: str) -> int:
        return max(0, self.limits.get(capability, 0) - self.used(capability))

    def can_use_api(self, capability: str) -> bool:
        return self.remaining(capability) > 0

    def record(self, capability: str, route: str, success: bool) -> None:
        self.db.log_api_usage(capability, route, success)


# ---------------- HTTP 助手 (标准库) ----------------

def http_post_json(url: str, key: str, payload: dict, timeout: int = 120) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_post_bytes(url: str, key: str, payload: dict, timeout: int = 300) -> bytes:
    """POST JSON, 返回原始二进制响应体(音频)。非 2xx 抛异常。"""
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def http_post_multipart(url: str, key: str, fields: dict, file_field: str, file_path: str, timeout: int = 300) -> dict:
    boundary = "----cradle" + uuid.uuid4().hex
    body = bytearray()
    for k, v in fields.items():
        body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8")
    fname = file_path.replace("\\", "/").split("/")[-1]
    body += (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; filename=\"{fname}\"\r\n"
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8")
    with open(file_path, "rb") as f:
        body += f.read()
    body += f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        url,
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def encode_image_data_url(image_path: str) -> str:
    import mimetypes

    mime = mimetypes.guess_type(image_path)[0] or "image/png"
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


class LocalUnavailable(RuntimeError):
    """本地兜底实现依赖缺失时抛出 (如未安装 diffusers/open_clip/edge-tts/whisper)。"""


class Adapter:
    """capability 级适配器。api_fn/local_fn 签名由各能力模块绑定(闭包/偏函数)。"""

    def __init__(self, capability: str, endpoint: Endpoint, budget: BudgetGuard, api_fn=None, local_fn=None, log=None):
        self.capability = capability
        self.endpoint = endpoint
        self.budget = budget
        self.api_fn = api_fn
        self.local_fn = local_fn
        self._log = log or (lambda level, msg: None)

    def call(self, *args, **kw):
        """返回 (result, route)。route ∈ {'api','local'}。"""
        if self.endpoint.configured and self.budget.can_use_api(self.capability):
            last_err: Exception | None = None
            for attempt in (1, 2):
                try:
                    result = self.api_fn(*args, **kw)
                    self.budget.record(self.capability, "api", True)
                    return result, "api"
                except Exception as e:  # noqa: BLE001 — API 侧任何失败都走兜底
                    last_err = e
                    self.budget.record(self.capability, "api", False)
                    self._log("warn", f"[{self.capability}] API 第{attempt}次调用失败: {e}")
            self._log("warn", f"[{self.capability}] API 重试后仍失败, 切本地兜底: {last_err}")
        elif self.endpoint.configured:
            self._log("warn", f"[{self.capability}] API 预算耗尽({self.budget.used(self.capability)}), 只走本地")
        if self.local_fn is None:
            raise LocalUnavailable(f"[{self.capability}] 无 API 且未提供本地实现")
        result = self.local_fn(*args, **kw)
        self.budget.record(self.capability, "local", True)
        return result, "local"
