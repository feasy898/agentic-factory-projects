"""契约：blueprint —— 诊断卷蓝图生成器（认知维度配比约束 + 覆盖约束）。

全部数值条款为手算可复核的闭式值（最大余数法 + 规范序破缺，实测于
CPython 3.12 x64）。graph 按鸭子类型（仅 has()）自封闭，不依赖 data/ 夹具；
唯一例外是 test_feeds_generate_paper（供 paper 组装的端到端可组装性）。
"""
import math
import random

import pytest

from xuexing.blueprint import (
    DEFAULT_RATIOS,
    DIFFICULTY_TARGET,
    DIMENSIONS,
    Blueprint,
    BlueprintError,
    build_blueprint,
)


class _Kp:
    def __init__(self, kp_id):
        self.name = f"节点-{kp_id}"


class _DuckGraph:
    """鸭子类型 graph：blueprint 只用 has()；get() 仅供 generate_paper 端到端。"""

    def __init__(self, ids):
        self._ids = set(ids)

    def has(self, kp_id):
        return kp_id in self._ids

    def get(self, kp_id):
        return _Kp(kp_id)


@pytest.fixture
def duck_graph():
    return _DuckGraph({"a", "b", "c", "d"})


IDS = ["a", "b", "c", "d"]


def _counts(bp):
    return bp.counts()


# ---------- 常量冻结 ----------

def test_frozen_constants():
    assert DIMENSIONS == ("记忆", "理解", "应用")
    assert DEFAULT_RATIOS == {"记忆": 0.4, "理解": 0.4, "应用": 0.2}
    assert DIFFICULTY_TARGET == {"记忆": 0.2, "理解": 0.5, "应用": 0.8}
    assert set(DIFFICULTY_TARGET) == set(DIMENSIONS)
    assert issubclass(BlueprintError, ValueError)


# ---------- 确定性与输入顺序无关 ----------

def test_determinism_and_order_independence(duck_graph):
    as_set = build_blueprint({"a", "b", "c", "d"}, 6, duck_graph)
    as_list = build_blueprint(["d", "c", "b", "a"], 6, duck_graph)
    as_dup_tuple = build_blueprint(("a", "a", "b", "c", "c", "d"), 6, duck_graph)
    assert as_set == as_list == as_dup_tuple
    # ratios 键序无关（规范化输出恒按规范维度序）
    r1 = build_blueprint(set(IDS), 6, duck_graph, {"记忆": 0.4, "理解": 0.4, "应用": 0.2})
    r2 = build_blueprint(set(IDS), 6, duck_graph, {"应用": 0.2, "记忆": 0.4, "理解": 0.4})
    assert r1 == r2
    assert list(r1.ratios) == ["记忆", "理解", "应用"]  # 规范维度序
    assert r1 == build_blueprint(set(IDS), 6, duck_graph)  # 与缺省配比等价


# ---------- 总量守恒 + 配比（最大余数容许集） ----------

def test_counts_partition_budget(duck_graph):
    bp = build_blueprint(set(IDS), 10, duck_graph)
    counts = _counts(bp)
    assert counts == {"a": 3, "b": 3, "c": 2, "d": 2}
    assert sum(counts.values()) == bp.budget == 10
    assert sum(bp.dimension_totals.values()) == 10
    assert bp.targets == ["a", "b", "c", "d"]
    assert bp.ratios == {"记忆": 0.4, "理解": 0.4, "应用": 0.2}  # 归一化后逐位等于字面值


def test_dimension_totals_largest_remainder(duck_graph):
    # N=10：配额恰为整数 4.0/4.0/2.0 -> T=(4,4,2)
    bp10 = build_blueprint(set(IDS), 10, duck_graph)
    assert bp10.dimension_totals == {"记忆": 4, "理解": 4, "应用": 2}
    assert bp10.allocation == {
        "a": {"记忆": 1, "理解": 1, "应用": 1},
        "b": {"记忆": 1, "理解": 1, "应用": 1},
        "c": {"记忆": 1, "理解": 1},
        "d": {"记忆": 1, "理解": 1},
    }
    # N=12：q=(4.800000000000001, 4.800000000000001, 2.4000000000000004)
    # floor=(4,4,2)，余 2 给余数最大的 记/理（二者逐位并列 -> 规范序破缺）-> T=(5,5,2)
    bp12 = build_blueprint(set(IDS), 12, duck_graph)
    assert bp12.dimension_totals == {"记忆": 5, "理解": 5, "应用": 2}
    for d, q in (("记忆", 12 * 0.4 / 1.0), ("理解", 12 * 0.4 / 1.0), ("应用", 12 * 0.2 / 1.0)):
        assert bp12.dimension_totals[d] in (math.floor(q), math.floor(q) + 1)
        assert abs(bp12.dimension_totals[d] - q) < 1.0


def test_ratio_property_sweep():
    # 3000 组随机 (K ∈ [1,8], N ∈ [K,60], 三类配比)：配比约束零违例 + 守恒 + 覆盖
    rng = random.Random(7)
    for _ in range(3000):
        k = rng.randint(1, 8)
        ids = [f"k{i:02d}" for i in range(k)]
        n = rng.randint(k, 60)
        style = rng.random()
        if style < 0.4:
            ratios = dict(DEFAULT_RATIOS)
        elif style < 0.7:
            ratios = {d: rng.randint(0, 4) for d in DIMENSIONS}
            if sum(ratios.values()) == 0:
                ratios["记忆"] = 1
        else:
            ratios = {rng.choice(DIMENSIONS): 1.0}
        bp = build_blueprint(ids, n, _DuckGraph(ids), ratios)
        s = sum(ratios.values())
        for d, w in ratios.items():
            if w <= 0:
                assert d not in bp.dimension_totals or bp.dimension_totals[d] == 0
                continue
            q = n * w / s
            t = bp.dimension_totals[d]
            assert t in (math.floor(q), math.floor(q) + 1)  # 最大余数容许集
            assert abs(t - q) < 1.0
        counts = bp.counts()
        assert sum(counts.values()) == n
        assert set(counts) == set(ids)
        assert all(v >= 1 for v in counts.values())  # 覆盖


# ---------- 覆盖约束（含修复语义） ----------

def test_full_coverage_at_minimum_budget(duck_graph):
    # budget == K：经覆盖修复后每个目标恰 1 题，维度合计仍按最大余数法
    bp = build_blueprint(set(IDS), 4, duck_graph)
    assert bp.dimension_totals == {"记忆": 2, "理解": 1, "应用": 1}
    assert bp.counts() == {"a": 1, "b": 1, "c": 1, "d": 1}
    assert bp.allocation == {
        "a": {"应用": 1}, "b": {"记忆": 1}, "c": {"记忆": 1}, "d": {"理解": 1},
    }


def test_coverage_repair_hand_cases(duck_graph):
    # N=6：T=(3,2,1)；理解/应用前缀全落在 a -> d 为零额 -> 从 a（合计最大、并列取最小 id）
    # 的最大维度（并列取规范序最前 = 记忆）移 1 题，同维移动 -> 维度合计不变
    bp = build_blueprint(set(IDS), 6, duck_graph)
    assert bp.dimension_totals == {"记忆": 3, "理解": 2, "应用": 1}
    assert bp.counts() == {"a": 2, "b": 2, "c": 1, "d": 1}
    assert bp.allocation == {
        "a": {"理解": 1, "应用": 1},
        "b": {"记忆": 1, "理解": 1},
        "c": {"记忆": 1},
        "d": {"记忆": 1},
    }


def test_equal_weight_tie_break(duck_graph):
    # 等权三方余数逐位并列 -> 规范维度序破缺：T=(2,2,1)；再经两次覆盖修复
    bp = build_blueprint(set(IDS), 5, duck_graph, {"记忆": 1, "理解": 1, "应用": 1})
    assert bp.dimension_totals == {"记忆": 2, "理解": 2, "应用": 1}
    assert bp.ratios == {"记忆": 1 / 3, "理解": 1 / 3, "应用": 1 / 3}
    assert bp.counts() == {"a": 1, "b": 2, "c": 1, "d": 1}
    assert bp.allocation == {
        "a": {"应用": 1},
        "b": {"记忆": 1, "理解": 1},
        "c": {"记忆": 1},
        "d": {"理解": 1},
    }


def test_single_kp(duck_graph):
    bp = build_blueprint({"a"}, 5, duck_graph)
    assert bp.targets == ["a"]
    assert bp.counts() == {"a": 5}
    assert bp.dimension_totals == {"记忆": 2, "理解": 2, "应用": 1}
    assert bp.allocation == {"a": {"记忆": 2, "理解": 2, "应用": 1}}


# ---------- 部分配比 / 零合计维度 / per_dimension ----------

def test_partial_ratios_restrict_dimensions(duck_graph):
    bp = build_blueprint(set(IDS), 7, duck_graph, {"理解": 0.6, "应用": 0.4})
    assert set(bp.ratios) == {"理解", "应用"}
    assert set(bp.dimension_totals) == {"理解", "应用"}
    assert bp.dimension_totals == {"理解": 4, "应用": 3}  # q=(4.2, 2.8)，余数大者 应用 +1
    assert bp.counts() == {"a": 2, "b": 2, "c": 2, "d": 1}
    flat = {d for cells in bp.allocation.values() for d in cells}
    assert flat == {"理解", "应用"}  # 全程无 记忆


def test_zero_total_dimension(duck_graph):
    # 正配比维度允许合计 0：dimension_totals 诚实保留键值 0，其余输出省略
    bp = build_blueprint({"a", "b"}, 2, duck_graph, {"理解": 0.999, "应用": 0.001})
    assert bp.dimension_totals == {"理解": 2, "应用": 0}
    assert bp.ratios == {"理解": 0.999, "应用": 0.001}
    assert bp.counts() == {"a": 1, "b": 1}
    assert bp.allocation == {"a": {"理解": 1}, "b": {"理解": 1}}
    assert bp.per_dimension() == [("理解", {"a": 1, "b": 1}, 0.5)]  # 零合计维度不出现


def test_per_dimension_partition(duck_graph):
    bp = build_blueprint(set(IDS), 10, duck_graph)
    per = bp.per_dimension()
    assert per == [
        ("记忆", {"a": 1, "b": 1, "c": 1, "d": 1}, 0.2),
        ("理解", {"a": 1, "b": 1, "c": 1, "d": 1}, 0.5),
        ("应用", {"a": 1, "b": 1}, 0.8),
    ]
    assert [dim for dim, _, _ in per] == ["记忆", "理解", "应用"]  # 规范维度序
    # sub-dict 划分 counts()
    for kp, total in bp.counts().items():
        assert sum(sub.get(kp, 0) for _, sub, _ in per) == total
    # sub-dict 是新容器，改动不影响蓝图
    per[0][1]["a"] = 99
    assert bp.counts()["a"] == 3


# ---------- 纯度与复制语义 ----------

def test_purity_and_copy_semantics(duck_graph):
    targets = ["d", "c", "b", "a"]
    ratios = {"记忆": 0.4, "理解": 0.4, "应用": 0.2}
    bp = build_blueprint(targets, 10, duck_graph, ratios)
    expected = build_blueprint(["d", "c", "b", "a"], 10, duck_graph, ratios)
    targets.append("zz")          # 调用方随后改自己的容器
    ratios["记忆"] = -5.0
    assert bp == expected         # 蓝图不受影响（不保留入参别名）
    counts = bp.counts()
    counts["a"] = 99
    counts["ghost"] = 1
    assert bp.counts() == {"a": 3, "b": 3, "c": 2, "d": 2}  # counts() 每次返回新 dict


# ---------- 校验完备性 ----------

def test_invalid_targets_rejected(duck_graph):
    for bad in ("abc", [], None, 42):
        with pytest.raises(BlueprintError):
            build_blueprint(bad, 1, duck_graph)
    for bad_elem in (["a", None], ["a", 3], ["a", ""]):
        with pytest.raises(BlueprintError):
            build_blueprint(bad_elem, 1, duck_graph)


def test_invalid_budget_rejected(duck_graph):
    for bad in (4.0, "5", True, None, 0, -1, 3):  # 3 < K=4：覆盖不可能
        with pytest.raises(BlueprintError):
            build_blueprint(set(IDS), bad, duck_graph)


def test_invalid_ratios_rejected(duck_graph):
    for bad in (
        [("记忆", 1)],          # 非 dict
        {"掌握": 1},             # 未知维度
        {"记忆": -0.1},          # 负
        {"记忆": float("nan")},  # NaN
        {"记忆": float("inf")},  # inf
        {"记忆": True},          # bool
        {"记忆": "0.5"},         # 数字字符串
        {},                      # 空 dict（Σ=0）
        {"记忆": 0, "理解": 0},  # 全零
    ):
        with pytest.raises(BlueprintError):
            build_blueprint(set(IDS), 10, duck_graph, bad)


def test_unknown_kp_rejected(duck_graph):
    with pytest.raises(BlueprintError):
        build_blueprint({"a", "ghost"}, 2, duck_graph)


# ---------- 供 generate_paper（端到端可组装性） ----------

def test_feeds_generate_paper(small_bank, duck_graph):
    # counts() 直接作 paper.generate_paper 的 blueprint（契约测试允许 import paper）
    from xuexing.paper import generate_paper

    bp = build_blueprint(set(IDS), 5, duck_graph)
    assert bp.counts() == {"a": 1, "b": 2, "c": 1, "d": 1}  # 夹具库存充足（a:3 b:2 c:1 d:2）
    paper = generate_paper(small_bank, duck_graph, bp.counts(), seed=3)
    assert len(paper.item_ids) == 5
    assert len(set(paper.item_ids)) == 5
    assert len(paper.sections) == 4
    for sec in paper.sections:
        assert len(sec["item_ids"]) == bp.counts()[sec["kp_id"]]
