"""xapi —— 学习事件导出为 xAPI statement JSON（BACKLOG P2「xAPI 学习事件导出」）的确定性内核。

行为契约（specs/drafts/xapi.spec.md，本文件为参考实现）：

- Response -> "answered" statement（result.success/score{scaled,raw,min,max}/response/duration）；
- ReviewEntry -> "review-scheduled" statement（result.extensions 携带 due/ease/interval-days）；
- PlanStep -> "plan-assigned" statement（result.extensions 携带策略/理由/目标掌握度/推荐题）；
- export_statements：混合事件批量导出（顺序保持，sequence=位置序号进入 statement id）；
- plan_statements：LearningPlan -> steps 全部在前、reviews 在后的批量导出；
- validate_statement：xAPI 1.0.3 数据 API 离线可检验 MUST 规则子集的符合性校验器，
  返回违规清单（空 = 符合）；is_iri/is_lang_tag/is_iso8601_duration/is_iso8601_datetime/
  is_uuid 为其导出的判定积木。

标准符合性事实来源（2026-09-29 实读 adlnet/xAPI-Spec xAPI-Data.md）：statement MUST 含
actor/verb/object；id 为标准字符串形式 UUID；Agent 恰一个反向功能标识符（本模块用
account={homePage,name}）；verb.id 必为 IRI（ADL 动词表 http://adlnet.gov/expapi/verbs/<名>，
spec 原文出现 attempted/attended/experienced/voided 等）；Activity object.id 必为 IRI；
result.duration 为 ISO 8601 时长（spec 例 "PT1234S"）；timestamp 为 ISO 8601 日期时间；
提供方写 version 必为 "1.0.0"；extensions 键必为 IRI。

确定性：statement id 用 uuid5（固定命名空间 NAMESPACE_UUID + "learner|verb|object|sequence"）
——无随机、无时钟（timestamp 必须由调用方传入，不传则不出该字段）、无 IO、不读环境；
鸭子类型参数表面（规格 §2，禁止 import 其所在模块；本模块不需要 xuexing.types）。
（注入装载约束：不用 from __future__ import annotations。）
"""

import math
import re
import uuid
from datetime import date, datetime

__all__ = [
    "XAPIError",
    "XAPI_VERSION",
    "ACTIVITY_PREFIX",
    "ACTOR_HOME_PAGE",
    "NAMESPACE_UUID",
    "EXTENSION_PREFIX",
    "EXT_DUE",
    "EXT_EASE",
    "EXT_INTERVAL_DAYS",
    "EXT_RATIONALE",
    "EXT_RECOMMENDED_ITEM_IDS",
    "EXT_STRATEGY_ID",
    "EXT_TARGET_MASTERY",
    "VERB_ANSWERED",
    "VERB_REVIEW_SCHEDULED",
    "VERB_PLAN_ASSIGNED",
    "VERBS",
    "SCORE_TOLERANCE",
    "is_iri",
    "is_lang_tag",
    "is_iso8601_duration",
    "is_iso8601_datetime",
    "is_uuid",
    "duration_iso",
    "make_actor",
    "make_verb",
    "make_activity",
    "statement_id",
    "response_statement",
    "review_entry_statement",
    "plan_step_statement",
    "export_statements",
    "plan_statements",
    "validate_statement",
]


class XAPIError(ValueError):
    """xapi 模块所有校验失败的异常类型（ValueError 直接子类）。"""


# ---- 冻结常量（specs/drafts/xapi.spec.md §3.1）----

XAPI_VERSION = "1.0.0"  # 提供方写 version 时的规定值（xAPI 数据 API §Version）

# 活动 IRI 前缀：题目 -> <prefix>items/<id>，知识点 -> <prefix>kps/<id>
ACTIVITY_PREFIX = "https://xuexing.example.com/xapi/activity/"
# 学习者 Agent 的 account.homePage（account.name = 学习者 id 原文）
ACTOR_HOME_PAGE = "https://xuexing.example.com/learners/"

# statement id 命名空间（uuid5；常量一次性生成后冻结，运行期不再生随机值）
NAMESPACE_UUID = "579bef2f-ca51-4a19-8b5d-ce167fe911fa"
_NAMESPACE = uuid.UUID(NAMESPACE_UUID)

# 扩展 IRI 前缀与各字段 IRI（xAPI：extensions 键必为 IRI）
EXTENSION_PREFIX = "https://xuexing.example.com/xapi/extensions/"
EXT_DUE = EXTENSION_PREFIX + "due"
EXT_EASE = EXTENSION_PREFIX + "ease"
EXT_INTERVAL_DAYS = EXTENSION_PREFIX + "interval-days"
EXT_RATIONALE = EXTENSION_PREFIX + "rationale"
EXT_RECOMMENDED_ITEM_IDS = EXTENSION_PREFIX + "recommended-item-ids"
EXT_STRATEGY_ID = EXTENSION_PREFIX + "strategy-id"
EXT_TARGET_MASTERY = EXTENSION_PREFIX + "target-mastery"

# 动词键（statement id 派生与 VERBS 表查键用）
VERB_ANSWERED = "answered"
VERB_REVIEW_SCHEDULED = "review-scheduled"
VERB_PLAN_ASSIGNED = "plan-assigned"

# 动词表：answered 取 ADL 动词表 IRI（http://adlnet.gov/expapi/verbs/<名>），
# 另两个为本仓库扩展动词（自有 IRI，xAPI 允许自定义动词 IRI）。
VERBS = {
    VERB_ANSWERED: {
        "id": "http://adlnet.gov/expapi/verbs/answered",
        "display": {"zh-CN": "回答", "en-US": "answered"},
    },
    VERB_REVIEW_SCHEDULED: {
        "id": "https://xuexing.example.com/xapi/verbs/review-scheduled",
        "display": {"zh-CN": "已安排复习", "en-US": "review-scheduled"},
    },
    VERB_PLAN_ASSIGNED: {
        "id": "https://xuexing.example.com/xapi/verbs/plan-assigned",
        "display": {"zh-CN": "已分配学习任务", "en-US": "plan-assigned"},
    },
}

# score 一致性容差：|scaled - (raw-min)/(max-min)| <= SCORE_TOLERANCE
SCORE_TOLERANCE = 1e-9


# ---- 判定积木（validate_statement 的构件，独立导出）----

_IRI_SCHEME_RE = re.compile(r"\A[A-Za-z][A-Za-z0-9+.\-]*:")
_UUID_RE = re.compile(
    r"\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z")
_LANG_TAG_RE = re.compile(r"\A[A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*\Z")
_DURATION_RE = re.compile(
    r"\AP(?=(?:[0-9]|T[0-9]))(?:[0-9]+Y)?(?:[0-9]+M)?(?:[0-9]+D)?"
    r"(?:T(?=[0-9])(?:[0-9]+H)?(?:[0-9]+M)?(?:[0-9]+(?:\.[0-9]+)?S)?)?\Z")
_VERSION_10X_RE = re.compile(r"\A1\.0\.[0-9]+\Z")


def is_iri(value):
    """绝对 IRI 判定（闭式子集）：str、非空、有方案（scheme:）、无空白、无控制字符。"""
    if not isinstance(value, str) or not value:
        return False
    if not _IRI_SCHEME_RE.match(value):
        return False
    for ch in value:
        if ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F:
            return False
    return True


def is_lang_tag(value):
    """RFC 5646 语言标签判定（闭式子集）：主子标签 1-8 字母，后续子标签 1-8 字母数字。"""
    return isinstance(value, str) and bool(_LANG_TAG_RE.match(value))


def is_iso8601_duration(value):
    """ISO 8601 时长判定：大写设计符 P/Y/M/D/T/H/S（M 按位置消歧），至少一个分量。"""
    return isinstance(value, str) and bool(_DURATION_RE.match(value))


def is_iso8601_datetime(value):
    """ISO 8601 日期时间判定：str、含大写 T 分隔符、datetime.fromisoformat 可解析。"""
    if not isinstance(value, str) or "T" not in value:
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def is_uuid(value):
    """UUID 标准字符串形式（8-4-4-4-12 十六进制，连字符分隔）。"""
    return isinstance(value, str) and bool(_UUID_RE.match(value))


# ---- 小工具 ----

def _require_learner(learner_id):
    if not isinstance(learner_id, str) or not learner_id.strip():
        raise XAPIError(
            f"learner_id must be a non-empty str, got {learner_id!r}")
    return learner_id


def _require_key(value, what):
    if not isinstance(value, str) or not value.strip():
        raise XAPIError(f"{what} must be a non-empty str, got {value!r}")
    return value


def _require_real(value, what, lo=None, hi=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise XAPIError(f"{what} must be a real number, got {value!r}")
    if not math.isfinite(value):
        raise XAPIError(f"{what} must be finite, got {value!r}")
    if lo is not None and value < lo:
        raise XAPIError(f"{what} must be >= {lo}, got {value!r}")
    if hi is not None and value > hi:
        raise XAPIError(f"{what} must be <= {hi}, got {value!r}")
    return value


def _require_int(value, what, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise XAPIError(f"{what} must be int, got {value!r}")
    if minimum is not None and value < minimum:
        raise XAPIError(f"{what} must be >= {minimum}, got {value}")
    return value


def _require_timestamp(timestamp):
    if not is_iso8601_datetime(timestamp):
        raise XAPIError(
            f"timestamp must be an ISO 8601 datetime with 'T' separator, got {timestamp!r}")
    return timestamp


# ---- 公开 API：id / actor / verb / object / duration ----

def duration_iso(ms):
    """毫秒 -> ISO 8601 时长（整型闭式，不借浮点）：PT<秒>[.<毫秒去尾零>]S。

    实测：0->"PT0S"、1->"PT0.001S"、500->"PT0.5S"、999->"PT0.999S"、1000->"PT1S"、
    1234->"PT1.234S"、45200->"PT45.2S"、60000->"PT60S"、7200000->"PT7200S"。
    ms 非 int（含 bool）或 < 0 -> XAPIError。
    """
    _require_int(ms, "duration ms", minimum=0)
    whole, rem = divmod(ms, 1000)
    frac = f"{rem:03d}".rstrip("0")
    return f"PT{whole}S" if not frac else f"PT{whole}.{frac}S"


def statement_id(learner_id, verb_key, object_key, sequence=0):
    """确定性 statement id：uuid5(NAMESPACE, "learner|verb_key|object_key|sequence")。

    同输入恒同 UUID（xAPI id 允许提供方自带；同 id 幂等）。返回标准字符串形式。
    """
    _require_learner(learner_id)
    _require_key(verb_key, "verb_key")
    _require_key(object_key, "object_key")
    _require_int(sequence, "sequence", minimum=0)
    name = "|".join([learner_id, verb_key, object_key, str(sequence)])
    return str(uuid.uuid5(_NAMESPACE, name))


def make_actor(learner_id):
    """学习者 -> xAPI Agent（account 型反向功能标识符，恰一个）。每次新构造 dict。"""
    _require_learner(learner_id)
    return {
        "objectType": "Agent",
        "account": {"homePage": ACTOR_HOME_PAGE, "name": learner_id},
    }


def make_verb(verb_key):
    """动词键 -> xAPI Verb（VERBS 表的新拷贝，display 为语言映射）。"""
    if verb_key not in VERBS:
        raise XAPIError(f"unknown verb key: {verb_key!r}")
    entry = VERBS[verb_key]
    return {"id": entry["id"], "display": dict(entry["display"])}


def make_activity(object_key):
    """对象键 -> xAPI Activity（id = ACTIVITY_PREFIX + object_key）。"""
    _require_key(object_key, "object_key")
    if re.search(r"\s", object_key):
        raise XAPIError(f"object_key must not contain whitespace: {object_key!r}")
    return {"objectType": "Activity", "id": ACTIVITY_PREFIX + object_key}


# ---- 公开 API：三类事件 -> statement ----

def _statement(learner_id, verb_key, object_key, result, timestamp, sequence):
    """statement 骨架；键构造顺序冻结：id, actor, verb, object, result?, timestamp?, version。"""
    stmt = {
        "id": statement_id(learner_id, verb_key, object_key, sequence),
        "actor": make_actor(learner_id),
        "verb": make_verb(verb_key),
        "object": make_activity(object_key),
    }
    if result is not None:
        stmt["result"] = result
    if timestamp is not None:
        stmt["timestamp"] = _require_timestamp(timestamp)
    stmt["version"] = XAPI_VERSION
    return stmt


def response_statement(response, learner_id, timestamp=None, sequence=0):
    """Response -> "answered" statement。

    result：response?（learner_answer 非 None 才有）、duration?（response_ms 非 None
    才有）、score{scaled:1.0|0.0, raw:1|0, min:0, max:1}、success=correct。
    object = ACTIVITY_PREFIX + "items/" + item_id。
    """
    _require_learner(learner_id)
    item_id = getattr(response, "item_id", None)
    _require_key(item_id, "response.item_id")
    correct = getattr(response, "correct", None)
    if not isinstance(correct, bool):
        raise XAPIError(f"response.correct must be bool, got {correct!r}")
    learner_answer = getattr(response, "learner_answer", None)
    if learner_answer is not None and not isinstance(learner_answer, str):
        raise XAPIError(
            f"response.learner_answer must be str or None, got {learner_answer!r}")
    response_ms = getattr(response, "response_ms", None)
    if response_ms is not None:
        _require_int(response_ms, "response.response_ms", minimum=0)

    result = {}
    if learner_answer is not None:
        result["response"] = learner_answer
    if response_ms is not None:
        result["duration"] = duration_iso(response_ms)
    result["score"] = {
        "scaled": 1.0 if correct else 0.0,
        "raw": 1 if correct else 0,
        "min": 0,
        "max": 1,
    }
    result["success"] = correct
    return _statement(learner_id, VERB_ANSWERED, "items/" + item_id,
                      result, timestamp, sequence)


def review_entry_statement(entry, learner_id, timestamp=None, sequence=0):
    """ReviewEntry -> "review-scheduled" statement（复习调度事件）。

    result.extensions（插入序 = IRI 码点升序）：due（ISO 日期原文）、ease（float）、
    interval-days（int）。object = ACTIVITY_PREFIX + "kps/" + kp_id。
    """
    _require_learner(learner_id)
    kp_id = getattr(entry, "kp_id", None)
    _require_key(kp_id, "entry.kp_id")
    due = getattr(entry, "due", None)
    if not isinstance(due, str):
        raise XAPIError(f"entry.due must be str, got {due!r}")
    try:
        date.fromisoformat(due)
    except ValueError:
        raise XAPIError(f"entry.due must be an ISO 8601 date, got {due!r}") from None
    interval_days = _require_int(getattr(entry, "interval_days", None),
                                 "entry.interval_days", minimum=0)
    ease = _require_real(getattr(entry, "ease", None), "entry.ease")

    result = {"extensions": {
        EXT_DUE: due,
        EXT_EASE: float(ease),
        EXT_INTERVAL_DAYS: interval_days,
    }}
    return _statement(learner_id, VERB_REVIEW_SCHEDULED, "kps/" + kp_id,
                      result, timestamp, sequence)


def plan_step_statement(step, learner_id, timestamp=None, sequence=0):
    """PlanStep -> "plan-assigned" statement（学习计划步骤下发事件）。

    result.extensions（插入序 = IRI 码点升序）：rationale（原文，可为空串）、
    recommended-item-ids（新列表拷贝）、strategy-id、target-mastery（float，[0,1]）。
    """
    _require_learner(learner_id)
    kp_id = getattr(step, "kp_id", None)
    _require_key(kp_id, "step.kp_id")
    strategy_id = _require_key(getattr(step, "strategy_id", None), "step.strategy_id")
    rationale = getattr(step, "rationale", None)
    if not isinstance(rationale, str):
        raise XAPIError(f"step.rationale must be str, got {rationale!r}")
    target_mastery = _require_real(getattr(step, "target_mastery", None),
                                   "step.target_mastery", lo=0.0, hi=1.0)
    rec_ids = getattr(step, "recommended_item_ids", [])
    if not isinstance(rec_ids, (list, tuple)):
        raise XAPIError(
            f"step.recommended_item_ids must be a list, got {type(rec_ids).__name__}")
    for rid in rec_ids:
        _require_key(rid, "step.recommended_item_ids entry")

    result = {"extensions": {
        EXT_RATIONALE: rationale,
        EXT_RECOMMENDED_ITEM_IDS: list(rec_ids),
        EXT_STRATEGY_ID: strategy_id,
        EXT_TARGET_MASTERY: float(target_mastery),
    }}
    return _statement(learner_id, VERB_PLAN_ASSIGNED, "kps/" + kp_id,
                      result, timestamp, sequence)


def _classify_statement(record, learner_id, timestamp, sequence):
    """鸭子分类：有 item_id -> Response；有 strategy_id -> PlanStep；有 due -> ReviewEntry。

    无法分类时抛 XAPIError，消息含位置（sequence 在批量导出中即位置下标）。
    """
    if hasattr(record, "item_id"):
        return response_statement(record, learner_id, timestamp, sequence)
    if hasattr(record, "strategy_id"):
        return plan_step_statement(record, learner_id, timestamp, sequence)
    if hasattr(record, "due"):
        return review_entry_statement(record, learner_id, timestamp, sequence)
    raise XAPIError(
        f"record at index {sequence} is not a Response/ReviewEntry/PlanStep-like "
        f"object (no item_id/strategy_id/due attribute): {record!r}")


def export_statements(records, learner_id, timestamp=None):
    """混合事件列表 -> statement 列表（顺序保持；sequence = 0 起位置序号）。

    records 必须 list/tuple；无法分类的元素按位置报 XAPIError。
    """
    _require_learner(learner_id)
    if not isinstance(records, (list, tuple)):
        raise XAPIError(
            f"records must be a list, got {type(records).__name__}")
    return [_classify_statement(rec, learner_id, timestamp, i)
            for i, rec in enumerate(records)]


def plan_statements(plan, timestamp=None):
    """LearningPlan -> statement 列表：steps 全部在前、reviews 在后，sequence 连续。"""
    learner_id = _require_learner(getattr(plan, "learner_id", None))
    steps = getattr(plan, "steps", None)
    reviews = getattr(plan, "reviews", None)
    for name, part in (("plan.steps", steps), ("plan.reviews", reviews)):
        if not isinstance(part, (list, tuple)):
            raise XAPIError(f"{name} must be a list, got {type(part).__name__}")
    records = list(steps) + list(reviews)
    return [_classify_statement(rec, learner_id, timestamp, i)
            for i, rec in enumerate(records)]


# ---- 公开 API：xAPI 标准符合性校验器（离线 MUST 子集）----

_IFI_KEYS = ("mbox", "mbox_sha1sum", "openid", "account")
_MBOX_SHA1_RE = re.compile(r"\A[0-9a-fA-F]{40}\Z")


def _check_agent(obj, what):
    problems = []
    object_type = obj.get("objectType", "Agent")
    if object_type not in ("Agent", "Group"):
        return [f"{what}.objectType must be Agent or Group, got {object_type!r}"]
    ifis = [k for k in _IFI_KEYS if k in obj]
    if len(ifis) != 1:
        problems.append(
            f"{what} must have exactly one inverse functional identifier, got {len(ifis)}")
        return problems
    ifi = obj[ifis[0]]
    if ifis[0] == "mbox":
        if not (isinstance(ifi, str) and ifi.startswith("mailto:") and is_iri(ifi)):
            problems.append(f"{what}.mbox must be a mailto: IRI")
    elif ifis[0] == "mbox_sha1sum":
        if not (isinstance(ifi, str) and _MBOX_SHA1_RE.match(ifi)):
            problems.append(f"{what}.mbox_sha1sum must be a 40-hex sha1 string")
    elif ifis[0] == "openid":
        if not is_iri(ifi):
            problems.append(f"{what}.openid must be an absolute IRI")
    else:  # account
        if not isinstance(ifi, dict):
            problems.append(f"{what}.account must be a dict")
        else:
            if not is_iri(ifi.get("homePage")):
                problems.append(f"{what}.account.homePage must be an absolute IRI")
            if not isinstance(ifi.get("name"), str):
                problems.append(f"{what}.account.name must be str")
    if object_type == "Group":
        member = obj.get("member")
        if not isinstance(member, list) or not all(isinstance(m, dict) for m in member):
            problems.append(f"{what}.member must be a list of Agent dicts")
    return problems


def _check_lang_map(lang_map, what):
    if lang_map is None:
        return []
    if not isinstance(lang_map, dict):
        return [f"{what} must be a language map (dict)"]
    problems = []
    for tag, text in lang_map.items():
        if not is_lang_tag(tag):
            problems.append(f"{what} key must be an RFC 5646 language tag, got {tag!r}")
        if not isinstance(text, str):
            problems.append(f"{what}[{tag!r}] must be str")
    return problems


def _check_extensions(ext, what):
    if ext is None:
        return []
    if not isinstance(ext, dict):
        return [f"{what} must be a dict"]
    return [f"{what} key must be an absolute IRI, got {k!r}"
            for k in ext if not is_iri(k)]


def _check_score(score):
    if score is None:
        return []
    if not isinstance(score, dict):
        return ["result.score must be a dict"]
    problems = []
    for k in score:
        if k not in ("scaled", "raw", "min", "max"):
            problems.append(f"result.score has unknown key: {k!r}")
    values = {}
    for k in ("scaled", "raw", "min", "max"):
        if k in score:
            v = score[k]
            if isinstance(v, bool) or not isinstance(v, (int, float)) \
                    or not math.isfinite(v):
                problems.append(f"result.score.{k} must be a finite real number")
            else:
                values[k] = float(v)
    if "scaled" in values and not -1.0 <= values["scaled"] <= 1.0:
        problems.append("result.score.scaled must be within [-1, 1]")
    if "min" in values and "max" in values and values["min"] > values["max"]:
        problems.append("result.score.min must be <= result.score.max")
    if "raw" in values and "min" in values and "max" in values:
        if not values["min"] <= values["raw"] <= values["max"]:
            problems.append("result.score.raw must be within [min, max]")
    if "scaled" in values and "raw" in values and "min" in values and "max" in values \
            and values["max"] > values["min"]:
        expected = (values["raw"] - values["min"]) / (values["max"] - values["min"])
        if abs(values["scaled"] - expected) > SCORE_TOLERANCE:
            problems.append(
                "result.score.scaled is inconsistent with (raw-min)/(max-min)")
    return problems


def validate_statement(stmt):
    """xAPI 1.0.3 数据 API「离线可检验 MUST 子集」符合性校验。

    返回违规清单（字符串列表，判定顺序冻结 = §5 各条目顺序）；空列表 = 符合。
    校验范围（规格 §5）：actor/verb/object 三必需项、Agent 的恰一 IFI、
    Activity/Agent/Group/StatementRef 四种 object、id 的 UUID 形式、timestamp/version/
    result（success/completion/response/duration/score/extensions）、context
    （extensions/contextActivities）。未列出的属性（authority/stored/attachments 等，
    通常由 LRS 填写）不校验。
    """
    if not isinstance(stmt, dict):
        return [f"statement must be a dict, got {type(stmt).__name__}"]
    problems = []

    # A1 actor（必需）
    actor = stmt.get("actor")
    if not isinstance(actor, dict):
        problems.append("actor must be a dict")
    else:
        problems.extend(_check_agent(actor, "actor"))

    # A2 verb（必需）
    verb = stmt.get("verb")
    if not isinstance(verb, dict):
        problems.append("verb must be a dict")
    else:
        if not is_iri(verb.get("id")):
            problems.append("verb.id must be an absolute IRI")
        problems.extend(_check_lang_map(verb.get("display"), "verb.display"))

    # A3 object（必需）
    obj = stmt.get("object")
    if not isinstance(obj, dict):
        problems.append("object must be a dict")
    else:
        object_type = obj.get("objectType", "Activity")
        if object_type == "Activity":
            if not is_iri(obj.get("id")):
                problems.append("object.id must be an absolute IRI")
            definition = obj.get("definition")
            if definition is not None:
                if not isinstance(definition, dict):
                    problems.append("object.definition must be a dict")
                else:
                    for f in ("name", "description"):
                        if f in definition:
                            problems.extend(_check_lang_map(
                                definition[f], f"object.definition.{f}"))
        elif object_type in ("Agent", "Group"):
            problems.extend(_check_agent(obj, "object"))
        elif object_type == "StatementRef":
            if not is_uuid(obj.get("id")):
                problems.append("object.id must be a UUID for StatementRef")
        else:
            problems.append(f"unsupported object.objectType: {object_type!r}")

    # A4 id / timestamp / version（可选出现时校验）
    if "id" in stmt and not is_uuid(stmt["id"]):
        problems.append("id must be a UUID in standard string form")
    if "timestamp" in stmt and not is_iso8601_datetime(stmt["timestamp"]):
        problems.append("timestamp must be an ISO 8601 datetime")
    if "version" in stmt and not (
            isinstance(stmt["version"], str)
            and _VERSION_10X_RE.match(stmt["version"])):
        problems.append("version must start with '1.0.'")

    # A5 result
    result = stmt.get("result")
    if result is not None:
        if not isinstance(result, dict):
            problems.append("result must be a dict")
        else:
            for f in ("success", "completion"):
                if f in result and not isinstance(result[f], bool):
                    problems.append(f"result.{f} must be bool")
            if "response" in result and not isinstance(result["response"], str):
                problems.append("result.response must be str")
            if "duration" in result and not is_iso8601_duration(result["duration"]):
                problems.append("result.duration must be an ISO 8601 duration")
            problems.extend(_check_score(result.get("score")))
            problems.extend(_check_extensions(
                result.get("extensions"), "result.extensions"))

    # A6 context
    context = stmt.get("context")
    if context is not None:
        if not isinstance(context, dict):
            problems.append("context must be a dict")
        else:
            problems.extend(_check_extensions(
                context.get("extensions"), "context.extensions"))
            activities = context.get("contextActivities")
            if activities is not None:
                if not isinstance(activities, dict):
                    problems.append("context.contextActivities must be a dict")
                else:
                    for key, val in activities.items():
                        if key not in ("parent", "grouping", "category", "other"):
                            problems.append(
                                "context.contextActivities key must be "
                                f"parent/grouping/category/other, got {key!r}")
                        entries = val if isinstance(val, list) else [val]
                        for act in entries:
                            if not isinstance(act, dict) or not is_iri(act.get("id")):
                                problems.append(
                                    f"context.contextActivities[{key!r}] entries "
                                    "must be Activities with an absolute IRI id")
    return problems
