"""跨包导入兼容层：让本包既能从仓库根（tests/scripts/e2e）也能从包根独立运行。

约定（与全仓一致，见 cs_voice/__init__.py 头注）：
1) 集成运行（cwd=仓库根）走 ``import chengshao.cs_schema``（命名空间包）；
2) 独立运行（cwd=chengshao/）走 ``import cs_schema``；
两种方式解析到的契约模块在单进程内保持一致（统一先尝试 1)，失败再回退 2)，
避免跨模块 isinstance 因双模块实例而失效。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PKG_ROOT = Path(__file__).resolve().parents[1]


def import_contract(name: str):
    """按统一顺序导入契约子模块（如 "cs_schema.models" 的 tail 写法 "models"）。

    参数是 cs_schema 内的子模块名（models/enums/constants），返回对应模块对象。
    """
    for path in (_REPO_ROOT, _PKG_ROOT):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    last_err: ImportError | None = None
    for modname in (f"chengshao.cs_schema.{name}", f"cs_schema.{name}"):
        try:
            return importlib.import_module(modname)
        except ImportError as err:  # 两种运行形态各试一次
            last_err = err
    raise last_err  # type: ignore[misc]


def schema_models():
    return import_contract("models")


def schema_enums():
    return import_contract("enums")


def schema_constants():
    return import_contract("constants")
