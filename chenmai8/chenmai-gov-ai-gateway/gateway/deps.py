"""网关请求面依赖：部门 Key 鉴权（常量时间比较）与 request/session 标识生成。"""
from __future__ import annotations

import hashlib
import hmac
import uuid

BEARER_PREFIX = "Bearer "

#: 对外标识前缀（§5.4/§5.6 示例形态）
REQUEST_ID_PREFIX = "req_"
SESSION_ID_PREFIX = "sess_"
_ID_TOKEN_LEN = 12


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def extract_bearer(authorization: str | None) -> str | None:
    """``Authorization: Bearer <key>`` → key；缺失/形态不符返回 None。"""
    if not authorization:
        return None
    if not authorization.startswith(BEARER_PREFIX):
        return None
    key = authorization[len(BEARER_PREFIX):].strip()
    return key or None


def authenticate(presented: str | None, dept_key_digests: dict[str, str]) -> str | None:
    """部门 Key 鉴权：对库存 sha256 逐部门常量时间比较；命中返回部门名，否则 None。"""
    if not presented:
        return None
    presented_digest = sha256_hex(presented)
    for dept, digest in dept_key_digests.items():
        if hmac.compare_digest(presented_digest, digest):
            return dept
    return None


def new_request_id() -> str:
    return REQUEST_ID_PREFIX + uuid.uuid4().hex[:_ID_TOKEN_LEN]


def new_session_id() -> str:
    return SESSION_ID_PREFIX + uuid.uuid4().hex[:_ID_TOKEN_LEN]
