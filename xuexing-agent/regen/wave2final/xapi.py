"""xapi —— 学习事件导出为 xAPI 1.0.3 statement JSON + 标准符合性校验（重生成 v0.2.0）。

按冻结契约 specs/frozen/xapi.spec.md 从零实现：
- Response/ReviewEntry/PlanStep 三类学习事件 → xAPI statement JSON；
- validate_statement：xAPI 数据 API「离线可检验 MUST 子集」符合性校验器。

纯函数：无 IO、无随机、无时钟、不读环境；statement id 由 uuid5（冻结命名空间）
派生，timestamp 只来自调用方入参。鸭子类型参数表面：仅 getattr 读取，禁止
isinstance 具体类；本模块不 import 任何 xuexing 模块。不使用
from __future__ import annotations（注入装载环境约定）。
"""
import math
import re
import uuid
from datetime import date, datetime

# ---------- §3.1 常量（冻结） ----------

XAPI_VERSION = "1.0.0"
ACTIVITY_PREFIX = "https://xuexing.example.com/xapi/activity/"
ACTOR_HOME_PAGE = "https://xuexing.example.com/learners/"
NAMESPACE_UUID = "579bef2f-ca51-4a19-8b5d-ce167fe911fa"
EXTENSION_PREFIX = "https://xuexing.example.com/xapi/extensions/"
EXT_DUE = EXTENSION_PREFIX + "due"
EXT_EASE = EXTENSION_PREFIX + "ease"
EXT_INTERVAL_DAYS = EXTENSION_PREFIX + "interval-days"
EXT_RATIONALE = EXTENSION_PREFIX + "rationale"
EXT_RECOMMENDED_ITEM_IDS = EXTENSION_PREFIX + "recommended-item-ids"
EXT_STRATEGY_ID = EXTENSION_PREFIX + "strategy-id"
EXT_TARGET_MASTERY = EXTENSION_PREFIX + "target-mastery"
VERB_ANSWERED = "answered"
VERB_REVIEW_SCHEDULED = "review-scheduled"
VERB_PLAN_ASSIGNED = "plan-assigned"
SCORE_TOLERANCE = 1e-9
VERBS = {
    "answered": {"id": "http://adlnet.gov/expapi/verbs/answered",
                 "display": {"zh-CN": "回答", "en-US": "answered"}},
    "review-scheduled": {
        "id": "https://xuexing.example.com/xapi/verbs/review-scheduled",
        "display": {"zh-CN": "已安排复习", "en-US": "review-scheduled"}},
    "plan-assigned": {
        "id": "https://xuexing.example.com/xapi/verbs/plan-assigned",
        "display": {"zh-CN": "已分配学习任务", "en-US": "plan-assigned"}},
}


class XAPIError(ValueError):
    """本模块唯一异常类型。"""


# ---------- 判定积木（闭式，§3.2） ----------

_SCHEME_RE = re.compile(r"\A[A-Za-z][A-Za-z0-9+.\-]*:")
_LANG_TAG_RE = re.compile(r"\A[A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*\Z")
_ISO_DURATION_RE = re.compile(
    r"\AP(?=(?:[0-9]|T[0-9]))(?:[0-9]+Y)?(?:[0-9]+M)?(?:[0-9]+D)?"
    r"(?:T(?=[0-9])(?:[0-9]+H)?(?:[0-9]+M)?(?:[0-9]+(?:\.[0-9]+)?S)?)?\Z")
_UUID_RE = re.compile(r"\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                      r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z")
_VERSION_RE = re.compile(r"\A1\.0\.[0-9]+\Z")
_SHA1_RE = re.compile(r"\A[0-9a-fA-F]{40}\Z")


def is_iri(v):
    if not isinstance(v, str) or not v or not _SCHEME_RE.match(v):
        return False
    for c in v:
        if c.isspace() or ord(c) < 0x20 or ord(c) == 0x7F:
            return False
    return True


def is_lang_tag(v):
    return isinstance(v, str) and bool(_LANG_TAG_RE.match(v))


def is_iso8601_duration(v):
    return isinstance(v, str) and bool(_ISO_DURATION_RE.match(v))


def is_iso8601_datetime(v):
    if not isinstance(v, str) or "T" not in v:
        return False
    try:
        datetime.fromisoformat(v)
    except ValueError:
        return False
    return True


def is_uuid(v):
    return isinstance(v, str) and bool(_UUID_RE.match(v))


# ---------- 内部守卫（校验清单 §3.5/§3.6；失败一律 XAPIError） ----------

_MISSING = object()


def _require_id(value, field):
    """id 类守卫：str 且 strip 后非空。"""
    if not isinstance(value, str) or not value.strip():
        raise XAPIError("%s must be a non-empty str" % field)
    return value


def _require_no_whitespace(value, field):
    for c in value:
        if c.isspace():
            raise XAPIError("%s must not contain whitespace" % field)
    return value


def _require_int(value, field, minimum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise XAPIError("%s must be int" % field)
    if value < minimum:
        raise XAPIError("%s must be >= %d" % (field, minimum))
    return value


def _require_finite_real(value, field):
    # int 恒有限；float 用 isfinite（bool 先拒）。
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (
            isinstance(value, float) and not math.isfinite(value)):
        raise XAPIError("%s must be a finite real number" % field)
    return value


def _require_timestamp(timestamp):
    if timestamp is not None and not is_iso8601_datetime(timestamp):
        raise XAPIError(
            "timestamp must be an ISO 8601 datetime str or None, got %r"
            % (timestamp,))
    return timestamp


# ---------- §3.3 duration_iso ----------

def duration_iso(ms):
    if isinstance(ms, bool) or not isinstance(ms, int):
        raise XAPIError("ms must be int, got %r" % (ms,))
    if ms < 0:
        raise XAPIError("ms must be >= 0, got %r" % (ms,))
    whole, rem = divmod(ms, 1000)  # 整型运算闭式，不走浮点
    if rem == 0:
        return "PT%dS" % whole
    frac = str(rem).zfill(3).rstrip("0")
    return "PT%d.%sS" % (whole, frac)


# ---------- §3.4 statement_id ----------

def statement_id(learner_id, verb_key, object_key, sequence=0):
    _require_id(learner_id, "learner_id")
    _require_id(verb_key, "verb_key")
    _require_id(object_key, "object_key")
    _require_int(sequence, "sequence", 0)
    name = "%s|%s|%s|%s" % (learner_id, verb_key, object_key, sequence)
    return str(uuid.uuid5(uuid.UUID(NAMESPACE_UUID), name))


# ---------- §3.5 make_actor / make_verb / make_activity ----------

def make_actor(learner_id):
    _require_id(learner_id, "learner_id")
    return {"objectType": "Agent",
            "account": {"homePage": ACTOR_HOME_PAGE, "name": learner_id}}


def make_verb(verb_key):
    if verb_key not in VERBS:
        raise XAPIError("unknown verb key: %r" % (verb_key,))
    entry = VERBS[verb_key]
    return {"id": entry["id"], "display": dict(entry["display"])}


def make_activity(object_key):
    _require_id(object_key, "object_key")
    _require_no_whitespace(object_key, "object_key")
    return {"objectType": "Activity", "id": ACTIVITY_PREFIX + object_key}


# ---------- §3.6 三类事件 -> statement ----------

def _build_statement(learner_id, verb_key, object_key, result, timestamp,
                     sequence):
    # 顶层键构造顺序冻结：id, actor, verb, object, result, [timestamp], version
    stmt = {
        "id": statement_id(learner_id, verb_key, object_key, sequence),
        "actor": make_actor(learner_id),
        "verb": make_verb(verb_key),
        "object": make_activity(object_key),
        "result": result,
    }
    if timestamp is not None:
        stmt["timestamp"] = timestamp
    stmt["version"] = XAPI_VERSION
    return stmt


def response_statement(response, learner_id, timestamp=None, sequence=0):
    _require_timestamp(timestamp)
    _require_id(learner_id, "learner_id")
    item_id = _require_id(getattr(response, "item_id", None),
                          "response.item_id")
    correct = getattr(response, "correct", None)
    if not isinstance(correct, bool):
        raise XAPIError("response.correct must be bool")
    learner_answer = getattr(response, "learner_answer", None)
    if learner_answer is not None and not isinstance(learner_answer, str):
        raise XAPIError("response.learner_answer must be str or None")
    response_ms = getattr(response, "response_ms", None)
    if response_ms is not None:
        _require_int(response_ms, "response.response_ms", 0)
        duration = duration_iso(response_ms)
    else:
        duration = None
    # result 键构造顺序冻结：response?, duration?, score, success
    result = {}
    if learner_answer is not None:
        result["response"] = learner_answer
    if duration is not None:
        result["duration"] = duration
    result["score"] = {"scaled": 1.0 if correct else 0.0,
                       "raw": 1 if correct else 0, "min": 0, "max": 1}
    result["success"] = correct
    return _build_statement(learner_id, VERB_ANSWERED, "items/" + item_id,
                            result, timestamp, sequence)


def review_entry_statement(entry, learner_id, timestamp=None, sequence=0):
    _require_timestamp(timestamp)
    _require_id(learner_id, "learner_id")
    kp_id = _require_id(getattr(entry, "kp_id", None), "entry.kp_id")
    due = getattr(entry, "due", None)
    if not isinstance(due, str):
        raise XAPIError("entry.due must be str")
    try:
        date.fromisoformat(due)
    except ValueError:
        raise XAPIError("entry.due must be an ISO date, got %r" % (due,))
    interval_days = _require_int(getattr(entry, "interval_days", None),
                                 "entry.interval_days", 0)
    ease = _require_finite_real(getattr(entry, "ease", None), "entry.ease")
    # 扩展键插入序 = IRI 码点升序：due < ease < interval-days
    result = {"extensions": {EXT_DUE: due,
                             EXT_EASE: float(ease),
                             EXT_INTERVAL_DAYS: interval_days}}
    return _build_statement(learner_id, VERB_REVIEW_SCHEDULED,
                            "kps/" + kp_id, result, timestamp, sequence)


def plan_step_statement(step, learner_id, timestamp=None, sequence=0):
    _require_timestamp(timestamp)
    _require_id(learner_id, "learner_id")
    kp_id = _require_id(getattr(step, "kp_id", None), "step.kp_id")
    strategy_id = _require_id(getattr(step, "strategy_id", None),
                              "step.strategy_id")
    rationale = getattr(step, "rationale", None)
    if not isinstance(rationale, str):
        raise XAPIError("step.rationale must be str")
    target_mastery = _require_finite_real(
        getattr(step, "target_mastery", None), "step.target_mastery")
    if not 0 <= target_mastery <= 1:
        raise XAPIError("step.target_mastery must be in [0,1]")
    raw_ids = getattr(step, "recommended_item_ids", _MISSING)
    if raw_ids is _MISSING:  # 属性缺省按 []
        raw_ids = []
    if not isinstance(raw_ids, (list, tuple)):
        raise XAPIError("step.recommended_item_ids must be list or tuple")
    item_ids = [_require_id(rid, "step.recommended_item_ids element")
                for rid in raw_ids]
    # 扩展键插入序 = IRI 码点升序：rationale < recommended-item-ids
    #   < strategy-id < target-mastery；推荐列表为新拷贝
    result = {"extensions": {EXT_RATIONALE: rationale,
                             EXT_RECOMMENDED_ITEM_IDS: item_ids,
                             EXT_STRATEGY_ID: strategy_id,
                             EXT_TARGET_MASTERY: float(target_mastery)}}
    return _build_statement(learner_id, VERB_PLAN_ASSIGNED, "kps/" + kp_id,
                            result, timestamp, sequence)


# ---------- §3.7/§3.8 批量导出 ----------

def _dispatch_statement(record, learner_id, timestamp, index):
    """鸭子分类（hasattr 语义，与属性值无关）；三属性名全缺按位置报错。"""
    if hasattr(record, "item_id"):
        return response_statement(record, learner_id, timestamp, index)
    if hasattr(record, "strategy_id"):
        return plan_step_statement(record, learner_id, timestamp, index)
    if hasattr(record, "due"):
        return review_entry_statement(record, learner_id, timestamp, index)
    raise XAPIError(
        "record at index %d has none of item_id/strategy_id/due" % index)


def export_statements(records, learner_id, timestamp=None):
    if not isinstance(records, (list, tuple)):
        raise XAPIError("records must be list or tuple, got %r"
                        % type(records).__name__)
    _require_id(learner_id, "learner_id")
    return [_dispatch_statement(record, learner_id, timestamp, index)
            for index, record in enumerate(records)]


def plan_statements(plan, timestamp=None):
    learner_id = _require_id(getattr(plan, "learner_id", None),
                             "plan.learner_id")
    steps = getattr(plan, "steps", None)
    reviews = getattr(plan, "reviews", None)
    if not isinstance(steps, (list, tuple)):
        raise XAPIError("plan.steps must be list or tuple")
    if not isinstance(reviews, (list, tuple)):
        raise XAPIError("plan.reviews must be list or tuple")
    merged = list(steps) + list(reviews)  # steps 全部在前、reviews 在后
    return [_dispatch_statement(record, learner_id, timestamp, index)
            for index, record in enumerate(merged)]


# ---------- §3.9 validate_statement（对任何输入不抛异常） ----------

_IFI_KEYS = ("mbox", "mbox_sha1sum", "openid", "account")
_CA_KEYS = ("parent", "grouping", "category", "other")
_SCORE_KEYS = ("scaled", "raw", "min", "max")


def _check_lang_map(value, field, violations):
    """共享语言映射判定：None/缺省跳过；非 dict 恰 1 条；逐键键/值独立各罚。"""
    if value is None:
        return
    if not isinstance(value, dict):
        violations.append("%s must be a language map (dict)" % field)
        return
    for tag, text in value.items():
        if not is_lang_tag(tag):
            violations.append("%s has invalid language tag %r" % (field, tag))
        if not isinstance(text, str):
            violations.append("%s value for %r must be str" % (field, tag))


def _check_agent(agent, field, violations):
    """共享 Agent/Group 判定；objectType 失格或 IFI 数 != 1 即终止该 agent。"""
    object_type = agent.get("objectType", "Agent")
    if object_type not in ("Agent", "Group"):
        violations.append("%s.objectType must be Agent or Group" % field)
        return
    ifis = [k for k in _IFI_KEYS if k in agent]
    if len(ifis) != 1:
        violations.append(
            "%s must have exactly one inverse functional identifier" % field)
        return
    ifi = ifis[0]
    if ifi == "mbox":
        v = agent["mbox"]
        if not (isinstance(v, str) and v.startswith("mailto:") and is_iri(v)):
            violations.append("%s.mbox must be a mailto: IRI" % field)
    elif ifi == "mbox_sha1sum":
        v = agent["mbox_sha1sum"]
        if not (isinstance(v, str) and _SHA1_RE.match(v)):
            violations.append("%s.mbox_sha1sum must be 40 hex digits" % field)
    elif ifi == "openid":
        if not is_iri(agent["openid"]):
            violations.append("%s.openid must be an IRI" % field)
    else:  # account（homePage 与 name 相互独立）
        account = agent["account"]
        if not isinstance(account, dict):
            violations.append("%s.account must be a dict" % field)
        else:
            if not is_iri(account.get("homePage")):
                violations.append(
                    "%s.account.homePage must be an IRI" % field)
            if not isinstance(account.get("name"), str):
                violations.append("%s.account.name must be str" % field)
    if object_type == "Group":
        # member 检查独立于 IFI 种类校验的结果；元素不递归
        member = agent.get("member")
        if not isinstance(member, list) or any(
                not isinstance(m, dict) for m in member):
            violations.append(
                "%s.member must be a list of Agent dicts" % field)


def _check_extensions(extensions, field, violations):
    if extensions is None:
        return
    if not isinstance(extensions, dict):
        violations.append("%s must be a dict" % field)
        return
    for key in extensions:
        if not is_iri(key):
            violations.append("%s key %r must be an IRI" % (field, key))


def _check_score(score, violations):
    # i. 未知键（迭代序）
    for key in score:
        if key not in _SCORE_KEYS:
            violations.append("result.score has unknown key %r" % (key,))
    # ii. 已知四键按 scaled->raw->min->max：bool/非数值/非有限各 1 条
    values = {}
    for key in _SCORE_KEYS:
        if key not in score:
            continue
        v = score[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or (
                isinstance(v, float) and not math.isfinite(v)):
            violations.append(
                "result.score.%s must be a finite number" % key)
        else:
            values[key] = v
    # iii-vi. 越界与一致性（仅合格值参与；max == min 不查一致性）
    if "scaled" in values and not -1 <= values["scaled"] <= 1:
        violations.append("result.score.scaled must be in [-1, 1]")
    if "min" in values and "max" in values and values["min"] > values["max"]:
        violations.append("result.score min must be <= max")
    if all(k in values for k in ("raw", "min", "max")):
        if not values["min"] <= values["raw"] <= values["max"]:
            violations.append("result.score.raw must be within [min, max]")
    if all(k in values for k in _SCORE_KEYS) and values["max"] > values["min"]:
        expected = (values["raw"] - values["min"]) / (values["max"] - values["min"])
        if abs(values["scaled"] - expected) > SCORE_TOLERANCE:
            violations.append(
                "result.score.scaled is inconsistent with raw/min/max")


def _check_context_activities(ca, violations):
    if not isinstance(ca, dict):
        violations.append("context.contextActivities must be a dict")
        return
    for key, value in ca.items():
        if key not in _CA_KEYS:
            violations.append(
                "context.contextActivities has invalid key %r" % (key,))
        elements = value if isinstance(value, list) else [value]
        for element in elements:
            if not isinstance(element, dict):
                violations.append(
                    "context.contextActivities[%r] elements must be dicts"
                    % (key,))
            elif not is_iri(element.get("id")):
                violations.append(
                    "context.contextActivities[%r] element id must be an IRI"
                    % (key,))


def validate_statement(stmt):
    """xAPI 1.0.3 离线可检验 MUST 子集校验；返回违规清单，不抛异常。"""
    if not isinstance(stmt, dict):
        return ["statement must be a dict, got %s" % type(stmt).__name__]
    violations = []
    # A1 actor（必需；无 None 豁免）
    actor = stmt.get("actor")
    if not isinstance(actor, dict):
        violations.append("actor must be an Agent/Group dict")
    else:
        _check_agent(actor, "actor", violations)
    # A2 verb（必需）
    verb = stmt.get("verb")
    if not isinstance(verb, dict):
        violations.append("verb must be a dict")
    else:
        if not is_iri(verb.get("id")):
            violations.append("verb.id must be an IRI")
        _check_lang_map(verb.get("display"), "verb.display", violations)
    # A3 object（必需）
    obj = stmt.get("object")
    if not isinstance(obj, dict):
        violations.append("object must be a dict")
    else:
        object_type = obj.get("objectType", "Activity")
        if object_type == "Activity":
            if not is_iri(obj.get("id")):
                violations.append("object.id must be an IRI")
            definition = obj.get("definition")
            if definition is not None:
                if not isinstance(definition, dict):
                    violations.append("object.definition must be a dict")
                else:
                    for key in ("name", "description"):
                        if key in definition:
                            _check_lang_map(
                                definition[key],
                                "object.definition.%s" % key, violations)
        elif object_type in ("Agent", "Group"):
            _check_agent(obj, "object", violations)
        elif object_type == "StatementRef":
            if not is_uuid(obj.get("id")):
                violations.append("object.id must be a UUID for StatementRef")
        else:
            violations.append(
                "object.objectType must be Activity/Agent/Group/StatementRef")
    # A4 顶层标量（三者相互独立；无 None 豁免；version 缺席放行）
    if "id" in stmt and not is_uuid(stmt["id"]):
        violations.append("statement.id must be a UUID")
    if "timestamp" in stmt and not is_iso8601_datetime(stmt["timestamp"]):
        violations.append("statement.timestamp must be an ISO 8601 datetime")
    if "version" in stmt and not (
            isinstance(stmt["version"], str)
            and _VERSION_RE.match(stmt["version"])):
        violations.append("statement.version must match 1.0.x")
    # A5 result（容器通则）
    result = stmt.get("result")
    if result is not None:
        if not isinstance(result, dict):
            violations.append("result must be a dict")
        else:
            for key in ("success", "completion"):
                if key in result and not isinstance(result[key], bool):
                    violations.append("result.%s must be bool" % key)
            if "response" in result and not isinstance(result["response"], str):
                violations.append("result.response must be str")
            if "duration" in result and not is_iso8601_duration(
                    result["duration"]):
                violations.append(
                    "result.duration must be an ISO 8601 duration")
            score = result.get("score")
            if score is not None:
                if not isinstance(score, dict):
                    violations.append("result.score must be a dict")
                else:
                    _check_score(score, violations)
            _check_extensions(result.get("extensions"),
                              "result.extensions", violations)
    # A6 context（容器通则）
    context = stmt.get("context")
    if context is not None:
        if not isinstance(context, dict):
            violations.append("context must be a dict")
        else:
            _check_extensions(context.get("extensions"),
                              "context.extensions", violations)
            ca = context.get("contextActivities")
            if ca is not None:
                _check_context_activities(ca, violations)
    return violations
