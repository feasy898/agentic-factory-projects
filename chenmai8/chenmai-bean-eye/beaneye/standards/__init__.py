"""BeanEye · 标准引擎包（M9）。

YAML → 定级判定：三套标准配置（configs/standards/*.yaml）+ 一个配置驱动
引擎，**换标准 = 换 YAML，不改代码**。实现冻结契约
``beaneye.schemas.StandardEngine`` Protocol（``evaluate(beans, measurements)
-> GradingDecision``）。

导出用 PEP 562 惰性加载（与 beaneye.acquisition 同约定）。
"""

from typing import TYPE_CHECKING

__all__ = [
    "DEFAULT_STANDARDS_DIR",
    "StandardsError",
    "Standard",
    "GradeRule",
    "MetrologyCfg",
    "WeightCfg",
    "ClassInfo",
    "load_standard",
    "list_standards",
    "StandardEngineV1",
    "load_engine",
]

_LAZY = {
    "DEFAULT_STANDARDS_DIR": ("beaneye.standards.loader", "DEFAULT_STANDARDS_DIR"),
    "StandardsError": ("beaneye.standards.loader", "StandardsError"),
    "Standard": ("beaneye.standards.loader", "Standard"),
    "GradeRule": ("beaneye.standards.loader", "GradeRule"),
    "MetrologyCfg": ("beaneye.standards.loader", "MetrologyCfg"),
    "WeightCfg": ("beaneye.standards.loader", "WeightCfg"),
    "ClassInfo": ("beaneye.standards.loader", "ClassInfo"),
    "load_standard": ("beaneye.standards.loader", "load_standard"),
    "list_standards": ("beaneye.standards.loader", "list_standards"),
    "StandardEngineV1": ("beaneye.standards.engine", "StandardEngineV1"),
    "load_engine": ("beaneye.standards.engine", "load_engine"),
}


def __getattr__(name: str):
    if name in _LAZY:
        import importlib

        module, attr = _LAZY[name]
        return getattr(importlib.import_module(module), attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
