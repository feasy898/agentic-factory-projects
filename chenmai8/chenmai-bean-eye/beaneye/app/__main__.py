"""``python -m beaneye.app`` 入口——转发到 :func:`beaneye.app.main`。

背景：``python -m <pkg>`` 只执行 ``<pkg>/__main__.py``，不会执行
``__init__.py`` 底部的 ``if __name__ == "__main__"`` 块；缺本文件时
``python -m beaneye.app`` 报 ``No module named beaneye.app.__main__``。
等价替代（无本文件的旧检出）：``python -c "from beaneye.app import run; run()"``。
"""

from beaneye.app import main

if __name__ == "__main__":
    main()
