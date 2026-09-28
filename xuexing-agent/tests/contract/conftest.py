"""契约测试环境：默认测参考实现；设置 XX_IMPL_DIR 后测重生成实例。

注入规则：XX_IMPL_DIR 目录下 <module>.py 会被装载并顶替 sys.modules["xuexing.<module>"]。
重生成实现必须：单文件、只 import 标准库 + xuexing.types（绝对导入）、暴露模块全部公开 API。
"""
import importlib.util
import os
import sys

MODULES = ["kpgraph", "itembank", "diagnosis", "paper", "scheduler", "pedagogy", "route", "agent_shell"]

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


# ---------- 契约级夹具（刻意不依赖 data/ 夹具，保持契约自封闭） ----------
import pytest  # noqa: E402

from xuexing.itembank import ItemBank  # noqa: E402
from xuexing.kpgraph import KPGraph  # noqa: E402
from xuexing.types import Item, KnowledgePoint, Strategy  # noqa: E402


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
