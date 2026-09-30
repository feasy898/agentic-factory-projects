"""测试根夹具。

1) sys.path 接入 src；
2) 重生成实例注入：设置 XX_IMPL_DIR（+可选 XX_MODULES）后，<impl_dir>/<module>.py
   会被装载并顶替 sys.modules["xuexing.<module>"]，全目录的测试（含 integration）都
   会打到重生成实现上；不设置则测参考实现。
"""
import importlib.util
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

MODULES = ["kpgraph", "itembank", "diagnosis", "paper", "scheduler", "pedagogy", "route", "agent_shell", "kt", "blueprint", "grading", "recommend", "standard_coverage", "misconception_coverage", "itembank_v2", "dual_verify", "paper_layout", "xapi", "omr_sheet", "multitenant", "mm_client", "mm_ingest"]

import xuexing  # noqa: F401,E402  先完整加载参考包，再做顶替

_impl_dir = os.environ.get("XX_IMPL_DIR", "")
if _impl_dir:
    for _name in os.environ.get("XX_MODULES", ",".join(MODULES)).split(","):
        _name = _name.strip()
        if not _name:
            continue
        _path = os.path.join(_impl_dir, f"{_name}.py")
        if not os.path.exists(_path):
            raise RuntimeError(f"impl file missing: {_path}")
        _spec = importlib.util.spec_from_file_location(f"_regen_{_name}", _path)
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules[f"xuexing.{_name}"] = _mod
        _spec.loader.exec_module(_mod)


from xuexing import load_itembank, load_kpgraph, load_strategies  # noqa: E402
from xuexing.types import Misconception  # noqa: E402


@pytest.fixture(scope="session")
def root():
    return ROOT


@pytest.fixture(scope="session")
def graph():
    return load_kpgraph(os.path.join(ROOT, "data", "knowledge", "math_grade7.json"))


@pytest.fixture(scope="session")
def bank():
    return load_itembank(os.path.join(ROOT, "data", "items", "math_grade7_items.json"))


@pytest.fixture(scope="session")
def strategies():
    return load_strategies(os.path.join(ROOT, "data", "pedagogy", "strategies.json"))


@pytest.fixture(scope="session")
def misconceptions():
    import json

    with open(os.path.join(ROOT, "data", "misconceptions", "math_misconceptions.json"), encoding="utf-8") as f:
        data = json.load(f)
    return [Misconception(**mc) for mc in data["misconceptions"]]
