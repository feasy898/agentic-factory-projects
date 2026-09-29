"""grading —— 主观题判分接口（数值归一化比对 + choice 自动判）。

在此之前 Response.correct 只能由教师/批改端外部给定；本模块把 fill/solve 的
数值答案（分数/带分数/百分数/小数，可带单位）按规则表归一化后按值比对，
choice 按选项标签/全文自动判，并经 grade_to_response 直接产出 Response。

行为契约（specs/drafts/grading.spec.md，本文件为参考实现）：
- 归一化规则表 N1–N5：全角折叠 → 空白折叠 → 尾部标点剥离 → 千分位逗号删除
  （只删"数字后恰跟 3 位数字"的逗号，坐标 (4,1) 不受伤）→ 小写化；
- 数值等价：分数/带分数/百分数/小数在相对容差 1e-9 下按值判等；
- 单位门：题目答案与学习者答案的单位（别名归一后）必须一致，缺单位/异单位
  判错；只做别名归一，不做换算（2千米 ≠ 2米）；
- 判分确定性：全模块纯函数，无随机、无时钟、无 IO，同输入同输出。
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
    """grading 模块所有校验失败的异常类型（ValueError 直接子类）。"""


# ---- 冻结常量（specs/drafts/grading.spec.md §3.1 / §3.5）----

GRADE_TOLERANCE = 1e-9  # numeric_equal 的相对容差（零附近退化为绝对带 1e-9）

# 单位别名表：键 = 表层写法（含规范形自身），值 = 规范单位；值必须也是键（闭包）。
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

# N1：全角折叠范围与偏移（[0xFF01, 0xFF5E] -> ASCII），U+3000 -> 半角空格
_FW_LO, _FW_HI, _FW_OFFSET = 0xFF01, 0xFF5E, 0xFEE0
# N3：尾部可剥字符（全角 ，！？；已由 N1 折叠为 ASCII，。、不在折叠范围）
_TRAILING_CHARS = "。，、;,.!?" + " \t\r\n\v\f"
# N4：千分位逗号 = 数字后且恰跟 3 位数字（第 4 位仍是数字则不算）
_THOUSANDS_RE = re.compile(r"(?<=[0-9]),(?=[0-9]{3}(?![0-9]))")
_WS_RE = re.compile(r"\s+")

# 数值文法（§3.3；[0-9] 显式限定，杜绝 unicode 数字/inf/nan）
_DECIMAL_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
_FRACTION_RE = re.compile(r"([+-]?[0-9]+)\s*/\s*([0-9]+)\Z")
_MIXED_RE = re.compile(r"([+-]?[0-9]+) ([0-9]+)\s*/\s*([0-9]+)\Z")


def normalize_answer(text: str) -> str:
    """归一化规则表 N1–N5（按序执行，见规格 §3.2）。非 str 抛 GradingError。"""
    if not isinstance(text, str):
        raise GradingError(f"normalize_answer expects str, got {type(text).__name__}")
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


def parse_numeric(text: str):
    """解析已归一化的数值文本（规格 §3.3）；不可解析返回 None。非 str 抛错。"""
    if not isinstance(text, str):
        raise GradingError(f"parse_numeric expects str, got {type(text).__name__}")
    percent = text.endswith("%")
    t = text[:-1].strip() if percent else text
    m = _MIXED_RE.match(t)  # 带分数 a b/c（b 前恰一个空格；/ 两侧容空白）
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


def split_unit(text: str):
    """从尾部剥单位（规格 §3.4）：最长后缀优先；纯单位词/无命中返回 (原文, None)。

    本函数不做任何归一化——先 normalize_answer 再调用。
    """
    if not isinstance(text, str):
        raise GradingError(f"split_unit expects str, got {type(text).__name__}")
    for width in range(min(len(text), _MAX_UNIT_LEN), 0, -1):
        suffix = text[-width:]
        if suffix in UNIT_ALIASES:
            rest = text[:-width].strip()
            if rest:
                return rest, UNIT_ALIASES[suffix]
            break  # 命中的是纯单位词（无数值部）→ 不算"数值+单位"
    return text, None


def numeric_equal(a: float, b: float) -> bool:
    """相对容差判等：|a−b| <= 1e-9 * max(1, |a|, |b|)（规格 §3.5）。"""
    return abs(a - b) <= GRADE_TOLERANCE * max(1.0, abs(a), abs(b))


def _key(s: str) -> str:
    """字符串等值键：归一化后删除全部空白（规格 §3.6）。"""
    return _WS_RE.sub("", s)


def grade_fill(item, learner_answer: object) -> bool:
    """fill/solve 判分（规格 §3.7）：归一化 → 单位门 → 数值/字面等值。"""
    if learner_answer is not None and not isinstance(learner_answer, str):
        raise GradingError(
            f"learner_answer must be str or None, got {type(learner_answer).__name__}")
    if learner_answer is None:
        return False
    canonical = normalize_answer(item.answer)
    learner = normalize_answer(learner_answer)
    if learner == "":
        return False
    ca_num, ca_unit = split_unit(canonical)
    la_num, la_unit = split_unit(learner)
    if ca_unit != la_unit:  # 单位门：缺单位/异单位判错；None==None 通过
        return False
    ca_val = parse_numeric(ca_num)
    la_val = parse_numeric(la_num)
    if ca_val is not None and la_val is not None:
        return numeric_equal(ca_val, la_val)
    return _key(ca_num) == _key(la_num)  # 字面支：两元 / x+1 / (4,1) / 鸡6只…


def _resolve_option(target: str, labels: list, texts: list):
    """标签优先（options 顺序第一个），其后全文 key 比较；不命中返回 None。"""
    if target in labels:
        return labels.index(target)
    target_key = _key(target)
    for i, t in enumerate(texts):
        if _key(t) == target_key:
            return i
    return None


def grade_choice(item, learner_answer: object) -> bool:
    """choice 自动判（规格 §3.8）：标签/全文解析，标签优先；非法题抛错。"""
    if learner_answer is not None and not isinstance(learner_answer, str):
        raise GradingError(
            f"learner_answer must be str or None, got {type(learner_answer).__name__}")
    if learner_answer is None:  # 未作答短路，优先于题目校验
        return False
    texts = [normalize_answer(o) for o in item.options]
    labels = [t.split(".", 1)[0].strip() for t in texts]
    learner = normalize_answer(learner_answer)
    if learner == "":
        return False
    correct = _resolve_option(normalize_answer(item.answer), labels, texts)
    if correct is None:
        raise GradingError(f"item {item.id!r}: answer not among options")
    given = _resolve_option(learner, labels, texts)
    if given is None:
        return False
    return given == correct


def grade(item, learner_answer: object) -> bool:
    """按 item_type 分派（规格 §3.9）：choice→grade_choice；fill/solve→grade_fill。"""
    t = item.item_type
    if t == "choice":
        return grade_choice(item, learner_answer)
    if t in ("fill", "solve"):
        return grade_fill(item, learner_answer)
    raise GradingError(f"unsupported item_type: {t!r}")


def grade_to_response(item, learner_answer: object,
                      response_ms: int | None = None) -> Response:
    """判分并产出 Response（规格 §3.9）：字段原样透传。"""
    return Response(
        item_id=item.id,
        correct=grade(item, learner_answer),
        learner_answer=learner_answer,
        response_ms=response_ms,
    )
