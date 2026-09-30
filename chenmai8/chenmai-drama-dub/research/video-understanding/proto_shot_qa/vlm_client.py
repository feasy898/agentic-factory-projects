#!/usr/bin/env python3
"""vlm_client —— 总览图 → 多模态模型读图（OpenAI 兼容 chat 接口）。

凭证纪律（组织红线 1）：凭证只从环境变量读（OPENAI_BASE_URL/OPENAI_API_KEY 或
HIGRESS_BASE_URL/HIGRESS_API_KEY），不进 argv、不落盘、不打印；缺失即 BLOCKED，
绝不默认放行，也绝不伪造调用结果。
"""

from __future__ import annotations

import base64
import json
import os
import urllib.request


class CredsBlocked(RuntimeError):
    """凭证缺失——调用方应以此走 BLOCKED 语义（原型约定 exit 3）。"""


def get_creds() -> tuple[str, str, str] | None:
    """返回 (base_url, api_key, model)，无凭证返回 None。"""
    base = os.environ.get("OPENAI_BASE_URL") or os.environ.get("HIGRESS_BASE_URL")
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("HIGRESS_API_KEY")
    model = os.environ.get("VLM_MODEL")
    if not (base and key and model):
        return None
    return base.rstrip("/"), key, model


def _data_uri(img_path: str) -> str:
    raw = open(img_path, "rb").read()
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")


def describe_sheet(img_path: str, prompt: str, *, timeout: int = 180) -> str:
    """单张总览图 → 模型文字理解。凭证缺失抛 CredsBlocked。"""
    creds = get_creds()
    if creds is None:
        raise CredsBlocked("no VLM credentials in env (OPENAI_*|HIGRESS_* + VLM_MODEL)")
    base, key, model = creds
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": _data_uri(img_path)}},
            ],
        }],
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


DEFAULT_PROMPT = (
    "这是一段短剧视频按时间顺序排布的关键帧总览图（每格下方 #序号 t=秒数）。"
    "请按时间顺序逐格看图，输出 JSON 数组：每格一个对象，字段 "
    "shot_type(近景/中景/远景)、frontal_closeup(bool，是否人物正脸近景)、"
    "scene(一句话场景)、on_screen_text(画面上出现的全部文字原文，无则空串)。只输出 JSON。"
)


def describe_all(overviews: list[str], prompt: str = DEFAULT_PROMPT) -> list[dict]:
    """逐张读总览图（顺序=时间顺序，一张不漏）。"""
    out = []
    for p in overviews:
        text = describe_sheet(p, prompt)
        out.append({"overview": p, "response": text})
    return out
