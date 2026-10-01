"""grading —— 主观题判分接口（重生成实现，按 specs/frozen/grading.spec.md 定稿 v1 从零实现）。

- normalize_answer：归一化规则表 N1–N5 按序执行（全角折叠 → 空白折叠 →
  尾部剥离 → 千分位逗号删除 → 小写化）；
- parse_numeric：百分数 → 带分数 → 分数 → 小数，按序尝试，模式全文锚定，
  数字类一律 ASCII [0-9]；
- split_unit：最长后缀优先的单位别名拆分；不做任何单位换算，只做别名归一；
- numeric_equal：1e-9 相对容差（零附近为绝对带）；
- grade_fill / grade_choice / grade：判定次序为绑定条款（未作答短路先于
  题目侧校验；fill 空白短路在 answer 归一之后；choice 空白短路在选项归一
  之后、正确项解析之前；grade 分派先于未作答短路）。

全模块纯函数：无随机、无时钟、无 IO、无全局可变状态；同输入同输出。
依赖：标准库 re + xuexing.types（绝对导入，模块间零 import）。
"""
import re

from xuexing.types import Response

__all__ = [
    "GradingError",
    "GRADE_TOLERANCE",
    "UNIT_ALIASES",
    "normalize_answer",
    "parse_numeric",
    "split_unit",
    "numeric_equal",
    "grade_fill",
    "grade_choice",
    "grade",
    "grade_to_response",
]


class GradingError(ValueError):
    """grading 模块唯一异常类型（ValueError 直接子类）。"""


GRADE_TOLERANCE = 1e-9

# §3.1 单位别名表：28 表层写法 → 23 规范单位；每个值自身也是键（规范闭包）。
# 注意：没有裸的「分米」，只有 平方分米 / 立方分米。
_UNIT_PAIRS = (
    ("千米", "千米"), ("公里", "千米"),
    ("米", "米"), ("厘米", "厘米"), ("毫米", "毫米"),
    ("平方千米", "平方千米"), ("平方公里", "平方千米"),
    ("平方米", "平方米"), ("平方分米", "平方分米"), ("平方厘米", "平方厘米"),
    ("立方米", "立方米"), ("立方分米", "立方分米"), ("立方厘米", "立方厘米"),
    ("公顷", "公顷"),
    ("吨", "吨"), ("克", "克"),
    ("千克", "千克"), ("公斤", "千克"),
    ("元", "元"), ("角", "角"), ("分", "分"),
    ("升", "升"), ("毫升", "毫升"),
    ("小时", "小时"), ("时", "小时"),
    ("分钟", "分"),
    ("秒", "秒"), ("度", "度"),
)
UNIT_ALIASES: dict[str, str] = dict(_UNIT_PAIRS)

# §3.4：L = UNIT_ALIASES 键的最大字符数（= 4，如「平方公里」）。
_UNIT_MAX_LEN = max(len(k) for k in UNIT_ALIASES)

# §3.2 N3 尾部剥离字符集合（N2 之后串内空白只可能是单个半角空格）。
_TRAILING_STRIP = "。、,.;!? "

_N2_WS = re.compile(r"\s+")
_N4_THOUSANDS = re.compile(r"(?<=[0-9]),(?=[0-9]{3}(?![0-9]))")

# §3.3 模式（全文锚定，数字类一律 ASCII [0-9]）。
_MIXED_RE = re.compile(r"([+-]?)([0-9]+) ([0-9]+)\s*/\s*([0-9]+)")
_FRAC_RE = re.compile(r"([+-]?)([0-9]+)\s*/\s*([0-9]+)")
_DEC_RE = re.compile(r"[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?")


# ---------- §3.2 归一化规则表 N1–N5 ----------

def normalize_answer(text: str) -> str:
    if not isinstance(text, str):
        raise GradingError(
            f"normalize_answer 需要 str，得到 {type(text).__name__}")
    # N1 全角折叠：[0xFF01, 0xFF5E] → ASCII；U+3000 全角空格 → 半角空格。
    chars = []
    for ch in text:
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            chars.append(chr(code - 0xFEE0))
        elif ch == "　":  # U+3000
            chars.append(" ")
        else:
            chars.append(ch)
    s = "".join(chars)
    # N2 空白折叠：内部空白串折叠为单个半角空格，再去首尾空白。
    s = _N2_WS.sub(" ", s).strip()
    # N3 尾部剥离：只剥尾部，不动内部。
    s = s.rstrip(_TRAILING_STRIP)
    # N4 千分位逗号删除：左侧是 ASCII 数字、右侧恰为 3 位 ASCII 数字。
    s = _N4_THOUSANDS.sub("", s)
    # N5 小写化。
    return s.lower()


# ---------- §3.3 parse_numeric ----------

def _parse_plain(text: str):
    """§3.3 步骤 2–4：带分数 → 分数 → 小数（不含百分数处理），全文锚定。"""
    m = _MIXED_RE.fullmatch(text)
    if m is not None:
        # 带分数：sign 只取整数部的符号、作用于整体：sign · (|a| + b/c)。
        sign = -1.0 if m.group(1) == "-" else 1.0
        whole = abs(int(m.group(2)))
        num = int(m.group(3))
        den = int(m.group(4))
        if den == 0:
            return None
        return sign * (whole + num / den)
    m = _FRAC_RE.fullmatch(text)
    if m is not None:
        sign = -1 if m.group(1) == "-" else 1
        num = int(m.group(2))
        den = int(m.group(3))
        if den == 0:
            return None
        return sign * num / den
    if _DEC_RE.fullmatch(text) is not None:
        # 按 IEEE 754 浮点字面量解析（"nan"/"inf" 不匹配文法）。
        return float(text)
    return None


def parse_numeric(text: str) -> float | None:
    if not isinstance(text, str):
        raise GradingError(
            f"parse_numeric 需要 str，得到 {type(text).__name__}")
    # 步骤 1 百分数：剥掉结尾的一个 '%'，余部 strip 后按步骤 2–4 解析，值 / 100。
    if text.endswith("%"):
        value = _parse_plain(text[:-1].strip())
        if value is None:
            return None
        return value / 100.0
    return _parse_plain(text)


# ---------- §3.4 split_unit / §3.5 numeric_equal ----------

def split_unit(text: str) -> tuple[str, str | None]:
    if not isinstance(text, str):
        raise GradingError(
            f"split_unit 需要 str，得到 {type(text).__name__}")
    # 最长后缀优先：对宽度 w = min(len(text), L), …, 1 依次取后缀。
    for w in range(min(len(text), _UNIT_MAX_LEN), 0, -1):
        suffix = text[-w:]
        canon = UNIT_ALIASES.get(suffix)
        if canon is None:
            continue
        rest = text[:-w].strip()
        if rest:
            return (rest, canon)
        # 纯单位词命中即返回原文，不回退更短后缀（如「小时」→ ("小时", None)）。
        return (text, None)
    return (text, None)


def numeric_equal(a: float, b: float) -> bool:
    return abs(a - b) <= GRADE_TOLERANCE * max(1.0, abs(a), abs(b))


# ---------- §3.6 字符串等值键（仅用于 fill 字面支与 choice 全文趟） ----------

def _key(s: str) -> str:
    return _N2_WS.sub("", normalize_answer(s))


# ---------- §3.8 resolve：两趟全局扫描 ----------

def _resolve(t: str, labels: list[str], texts: list[str]) -> int | None:
    # 第一趟（标签）：直接相等（键形态不适用），取最小下标；命中即止。
    for i, label in enumerate(labels):
        if t == label:
            return i
    # 第二趟（全文）：键形态相等，取最小下标。
    kt = _key(t)
    for i, text in enumerate(texts):
        if kt == _key(text):
            return i
    return None


# ---------- §3.7 grade_fill ----------

def grade_fill(item, learner_answer) -> bool:
    # 步骤 1：类型与未作答——未作答短路先于一切题目侧校验。
    if learner_answer is not None and not isinstance(learner_answer, str):
        raise GradingError(
            f"learner_answer 需要 str 或 None，得到 {type(learner_answer).__name__}")
    if learner_answer is None:
        return False
    # 步骤 2：answer 归一（answer 非 str 在此抛错，即使 learner 是空白串）。
    ca = normalize_answer(item.answer)
    # 步骤 3：learner 归一；空白作答在 answer 归一之后判 False。
    la = normalize_answer(learner_answer)
    if la == "":
        return False
    # 步骤 4：拆单位。
    ca_num, ca_unit = split_unit(ca)
    la_num, la_unit = split_unit(la)
    # 步骤 5：单位门——缺单位、异单位判错（别名已在归一中对齐到同一规范单位）。
    if ca_unit != la_unit:
        return False
    # 步骤 6：数值支优先，否则字面等值支（键形态）。
    ca_val = parse_numeric(ca_num)
    la_val = parse_numeric(la_num)
    if ca_val is not None and la_val is not None:
        return numeric_equal(ca_val, la_val)
    return _key(ca_num) == _key(la_num)


# ---------- §3.8 grade_choice ----------

def grade_choice(item, learner_answer) -> bool:
    # 步骤 1：类型与未作答——未作答短路优先于题目校验。
    if learner_answer is not None and not isinstance(learner_answer, str):
        raise GradingError(
            f"learner_answer 需要 str 或 None，得到 {type(learner_answer).__name__}")
    if learner_answer is None:
        return False
    # 步骤 2：选项归一（选项含非 str 在此抛错），再取标签。
    texts = [normalize_answer(o) for o in item.options]
    labels = [t.split(".", 1)[0].strip() for t in texts]
    # 步骤 3：learner 归一；空白短路在选项归一之后、正确项解析之前。
    la = normalize_answer(learner_answer)
    if la == "":
        return False
    # 步骤 4：解析正确项——解析不了任何选项（含 options 空）即题目非法。
    correct = _resolve(normalize_answer(item.answer), labels, texts)
    if correct is None:
        raise GradingError(f"choice 题答案无法解析到任何选项: {item.id}")
    # 步骤 5：解析学习者项——写了不存在的内容判 False。
    given = _resolve(la, labels, texts)
    if given is None:
        return False
    # 步骤 6：判分。
    return given == correct


# ---------- §3.9 grade / grade_to_response ----------

def grade(item, learner_answer) -> bool:
    # 分派先于未作答短路：item_type 非法时即使 learner_answer 为 None 也抛错。
    item_type = item.item_type
    if item_type == "choice":
        return grade_choice(item, learner_answer)
    if item_type == "fill" or item_type == "solve":
        return grade_fill(item, learner_answer)
    raise GradingError(f"未知 item_type: {item_type!r}")


def grade_to_response(item, learner_answer, response_ms: int | None = None) -> Response:
    return Response(
        item_id=item.id,
        correct=grade(item, learner_answer),
        learner_answer=learner_answer,
        response_ms=response_ms,
    )
