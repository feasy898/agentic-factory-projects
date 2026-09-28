"""入口：python -m cs_dashboard（或 python -m chengshao.cs_dashboard）。

缺省 127.0.0.1:8100（开发指令 §5.7 手工验收端口），数据库缺省仓库根 data/care.db。
无外网依赖：静态资源全部本地化，拔网线可开（验收项"离线可开"）。
"""

from __future__ import annotations

import argparse

import uvicorn

from .app import create_app
from .store import DEFAULT_DB_PATH


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="护理看板服务（FastAPI + SQLite + SSE）")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（缺省 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8100, help="监听端口（缺省 8100）")
    parser.add_argument(
        "--db", default=str(DEFAULT_DB_PATH), help=f"SQLite 文件路径（缺省 {DEFAULT_DB_PATH}）"
    )
    args = parser.parse_args(argv)

    app = create_app(db_path=args.db)
    print(f"护理看板: http://{args.host}:{args.port}/  (db: {args.db})")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
