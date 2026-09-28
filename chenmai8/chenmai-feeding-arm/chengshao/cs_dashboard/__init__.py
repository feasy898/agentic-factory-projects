"""数据包：护理看板。FastAPI + SQLite（data/care.db）+ SSE 实时 + 本地化单页前端。

HTTP 契约冻结（§3.2）：POST /api/session/start、POST /api/bite、
GET /api/session/current、GET /api/stream。

用法：
    python -m cs_dashboard                # 本机 127.0.0.1:8100（以 chengshao/ 为 cwd）
    python -m chengshao.cs_dashboard      # 同上（以仓库根为 cwd）
    uvicorn chengshao.cs_dashboard.app:create_app --factory --port 8100
"""

from __future__ import annotations

from .app import create_app
from .store import (
    DEFAULT_DB_PATH,
    ActiveSessionExistsError,
    DuplicateBiteError,
    NoActiveSessionError,
    Store,
    StoreError,
)

__all__ = [
    "DEFAULT_DB_PATH",
    "ActiveSessionExistsError",
    "DuplicateBiteError",
    "NoActiveSessionError",
    "Store",
    "StoreError",
    "create_app",
]
