"""`python -m chengshao.cs_orchestra`（或包根 `python -m cs_orchestra`）入口：
等价于 cs_orchestra.eval 主入口。"""

from .eval import main

if __name__ == "__main__":
    raise SystemExit(main())
