"""xapi —— 学习事件导出为 xAPI 1.0.3 statement JSON + 标准符合性校验。

冻结契约：specs/frozen/xapi.spec.md（定稿 v1）。纯函数内核：无 IO、无随机、
无时钟、不读环境；statement id 由 uuid5(固定命名空间, "learner|verb键|object键|
sequence") 确定性派生；timestamp 由调用方传入（None -> 输出不含该键）。
鸭子类型参数表面：只按 getattr 读取事件对象属性；仅依赖标准库，不 import 任何
xuexing 模块。不使用 from __future__ import annotations（注入装载环境约定）。
"""
import math
import re
import uuid
from datetime import date, datetime

__all__ = [
    "XAPIError", "XAPI_VERSION", "ACTIVITY_PREFIX", "ACTOR_HOME_PAGE",
    "NAMESPACE_UUID", "EXTENSION_PREFIX", "EXT_DUE", "EXT_EASE",
    "EXT_INTERVAL_DAYS", "EXT_RATIONALE", "EXT_RECOMMENDED_ITEM_IDS",
    "EXT_STRATEGY_ID", "EXT_TARGET_MASTERY", "VERB_ANSWERED",
    "VERB_REVIEW_SCHEDULED", "VERB_PLAN_ASSIGNED", "VERBS", "SCORE_TOLERANCE",
    "is_iri", "is_lang_tag", "is_iso8601_duration", "is_iso8601_datetime",
    "is_uuid", "duration_iso", "make_actor", "make_verb", "make_activity",
    "statement_id", "response_statement", "review_entry_statement",
    "plan_step_statement", "export_statements", "plan_statements",
    "validate_statement",
]

# ---------- §3.1 常量（冻结） ----------

XAPI_VERSION = "1.0.0"
ACTIVITY_PREFIX = "https://xuexing.example.com/xapi/activity/"
ACTOR_HOME_PAGE = "https://xuexing.example.com/learners/"
NAMESPACE_UUID = "579bef2f-ca51-4a19-8b5d-ce167fe911fa"  # statement id 命名空间
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

_NAMESPACE = uuid.UUID(NAMESPACE_UUID)


class XAPIError(ValueError):
    """本模块唯一异常类型（ValueError 直接子类）。"""


# ---------- §3.2 判定积木 ----------

_IRI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
_LANG_TAG_RE = re.compile(r"^[A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*$")
# 冻结文法（§3.2）：小数分量仅允许出现在秒；P/PT 单独不合法；整串锚定。
_ISO8601_DURATION_RE = re.compile(
    r"\AP(?=(?:[0-9]|T[0-9]))(?:[0-9]+Y)?(?:[0-9]+M)?(?:[0-9]+D)?"
    r"(?:T(?=[0-9])(?:[0-9]+H)?(?:[0-9]+M)?(?:[0-9]+(?:\.[0-9]+)?S)?)?\Z")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{12}$")
_VERSION_RE = re.compile(r"^1\.0\.[0-9]+$")
_SHA1_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def is_iri(v):
    """str 且非空、有方案前缀、无空白/控制字符（非 ASCII 不拒——IRI 非 URI）。"""
    if not isinstance(v, str) or not v:
        return False
    if not _IRI_SCHEME_RE.match(v):
        return False
    for c in v:
        if c.isspace() or ord(c) < 0x20 or ord(c) == 0x7F:
            return False
    return True


def is_lang_tag(v):
    """RFC 5646 闭式子集：主子标签 1-8 字母，后续子标签 1-8 字母数字。"""
    return isinstance(v, str) and bool(_LANG_TAG_RE.match(v))


def is_iso8601_duration(v):
    """§3.2 冻结正则（小数仅允许在 S 分量；P/PT 单独不合法）。"""
    return isinstance(v, str) and bool(_ISO8601_DURATION_RE.match(v))


def is_iso8601_datetime(v):
    """str、含大写 "T"、且 datetime.fromisoformat 可解析。"""
    if not isinstance(v, str) or "T" not in v:
        return False
    try:
        datetime.fromisoformat(v)
    except ValueError:
        return False
    return True


def is_uuid(v):
    """标准 8-4-4-4-12 连字符形式，十六进制大小写均可。"""
    return isinstance(v, str) and bool(_UUID_RE.match(v))


# ---------- 内部守卫 ----------

def _require_id(value, field):
    """id 类守卫（§3.5，与 §3.6 共用）：str 且 strip() 后非空。"""
    if not isinstance(value, str) or not value.strip():
        raise XAPIError(field + " must be a non-empty str, got %r" % (value,))


def _require_no_whitespace(value, field):
    """object_key 附加守卫（§3.5）：不得含任何空白字符。"""
    for c in value:
        if c.isspace():
            raise XAPIError(field + " must contain no whitespace, got %r"
                            % (value,))


def _require_timestamp(timestamp):
    if timestamp is None:
        return
    if not is_iso8601_datetime(timestamp):
        raise XAPIError("timestamp must be an ISO 8601 datetime str or None,"
                        " got %r" % (timestamp,))


def _require_number(value, field):
    """int/float（bool 拒绝）且有限。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise XAPIError(field + " must be an int or float (bool rejected),"
                        " got %r" % (value,))
    if isinstance(value, float) and not math.isfinite(value):
        raise XAPIError(field + " must be finite, got %r" % (value,))


def _to_float(value, field):
    try:
        return float(value)
    except OverflowError:  # 超大 int 转 float 溢出（int 本身有限）
        raise XAPIError(field + " out of float range, got %r" % (value,))


def _require_int(value, field, minimum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise XAPIError(field + " must be an int (bool rejected), got %r"
                        % (value,))
    if value < minimum:
        raise XAPIError(field + " must be >= %d, got %r" % (minimum, value))


# ---------- §3.3 duration_iso ----------

def duration_iso(ms):
    """毫秒 -> ISO 8601 时长（整型运算闭式）。"""
    _require_int(ms, "duration_iso: ms", 0)
    whole, rem = divmod(ms, 1000)
    if rem == 0:
        return "PT%dS" % whole
    frac = str(rem).zfill(3).rstrip("0")  # 三位零填充十进制去尾部 "0"
    return "PT%d.%sS" % (whole, frac)


# ---------- §3.4 statement_id ----------

def statement_id(learner_id, verb_key, object_key, sequence=0):
    """uuid5(固定命名空间, "learner|verb键|object键|sequence")——确定性派生。"""
    _require_id(learner_id, "learner_id")
    _require_id(verb_key, "verb_key")
    _require_id(object_key, "object_key")
    _require_int(sequence, "statement_id: sequence", 0)
    name = learner_id + "|" + verb_key + "|" + object_key + "|" + str(sequence)
    return str(uuid.uuid5(_NAMESPACE, name))


# ---------- §3.5 make_actor / make_verb / make_activity ----------

def make_actor(learner_id):
    """account 型 Agent（恰一个反向功能标识符）；每次返回全新容器。"""
    _require_id(learner_id, "learner_id")
    return {"objectType": "Agent",
            "account": {"homePage": ACTOR_HOME_PAGE, "name": learner_id}}


def make_verb(verb_key):
    """VERBS 深拷贝出口：顶层与 display 均新建，改动不污染动词表。"""
    if not isinstance(verb_key, str) or verb_key not in VERBS:
        raise XAPIError("make_verb: unknown verb key %r" % (verb_key,))
    entry = VERBS[verb_key]
    return {"id": entry["id"], "display": dict(entry["display"])}


def make_activity(object_key):
    """object_key 过 id 类守卫 + 无空白守卫；每次返回新 dict；原值透传。"""
    _require_id(object_key, "object_key")
    _require_no_whitespace(object_key, "object_key")
    return {"objectType": "Activity", "id": ACTIVITY_PREFIX + object_key}


# ---------- §3.6 三类事件 -> statement ----------

def response_statement(response, learner_id, timestamp=None, sequence=0):
    """Response -> answered statement（顶层/result 键构造顺序冻结）。"""
    _require_id(learner_id, "learner_id")
    _require_timestamp(timestamp)
    item_id = getattr(response, "item_id", None)
    _require_id(item_id, "response.item_id")
    correct = getattr(response, "correct", None)
    if not isinstance(correct, bool):
        raise XAPIError("response.correct must be a bool, got %r" % (correct,))
    learner_answer = getattr(response, "learner_answer", None)
    if learner_answer is not None and not isinstance(learner_answer, str):
        raise XAPIError("response.learner_answer must be None or a str,"
                        " got %r" % (learner_answer,))
    response_ms = getattr(response, "response_ms", None)
    if response_ms is not None:
        _require_int(response_ms, "response.response_ms", 0)

    object_key = "items/" + item_id
    stmt = {
        "id": statement_id(learner_id, VERB_ANSWERED, object_key, sequence),
        "actor": make_actor(learner_id),
        "verb": make_verb(VERB_ANSWERED),
        "object": make_activity(object_key),
    }
    result = {}
    if learner_answer is not None:
        result["response"] = learner_answer
    if response_ms is not None:
        result["duration"] = duration_iso(response_ms)
    result["score"] = {"scaled": 1.0 if correct else 0.0,
                       "raw": 1 if correct else 0, "min": 0, "max": 1}
    result["success"] = correct
    stmt["result"] = result
    if timestamp is not None:
        stmt["timestamp"] = timestamp
    stmt["version"] = XAPI_VERSION
    return stmt


def review_entry_statement(entry, learner_id, timestamp=None, sequence=0):
    """ReviewEntry -> review-scheduled statement（extensions 键序 = IRI 码点升序）。"""
    _require_id(learner_id, "learner_id")
    _require_timestamp(timestamp)
    kp_id = getattr(entry, "kp_id", None)
    _require_id(kp_id, "entry.kp_id")
    due = getattr(entry, "due", None)
    if not isinstance(due, str):
        raise XAPIError("entry.due must be a str, got %r" % (due,))
    try:
        date.fromisoformat(due)
    except ValueError:
        raise XAPIError("entry.due must be an ISO 8601 date, got %r" % (due,))
    interval_days = getattr(entry, "interval_days", None)
    _require_int(interval_days, "entry.interval_days", 0)
    ease = getattr(entry, "ease", None)
    _require_number(ease, "entry.ease")

    object_key = "kps/" + kp_id
    stmt = {
        "id": statement_id(learner_id, VERB_REVIEW_SCHEDULED, object_key,
                           sequence),
        "actor": make_actor(learner_id),
        "verb": make_verb(VERB_REVIEW_SCHEDULED),
        "object": make_activity(object_key),
        "result": {"extensions": {
            EXT_DUE: due,
            EXT_EASE: _to_float(ease, "entry.ease"),
            EXT_INTERVAL_DAYS: interval_days,
        }},
    }
    if timestamp is not None:
        stmt["timestamp"] = timestamp
    stmt["version"] = XAPI_VERSION
    return stmt


def plan_step_statement(step, learner_id, timestamp=None, sequence=0):
    """PlanStep -> plan-assigned statement（推荐列表为新拷贝）。"""
    _require_id(learner_id, "learner_id")
    _require_timestamp(timestamp)
    kp_id = getattr(step, "kp_id", None)
    _require_id(kp_id, "step.kp_id")
    strategy_id = getattr(step, "strategy_id", None)
    _require_id(strategy_id, "step.strategy_id")
    rationale = getattr(step, "rationale", None)
    if not isinstance(rationale, str):
        raise XAPIError("step.rationale must be a str, got %r" % (rationale,))
    target_mastery = getattr(step, "target_mastery", None)
    _require_number(target_mastery, "step.target_mastery")
    if not 0 <= target_mastery <= 1:
        raise XAPIError("step.target_mastery must be in [0, 1], got %r"
                        % (target_mastery,))
    recommended = getattr(step, "recommended_item_ids", [])
    if not isinstance(recommended, (list, tuple)):
        raise XAPIError("step.recommended_item_ids must be a list or tuple,"
                        " got %r" % (recommended,))
    for element in recommended:
        _require_id(element, "step.recommended_item_ids element")

    object_key = "kps/" + kp_id
    stmt = {
        "id": statement_id(learner_id, VERB_PLAN_ASSIGNED, object_key,
                           sequence),
        "actor": make_actor(learner_id),
        "verb": make_verb(VERB_PLAN_ASSIGNED),
        "object": make_activity(object_key),
        "result": {"extensions": {
            EXT_RATIONALE: rationale,
            EXT_RECOMMENDED_ITEM_IDS: list(recommended),
            EXT_STRATEGY_ID: strategy_id,
            EXT_TARGET_MASTERY: _to_float(target_mastery,
                                          "step.target_mastery"),
        }},
    }
    if timestamp is not None:
        stmt["timestamp"] = timestamp
    stmt["version"] = XAPI_VERSION
    return stmt


# ---------- §3.7/§3.8 批量导出 ----------

def _emit_record(record, learner_id, timestamp, index):
    """§3.7 鸭子分类（hasattr 语义，次序冻结：item_id -> strategy_id -> due）。"""
    if hasattr(record, "item_id"):
        return response_statement(record, learner_id, timestamp, index)
    if hasattr(record, "strategy_id"):
        return plan_step_statement(record, learner_id, timestamp, index)
    if hasattr(record, "due"):
        return review_entry_statement(record, learner_id, timestamp, index)
    raise XAPIError("record at index %d has none of item_id/strategy_id/due;"
                    " cannot classify" % index)


def export_statements(records, learner_id, timestamp=None):
    """混合事件批量导出：顺序保持，sequence = 0 起的位置下标。"""
    if not isinstance(records, (list, tuple)):
        raise XAPIError("records must be a list or tuple, got %r" % (records,))
    _require_id(learner_id, "learner_id")
    _require_timestamp(timestamp)
    return [_emit_record(record, learner_id, timestamp, index)
            for index, record in enumerate(records)]


def plan_statements(plan, timestamp=None):
    """steps 全部在前、reviews 在后（各自原序）；sequence = 合并序列连续下标。"""
    learner_id = getattr(plan, "learner_id", None)
    _require_id(learner_id, "plan.learner_id")
    _require_timestamp(timestamp)
    steps = getattr(plan, "steps", None)
    reviews = getattr(plan, "reviews", None)
    if not isinstance(steps, (list, tuple)):
        raise XAPIError("plan.steps must be a list or tuple, got %r" % (steps,))
    if not isinstance(reviews, (list, tuple)):
        raise XAPIError("plan.reviews must be a list or tuple, got %r"
                        % (reviews,))
    merged = list(steps) + list(reviews)
    return [_emit_record(record, learner_id, timestamp, index)
            for index, record in enumerate(merged)]


# ---------- §3.9 validate_statement ----------

_IFI_KEYS = ("mbox", "mbox_sha1sum", "openid", "account")
_CA_KEYS = ("parent", "grouping", "category", "other")
_SCORE_KEYS = ("scaled", "raw", "min", "max")


def _check_lang_map(value, prefix, problems):
    """【语言映射】：None/缺席 -> 0 条；非 dict -> 1 条；逐键键/值独立各罚 1 条。"""
    if value is None:
        return
    if not isinstance(value, dict):
        problems.append(prefix + " must be a dict (language map), got %r"
                        % (value,))
        return
    for tag, text in value.items():
        if not is_lang_tag(tag):
            problems.append(prefix + " key must be a language tag, got %r"
                            % (tag,))
        if not isinstance(text, str):
            problems.append(prefix + " value must be a str, got %r" % (text,))


def _check_agent(agent, prefix, problems):
    """【Agent/Group 校验】：objectType -> 恰一 IFI -> 按种类 -> Group member。"""
    object_type = agent.get("objectType", "Agent")
    if object_type not in ("Agent", "Group"):
        problems.append(prefix + '.objectType must be "Agent" or "Group",'
                        " got %r" % (object_type,))
        return
    ifis = [key for key in _IFI_KEYS if key in agent]
    if len(ifis) != 1:
        problems.append(prefix + " must have exactly one inverse functional"
                        " identifier among %s, got %r" % (list(_IFI_KEYS),
                                                          ifis))
        return
    ifi = ifis[0]
    if ifi == "mbox":
        mbox = agent["mbox"]
        if not (isinstance(mbox, str) and mbox.startswith("mailto:")
                and is_iri(mbox)):
            problems.append(prefix + ".mbox must be a mailto IRI, got %r"
                            % (mbox,))
    elif ifi == "mbox_sha1sum":
        sha = agent["mbox_sha1sum"]
        if not (isinstance(sha, str) and _SHA1_RE.match(sha)):
            problems.append(prefix + ".mbox_sha1sum must be a 40-hex str,"
                            " got %r" % (sha,))
    elif ifi == "openid":
        if not is_iri(agent["openid"]):
            problems.append(prefix + ".openid must be an IRI, got %r"
                            % (agent["openid"],))
    else:  # account
        account = agent["account"]
        if not isinstance(account, dict):
            problems.append(prefix + ".account must be a dict, got %r"
                            % (account,))
        else:
            if not is_iri(account.get("homePage")):
                problems.append(prefix + ".account.homePage must be an IRI,"
                                " got %r" % (account.get("homePage"),))
            if not isinstance(account.get("name"), str):
                problems.append(prefix + ".account.name must be a str, got %r"
                                % (account.get("name"),))
    if object_type == "Group":
        member = agent.get("member")
        if not isinstance(member, list) or any(
                not isinstance(m, dict) for m in member):
            problems.append(prefix + ".member must be a list of dicts, got %r"
                            % (member,))


def _check_extensions(extensions, prefix, problems):
    """容器通则 + 每个非 IRI 键 1 条（迭代序）。"""
    if extensions is None:
        return
    if not isinstance(extensions, dict):
        problems.append(prefix + " must be a dict, got %r" % (extensions,))
        return
    for key in extensions:
        if not is_iri(key):
            problems.append(prefix + " keys must be IRIs, got %r" % (key,))


def _check_score(score, problems):
    if score is None:
        return
    if not isinstance(score, dict):
        problems.append("result.score must be a dict, got %r" % (score,))
        return
    for key in score:  # i. 未知键（迭代序）
        if key not in _SCORE_KEYS:
            problems.append("result.score has unknown key %r" % (key,))
    numeric = {}
    for key in _SCORE_KEYS:  # ii. 已知四键按 scaled->raw->min->max
        if key not in score:
            continue
        value = score[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            problems.append("result.score.%s must be a number (bool"
                            " rejected), got %r" % (key, value))
        elif isinstance(value, float) and not math.isfinite(value):
            problems.append("result.score.%s must be finite, got %r"
                            % (key, value))
        else:
            numeric[key] = value
    if "scaled" in numeric and not -1 <= numeric["scaled"] <= 1:  # iii.
        problems.append("result.score.scaled must be in [-1, 1], got %r"
                        % (numeric["scaled"],))
    if "min" in numeric and "max" in numeric \
            and numeric["min"] > numeric["max"]:  # iv.
        problems.append("result.score min > max (%r > %r)"
                        % (numeric["min"], numeric["max"]))
    if all(key in numeric for key in ("raw", "min", "max")) \
            and not numeric["min"] <= numeric["raw"] <= numeric["max"]:  # v.
        problems.append("result.score.raw must be in [min, max], got %r"
                        % (numeric["raw"],))
    if all(key in numeric for key in _SCORE_KEYS) \
            and numeric["max"] > numeric["min"]:  # vi. max == min 不查一致性
        try:
            expected = (numeric["raw"] - numeric["min"]) \
                / (numeric["max"] - numeric["min"])
        except (OverflowError, ZeroDivisionError):
            problems.append("result.score raw/min/max out of float range")
            return
        if abs(numeric["scaled"] - expected) > SCORE_TOLERANCE:
            problems.append("result.score scaled inconsistent with"
                            " raw/min/max: %r vs expected %r"
                            % (numeric["scaled"], expected))


def _check_result(result, problems):
    if result is None:
        return
    if not isinstance(result, dict):
        problems.append("result must be a dict, got %r" % (result,))
        return
    for key in ("success", "completion"):  # 1. 先 success 后 completion
        if key in result and not isinstance(result[key], bool):
            problems.append("result.%s must be a bool, got %r"
                            % (key, result[key]))
    if "response" in result and not isinstance(result["response"], str):  # 2.
        problems.append("result.response must be a str, got %r"
                        % (result["response"],))
    if "duration" in result and not is_iso8601_duration(result["duration"]):
        problems.append("result.duration must be an ISO 8601 duration, got %r"
                        % (result["duration"],))
    _check_score(result.get("score"), problems)  # 4.
    _check_extensions(result.get("extensions"), "result.extensions",
                      problems)  # 5.


def _check_context(context, problems):
    if context is None:
        return
    if not isinstance(context, dict):
        problems.append("context must be a dict, got %r" % (context,))
        return
    _check_extensions(context.get("extensions"), "context.extensions",
                      problems)  # 1.
    activities = context.get("contextActivities")  # 2.
    if activities is None:
        return
    if not isinstance(activities, dict):
        problems.append("context.contextActivities must be a dict, got %r"
                        % (activities,))
        return
    for key, value in activities.items():
        if key not in _CA_KEYS:
            problems.append("context.contextActivities has unknown key %r"
                            % (key,))
        elements = value if isinstance(value, list) else [value]
        for element in elements:
            if not isinstance(element, dict) or not is_iri(element.get("id")):
                problems.append("context.contextActivities element under %r"
                                " must be a dict with an IRI id, got %r"
                                % (key, element))


def _check_object(stmt, problems):
    obj = stmt.get("object")
    if not isinstance(obj, dict):
        problems.append("object must be a dict, got %r" % (obj,))
        return
    object_type = obj.get("objectType", "Activity")
    if object_type == "Activity":
        if not is_iri(obj.get("id")):
            problems.append("object.id must be an IRI, got %r"
                            % (obj.get("id"),))
        definition = obj.get("definition")
        if definition is None:
            return
        if not isinstance(definition, dict):
            problems.append("object.definition must be a dict, got %r"
                            % (definition,))
            return
        for key in ("name", "description"):  # name -> description 序
            if key in definition:
                _check_lang_map(definition[key],
                                "object.definition." + key, problems)
    elif object_type in ("Agent", "Group"):
        _check_agent(obj, "object", problems)
    elif object_type == "StatementRef":
        if not is_uuid(obj.get("id")):
            problems.append("object.id must be a UUID for a StatementRef,"
                            " got %r" % (obj.get("id"),))
    else:
        problems.append("object.objectType is not supported, got %r"
                        % (object_type,))


def validate_statement(stmt):
    """xAPI 1.0.3 数据 API 离线可检验 MUST 子集校验；对任何输入不抛异常。

    判定顺序冻结：A0 -> A1 actor -> A2 verb -> A3 object -> A4 -> A5 result
    -> A6 context；每处失格恰一条违规，不聚合、不去重。
    """
    if not isinstance(stmt, dict):  # A0
        return ["statement must be a JSON dict, got " + type(stmt).__name__]
    problems = []
    actor = stmt.get("actor")  # A1（必需，无 None 豁免）
    if not isinstance(actor, dict):
        problems.append("actor must be a dict, got %r" % (actor,))
    else:
        _check_agent(actor, "actor", problems)
    verb = stmt.get("verb")  # A2（必需，无 None 豁免）
    if not isinstance(verb, dict):
        problems.append("verb must be a dict, got %r" % (verb,))
    else:
        if not is_iri(verb.get("id")):
            problems.append("verb.id must be an IRI, got %r"
                            % (verb.get("id"),))
        _check_lang_map(verb.get("display"), "verb.display", problems)
    _check_object(stmt, problems)  # A3
    if "id" in stmt and not is_uuid(stmt["id"]):  # A4（无 None 豁免）
        problems.append("id must be a UUID, got %r" % (stmt["id"],))
    if "timestamp" in stmt and not is_iso8601_datetime(stmt["timestamp"]):
        problems.append("timestamp must be an ISO 8601 datetime, got %r"
                        % (stmt["timestamp"],))
    if "version" in stmt:
        version = stmt["version"]
        if not (isinstance(version, str) and _VERSION_RE.match(version)):
            problems.append("version must be a str matching ^1\\.0.[0-9]+$,"
                            " got %r" % (version,))
    _check_result(stmt.get("result"), problems)  # A5
    _check_context(stmt.get("context"), problems)  # A6
    return problems
