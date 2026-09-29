"""契约：standard_coverage —— 课标覆盖检查器（standard_ref × 课标主题清单对照）。

闭式值均为手算可复核（specs/drafts/standard_coverage.spec.md §3/§4 全部实测）：
夹具清单 topic_data 拍平序 = [t_lin, t_fun, t_tri, t_cir]（数与代数在图形与几何前，
t_lin/t_fun 同域但主题序不等）：
  ref "2022课标：能解一元一次方程"        -> ("t_lin",)
  ref "2022课标：理解一次函数前先学函数的概念" -> ("t_fun",)
  ref "2022课标：掌握全等三角形与内角和"   -> ("t_tri",)（全等+内角和同条目去重）
  ref "2022课标：圆与全等三角形内角和"     -> ("t_tri", "t_cir")（清单原序，非 ref 序）
  kp 库 [k1..k4]（k4 空 ref）-> covered={t_lin,t_fun,t_tri} uncovered=(t_cir,)
  unmatched=(k4,)；rate=3/4=0.75。
"""
import copy

import pytest

from xuexing.standard_coverage import (
    CoverageReport,
    KPMatch,
    StandardCoverageError,
    Topic,
    check_coverage,
    check_coverage_dicts,
    match_ref,
    parse_topics,
)
from xuexing.types import KnowledgePoint


# ---------- 自封闭夹具（不依赖 data/，清单与 KP 显式可控） ----------

@pytest.fixture
def topic_data():
    return {
        "domains": [
            {
                "domain": "数与代数",
                "themes": [
                    {"theme": "方程与不等式", "topics": [
                        {"id": "t_lin", "name": "一元一次方程", "requirement": "能解一元一次方程",
                         "aliases": ["一元一次方程", "列方程"]},
                    ]},
                    {"theme": "函数", "topics": [
                        {"id": "t_fun", "name": "函数", "requirement": "了解函数的概念",
                         "aliases": ["函数的概念"]},
                    ]},
                ],
            },
            {
                "domain": "图形与几何",
                "themes": [
                    {"theme": "图形的变化", "topics": [
                        {"id": "t_tri", "name": "三角形", "requirement": "全等与内角和",
                         "aliases": ["全等", "内角和"]},
                        {"id": "t_cir", "name": "圆", "requirement": "圆的有关概念",
                         "aliases": ["圆"]},
                    ]},
                ],
            },
        ]
    }


@pytest.fixture
def topics(topic_data):
    return parse_topics(topic_data)


def _kp(kp_id, ref):
    return KnowledgePoint(id=kp_id, name=kp_id, subject="math", grade=7,
                          cluster="c", standard_ref=ref)


@pytest.fixture
def kps():
    return [
        _kp("k1", "2022课标：能解一元一次方程"),
        _kp("k2", "2022课标：掌握全等三角形与内角和"),
        _kp("k3", "2022课标：理解一次函数前先学函数的概念"),
        _kp("k4", "  "),
    ]


# ---------- parse_topics：拍平 + 校验（I2/I3） ----------

def test_parse_topics_flatten_order_and_fields(topic_data):
    topics = parse_topics(topic_data)
    assert [t.id for t in topics] == ["t_lin", "t_fun", "t_tri", "t_cir"]
    assert topics[0].domain == "数与代数" and topics[0].theme == "方程与不等式"
    assert topics[3].domain == "图形与几何" and topics[3].theme == "图形的变化"
    assert topics[0].requirement == "能解一元一次方程"
    assert topics[0].aliases == ("一元一次方程", "列方程")  # list -> tuple
    assert all(isinstance(t.aliases, tuple) for t in topics)
    assert all(isinstance(t, Topic) for t in topics)


def test_parse_topics_pure_and_deterministic(topic_data):
    snapshot = copy.deepcopy(topic_data)
    first, second = parse_topics(topic_data), parse_topics(topic_data)
    assert first == second  # dataclass 逐字段相等
    assert topic_data == snapshot  # 不改输入


def test_parse_topics_rejections(topic_data):
    def bad(mutate):
        data = copy.deepcopy(topic_data)
        mutate(data)
        return data

    cases = [
        lambda d: d.update(domains=[]),                                # 空 domains
        lambda d: d.update(domains="x"),                               # 非 list
        lambda d: d["domains"][0].update(domain=""),                   # 空域名
        lambda d: d["domains"][0].update(themes=[]),                   # 空 themes
        lambda d: d["domains"][0]["themes"][0].update(theme=""),       # 空主题名
        lambda d: d["domains"][0]["themes"][0].update(topics=[]),      # 空 topics
        lambda d: d["domains"][0]["themes"][0]["topics"][0].update(id="t_fun"),  # id 跨条目重复
        lambda d: d["domains"][0]["themes"][0]["topics"][0].update(id=""),       # 空 id
        lambda d: d["domains"][0]["themes"][0]["topics"][0].update(name=""),     # 空 name
        lambda d: d["domains"][0]["themes"][0]["topics"][0].update(requirement=""),  # 空 requirement
        lambda d: d["domains"][0]["themes"][0]["topics"][0].update(aliases=[]),  # 空 aliases
        lambda d: d["domains"][0]["themes"][0]["topics"][0].update(aliases=[""]),  # 空串 alias
        lambda d: d["domains"][0]["themes"][0]["topics"][0].update(aliases=[" 一元一次方程"]),  # 首尾空白
        lambda d: d["domains"][0]["themes"][0]["topics"][0].update(aliases=["函数的概念"]),  # alias 跨条目重复
    ]
    for mutate in cases:
        with pytest.raises(StandardCoverageError):
            parse_topics(bad(mutate))
    for worse in ({}, {"domains": None}, "not-a-dict", None):
        with pytest.raises(StandardCoverageError):
            parse_topics(worse)
    assert issubclass(StandardCoverageError, ValueError)


# ---------- match_ref：子串命中 + 去重 + 清单原序（I1/I4） ----------

def test_match_ref_basic(topics):
    assert match_ref("2022课标：能解一元一次方程", topics) == ("t_lin",)
    assert match_ref("2022课标：理解一次函数前先学函数的概念", topics) == ("t_fun",)
    assert match_ref("2022课标：掌握全等三角形与内角和", topics) == ("t_tri",)
    assert match_ref("2022课标：能根据实际问题列方程", topics) == ("t_lin",)


def test_match_ref_dedup_and_topic_list_order(topics):
    # 同条目两个 alias 都命中 -> 去重为一条
    assert match_ref("2022课标：全等三角形内角和", topics) == ("t_tri",)
    # 多条目命中按清单原序，与 ref 中出现顺序无关（圆在 ref 前、t_tri 在清单前）
    assert match_ref("2022课标：圆与全等三角形内角和", topics) == ("t_tri", "t_cir")


def test_match_ref_alias_declaration_order_irrelevant(topic_data, topics):
    reordered = copy.deepcopy(topic_data)
    reordered["domains"][1]["themes"][0]["topics"][1]["aliases"].reverse()
    assert match_ref("2022课标：圆的切线与圆心角", parse_topics(reordered)) == \
        match_ref("2022课标：圆的切线与圆心角", topics) == ("t_cir",)


def test_match_ref_blank_and_type(topics):
    assert match_ref(None, topics) == ()
    assert match_ref("", topics) == ()
    assert match_ref("   ", topics) == ()
    assert match_ref("2022课标：超纲内容", topics) == ()
    with pytest.raises(StandardCoverageError):
        match_ref(123, topics)
    with pytest.raises(StandardCoverageError):
        match_ref("x", [])
    with pytest.raises(StandardCoverageError):
        match_ref("x", ())


# ---------- check_coverage：报告闭式 + 分划 + 纯度（I5/I6/I7） ----------

def test_check_coverage_closed_form(kps, topics):
    rep = check_coverage(kps, topics)
    assert isinstance(rep, CoverageReport)
    assert rep.matches == (
        KPMatch(kp_id="k1", topic_ids=("t_lin",)),
        KPMatch(kp_id="k2", topic_ids=("t_tri",)),
        KPMatch(kp_id="k3", topic_ids=("t_fun",)),
        KPMatch(kp_id="k4", topic_ids=()),
    )
    assert rep.uncovered_topic_ids == ("t_cir",)
    assert rep.unmatched_kp_ids == ("k4",)
    assert rep.matched_kp_ids == ("k1", "k2", "k3")
    assert rep.covered_topic_ids == ("t_lin", "t_fun", "t_tri")
    assert rep.topics == tuple(topics)
    assert rep.coverage_rate == 3 / 4
    assert rep.is_complete() is False


def test_check_coverage_kp_input_order(kps, topics):
    rep = check_coverage(list(reversed(kps)), topics)
    assert [m.kp_id for m in rep.matches] == ["k4", "k3", "k2", "k1"]
    assert rep.unmatched_kp_ids == ("k4",)          # 输入原序
    assert rep.matched_kp_ids == ("k3", "k2", "k1")


def test_coverage_partitions_and_rate(kps, topics):
    rep = check_coverage(kps, topics)
    assert set(rep.matched_kp_ids) | set(rep.unmatched_kp_ids) == {"k1", "k2", "k3", "k4"}
    assert not (set(rep.matched_kp_ids) & set(rep.unmatched_kp_ids))
    assert set(rep.covered_topic_ids) | set(rep.uncovered_topic_ids) == \
        {t.id for t in topics}
    assert not (set(rep.covered_topic_ids) & set(rep.uncovered_topic_ids))
    assert rep.coverage_rate == len(rep.covered_topic_ids) / len(rep.topics)


def test_check_coverage_complete(topics):
    mega = _kp("m1", "2022课标：一元一次方程、函数的概念、全等三角形内角和与圆")
    rep = check_coverage([mega], topics)
    assert rep.matches == (KPMatch(kp_id="m1", topic_ids=("t_lin", "t_fun", "t_tri", "t_cir")),)
    assert rep.uncovered_topic_ids == () and rep.unmatched_kp_ids == ()
    assert rep.coverage_rate == 1.0
    assert rep.is_complete() is True


def test_check_coverage_empty_kps(topics):
    rep = check_coverage([], topics)
    assert rep.matches == () and rep.unmatched_kp_ids == () and rep.matched_kp_ids == ()
    assert rep.uncovered_topic_ids == ("t_lin", "t_fun", "t_tri", "t_cir")
    assert rep.coverage_rate == 0.0
    assert rep.is_complete() is False


def test_check_coverage_duplicate_kp_id(topics):
    with pytest.raises(StandardCoverageError):
        check_coverage([_kp("d", "圆"), _kp("d", "全等")], topics)
    with pytest.raises(StandardCoverageError):
        check_coverage([_kp("e", ""), _kp(" ", "x")], topics)  # 空 id 同样拒绝


def test_check_coverage_empty_topics(kps):
    with pytest.raises(StandardCoverageError):
        check_coverage(kps, [])


def test_check_coverage_purity(kps, topics):
    snapshot = copy.deepcopy(kps)
    rep = check_coverage(kps, topics)
    assert kps == snapshot                      # 输入对象不被修改
    with pytest.raises(AttributeError):         # 报告字段是 tuple，改不动
        rep.uncovered_topic_ids.append("x")
    with pytest.raises(AttributeError):
        rep.matches[0].topic_ids.append("x")
    assert rep.matches[0] == KPMatch(kp_id="k1", topic_ids=("t_lin",))  # 未被上一句破坏


def test_check_coverage_none_ref_and_missing_attr(topics):
    assert check_coverage([_kp("n1", None)], topics).unmatched_kp_ids == ("n1",)

    class Bare:
        id = "b1"                               # 缺 standard_ref 属性

    with pytest.raises(AttributeError):
        check_coverage([Bare()], topics)


# ---------- check_coverage_dicts：入口等价 + 校验（I8） ----------

def test_dicts_entry_equivalence(kps, topics, topic_data):
    kp_dicts = [{"id": k.id, "standard_ref": k.standard_ref} for k in kps]
    rep_dicts = check_coverage_dicts(kp_dicts, topic_data)
    rep_objs = check_coverage(kps, topics)
    assert rep_dicts == rep_objs
    # standard_ref 键缺省视为空串 -> 未归属
    rep = check_coverage_dicts([{"id": "z1"}], topic_data)
    assert rep.unmatched_kp_ids == ("z1",) and rep.matches == (KPMatch("z1", ()),)


def test_dicts_entry_validation(topic_data):
    topics = parse_topics(topic_data)
    rep = check_coverage_dicts([], topic_data)  # 空 KP 库合法
    assert rep.uncovered_topic_ids == ("t_lin", "t_fun", "t_tri", "t_cir")
    with pytest.raises(StandardCoverageError):
        check_coverage_dicts(["not-a-dict"], topic_data)
    with pytest.raises(StandardCoverageError):
        check_coverage_dicts([{"standard_ref": "圆"}], topic_data)          # 缺 id
    with pytest.raises(StandardCoverageError):
        check_coverage_dicts([{"id": ""}], topic_data)                      # 空 id
    with pytest.raises(StandardCoverageError):
        check_coverage_dicts([{"id": "a", "standard_ref": 7}], topic_data)  # ref 非 str/None
    with pytest.raises(StandardCoverageError):
        check_coverage_dicts([{"id": "a"}, {"id": "a"}], topic_data)        # 重复 id
    with pytest.raises(StandardCoverageError):
        check_coverage_dicts([{"id": "a"}], {"domains": []})                # 清单非法
    assert len(topics) == 4  # 前置解析未被破坏


# ---------- 确定性（I9） ----------

def test_determinism(kps, topics, topic_data):
    assert check_coverage(kps, topics) == check_coverage(kps, topics)
    assert check_coverage_dicts([{"id": "k1", "standard_ref": "列方程"}], topic_data) == \
        check_coverage_dicts([{"id": "k1", "standard_ref": "列方程"}], topic_data)
