"""契约：itembank_v2 —— 题 schema v2（source / verification）字段完整性校验。

自封闭：全部夹具为字面 dict，不依赖 data/。只测公开 API 行为（错误消息子串/
全等、统计闭式、纯函数性），不测内部实现。
"""
import copy

from xuexing.itembank_v2 import (
    SCHEMA_VERSION,
    SOURCE_VALUES,
    validate_bank_v2,
    validate_item_v2,
    source_counts,
    verification_stats,
)


def _item(**over):
    base = {
        "id": "i1",
        "item_type": "fill",
        "stem": "s",
        "answer": "a",
        "kps": ["kp"],
        "difficulty": 0.5,
        "source": "original",
    }
    base.update(over)
    return base


def _verified(agents=("solver-a", "solver-b")):
    return {"agents": list(agents), "answers_agree": True}


# ---------- 常量 ----------


def test_schema_constants():
    assert SCHEMA_VERSION == 2
    assert SOURCE_VALUES == ("original", "adapted", "llm_generated")
    assert isinstance(SOURCE_VALUES, tuple)


# ---------- 合法输入零消息 ----------


def test_valid_original_without_verification_passes():
    assert validate_item_v2(_item()) == []
    assert validate_item_v2(_item(verification=None)) == []
    assert validate_item_v2(_item(verification=_verified())) == []


def test_valid_adapted_passes_with_source_ref():
    assert validate_item_v2(_item(source="adapted", source_ref="2022·某市中考第12题")) == []
    assert (
        validate_item_v2(_item(source="adapted", source_ref="人教版七上例1", verification=_verified()))
        == []
    )


def test_valid_llm_generated_with_full_record_passes():
    ok = _item(source="llm_generated", verification=_verified(agents=("gen-llm", "check-1", "check-2")))
    assert validate_item_v2(ok) == []


def test_extra_keys_ignored():
    assert validate_item_v2(_item(notes="审题备注", tags=["x"])) == []


# ---------- source 规则（V1）----------


def test_missing_source():
    assert validate_item_v2({}) == ["<no-id>: missing source"]
    assert validate_item_v2({"id": "i9", "stem": "s"}) == ["i9: missing source"]
    assert validate_item_v2(_item(source="")) == ["i1: missing source"]
    assert validate_item_v2(_item(source="   ")) == ["i1: missing source"]


def test_bad_source():
    assert validate_item_v2(_item(source=42)) == ["i1: bad source 42"]
    assert validate_item_v2(_item(source=None)) == ["i1: bad source None"]
    assert validate_item_v2(_item(source="scraped")) == ["i1: bad source 'scraped'"]
    assert validate_item_v2(_item(source=("original",))) == ["i1: bad source ('original',)"]


# ---------- source_ref 规则（V2）----------


def test_adapted_requires_non_empty_source_ref():
    expected = ["i1: adapted requires non-empty source_ref"]
    assert validate_item_v2(_item(source="adapted")) == expected
    assert validate_item_v2(_item(source="adapted", source_ref="")) == expected
    assert validate_item_v2(_item(source="adapted", source_ref="   ")) == expected
    assert validate_item_v2(_item(source="adapted", source_ref=42)) == expected
    assert validate_item_v2(_item(source="adapted", source_ref=None)) == expected


def test_source_ref_ignored_for_other_sources():
    assert validate_item_v2(_item(source_ref="随便记点什么")) == []
    assert validate_item_v2(_item(source="llm_generated", source_ref="x", verification=_verified())) == []


# ---------- verification 规则（V3）----------


def test_llm_generated_requires_verification():
    expected = ["i1: llm_generated requires verification"]
    assert validate_item_v2(_item(source="llm_generated")) == expected
    assert validate_item_v2(_item(source="llm_generated", verification=None)) == expected


def test_bad_verification_shape():
    assert validate_item_v2(_item(verification="yes")) == ["i1: bad verification 'yes'"]
    assert validate_item_v2(_item(verification=[])) == ["i1: bad verification []"]
    assert validate_item_v2(_item(verification=True)) == ["i1: bad verification True"]
    assert validate_item_v2(_item(verification=3.14)) == ["i1: bad verification 3.14"]


def test_agents_requirement():
    needs = "i1: verification needs >=2 agents"
    assert validate_item_v2(_item(verification={"answers_agree": True})) == [needs]
    assert validate_item_v2(_item(verification={"agents": [], "answers_agree": True})) == [needs]
    assert validate_item_v2(_item(verification={"agents": ["a"], "answers_agree": True})) == [needs]
    # 必须是 list（JSON 数组语义）；tuple 不算
    assert validate_item_v2(_item(verification={"agents": ("a", "b"), "answers_agree": True})) == [needs]
    assert validate_item_v2(_item(verification={"agents": "ab", "answers_agree": True})) == [needs]


def test_agent_element_rules():
    assert validate_item_v2(_item(verification={"agents": ["a", " b"], "answers_agree": True})) == [
        "i1: bad verification agent ' b'"
    ]
    assert validate_item_v2(_item(verification={"agents": ["a", 7], "answers_agree": True})) == [
        "i1: bad verification agent 7"
    ]
    assert validate_item_v2(_item(verification={"agents": ["a", ""], "answers_agree": True})) == [
        "i1: bad verification agent ''"
    ]
    # 多个坏元素按列表序逐条报
    assert validate_item_v2(_item(verification={"agents": [" x", 5], "answers_agree": True})) == [
        "i1: bad verification agent ' x'",
        "i1: bad verification agent 5",
    ]


def test_agent_duplicate_rules():
    assert validate_item_v2(_item(verification={"agents": ["a", "a"], "answers_agree": True})) == [
        "i1: duplicate verification agents"
    ]
    assert validate_item_v2(_item(verification={"agents": ["a", "b", "a"], "answers_agree": True})) == [
        "i1: duplicate verification agents"
    ]
    # 坏元素消息在前，重复消息在后
    assert validate_item_v2(_item(verification={"agents": ["a", "a", " b"], "answers_agree": True})) == [
        "i1: bad verification agent ' b'",
        "i1: duplicate verification agents",
    ]


def test_answers_agree_rules():
    assert validate_item_v2(_item(verification={"agents": ["a", "b"]})) == [
        "i1: verification missing answers_agree"
    ]
    assert validate_item_v2(_item(verification={"agents": ["a", "b"], "answers_agree": None})) == [
        "i1: bad answers_agree None"
    ]
    assert validate_item_v2(_item(verification={"agents": ["a", "b"], "answers_agree": 1})) == [
        "i1: bad answers_agree 1"
    ]
    assert validate_item_v2(_item(verification={"agents": ["a", "b"], "answers_agree": "yes"})) == [
        "i1: bad answers_agree 'yes'"
    ]
    assert validate_item_v2(_item(verification={"agents": ["a", "b"], "answers_agree": False})) == [
        "i1: verification not passed"
    ]


# ---------- 累积顺序 / 前缀 / 全函数 ----------


def test_rule_accumulation_order():
    assert validate_item_v2(_item(id="x", source="adapted", verification={})) == [
        "x: adapted requires non-empty source_ref",
        "x: verification needs >=2 agents",
        "x: verification missing answers_agree",
    ]
    assert validate_item_v2(
        _item(id="m", source="nope", verification={"agents": ["a", "a"], "answers_agree": False})
    ) == [
        "m: bad source 'nope'",
        "m: duplicate verification agents",
        "m: verification not passed",
    ]
    # source 缺失不连锁触发 llm/source_ref 规则（各规则独立评估实际值），但 V1 本身照报
    assert validate_item_v2({"id": "n", "verification": "no"}) == [
        "n: missing source",
        "n: bad verification 'no'",
    ]


def test_non_dict_items():
    for bad in (None, 42, "x", ["a"], True, 3.14):
        assert validate_item_v2(bad) == ["item is not a dict"]


def test_id_prefix_rendering():
    assert validate_item_v2({"source": "bogus"}) == ["<no-id>: bad source 'bogus'"]
    assert validate_item_v2({"id": None, "source": "bogus"}) == ["None: bad source 'bogus'"]
    assert validate_item_v2({"id": 42, "source": "bogus"}) == ["42: bad source 'bogus'"]
    # falsy id 照字面渲染（同冻结 itembank R1 探针风格）
    assert validate_item_v2({"id": "", "source": "bogus"}) == [": bad source 'bogus'"]


def test_never_raises_battery():
    nasty = [
        None,
        42,
        "s",
        [],
        {},
        {"source": {}},
        {"source": ["original"]},
        {"verification": []},
        {"verification": {"agents": ["a", {}]}},
        {"verification": {"agents": ["a", ["b"]]}},
        {"answers_agree": []},
        {"id": {"x": 1}, "source": 9.5, "verification": 3.14},
        {"id": "p", "source": "adapted", "source_ref": [], "verification": {"agents": "ab"}},
    ]
    for item in nasty:
        result = validate_item_v2(item)
        assert isinstance(result, list)
        assert all(isinstance(e, str) for e in result)


# ---------- bank 级 ----------


def test_bank_accumulates_in_input_order_without_dedup():
    b1 = _item(id="b1", source="")
    b2 = _item(id="b2", source="scraped")
    ok = _item(id="ok")
    assert validate_bank_v2([b1, b2, ok]) == validate_item_v2(b1) + validate_item_v2(b2)
    # 不去重：同一坏题出现两次，消息重复两次
    twice = validate_bank_v2([b1, b1])
    assert twice == validate_item_v2(b1) * 2


def test_bank_empty_and_non_dict_elements():
    assert validate_bank_v2([]) == []
    assert validate_bank_v2([None, {"id": "z"}, 7]) == [
        "item is not a dict",
        "z: missing source",
        "item is not a dict",
    ]


# ---------- 统计 ----------


def test_source_counts_canonical_and_fresh():
    counts = source_counts([])
    assert counts == {"original": 0, "adapted": 0, "llm_generated": 0}
    assert list(counts) == list(SOURCE_VALUES)  # canonical 键序
    items = [
        _item(id="a"),
        _item(id="b", source="adapted", source_ref="r"),
        _item(id="c", source="llm_generated", verification=_verified()),
        _item(id="d", source="scraped"),  # 非法 source 不入桶
        "not-a-dict",  # 非 dict 不入桶
    ]
    assert source_counts(items) == {"original": 1, "adapted": 1, "llm_generated": 1}
    # 每次返回新 dict：修改返回值不影响后续调用
    mutable = source_counts(items)
    mutable["original"] = 999
    assert source_counts(items)["original"] == 1


def test_verification_stats_closed_form():
    items = [
        _item(id="a"),  # 未验证
        _item(id="b", verification=_verified()),  # 已验证
        _item(id="c", verification={"agents": ["a", "b"], "answers_agree": False}),  # 未通过
        _item(id="d", verification={"agents": ["a", "a"], "answers_agree": True}),  # 记录不完整
        _item(id="e", verification="no"),  # 形状坏
        "not-a-dict",  # 只进 total
    ]
    stats = verification_stats(items)
    assert isinstance(stats, tuple)
    assert stats == (6, 1)
    assert verification_stats([]) == (0, 0)
    assert verification_stats(items) == (6, 1)  # 同输入同输出


# ---------- 纯函数性 ----------


def test_purity_inputs_not_modified_and_repeatable():
    items = [
        _item(id="p1", source="adapted"),
        _item(id="p2", source="llm_generated", verification={"agents": ["a", " b"], "answers_agree": 1}),
        _item(id="p3"),
    ]
    snapshot = copy.deepcopy(items)
    first = validate_bank_v2(items)
    # source_counts 只按声明的 source 值计数（记录不完整由校验器报错，不影响计数）
    assert source_counts(items) == {"original": 1, "adapted": 1, "llm_generated": 1}
    assert verification_stats(items) == (3, 0)
    assert items == snapshot  # 入参不被修改
    assert validate_bank_v2(items) == first  # 两次调用同输出
