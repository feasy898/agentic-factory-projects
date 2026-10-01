"""``python -m pipeline`` 入口：等价于 ``python -m pipeline.cli``。"""

import sys

from pipeline.cli import main

if __name__ == "__main__":
    sys.exit(main())
