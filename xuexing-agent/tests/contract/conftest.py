"""契约测试环境。

实现注入（XX_IMPL_DIR）已上移到 tests/conftest.py，对全部测试目录生效。
本文件只保留契约级夹具（刻意不依赖 data/ 夹具，保持契约自封闭）。
"""
import pytest

from xuexing.itembank import ItemBank
from xuexing.kpgraph import KPGraph
from xuexing.types import Item, KnowledgePoint, Strategy


@pytest.fixture
def small_graph():
    g = KPGraph()
    g.add_kp(KnowledgePoint(id="a", name="甲", subject="math", grade=7, cluster="c1"))
    g.add_kp(KnowledgePoint(id="b", name="乙", subject="math", grade=7, cluster="c1", prereqs=["a"]))
    g.add_kp(KnowledgePoint(id="c", name="丙", subject="math", grade=7, cluster="c2", prereqs=["b"]))
    g.add_kp(KnowledgePoint(id="d", name="丁", subject="math", grade=7, cluster="c2"))
    for kp in g.kps():
        for p in kp.prereqs:
            g.add_edge(p, kp.id)
    return g


@pytest.fixture
def small_bank():
    b = ItemBank()

    def add(item_id, kp, difficulty, item_type="fill", options=None, answer="ans", guess=None, kps=None):
        b.add(Item(
            id=item_id, item_type=item_type, stem=f"stem-{item_id}", answer=answer,
            kps=kps or [kp], difficulty=difficulty, options=options or [], guess=guess,
        ))

    add("a1", "a", 0.2)
    add("a2", "a", 0.5)
    add("a3", "a", 0.8)
    add("b1", "b", 0.3)
    add("b2", "b", 0.6)
    add("c1", "c", 0.4)
    add("d1", "d", 0.5, item_type="choice", options=["A. 1", "B. 2"], answer="B", guess=0.25)
    add("d2", "d", 0.5)
    return b
