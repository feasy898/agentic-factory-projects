"""python -m qacore 入口（spec §2 命令契约）。"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
