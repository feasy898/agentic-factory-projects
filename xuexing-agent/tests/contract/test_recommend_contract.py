"""契约：recommend —— 知识点掌握 -> 母题推荐（误解标签针对性选题 + 计划步骤挂载）。

闭式值均为手算可复核（specs/drafts/recommend.spec.md §3/§4 全部实测）：
夹具 mc_bank 的 kp "a" 池（主知识点）：a_x(0.05, 标 mc_b1)、a_g2(0.1)、a_g1(0.5)
无 M 中标签 -> Tier 2 按 (difficulty, id) = [a_x, a_g2, a_g1]；
a_t2(0.3, 标 mc_a1)、a_t1(0.6, 标 mc_a2) -> Tier 1 = [a_t2, a_t1]；
全量 = ["a_t2", "a_t1", "a_x", "a_g2", "a_g1"]。
真实数据闭式（I9）：grade7 题库 kp_rational_add -> ["m7_010","m7_011","m7_012","m7_115"]。
"""
import dataclasses

import pytest

from xuexing.recommend import (
    RecommendError,
    Recommendation,
    attach_recommendations,
    recommend_for_kp,
    recommend_for_profile,
)
from xuexing.types import (
    Item,
    LearningPlan,
    Misconception,
    PlanStep,
    Profile,
    ReviewEntry,
    to_dict,
)


# ---------- 自封闭夹具（不依赖 data/，误解标签显式可控） ----------

@pytest.fixture
def mc_bank():
    from xuexing.itembank import ItemBank

    b = ItemBank()

    def add(item_id, kp, difficulty, mcs=(), kps=None):
        b.add(Item(
            id=item_id, item_type="fill", stem=f"stem-{item_id}", answer="ans",
            kps=kps or [kp], difficulty=difficulty, misconceptions=list(mcs),
        ))

    # kp "a"：难度乱序注册，验证 (difficulty, id) 排序重排
    add("a_g1", "a", 0.5)                 # 无标签 -> Tier 2
    add("a_t1", "a", 0.6, mcs=["mc_a2"])  # M 中标签 -> Tier 1（难度大）
    add("a_t2", "a", 0.3, mcs=["mc_a1"])  # M 中标签 -> Tier 1（难度小）
    add("a_g2", "a", 0.1)                 # 无标签 -> Tier 2
    add("a_x", "a", 0.05, mcs=["mc_b1"])  # 标签属于别的 kp -> 仍 Tier 2
    add("a_sec", "b", 0.02, kps=["b", "a"])  # a 只是次要 kp -> 永不入 a 的池
    add("b_g1", "b", 0.4)
    return b


@pytest.fixture
def mcs():
    return [
        Misconception(id="mc_a1", kp_id="a", description="d1", hint="h1", signature=["x"]),
        Misconception(id="mc_a2", kp_id="a", description="d2", hint="h2", signature=["y"]),
        Misconception(id="mc_b1", kp_id="b", description="d3", hint="h3", signature=["z"]),
    ]


def _profile(mastery, learner_id="u"):
    return Profile(learner_id=learner_id, mastery=dict(mastery),
                   evidence={k: 2 for k in mastery})


def _plan(steps_kps, learner_id="u2", created_at="2026-09-29"):
    steps = [PlanStep(kp_id=k, strategy_id="s_worked_example",
                      rationale=f"weak {k}", target_mastery=0.85)
             for k in steps_kps]
    return LearningPlan(learner_id=learner_id, steps=steps,
                        reviews=[ReviewEntry(kp_id="m", due="2026-10-01",
                                             interval_days=2, ease=2.5)],
                        created_at=created_at)


# ---------- recommend_for_kp：分层 + 排序 + 误解库语义 ----------

def test_tier_order_and_misconception_order_independence(mc_bank, mcs):
    expected = ["a_t2", "a_t1", "a_x", "a_g2", "a_g1"]
    assert recommend_for_kp("a", mc_bank, mcs) == expected
    # 确定性：两次调用逐位相等
    assert recommend_for_kp("a", mc_bank, mcs) == recommend_for_kp("a", mc_bank, mcs)
    # 误解库输入顺序无关：反转后输出逐位相等
    assert recommend_for_kp("a", mc_bank, list(reversed(mcs))) == expected


def test_foreign_tag_is_general(mc_bank, mcs):
    ids = recommend_for_kp("a", mc_bank, mcs)
    # a_x 带标签但标签属于 kp b：归 Tier 2，排在两个 Tier 1 之后
    assert ids.index("a_x") == 2
    assert ids[:2] == ["a_t2", "a_t1"]


def test_secondary_kp_never_recommended(mc_bank, mcs):
    # a_sec 把 a 列为次要 kp：不出现在 a 的推荐里
    assert "a_sec" not in recommend_for_kp("a", mc_bank, mcs)
    # 但它是 b 的主知识点题（无 M 中标签 -> Tier 2，difficulty 0.02 最小排头）
    assert recommend_for_kp("b", mc_bank, mcs) == ["a_sec", "b_g1"]


def test_unknown_kp_empty(mc_bank, mcs):
    assert recommend_for_kp("ghost", mc_bank, mcs) == []
    assert recommend_for_kp("ghost", mc_bank, None) == []


def test_empty_misconception_library_all_general(mc_bank):
    expected = ["a_x", "a_g2", "a_t2", "a_g1", "a_t1"]  # 全按 (difficulty, id)
    assert recommend_for_kp("a", mc_bank, []) == expected
    assert recommend_for_kp("a", mc_bank, None) == expected


def test_limit_semantics(mc_bank, mcs):
    full = ["a_t2", "a_t1", "a_x", "a_g2", "a_g1"]
    assert recommend_for_kp("a", mc_bank, mcs, limit=None) == full
    assert recommend_for_kp("a", mc_bank, mcs, limit=1) == ["a_t2"]
    assert recommend_for_kp("a", mc_bank, mcs, limit=2) == ["a_t2", "a_t1"]
    assert recommend_for_kp("a", mc_bank, mcs, limit=99) == full  # 超池长容忍


def test_output_independence(mc_bank, mcs):
    first = recommend_for_kp("a", mc_bank, mcs)
    first.reverse()
    first.append("junk")
    assert recommend_for_kp("a", mc_bank, mcs) == ["a_t2", "a_t1", "a_x", "a_g2", "a_g1"]


# ---------- recommend_for_profile：掌握度 -> 推荐 ----------

def test_weak_only_and_threshold_boundary(mc_bank, mcs):
    # c 恰等于阈值 -> 达标不推荐；ghost 图外/池空 -> 照常产出空推荐
    p = _profile({"a": 0.3, "b": 0.9, "c": 0.65, "ghost": 0.1})
    recs = recommend_for_profile(p, mc_bank, mcs, mastery_threshold=0.65)
    assert [(r.kp_id, r.item_ids) for r in recs] == [
        ("ghost", []),
        ("a", ["a_t2", "a_t1", "a_x", "a_g2", "a_g1"]),
    ]


def test_weakest_first_tie_by_kp_id(mc_bank, mcs):
    recs = recommend_for_profile(_profile({"b": 0.5, "a": 0.1}), mc_bank, mcs)
    assert [r.kp_id for r in recs] == ["a", "b"]  # 最弱优先
    recs = recommend_for_profile(_profile({"b": 0.2, "a": 0.2}), mc_bank, mcs)
    assert [r.kp_id for r in recs] == ["a", "b"]  # 平局按 kp_id 升序
    assert all(isinstance(r, Recommendation) for r in recs)


def test_profile_purity(mc_bank, mcs):
    p = _profile({"a": 0.3})
    before = dict(p.mastery)
    recs = recommend_for_profile(p, mc_bank, mcs)
    assert p.mastery == before
    recs.append(Recommendation(kp_id="junk", item_ids=[]))
    assert [r.kp_id for r in recommend_for_profile(p, mc_bank, mcs)] == ["a"]


# ---------- 校验错误 ----------

def test_validation_errors(mc_bank, mcs):
    p = _profile({"a": 0.3})
    for bad in (0, 1, 1.5, -0.1):
        with pytest.raises(RecommendError):
            recommend_for_profile(p, mc_bank, mcs, mastery_threshold=bad)
    for bad_limit in (0, -1, True, "3", 2.5):
        with pytest.raises(RecommendError):
            recommend_for_kp("a", mc_bank, mcs, limit=bad_limit)
        with pytest.raises(RecommendError):
            recommend_for_profile(p, mc_bank, mcs, limit=bad_limit)
    # 两参同错：threshold 先查（异常类型断言，不依赖消息文本）
    with pytest.raises(RecommendError):
        recommend_for_profile(p, mc_bank, mcs, mastery_threshold=2.0, limit=0)
    assert issubclass(RecommendError, ValueError)


# ---------- attach_recommendations：计划步骤挂载 ----------

def test_attach_fills_steps_without_mutating_input(mc_bank, mcs):
    plan = _plan(["a", "b"])
    attached = attach_recommendations(plan, mc_bank, mcs)
    by_kp = {s.kp_id: s.recommended_item_ids for s in attached.steps}
    assert by_kp["a"] == ["a_t2", "a_t1", "a_x", "a_g2", "a_g1"]
    assert by_kp["b"] == ["a_sec", "b_g1"]
    assert by_kp["a"] == recommend_for_kp("a", mc_bank, mcs)
    # 原 plan 不被修改：步骤仍为构造时的空推荐
    assert all(s.recommended_item_ids == [] for s in plan.steps)


def test_attach_preserves_fields(mc_bank, mcs):
    plan = _plan(["a", "ghost"])
    attached = attach_recommendations(plan, mc_bank, mcs)
    assert attached.learner_id == plan.learner_id == "u2"
    assert attached.created_at == plan.created_at == "2026-09-29"
    for new, old in zip(attached.steps, plan.steps):
        assert (new.kp_id, new.strategy_id, new.rationale, new.target_mastery) == \
               (old.kp_id, old.strategy_id, old.rationale, old.target_mastery)
    assert attached.reviews == plan.reviews
    assert {r.kp_id for r in attached.reviews} == {"m"}
    # 池空的步骤诚实给空列表；容器是新列表（不别名共享）
    assert next(s for s in attached.steps if s.kp_id == "ghost").recommended_item_ids == []
    attached.steps.append(PlanStep(kp_id="junk", strategy_id="s"))
    attached.reviews.append(ReviewEntry(kp_id="junk", due="d", interval_days=1, ease=2.5))
    assert len(plan.steps) == 2 and len(plan.reviews) == 1


def test_attach_limit_passthrough_and_duplicate_kp(mc_bank, mcs):
    plan = _plan(["a", "a"])
    attached = attach_recommendations(plan, mc_bank, mcs, limit=1)
    assert all(s.recommended_item_ids == ["a_t2"] for s in attached.steps)
    with pytest.raises(RecommendError):
        attach_recommendations(plan, mc_bank, mcs, limit=0)


# ---------- 可组装性：真实数据 route 编排闭环（I9 闭式） ----------

def test_composable_with_route_plan(bank, graph, strategies, misconceptions):
    from datetime import date

    from xuexing.diagnosis import diagnose
    from xuexing.route import build_plan
    from xuexing.types import Response

    today = date(2026, 9, 28)
    rs = [Response(it.id, it.kps[0] != "kp_rational_add") for it in bank.items()]
    profile = diagnose(rs, bank, graph, learner_id="u")
    plan = build_plan(profile, bank, graph, strategies, today)
    weak = {k for k, m in profile.mastery.items() if m < 0.65}
    assert weak  # 路线确有薄弱步骤
    assert {s.kp_id for s in plan.steps} == weak
    attached = attach_recommendations(plan, bank, misconceptions)
    step = next(s for s in attached.steps if s.kp_id == "kp_rational_add")
    # 真实闭式：mc_sign_neg 针对题（均难度 0.2，id 升序）在前，一般巩固在后
    assert step.recommended_item_ids == ["m7_010", "m7_011", "m7_012", "m7_115"]
    # 原 plan 步骤仍为空推荐（attach 是独立纯步骤）
    assert all(s.recommended_item_ids == [] for s in plan.steps)


# ---------- types.PlanStep 扩展兼容（I11） ----------

def test_planstep_field_default():
    bare = PlanStep(kp_id="a", strategy_id="s")
    explicit = PlanStep(kp_id="a", strategy_id="s", rationale="", target_mastery=0.85,
                        recommended_item_ids=[])
    assert bare.recommended_item_ids == []
    assert bare == explicit  # 缺省与显式空列表 dataclass 相等
    assert to_dict(bare)["recommended_item_ids"] == []
    names = {f.name for f in dataclasses.fields(PlanStep)}
    assert names == {"kp_id", "strategy_id", "rationale", "target_mastery",
                     "recommended_item_ids"}
