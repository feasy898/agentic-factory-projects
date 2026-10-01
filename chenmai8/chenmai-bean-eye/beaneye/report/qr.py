"""M10 质量护照：验真二维码与结果校验和。

- **规范化 JSON**：``BatchResult.to_json()`` 解析后按键排序、紧凑分隔符、
  UTF-8 原文序列化；sha256 即对该字节串计算（``canonical_sha256``）。
- **QR 负载**（M10 spec）：``{verify_base_url}/r/{report_id}|{sha256}``；
  ``|`` 为分隔符，sha256 为 64 位十六进制校验和。
- **渲染**：``segno`` 生成 PNG（纠错级 M）；解码验读用 ``zxing-cpp``，
  由 eval（tests/test_report.py）完成「生成→解码→回读一致」闭环。
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
from typing import TYPE_CHECKING

import segno

from .errors import ReportError

if TYPE_CHECKING:  # 仅供类型标注
    from beaneye.schemas import BatchResult

__all__ = [
    "DEFAULT_VERIFY_BASE_URL",
    "canonical_json",
    "canonical_sha256",
    "build_qr_payload",
    "parse_qr_payload",
    "render_qr_png",
    "qr_data_uri",
]

DEFAULT_VERIFY_BASE_URL = "https://verify.beaneye.example"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def canonical_json(result: BatchResult) -> str:
    """BatchResult 的规范化 JSON（键排序 + 紧凑分隔符 + ensure_ascii=False）。"""
    data = json.loads(result.to_json())
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_sha256(result: BatchResult) -> str:
    """结果校验和 = sha256(canonical_json(result).encode("utf-8"))，64 位十六进制。"""
    return hashlib.sha256(canonical_json(result).encode("utf-8")).hexdigest()


def build_qr_payload(
    report_id: str,
    sha256_hex: str,
    *,
    verify_base_url: str = DEFAULT_VERIFY_BASE_URL,
) -> str:
    """组装验真负载 ``{verify_base_url}/r/{report_id}|{sha256}``。

    ``sha256_hex`` 必须是 64 位十六进制；否则抛 :class:`ReportError`。
    """
    if not report_id:
        raise ReportError("report_id 不能为空")
    if not _SHA256_RE.match(sha256_hex):
        raise ReportError(f"sha256 必须是 64 位十六进制，得到 {sha256_hex!r}")
    base = verify_base_url.rstrip("/")
    return f"{base}/r/{report_id}|{sha256_hex}"


def parse_qr_payload(payload: str) -> tuple[str, str]:
    """解析验真负载 → ``(report_id, sha256)``；格式非法抛 :class:`ReportError`。"""
    if "|" not in payload:
        raise ReportError(f"QR 负载缺少 '|' 分隔符: {payload[:80]!r}")
    head, _, sha = payload.rpartition("|")
    prefix, _, rid = head.rpartition("/r/")
    if not prefix or not rid:
        raise ReportError(f"QR 负载缺少 '/r/<report_id>' 段: {payload[:80]!r}")
    if not _SHA256_RE.match(sha):
        raise ReportError(f"QR 负载的校验和非法: {sha!r}")
    return rid, sha


def render_qr_png(payload: str, *, scale: int = 6, border: int = 2) -> bytes:
    """用 segno 把负载渲染为二维码 PNG 字节（纠错级 M）。"""
    if not payload:
        raise ReportError("QR 负载不能为空")
    qr = segno.make(payload, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=scale, border=border, dark="#111111", light="#ffffff")
    return buf.getvalue()


def qr_data_uri(payload: str, **kwargs: int) -> str:
    """渲染二维码并转成 ``data:image/png;base64,...``（HTML 内嵌自包含）。"""
    raw = render_qr_png(payload, **kwargs)
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
