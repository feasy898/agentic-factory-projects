"""grading —— 主观题判分内核（终版重生成）。

实现冻结契约 specs/frozen/grading.spec.md（定稿 v1）：N1–N5 归一化规则表、
ASCII 数值解析（百分数/带分数/分数/小数，全文锚定）、单位别名表 + 单位门
（只归一别名、不做换算）、choice 两趟解析（标签直接相等先于全文键形态，
各取最小下标）。全模块纯函数：无随机/时钟/IO/全局可变状态。
"""
import re

from xuexing.types import Response

GRADE_TOLERANCE = 1e-9


class GradingError(ValueError):
    """本模块唯一异常类型（ValueError 直接子类）。"""


# 单位别名表：表层写法（含规范形自身）→ 规范单位。只归一别名，不做任何换算。
UNIT_ALIASES = {
    "千米": "千米", "公里": "千米",
    "米": "米",
    "厘米": "厘米",
    "毫米": "毫米",
    "平方千米": "平方千米", "平方公里": "平方千米",
    "平方米": "平方米",
    "平方分米": "平方分米",
    "平方厘米": "平方厘米",
    "立方米": "立方米",
    "立方分米": "立方分米",
    "立方厘米": "立方厘米",
    "公顷": "公顷",
    "吨": "吨",
    "克": "克",
    "千克": "千克", "公斤": "千克",
    "元": "元",
    "角": "角",
    "分": "分",
    "升": "升",
    "毫升": "毫升",
    "小时": "小时", "时": "小时",
    "分钟": "分",
    "秒": "秒",
    "度": "度",
}

_UNIT_MAX_LEN = max(len(k) for k in UNIT_ALIASES)

_WHITESPACE_RE = re.compile(r"\s+")
# N4 千分位：左邻为 ASCII 数字、右侧恰为 3 位 ASCII 数字（第 4 位仍是数字则不算）
_THOUSANDS_RE = re.compile(r"(?<=[0-9]),(?=[0-9]{3}(?![0-9]))")
# N3 尾部剥离集合；N2 之后串内空白只可能是单个半角空格
_TAIL_STRIP_CHARS = {"。", "、", ",", ".", ";", "!", "?", " "}

# 数值文法：数字类一律 ASCII [0-9]，全部全文锚定（fullmatch）
_MIXED_RE = re.compile(r"([+-]?)([0-9]+) ([0-9]+)\s*/\s*([0-9]+)")
_FRACTION_RE = re.compile(r"([+-]?)([0-9]+)\s*/\s*([0-9]+)")
_DECIMAL_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


# ---------- §3.2 normalize_answer：N1–N5 按序 ----------

def normalize_answer(text: str) -> str:
    if not isinstance(text, str):
        raise GradingError(f"normalize_answer expects str, got {type(text).__name__}")
    # N1 全角折叠：[0xFF01, 0xFF5E] → -0xFEE0；U+3000 → 半角空格
    folded = []
    for ch in text:
        cp = ord(ch)
        if 0xFF01 <= cp <= 0xFF5E:
            folded.append(chr(cp - 0xFEE0))
        elif cp == 0x3000:
            folded.append(" ")
        else:
            folded.append(ch)
    s = "".join(folded)
    # N2 空白折叠：内部空白串 → 单个半角空格，再去首尾
    s = _WHITESPACE_RE.sub(" ", s).strip()
    # N3 尾部剥离：只剥尾部，不动内部
    while s and s[-1] in _TAIL_STRIP_CHARS:
        s = s[:-1]
    # N4 千分位逗号删除
    s = _THOUSANDS_RE.sub("", s)
    # N5 小写化
    return s.lower()


# ---------- §3.3 parse_numeric ----------

def _parse_bare(text: str) -> float | None:
    """带分数 → 分数 → 小数（不含百分数支），全部全文锚定。"""
    m = _MIXED_RE.fullmatch(text)
    if m is not None:
        denom = int(m.group(4))
        if denom == 0:
            return None
        sign = -1.0 if m.group(1) == "-" else 1.0
        # 符号只取整数部、作用于整体：sign·(|a| + b/c)
        return sign * (int(m.group(2)) + int(m.group(3)) / denom)
    m = _FRACTION_RE.fullmatch(text)
    if m is not None:
        denom = int(m.group(3))
        if denom == 0:
            return None
        value = int(m.group(2)) / denom
        return -value if m.group(1) == "-" else value
    if _DECIMAL_RE.fullmatch(text) is not None:
        return float(text)
    return None


def parse_numeric(text: str) -> float | None:
    if not isinstance(text, str):
        raise GradingError(f"parse_numeric expects str, got {type(text).__name__}")
    if text.endswith("%"):
        bare = _parse_bare(text[:-1].strip())
        if bare is None:
            return None
        return bare / 100
    return _parse_bare(text)


# ---------- §3.4 split_unit ----------

def split_unit(text: str) -> tuple[str, str | None]:
    if not isinstance(text, str):
        raise GradingError(f"split_unit expects str, got {type(text).__name__}")
    for width in range(min(len(text), _UNIT_MAX_LEN), 0, -1):
        canon = UNIT_ALIASES.get(text[-width:])
        if canon is None:
            continue
        rest = text[:-width].strip()
        if not rest:
            # 纯单位词：命中即返回原文，不回退更短后缀
            return (text, None)
        return (rest, canon)
    return (text, None)


# ---------- §3.5 numeric_equal ----------

def numeric_equal(a: float, b: float) -> bool:
    return abs(a - b) <= GRADE_TOLERANCE * max(1.0, abs(a), abs(b))


# ---------- §3.6 键形态（仅 fill 字面支与 choice 全文趟使用） ----------

def _answer_key(s: str) -> str:
    return _WHITESPACE_RE.sub("", normalize_answer(s))


# ---------- §3.7 grade_fill ----------

def grade_fill(item, learner_answer) -> bool:
    # 步骤 1：learner 类型检查与未作答短路先于一切题目侧校验
    if learner_answer is not None and not isinstance(learner_answer, str):
        raise GradingError(
            f"learner_answer expects str or None, got {type(learner_answer).__name__}"
        )
    if learner_answer is None:
        return False
    # 步骤 2：item.answer 非 str 在此抛错（即使 learner_answer 是空白串）
    ca = normalize_answer(item.answer)
    # 步骤 3：空白作答短路在题目侧归一之后
    la = normalize_answer(learner_answer)
    if la == "":
        return False
    # 步骤 4：拆单位（别名已归一到规范单位）
    ca_num, ca_unit = split_unit(ca)
    la_num, la_unit = split_unit(la)
    # 步骤 5：单位门（缺单位/异单位判错；None == None 通过）
    if ca_unit != la_unit:
        return False
    # 步骤 6：数值支，否则字面等值支
    ca_val = parse_numeric(ca_num)
    la_val = parse_numeric(la_num)
    if ca_val is not None and la_val is not None:
        return numeric_equal(ca_val, la_val)
    return _answer_key(ca_num) == _answer_key(la_num)


# ---------- §3.8 grade_choice ----------

def _resolve_choice(t: str, labels: list[str], texts: list[str]) -> int | None:
    # 第一趟（标签）：归一化标签上的直接 ==（键形态不适用），取最小下标
    for i, label in enumerate(labels):
        if t == label:
            return i
    # 第二趟（全文）：键形态相等，取最小下标
    t_key = _answer_key(t)
    for i, txt in enumerate(texts):
        if t_key == _answer_key(txt):
            return i
    return None


def grade_choice(item, learner_answer) -> bool:
    # 步骤 1：learner 类型检查与未作答短路优先于题目校验
    if learner_answer is not None and not isinstance(learner_answer, str):
        raise GradingError(
            f"learner_answer expects str or None, got {type(learner_answer).__name__}"
        )
    if learner_answer is None:
        return False
    # 步骤 2：选项归一（选项含非 str 在此抛错）与标签切分
    texts = [normalize_answer(option) for option in item.options]
    labels = [t.split(".", 1)[0].strip() for t in texts]
    # 步骤 3：空白作答短路在选项归一之后、正确项解析之前
    la = normalize_answer(learner_answer)
    if la == "":
        return False
    # 步骤 4：解析正确项；题目非法（含 options 空）→ GradingError
    correct = _resolve_choice(normalize_answer(item.answer), labels, texts)
    if correct is None:
        raise GradingError(f"item {item.id!r}: answer matches no option")
    # 步骤 5：解析学习者项；未知 token → False
    given = _resolve_choice(la, labels, texts)
    if given is None:
        return False
    # 步骤 6
    return given == correct


# ---------- §3.9 grade / grade_to_response ----------

def grade(item, learner_answer) -> bool:
    # 分派先于未作答短路：非法 item_type 即使 None 也抛错
    kind = item.item_type
    if kind == "choice":
        return grade_choice(item, learner_answer)
    if kind == "fill" or kind == "solve":
        return grade_fill(item, learner_answer)
    raise GradingError(f"unsupported item_type: {kind!r}")


def grade_to_response(item, learner_answer, response_ms=None) -> Response:
    return Response(
        item_id=item.id,
        correct=grade(item, learner_answer),
        learner_answer=learner_answer,
        response_ms=response_ms,
    )
