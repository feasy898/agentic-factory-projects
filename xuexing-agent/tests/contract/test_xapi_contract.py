"""契约：xapi —— 学习事件导出为 xAPI statement JSON + 标准符合性校验。

全部数值条款为闭式可复核值（uuid5 派生 id / 整型时长格式化 / 扩展键序，实测于
CPython 3.12 x64）。夹具自封闭：用真实 types.Response/ReviewEntry/PlanStep/
LearningPlan 与鸭子类型桩，不依赖 data/ 夹具。标准符合性测试对产出的 statement
另做**独立**复核（本文件自带正则/解析，不信任模块自身的判定积木）。
"""
import copy
import json
import re
import uuid
from datetime import datetime

import pytest

from xuexing.types import LearningPlan, PlanStep, Response, ReviewEntry
from xuexing.xapi import (
    ACTIVITY_PREFIX,
    ACTOR_HOME_PAGE,
    EXT_DUE,
    EXT_EASE,
    EXT_INTERVAL_DAYS,
    EXT_RATIONALE,
    EXT_RECOMMENDED_ITEM_IDS,
    EXT_STRATEGY_ID,
    EXT_TARGET_MASTERY,
    EXTENSION_PREFIX,
    NAMESPACE_UUID,
    SCORE_TOLERANCE,
    VERBS,
    VERB_ANSWERED,
    VERB_PLAN_ASSIGNED,
    VERB_REVIEW_SCHEDULED,
    XAPI_VERSION,
    XAPIError,
    duration_iso,
    export_statements,
    is_iso8601_datetime,
    is_iso8601_duration,
    is_iri,
    is_lang_tag,
    is_uuid,
    make_activity,
    make_actor,
    make_verb,
    plan_statements,
    plan_step_statement,
    response_statement,
    review_entry_statement,
    statement_id,
    validate_statement,
)


# ---------- 自封闭小夹具 ----------

def _response(**kw):
    base = dict(item_id="q1", correct=True, learner_answer="B", response_ms=45200)
    base.update(kw)
    return Response(**base)


def _review(**kw):
    base = dict(kp_id="kp7", due="2026-10-02", interval_days=3, ease=2.5)
    base.update(kw)
    return ReviewEntry(**base)


def _step(**kw):
    base = dict(kp_id="kp3", strategy_id="s-drill", rationale="先序薄弱",
                target_mastery=0.85, recommended_item_ids=["i1", "i2"])
    base.update(kw)
    return PlanStep(**base)


_TS = "2026-09-29T12:17:00+00:00"


# ---------- 独立符合性复核（不使用模块自身的判定积木） ----------

_OWN_IRI_RE = re.compile(r"\A[A-Za-z][A-Za-z0-9+.\-]*:")
_OWN_LANG_RE = re.compile(r"\A[A-Za-z]{1,8}(-[A-Za-z0-9]{1,8})*\Z")
_OWN_DUR_RE = re.compile(
    r"\AP(?=[0-9T])(?:(?:[0-9]+[YMD])|(?:T(?:[0-9]+H)?(?:[0-9]+M)?"
    r"(?:[0-9]+(?:\.[0-9]+)?S)?))+\Z")


def _own_iri(v):
    return isinstance(v, str) and bool(_OWN_IRI_RE.match(v)) and not any(
        c.isspace() for c in v)


def _own_uuid(v):
    try:
        return str(uuid.UUID(v)) == v.lower()
    except (ValueError, TypeError):
        return False


def _conformance_recheck(stmt):
    """独立复核 xAPI MUST 子集；违规断言直接 assert（非空即测试失败）。"""
    assert _own_uuid(stmt["id"]), stmt["id"]
    actor = stmt["actor"]
    ifis = [k for k in ("mbox", "mbox_sha1sum", "openid", "account") if k in actor]
    assert len(ifis) == 1
    assert _own_iri(actor["account"]["homePage"])
    assert isinstance(actor["account"]["name"], str)
    assert _own_iri(stmt["verb"]["id"])
    assert isinstance(stmt["verb"]["display"], dict)
    for tag, text in stmt["verb"]["display"].items():
        assert _OWN_LANG_RE.match(tag) and isinstance(text, str)
    assert stmt["object"]["objectType"] == "Activity"
    assert _own_iri(stmt["object"]["id"])
    result = stmt["result"]
    if "success" in result:
        assert isinstance(result["success"], bool)
    if "score" in result:
        assert result["score"]["min"] <= result["score"]["max"]
        assert -1.0 <= result["score"]["scaled"] <= 1.0
    for k, v in result.get("extensions", {}).items():
        assert _own_iri(k), k
    if "timestamp" in stmt:
        assert isinstance(stmt["timestamp"], str)
        datetime.fromisoformat(stmt["timestamp"])
    assert stmt["version"] == "1.0.0"


# ---------- 常量冻结 ----------

def test_frozen_constants():
    assert XAPI_VERSION == "1.0.0"
    assert ACTIVITY_PREFIX == "https://xuexing.example.com/xapi/activity/"
    assert ACTOR_HOME_PAGE == "https://xuexing.example.com/learners/"
    assert NAMESPACE_UUID == "579bef2f-ca51-4a19-8b5d-ce167fe911fa"
    uuid.UUID(NAMESPACE_UUID)  # 可解析
    assert is_uuid(NAMESPACE_UUID)
    assert EXTENSION_PREFIX == "https://xuexing.example.com/xapi/extensions/"
    assert (EXT_DUE, EXT_EASE, EXT_INTERVAL_DAYS) == (
        EXTENSION_PREFIX + "due",
        EXTENSION_PREFIX + "ease",
        EXTENSION_PREFIX + "interval-days",
    )
    assert (EXT_RATIONALE, EXT_RECOMMENDED_ITEM_IDS, EXT_STRATEGY_ID,
            EXT_TARGET_MASTERY) == (
        EXTENSION_PREFIX + "rationale",
        EXTENSION_PREFIX + "recommended-item-ids",
        EXTENSION_PREFIX + "strategy-id",
        EXTENSION_PREFIX + "target-mastery",
    )
    for ext in (EXT_DUE, EXT_EASE, EXT_INTERVAL_DAYS, EXT_RATIONALE,
                EXT_RECOMMENDED_ITEM_IDS, EXT_STRATEGY_ID, EXT_TARGET_MASTERY):
        assert ext.startswith(EXTENSION_PREFIX) and is_iri(ext)
    assert SCORE_TOLERANCE == 1e-9
    assert issubclass(XAPIError, ValueError)


def test_verbs_table_frozen():
    assert VERBS == {
        "answered": {"id": "http://adlnet.gov/expapi/verbs/answered",
                     "display": {"zh-CN": "回答", "en-US": "answered"}},
        "review-scheduled": {
            "id": "https://xuexing.example.com/xapi/verbs/review-scheduled",
            "display": {"zh-CN": "已安排复习", "en-US": "review-scheduled"}},
        "plan-assigned": {
            "id": "https://xuexing.example.com/xapi/verbs/plan-assigned",
            "display": {"zh-CN": "已分配学习任务", "en-US": "plan-assigned"}},
    }
    assert set(VERBS) == {VERB_ANSWERED, VERB_REVIEW_SCHEDULED, VERB_PLAN_ASSIGNED}
    for entry in VERBS.values():
        assert is_iri(entry["id"])
        for tag in entry["display"]:
            assert is_lang_tag(tag)
    v = make_verb("answered")
    assert v == VERBS["answered"] and v is not VERBS["answered"]
    v["display"]["zh-CN"] = "篡改"          # 改返回拷贝
    v["id"] = "tampered"
    assert VERBS["answered"]["display"]["zh-CN"] == "回答"  # 表不被污染
    assert make_verb("answered")["id"] == "http://adlnet.gov/expapi/verbs/answered"
    with pytest.raises(XAPIError):
        make_verb("nope")


# ---------- 构件闭式 ----------

def test_make_actor_closed_form_and_guards():
    assert make_actor("stu-1") == {
        "objectType": "Agent",
        "account": {"homePage": ACTOR_HOME_PAGE, "name": "stu-1"},
    }
    a1 = make_actor("stu-1")
    a2 = make_actor("stu-1")
    assert a1 is not a2 and a1["account"] is not a2["account"]  # 新构造
    for bad in ("", "   ", None, 5):
        with pytest.raises(XAPIError):
            make_actor(bad)


def test_make_activity_closed_form_and_guards():
    assert make_activity("items/q1") == {
        "objectType": "Activity",
        "id": ACTIVITY_PREFIX + "items/q1",
    }
    assert make_activity("items/q1") is not make_activity("items/q1")
    for bad in ("", "   ", None, 5, "has space", "tab\there"):
        with pytest.raises(XAPIError):
            make_activity(bad)


def test_statement_id_uuid5_closed_form():
    ns = uuid.UUID(NAMESPACE_UUID)
    assert statement_id("stu-1", "answered", "items/q1", 0) == \
        str(uuid.uuid5(ns, "stu-1|answered|items/q1|0"))
    assert statement_id("stu-1", "answered", "items/q1", 0) == \
        "1ad1c8b8-5dad-5a3c-8ebb-e4a0baab4e57"  # 实测闭式
    assert statement_id("stu-1", "review-scheduled", "kps/kp7", 1) == \
        "b9c9beab-f031-5496-ac79-51bf2bfbb099"
    assert statement_id("stu-9", "plan-assigned", "kps/kp3", 0) == \
        "4dcf3f0e-e2bf-5cef-b8cb-839d61f9107e"
    # 同输入同 id；任一部分不同则 id 不同
    a = statement_id("stu-1", "answered", "items/q1", 0)
    assert a == statement_id("stu-1", "answered", "items/q1", 0)
    assert len({a,
                statement_id("stu-2", "answered", "items/q1", 0),
                statement_id("stu-1", "plan-assigned", "items/q1", 0),
                statement_id("stu-1", "answered", "items/q2", 0),
                statement_id("stu-1", "answered", "items/q1", 1)}) == 5
    for bad in (("", "answered", "k", 0), ("s", "", "k", 0), ("s", "answered", "", 0),
                ("s", "answered", "k", -1), ("s", "answered", "k", True),
                ("s", "answered", "k", 0.0), ("s", "answered", "k", None)):
        with pytest.raises(XAPIError):
            statement_id(*bad)


def test_duration_iso_closed_form():
    for ms, text in ((0, "PT0S"), (1, "PT0.001S"), (500, "PT0.5S"), (999, "PT0.999S"),
                     (1000, "PT1S"), (1234, "PT1.234S"), (45200, "PT45.2S"),
                     (60000, "PT60S"), (7200000, "PT7200S")):
        assert duration_iso(ms) == text, ms
    for bad in (-1, True, 1.5, "5", None):
        with pytest.raises(XAPIError):
            duration_iso(bad)


def test_predicate_predicates_closed_forms():
    assert is_iri("http://adlnet.gov/expapi/verbs/answered")
    assert is_iri("https://xuexing.example.com/xapi/activity/items/q1")
    for no in ("answered", "", "http://a b", "http://a\nb", 42, None):
        assert not is_iri(no), no
    assert is_lang_tag("zh-CN") and is_lang_tag("en-US") and is_lang_tag("e")
    for no in ("not a tag", "zh_CN", "", "回答", 42):
        assert not is_lang_tag(no), no
    assert is_iso8601_duration("PT0S") and is_iso8601_duration("PT45.2S")
    assert is_iso8601_duration("P1DT2H") and is_iso8601_duration("PT1234S")
    for no in ("PT", "P", "pt5s", "5 seconds", "PT1234 s", 42):
        assert not is_iso8601_duration(no), no
    assert is_iso8601_datetime("2026-09-29T12:17:00+00:00")
    assert is_iso8601_datetime("2026-09-29T12:17")
    for no in ("2026-09-29", "nope", "", 42, None):
        assert not is_iso8601_datetime(no), no
    assert is_uuid("1ad1c8b8-5dad-5a3c-8ebb-e4a0baab4e57")
    for no in ("abc", "1ad1c8b85dad5a3c8ebbe4a0baab4e57", "", 42, None):
        assert not is_uuid(no), no


# ---------- Response -> answered statement ----------

def test_response_statement_full_closed_form():
    stmt = response_statement(_response(), "stu-1", _TS, 0)
    assert stmt == {
        "id": "1ad1c8b8-5dad-5a3c-8ebb-e4a0baab4e57",
        "actor": {"objectType": "Agent",
                  "account": {"homePage": ACTOR_HOME_PAGE, "name": "stu-1"}},
        "verb": {"id": "http://adlnet.gov/expapi/verbs/answered",
                 "display": {"zh-CN": "回答", "en-US": "answered"}},
        "object": {"objectType": "Activity",
                   "id": ACTIVITY_PREFIX + "items/q1"},
        "result": {"response": "B", "duration": "PT45.2S",
                   "score": {"scaled": 1.0, "raw": 1, "min": 0, "max": 1},
                   "success": True},
        "timestamp": _TS,
        "version": "1.0.0",
    }
    assert list(stmt) == ["id", "actor", "verb", "object", "result",
                          "timestamp", "version"]  # 键构造顺序冻结
    assert list(stmt["result"]) == ["response", "duration", "score", "success"]
    assert validate_statement(stmt) == []


def test_response_statement_omits_absent_optionals_and_key_order():
    stmt = response_statement(_response(learner_answer=None, response_ms=None),
                              "stu-1")
    assert list(stmt) == ["id", "actor", "verb", "object", "result", "version"]
    assert list(stmt["result"]) == ["score", "success"]
    assert "response" not in stmt["result"] and "duration" not in stmt["result"]
    assert "timestamp" not in stmt
    assert stmt["result"]["score"] == {"scaled": 1.0, "raw": 1, "min": 0, "max": 1}
    assert validate_statement(stmt) == []


def test_response_statement_score_encodes_correctness():
    yes = response_statement(_response(correct=True), "s")
    no = response_statement(_response(correct=False), "s")
    assert yes["result"]["score"] == {"scaled": 1.0, "raw": 1, "min": 0, "max": 1}
    assert yes["result"]["success"] is True
    assert no["result"]["score"] == {"scaled": 0.0, "raw": 0, "min": 0, "max": 1}
    assert no["result"]["success"] is False
    assert isinstance(no["result"]["score"]["scaled"], float)
    assert isinstance(no["result"]["score"]["raw"], int)


def test_response_statement_timestamp_optional_but_validated():
    assert "timestamp" not in response_statement(_response(), "s")
    ts = "2026-09-29T08:00:00+08:00"
    assert response_statement(_response(), "s", ts)["timestamp"] == ts  # 原文透传
    for bad in ("2026-09-29", "nope", "", 42, True):  # None 是合法的「不出 timestamp」
        with pytest.raises(XAPIError):
            response_statement(_response(), "s", bad)


def test_response_statement_input_guards():
    for kwargs in (dict(item_id=""), dict(item_id=None), dict(item_id=5),
                   dict(correct=1), dict(correct=None),
                   dict(learner_answer=5),
                   dict(response_ms=-5), dict(response_ms=True),
                   dict(response_ms=1.5)):
        with pytest.raises(XAPIError):
            response_statement(_response(**kwargs), "s")
    with pytest.raises(XAPIError):
        response_statement(_response(), "")


def test_response_statement_sequence_enters_id():
    s0 = response_statement(_response(), "s")
    s1 = response_statement(_response(), "s", sequence=1)
    assert s0["id"] != s1["id"]
    assert s0["id"] == statement_id("s", "answered", "items/q1", 0)
    assert s1["id"] == statement_id("s", "answered", "items/q1", 1)


# ---------- ReviewEntry -> review-scheduled statement ----------

def test_review_entry_statement_closed_form():
    stmt = review_entry_statement(_review(), "stu-1", None, 1)
    assert stmt["id"] == "b9c9beab-f031-5496-ac79-51bf2bfbb099"
    assert stmt["verb"]["id"] == \
        "https://xuexing.example.com/xapi/verbs/review-scheduled"
    assert stmt["object"] == {"objectType": "Activity",
                              "id": ACTIVITY_PREFIX + "kps/kp7"}
    assert stmt["result"] == {"extensions": {
        EXT_DUE: "2026-10-02",
        EXT_EASE: 2.5,
        EXT_INTERVAL_DAYS: 3,
    }}
    assert list(stmt["result"]["extensions"]) == [EXT_DUE, EXT_EASE,
                                                  EXT_INTERVAL_DAYS]  # IRI 码点升序
    assert list(stmt) == ["id", "actor", "verb", "object", "result", "version"]
    assert validate_statement(stmt) == []


def test_review_entry_statement_ease_int_kept_and_due_original():
    stmt = review_entry_statement(_review(ease=3, due="2026-01-05"), "s")
    assert stmt["result"]["extensions"][EXT_EASE] == 3.0
    assert isinstance(stmt["result"]["extensions"][EXT_EASE], float)
    assert stmt["result"]["extensions"][EXT_DUE] == "2026-01-05"


def test_review_entry_input_guards():
    for kwargs in (dict(kp_id=""), dict(kp_id=None),
                   dict(due="not-a-date"), dict(due="2026-10-02T05:00:00"),
                   dict(due=None), dict(due=5),
                   dict(interval_days=-1), dict(interval_days=True),
                   dict(interval_days=None),
                   dict(ease=float("nan")), dict(ease=float("inf")),
                   dict(ease=True), dict(ease=None)):
        with pytest.raises(XAPIError):
            review_entry_statement(_review(**kwargs), "s")
    with pytest.raises(XAPIError):
        review_entry_statement(_review(), "")


# ---------- PlanStep -> plan-assigned statement ----------

def test_plan_step_statement_closed_form():
    stmt = plan_step_statement(
        _step(), "stu-9", "2026-09-29T08:00:00+08:00", 0)
    assert stmt == {
        "id": "4dcf3f0e-e2bf-5cef-b8cb-839d61f9107e",
        "actor": {"objectType": "Agent",
                  "account": {"homePage": ACTOR_HOME_PAGE, "name": "stu-9"}},
        "verb": {"id": "https://xuexing.example.com/xapi/verbs/plan-assigned",
                 "display": {"zh-CN": "已分配学习任务", "en-US": "plan-assigned"}},
        "object": {"objectType": "Activity",
                   "id": ACTIVITY_PREFIX + "kps/kp3"},
        "result": {"extensions": {
            EXT_RATIONALE: "先序薄弱",
            EXT_RECOMMENDED_ITEM_IDS: ["i1", "i2"],
            EXT_STRATEGY_ID: "s-drill",
            EXT_TARGET_MASTERY: 0.85,
        }},
        "timestamp": "2026-09-29T08:00:00+08:00",
        "version": "1.0.0",
    }
    assert list(stmt["result"]["extensions"]) == [
        EXT_RATIONALE, EXT_RECOMMENDED_ITEM_IDS, EXT_STRATEGY_ID,
        EXT_TARGET_MASTERY]  # IRI 码点升序
    assert validate_statement(stmt) == []


def test_plan_step_defaults_and_recommended_list_is_copy():
    ids = ["i1", "i2"]
    stmt = plan_step_statement(_step(recommended_item_ids=ids), "s")
    assert stmt["result"]["extensions"][EXT_RECOMMENDED_ITEM_IDS] == ["i1", "i2"]
    ids.append("i3")  # 改入参列表
    assert stmt["result"]["extensions"][EXT_RECOMMENDED_ITEM_IDS] == ["i1", "i2"]
    empty = plan_step_statement(
        _step(rationale="", recommended_item_ids=[]), "s")
    assert empty["result"]["extensions"][EXT_RATIONALE] == ""  # 空串原样入扩展
    assert empty["result"]["extensions"][EXT_RECOMMENDED_ITEM_IDS] == []


def test_plan_step_input_guards():
    for kwargs in (dict(kp_id=""), dict(kp_id=None),
                   dict(strategy_id=""), dict(strategy_id=None),
                   dict(rationale=None), dict(rationale=5),
                   dict(target_mastery=1.5), dict(target_mastery=-0.1),
                   dict(target_mastery=float("nan")), dict(target_mastery=True),
                   dict(target_mastery=None),
                   dict(recommended_item_ids="i1"),
                   dict(recommended_item_ids=["ok", ""])):
        with pytest.raises(XAPIError):
            plan_step_statement(_step(**kwargs), "s")
    # recommended_item_ids 属性缺省按 []
    class _Bare:
        kp_id = "kp1"
        strategy_id = "s1"
        rationale = ""
        target_mastery = 0.8

    stmt = plan_step_statement(_Bare(), "s")
    assert stmt["result"]["extensions"][EXT_RECOMMENDED_ITEM_IDS] == []
    assert validate_statement(stmt) == []


# ---------- 批量导出 ----------

def test_export_statements_order_and_sequence():
    records = [_response(), _review(),
               _step(), _response(item_id="q2", learner_answer=None,
                                  response_ms=None)]
    out = export_statements(records, "stu-1", _TS)
    assert [s["verb"]["id"].rsplit("/", 1)[-1] for s in out] == \
        ["answered", "review-scheduled", "plan-assigned", "answered"]
    assert [s["id"] for s in out] == [
        statement_id("stu-1", "answered", "items/q1", 0),
        statement_id("stu-1", "review-scheduled", "kps/kp7", 1),
        statement_id("stu-1", "plan-assigned", "kps/kp3", 2),
        statement_id("stu-1", "answered", "items/q2", 3),
    ]
    assert all(validate_statement(s) == [] for s in out)
    assert all(_own_iri(s["object"]["id"]) for s in out)


def test_export_statements_unknown_record_and_container():
    class _Ghost:
        pass

    with pytest.raises(XAPIError) as ei:
        export_statements([_response(), _Ghost()], "s")
    assert "1" in str(ei.value)  # 报错消息含位置下标
    for bad in (None, 42, "records", {"a": 1}, _response()):
        with pytest.raises(XAPIError):
            export_statements(bad, "s")
    with pytest.raises(XAPIError):
        export_statements([_response()], "")


def test_plan_statements_steps_before_reviews_closed_form():
    plan = LearningPlan(learner_id="stu-9",
                        steps=[_step(), _step(kp_id="kp4")],
                        reviews=[_review()])
    out = plan_statements(plan, _TS)
    assert [s["verb"]["id"].rsplit("/", 1)[-1] for s in out] == \
        ["plan-assigned", "plan-assigned", "review-scheduled"]
    assert [s["id"] for s in out] == [
        statement_id("stu-9", "plan-assigned", "kps/kp3", 0),
        statement_id("stu-9", "plan-assigned", "kps/kp4", 1),
        statement_id("stu-9", "review-scheduled", "kps/kp7", 2),
    ]
    assert out[2]["id"] == str(uuid.uuid5(uuid.UUID(NAMESPACE_UUID),
                                          "stu-9|review-scheduled|kps/kp7|2"))
    # 单步 plan 的实测闭式（probe：steps=1 -> review sequence=1）
    one_step = plan_statements(LearningPlan(learner_id="stu-9", steps=[_step()],
                                            reviews=[_review()]), _TS)
    assert one_step[1]["id"] == "509234c9-6db9-59b5-b24f-a447ba29955b"
    assert all(s["actor"]["account"]["name"] == "stu-9" for s in out)
    assert all(validate_statement(s) == [] for s in out)


def test_plan_statements_surface_guards():
    for kwargs in (dict(learner_id=""), dict(learner_id=None),
                   dict(steps="x"), dict(steps=None),
                   dict(reviews="x"), dict(reviews=None)):
        fields = dict(learner_id="s", steps=[], reviews=[])
        fields.update(kwargs)
        with pytest.raises(XAPIError):
            plan_statements(LearningPlan(**fields))


# ---------- 标准符合性（产出侧：模块校验 + 独立复核） ----------

def test_all_produced_statements_conformant():
    produced = [
        response_statement(_response(), "s1", _TS, 0),
        response_statement(_response(learner_answer=None, response_ms=None), "s1"),
        response_statement(_response(correct=False), "s1"),
        review_entry_statement(_review(), "s1", _TS, 0),
        review_entry_statement(_review(), "s1"),
        plan_step_statement(_step(), "s1", _TS, 0),
        plan_step_statement(_step(rationale="", recommended_item_ids=[]), "s1"),
        export_statements([_response(), _review(), _step()], "s1", _TS),
        plan_statements(LearningPlan(learner_id="s1", steps=[_step()],
                                     reviews=[_review()]), _TS),
    ]
    flat = []
    for item in produced:
        flat.extend(item if isinstance(item, list) else [item])
    assert len(flat) == 12
    for stmt in flat:
        assert validate_statement(stmt) == [], stmt
        _conformance_recheck(stmt)  # 独立复核
        json.dumps(stmt, ensure_ascii=False)  # 全量可序列化（含中文显示值）


# ---------- 标准符合性（校验器负向矩阵） ----------

def _base_stmt():
    return response_statement(_response(), "stu-1", _TS, 0)


def test_validate_non_dict_input_single_violation():
    for bad in (42, "x", None, [], 1.5):
        problems = validate_statement(bad)
        assert len(problems) == 1 and "dict" in problems[0], bad


def test_validate_missing_required_properties():
    for key in ("actor", "verb", "object"):
        stmt = _base_stmt()
        del stmt[key]
        assert validate_statement(stmt) != [], key


def test_validate_actor_ifi_matrix():
    def with_actor(agent):
        stmt = _base_stmt()
        stmt["actor"] = agent
        return validate_statement(stmt)

    good_account = {"homePage": ACTOR_HOME_PAGE, "name": "stu-1"}
    # 双 IFI -> 违规
    assert with_actor({"objectType": "Agent", "account": good_account,
                       "mbox": "mailto:a@b.c"}) != []
    # 零 IFI -> 违规
    assert with_actor({"objectType": "Agent"}) != []
    # 坏 homePage -> 违规
    assert with_actor({"objectType": "Agent",
                       "account": {"homePage": "not an iri",
                                   "name": "s"}}) != []
    assert with_actor({"objectType": "Agent",
                       "account": {"name": "s"}}) != []
    # 合法 mailbox 型 Agent -> 符合
    assert with_actor({"objectType": "Agent",
                       "mbox": "mailto:stu@example.com"}) == []
    # Group（恰一 IFI + member）-> 符合；member 非 list -> 违规
    assert with_actor({"objectType": "Group", "account": good_account,
                       "member": [{"objectType": "Agent",
                                   "account": good_account}]}) == []
    assert with_actor({"objectType": "Group", "account": good_account,
                       "member": "x"}) != []
    # 非法 objectType -> 违规
    assert with_actor({"objectType": "Robot", "account": good_account}) != []


def test_validate_verb_object_and_scalar_matrix():
    def violation(mutator):
        stmt = _base_stmt()
        mutator(stmt)
        return validate_statement(stmt)

    assert violation(lambda s: s["verb"].update(id="answered")) != []  # 相对引用
    assert violation(lambda s: s["verb"]["display"].update(**{"zh_CN": "x"})) != []
    assert violation(lambda s: s["verb"].update(display="answered")) != []
    assert violation(lambda s: s["object"].update(id="items/q1")) != []
    assert violation(lambda s: s["object"].update(id=None)) != []
    assert violation(lambda s: s.update(id="abc")) != []  # 非 UUID
    assert violation(lambda s: s.update(timestamp="2026-09-29")) != []
    assert violation(lambda s: s.update(version="0.9.0")) != []
    assert violation(lambda s: s.update(version=1.0)) != []
    assert violation(lambda s: s["result"].update(success=1)) != []
    assert violation(lambda s: s["result"].update(duration="5 seconds")) != []
    assert violation(lambda s: s["result"].update(response=7)) != []


def test_validate_score_matrix():
    def score_problems(score):
        stmt = _base_stmt()
        stmt["result"]["score"] = score
        return validate_statement(stmt)

    assert score_problems({"scaled": 1.0, "raw": 1, "min": 0, "max": 1}) == []
    assert score_problems({"scaled": 0.5, "raw": 2, "min": 0, "max": 4}) == []
    assert score_problems({"scaled": 0, "raw": 0, "min": 0, "max": 0}) == []  # max=min 不查一致性
    assert score_problems({"scaled": 1.5, "raw": 1, "min": 0, "max": 1}) != []
    assert score_problems({"scaled": -1.1, "raw": 0, "min": 0, "max": 1}) != []
    assert score_problems({"scaled": 1.0, "raw": 1, "min": 0, "max": 1, "x": 2}) != []
    assert score_problems({"scaled": True, "raw": 1, "min": 0, "max": 1}) != []
    assert score_problems({"scaled": float("nan")}) != []
    assert score_problems({"raw": 1, "min": 5, "max": 1}) != []  # min > max
    assert score_problems({"raw": 7, "min": 0, "max": 1}) != []  # raw 越界
    assert score_problems({"scaled": 0.5, "raw": 1, "min": 0, "max": 1}) != []  # 不一致
    assert score_problems("score") != []


def test_validate_extensions_and_context_matrix():
    def violation(mutator):
        stmt = _base_stmt()
        mutator(stmt)
        return validate_statement(stmt)

    assert violation(lambda s: s["result"].update(extensions={"interval": 3})) != []
    assert violation(lambda s: s["result"].update(
        extensions={EXT_INTERVAL_DAYS: 3})) == []
    assert violation(lambda s: s["result"].update(extensions=[1])) != []
    assert violation(lambda s: s.update(
        context={"extensions": {"not an iri": 1}})) != []
    assert violation(lambda s: s.update(
        context={"contextActivities": {"xyz": {"id": "http://a/b"}}})) != []
    assert violation(lambda s: s.update(
        context={"contextActivities": {
            "parent": {"id": "http://a/b"},
            "grouping": [{"id": "http://a/c"}]}})) == []
    assert violation(lambda s: s.update(
        context={"contextActivities": {"parent": {"id": "no-scheme"}}})) != []


def test_validate_statementref_and_agent_objects():
    stmt = _base_stmt()
    stmt["object"] = {"objectType": "StatementRef", "id": stmt["id"]}
    assert validate_statement(stmt) == []
    stmt["object"] = {"objectType": "StatementRef", "id": "abc"}
    assert validate_statement(stmt) != []
    stmt["object"] = {"objectType": "Agent",
                      "account": {"homePage": ACTOR_HOME_PAGE, "name": "t"}}
    assert validate_statement(stmt) == []
    stmt["object"] = {"objectType": "SubStatement"}
    assert validate_statement(stmt) != []
    # 带 definition 语言映射的 Activity
    stmt["object"] = {"objectType": "Activity", "id": ACTIVITY_PREFIX + "items/q1",
                      "definition": {"name": {"zh-CN": "题目"},
                                     "description": {"zh_CN": "坏标签"}}}
    assert len(validate_statement(stmt)) == 1


# ---------- 纯函数性 / 确定性 / JSON ----------

def test_purity_inputs_not_mutated():
    resp = _response()
    rev = _review()
    step = _step()
    plan = LearningPlan(learner_id="s", steps=[step], reviews=[rev])
    snap = copy.deepcopy((vars(resp), vars(rev), vars(step), vars(plan)))
    response_statement(resp, "s", _TS, 0)
    review_entry_statement(rev, "s", _TS, 0)
    plan_step_statement(step, "s", _TS, 0)
    plan_statements(plan, _TS)
    assert (vars(resp), vars(rev), vars(step), vars(plan)) == snap


def test_determinism_and_json_roundtrip():
    s1 = response_statement(_response(), "stu-1", _TS, 0)
    s2 = response_statement(_response(), "stu-1", _TS, 0)
    assert s1 == s2
    assert json.dumps(s1, ensure_ascii=False, sort_keys=True) == \
        json.dumps(s2, ensure_ascii=False, sort_keys=True)
    assert json.loads(json.dumps(s1, ensure_ascii=False)) == s1
    batch1 = plan_statements(LearningPlan(learner_id="s", steps=[_step()],
                                          reviews=[_review()]), _TS)
    batch2 = plan_statements(LearningPlan(learner_id="s", steps=[_step()],
                                          reviews=[_review()]), _TS)
    assert batch1 == batch2
    dumped = json.dumps(batch1, ensure_ascii=False)
    assert "已分配学习任务" in dumped and "已安排复习" in dumped  # 中文 display 保留
