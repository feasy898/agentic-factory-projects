"""asr_answer —— 口述作答（BACKLOG P3「asr_answer 口述作答」）的确定性内核。

行为契约（specs/drafts/asr_answer.spec.md，本文件为参考实现）：

- 管线：学生语音（音频字节）-> 注入的 ASR 客户端（mm_client.MMClient 满足其表面）
  恰好一次转写 -> 确定性口语答案抽取（清洗规则表 + 口语数字文法）-> 注入的判分器
  （grading.grade_to_response 满足其表面）产出作答结果。
- 抽取不偷看题目：extract_answer/clean_transcript/spoken_to_math 都只吃转写文本，
  与 item 无关——不会用标答反推答案（诚实性）。
- 抽取不出答案时（空白转写/纯语气词）交 grader(item, None)，与 mm_ingest 空白语义
  一致：不伪造作答。
- 模块间零 import：client 与 grader 都是注入鸭子参数，与 mm_client/grading 的一致性
  由契约测试在测试内 import 对方模块跨模块锁定。

全模块纯函数：无 IO、无随机、无时钟、不读环境，同输入同输出（出网只发生在注入的
client.asr 恰好一次调用上）。
"""
# 注意：不用 `from __future__ import annotations`——重生成注入装载（XX_IMPL_DIR）
# 约定见 tts_reader/mm_ingest 同款注释。
import re

__all__ = [
    "ASRError",
    "ASR_VERSION",
    "DEFAULT_FILENAME",
    "EDGE_CHARS",
    "HEAD_FILLERS",
    "SPOKEN_OPERATORS",
    "clean_transcript",
    "spoken_to_math",
    "extract_answer",
    "asr_answer",
]


class ASRError(ValueError):
    """asr_answer 模块所有校验失败的异常类型（ValueError 直接子类）。"""


# ---- 冻结常量（specs/drafts/asr_answer.spec.md §3）----

ASR_VERSION = "1"

# 转写文件名透传缺省值（与 mm_client.MMClient.asr 的 filename 缺省一致，跨模块锁定）
DEFAULT_FILENAME = "audio.wav"

# 上下缘可剥离字符：引号/标点/语气词（fold 全角->半角之后的形态；集合语义，只做
# 成员判断）。语气词两头都剥——口语转写的「嗯」「吧」不承载答案信息。
_EDGE_CHAR_SOURCE = "\"'“”‘’。，、…·.,;:!?()嗯呃唉哦噢喔吧了呢啦咯嘛呀哈啊"
EDGE_CHARS = frozenset(_EDGE_CHAR_SOURCE)

# 句首引导语词表（按长度降序，循环剥离直到不动点）：
# 「答案是」「我选的是」「等于」……注意只在头部剥离——「x等于3」的「等于」不在头部，
# 方程式作答不被破坏。
HEAD_FILLERS = (
    "我认为答案是", "我觉得答案是", "我的答案是", "所以答案是",
    "我选的是", "答案等于", "答案是", "选的是",
    "答案", "选择", "所以", "我选", "等于", "就是",
    "答", "得", "选",
)

# 口语算符 -> 数学符号（前缀最长优先；「三除五」传统歧义大，「除」单词不入表）
SPOKEN_OPERATORS = (
    ("等于", "="), ("乘以", "*"), ("除以", "/"),
    ("乘", "*"), ("加", "+"), ("减", "-"),
)

# 口语数字文法（冻结）：
_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}
_CN_BIG = {"万": 10000, "亿": 100000000}
_ASCII_DIGITS = "0123456789"
_NEG_MARK = "负"
_POINT_MARK = "点"
_MIXED_MARK = "又"
_PERCENT_MARK = "百分之"
_FRAC_MARK = "分之"

_FULLWIDTH_FOLD_RE = None  # 占位说明：fold 与 grading N1 同闭式，手写循环实现（见 _fold）


# ---------- 全角折叠（与 grading.normalize_answer 的 N1 同闭式） ----------

def _fold(text: str) -> str:
    folded = []
    for ch in text:
        cp = ord(ch)
        if 0xFF01 <= cp <= 0xFF5E:
            folded.append(chr(cp - 0xFEE0))
        elif cp == 0x3000:
            folded.append(" ")
        else:
            folded.append(ch)
    return "".join(folded)


# ---------- §3.x clean_transcript：折叠 + 上下缘剥离 + 句首引导语剥离 ----------

def _strip_edges(s: str) -> str:
    start = 0
    end = len(s)
    while start < end and s[start] in EDGE_CHARS:
        start += 1
    while end > start and s[end - 1] in EDGE_CHARS:
        end -= 1
    return s[start:end]


def clean_transcript(text) -> str:
    """ASR 转写文本 -> 清洗后的口语串（非 str -> ASRError）。

    冻结流程：全角折叠（grading N1 同闭式）-> 首尾空白剥离 -> 循环到不动点：
    剥上下缘字符（引号/标点/语气词）-> 剥一个句首引导语（HEAD_FILLERS 按序首个
    前缀命中）-> 再剥上下缘。只在头部剥引导语、只在边缘剥标点——「x等于3」
    「-2」等核心内容不被触碰。
    """
    if not isinstance(text, str):
        raise ASRError(f"transcript must be str, got {type(text).__name__}")
    s = _fold(text).strip()
    while True:
        before = s
        s = _strip_edges(s)
        for filler in HEAD_FILLERS:
            if s.startswith(filler):
                s = s[len(filler):]
                break
        s = _strip_edges(s)
        if s == before:
            return s


# ---------- §3.x 口语数字文法 ----------

def _int_prefix(s: str, i: int):
    """从 s[i:] 解析最大中文/ASCII 整数前缀 -> (值, 结束下标)；无数字消费 -> None。

    文法（冻结）：数字串（零〇一二两三四五六七八九 + ASCII）按位累积；十/百/千为段内
    单位（缺系数按 1：「十二」=12、「十」=10）；万/亿为大段单位（必须有非零前值）；
    零作占位。显式单位文法：「一百五」=105（不是口语约算的 150）。
    """
    total = section = pending = 0
    seen = False
    j, n = i, len(s)
    while j < n:
        ch = s[j]
        if ch in _CN_DIGITS:
            pending = pending * 10 + _CN_DIGITS[ch]
            seen = True
            j += 1
        elif ch in _ASCII_DIGITS:
            pending = pending * 10 + (ord(ch) - 48)
            seen = True
            j += 1
        elif ch in _CN_UNITS:
            section += (pending if pending else 1) * _CN_UNITS[ch]
            pending = 0
            seen = True
            j += 1
        elif ch in _CN_BIG:
            if section + pending == 0:
                break  # 孤立「万/亿」不是数，交给逐字符透传
            total += (section + pending) * _CN_BIG[ch]
            section = pending = 0
            seen = True
            j += 1
        else:
            break
    if not seen:
        return None
    return (total + section + pending, j)


def _decimal_prefix(s: str, i: int):
    """整数前缀 + 可选「点」逐位小数 -> ("串形式", 结束下标)；无整数 -> None。"""
    head = _int_prefix(s, i)
    if head is None:
        return None
    value, j = head
    if j < len(s) and s[j] == _POINT_MARK:
        k = j + 1
        frac = []
        while k < len(s):
            ch = s[k]
            if ch in _CN_DIGITS:
                frac.append(str(_CN_DIGITS[ch]))
                k += 1
            elif ch in _ASCII_DIGITS:
                frac.append(ch)
                k += 1
            else:
                break
        if frac:
            return (f"{value}.{''.join(frac)}", k)
    return (str(value), j)


def _fraction_prefix(s: str, i: int):
    """「den分之num」-> ("num/den", 结束下标)；den 整数、num 可带小数。"""
    den = _int_prefix(s, i)
    if den is None:
        return None
    j = den[1]
    if not s.startswith(_FRAC_MARK, j):
        return None
    num = _decimal_prefix(s, j + len(_FRAC_MARK))
    if num is None:
        return None
    return (f"{num[0]}/{den[0]}", num[1])


def _number_core(s: str, i: int):
    """不带负号的数表达式，按冻结优先级：百分之 -> 带分数 -> 分数 -> 整数/小数。"""
    if s.startswith(_PERCENT_MARK, i):
        inner = _decimal_prefix(s, i + len(_PERCENT_MARK))
        if inner is not None:
            return (inner[0] + "%", inner[1])
    head = _int_prefix(s, i)
    if head is not None and head[1] < len(s) and s[head[1]] == _MIXED_MARK:
        frac = _fraction_prefix(s, head[1] + len(_MIXED_MARK))
        if frac is not None:
            return (f"{head[0]} {frac[0]}", frac[1])
    frac = _fraction_prefix(s, i)
    if frac is not None:
        return frac
    return _decimal_prefix(s, i)


def _number(s: str, i: int):
    """数表达式（「负」恰修饰一次）：负 X -> -X。"""
    if s.startswith(_NEG_MARK, i):
        inner = _number_core(s, i + 1)
        if inner is not None:
            return ("-" + inner[0], inner[1])
        return None
    return _number_core(s, i)


def spoken_to_math(text) -> str:
    """口语串 -> 数学记号串（非 str -> ASRError）。

    逐位置扫描，按冻结优先级：数表达式（负/百分之/带分数/分数/小数/整数，最大
    匹配）-> 口语算符（SPOKEN_OPERATORS 前缀最长优先）-> 其余字符原样透传。
    单位词（厘米/升/元……）与未知文本不转换，交给判分器的单位门/字面支。
    不做表达式求值：「三加五」->「3+5」而不是 8。
    """
    if not isinstance(text, str):
        raise ASRError(f"text must be str, got {type(text).__name__}")
    out = []
    i, n = 0, len(text)
    while i < n:
        hit = _number(text, i)
        if hit is not None:
            out.append(hit[0])
            i = hit[1]
            continue
        for word, sym in SPOKEN_OPERATORS:
            if text.startswith(word, i):
                out.append(sym)
                i += len(word)
                break
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


# ---------- §3.x extract_answer：转写 -> 候选答案（不出答案则 None） ----------

def extract_answer(text) -> "str | None":
    """ASR 转写文本 -> 候选答案串；清洗后为空 -> None（无作答证据，不伪造）。

    冻结流程：clean_transcript（折叠/上下缘/句首引导语）-> spoken_to_math
    （口语数字/算符 -> 数学记号）-> 首尾空白剥离 -> 空则 None。
    只依赖转写文本，与题目无关（不偷看标答）。
    """
    if not isinstance(text, str):
        raise ASRError(f"transcript must be str, got {type(text).__name__}")
    cleaned = spoken_to_math(clean_transcript(text)).strip()
    return cleaned or None


# ---------- §3.x 管线入口 ----------

def asr_answer(audio, item, client, grader, *, filename=DEFAULT_FILENAME):
    """口述作答管线：audio -> 恰好一次 client.asr -> extract_answer -> grader(item, 答案)。

    守卫顺序冻结（任一失败抛 ASRError 且零次 client 调用）：
    V1 client 有 callable asr 属性 -> V2 grader callable -> V3 audio 非空 bytes
    -> V4 filename 非空 str。随后恰好一次 client.asr(audio, filename=filename)
    （mm_client.MMClient.asr 满足该表面）；回写非 str -> ASRError；转写空白/
    纯语气词 -> grader(item, None)（不伪造作答，与 mm_ingest 空白语义一致）。
    client 异常原样传播；返回值即 grader 返回值（grading.grade_to_response 满足
    时为 Response）。
    """
    asr_fn = getattr(client, "asr", None)          # V1
    if not callable(asr_fn):
        raise ASRError("client must provide a callable asr()")
    if not callable(grader):                        # V2
        raise ASRError("grader must be callable")
    if not isinstance(audio, bytes) or not audio:   # V3
        raise ASRError(f"audio must be non-empty bytes, got {type(audio).__name__}")
    if not isinstance(filename, str) or not filename.strip():  # V4
        raise ASRError("filename must be a non-blank str")
    transcript = asr_fn(audio, filename=filename)   # 恰好一次出网（唯一注入口）
    if not isinstance(transcript, str):
        raise ASRError(
            f"asr transcript must be str, got {type(transcript).__name__}")
    return grader(item, extract_answer(transcript))
