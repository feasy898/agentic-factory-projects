"""结构化日志骨架（全模块共用，M0 定稿）。

红线（构建纪律）：
- 日志只记录事件与元数据（request_id、长度、类别计数、路由决策等），
  **禁止记录任何未脱敏原文**（prompt/补全文本、raw 值）；
- 唯一例外：显式 ``--debug`` 且输出重定向到 ``data/debug/``（已被 .gitignore 覆盖）；
- 时间戳一律 UTC ISO8601；输出流显式 UTF-8。

用法::

    from common.logs import setup_logging, get_logger
    setup_logging("INFO")            # 进程入口调用一次
    log = get_logger(__name__)
    log.info("chat.completed", extra={"request_id": rid, "latency_ms": 81,
                                      "class_counts": {"ID_CARD": 2}})
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

# LogRecord 的标准属性不进 JSON 字段（避免与业务 extra 混淆/泄漏路径信息）
_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName", "message", "asctime",
}


class JsonFormatter(logging.Formatter):
    """一行一条 JSON；业务 extra 里的可 JSON 化字段直接并入。"""

    def format(self, record: logging.LogRecord) -> str:
        fields: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, val in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            try:
                json.dumps(val, ensure_ascii=False)
            except (TypeError, ValueError):
                val = repr(val)
            fields[key] = val
        if record.exc_info:
            fields["exc"] = self.formatException(record.exc_info)
        return json.dumps(fields, ensure_ascii=False)


def setup_logging(
    level: int | str = logging.INFO,
    json_mode: bool = True,
    stream: Any = None,
) -> None:
    """初始化根 logger（进程入口调用一次；测试可传 stream 捕获）。"""
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    if json_mode:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
