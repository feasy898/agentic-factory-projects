"""dual_verify —— 双代理独立复验题库（BACKLOG P2）的确定性内核。

行为契约（specs/drafts/dual_verify.spec.md，本文件为参考实现）：

- answers_match：verification 级标答-提案比对——归一化（N1–N5，语义对齐 grading）、
  choice 选项解析、数值等价（相对容差 1e-9）、单位门、多答案集合无序等值
  （"3或7" == "7或3"）、赋值前缀剥离（"x=5，y=2" == "y=2，x=5"）、字面兜底；
- verify_item：单题裁决——对 {agent_id: answer} 逐代理判定 match/mismatch/no_answer，
  产出 agree（≥2 match 且零 mismatch，可回填 v2 记录）/ disagree（有具体提案与标答
  不符 → 人工仲裁，不得回填）/ incomplete（证据不足，诚实缺口，不得回填）；
- verification_record / make_record / backfill_item：恰为 itembank_v2 合法形状
  {"agents": [...升序去重...], "answers_agree": True} 的记录构造与纯回填；
- verify_bank / arbitration_rows / DualVerifyReport：全库裁决与人工仲裁队列行。

全模块纯函数：无 IO、无随机、无时钟、不读环境；代理序一律码点升序，同输入同输出。
与 grading/itembank_v2 的行为一致性由契约测试跨模块断言，模块间零 import
（注入装载约束：不用 from __future__ import annotations，注解直接写真实对象）。
"""

import re
from dataclasses import dataclass

__all__ = [
    "DualVerifyError",
    "COMPARISON_TOLERANCE",
    "UNIT_ALIASES",
    "VERDICT_AGREE",
    "VERDICT_DISAGREE",
    "VERDICT_INCOMPLETE",
    "normalize_answer",
    "answers_match",
    "verify_item",
    "verification_record",
    "make_record",
    "backfill_item",
    "verify_bank",
    "arbitration_rows",
    "DualVerifyReport",
]


class DualVerifyError(ValueError):
    """dual_verify 模块所有校验失败的异常类型（ValueError 直接子类）。"""


# ---- 冻结常量（specs/drafts/dual_verify.spec.md §3.1）----

COMPARISON_TOLERANCE = 1e-9  # 数值等价相对容差（与 grading.GRADE_TOLERANCE 同值）

# 单位别名表：与 grading.UNIT_ALIASES 逐键逐值相同（依赖约束下自包含；
# 契约测试断言两表一致）。键 = 表层写法（含规范形自身），值 = 规范单位。
UNIT_ALIASES = {
    "千米": "千米", "公里": "千米",
    "米": "米", "厘米": "厘米", "毫米": "毫米",
    "平方千米": "平方千米", "平方公里": "平方千米",
    "平方米": "平方米", "平方分米": "平方分米", "平方厘米": "平方厘米",
    "立方米": "立方米", "立方分米": "立方分米", "立方厘米": "立方厘米",
    "公顷": "公顷",
    "吨": "吨", "千克": "千克", "公斤": "千克", "克": "克",
    "元": "元", "角": "角", "分": "分",
    "升": "升", "毫升": "毫升",
    "小时": "小时", "时": "小时", "分钟": "分", "秒": "秒",
    "度": "度",
}
_MAX_UNIT_LEN = max(len(k) for k in UNIT_ALIASES)  # = 4（如 平方公里）

VERDICT_AGREE = "agree"
VERDICT_DISAGREE = "disagree"
VERDICT_INCOMPLETE = "incomplete"

ST_MATCH = "match"
ST_MISMATCH = "mismatch"
ST_NO_ANSWER = "no_answer"

# N1：全角折叠范围与偏移（[0xFF01, 0xFF5E] -> ASCII），U+3000 -> 半角空格
_FW_LO, _FW_HI, _FW_OFFSET = 0xFF01, 0xFF5E, 0xFEE0
# N3：尾部可剥字符（全角 ，！？；已由 N1 折叠为 ASCII，。、不在折叠范围）
_TRAILING_CHARS = "。，、;,.!?" + " \t\r\n\v\f"
# N4：千分位逗号 = 数字后且恰跟 3 位数字（第 4 位仍是数字则不算）
_THOUSANDS_RE = re.compile(r"(?<=[0-9]),(?=[0-9]{3}(?![0-9]))")
_WS_RE = re.compile(r"\s+")

# 数值文法（与 grading 同：[0-9] 显式限定，杜绝 unicode 数字/inf/nan）
_DECIMAL_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
_FRACTION_RE = re.compile(r"([+-]?[0-9]+)\s*/\s*([0-9]+)\Z")
_MIXED_RE = re.compile(r"([+-]?[0-9]+) ([0-9]+)\s*/\s*([0-9]+)\Z")

# R4：多答案分隔符——只按**原始文本**的全角分隔符拆分（ASCII 逗号不拆，
# 坐标 "(4,1)" 不受伤）；拆分后才逐分量归一化。
_SPLIT_RE = re.compile(r"或|和|、|；|，")

# R4：赋值前缀——首个 = 之前由字母/希腊字母/∠(U+2220)/下标数字/撇号组成且 ≤6 字符
# 时剥去（x= / y= / m= / x₁= / ∠2= …）；含括号/数字开头的表达式整体不受影响。
_PREFIX_RE = re.compile(r"[A-Za-z\u0370-\u03ff\u2220\u2080-\u2089\u00b9\u00b2\u00b3'′]{1,6}=(.+)\Z", re.S)

_ITEM_TYPES = ("choice", "fill", "solve")


def _require_str(value, what):
    if not isinstance(value, str):
        raise DualVerifyError(f"{what} must be str, got {type(value).__name__}")
    return value


def normalize_answer(text):
    """归一化规则表 N1–N5（按序执行，见规格 §3.2）。非 str 抛 DualVerifyError。"""
    _require_str(text, "answer text")
    # N1 全角折叠
    out = []
    for ch in text:
        code = ord(ch)
        if _FW_LO <= code <= _FW_HI:
            out.append(chr(code - _FW_OFFSET))
        elif code == 0x3000:
            out.append(" ")
        else:
            out.append(ch)
    # N2 空白折叠 + 去首尾
    s = _WS_RE.sub(" ", "".join(out)).strip()
    # N3 尾部剥离（标点与空白交错循环剥）
    while s and s[-1] in _TRAILING_CHARS:
        s = s[:-1]
    # N4 千分位逗号
    s = _THOUSANDS_RE.sub("", s)
    # N5 小写化
    return s.lower()


def _parse_numeric(text):
    """解析已归一化的数值文本；不可解析返回 None。"""
    percent = text.endswith("%")
    t = text[:-1].strip() if percent else text
    m = _MIXED_RE.match(t)  # 带分数 a b/c
    if m is not None:
        a = int(m.group(1))
        b, c = int(m.group(2)), int(m.group(3))
        if c == 0:
            return None
        value = (-1 if a < 0 else 1) * (abs(a) + b / c)
    else:
        m = _FRACTION_RE.match(t)  # 分数 a/b
        if m is not None:
            a, b = int(m.group(1)), int(m.group(2))
            if b == 0:
                return None
            value = a / b
        elif _DECIMAL_RE.match(t) is not None:  # 小数（含 .5 / 3. / 1e3）
            value = float(t)
        else:
            return None
    return value / 100.0 if percent else value


def _split_unit(text):
    """从尾部剥单位（最长后缀优先）；纯单位词/无命中返回 (原文, None)。"""
    for width in range(min(len(text), _MAX_UNIT_LEN), 0, -1):
        suffix = text[-width:]
        if suffix in UNIT_ALIASES:
            rest = text[:-width].strip()
            if rest:
                return rest, UNIT_ALIASES[suffix]
            break  # 命中的是纯单位词（无数值部）
    return text, None


def _numeric_equal(a, b):
    """相对容差判等：|a−b| <= 1e-9 * max(1, |a|, |b|)。"""
    return abs(a - b) <= COMPARISON_TOLERANCE * max(1.0, abs(a), abs(b))


def _key(s):
    """字面等值键：归一化后删除全部空白。"""
    return _WS_RE.sub("", s)


def _strip_assignment(normalized):
    """剥赋值前缀（x= / y= / x₁= …）；无前缀原样返回。"""
    m = _PREFIX_RE.match(normalized)
    return m.group(1) if m is not None else normalized


def _component_match(ca, cb):
    """单分量比对：单位门 → 数值/字面。输入均为已归一化文本。"""
    ca_val, ca_unit = _split_unit(ca)
    cb_val, cb_unit = _split_unit(cb)
    if ca_unit != cb_unit:  # 单位门：缺单位/异单位不匹配
        return False
    ca_num = _parse_numeric(ca_val)
    cb_num = _parse_numeric(cb_val)
    if ca_num is not None and cb_num is not None:
        return _numeric_equal(ca_num, cb_num)
    return _key(ca_val) == _key(cb_val)


def _multiset_match(list_a, list_b):
    """分量多重集配对：逐分量 _component_match，全部配对成功且数量相等才 True。"""
    if len(list_a) != len(list_b):
        return False
    remaining = list(list_b)
    for a in list_a:
        hit = None
        for i, b in enumerate(remaining):
            if _component_match(a, b):
                hit = i
                break
        if hit is None:
            return False
        remaining.pop(hit)
    return not remaining


def _resolve_option(target, labels, texts):
    """标签优先（options 顺序第一个），其后全文 _key 比较；不命中返回 None。"""
    if target in labels:
        return labels.index(target)
    target_key = _key(target)
    for i, t in enumerate(texts):
        if _key(t) == target_key:
            return i
    return None


def _match_choice(key_answer, proposed, options):
    texts = [normalize_answer(o) for o in options]
    labels = [t.split(".", 1)[0].strip() for t in texts]
    correct = _resolve_option(normalize_answer(key_answer), labels, texts)
    given = _resolve_option(normalize_answer(proposed), labels, texts)
    return correct is not None and correct == given


def _split_components(raw):
    """原始文本按全角分隔符拆分量 → 逐分量归一化 + 剥赋值前缀。"""
    parts = [p for p in _SPLIT_RE.split(raw) if p.strip()]
    if not parts:  # 原文全为分隔符（域内不出现；防御）
        parts = [raw]
    return [_strip_assignment(normalize_answer(p)) for p in parts]


def answers_match(key_answer, proposed, item_type="fill", options=None):
    """verification 级标答-提案等值判定（规格 §3.3 规则表 R1–R5）。"""
    _require_str(key_answer, "key_answer")
    _require_str(proposed, "proposed")
    if item_type not in _ITEM_TYPES:
        raise DualVerifyError(f"unsupported item_type: {item_type!r}")
    if item_type == "choice":
        if not isinstance(options, list) or len(options) < 2:
            raise DualVerifyError("choice requires a list of >=2 options")
        return _match_choice(key_answer, proposed, options)
    # fill/solve：R1 全串归一化等值
    nk, np_ = normalize_answer(key_answer), normalize_answer(proposed)
    if nk == np_:
        return True
    # R3/R4：多答案集合等值（单分量即 R3 数值/单位路径）
    if _multiset_match(_split_components(key_answer), _split_components(proposed)):
        return True
    # R5：字面兜底（归一化后删除全部空白）
    return _key(nk) == _key(np_)


# ---------- 单题裁决 ----------

def _require_clean_id(value, what):
    _require_str(value, what)
    if value != value.strip() or value.strip() == "":
        raise DualVerifyError(f"{what} must be a non-empty id without surrounding whitespace, got {value!r}")
    return value


def _check_item(item):
    """结构性校验：非 dict / id、answer 空白 / item_type 非法 / choice options 非法 → 抛错。"""
    if not isinstance(item, dict):
        raise DualVerifyError(f"item must be a dict, got {type(item).__name__}")
    item_id = _require_clean_id(item.get("id"), "item id")
    answer = item.get("answer")
    _require_str(answer, f"item {item_id} answer")
    if answer.strip() == "":
        raise DualVerifyError(f"item {item_id} answer must be non-empty")
    item_type = item.get("item_type")
    if item_type not in _ITEM_TYPES:
        raise DualVerifyError(f"item {item_id}: unsupported item_type {item_type!r}")
    if item_type == "choice":
        options = item.get("options")
        if not isinstance(options, list) or len(options) < 2:
            raise DualVerifyError(f"item {item_id}: choice requires a list of >=2 options")
    return item_id


def verify_item(item, agent_answers):
    """单题双代理裁决（规格 §3.4）。返回新构造 JSON 形 dict。"""
    item_id = _check_item(item)
    if not isinstance(agent_answers, dict):
        raise DualVerifyError(f"agent_answers must be a dict, got {type(agent_answers).__name__}")
    statuses = []
    for agent_id in sorted(agent_answers):
        _require_clean_id(agent_id, "agent id")
        raw = agent_answers[agent_id]
        if not isinstance(raw, str) or raw.strip() == "":
            statuses.append((agent_id, ST_NO_ANSWER))
        elif answers_match(item["answer"], raw, item["item_type"], item.get("options")):
            statuses.append((agent_id, ST_MATCH))
        else:
            statuses.append((agent_id, ST_MISMATCH))
    n_match = sum(1 for _, st in statuses if st == ST_MATCH)
    n_mismatch = sum(1 for _, st in statuses if st == ST_MISMATCH)
    if n_mismatch:
        verdict = VERDICT_DISAGREE
    elif n_match >= 2:
        verdict = VERDICT_AGREE
    else:
        verdict = VERDICT_INCOMPLETE
    return {"item_id": item_id, "verdict": verdict, "statuses": tuple(statuses)}


# ---------- 记录构造与回填 ----------

def make_record(agent_ids):
    """由代理 id 可迭代对象构造 v2 合法记录：去重、码点升序、<2 抛错。"""
    cleaned = set()
    for a in agent_ids:
        cleaned.add(_require_clean_id(a, "agent id"))
    if len(cleaned) < 2:
        raise DualVerifyError(f"verification record needs >=2 distinct agents, got {sorted(cleaned)!r}")
    return {"agents": sorted(cleaned), "answers_agree": True}


def verification_record(verify_result):
    """verify_item 结果 → v2 记录；非 agree 一律 None（诚实缺口/分歧不回填）。"""
    if not isinstance(verify_result, dict) or "verdict" not in verify_result:
        raise DualVerifyError(f"not a verify_item result: {verify_result!r}")
    if verify_result["verdict"] != VERDICT_AGREE:
        return None
    return make_record(a for a, st in verify_result.get("statuses", ()) if st == ST_MATCH)


def _check_record(record):
    if not isinstance(record, dict):
        raise DualVerifyError(f"verification record must be a dict, got {type(record).__name__}")
    agents = record.get("agents")
    if not isinstance(agents, list) or len(agents) < 2:
        raise DualVerifyError("verification record needs >=2 agents")
    seen = set()
    for a in agents:
        _require_clean_id(a, "verification agent id")
        if a in seen:
            raise DualVerifyError(f"duplicate verification agent {a!r}")
        seen.add(a)
    if record.get("answers_agree") is not True:
        raise DualVerifyError("verification record answers_agree must be exactly True")


def backfill_item(item, record):
    """纯回填：返回新 dict（原键原序，verification 追加在末尾）；record None → 原样副本。"""
    if not isinstance(item, dict):
        raise DualVerifyError(f"item must be a dict, got {type(item).__name__}")
    if record is None:
        return dict(item)
    _check_record(record)
    out = dict(item)
    out["verification"] = {"agents": list(record["agents"]), "answers_agree": True}
    return out


# ---------- bank 级 ----------


@dataclass(frozen=True)
class DualVerifyReport:
    """全库裁决报告：字段全部 tuple 化、顺序 = items 输入原序（规格 §3.7）。"""

    item_ids: tuple
    verdicts: tuple  # ((item_id, verdict), ...) 原序
    agreed_item_ids: tuple
    disputed_item_ids: tuple
    incomplete_item_ids: tuple
    records: tuple  # ((item_id, record_or_None), ...) 原序

    def counts(self):
        """{"agree": n1, "disagree": n2, "incomplete": n3}，每次返回新 dict。"""
        c = {VERDICT_AGREE: 0, VERDICT_DISAGREE: 0, VERDICT_INCOMPLETE: 0}
        for _, v in self.verdicts:
            c[v] += 1
        return c


def verify_bank(items, answers_by_item):
    """按输入原序逐题裁决；answers_by_item 缺条目按空 dict（→ incomplete）。"""
    if not isinstance(answers_by_item, dict):
        raise DualVerifyError(f"answers_by_item must be a dict, got {type(answers_by_item).__name__}")
    item_ids, verdicts, agreed, disputed, incomplete, records = [], [], [], [], [], []
    for item in items:
        result = verify_item(item, answers_by_item.get(item["id"], {}))
        item_ids.append(result["item_id"])
        verdicts.append((result["item_id"], result["verdict"]))
        if result["verdict"] == VERDICT_AGREE:
            agreed.append(result["item_id"])
        elif result["verdict"] == VERDICT_DISAGREE:
            disputed.append(result["item_id"])
        else:
            incomplete.append(result["item_id"])
        records.append((result["item_id"], verification_record(result)))
    return DualVerifyReport(
        item_ids=tuple(item_ids),
        verdicts=tuple(verdicts),
        agreed_item_ids=tuple(agreed),
        disputed_item_ids=tuple(disputed),
        incomplete_item_ids=tuple(incomplete),
        records=tuple(records),
    )


def arbitration_rows(items, answers_by_item):
    """人工仲裁队列行：mismatch 代理成行，item 输入序 + 代理 id 升序（规格 §3.7）。"""
    if not isinstance(answers_by_item, dict):
        raise DualVerifyError(f"answers_by_item must be a dict, got {type(answers_by_item).__name__}")
    rows = []
    for item in items:
        result = verify_item(item, answers_by_item.get(item["id"], {}))
        for agent_id, status in result["statuses"]:
            if status == ST_MISMATCH:
                rows.append({
                    "item_id": result["item_id"],
                    "key_answer": item["answer"],
                    "agent": agent_id,
                    "proposed": answers_by_item[result["item_id"]][agent_id],
                })
    return tuple(rows)
