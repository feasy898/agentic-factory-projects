import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

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
