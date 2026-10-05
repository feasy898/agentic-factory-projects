"""M7 严重度裁决 eval：表驱动用例（并列/单面/normal vs 缺陷/临界序）
+ CQI 计数规则（一粒只计一次）。

运行（仓库根）::

    .venv/Scripts/python.exe -m pytest tests/test_severity.py -q
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import pytest
import yaml

from beaneye.schemas import (
    BeanMask,
    BeanObservation,
    PairedBean,
    defect_counts_from_beans,
)
from beaneye.severity import (
    CQI_COUNT_RULE,
    SeverityAdjudicator,
    SeverityError,
    SeverityOrder,
    adjudicate_pairs,
    count_defects,
    default_severity_order,
    effective_defect_counts,
    primary_secondary_counts,
    worst,
    worst_detail,
)
from beaneye.taxonomy import load_taxonomy

TAX = load_taxonomy()
# taxonomy 默认序位次（configs/taxonomy.yaml severity_order 下标）：
# normal=0 broken=1 faded=2 brocade=3 immature=4 peaberry=5 shell=6
# elephant=7 insect=8 dried=9 sour=10 mold=11 black=12
RANK = {k: TAX.severity_rank(k) for k in TAX.keys()}


# ---------------------------------------------------------------------------
# 确定性观测构造器（合成数据，不依赖任何真实豆图/数据集）
# ---------------------------------------------------------------------------

_SEQ = itertools.count(1)


def _mask(mid: str, side: str) -> BeanMask:
    return BeanMask(
        mask_id=mid,
        side=side,
        polygon=[[10.0, 20.0], [16.0, 20.0], [16.0, 26.0], [10.0, 26.0]],
        bbox_mm=(10.0, 20.0, 16.0, 26.0),
        area_mm2=36.0,
        centroid_mm=(13.0, 23.0),
        source="oracle",
        conf=1.0,
    )


def _obs(side: str, defect: str, conf: float) -> BeanObservation:
    """severity_rank 按taxonomy 默认序填写（模拟 M5 分类输出）。"""
    mid = f"{side}_{next(_SEQ):03d}"
    return BeanObservation(
        obs_id=mid,
        side=side,
        defect=defect,
        defect_conf=conf,
        severity_rank=RANK[defect],
        crop_path=f"out/crops/scan_severity/{mid}.png",
        mask=_mask(mid, side),
        color_lab=(132.6, 118.0, 148.0),  # lab8 标度（契约单一标度，W13）
        eq_diameter_mm=6.0,
    )


def _side(spec: tuple[str, float] | None, side: str) -> BeanObservation | None:
    return _obs(side, *spec) if spec is not None else None


def _bean(
    bean_id: str,
    top_spec: tuple[str, float] | None,
    bottom_spec: tuple[str, float] | None,
) -> PairedBean:
    top, bottom = _side(top_spec, "top"), _side(bottom_spec, "bottom")
    cost = 1.5 if (top is not None and bottom is not None) else -1.0
    (pb,) = adjudicate_pairs([(bean_id, top, bottom, cost)])
    return pb


# ---------------------------------------------------------------------------
# 表驱动用例（spec：≥15 用例，含并列/单面/normal vs 缺陷/临界序）
# fixture 覆盖类别：single_defect / multi_defect / critical_order 为验收必选项
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    top: tuple[str, float] | None
    bottom: tuple[str, float] | None
    final_defect: str
    worst_side: str
    final_rank: int


CASES: list[Case] = [
    Case("both_sides_absent", "empty", None, None, "normal", "none", 0),
    # 单缺陷（一面缺陷、另一面缺失）
    Case("single_defect_top_black", "single_defect", ("black", 0.90), None, "black", "top", 12),
    Case("single_defect_bottom_sour", "single_defect", None, ("sour", 0.85), "sour", "bottom", 10),
    Case("single_defect_bottom_peaberry", "single_defect", None, ("peaberry", 0.80), "peaberry", "bottom", 5),
    # 单面（只有一面观测，含 normal）
    Case("single_side_top_normal", "single_side", ("normal", 0.99), None, "normal", "top", 0),
    # normal vs 缺陷
    Case("normal_vs_defect_top_wins", "normal_vs_defect", ("black", 0.70), ("normal", 0.99), "black", "top", 12),
    Case("normal_vs_defect_bottom_wins", "normal_vs_defect", ("normal", 0.99), ("mold", 0.66), "mold", "bottom", 11),
    # 多缺陷（两面各一种缺陷，取最严重）
    Case("multi_black_beats_mold", "multi_defect", ("mold", 0.95), ("black", 0.80), "black", "bottom", 12),
    Case("multi_faded_beats_broken", "multi_defect", ("broken", 0.90), ("faded", 0.60), "faded", "bottom", 2),
    Case("multi_sour_beats_insect", "multi_defect", ("sour", 0.50), ("insect", 0.99), "sour", "top", 10),
    Case("multi_shell_beats_peaberry", "multi_defect", ("peaberry", 0.70), ("shell", 0.70), "shell", "bottom", 6),
    # 临界序（severity_order 相邻位次对，conf 不影响结果）
    Case("crit_dried_over_insect", "critical_order", ("insect", 0.80), ("dried", 0.80), "dried", "bottom", 9),
    Case("crit_sour_over_dried", "critical_order", ("dried", 0.80), ("sour", 0.75), "sour", "bottom", 10),
    Case("crit_black_over_mold", "critical_order", ("mold", 0.90), ("black", 0.50), "black", "bottom", 12),
    Case("crit_faded_over_broken", "critical_order", ("faded", 0.50), ("broken", 0.90), "faded", "top", 2),
    Case("crit_shell_over_peaberry", "critical_order", ("shell", 0.60), ("peaberry", 0.95), "shell", "top", 6),
    Case("crit_insect_over_elephant", "critical_order", ("elephant", 0.90), ("insect", 0.55), "insect", "bottom", 8),
    Case("crit_immature_over_brocade", "critical_order", ("brocade", 0.70), ("immature", 0.70), "immature", "bottom", 4),
    # 非缺陷类不参与「最严重缺陷」比较（W13 修复：peaberry 位次再高也不吞
    # 掉另一面的可计缺陷——"一面花豆、一面破碎"必须计破碎）
    Case("nondef_peaberry_vs_broken_top", "non_defect_vs_defect", ("peaberry", 0.95), ("broken", 0.60), "broken", "bottom", 1),
    Case("nondef_broken_vs_peaberry_bottom", "non_defect_vs_defect", ("broken", 0.60), ("peaberry", 0.95), "broken", "top", 1),
    Case("nondef_peaberry_vs_mold", "non_defect_vs_defect", ("peaberry", 0.99), ("mold", 0.30), "mold", "bottom", 11),
    # 两面皆非可计缺陷 → 退回全量比较，peaberry 标注不丢失
    Case("nondef_peaberry_annotation_single", "non_defect_annotation", None, ("peaberry", 0.80), "peaberry", "bottom", 5),
    Case("nondef_peaberry_vs_normal", "non_defect_annotation", ("peaberry", 0.80), ("normal", 0.99), "peaberry", "top", 5),
    Case("nondef_peaberry_both_tie_conf", "non_defect_annotation", ("peaberry", 0.70), ("peaberry", 0.90), "peaberry", "both", 5),
    # 并列（两面同缺陷同位次 → worst_side=both，取 conf 高者的缺陷）
    Case("tie_broken_bottom_conf", "tie", ("broken", 0.70), ("broken", 0.90), "broken", "both", 1),
    Case("tie_mold_equal_conf", "tie", ("mold", 0.80), ("mold", 0.80), "mold", "both", 11),
    Case("tie_black_top_conf", "tie", ("black", 0.91), ("black", 0.55), "black", "both", 12),
    Case("tie_normal_both", "tie", ("normal", 0.98), ("normal", 0.95), "normal", "both", 0),
]

REQUIRED_CATEGORIES = {
    "single_defect",  # 单缺陷
    "multi_defect",   # 多缺陷
    "critical_order", # 临界序
    "tie",
    "single_side",
    "normal_vs_defect",
    "non_defect_vs_defect",   # W13：非缺陷类不吞可计缺陷
    "non_defect_annotation",  # W13：peaberry 标注保留
}


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_worst_table(case: Case):
    """表驱动主用例：worst() 与 worst_detail() 的裁决逐项正确。"""
    top, bottom = _side(case.top, "top"), _side(case.bottom, "bottom")
    adj = SeverityAdjudicator()  # taxonomy 默认序
    assert adj.worst(top, bottom) == (case.final_defect, case.worst_side)
    d = adj.worst_detail(top, bottom)
    assert d.final_severity_rank == case.final_rank
    assert d.final_defect == case.final_defect
    assert d.worst_side == case.worst_side


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_adjudicate_pairs_matches_contract(case: Case):
    """默认序下 adjudicate_pairs 与契约入口 PairedBean.from_sides 完全一致。"""
    top, bottom = _side(case.top, "top"), _side(case.bottom, "bottom")
    cost = 1.5 if (top is not None and bottom is not None) else -1.0
    (pb,) = adjudicate_pairs([("b0001", top, bottom, cost)])
    ref = PairedBean.from_sides("b0001", top, bottom, cost)
    assert pb == ref


def test_case_table_meets_spec():
    """验收线：≥15 用例；fixture 覆盖单缺陷/多缺陷/临界序（及并列/单面/normal vs 缺陷）。"""
    assert len(CASES) >= 15
    assert len({c.id for c in CASES}) == len(CASES), "用例 id 必须唯一"
    cats = {c.category for c in CASES}
    assert REQUIRED_CATEGORIES <= cats, f"缺少覆盖类别: {REQUIRED_CATEGORIES - cats}"


# ---------------------------------------------------------------------------
# 平级细则：conf 高者胜，完全相等偏向 top（与契约 _resolve_worst 一致）
# ---------------------------------------------------------------------------


def test_tie_winner_conf_detail():
    top, bottom = _obs("top", "broken", 0.70), _obs("bottom", "broken", 0.90)
    d = worst_detail(top, bottom)
    assert (d.worst_side, d.tie, d.winner_side, d.winner_conf) == (
        "both",
        True,
        "bottom",
        0.90,
    )


def test_tie_equal_conf_prefers_top_like_contract():
    top, bottom = _obs("top", "mold", 0.80), _obs("bottom", "mold", 0.80)
    d = worst_detail(top, bottom)
    assert d.worst_side == "both" and d.tie and d.winner_side == "top"


def test_critical_pair_conf_cannot_flip_rank():
    """临界序：insect(8) vs dried(9)，conf 再悬殊也不改变位次裁决。"""
    top, bottom = _obs("top", "insect", 1.0), _obs("bottom", "dried", 0.05)
    assert worst(top, bottom) == ("dried", "bottom")


# ---------------------------------------------------------------------------
# severity_order 来源：taxonomy 默认序 / 标准 YAML 覆盖序
# ---------------------------------------------------------------------------


def test_default_severity_order_from_taxonomy():
    assert default_severity_order() == TAX.severity_order
    assert default_severity_order()[0] == "normal"


def test_adjudicator_rank_matches_taxonomy():
    adj = SeverityAdjudicator()
    assert adj.rank("normal") == 0
    assert adj.rank("black") == 12


def test_module_worst_accepts_explicit_order():
    """spec 签名 worst(top, bottom, severity_order)。"""
    top, bottom = _obs("top", "insect", 0.80), _obs("bottom", "dried", 0.80)
    assert worst(top, bottom, TAX.severity_order) == ("dried", "bottom")


# 自定义序：主缺陷段反排（black 最重 → broken 最重），用于验证序可换标准
CUSTOM_ORDER = [
    "normal", "black", "sour", "mold", "dried", "insect", "elephant",
    "shell", "peaberry", "immature", "brocade", "faded", "broken",
]


def test_custom_order_flips_decision():
    top, bottom = _obs("top", "faded", 0.90), _obs("bottom", "broken", 0.60)
    assert worst(top, bottom) == ("faded", "top")  # taxonomy 默认序：faded(2) > broken(1)
    assert worst(top, bottom, CUSTOM_ORDER) == ("broken", "bottom")  # 自定义序：broken(12) > faded(11)


def test_custom_order_rebase_keeps_contract_invariant():
    """自定义序下 rebase 观测位次后，PairedBean 契约不变式仍成立（构造即校验）。"""
    top, bottom = _obs("top", "faded", 0.90), _obs("bottom", "broken", 0.60)
    (pb,) = adjudicate_pairs([("b0009", top, bottom, 2.0)], CUSTOM_ORDER)
    assert (pb.final_defect, pb.worst_side, pb.final_severity_rank) == ("broken", "bottom", 12)
    assert pb.top.severity_rank == 11 and pb.bottom.severity_rank == 12


def test_from_standard_yaml(tmp_path):
    p = tmp_path / "std_test.yaml"
    p.write_text(
        yaml.safe_dump({"standard": "std_x", "severity_order": CUSTOM_ORDER}),
        encoding="utf-8",
    )
    so = SeverityOrder.from_standard_yaml(p)
    assert so.source == "standard:std_x"
    assert so.rank("black") == 1
    assert "peaberry" in so and len(so) == 13


def test_from_standard_yaml_missing_order(tmp_path):
    p = tmp_path / "std_bad.yaml"
    p.write_text(yaml.safe_dump({"standard": "std_bad"}), encoding="utf-8")
    with pytest.raises(SeverityError):
        SeverityOrder.from_standard_yaml(p)


def test_from_standard_yaml_partial_coverage_rejected(tmp_path):
    """标准 YAML 序必须覆盖 taxonomy 全部类别（缺 elephant → 拒绝）。"""
    p = tmp_path / "std_partial.yaml"
    p.write_text(
        yaml.safe_dump({"standard": "std_p", "severity_order": ["normal", "black"]}),
        encoding="utf-8",
    )
    with pytest.raises(SeverityError, match="不一致"):
        SeverityOrder.from_standard_yaml(p)


# ---------------------------------------------------------------------------
# 非法 severity_order / 未知类别 → SeverityError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "keys",
    [(), ("black", "normal"), ("normal", "black", "black")],
    ids=["empty", "not_normal_first", "duplicated"],
)
def test_bad_order_rejected(keys):
    with pytest.raises(SeverityError):
        SeverityOrder(keys)


def test_rank_unknown_key_rejected():
    with pytest.raises(SeverityError, match="不在 severity_order"):
        SeverityOrder(("normal", "black")).rank("mold")


def test_worst_with_defect_not_in_order_rejected():
    """观测缺陷不在（自定义部分）序中 → 明确报错，不得静默裁决。"""
    partial = ["normal", "black", "sour"]
    top, bottom = _obs("top", "shell", 0.9), None
    with pytest.raises(SeverityError):
        worst(top, bottom, partial)


# ---------------------------------------------------------------------------
# CQI 计数规则（count_rule: most_severe_per_bean，一粒只计一次）
# ---------------------------------------------------------------------------

BEANS: list[PairedBean] = [
    _bean("b0001", ("mold", 0.95), ("black", 0.80)),    # → black（主）
    _bean("b0002", ("broken", 0.70), ("broken", 0.90)), # → broken（次，并列取 conf 高）
    _bean("b0003", None, ("peaberry", 0.80)),           # → peaberry（计量不计缺陷）
    _bean("b0004", ("normal", 0.99), ("normal", 0.98)), # → normal
    _bean("b0005", ("sour", 0.85), ("normal", 0.90)),   # → sour（主）
]


def test_count_rule_constant():
    assert CQI_COUNT_RULE == "most_severe_per_bean"


def test_count_defects_one_bean_once():
    assert count_defects(BEANS) == {"black": 1, "broken": 1, "peaberry": 1, "sour": 1}


def test_count_defects_matches_contract():
    """独立实现与契约 defect_counts_from_beans 逐键一致（include_normal 两种口径）。"""
    for inc in (False, True):
        assert count_defects(BEANS, include_normal=inc) == defect_counts_from_beans(
            BEANS, include_normal=inc
        )


def test_multi_defect_bean_not_double_counted():
    """同一粒两面各有一种缺陷：只计入更严重一类，轻的那类不重复计。"""
    beans = [_bean(f"b{i:04d}", ("mold", 0.90), ("black", 0.90)) for i in range(3)]
    hist = count_defects(beans)
    assert hist == {"black": 3}
    assert "mold" not in hist


def test_effective_counts_drop_peaberry():
    """peaberry 计量不计缺陷（counts_as_defect=false）。"""
    assert effective_defect_counts(BEANS) == {"black": 1, "broken": 1, "sour": 1}


def test_peaberry_side_does_not_swallow_countable_defect():
    """「一面花豆、一面破碎」（W13 修复，评审 A 项）：peaberry 位次(5)高于
    broken(1)，修复前 final=peaberry 把破碎从计数里吞掉；修复后非缺陷类
    不参与比较 → final=broken，破碎计入次缺陷，peaberry 仅保留标注。"""
    beans = [_bean(f"b{i:04d}", ("peaberry", 0.95), ("broken", 0.60)) for i in range(3)]
    for b in beans:
        assert (b.final_defect, b.worst_side, b.final_severity_rank) == ("broken", "bottom", 1)
        assert b.top is not None and b.top.defect == "peaberry"  # 观测保留不丢
    assert count_defects(beans) == {"broken": 3}
    assert effective_defect_counts(beans) == {"broken": 3}
    assert primary_secondary_counts(beans) == (0, 3)  # 次缺陷不再被吞


def test_peaberry_annotation_kept_when_no_countable_defect():
    """两面皆非可计缺陷（peaberry/normal）：退回全量比较，标注不丢失。"""
    b = _bean("b0001", ("peaberry", 0.80), ("normal", 0.99))
    assert (b.final_defect, b.worst_side) == ("peaberry", "top")
    assert count_defects([b]) == {"peaberry": 1}
    assert effective_defect_counts([b]) == {}  # 不计缺陷
    assert primary_secondary_counts([b]) == (0, 0)


def test_primary_secondary_counts():
    assert primary_secondary_counts(BEANS) == (2, 1)  # 主: black+sour；次: broken（peaberry 不计）


def test_include_normal():
    hist = count_defects(BEANS, include_normal=True)
    assert hist["normal"] == 1 and hist["black"] == 1


def test_count_total_never_exceeds_bean_count():
    """一粒只计一次的结构性保证：缺陷粒数 ≤ 总粒数，normal 不进缺陷直方。"""
    hist = count_defects(BEANS)
    assert sum(hist.values()) <= len(BEANS)
    assert "normal" not in hist
